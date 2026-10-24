"""Normalisation des données brutes de connecteurs."""

from __future__ import annotations

import html
import re
from datetime import UTC, datetime

from bs4 import BeautifulSoup

from applyflow.matching.seniority import assess_seniority
from applyflow.matching.skills import extract_skills
from applyflow.text import normalize_text


def html_to_text(value: str | None) -> str:
    if not value:
        return ""
    soup = BeautifulSoup(html.unescape(value), "html.parser")
    text = soup.get_text("\n", strip=True)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def infer_remote(location: str | None, description: str = "") -> str:
    text = normalize_text(f"{location or ''} {description}")
    if any(
        phrase in text
        for phrase in ("fully remote", "100 remote", "remote first", "teletravail total")
    ):
        return "remote"
    if re.search(r"\bremote\b", text) or "teletravail" in text:
        return "remote"
    if "hybrid" in text or "hybride" in text:
        return "hybrid"
    if any(phrase in text for phrase in ("on-site", "onsite", "sur site", "presentiel")):
        return "onsite"
    return "unspecified"


def infer_contract(text: str) -> str | None:
    normalized = normalize_text(text)
    mapping = [
        ("cdi", "CDI"),
        ("permanent", "permanent"),
        ("open-ended", "permanent"),
        ("cdd", "CDD"),
        ("fixed-term", "fixed-term"),
        ("fixed term", "fixed-term"),
        ("internship", "internship"),
        ("stage", "internship"),
        ("alternance", "apprenticeship"),
        ("apprenticeship", "apprenticeship"),
        ("freelance", "freelance"),
        ("full-time", "full-time"),
        ("full time", "full-time"),
        ("part-time", "part-time"),
        ("part time", "part-time"),
        ("interim", "temporary"),
    ]
    for needle, label in mapping:
        if re.search(rf"(?<![a-z0-9]){re.escape(needle)}(?![a-z0-9])", normalized):
            return label
    return None


def parse_datetime(value: object) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    try:
        if isinstance(value, (int, float)):
            timestamp = float(value)
            if timestamp > 1e11:  # millisecondes (Lever, certains flux)
                timestamp /= 1000
            return datetime.fromtimestamp(timestamp, tz=UTC)
        text = str(value).strip().replace("Z", "+00:00")
        parsed = datetime.fromisoformat(text)
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    except (TypeError, ValueError, OSError, OverflowError):
        return None


def enrich_description(description: str, skills: list[str] | None = None) -> list[str]:
    found = list(skills or [])
    for skill in extract_skills(description):
        if skill not in found:
            found.append(skill)
    return found


def infer_seniority(title: str, description: str, contract_type: str | None = None) -> str:
    return assess_seniority(title, description, contract_type).level


def infer_salary(text: str) -> tuple[int | None, int | None, str | None]:
    """Extrait une fourchette simple (k€, k$, €). Volontairement conservateur."""
    normalized = normalize_text(text)
    match = re.search(r"(\d{2,3})\s*(?:k|000)?\s*(?:-|to|a)\s*(\d{2,3})\s*(?:k)?\s*(eur|euro|€|usd|\\$)", normalized)
    if match:
        low = int(match.group(1))
        high = int(match.group(2))
        currency = "EUR" if match.group(3) in {"eur", "euro", "€"} else "USD"
        if low < 1000:
            low *= 1000
        if high < 1000:
            high *= 1000
        return low, high, currency
    single = re.search(r"(\d{2,3})\s*(?:k|000)\s*(eur|euro|€|usd|\\$)", normalized)
    if single:
        value = int(single.group(1))
        if value < 1000:
            value *= 1000
        currency = "EUR" if single.group(2) in {"eur", "euro", "€"} else "USD"
        return value, value, currency
    return None, None, None
