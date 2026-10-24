"""Agrégats du tableau de bord."""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from applyflow.db.models import (
    Application,
    ApplicationAttempt,
    CampaignJob,
    Job,
    Profile,
)

ANALYZED_STAGES = (
    "analyzed",
    "rejected",
    "prepared",
    "needs_review",
    "manual",
    "blocked",
    "duplicate",
    "approved",
    "submitted",
)


def dashboard_metrics(session: Session) -> dict[str, object]:
    jobs_collected = int(session.scalar(select(func.count()).select_from(Job)) or 0)
    jobs_analyzed = int(
        session.scalar(
            select(func.count(func.distinct(CampaignJob.job_id))).where(
                CampaignJob.stage.in_(ANALYZED_STAGES)
            )
        )
        or 0
    )
    relevant = int(
        session.scalar(
            select(func.count(func.distinct(CampaignJob.job_id))).where(
                CampaignJob.eligible.is_(True)
            )
        )
        or 0
    )
    prepared = int(
        session.scalar(
            select(func.count())
            .select_from(ApplicationAttempt)
            .where(ApplicationAttempt.status.in_(("prepared", "needs_review", "manual", "approved")))
        )
        or 0
    )
    submitted = int(
        session.scalar(
            select(func.count()).select_from(Application).where(Application.status == "submitted")
        )
        or 0
    )
    failures = int(
        session.scalar(
            select(func.count())
            .select_from(ApplicationAttempt)
            .where(ApplicationAttempt.status == "blocked")
        )
        or 0
    ) + int(
        session.scalar(
            select(func.count()).select_from(CampaignJob).where(CampaignJob.error.is_not(None))
        )
        or 0
    )

    per_profile: dict[str, int] = {}
    profiles = {profile.id: profile.name for profile in session.scalars(select(Profile))}
    for campaign_job in session.scalars(
        select(CampaignJob).where(CampaignJob.decision.is_not(None))
    ):
        decision = campaign_job.decision or {}
        profile_id = decision.get("profile_id")
        if profile_id:
            per_profile[profile_id] = per_profile.get(profile_id, 0) + 1
    profile_rows = [
        {"profile_id": profile_id, "name": profiles.get(profile_id, profile_id), "jobs": count}
        for profile_id, count in sorted(per_profile.items(), key=lambda item: -item[1])
    ]

    return {
        "jobs_collected": jobs_collected,
        "jobs_analyzed": jobs_analyzed,
        "jobs_relevant": relevant,
        "applications_prepared": prepared,
        "applications_submitted": submitted,
        "failures": failures,
        "per_profile": profile_rows,
    }


def campaign_stage_counts(session: Session, campaign_id: str) -> dict[str, int]:
    rows = session.execute(
        select(CampaignJob.stage, func.count())
        .where(CampaignJob.campaign_id == campaign_id)
        .group_by(CampaignJob.stage)
    ).all()
    return {str(stage): int(count) for stage, count in rows}
