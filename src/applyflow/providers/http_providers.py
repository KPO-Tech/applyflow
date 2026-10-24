"""Connecteurs HTTP en lecture seule : Greenhouse, Lever, RSS et import d'URL."""

from __future__ import annotations

import json
import time
from typing import Any

import feedparser
import httpx
from bs4 import BeautifulSoup

from applyflow.providers.base import ProviderCapabilities, ProviderError, apply_query_filters
from applyflow.providers.json_import import normalized_from_mapping
from applyflow.providers.normalize import (
    enrich_description,
    html_to_text,
    infer_contract,
    infer_remote,
    infer_salary,
    infer_seniority,
    parse_datetime,
)
from applyflow.schemas import JobQuery, NormalizedJob
from applyflow.text import slugify

USER_AGENT = "ApplyFlow/0.1 (local job application assistant)"


class _HttpProvider:
    timeout_seconds: float = 20.0

    def _client(self, transport: httpx.BaseTransport | None = None) -> httpx.Client:
        return httpx.Client(
            timeout=self.timeout_seconds,
            follow_redirects=True,
            headers={"User-Agent": USER_AGENT},
            transport=transport,
        )


class GreenhouseProvider(_HttpProvider):
    """API publique en lecture seule des job boards Greenhouse."""

    kind = "greenhouse"
    capabilities = ProviderCapabilities(
        kind=kind,
        label="Greenhouse (API publique du board)",
        supports_search=True,
        supports_auto_apply=False,
        terms_url="https://www.greenhouse.io/legal",
        notes=(
            "Lecture des offres publiées par une entreprise via boards-api.greenhouse.io. "
            "Aucune soumission automatisée : le formulaire Greenhouse doit être validé "
            "manuellement (préparation dry-run uniquement)."
        ),
        config_fields=("board_token", "base_url"),
    )

    def __init__(
        self,
        board_token: str,
        *,
        base_url: str = "https://boards-api.greenhouse.io/v1/boards",
        source_name: str = "Greenhouse",
        transport: httpx.BaseTransport | None = None,
        timeout_seconds: float = 20.0,
        **_: Any,
    ) -> None:
        if not board_token:
            raise ProviderError("board_token Greenhouse manquant")
        self.board_token = board_token
        self.base_url = base_url.rstrip("/")
        self.source_name = source_name
        self._transport = transport
        self.timeout_seconds = timeout_seconds

    def fetch(self, query: JobQuery) -> list[NormalizedJob]:
        url = f"{self.base_url}/{self.board_token}/jobs"
        try:
            with self._client(self._transport) as client:
                response = client.get(url, params={"content": "true"})
                response.raise_for_status()
                payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise ProviderError(f"Greenhouse indisponible : {exc}") from exc

        jobs: list[NormalizedJob] = []
        for item in payload.get("jobs", []):
            description = html_to_text(item.get("content"))
            location = (item.get("location") or {}).get("name")
            jobs.append(
                normalized_from_mapping(
                    {
                        "external_id": str(item.get("id")),
                        "url": item.get("absolute_url"),
                        "apply_url": item.get("absolute_url"),
                        "company": item.get("company_name") or self.board_token,
                        "title": item.get("title"),
                        "description": description,
                        "location": location,
                        "remote": infer_remote(location, description),
                        "published_at": item.get("updated_at") or item.get("first_published"),
                        "skills": enrich_description(description),
                    },
                    source_kind=self.kind,
                    source_name=self.source_name,
                )
            )
        return apply_query_filters(jobs, query)


class LeverProvider(_HttpProvider):
    """API publique en lecture seule des offres Lever."""

    kind = "lever"
    capabilities = ProviderCapabilities(
        kind=kind,
        label="Lever (API publique des postings)",
        supports_search=True,
        supports_auto_apply=False,
        terms_url="https://www.lever.co/terms",
        notes=(
            "Lecture des postings publiés via api.lever.co. "
            "Préparation locale uniquement, aucune soumission automatique."
        ),
        config_fields=("company", "base_url"),
    )

    def __init__(
        self,
        company: str,
        *,
        base_url: str = "https://api.lever.co/v0/postings",
        source_name: str = "Lever",
        transport: httpx.BaseTransport | None = None,
        timeout_seconds: float = 20.0,
        **_: Any,
    ) -> None:
        if not company:
            raise ProviderError("identifiant d'entreprise Lever manquant")
        self.company = company
        self.base_url = base_url.rstrip("/")
        self.source_name = source_name
        self._transport = transport
        self.timeout_seconds = timeout_seconds

    def fetch(self, query: JobQuery) -> list[NormalizedJob]:
        url = f"{self.base_url}/{self.company}"
        try:
            with self._client(self._transport) as client:
                response = client.get(url, params={"mode": "json"})
                response.raise_for_status()
                payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise ProviderError(f"Lever indisponible : {exc}") from exc
        if not isinstance(payload, list):
            raise ProviderError("réponse Lever inattendue")

        jobs: list[NormalizedJob] = []
        for item in payload:
            categories = item.get("categories") or {}
            description = item.get("descriptionPlain") or html_to_text(item.get("description"))
            location = categories.get("location")
            jobs.append(
                normalized_from_mapping(
                    {
                        "external_id": str(item.get("id")),
                        "url": item.get("hostedUrl"),
                        "apply_url": item.get("applyUrl") or item.get("hostedUrl"),
                        "company": self.company,
                        "title": item.get("text"),
                        "description": description,
                        "location": location,
                        "contract_type": categories.get("commitment"),
                        "remote": infer_remote(location, description),
                        "published_at": item.get("createdAt"),
                        "skills": enrich_description(description),
                    },
                    source_kind=self.kind,
                    source_name=self.source_name,
                )
            )
        return apply_query_filters(jobs, query)


class RssProvider(_HttpProvider):
    """Flux RSS/Atom d'offres autorisés explicitement par l'utilisateur."""

    kind = "rss"
    capabilities = ProviderCapabilities(
        kind=kind,
        label="Flux RSS/Atom",
        supports_search=True,
        supports_auto_apply=False,
        notes=(
            "L'utilisateur fournit les URL de flux. Respecter les conditions du site ; "
            "ApplyFlow n'essaie pas de contourner d'éventuelles restrictions."
        ),
        config_fields=("feeds", "company", "delay_seconds"),
    )

    def __init__(
        self,
        feeds: list[str],
        *,
        company: str = "",
        source_name: str = "RSS",
        transport: httpx.BaseTransport | None = None,
        timeout_seconds: float = 20.0,
        delay_seconds: float = 1.0,
        **_: Any,
    ) -> None:
        if not feeds:
            raise ProviderError("aucun flux RSS configuré")
        self.feeds = feeds
        self.company = company
        self.source_name = source_name
        self._transport = transport
        self.timeout_seconds = timeout_seconds
        self.delay_seconds = max(0.0, delay_seconds)

    def fetch(self, query: JobQuery) -> list[NormalizedJob]:
        jobs: list[NormalizedJob] = []
        for index, feed_url in enumerate(self.feeds):
            if index > 0 and self.delay_seconds:
                time.sleep(self.delay_seconds)
            try:
                with self._client(self._transport) as client:
                    response = client.get(feed_url)
                    response.raise_for_status()
                parsed = feedparser.parse(response.content)
            except httpx.HTTPError as exc:
                raise ProviderError(f"flux RSS inaccessible ({feed_url}) : {exc}") from exc
            feed_title = (parsed.feed or {}).get("title") or self.company or feed_url
            for entry in parsed.entries[: query.limit]:
                description = html_to_text(entry.get("summary") or entry.get("description"))
                jobs.append(
                    normalized_from_mapping(
                        {
                            "external_id": entry.get("id") or entry.get("link"),
                            "url": entry.get("link"),
                            "company": self.company or feed_title,
                            "title": entry.get("title") or "Offre sans titre",
                            "description": description,
                            "published_at": entry.get("published"),
                            "skills": enrich_description(description),
                        },
                        source_kind=self.kind,
                        source_name=self.source_name,
                    )
                )
        return apply_query_filters(jobs, query)


class SingleUrlProvider(_HttpProvider):
    """Import d'une annonce précise fournie par l'utilisateur (JSON-LD / OpenGraph)."""

    kind = "manual_url"
    capabilities = ProviderCapabilities(
        kind=kind,
        label="Import d'une URL d'annonce",
        supports_search=False,
        supports_auto_apply=False,
        notes=(
            "Requête unique déclenchée par l'utilisateur sur une page qu'il consulte. "
            "Ne pas utiliser pour du moissonnage massif."
        ),
        config_fields=("url",),
    )

    def __init__(
        self,
        url: str,
        *,
        source_name: str = "Import URL",
        transport: httpx.BaseTransport | None = None,
        timeout_seconds: float = 20.0,
        **_: Any,
    ) -> None:
        if not url.startswith(("http://", "https://")):
            raise ProviderError("URL http(s) attendue")
        self.url = url
        self.source_name = source_name
        self._transport = transport
        self.timeout_seconds = timeout_seconds

    def fetch(self, query: JobQuery) -> list[NormalizedJob]:
        try:
            with self._client(self._transport) as client:
                response = client.get(self.url)
                response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            hint = ""
            if status in {401, 403, 429}:
                hint = (
                    " Ce site refuse les requêtes automatiques (c'est normal pour LinkedIn, Indeed, "
                    "Glassdoor ou HelloWork). Pour ces sites, utilisez la source « Job boards » "
                    "(à activer dans Réglages → Collecte) ; sinon copiez l'annonce dans un fichier "
                    "JSON."
                )
            raise ProviderError(f"page inaccessible (HTTP {status}).{hint}") from exc
        except httpx.HTTPError as exc:
            raise ProviderError(f"page inaccessible : {exc}") from exc

        soup = BeautifulSoup(response.text, "html.parser")
        job = _job_from_json_ld(soup, response.url, self.source_name)
        if job is None:
            title_tag = soup.find("meta", property="og:title") or soup.find("title")
            title = title_tag.get("content") if title_tag and title_tag.has_attr("content") else (
                title_tag.get_text(strip=True) if title_tag else ""
            )
            description_tag = soup.find("meta", property="og:description")
            description = description_tag.get("content") if description_tag else ""
            if not title:
                raise ProviderError("aucune offre détectée sur cette page")
            company = httpx.URL(str(response.url)).host.removeprefix("www.").split(".")[0]
            job = normalized_from_mapping(
                {
                    "url": str(response.url),
                    "company": company,
                    "title": title,
                    "description": html_to_text(description),
                    "skills": enrich_description(description),
                },
                source_kind=self.kind,
                source_name=self.source_name,
            )
        return [job]


def _job_from_json_ld(
    soup: BeautifulSoup, url: httpx.URL, source_name: str
) -> NormalizedJob | None:
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or script.get_text() or "{}")
        except json.JSONDecodeError:
            continue
        entries = data if isinstance(data, list) else [data]
        if isinstance(data, dict) and "@graph" in data:
            entries = data["@graph"]
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            types = entry.get("@type")
            is_job = "JobPosting" in types if isinstance(types, list) else types == "JobPosting"
            if not is_job:
                continue
            organization = entry.get("hiringOrganization") or {}
            address = ((entry.get("jobLocation") or {}).get("address") or {})
            location = ", ".join(
                str(part)
                for part in (address.get("addressLocality"), address.get("addressCountry"))
                if part
            ) or None
            salary = (entry.get("baseSalary") or {}).get("value") or {}
            description = html_to_text(str(entry.get("description") or ""))
            contract = entry.get("employmentType")
            if isinstance(contract, list):
                contract = contract[0] if contract else None
            return normalized_from_mapping(
                {
                    "external_id": entry.get("identifier") or slugify(str(url)),
                    "url": entry.get("url") or str(url),
                    "company": organization.get("name") or httpx.URL(str(url)).host,
                    "title": entry.get("title"),
                    "description": description,
                    "location": location,
                    "remote": infer_remote(location, description),
                    "contract_type": infer_contract(str(contract or "")) or contract,
                    "seniority": infer_seniority(str(entry.get("title") or ""), description),
                    "salary_min": salary.get("minValue") or salary.get("value"),
                    "salary_max": salary.get("maxValue"),
                    "salary_currency": salary.get("currency"),
                    "published_at": parse_datetime(entry.get("datePosted")),
                    "skills": enrich_description(description),
                },
                source_kind="manual_url",
                source_name=source_name,
            )
    return None


def infer_salary_from_text(text: str) -> tuple[int | None, int | None, str | None]:
    return infer_salary(text)
