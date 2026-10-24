"""Détection de séniorité et d'exigences d'expérience, sensible au contexte."""

from __future__ import annotations

import re

from pydantic import BaseModel, Field

from applyflow.text import normalize_text, split_sentences, truncate

LEVELS = (
    "intern",
    "entry",
    "junior",
    "mid",
    "senior",
    "lead",
    "principal",
    "director",
    "unknown",
)

_TITLE_LEVELS: list[tuple[str, re.Pattern[str]]] = [
    ("intern", re.compile(r"\b(?:intern|internship|stage|stagiaire|alternance)\b")),
    (
        "director",
        re.compile(r"\b(?:director|directeur|head of|vp of|vice president|chief|cto|ceo)\b"),
    ),
    (
        "principal",
        re.compile(r"\b(?:principal|staff|distinguished|architect|fellow)\b"),
    ),
    ("lead", re.compile(r"\b(?:lead|leader|supervisor|manager|responsable)\b")),
    ("senior", re.compile(r"\b(?:senior|sr|snr)\b")),
    ("mid", re.compile(r"\b(?:mid[- ]?level|intermediate|confirme|confirmed)\b")),
    (
        "entry",
        re.compile(
            r"\b(?:entry[- ]?level|graduate|new grad(?:uate)?|associate|trainee|apprentice|"
            r"debutant|premiere experience|early career|no experience)\b"
        ),
    ),
    ("junior", re.compile(r"\b(?:junior|jr|jun)\b")),
]

# Signaux explicites dans la description. On ignore volontairement « senior X » nu,
# car « senior stakeholders » ou « senior engineers » ne décrivent pas le poste.
_DESCRIPTION_LEVELS: list[tuple[str, re.Pattern[str]]] = [
    ("senior", re.compile(r"\b(?:senior|sr)[- ]level\b")),
    ("lead", re.compile(r"\b(?:lead|leadership)[- ]level\b")),
    (
        "senior",
        re.compile(
            r"\b(?:this|the) (?:role|position|opportunity) (?:is|requires) "
            r"(?:a |an )?(?:senior|experienced|confirmed)\b"
        ),
    ),
    (
        "entry",
        re.compile(
            r"\b(?:this|the) (?:role|position|opportunity) (?:is|requires) "
            r"(?:a |an )?(?:entry[- ]level|junior|graduate)\b"
        ),
    ),
    (
        "junior",
        re.compile(r"\b(?:hiring|seeking|looking for) (?:a |an )?(?:junior|graduate|entry[- ]level)\b"),
    ),
    (
        "senior",
        re.compile(r"\b(?:job|career|experience) level\s*[:=]\s*(?:senior|experienced)\b"),
    ),
    (
        "junior",
        re.compile(r"\b(?:job|career|experience) level\s*[:=]\s*(?:junior|entry)\b"),
    ),
]

_YEARS_RE = re.compile(
    r"(?<![a-z0-9])(\d{1,2})(?:\s*(?:-|to|a)\s*(\d{1,2}))?\s*(\+)?\s*(?:years?|yrs?|ans?)\b"
)

_REQUIRED_MARKERS = (
    "required",
    "requirement",
    "must",
    "minimum",
    "at least",
    "exig",
    "obligatoire",
    "au moins",
    "requis",
    "demande",
)
_PREFERRED_MARKERS = (
    "preferred",
    "a plus",
    "nice to have",
    "ideally",
    "souhaite",
    "apprecie",
    "bonus",
    "desired",
    "plus",
)


class YearsRequirement(BaseModel):
    years: float
    hard: bool = False
    evidence: str = ""


class SeniorityAssessment(BaseModel):
    level: str = "unknown"
    title_level: str | None = None
    years_required: YearsRequirement | None = None
    years_preferred: YearsRequirement | None = None
    evidence: list[str] = Field(default_factory=list)

    @property
    def is_entry_like(self) -> bool:
        return self.level in {"intern", "entry", "junior", "unknown"}


def _level_from_title(title: str) -> tuple[str, str | None]:
    normalized = normalize_text(title)
    for level, pattern in _TITLE_LEVELS:
        match = pattern.search(normalized)
        if match:
            return level, match.group(0)
    return "unknown", None


def _level_from_description(description: str) -> tuple[str, str | None]:
    normalized = normalize_text(description)
    for level, pattern in _DESCRIPTION_LEVELS:
        match = pattern.search(normalized)
        if match:
            return level, match.group(0)
    return "unknown", None


def _classify_years(sentence: str, years: float, match: str, plus: bool) -> YearsRequirement:
    normalized = normalize_text(sentence)
    hard = plus or any(marker in normalized for marker in _REQUIRED_MARKERS)
    preferred = any(marker in normalized for marker in _PREFERRED_MARKERS)
    if preferred and not hard:
        return YearsRequirement(years=years, hard=False, evidence=truncate(sentence, 180))
    return YearsRequirement(years=years, hard=hard, evidence=truncate(match, 180))


def extract_years(description: str) -> tuple[YearsRequirement | None, YearsRequirement | None]:
    required: YearsRequirement | None = None
    preferred: YearsRequirement | None = None
    for sentence in split_sentences(description):
        normalized = normalize_text(sentence)
        match = _YEARS_RE.search(normalized)
        if not match:
            continue
        years = float(match.group(1))
        if years <= 0 and match.group(2):
            years = float(match.group(2))
        if years <= 0 or years > 30:
            continue
        requirement = _classify_years(sentence, years, match.group(0), bool(match.group(3)))
        if requirement.hard:
            if required is None or requirement.years < required.years:
                required = requirement
        elif preferred is None or requirement.years > preferred.years:
            preferred = requirement
    return required, preferred


def assess_seniority(title: str, description: str = "", contract_type: str | None = None) -> SeniorityAssessment:
    title_level, title_evidence = _level_from_title(title)
    evidence: list[str] = []
    if title_evidence:
        evidence.append(f"intitulé : « {title_evidence} »")

    level = title_level
    if level == "unknown":
        level, description_signal = _level_from_description(description)
        if description_signal:
            evidence.append(f"description : « {description_signal} »")

    required, preferred = extract_years(description)
    if required:
        evidence.append(f"expérience exigée : {required.years:g} ans")
    elif preferred:
        evidence.append(f"expérience souhaitée : {preferred.years:g} ans")

    normalized_contract = normalize_text(contract_type or "")
    if level == "unknown" and normalized_contract in {"internship", "stage", "alternance", "apprenticeship"}:
        level = "intern"
        evidence.append("type de contrat : stage/alternance")

    if level == "unknown":
        evidence.append("séniorité non explicite")

    return SeniorityAssessment(
        level=level,
        title_level=title_level if title_level != "unknown" else None,
        years_required=required,
        years_preferred=preferred,
        evidence=evidence,
    )


def priority_rank(level: str) -> int:
    """Plus bas = plus prioritaire pour un profil débutant."""
    return {
        "intern": 0,
        "entry": 1,
        "junior": 2,
        "unknown": 3,
        "mid": 4,
        "senior": 5,
        "lead": 6,
        "principal": 7,
        "director": 8,
    }.get(level, 3)
