"""Sérialisation JSON des entités."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from applyflow.db.models import (
    Application,
    ApplicationAttempt,
    Campaign,
    CampaignJob,
    Job,
    Profile,
    Resume,
)


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def resume_dict(resume: Resume) -> dict[str, Any]:
    return {
        "id": resume.id,
        "filename": resume.filename,
        "size_bytes": resume.size_bytes,
        "sha256": resume.sha256,
        "is_active": resume.is_active,
        "uploaded_at": _iso(resume.uploaded_at),
    }


def profile_dict(profile: Profile) -> dict[str, Any]:
    return {
        "id": profile.id,
        "name": profile.name,
        "full_name": profile.full_name,
        "email": profile.email,
        "phone": profile.phone,
        "city": profile.city,
        "linkedin_url": profile.linkedin_url,
        "github_url": profile.github_url,
        "website": profile.website,
        "other_links": profile.other_links or [],
        "target_titles": profile.target_titles,
        "technical_skills": profile.technical_skills,
        "domain_skills": profile.domain_skills,
        "experience_level": profile.experience_level,
        "years_experience": profile.years_experience,
        "locations": profile.locations,
        "contract_types": profile.contract_types,
        "remote_preferences": profile.remote_preferences,
        "salary_min": profile.salary_min,
        "salary_max": profile.salary_max,
        "salary_currency": profile.salary_currency,
        "exclusion_criteria": profile.exclusion_criteria,
        "work_authorization": profile.work_authorization,
        "active": profile.active,
        "resumes": [resume_dict(resume) for resume in profile.resumes],
    }


def job_dict(job: Job, *, include_description: bool = False) -> dict[str, Any]:
    payload = {
        "id": job.id,
        "source": job.source_kind,
        "external_id": job.external_id,
        "url": job.url,
        "apply_url": job.apply_url,
        "company": job.company,
        "title": job.title,
        "location": job.location,
        "country": job.country,
        "remote": job.remote,
        "salary_min": job.salary_min,
        "salary_max": job.salary_max,
        "salary_currency": job.salary_currency,
        "contract_type": job.contract_type,
        "seniority": job.seniority,
        "skills": job.required_skills,
        "published_at": _iso(job.published_at),
        "collected_at": _iso(job.collected_at),
    }
    if include_description:
        payload["description"] = job.description
    return payload


def campaign_dict(campaign: Campaign) -> dict[str, Any]:
    return {
        "id": campaign.id,
        "name": campaign.name,
        "status": campaign.status,
        "sources": campaign.sources,
        "profile_ids": campaign.profile_ids,
        "locations": campaign.locations,
        "keywords": campaign.keywords,
        "experience_levels": campaign.experience_levels,
        "max_jobs": campaign.max_jobs,
        "min_score": campaign.min_score,
        "exclusions": campaign.exclusions,
        "created_at": _iso(campaign.created_at),
        "started_at": _iso(campaign.started_at),
        "finished_at": _iso(campaign.finished_at),
        "last_error": campaign.last_error,
    }


def campaign_job_dict(row: CampaignJob, job: Job | None = None) -> dict[str, Any]:
    job = job or row.job
    return {
        "id": row.id,
        "job_id": row.job_id,
        "stage": row.stage,
        "score": row.score,
        "priority": row.priority,
        "eligible": row.eligible,
        "reasons": row.reasons,
        "decision": row.decision,
        "error": row.error,
        "job": job_dict(job) if job else None,
    }


def attempt_dict(session: Session, attempt: ApplicationAttempt) -> dict[str, Any]:
    job = session.get(Job, attempt.job_id)
    profile = session.get(Profile, attempt.profile_id)
    return {
        "id": attempt.id,
        "campaign_id": attempt.campaign_id,
        "job_id": attempt.job_id,
        "profile_id": attempt.profile_id,
        "resume_id": attempt.resume_id,
        "mode": attempt.mode,
        "status": attempt.status,
        "plan": attempt.plan,
        "unknown_questions": attempt.unknown_questions,
        "error": attempt.error,
        "created_at": _iso(attempt.created_at),
        "updated_at": _iso(attempt.updated_at),
        "job": job_dict(job) if job else None,
        "profile_name": profile.name if profile else None,
    }


def application_dict(session: Session, application: Application) -> dict[str, Any]:
    job = session.get(Job, application.job_id)
    profile = session.get(Profile, application.profile_id)
    return {
        "id": application.id,
        "job_id": application.job_id,
        "profile_id": application.profile_id,
        "resume_id": application.resume_id,
        "campaign_id": application.campaign_id,
        "status": application.status,
        "submitted_at": _iso(application.submitted_at),
        "external_reference": application.external_reference,
        "notes": application.notes,
        "created_at": _iso(application.created_at),
        "job": job_dict(job) if job else None,
        "profile_name": profile.name if profile else None,
    }
