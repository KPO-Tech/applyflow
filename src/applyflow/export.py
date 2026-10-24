"""Export des résultats d'une campagne."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from applyflow.db.models import CampaignJob, Profile


def _rows(session: Session, campaign_id: str) -> list[dict[str, Any]]:
    profiles = {profile.id: profile.name for profile in session.scalars(select(Profile))}
    rows: list[dict[str, Any]] = []
    campaign_jobs = session.scalars(
        select(CampaignJob)
        .options(joinedload(CampaignJob.job))
        .where(CampaignJob.campaign_id == campaign_id)
        .order_by(CampaignJob.score.desc())
    )
    for item in campaign_jobs:
        decision = item.decision or {}
        reasons = "; ".join(
            reason.get("label", "") for reason in (item.reasons or []) if reason.get("label")
        )
        rows.append(
            {
                "campaign_id": campaign_id,
                "stage": item.stage,
                "score": item.score,
                "priority": item.priority,
                "eligible": item.eligible,
                "company": item.job.company,
                "title": item.job.title,
                "location": item.job.location,
                "contract_type": item.job.contract_type,
                "seniority": decision.get("seniority_level") or item.job.seniority,
                "url": item.job.url,
                "apply_url": item.job.apply_url,
                "profile": profiles.get(decision.get("profile_id", ""), ""),
                "resume_id": decision.get("resume_id"),
                "router": decision.get("router"),
                "confidence": decision.get("confidence"),
                "uncertain": decision.get("uncertain"),
                "reasons": reasons,
                "error": item.error,
            }
        )
    return rows


def export_campaign(
    session: Session, campaign_id: str, destination: Path, *, fmt: str | None = None
) -> Path:
    fmt = (fmt or destination.suffix.lstrip(".") or "csv").lower()
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    rows = _rows(session, campaign_id)
    if fmt == "json":
        destination.write_text(
            json.dumps(rows, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
        )
        return destination
    if fmt != "csv":
        raise ValueError("format d'export supporté : csv ou json")
    fieldnames = list(rows[0].keys()) if rows else [
        "campaign_id",
        "stage",
        "score",
        "priority",
        "eligible",
        "company",
        "title",
        "location",
        "contract_type",
        "seniority",
        "url",
        "apply_url",
        "profile",
        "resume_id",
        "router",
        "confidence",
        "uncertain",
        "reasons",
        "error",
    ]
    with destination.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    return destination
