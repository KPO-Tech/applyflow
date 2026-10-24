"""Connecteur JobSpy (LinkedIn, Indeed, Glassdoor, HelloWork…) : opt-in, débit limité.

JobSpy est utilisé tel quel comme bibliothèque (extra `boards`). Garde-fous d'ApplyFlow :
requêtes séquentielles avec pauses, volume plafonné par site, aucun contournement de CAPTCHA
ou de connexion ; un site qui répond 403/429 est abandonné pour la collecte en cours.
"""

from __future__ import annotations

import math
import time
from collections.abc import Callable
from typing import Any

from applyflow.geo import detect_country, get_country, normalize_country
from applyflow.logging_setup import get_logger
from applyflow.providers.base import Controllable, ProviderCapabilities, ProviderError
from applyflow.providers.json_import import normalized_from_mapping
from applyflow.schemas import JobQuery, NormalizedJob
from applyflow.usage import UsageStore

logger = get_logger("jobspy")

SUPPORTED_SITES = ("indeed", "linkedin", "glassdoor", "hellowork", "google")
JOB_TYPES = {"fulltime": "CDI", "parttime": "Temps partiel", "contract": "CDD / contrat",
             "temporary": "Intérim", "internship": "Stage"}
BLOCK_MARKERS = ("403", "429", "blocked")


def jobspy_country(iso: str | None) -> str | None:
    """Valeur `country_indeed` de JobSpy pour un pays ; None si JobSpy ne le connaît pas."""
    country = get_country(iso)
    if country is None:
        return None
    try:
        from jobspy.model import Country

        return Country(country.name.lower()).value
    except (ImportError, ValueError):
        return None


def site_covers(site: str, iso: str | None) -> bool:
    """HelloWork est un site français ; les autres savent chercher par lieu."""
    return iso in (None, "FR") if site == "hellowork" else True


def _default_scrape(**kwargs: Any) -> Any:
    try:
        from jobspy import scrape_jobs
    except ImportError as exc:
        raise ProviderError(
            "JobSpy n'est pas installé : `uv sync --extra boards`."
        ) from exc
    return scrape_jobs(**kwargs)


def _clean(value: Any) -> Any:
    """Convertit les NaN/NaT de pandas en None."""
    if value is None:
        return None
    try:
        if isinstance(value, float) and math.isnan(value):
            return None
        if value != value:  # NaT / NaN
            return None
    except (TypeError, ValueError):
        return value
    return value


JOB_BOARD_LABELS = {
    "indeed": "Indeed",
    "hellowork": "HelloWork",
    "linkedin": "LinkedIn",
    "glassdoor": "Glassdoor",
    "google": "Google",
}


class JobSpyProvider(Controllable):
    kind = "jobspy"
    capabilities = ProviderCapabilities(
        kind=kind,
        label="Job boards via JobSpy (LinkedIn, Indeed, Glassdoor, HelloWork)",
        supports_search=True,
        supports_auto_apply=False,
        terms_url="https://github.com/speedyapply/JobSpy",
        notes=(
            "Lecture des pages publiques de recherche d'emploi. Ces sites encadrent ou interdisent "
            "l'automatisation dans leurs conditions : usage personnel, volume faible, à vos "
            "risques (blocage d'IP possible). Désactivé par défaut."
        ),
        config_fields=("sites", "country", "max_per_site", "pause_seconds"),
    )

    def __init__(
        self,
        *,
        sites: list[str] | None = None,
        country: str = "france",
        max_per_site: int = 100,
        pause_seconds: float = 5.0,
        hours_old: int | None = None,
        fetch_description: bool = True,
        proxies: list[str] | None = None,
        enabled: bool = True,
        source_name: str = "JobSpy",
        scrape: Callable[..., Any] | None = None,
        sleep: Callable[[float], None] = time.sleep,
        budget: UsageStore | None = None,
        **_: Any,
    ) -> None:
        chosen = [s.strip().lower() for s in (sites or ["indeed", "hellowork", "linkedin"])]
        unknown = [s for s in chosen if s not in SUPPORTED_SITES]
        if unknown:
            raise ProviderError(
                f"site(s) JobSpy non supporté(s) : {', '.join(unknown)}. "
                f"Disponibles : {', '.join(SUPPORTED_SITES)}."
            )
        self.sites = chosen
        self.country = country
        self.max_per_site = max(1, min(int(max_per_site), 1000))
        self.pause_seconds = max(0.0, float(pause_seconds))
        self.hours_old = hours_old
        self.fetch_description = fetch_description
        self.proxies = proxies or None
        self.enabled = enabled
        self.source_name = source_name
        self._scrape = scrape or _default_scrape
        self._sleep = sleep
        #: plafond quotidien par site (None : aucun plafond)
        self.budget = budget
        #: statistiques de la dernière collecte, par site
        self.last_stats: dict[str, dict[str, Any]] = {}
        #: utilisation quotidienne après la dernière collecte (utilisé / plafond / reste)
        self.daily_usage: dict[str, dict[str, int | None]] = {}

    def fetch(self, query: JobQuery) -> list[NormalizedJob]:
        if not self.enabled:
            raise ProviderError(
                "JobSpy est désactivé. Activez-le dans Réglages → Collecte "
                "([boards] jobspy_enabled = true) après avoir lu l'avertissement."
            )
        if not query.keywords:
            raise ProviderError("indiquez au moins un mot-clé pour JobSpy.")
        locations = query.locations or ["France"]
        per_site = min(self.max_per_site, query.limit)
        searches = [(kw, loc) for kw in query.keywords for loc in locations]
        per_search = max(1, math.ceil(per_site / len(searches)))

        self.last_stats = {s: {"jobs": 0, "errors": [], "seconds": 0.0} for s in self.sites}
        blocked: set[str] = set()
        capped: set[str] = set()
        jobs: list[NormalizedJob] = []
        first = True
        steps = [(kw, loc, site) for kw, loc in searches for site in self.sites]
        for index, (keyword, location, site) in enumerate(steps):
            if self._cancelled():
                break
            self._report(index, len(steps), f"{JOB_BOARD_LABELS.get(site, site)} · {keyword}", len(jobs))
            if site in blocked or site in capped or self.last_stats[site]["jobs"] >= per_site:
                continue
            iso = detect_country(location) or normalize_country(location)
            if not site_covers(site, iso):
                note = f"{JOB_BOARD_LABELS.get(site, site)} ne couvre pas « {location} »"
                if note not in self.last_stats[site]["errors"]:
                    self.last_stats[site]["errors"].append(note)
                continue
            wanted = per_search
            if self.budget is not None:
                remaining = self.budget.remaining(site)
                if remaining is not None:
                    if remaining <= 0:
                        capped.add(site)
                        self.last_stats[site]["errors"].append(
                            f"plafond quotidien atteint ({self.budget.limit(site)} offres/jour)"
                        )
                        continue
                    wanted = min(wanted, remaining)
            if not first:
                self._pause()
            if self._cancelled():
                break
            first = False
            jobs.extend(self._run_one(site, keyword, location, wanted, blocked, iso))
        else:
            self._report(len(steps), len(steps), "Terminé", len(jobs))
        self.daily_usage = self.budget.snapshot() if self.budget is not None else {}
        if not jobs and capped and len(capped) == len(self.sites):
            raise ProviderError(
                "plafond quotidien atteint sur tous les sites choisis : "
                + ", ".join(f"{s} ({self.budget.limit(s)}/jour)" for s in sorted(capped))  # type: ignore[union-attr]
                + ". Réessayez demain ou relevez la limite dans [boards.daily_limits]."
            )
        if not jobs and blocked and len(blocked) == len(self.sites):
            raise ProviderError(
                "tous les sites JobSpy ont bloqué la requête (403/429). Réessayez plus tard, "
                "réduisez le volume ou changez de réseau ; ApplyFlow n'insiste pas."
            )
        return jobs[: query.limit]

    def _pause(self) -> None:
        """Pause entre deux requêtes ; une annulation l'interrompt immédiatement."""
        if self._cancel_event is not None:
            self._cancel_event.wait(self.pause_seconds)
        else:
            self._sleep(self.pause_seconds)

    def _run_one(
        self,
        site: str,
        keyword: str,
        location: str,
        wanted: int,
        blocked: set[str],
        iso: str | None = None,
    ) -> list[NormalizedJob]:
        stats = self.last_stats[site]
        started = time.monotonic()
        kwargs: dict[str, Any] = {
            "site_name": [site],
            "search_term": keyword,
            "location": location,
            "results_wanted": wanted,
            # Indeed et Glassdoor ont un domaine par pays : on suit le pays du lieu cherché.
            "country_indeed": jobspy_country(iso) or self.country,
            "fetch_description": self.fetch_description,
            "description_format": "markdown",
            "verbose": 0,
        }
        if self.hours_old:
            kwargs["hours_old"] = self.hours_old
        if self.proxies:
            kwargs["proxies"] = self.proxies
        try:
            frame = self._scrape(**kwargs)
        except Exception as exc:  # JobSpy lève ValueError ou erreurs réseau
            stats["errors"].append(str(exc))
            logger.warning("échec JobSpy", extra={"data": {"site": site, "error": str(exc)}})
            return []
        finally:
            stats["seconds"] = round(stats["seconds"] + time.monotonic() - started, 2)
        errors = getattr(frame, "attrs", {}).get("errors", {}) or {}
        if site in errors:
            message = str(errors[site])
            stats["errors"].append(message)
            if any(marker in message.lower() for marker in BLOCK_MARKERS):
                blocked.add(site)
        result: list[NormalizedJob] = []
        for row in frame.to_dict("records"):
            try:
                result.append(self._normalize(site, row))
            except (ProviderError, ValueError) as exc:
                stats["errors"].append(str(exc))
        stats["jobs"] += len(result)
        if self.budget is not None:
            self.budget.consume(site, len(result))
        return result

    def _normalize(self, site: str, row: dict[str, Any]) -> NormalizedJob:
        row = {key: _clean(value) for key, value in row.items()}
        interval = str(row.get("interval") or "").lower()
        low, high = row.get("min_amount"), row.get("max_amount")
        if interval == "hourly":
            low, high = (low and low * 1607), (high and high * 1607)
        elif interval == "monthly":
            low, high = (low and low * 12), (high and high * 12)
        job_types = str(row.get("job_type") or "").split(",")
        contract = next((JOB_TYPES[t.strip()] for t in job_types if t.strip() in JOB_TYPES), None)
        remote = row.get("is_remote")
        location = row.get("location")
        data = {
            "country_hint": self.country,
            "external_id": f"{site}:{row.get('id') or ''}",
            "url": row.get("job_url"),
            "apply_url": row.get("job_url_direct") or row.get("job_url"),
            "company": row.get("company") or "Entreprise non communiquée",
            "title": row.get("title"),
            "description": row.get("description") or "",
            "location": location,
            "contract_type": contract,
            "salary_min": int(low) if low else None,
            "salary_max": int(high) if high else None,
            "salary_currency": row.get("currency"),
            "seniority": None,
            "skills": [s.strip() for s in str(row.get("skills") or "").split(",") if s.strip()],
            "published_at": str(row["date_posted"]) if row.get("date_posted") else None,
            "raw": {k: (v if isinstance(v, str | int | float | bool) else str(v))
                    for k, v in row.items() if v is not None},
        }
        job = normalized_from_mapping(
            data, source_kind=self.kind, source_name=f"{self.source_name}:{site}"
        )
        if remote is True and job.remote in (None, "unspecified"):
            job = job.model_copy(update={"remote": "remote"})
        return job
