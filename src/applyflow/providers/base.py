"""Interface `JobProvider` : ajouter une source sans toucher au reste du système."""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from applyflow.schemas import JobQuery, NormalizedJob

#: (étapes faites, étapes totales, libellé, offres collectées jusqu'ici)
ProgressCallback = Callable[[int, int, str, int], None]


class ProviderError(RuntimeError):
    """Erreur récupérable d'un connecteur (réseau, format, configuration)."""


class Controllable:
    """Progression et annulation pour les connecteurs longs (job boards, ATS).

    Une annulation n'est pas une erreur : le connecteur s'arrête entre deux requêtes et rend
    les offres déjà collectées, qui sont alors enregistrées.
    """

    _progress: ProgressCallback | None = None
    _cancel_event: threading.Event | None = None

    def bind_control(
        self, progress: ProgressCallback | None = None, cancel_event: threading.Event | None = None
    ) -> None:
        self._progress = progress
        self._cancel_event = cancel_event

    def _report(self, done: int, total: int, label: str, collected: int) -> None:
        if self._progress is not None:
            self._progress(done, total, label, collected)

    def _cancelled(self) -> bool:
        return self._cancel_event is not None and self._cancel_event.is_set()


class ProviderDisabled(ProviderError):
    """Source non supportée pour des raisons de conformité ou de faisabilité."""


@dataclass(frozen=True)
class ProviderCapabilities:
    kind: str
    label: str
    supports_search: bool = True
    supports_auto_apply: bool = False
    terms_url: str | None = None
    notes: str = ""
    config_fields: tuple[str, ...] = field(default_factory=tuple)


@runtime_checkable
class JobProvider(Protocol):
    kind: str
    capabilities: ProviderCapabilities

    def fetch(self, query: JobQuery) -> list[NormalizedJob]: ...


def location_matches(
    job_location: str | None, locations: list[str], *, country: str | None = None
) -> bool:
    """Une offre correspond si sa localisation contient un lieu demandé, ou si un pays demandé
    est celui de l'offre : « France » retrouve « Paris » même sans le mot « France »."""
    from applyflow.geo import detect_country, normalize_country
    from applyflow.text import normalize_text

    wanted = [normalize_text(location) for location in locations if location.strip()]
    if not wanted:
        return True
    normalized = normalize_text(job_location or "")
    if any(location in normalized for location in wanted):
        return True
    countries = {normalize_country(location) for location in locations} - {None}
    return bool(countries) and (normalize_country(country) or detect_country(job_location)) in countries


def apply_query_filters(jobs: list[NormalizedJob], query: JobQuery) -> list[NormalizedJob]:
    """Filtre commun (mots-clés, localisation, télétravail) puis tronque."""
    from applyflow.text import normalize_text

    result: list[NormalizedJob] = []
    keywords = [normalize_text(keyword) for keyword in query.keywords if keyword.strip()]
    for job in jobs:
        haystack = normalize_text(f"{job.title} {job.description} {job.company}")
        if keywords and not any(keyword in haystack for keyword in keywords):
            continue
        if query.locations and not location_matches(
            job.location, query.locations, country=job.country
        ):
            continue
        if query.remote_only and (job.remote or "") not in {"remote", "hybrid"}:
            continue
        result.append(job)
    return result[: query.limit]


def provider_config(capabilities: ProviderCapabilities) -> dict[str, Any]:
    return {
        "kind": capabilities.kind,
        "label": capabilities.label,
        "supports_search": capabilities.supports_search,
        "supports_auto_apply": capabilities.supports_auto_apply,
        "terms_url": capabilities.terms_url,
        "notes": capabilities.notes,
        "config_fields": list(capabilities.config_fields),
    }
