"""Moteur de scoring explicable (0-100), indépendant du routeur de CV."""

from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, Field

from applyflow.config import ScoringConfig
from applyflow.contracts import contract_matches, normalize_contract
from applyflow.geo import detect_country, normalize_country
from applyflow.matching.seniority import SeniorityAssessment, assess_seniority
from applyflow.matching.skills import canonicalize_skills, extract_skills, skill_overlap
from applyflow.matching.types import ProfileSnapshot, Reason, ScoreResult
from applyflow.text import contains_phrase, normalize_text, token_set


class JobSignals(BaseModel):
    title: str
    description: str = ""
    company: str = ""
    location: str | None = None
    remote: str | None = None
    contract_type: str | None = None
    skills: list[str] = Field(default_factory=list)
    salary_min: int | None = None
    salary_max: int | None = None

    @classmethod
    def from_any(cls, job: Any) -> JobSignals:
        skills = getattr(job, "skills", None)
        if skills is None:
            skills = getattr(job, "required_skills", None)
        return cls(
            title=getattr(job, "title", "") or "",
            description=getattr(job, "description", "") or "",
            company=getattr(job, "company", "") or "",
            location=getattr(job, "location", None),
            remote=getattr(job, "remote", None),
            contract_type=getattr(job, "contract_type", None),
            skills=list(skills or []),
            salary_min=getattr(job, "salary_min", None),
            salary_max=getattr(job, "salary_max", None),
        )


_REMOTE_ALIASES = {
    "remote": "remote",
    "full remote": "remote",
    "teletravail": "remote",
    "télétravail": "remote",
    "hybrid": "hybrid",
    "hybride": "hybrid",
    "onsite": "onsite",
    "on-site": "onsite",
    "presentiel": "onsite",
    "présentiel": "onsite",
}

_COUNTRY_ALIASES = {
    "fr": "france",
    "france": "france",
    "uk": "united kingdom",
    "united kingdom": "united kingdom",
    "gb": "united kingdom",
    "england": "united kingdom",
    "us": "united states",
    "usa": "united states",
    "united states": "united states",
    "ca": "canada",
    "canada": "canada",
    "de": "germany",
    "germany": "germany",
    "allemagne": "germany",
    "es": "spain",
    "spain": "spain",
    "espagne": "spain",
    "nl": "netherlands",
    "netherlands": "netherlands",
    "pays-bas": "netherlands",
    "be": "belgium",
    "belgium": "belgium",
    "belgique": "belgium",
    "ch": "switzerland",
    "switzerland": "switzerland",
    "suisse": "switzerland",
    "eu": "europe",
    "europe": "europe",
}

_AUTH_RE = re.compile(
    r"(?:must|required|need|requires?)\s+(?:to\s+)?(?:be\s+)?"
    r"(?:legally\s+)?(?:authori[sz]ed|eligible|permitted|able)\s+to\s+work\s+in\s+"
    r"([a-z][a-z\s]{1,30})"
)


def normalize_remote(value: str | None) -> str | None:
    if not value:
        return None
    normalized = normalize_text(value)
    return _REMOTE_ALIASES.get(normalized, normalized)


def _country(value: str) -> str | None:
    normalized = normalize_text(value)
    return _COUNTRY_ALIASES.get(normalized)


def _location_match(job_location: str, accepted: list[str]) -> bool:
    job_norm = normalize_text(job_location)
    if not job_norm:
        return False
    job_tokens = token_set(job_location)
    for location in accepted:
        loc_norm = normalize_text(location)
        if not loc_norm:
            continue
        if loc_norm in job_norm or job_norm in loc_norm:
            return True
        loc_tokens = token_set(location)
        if loc_tokens and loc_tokens.issubset(job_tokens):
            return True
        if _country(location) and _country(location) == _country(job_location):
            return True
        # Un pays accepté couvre ses villes : « France » accepte « Lyon » ou « Nantes ».
        wanted_country = normalize_country(location)
        if wanted_country and wanted_country == detect_country(job_location):
            return True
        if loc_norm in {"remote", "full remote", "teletravail"} and "remote" in job_norm:
            return True
    return False


def _title_similarity(target: str, title: str) -> float:
    target_norm = normalize_text(target)
    title_norm = normalize_text(title)
    if not target_norm or not title_norm:
        return 0.0
    if target_norm == title_norm:
        return 1.0
    if target_norm in title_norm or title_norm in target_norm:
        return 0.9
    target_tokens = token_set(target)
    title_tokens = token_set(title)
    if not target_tokens or not title_tokens:
        return 0.0
    overlap = len(target_tokens & title_tokens) / len(target_tokens | title_tokens)
    if target_tokens.issubset(title_tokens):
        return max(0.85, overlap)
    return overlap


_LEVEL_ALIGNMENT = {
    "intern": 0.85,
    "entry": 1.0,
    "junior": 1.0,
    "mid": 0.8,
    "unknown": 0.75,
    "senior": 0.4,
    "lead": 0.15,
    "principal": 0.1,
    "director": 0.05,
}


def score_job(job: JobSignals, profile: ProfileSnapshot, config: ScoringConfig) -> ScoreResult:
    assessment: SeniorityAssessment = assess_seniority(
        job.title, job.description, job.contract_type
    )
    job_text = f"{job.title} {job.description}"
    job_skills = canonicalize_skills(job.skills) or extract_skills(job_text)
    profile_skills = canonicalize_skills(profile.all_skills)

    matched_skills_ratio, matched, missing = skill_overlap(profile_skills, job_skills)
    profile_matched = [skill for skill in profile_skills if contains_phrase(job_text, skill)]
    profile_coverage = len(profile_matched) / len(profile_skills) if profile_skills else 0.0
    if job_skills:
        skills_component = 0.7 * matched_skills_ratio + 0.3 * min(1.0, profile_coverage)
    else:
        skills_component = 0.5 * min(1.0, profile_coverage) + 0.25

    title_component = max(
        (_title_similarity(target, job.title) for target in profile.target_titles or [""]),
        default=0.0,
    )

    seniority_component = _LEVEL_ALIGNMENT.get(assessment.level, 0.6)
    if (
        assessment.years_required
        and profile.years_experience < assessment.years_required.years
    ):
        ratio = max(0.3, profile.years_experience / assessment.years_required.years)
        seniority_component *= ratio
    if profile.years_experience >= 5 and assessment.level in {"intern", "entry", "junior"}:
        seniority_component *= 0.9

    experience_component = _experience_component(profile, assessment)
    location_component, location_reason = _location_component(job, profile)
    contract_component, contract_reason = _contract_component(job, profile)

    obligations_component = matched_skills_ratio if job_skills else 0.75
    if job_skills and missing:
        obligations_component = max(0.0, matched_skills_ratio * 0.85)

    reasons: list[Reason] = []
    gates: list[Reason] = []

    # --- Portes d'éligibilité (indépendantes du score) ---
    for criterion in profile.exclusion_criteria:
        if criterion and (
            contains_phrase(job.title, criterion) or contains_phrase(job.description, criterion)
        ):
            gates.append(
                Reason(
                    code="exclusion",
                    label=f"Critère d'exclusion du profil : « {criterion} »",
                    impact="gate",
                )
            )
            break

    if assessment.level in config.excluded_seniority:
        gates.append(
            Reason(
                code="seniority",
                label=f"Niveau {assessment.level} hors cible",
                impact="gate",
                detail="Niveau exclu par la configuration.",
            )
        )
    if (
        assessment.years_required
        and assessment.years_required.hard
        and assessment.years_required.years > config.max_required_years
    ):
        gates.append(
            Reason(
                code="years",
                label=f"{assessment.years_required.years:g} ans exigés (au-delà du plafond)",
                impact="gate",
            )
        )

    if job.location and profile.locations and not _location_match(job.location, profile.locations):
        accepts_remote = _accepts(job, profile)
        if not accepts_remote:
            gates.append(
                Reason(
                    code="location",
                    label=f"Localisation non acceptée : {job.location}",
                    impact="gate",
                )
            )

    if (
        job.contract_type
        and profile.contract_types
        and contract_component == 0.0
    ):
        gates.append(
            Reason(
                code="contract",
                label=contract_reason,
                impact="gate",
            )
        )

    if profile.work_authorization:
        auth_match = _AUTH_RE.search(normalize_text(job.description))
        if auth_match:
            required_country = auth_match.group(1).strip()
            required_country = required_country.removeprefix("the ").split()[0]
            declared = normalize_text(profile.work_authorization)
            if required_country and required_country not in declared:
                gates.append(
                    Reason(
                        code="authorization",
                        label=f"Autorisation de travail requise : {required_country}",
                        impact="gate",
                    )
                )

    # --- Score pondéré ---
    weights = config.weights.normalized()
    components = {
        "skills": skills_component,
        "titles": title_component,
        "seniority": seniority_component,
        "experience": experience_component,
        "location": location_component,
        "contract": contract_component,
        "obligations": obligations_component,
    }
    score = round(100 * sum(weights[key] * value for key, value in components.items()))

    reasons.append(
        Reason(
            code="skills",
            label=f"Compétences : {len(matched)}/{len(job_skills)} requises couvertes",
            impact="positive" if skills_component >= 0.6 else "negative",
            detail=", ".join(matched[:6]) or "aucune correspondance détectée",
        )
    )
    if missing:
        reasons.append(
            Reason(
                code="missing_skills",
                label=f"Compétences manquantes : {', '.join(missing[:5])}",
                impact="negative",
            )
        )
    reasons.append(
        Reason(
            code="titles",
            label=f"Intitulé : correspondance {title_component:.0%}",
            impact="positive" if title_component >= 0.5 else "neutral",
        )
    )
    reasons.append(
        Reason(
            code="seniority",
            label=f"Séniorité détectée : {assessment.level}",
            impact="positive" if seniority_component >= 0.7 else "negative",
            detail="; ".join(assessment.evidence[:3]),
        )
    )
    if assessment.years_required:
        reasons.append(
            Reason(
                code="years_required",
                label=(
                    f"{assessment.years_required.years:g} ans "
                    f"{'exigés' if assessment.years_required.hard else 'mentionnés'}"
                ),
                impact="negative" if profile.years_experience < assessment.years_required.years else "positive",
            )
        )
    reasons.append(
        Reason(
            code="location",
            label=location_reason,
            impact="positive" if location_component >= 0.7 else "negative",
        )
    )
    reasons.append(
        Reason(
            code="contract",
            label=contract_reason,
            impact="positive" if contract_component >= 0.7 else "negative",
        )
    )
    if profile.salary_min and job.salary_max and job.salary_max < profile.salary_min:
        reasons.append(
            Reason(
                code="salary",
                label="Salaire maximum inférieur à la prétention",
                impact="negative",
                detail=f"{job.salary_max} < {profile.salary_min} {profile.salary_currency}",
            )
        )

    eligible = not gates
    band = config.thresholds.band(score) if eligible else "low"
    priority = band if eligible else "rejected"
    return ScoreResult(
        score=score,
        band=band,
        priority=priority,
        eligible=eligible,
        components={key: round(value, 3) for key, value in components.items()},
        reasons=[*gates, *reasons],
        matched_skills=matched,
        missing_skills=missing,
        seniority_level=assessment.level,
    )


def _experience_component(profile: ProfileSnapshot, assessment: SeniorityAssessment) -> float:
    required = assessment.years_required or assessment.years_preferred
    if required is None:
        return min(1.0, 0.6 + profile.years_experience / 12)
    ratio = profile.years_experience / required.years if required.years else 1.0
    if assessment.years_required:
        return max(0.1, min(1.0, ratio))
    return max(0.5, min(1.0, 0.7 + 0.3 * ratio))


def _accepts(job: JobSignals, profile: ProfileSnapshot) -> bool:
    preferences = [normalize_remote(item) for item in profile.remote_preferences]
    remote_mode = normalize_remote(job.remote)
    if not preferences:
        return True
    return bool(
        (remote_mode and remote_mode in preferences)
        or ("remote" in preferences and remote_mode == "hybrid")
    )


def _location_component(job: JobSignals, profile: ProfileSnapshot) -> tuple[float, str]:
    if not profile.locations:
        return 0.8, "Aucune localisation imposée par le profil"
    if not job.location:
        return 0.6, "Localisation du poste inconnue"
    if _location_match(job.location, profile.locations):
        return 1.0, f"Localisation compatible : {job.location}"
    if _accepts(job, profile):
        return 0.7, f"Poste à distance compatible ({job.location})"
    return 0.0, f"Localisation non acceptée : {job.location}"


def _contract_component(job: JobSignals, profile: ProfileSnapshot) -> tuple[float, str]:
    if not profile.contract_types:
        return 0.8, "Aucun type de contrat imposé par le profil"
    if not job.contract_type:
        return 0.7, "Type de contrat inconnu"
    job_contract = normalize_contract(job.contract_type)
    accepted = {normalize_contract(item) for item in profile.contract_types}
    if contract_matches(job_contract, accepted):
        return 1.0, f"Contrat compatible : {job.contract_type}"
    return 0.0, f"Contrat non accepté : {job.contract_type}"

