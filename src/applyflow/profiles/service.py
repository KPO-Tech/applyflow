"""Gestion des profils et des CV PDF (jamais modifiés par le système)."""

from __future__ import annotations

import hashlib
from pathlib import Path

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from applyflow.config import Settings
from applyflow.db.models import Profile, Resume
from applyflow.logging_setup import get_logger
from applyflow.profiles.schemas import ProfileInput
from applyflow.services import ensure_local_user, record_audit

logger = get_logger("profiles")


class ResumeValidationError(ValueError):
    pass


def list_profiles(session: Session, *, active_only: bool = True) -> list[Profile]:
    query = select(Profile).order_by(Profile.created_at)
    if active_only:
        query = query.where(Profile.active.is_(True))
    return list(session.scalars(query))


def get_profile(session: Session, profile_id: str) -> Profile:
    profile = session.get(Profile, profile_id)
    if profile is None:
        raise LookupError(f"profil introuvable : {profile_id}")
    return profile


def create_profile(session: Session, payload: ProfileInput) -> Profile:
    user = ensure_local_user(session)
    profile = Profile(user_id=user.id, **payload.model_dump())
    session.add(profile)
    session.flush()
    record_audit(
        session,
        entity_type="profile",
        entity_id=profile.id,
        action="profile.created",
        data={"name": profile.name},
    )
    logger.info("profil créé", extra={"data": {"profile_id": profile.id}})
    return profile


def update_profile(session: Session, profile_id: str, payload: ProfileInput) -> Profile:
    profile = get_profile(session, profile_id)
    for field, value in payload.model_dump().items():
        setattr(profile, field, value)
    record_audit(
        session,
        entity_type="profile",
        entity_id=profile.id,
        action="profile.updated",
        data={"name": profile.name},
    )
    return profile


def set_active(session: Session, profile_id: str, active: bool) -> Profile:
    profile = get_profile(session, profile_id)
    profile.active = active
    record_audit(
        session,
        entity_type="profile",
        entity_id=profile.id,
        action="profile.activated" if active else "profile.deactivated",
    )
    return profile


def upload_resume(
    session: Session,
    settings: Settings,
    profile_id: str,
    *,
    filename: str,
    content: bytes,
) -> Resume:
    profile = get_profile(session, profile_id)
    max_bytes = settings.application.max_resume_mb * 1024 * 1024
    if not content:
        raise ResumeValidationError("fichier vide")
    if len(content) > max_bytes:
        raise ResumeValidationError(
            f"fichier trop volumineux (max {settings.application.max_resume_mb} Mo)"
        )
    if not content.startswith(b"%PDF-"):
        raise ResumeValidationError("seul un CV PDF est accepté (en-tête %PDF manquant)")
    digest = hashlib.sha256(content).hexdigest()
    existing = session.scalar(
        select(Resume).where(Resume.profile_id == profile.id, Resume.sha256 == digest)
    )
    if existing is not None:
        session.execute(
            update(Resume).where(Resume.profile_id == profile.id).values(is_active=False)
        )
        existing.is_active = True
        session.flush()
        session.expire(profile, ["resumes"])
        return existing

    resume = Resume(
        profile_id=profile.id,
        filename=Path(filename).name or "cv.pdf",
        stored_path="",
        sha256=digest,
        size_bytes=len(content),
        is_active=True,
    )
    session.add(resume)
    session.flush()
    relative = Path("resumes") / f"{resume.id}.pdf"
    target = settings.data_dir / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(content)
    resume.stored_path = relative.as_posix()
    session.execute(
        update(Resume).where(Resume.profile_id == profile.id).values(is_active=False)
    )
    resume.is_active = True
    session.flush()
    session.expire(profile, ["resumes"])
    record_audit(
        session,
        entity_type="resume",
        entity_id=resume.id,
        action="resume.uploaded",
        data={"profile_id": profile.id, "filename": resume.filename, "sha256": digest},
    )
    logger.info(
        "CV importé", extra={"data": {"resume_id": resume.id, "profile_id": profile.id}}
    )
    return resume


def _uploaded_at_key(resume: Resume):
    """SQLite renvoie des datetimes naïfs : normaliser avant tout tri."""
    value = resume.uploaded_at
    return value.replace(tzinfo=None) if value and value.tzinfo else value


def active_resume(profile: Profile) -> Resume | None:
    resumes = [resume for resume in profile.resumes if resume.is_active]
    if not resumes:
        return None
    return sorted(resumes, key=_uploaded_at_key, reverse=True)[0]


def resume_path(settings: Settings, resume: Resume) -> Path:
    return settings.data_dir / resume.stored_path


DEFAULT_PROFILE_DATA = [
    {
        "name": "Data Engineer",
        "full_name": "Camille Martin",
        "email": "camille.martin@example.invalid",
        "phone": "+33 6 12 34 56 78",
        "city": "Paris",
        "target_titles": ["Data Engineer", "Analytics Engineer", "Data Platform Engineer"],
        "technical_skills": [
            "Python", "SQL", "PostgreSQL", "Airflow", "dbt", "Spark", "Snowflake",
            "Docker", "AWS", "Git",
        ],
        "domain_skills": ["finance", "retail"],
        "experience_level": "junior",
        "years_experience": 2,
        "locations": ["France", "Paris", "Remote"],
        "contract_types": ["CDI", "CDD"],
        "remote_preferences": ["hybrid", "remote"],
        "salary_min": 42000,
        "salary_max": 52000,
        "work_authorization": "France / Union européenne",
    },
    {
        "name": "Data Analyst / BI Analyst",
        "full_name": "Camille Martin",
        "email": "camille.martin@example.invalid",
        "phone": "+33 6 12 34 56 78",
        "city": "Paris",
        "target_titles": ["Data Analyst", "BI Analyst", "Business Intelligence Analyst"],
        "technical_skills": ["SQL", "Power BI", "Tableau", "Excel", "Python", "dbt", "Statistics"],
        "domain_skills": ["marketing", "retail", "ecommerce"],
        "experience_level": "junior",
        "years_experience": 2,
        "locations": ["France", "Paris", "Remote"],
        "contract_types": ["CDI", "CDD"],
        "remote_preferences": ["hybrid", "remote"],
        "salary_min": 38000,
        "salary_max": 46000,
        "work_authorization": "France / Union européenne",
    },
    {
        "name": "AI Engineer",
        "full_name": "Camille Martin",
        "email": "camille.martin@example.invalid",
        "phone": "+33 6 12 34 56 78",
        "city": "Paris",
        "target_titles": ["AI Engineer", "Machine Learning Engineer", "ML Engineer"],
        "technical_skills": [
            "Python", "PyTorch", "scikit-learn", "LLM", "NLP", "Docker", "FastAPI",
            "MLflow", "Git", "SQL",
        ],
        "domain_skills": ["healthcare", "saas"],
        "experience_level": "junior",
        "years_experience": 2,
        "locations": ["France", "Paris", "Remote"],
        "contract_types": ["CDI"],
        "remote_preferences": ["hybrid", "remote"],
        "salary_min": 45000,
        "salary_max": 55000,
        "work_authorization": "France / Union européenne",
    },
    {
        "name": "Data Scientist",
        "full_name": "Camille Martin",
        "email": "camille.martin@example.invalid",
        "phone": "+33 6 12 34 56 78",
        "city": "Paris",
        "target_titles": ["Data Scientist", "Applied Scientist", "Decision Scientist"],
        "technical_skills": [
            "Python", "Statistics", "scikit-learn", "pandas", "SQL", "A/B testing",
            "Machine Learning", "MLflow",
        ],
        "domain_skills": ["marketing", "finance", "ecommerce"],
        "experience_level": "junior",
        "years_experience": 2,
        "locations": ["France", "Paris", "Remote"],
        "contract_types": ["CDI"],
        "remote_preferences": ["hybrid", "remote"],
        "salary_min": 42000,
        "salary_max": 50000,
        "work_authorization": "France / Union européenne",
    },
    {
        "name": "Python Developer",
        "full_name": "Camille Martin",
        "email": "camille.martin@example.invalid",
        "phone": "+33 6 12 34 56 78",
        "city": "Lyon",
        "target_titles": ["Python Developer", "Backend Developer", "Software Engineer Python"],
        "technical_skills": ["Python", "FastAPI", "Django", "PostgreSQL", "Docker", "REST API", "Git", "pytest"],
        "domain_skills": ["saas", "b2b"],
        "experience_level": "junior",
        "years_experience": 2,
        "locations": ["France", "Lyon", "Remote"],
        "contract_types": ["CDI", "CDD", "freelance"],
        "remote_preferences": ["hybrid", "remote"],
        "salary_min": 38000,
        "salary_max": 48000,
        "work_authorization": "France / Union européenne",
    },
]


def seed_default_profiles(session: Session) -> list[Profile]:
    existing = {profile.name for profile in list_profiles(session, active_only=False)}
    created: list[Profile] = []
    for data in DEFAULT_PROFILE_DATA:
        if data["name"] in existing:
            continue
        created.append(create_profile(session, ProfileInput(**data)))
    return created
