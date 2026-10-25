"""Connecteur Adzuna : API officielle, en lecture seule, avec une clé gratuite."""

from __future__ import annotations

import math
import time
from collections.abc import Callable
from typing import Any

import httpx

from applyflow.geo import detect_country, normalize_country
from applyflow.providers.base import ProviderCapabilities, ProviderError
from applyflow.providers.json_import import normalized_from_mapping
from applyflow.providers.resilience import Pacer, RetryPolicy, request_with_retry
from applyflow.schemas import JobQuery, NormalizedJob

USER_AGENT = "ApplyFlow/0.1 (local job application assistant)"
MAX_PAGE_SIZE = 50

# Pays de l'API Adzuna et leur devise. Un pays absent de cette liste n'est pas interrogé.
ADZUNA_COUNTRIES = {
    "at": "EUR", "au": "AUD", "be": "EUR", "br": "BRL", "ca": "CAD", "ch": "CHF", "de": "EUR",
    "es": "EUR", "fr": "EUR", "gb": "GBP", "in": "INR", "it": "EUR", "mx": "MXN", "nl": "EUR",
    "nz": "NZD", "pl": "PLN", "sg": "SGD", "us": "USD", "za": "ZAR",
}


class AdzunaProvider:
    """Recherche d'offres via `api.adzuna.com` (identifiants personnels)."""

    kind = "adzuna"
    capabilities = ProviderCapabilities(
        kind=kind,
        label="Adzuna (API officielle)",
        supports_search=True,
        supports_auto_apply=False,
        terms_url="https://developer.adzuna.com/docs/terms_of_service",
        notes=(
            "API officielle d'un agrégateur d'offres français. Une clé gratuite est requise "
            "(developer.adzuna.com). Aucun scraping, aucun contournement."
        ),
    )

    def __init__(
        self,
        app_id: str = "",
        app_key: str = "",
        *,
        country: str = "fr",
        max_pages: int = 5,
        base_url: str = "https://api.adzuna.com/v1/api/jobs",
        source_name: str = "Adzuna",
        transport: httpx.BaseTransport | None = None,
        timeout_seconds: float = 20.0,
        retry_attempts: int = 3,
        retry_base_seconds: float = 1.0,
        retry_max_seconds: float = 20.0,
        request_interval_seconds: float = 0.35,
        sleep: Callable[[float], None] = time.sleep,
        **_: Any,
    ) -> None:
        self.app_id = (app_id or "").strip()
        self.app_key = (app_key or "").strip()
        self.country = (country or "fr").strip().lower()
        self.max_pages = max(1, min(int(max_pages), 20))
        self.base_url = base_url.rstrip("/")
        self.source_name = source_name
        self._transport = transport
        self.timeout_seconds = timeout_seconds
        # Une page Adzuna toutes les 350 ms au minimum, avec repli sur erreur passagère.
        self.retry = RetryPolicy(
            attempts=retry_attempts,
            base_seconds=retry_base_seconds,
            max_seconds=retry_max_seconds,
        )
        self.pacer = Pacer(request_interval_seconds, sleep=sleep)
        self.sleep = sleep
        self.last_count = 0
        #: statistiques de la dernière collecte, par pays
        self.last_stats: dict[str, dict[str, Any]] = {}

    def _client(self) -> httpx.Client:
        return httpx.Client(
            timeout=self.timeout_seconds,
            follow_redirects=True,
            headers={"User-Agent": USER_AGENT},
            transport=self._transport,
        )

    def fetch(self, query: JobQuery) -> list[NormalizedJob]:
        if not self.app_id or not self.app_key:
            raise ProviderError(
                "Adzuna n'est pas configuré : ajoutez app_id et app_key dans "
                "Réglages → Collecte (clé gratuite sur developer.adzuna.com)."
            )
        if not query.keywords and not query.locations:
            raise ProviderError("indiquez au moins un mot-clé ou une localisation pour Adzuna.")

        targets = self._targets(query)
        if not targets:
            raise ProviderError(
                "Adzuna ne couvre aucun des pays demandés. Pays pris en charge : "
                + ", ".join(sorted(code.upper() for code in ADZUNA_COUNTRIES))
                + "."
            )
        per_target = max(1, math.ceil(query.limit / len(targets)))
        jobs: list[NormalizedJob] = []
        self.last_stats = {}
        failures: list[str] = []
        try:
            with self._client() as client:
                for country, where in targets:
                    key = country.upper() + (f" · {where}" if where else "")
                    stats = self.last_stats[key] = {"jobs": 0, "errors": [], "seconds": 0.0}
                    started = time.monotonic()
                    try:
                        found = self._search(client, query, country, where, per_target)
                    except ProviderError:
                        raise
                    except httpx.HTTPStatusError as exc:
                        message = f"Adzuna {country.upper()} : HTTP {exc.response.status_code}"
                        stats["errors"].append(message)
                        failures.append(message)
                        found = []
                    stats["jobs"] = len(found)
                    stats["seconds"] = round(time.monotonic() - started, 2)
                    jobs.extend(found)
        except httpx.HTTPError as exc:
            raise ProviderError(f"Adzuna indisponible : {exc}") from exc
        except ValueError as exc:
            raise ProviderError("réponse Adzuna illisible (JSON attendu).") from exc
        if not jobs and failures and len(failures) == len(targets):
            raise ProviderError("; ".join(failures))
        return jobs[: query.limit]

    def _targets(self, query: JobQuery) -> list[tuple[str, str | None]]:
        """(pays Adzuna, lieu) à interroger : un pays demandé = une recherche dans ce pays."""
        if not query.locations:
            return [(self.country, None)]
        targets: list[tuple[str, str | None]] = []
        for location in query.locations:
            if not location.strip():
                continue
            iso = detect_country(location) or normalize_country(location)
            code = iso.lower() if iso else self.country
            if code not in ADZUNA_COUNTRIES:
                continue
            where = None if normalize_country(location) == iso else location
            target = (code, where)
            if target not in targets:
                targets.append(target)
        return targets

    def _search(
        self, client: httpx.Client, query: JobQuery, country: str, where: str | None, limit: int
    ) -> list[NormalizedJob]:
        found: list[NormalizedJob] = []
        remaining = limit
        page_size = min(MAX_PAGE_SIZE, max(1, remaining))
        pages = min(self.max_pages, max(1, math.ceil(remaining / page_size)))
        for page in range(1, pages + 1):
            params: dict[str, Any] = {
                "app_id": self.app_id,
                "app_key": self.app_key,
                "results_per_page": page_size,
                "content-type": "application/json",
            }
            if query.keywords:
                params["what"] = " ".join(query.keywords)
            if where:
                params["where"] = where
            try:
                response = request_with_retry(
                    client,
                    "GET",
                    f"{self.base_url}/{country}/search/{page}",
                    params=params,
                    policy=self.retry,
                    pacer=self.pacer,
                    sleep=self.sleep,
                )
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code in {401, 403}:
                    raise ProviderError(
                        "Adzuna a refusé la clé (app_id ou app_key invalide). "
                        "Vérifiez la clé dans Réglages → Collecte."
                    ) from exc
                raise
            payload = response.json()
            results = payload.get("results") or []
            self.last_count = int(payload.get("count") or 0)
            found.extend(
                self._normalize(item, country) for item in results if item.get("redirect_url")
            )
            remaining -= len(results)
            if len(results) < page_size or remaining <= 0:
                break
        return found

    def _normalize(self, item: dict[str, Any], country: str | None = None) -> NormalizedJob:
        country = (country or self.country).lower()
        company = (item.get("company") or {}).get("display_name") or "Entreprise confidentielle"
        location = (item.get("location") or {}).get("display_name")
        currency = ADZUNA_COUNTRIES.get(country, "EUR")
        return normalized_from_mapping(
            {
                "external_id": str(item.get("id") or ""),
                "url": item.get("redirect_url"),
                "apply_url": item.get("redirect_url"),
                "company": company,
                "title": item.get("title"),
                "description": item.get("description") or "",
                "location": location,
                "country": country,
                "contract_type": item.get("contract_type") or item.get("contract_time"),
                "salary_min": item.get("salary_min"),
                "salary_max": item.get("salary_max"),
                "salary_currency": item.get("salary_currency") or currency,
                "published_at": item.get("created"),
                "skills": [],
                "raw": item,
            },
            source_kind=self.kind,
            source_name=self.source_name,
        )
