"""Import d'annonces depuis un fichier JSON (format documenté, sans réseau)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from applyflow.geo import detect_country, normalize_country
from applyflow.providers.base import ProviderCapabilities, ProviderError, apply_query_filters
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


def normalized_from_mapping(
    data: dict[str, Any], *, source_kind: str, source_name: str = ""
) -> NormalizedJob:
    description = html_to_text(str(data.get("description") or ""))
    title = str(data.get("title") or "").strip()
    company = str(data.get("company") or "").strip()
    url = str(data.get("url") or "").strip()
    if not url:
        raise ProviderError(f"annonce sans URL ignorée : {title!r}")
    location = data.get("location")
    provided_contract = str(data.get("contract_type") or "").strip()
    contract = (
        infer_contract(provided_contract)
        or provided_contract
        or infer_contract(description)
    )
    salary_min, salary_max, currency = infer_salary(description)
    return NormalizedJob(
        source_kind=source_kind,
        source_name=source_name or source_kind,
        external_id=str(data.get("external_id") or slugify(f"{company}-{title}")),
        url=url,
        apply_url=data.get("apply_url"),
        company=company,
        title=title,
        description=description,
        location=str(location).strip() if location else None,
        country=normalize_country(data.get("country"))
        or detect_country(str(location or ""), default=data.get("country_hint")),
        remote=infer_remote(str(location or ""), description),
        salary_min=data.get("salary_min") or salary_min,
        salary_max=data.get("salary_max") or salary_max,
        salary_currency=data.get("salary_currency") or currency,
        contract_type=contract,
        seniority=data.get("seniority") or infer_seniority(title, description, contract),
        skills=enrich_description(description, data.get("skills")),
        published_at=parse_datetime(data.get("published_at")),
        raw=data,
    )


class JsonFileProvider:
    """Lit une liste d'annonces (fichier local), utile pour les exports et les tests."""

    kind = "json_file"
    capabilities = ProviderCapabilities(
        kind=kind,
        label="Import JSON local",
        supports_search=True,
        supports_auto_apply=False,
        notes="Aucun accès réseau. Le format est décrit dans docs/connectors.md.",
        config_fields=("path",),
    )

    def __init__(self, path: str, *, source_name: str = "json_file", **_: Any) -> None:
        self.path = Path(path).expanduser()
        self.source_name = source_name

    def fetch(self, query: JobQuery) -> list[NormalizedJob]:
        if not self.path.is_file():
            raise ProviderError(f"fichier JSON introuvable : {self.path}")
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        items = payload.get("jobs", []) if isinstance(payload, dict) else payload
        jobs = [
            normalized_from_mapping(item, source_kind=self.kind, source_name=self.source_name)
            for item in items
        ]
        return apply_query_filters(jobs, query)
