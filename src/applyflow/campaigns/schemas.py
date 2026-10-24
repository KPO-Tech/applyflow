"""Validation des campagnes."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, field_validator


class CampaignInput(BaseModel):
    name: str = Field(min_length=2, max_length=160)
    sources: list[dict[str, Any]] = Field(default_factory=list, validate_default=True)
    profile_ids: list[str] = Field(default_factory=list)
    locations: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)
    experience_levels: list[str] = Field(
        default_factory=lambda: ["intern", "entry", "junior", "graduate", "unknown"]
    )
    max_jobs: int = Field(default=1000, ge=1, le=5000)
    min_score: int = Field(default=65, ge=0, le=100)
    exclusions: list[str] = Field(default_factory=list)

    @field_validator("sources")
    @classmethod
    def _sources(cls, values: list[dict[str, Any]]) -> list[dict[str, Any]]:
        cleaned = []
        for value in values:
            kind = str(value.get("kind") or "").strip()
            if not kind:
                raise ValueError("chaque source doit définir un champ 'kind'")
            cleaned.append({"kind": kind, "name": value.get("name"), "config": value.get("config") or {}})
        if not cleaned:  # jamais de source fictive par défaut
            raise ValueError("choisissez au moins une source de collecte")
        return cleaned
