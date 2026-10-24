"""Routage profil/CV : routeur déterministe et fabrique avec fallback."""

from __future__ import annotations

from typing import Any, Protocol

from applyflow.config import RouterConfig
from applyflow.logging_setup import get_logger
from applyflow.matching.scoring import JobSignals, _title_similarity
from applyflow.matching.skills import canonicalize_skills, extract_skills, skill_overlap
from applyflow.matching.types import ProfileSnapshot, RouteCandidate, RouterDecision
from applyflow.text import contains_phrase

logger = get_logger("router")


class RouterUnavailable(RuntimeError):
    """Le routeur configuré n'est pas disponible ; le fallback est autorisé."""


class ResumeRouter(Protocol):
    name: str

    def route(self, job: Any, profiles: list[ProfileSnapshot]) -> RouterDecision: ...


class DeterministicRouter:
    """Routeur explicable basé sur les intitulés, les compétences et le niveau."""

    name = "deterministic"

    def __init__(self, *, uncertainty_margin: float = 0.08) -> None:
        self.uncertainty_margin = uncertainty_margin

    def route(self, job: Any, profiles: list[ProfileSnapshot]) -> RouterDecision:
        if not profiles:
            raise RouterUnavailable("aucun profil actif disponible pour le routage")
        signals = JobSignals.from_any(job)
        job_text = f"{signals.title} {signals.description}"
        job_skills = canonicalize_skills(signals.skills) or extract_skills(job_text)

        candidates: list[RouteCandidate] = []
        for profile in profiles:
            title_score = max(
                (_title_similarity(target, signals.title) for target in profile.target_titles),
                default=0.0,
            )
            profile_skills = canonicalize_skills(profile.all_skills)
            coverage_job, matched, _ = skill_overlap(profile_skills, job_skills)
            profile_in_job = (
                len([skill for skill in profile_skills if contains_phrase(job_text, skill)])
                / len(profile_skills)
                if profile_skills
                else 0.0
            )
            skill_score = 0.6 * coverage_job + 0.4 * profile_in_job
            level_score = _level_alignment(profile, job_text)
            score = 0.45 * title_score + 0.45 * skill_score + 0.10 * level_score
            reasons = [
                f"intitulé : {title_score:.0%} de correspondance",
                f"compétences : {len(matched)}/{len(job_skills) or 0} requises"
                if job_skills
                else "compétences : aucune exigence explicite",
            ]
            candidates.append(
                RouteCandidate(
                    profile_id=profile.id,
                    profile_name=profile.name,
                    resume_id=profile.resume_id,
                    resume_filename=profile.resume_filename,
                    score=round(score, 4),
                    reasons=reasons,
                )
            )

        candidates.sort(key=lambda candidate: candidate.score, reverse=True)
        best = candidates[0]
        second_score = candidates[1].score if len(candidates) > 1 else None
        margin = best.score - second_score if second_score is not None else None
        confidence = (
            0.6 if margin is None else round(min(0.95, 0.5 + max(0.0, margin) * 2), 3)
        )
        uncertain = best.score < 0.25 or (
            margin is not None and margin < self.uncertainty_margin
        )

        reasons = list(best.reasons)
        if best.resume_id is None:
            reasons.append("aucun CV actif associé à ce profil")
        if uncertain:
            reasons.append("choix incertain : scores proches ou correspondance faible")

        return RouterDecision(
            profile_id=best.profile_id,
            resume_id=best.resume_id,
            router=self.name,
            confidence=confidence,
            reasons=reasons,
            uncertain=uncertain,
            candidates=candidates,
        )


class FallbackRouter:
    """Essaie le routeur principal puis retombe sur le déterministe, sans échouer la campagne."""

    name = "fallback"

    def __init__(self, primary: ResumeRouter, fallback: ResumeRouter) -> None:
        self.primary = primary
        self.fallback = fallback

    def route(self, job: Any, profiles: list[ProfileSnapshot]) -> RouterDecision:
        try:
            return self.primary.route(job, profiles)
        except RouterUnavailable as exc:
            logger.warning(
                "routeur indisponible, fallback déterministe",
                extra={"data": {"router": self.primary.name, "error": str(exc)}},
            )
            decision = self.fallback.route(job, profiles)
            decision.reasons.insert(0, f"Fallback déterministe ({exc})")
            decision.router = f"{self.fallback.name} (fallback: {self.primary.name})"
            return decision


def _level_alignment(profile: ProfileSnapshot, job_text: str) -> float:
    from applyflow.matching.seniority import assess_seniority

    level = assess_seniority(job_text[:400]).level
    if profile.experience_level in {"entry", "intern"}:
        return {"intern": 1.0, "entry": 1.0, "junior": 0.9, "unknown": 0.7}.get(level, 0.3)
    if profile.experience_level == "junior":
        return {"entry": 0.9, "junior": 1.0, "mid": 0.8, "unknown": 0.7}.get(level, 0.4)
    if profile.experience_level in {"mid", "senior"}:
        return {"mid": 1.0, "senior": 0.9, "junior": 0.6, "unknown": 0.7}.get(level, 0.5)
    return 0.6


def build_router(settings: Any) -> ResumeRouter:
    config: RouterConfig = settings.router
    deterministic = DeterministicRouter(uncertainty_margin=config.uncertainty_margin)
    if config.provider == "deterministic":
        return deterministic

    from applyflow.matching.laya_router import LayaRouter, RemoteRouter

    if config.provider == "laya":
        primary: ResumeRouter = LayaRouter(config)
    else:
        primary = RemoteRouter(config, name="remote")
    if config.fallback_to_deterministic:
        return FallbackRouter(primary, deterministic)
    return primary
