"""Initialisation d'une base de démonstration entièrement locale."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from applyflow.applications.answers import upsert_answer
from applyflow.campaigns.schemas import CampaignInput
from applyflow.campaigns.service import create_campaign
from applyflow.config import PROJECT_ROOT, Settings
from applyflow.db.models import Campaign, Job
from applyflow.jobs.service import collect_jobs, count_jobs
from applyflow.profiles.service import list_profiles, seed_default_profiles, upload_resume
from applyflow.schemas import JobQuery

SAMPLE_CV = PROJECT_ROOT / "playground" / "sample_cv.pdf"


def seed_demo(session: Session, settings: Settings) -> dict[str, Any]:
    created_profiles = seed_default_profiles(session)
    profiles = list_profiles(session)
    resumes = 0
    if SAMPLE_CV.is_file():
        for profile in profiles:
            if any(resume.is_active for resume in profile.resumes):
                continue
            upload_resume(
                session,
                settings,
                profile.id,
                filename=f"cv_{profile.name.replace(' ', '_').replace('/', '-')}.pdf",
                content=SAMPLE_CV.read_bytes(),
            )
            resumes += 1

    jobs_created = 0
    if count_jobs(session) == 0:
        result, _errors = collect_jobs(
            session,
            [{"kind": "fixture"}],
            JobQuery(limit=1000),
            settings,
        )
        jobs_created = result.created

    campaign = session.scalar(select(Campaign).where(Campaign.name == "Campagne démo — Entry level"))
    if campaign is None:
        campaign = create_campaign(
            session,
            CampaignInput(
                name="Campagne démo — Entry level",
                sources=[{"kind": "fixture"}],
                profile_ids=[profile.id for profile in profiles],
                max_jobs=200,
                min_score=65,
            ),
        )

    upsert_answer(
        session,
        question_text="What is your notice period?",
        answer="1 month",
        approved=True,
    )
    upsert_answer(
        session,
        question_text="Earliest start date",
        answer="2026-11-02",
        approved=True,
    )
    session.commit()
    return {
        "profiles_created": len(created_profiles),
        "profiles_total": len(profiles),
        "resumes_created": resumes,
        "jobs_created": jobs_created,
        "jobs_total": count_jobs(session),
        "campaign_id": campaign.id,
    }


def sample_cv_bytes() -> bytes:
    return SAMPLE_CV.read_bytes()


def job_ids(session: Session) -> list[str]:
    return list(session.scalars(select(Job.id)))


__all__ = ["SAMPLE_CV", "Path", "job_ids", "sample_cv_bytes", "seed_demo"]
