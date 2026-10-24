"""Types partagés du moteur de décision."""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from applyflow.db.models import Profile, Resume

Impact = Literal["positive", "negative", "neutral", "gate"]


class ProfileSnapshot(BaseModel):
    id: str
    name: str
    target_titles: list[str] = Field(default_factory=list)
    technical_skills: list[str] = Field(default_factory=list)
    domain_skills: list[str] = Field(default_factory=list)
    experience_level: str = "junior"
    years_experience: float = 0.0
    locations: list[str] = Field(default_factory=list)
    contract_types: list[str] = Field(default_factory=list)
    remote_preferences: list[str] = Field(default_factory=list)
    salary_min: int | None = None
    salary_max: int | None = None
    salary_currency: str = "EUR"
    exclusion_criteria: list[str] = Field(default_factory=list)
    work_authorization: str | None = None
    resume_id: str | None = None
    resume_filename: str | None = None

    @property
    def all_skills(self) -> list[str]:
        return [*self.technical_skills, *self.domain_skills]


def snapshot_profile(profile: Profile, resume: Resume | None = None) -> ProfileSnapshot:
    active_resume = resume
    if active_resume is None:
        active = [item for item in profile.resumes if item.is_active]
        active_resume = (
            sorted(
                active,
                key=lambda item: (
                    item.uploaded_at.replace(tzinfo=None)
                    if item.uploaded_at and item.uploaded_at.tzinfo
                    else item.uploaded_at
                ),
                reverse=True,
            )[0]
            if active
            else None
        )
    return ProfileSnapshot(
        id=profile.id,
        name=profile.name,
        target_titles=list(profile.target_titles or []),
        technical_skills=list(profile.technical_skills or []),
        domain_skills=list(profile.domain_skills or []),
        experience_level=profile.experience_level,
        years_experience=profile.years_experience,
        locations=list(profile.locations or []),
        contract_types=list(profile.contract_types or []),
        remote_preferences=list(profile.remote_preferences or []),
        salary_min=profile.salary_min,
        salary_max=profile.salary_max,
        salary_currency=profile.salary_currency,
        exclusion_criteria=list(profile.exclusion_criteria or []),
        work_authorization=profile.work_authorization,
        resume_id=active_resume.id if active_resume else None,
        resume_filename=active_resume.filename if active_resume else None,
    )


class Reason(BaseModel):
    code: str
    label: str
    impact: Impact = "neutral"
    detail: str = ""


class ScoreResult(BaseModel):
    score: int = Field(ge=0, le=100)
    band: str
    priority: str
    eligible: bool
    components: dict[str, float] = Field(default_factory=dict)
    reasons: list[Reason] = Field(default_factory=list)
    matched_skills: list[str] = Field(default_factory=list)
    missing_skills: list[str] = Field(default_factory=list)
    seniority_level: str = "unknown"


class RouteCandidate(BaseModel):
    profile_id: str
    profile_name: str
    resume_id: str | None = None
    resume_filename: str | None = None
    score: float
    reasons: list[str] = Field(default_factory=list)


class RouterDecision(BaseModel):
    profile_id: str
    resume_id: str | None = None
    router: str
    confidence: float = Field(ge=0, le=1)
    reasons: list[str] = Field(default_factory=list)
    uncertain: bool = False
    candidates: list[RouteCandidate] = Field(default_factory=list)
