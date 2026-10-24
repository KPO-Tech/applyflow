"""Connecteur ATS publics via la bibliothèque `ats-scrapers` (extra `boards`).

Chaque entreprise est lue sur l'API publique de son ATS (lecture seule, sans connexion), puis les
offres sont filtrées par mots-clés et localisation. Seuls les ATS dont l'API répond à un client
HTTP ordinaire sont autorisés : ceux qui exigent une usurpation TLS ou un navigateur furtif sont
écartés.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from applyflow.logging_setup import get_logger
from applyflow.providers.base import (
    Controllable,
    ProviderCapabilities,
    ProviderError,
    apply_query_filters,
    location_matches,
)
from applyflow.providers.json_import import normalized_from_mapping
from applyflow.schemas import JobQuery, NormalizedJob

logger = get_logger("ats")

ALLOWED_ATS = (
    "greenhouse", "lever", "ashby", "smartrecruiters", "workday", "successfactors",
    "workable", "recruitee", "personio", "teamtailor",
)
CONTRACTS = {"FULL_TIME": "CDI", "PART_TIME": "Temps partiel", "CONTRACT": "CDD / contrat",
             "INTERN": "Stage", "TEMPORARY": "Intérim"}


def _default_make_scraper(ats: str, slug: str, timeout: float) -> Any:
    try:
        from ats_scrapers.scrapers import get_scraper
    except ImportError as exc:
        raise ProviderError("ats-scrapers n'est pas installé : `uv sync --extra boards`.") from exc
    return get_scraper(ats, slug, timeout=timeout)


def parse_company(entry: str | dict[str, Any]) -> tuple[str, str]:
    """Accepte `"greenhouse:datadog"` ou `{"ats": "greenhouse", "slug": "datadog"}`."""
    if isinstance(entry, dict):
        ats, slug = str(entry.get("ats") or ""), str(entry.get("slug") or "")
    else:
        ats, _, slug = str(entry).partition(":")
    ats, slug = ats.strip().lower(), slug.strip()
    if ats not in ALLOWED_ATS:
        raise ProviderError(f"ATS non pris en charge : {ats!r}. Disponibles : {', '.join(ALLOWED_ATS)}.")
    if not slug:
        raise ProviderError(f"identifiant d'entreprise manquant pour {ats}.")
    return ats, slug


class AtsProvider(Controllable):
    kind = "ats"
    capabilities = ProviderCapabilities(
        kind=kind,
        label="ATS publics (Greenhouse, Lever, Ashby, SmartRecruiters, Workday…)",
        supports_search=True,
        supports_auto_apply=False,
        terms_url="https://github.com/kalil0321/ats-scrapers",
        notes=(
            "API publiques de lecture des pages carrières, entreprise par entreprise. "
            "Aucune connexion, aucun contournement ; soumission manuelle."
        ),
        config_fields=("companies", "concurrency"),
    )

    def __init__(
        self,
        *,
        companies: list[str | dict[str, Any]] | None = None,
        concurrency: int = 4,
        timeout_seconds: float = 30.0,
        source_name: str = "ATS",
        make_scraper: Callable[[str, str, float], Any] | None = None,
        **_: Any,
    ) -> None:
        self.companies = [parse_company(entry) for entry in (companies or [])]
        self.concurrency = max(1, min(int(concurrency), 16))
        self.timeout_seconds = timeout_seconds
        self.source_name = source_name
        self._make_scraper = make_scraper or _default_make_scraper
        #: statistiques de la dernière collecte, par entreprise (`ats:slug`)
        self.last_stats: dict[str, dict[str, Any]] = {}

    def fetch(self, query: JobQuery) -> list[NormalizedJob]:
        if not self.companies:
            raise ProviderError(
                "aucune entreprise configurée : indiquez `companies`, par exemple "
                '["greenhouse:datadog", "lever:qonto"].'
            )
        self.last_stats = {}
        with ThreadPoolExecutor(max_workers=1) as pool:  # boucle asyncio isolée du serveur web
            raw = pool.submit(lambda: asyncio.run(self._collect())).result()
        jobs: list[NormalizedJob] = []
        for (ats, slug), items in raw:
            key = f"{ats}:{slug}"
            self.last_stats[key]["total"] = len(items)
            # Pré-filtre exact sur la localisation (texte brut) avant la normalisation, qui est la
            # partie coûteuse : même règle que `apply_query_filters`, aucune offre valide perdue.
            candidates = [
                item for item in items
                if location_matches(
                    getattr(item, "location", None), query.locations,
                    country=getattr(item, "country_iso", None),
                )
            ]
            self._report(len(self.companies), len(self.companies), f"Analyse · {key}", len(jobs))
            normalized: list[NormalizedJob] = []
            for item in candidates:
                try:
                    normalized.append(self._normalize(ats, item))
                except (ProviderError, ValueError) as exc:
                    self.last_stats[key]["errors"].append(str(exc))
            kept = apply_query_filters(normalized, query.model_copy(update={"limit": 10**6}))
            self.last_stats[key]["jobs"] = len(kept)
            jobs.extend(kept)
        if not jobs and not self._cancelled() and all(s["errors"] for s in self.last_stats.values()):
            raise ProviderError(
                "aucune entreprise ATS n'a répondu : "
                + " ; ".join(f"{k}: {s['errors'][0]}" for k, s in self.last_stats.items())
            )
        return jobs[: query.limit]

    async def _collect(self) -> list[tuple[tuple[str, str], list[Any]]]:
        semaphore = asyncio.Semaphore(self.concurrency)
        total = len(self.companies)
        finished = {"done": 0, "jobs": 0}

        async def one(ats: str, slug: str) -> tuple[tuple[str, str], list[Any]]:
            key = f"{ats}:{slug}"
            self.last_stats[key] = {"jobs": 0, "total": 0, "errors": [], "seconds": 0.0}
            started = time.monotonic()
            async with semaphore:
                if self._cancelled():  # annulation : les entreprises non démarrées sont ignorées
                    self.last_stats[key]["errors"].append("annulé")
                    return (ats, slug), []
                self._report(finished["done"], total, key, finished["jobs"])
                try:
                    scraper = self._make_scraper(ats, slug, self.timeout_seconds)
                    items = await scraper.afetch()
                except Exception as exc:  # une entreprise en échec ne bloque pas les autres
                    self.last_stats[key]["errors"].append(str(exc) or type(exc).__name__)
                    logger.warning("échec ATS", extra={"data": {"company": key, "error": str(exc)}})
                    items = []
            self.last_stats[key]["seconds"] = round(time.monotonic() - started, 2)
            finished["done"] += 1
            finished["jobs"] += len(items)
            self._report(finished["done"], total, key, finished["jobs"])
            return (ats, slug), items

        return list(await asyncio.gather(*(one(a, s) for a, s in self.companies)))

    def _normalize(self, ats: str, job: Any) -> NormalizedJob:
        employment = getattr(job.employment_type, "value", job.employment_type)
        data = {
            "external_id": f"{ats}:{job.ats_id or job.global_id}",
            "url": str(job.url),
            "apply_url": str(job.apply_url) if job.apply_url else str(job.url),
            "company": job.company,
            "title": job.title,
            "description": job.description or "",
            "location": job.location,
            "country": getattr(job, "country_iso", None),
            "contract_type": CONTRACTS.get(str(employment)) if employment else None,
            "salary_min": int(job.salary_min) if job.salary_min else None,
            "salary_max": int(job.salary_max) if job.salary_max else None,
            "salary_currency": job.salary_currency,
            "published_at": job.posted_at.isoformat() if job.posted_at else None,
            "raw": {"ats": ats, "department": job.department, "language": job.language},
        }
        result = normalized_from_mapping(
            data, source_kind=self.kind, source_name=f"{self.source_name}:{ats}"
        )
        if job.is_remote is True and result.remote in (None, "unspecified"):
            result = result.model_copy(update={"remote": "remote"})
        return result
