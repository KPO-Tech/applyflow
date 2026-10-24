"""Fabrique de connecteurs et catalogue des limitations."""

from __future__ import annotations

from typing import Any

from applyflow.config import Settings
from applyflow.providers.adzuna import AdzunaProvider
from applyflow.providers.ats_provider import AtsProvider
from applyflow.providers.base import (
    JobProvider,
    ProviderCapabilities,
    ProviderDisabled,
    provider_config,
)
from applyflow.providers.fixture import FixtureProvider
from applyflow.providers.http_providers import (
    GreenhouseProvider,
    LeverProvider,
    RssProvider,
    SingleUrlProvider,
)
from applyflow.providers.jobspy_provider import JobSpyProvider
from applyflow.providers.json_import import JsonFileProvider
from applyflow.usage import UsageStore, usage_path

PROVIDER_KINDS: dict[str, dict[str, Any]] = {
    "fixture": {
        "label": "Annonces fictives (démonstration)",
        "available": True,
        "requirements": "aucun",
        "notes": "Jeu de données local fourni avec ApplyFlow.",
    },
    "json_file": {
        "label": "Import JSON local",
        "available": True,
        "requirements": "path",
        "notes": "Format documenté dans docs/connectors.md.",
    },
    "rss": {
        "label": "Flux RSS/Atom",
        "available": True,
        "requirements": "feeds",
        "notes": "Flux fournis par l'utilisateur, lecture uniquement.",
    },
    "greenhouse": {
        "label": "Greenhouse",
        "available": True,
        "requirements": "board_token",
        "notes": "API publique de lecture ; soumission manuelle après préparation.",
    },
    "lever": {
        "label": "Lever",
        "available": True,
        "requirements": "company",
        "notes": "API publique de lecture ; soumission manuelle après préparation.",
    },
    "manual_url": {
        "label": "Import d'une URL",
        "available": True,
        "requirements": "url",
        "notes": "Requête unique déclenchée par l'utilisateur (JSON-LD / OpenGraph).",
    },
    "adzuna": {
        "label": "Adzuna (API officielle)",
        "available": True,
        "requirements": "app_id, app_key (dans les réglages)",
        "notes": (
            "Agrégateur d'offres françaises via l'API officielle. Clé gratuite sur "
            "developer.adzuna.com ; aucun scraping."
        ),
    },
    "ats": {
        "label": "ATS publics (Greenhouse, Lever, Ashby, SmartRecruiters, Workday…)",
        "available": True,
        "requirements": "companies (extra `boards`)",
        "notes": "API publiques de lecture, entreprise par entreprise ; voir docs/discovery.md.",
    },
    "jobspy": {
        "label": "Job boards via JobSpy (LinkedIn, Indeed, Glassdoor, HelloWork)",
        "available": True,
        "requirements": "extra `boards` + [boards] jobspy_enabled = true",
        "notes": "Opt-in, débit limité, à vos risques : voir docs/discovery.md.",
    },
    "linkedin": {
        "label": "LinkedIn",
        "available": False,
        "requirements": "—",
        "notes": (
            "Pas de connecteur dédié : la lecture des offres passe par la source « Job boards "
            "(JobSpy) », opt-in, avec plafond quotidien. LinkedIn interdit l'automatisation dans "
            "ses conditions : à vos risques. Sinon, importez une offre via « manual_url »."
        ),
    },
    "indeed": {
        "label": "Indeed",
        "available": False,
        "requirements": "—",
        "notes": (
            "Pas de connecteur dédié : la lecture des offres passe par la source « Job boards "
            "(JobSpy) », opt-in, avec plafond quotidien. Indeed encadre l'automatisation dans "
            "ses conditions : à vos risques. Sinon, importez les annonces via une URL ou un export."
        ),
    },
    "welcome_to_the_jungle": {
        "label": "Welcome to the Jungle",
        "available": False,
        "requirements": "—",
        "notes": (
            "Non implémenté : pas d'API publique documentée. Utilisez l'import "
            "d'URL ou un export JSON."
        ),
    },
    "workday": {
        "label": "Workday",
        "available": False,
        "requirements": "—",
        "notes": (
            "Non implémenté : chaque tenant Workday a un formulaire différent et "
            "aucune API publique de candidature. Importez l'annonce puis préparez "
            "manuellement la candidature."
        ),
    },
}

_FACTORIES = {
    "fixture": FixtureProvider,
    "json_file": JsonFileProvider,
    "rss": RssProvider,
    "greenhouse": GreenhouseProvider,
    "lever": LeverProvider,
    "manual_url": SingleUrlProvider,
    "adzuna": AdzunaProvider,
    "jobspy": JobSpyProvider,
    "ats": AtsProvider,
}

_ALIASES = {
    "career_site": "manual_url",
    "company_site": "manual_url",
    "welcome_to_the_jungle": "welcome_to_the_jungle",
    "wttj": "welcome_to_the_jungle",
}


def build_provider(spec: dict[str, Any], settings: Settings | None = None) -> JobProvider:
    """Construit un connecteur depuis `{"kind": ..., "config": {...}}`."""
    kind = str(spec.get("kind") or "").strip().lower()
    kind = _ALIASES.get(kind, kind)
    config = dict(spec.get("config") or {})
    if kind == "adzuna" and settings is not None:
        # Les identifiants restent dans les réglages, jamais dans une campagne.
        config.setdefault("app_id", settings.adzuna.app_id)
        config.setdefault("app_key", settings.adzuna.app_key)
        config.setdefault("country", settings.adzuna.country)
        config.setdefault("max_pages", settings.adzuna.max_pages)
    if kind == "jobspy" and settings is not None:
        boards = settings.boards
        config["enabled"] = boards.jobspy_enabled  # le réglage global prime sur la campagne
        config.setdefault("sites", boards.sites)
        config.setdefault("country", boards.country)
        config.setdefault("max_per_site", boards.max_per_site)
        config.setdefault("pause_seconds", boards.pause_seconds)
        config.setdefault("proxies", boards.proxies)
        config["budget"] = UsageStore(
            usage_path(settings.app.data_dir), limits=boards.daily_limits
        )  # le plafond global prime sur la campagne
    elif kind == "jobspy":
        config["enabled"] = False
    if kind in _FACTORIES:
        try:
            return _FACTORIES[kind](**config)
        except TypeError as exc:
            raise ProviderDisabled(f"configuration invalide pour {kind} : {exc}") from exc
    docs = PROVIDER_KINDS.get(kind)
    if docs:
        raise ProviderDisabled(f"{docs['label']} n'est pas disponible : {docs['notes']}")
    raise ProviderDisabled(
        f"connecteur inconnu « {kind} ». Connecteurs disponibles : "
        + ", ".join(sorted(_FACTORIES))
    )


def provider_catalog() -> list[dict[str, Any]]:
    catalog: list[dict[str, Any]] = []
    for kind, meta in PROVIDER_KINDS.items():
        catalog.append({"kind": kind, **meta})
    for kind, factory in _FACTORIES.items():
        capabilities: ProviderCapabilities = factory.capabilities  # type: ignore[attr-defined]
        for entry in catalog:
            if entry["kind"] == kind:
                entry.update(provider_config(capabilities))
    return catalog
