"""Validation des données de profil."""

from __future__ import annotations

import re
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, Field, field_validator

EXPERIENCE_LEVELS = ("intern", "entry", "junior", "mid", "senior")

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_SCHEME_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.-]*:")
MAX_OTHER_LINKS = 10


def normalize_url(value: str | None) -> str | None:
    """`monsite.fr` devient `https://monsite.fr` ; seuls http et https sont acceptés.

    Ces adresses sont écrites dans des formulaires de candidature et affichées dans
    l'interface : un schéma comme `javascript:` ou `file:` est refusé.
    """
    if value is None or not value.strip():
        return None
    value = value.strip()
    is_port = re.match(r"^[^/:]+:\d+(/|$)", value)  # « monsite.fr:8080 » n'est pas un schéma
    if _SCHEME_RE.match(value) and not value.lower().startswith(("http://", "https://")) and not is_port:
        raise ValueError("adresse invalide : seuls http et https sont acceptés")
    if not value.lower().startswith(("http://", "https://")):
        value = f"https://{value}"
    parts = urlsplit(value)
    if not parts.hostname or "." not in parts.hostname or " " in value:
        raise ValueError("adresse de site invalide (ex. https://monsite.fr)")
    return value


class ProfileLink(BaseModel):
    """Un site ou un lien supplémentaire (portfolio, projet, publication…)."""

    label: str = Field(default="", max_length=80)
    url: str = Field(max_length=500)

    @field_validator("label")
    @classmethod
    def _label(cls, value: str) -> str:
        return value.strip()

    @field_validator("url")
    @classmethod
    def _url(cls, value: str) -> str:
        normalized = normalize_url(value)
        if normalized is None:
            raise ValueError("adresse manquante")
        return normalized


class ProfileInput(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    full_name: str | None = Field(default=None, max_length=160)
    email: str | None = Field(default=None, max_length=255)
    phone: str | None = Field(default=None, max_length=50)
    linkedin_url: str | None = Field(default=None, max_length=500)
    github_url: str | None = Field(default=None, max_length=500)
    website: str | None = Field(default=None, max_length=500)  # portfolio / site personnel
    other_links: list[ProfileLink] = Field(default_factory=list, max_length=MAX_OTHER_LINKS)
    city: str | None = Field(default=None, max_length=120)
    target_titles: list[str] = Field(min_length=1)
    technical_skills: list[str] = Field(default_factory=list)
    domain_skills: list[str] = Field(default_factory=list)
    experience_level: Literal["intern", "entry", "junior", "mid", "senior"] = "junior"
    years_experience: float = Field(default=0, ge=0, le=50)
    locations: list[str] = Field(default_factory=list)
    contract_types: list[str] = Field(default_factory=list)
    remote_preferences: list[str] = Field(default_factory=list)
    salary_min: int | None = Field(default=None, ge=0)
    salary_max: int | None = Field(default=None, ge=0)
    salary_currency: str = Field(default="EUR", max_length=8)
    exclusion_criteria: list[str] = Field(default_factory=list)
    work_authorization: str | None = Field(default=None, max_length=120)
    notes: str | None = None
    active: bool = True

    @field_validator("target_titles", "technical_skills", "domain_skills", "locations",
                     "contract_types", "remote_preferences", "exclusion_criteria")
    @classmethod
    def _clean_list(cls, values: list[str]) -> list[str]:
        cleaned: list[str] = []
        for value in values:
            value = value.strip()
            if value and value not in cleaned:
                cleaned.append(value)
        return cleaned

    @field_validator("linkedin_url", "github_url", "website")
    @classmethod
    def _links(cls, value: str | None) -> str | None:
        return normalize_url(value)

    @field_validator("other_links")
    @classmethod
    def _other_links(cls, links: list[ProfileLink]) -> list[ProfileLink]:
        seen: set[str] = set()
        unique: list[ProfileLink] = []
        for link in links:
            key = link.url.lower().rstrip("/")
            if key not in seen:
                seen.add(key)
                unique.append(link)
        return unique

    @field_validator("email")
    @classmethod
    def _email(cls, value: str | None) -> str | None:
        if value is None or not value.strip():
            return None
        value = value.strip()
        if not _EMAIL_RE.match(value):
            raise ValueError("adresse e-mail invalide")
        return value

    @field_validator("salary_max")
    @classmethod
    def _salary(cls, value: int | None, info) -> int | None:
        minimum = info.data.get("salary_min")
        if value is not None and minimum is not None and value < minimum:
            raise ValueError("salary_max doit être supérieur ou égal à salary_min")
        return value
