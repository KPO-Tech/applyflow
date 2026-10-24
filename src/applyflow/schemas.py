"""Schémas Pydantic partagés (annonces normalisées, requêtes de découverte)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator

REMOTE_VALUES = {"remote", "hybrid", "onsite", "unspecified"}


class NormalizedJob(BaseModel):
    source_kind: str
    source_name: str = ""
    external_id: str = ""
    url: str
    apply_url: str | None = None
    company: str
    title: str
    description: str = ""
    location: str | None = None
    country: str | None = None  # code ISO 3166-1 alpha-2 (FR, GB…), None si inconnu
    remote: str | None = None
    salary_min: int | None = None
    salary_max: int | None = None
    salary_currency: str | None = None
    contract_type: str | None = None
    seniority: str | None = None
    skills: list[str] = Field(default_factory=list)
    published_at: datetime | None = None
    raw: dict[str, Any] = Field(default_factory=dict)

    @field_validator("country")
    @classmethod
    def _country(cls, value: str | None) -> str | None:
        from applyflow.geo import normalize_country

        return normalize_country(value)

    @field_validator("remote")
    @classmethod
    def _remote(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.lower().strip()
        return value if value in REMOTE_VALUES else "unspecified"

    @field_validator("company", "title", "url")
    @classmethod
    def _required_text(cls, value: str) -> str:
        value = (value or "").strip()
        if not value:
            raise ValueError("champ obligatoire vide")
        return value


class JobQuery(BaseModel):
    keywords: list[str] = Field(default_factory=list)
    locations: list[str] = Field(default_factory=list)
    contracts: list[str] = Field(default_factory=list)
    limit: int = 1000
    remote_only: bool = False

    @field_validator("limit")
    @classmethod
    def _limit(cls, value: int) -> int:
        if value < 1:
            raise ValueError("limit doit être >= 1")
        return value


class ImportResult(BaseModel):
    created: int = 0
    duplicates: int = 0
    skipped: int = 0
    errors: list[str] = Field(default_factory=list)
    job_ids: list[str] = Field(default_factory=list)
    # Statistiques par connecteur (offres, erreurs, durée par site ou par entreprise).
    stats: dict[str, Any] = Field(default_factory=dict)
