"""Annonces fictives livrées avec ApplyFlow : aucun compte externe requis."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from applyflow.providers.base import ProviderCapabilities, ProviderError, apply_query_filters
from applyflow.providers.json_import import normalized_from_mapping
from applyflow.schemas import JobQuery, NormalizedJob

DEFAULT_FIXTURES = Path(__file__).resolve().parents[1] / "data" / "fixtures" / "jobs.json"


class FixtureProvider:
    kind = "fixture"
    capabilities = ProviderCapabilities(
        kind=kind,
        label="Annonces fictives (démonstration)",
        supports_search=True,
        supports_auto_apply=False,
        notes=(
            "Jeu de données local d'entreprises et d'offres inventées. "
            "Les formulaires `demo://` sont des pages HTML locales."
        ),
        config_fields=("path",),
    )

    def __init__(self, path: str | None = None, **_: Any) -> None:
        self.path = Path(path).expanduser() if path else DEFAULT_FIXTURES

    def fetch(self, query: JobQuery) -> list[NormalizedJob]:
        if not self.path.is_file():
            raise ProviderError(f"jeu de données fictif introuvable : {self.path}")
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        items = payload.get("jobs", []) if isinstance(payload, dict) else payload
        jobs = [
            normalized_from_mapping(item, source_kind=self.kind, source_name="démo")
            for item in items
        ]
        return apply_query_filters(jobs, query)
