"""Campagnes : collecte, analyse et préparation, reprise après interruption."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from applyflow.applications.preparer import DuplicateApplication, prepare_attempt
from applyflow.campaigns.schemas import CampaignInput
from applyflow.config import Settings
from applyflow.db.models import Campaign, CampaignJob, Job, Profile, RoutingDecision
from applyflow.geo import normalize_country
from applyflow.jobs.service import collect_jobs
from applyflow.logging_setup import get_logger
from applyflow.matching.router import build_router
from applyflow.matching.scoring import JobSignals, score_job
from applyflow.matching.seniority import assess_seniority, priority_rank
from applyflow.matching.types import ProfileSnapshot, Reason, snapshot_profile
from applyflow.profiles.service import list_profiles
from applyflow.providers.base import location_matches
from applyflow.schemas import JobQuery
from applyflow.services import record_audit
from applyflow.text import normalize_text

logger = get_logger("campaigns")

STEPS = ("discover", "analyze", "prepare")

# (étape, éléments traités, total) : progression d'une exécution en arrière-plan.
StepProgress = Callable[[str, int, int], None]

_LEVEL_ALIASES = {
    "graduate": "entry",
    "new graduate": "entry",
    "debutant": "entry",
    "premiere experience": "entry",
    "associate": "entry",
    "internship": "intern",
}


class CampaignError(RuntimeError):
    pass


def create_campaign(session: Session, payload: CampaignInput) -> Campaign:
    campaign = Campaign(**payload.model_dump())
    session.add(campaign)
    session.flush()
    record_audit(
        session,
        entity_type="campaign",
        entity_id=campaign.id,
        action="campaign.created",
        data={"name": campaign.name, "max_jobs": campaign.max_jobs},
    )
    return campaign


def list_campaigns(session: Session) -> list[Campaign]:
    return list(session.scalars(select(Campaign).order_by(Campaign.created_at.desc())))


def get_campaign(session: Session, campaign_id: str) -> Campaign:
    campaign = session.get(Campaign, campaign_id)
    if campaign is None:
        raise LookupError(f"campagne introuvable : {campaign_id}")
    return campaign


def pause_campaign(session: Session, campaign_id: str) -> Campaign:
    campaign = get_campaign(session, campaign_id)
    if campaign.status in {"draft", "running", "paused"}:
        campaign.status = "paused"
        record_audit(session, entity_type="campaign", entity_id=campaign.id, action="campaign.paused")
    return campaign


def cancel_campaign(session: Session, campaign_id: str) -> Campaign:
    campaign = get_campaign(session, campaign_id)
    campaign.status = "cancelled"
    campaign.finished_at = datetime.now(UTC)
    record_audit(session, entity_type="campaign", entity_id=campaign.id, action="campaign.cancelled")
    return campaign


def resume_campaign(session: Session, campaign_id: str) -> Campaign:
    campaign = get_campaign(session, campaign_id)
    if campaign.status == "cancelled":
        raise CampaignError("une campagne annulée ne peut pas être reprise")
    campaign.status = "running"
    if campaign.started_at is None:
        campaign.started_at = datetime.now(UTC)
    record_audit(session, entity_type="campaign", entity_id=campaign.id, action="campaign.resumed")
    return campaign


def _allowed_profiles(session: Session, campaign: Campaign) -> list[Profile]:
    profiles = list_profiles(session, active_only=True)
    if campaign.profile_ids:
        wanted = set(campaign.profile_ids)
        profiles = [profile for profile in profiles if profile.id in wanted]
    return profiles


def _count_campaign_jobs(session: Session, campaign_id: str) -> int:
    return int(
        session.scalar(
            select(func.count())
            .select_from(CampaignJob)
            .where(CampaignJob.campaign_id == campaign_id)
        )
        or 0
    )


def _link_jobs(session: Session, campaign: Campaign, job_ids: list[str]) -> int:
    existing = set(
        session.scalars(
            select(CampaignJob.job_id).where(CampaignJob.campaign_id == campaign.id)
        )
    )
    remaining = campaign.max_jobs - len(existing)
    linked = 0
    for job_id in job_ids:
        if remaining <= 0:
            break
        if job_id in existing:
            continue
        session.add(
            CampaignJob(campaign_id=campaign.id, job_id=job_id, stage="discovered")
        )
        existing.add(job_id)
        remaining -= 1
        linked += 1
    return linked


LIBRARY_KIND = "library"


def _library_job_ids(session: Session, campaign: Campaign, spec: dict[str, Any]) -> list[str]:
    """Offres déjà en bibliothèque qui correspondent aux mots-clés et lieux de la campagne.

    Aucune collecte : on reprend ce qui a été collecté depuis l'écran Découverte. Les plus
    récentes d'abord. `config` accepte `country` (code ou liste) et `source_kinds`.
    """
    config = spec.get("config") or {}

    def as_list(value: Any) -> list[str]:
        if not value:
            return []
        return [str(item) for item in (value if isinstance(value, list) else [value])]

    countries = [normalize_country(item) or item.strip().upper() for item in as_list(config.get("country"))]
    kinds = as_list(config.get("source_kinds"))
    keywords = [normalize_text(word) for word in (campaign.keywords or []) if word.strip()]
    statement = select(Job).order_by(Job.collected_at.desc())
    if kinds:
        statement = statement.where(Job.source_kind.in_(kinds))
    if countries:
        statement = statement.where(Job.country.in_(countries))
    selected: list[str] = []
    for job in session.scalars(statement):
        if campaign.locations and not location_matches(
            job.location, list(campaign.locations), country=job.country
        ):
            continue
        if keywords:
            text = normalize_text(f"{job.title} {job.company} {job.description}")
            if not any(word in text for word in keywords):
                continue
        selected.append(job.id)
    return selected


def discover(
    session: Session,
    campaign: Campaign,
    settings: Settings,
    *,
    max_items: int | None = None,
    should_stop: Callable[[], bool] | None = None,
    on_progress: StepProgress | None = None,
) -> dict[str, Any]:
    total = _count_campaign_jobs(session, campaign.id)
    remaining = campaign.max_jobs - total
    summary: dict[str, Any] = {"linked": 0, "created": 0, "duplicates": 0, "errors": []}
    if remaining <= 0:
        return summary

    # On demande un peu plus que nécessaire : une annonce dédoublonnée ne doit pas
    # réduire le nombre d'offres uniques collectées. `max_items` limite l'analyse
    # et la préparation, pas la collecte (déjà plafonnée par max_jobs).
    fetch_limit = min(remaining * 2 + 50, 5000)
    query = JobQuery(
        keywords=list(campaign.keywords or []),
        locations=list(campaign.locations or []),
        limit=fetch_limit,
    )
    sources = list(campaign.sources or [])  # jamais de source fictive par défaut
    library_specs = [spec for spec in sources if spec.get("kind") == LIBRARY_KIND]
    collect_specs = [spec for spec in sources if spec.get("kind") != LIBRARY_KIND]
    summary["from_library"] = 0
    errors: list[str] = []
    job_ids: list[str] = []
    # La bibliothèque passe d'abord : ses offres sont déjà là, sans nouvelle requête réseau.
    for spec in library_specs:
        job_ids.extend(_library_job_ids(session, campaign, spec))
    if collect_specs:
        if on_progress:
            on_progress("discover", 0, len(collect_specs))
        result, errors = collect_jobs(session, collect_specs, query, settings)
        summary["created"] = result.created
        summary["duplicates"] = result.duplicates
        job_ids.extend(result.job_ids)
    summary["errors"] = errors
    before = _count_campaign_jobs(session, campaign.id)
    summary["linked"] = _link_jobs(session, campaign, list(dict.fromkeys(job_ids)))
    if library_specs:
        summary["from_library"] = min(summary["linked"], max(0, _count_campaign_jobs(session, campaign.id) - before))
    if errors:
        campaign.last_error = "; ".join(errors)
    session.flush()
    record_audit(
        session,
        entity_type="campaign",
        entity_id=campaign.id,
        action="campaign.discovered",
        data={"linked": summary["linked"], "errors": errors},
    )
    return summary


def _level_allowed(level: str, campaign_levels: Sequence[str]) -> bool:
    if not campaign_levels:
        return True
    normalized = {_LEVEL_ALIASES.get(value.lower(), value.lower()) for value in campaign_levels}
    return _LEVEL_ALIASES.get(level, level) in normalized


def analyze(
    session: Session,
    campaign: Campaign,
    settings: Settings,
    *,
    max_items: int | None = None,
    should_stop: Callable[[], bool] | None = None,
    redo: bool = False,
    on_progress: StepProgress | None = None,
) -> dict[str, Any]:
    profiles = _allowed_profiles(session, campaign)
    if not profiles:
        raise CampaignError("aucun profil actif autorisé pour cette campagne")
    snapshots = {profile.id: snapshot_profile(profile) for profile in profiles}
    router = build_router(settings)

    rows = list(
        session.scalars(
            select(CampaignJob)
            .options(joinedload(CampaignJob.job))
            .where(
                CampaignJob.campaign_id == campaign.id,
                # `redo` : on réanalyse aussi les offres déjà notées (après un changement de
                # critères), jamais celles déjà préparées ou plus avancées.
                CampaignJob.stage.in_(("discovered", "analyzed", "rejected") if redo else ("discovered",)),
            )
        )
    )
    rows.sort(key=lambda row: priority_rank(assess_seniority(row.job.title, row.job.description).level))

    summary: dict[str, Any] = {"analyzed": 0, "rejected": 0, "errors": 0}
    for index, row in enumerate(rows):
        if max_items is not None and index >= max_items:
            break
        if should_stop and should_stop():
            break
        job = row.job
        session.refresh(campaign)
        if campaign.status != "running":
            break
        try:
            decision = router.route(job, list(snapshots.values()))
            profile_snapshot: ProfileSnapshot = snapshots[decision.profile_id]
            score = score_job(JobSignals.from_any(job), profile_snapshot, settings.scoring)
            level_ok = _level_allowed(score.seniority_level, campaign.experience_levels)
            if not level_ok:
                score.reasons.insert(
                    0,
                    Reason(
                        code="experience_level",
                        label=f"Niveau {score.seniority_level} non autorisé par la campagne",
                        impact="gate",
                    ),
                )
            eligible = score.eligible and level_ok
            row.stage = "analyzed" if eligible else "rejected"
            row.score = float(score.score)
            row.priority = score.priority
            row.eligible = eligible
            row.reasons = [reason.model_dump() for reason in score.reasons]
            row.error = None
            row.decision = {
                "profile_id": decision.profile_id,
                "profile_name": profile_snapshot.name,
                "resume_id": decision.resume_id,
                "router": decision.router,
                "confidence": decision.confidence,
                "uncertain": decision.uncertain,
                "fit_score": score.score,
                "components": score.components,
                "seniority_level": score.seniority_level,
                "min_score": campaign.min_score,
            }
            session.add(
                RoutingDecision(
                    job_id=job.id,
                    profile_id=decision.profile_id,
                    resume_id=decision.resume_id,
                    router=decision.router,
                    confidence=decision.confidence,
                    reasons=[{"text": reason} for reason in decision.reasons],
                    uncertain=decision.uncertain,
                )
            )
            if eligible:
                summary["analyzed"] += 1
            else:
                summary["rejected"] += 1
        except Exception as exc:  # une offre en erreur ne bloque pas la campagne
            row.error = str(exc)[:500]
            summary["errors"] += 1
            logger.warning(
                "analyse impossible",
                extra={"data": {"job_id": job.id, "error": str(exc)}},
            )
        session.commit()
        if on_progress:
            on_progress("analyze", index + 1, len(rows))
        if should_stop and should_stop():
            break

    session.refresh(campaign)
    handled = summary["analyzed"] + summary["rejected"] + summary["errors"]
    summary["remaining"] = max(0, len(rows) - handled)  # laissées de côté par la limite
    return summary


def _is_below_min(row: CampaignJob) -> bool:
    return any(reason.get("code") == "min_score" for reason in (row.reasons or []))


def _can_prepare_now(row: CampaignJob, min_score: int) -> bool:
    if row.stage == "analyzed":
        return True
    return row.stage == "rejected" and _is_below_min(row) and float(row.score or 0) >= min_score


def prepare(
    session: Session,
    campaign: Campaign,
    settings: Settings,
    *,
    max_items: int | None = None,
    should_stop: Callable[[], bool] | None = None,
    on_progress: StepProgress | None = None,
) -> dict[str, Any]:
    rows = list(
        session.scalars(
            select(CampaignJob)
            .options(joinedload(CampaignJob.job))
            .where(
                CampaignJob.campaign_id == campaign.id,
                CampaignJob.stage.in_(("analyzed", "rejected")),
                CampaignJob.eligible.is_(True),
            )
            .order_by(CampaignJob.score.desc())
        )
    )
    # Une offre éligible écartée « sous le score minimal » revient dès que le seuil est abaissé.
    rows = [row for row in rows if _can_prepare_now(row, campaign.min_score)]
    summary: dict[str, Any] = {
        "prepared": 0,
        "needs_review": 0,
        "manual": 0,
        "blocked": 0,
        "duplicates": 0,
        "skipped": 0,
        "errors": 0,
    }
    processed = 0
    for index, row in enumerate(rows):
        if max_items is not None and processed >= max_items:
            break
        if should_stop and should_stop():
            break
        decision = row.decision or {}
        if float(row.score or 0) >= campaign.min_score and _is_below_min(row):
            row.reasons = [r for r in (row.reasons or []) if r.get("code") != "min_score"]
        if float(row.score or 0) < campaign.min_score:
            summary["skipped"] += 1
            row.stage = "rejected"
            row.reasons = [
                *(row.reasons or []),
                Reason(
                    code="min_score",
                    label=f"Score {int(row.score or 0)} < seuil {campaign.min_score}",
                    impact="negative",
                ).model_dump(),
            ]
            session.commit()
            if on_progress:
                on_progress("prepare", index + 1, len(rows))
            continue
        profile = session.get(Profile, decision.get("profile_id") or "")
        if profile is None:
            summary["errors"] += 1
            row.error = "profil de la décision introuvable"
            session.commit()
            continue
        processed += 1
        try:
            attempt = prepare_attempt(
                session,
                settings,
                row.job,
                profile,
                campaign_id=campaign.id,
            )
            row.stage = attempt.status
            row.error = attempt.error
            if attempt.status in summary:
                summary[attempt.status] += 1
        except DuplicateApplication as exc:
            row.stage = "duplicate"
            row.error = str(exc)
            summary["duplicates"] += 1
        except Exception as exc:
            row.error = str(exc)[:500]
            summary["errors"] += 1
            logger.warning(
                "préparation impossible",
                extra={"data": {"job_id": row.job_id, "error": str(exc)}},
            )
        session.commit()
        if on_progress:
            on_progress("prepare", index + 1, len(rows))
        if should_stop and should_stop():
            break

    handled = sum(summary[key] for key in (
        "prepared", "needs_review", "manual", "blocked", "duplicates", "skipped", "errors"
    ))
    summary["remaining"] = max(0, len(rows) - handled)  # laissées de côté par la limite
    session.refresh(campaign)
    return summary


def run_campaign(
    session: Session,
    campaign_id: str,
    settings: Settings,
    *,
    steps: Sequence[str] = STEPS,
    max_items: int | None = None,
    should_stop: Callable[[], bool] | None = None,
    redo: bool = False,
    min_score: int | None = None,
    on_progress: StepProgress | None = None,
) -> dict[str, Any]:
    unknown = set(steps) - set(STEPS)
    if unknown:
        raise CampaignError(f"étapes inconnues : {', '.join(sorted(unknown))}")
    campaign = get_campaign(session, campaign_id)
    if campaign.status == "cancelled":
        raise CampaignError("campagne annulée : créer une nouvelle campagne")
    if min_score is not None:
        campaign.min_score = min_score  # seuil modifiable d'un essai à l'autre
    campaign.status = "running"
    if campaign.started_at is None:
        campaign.started_at = datetime.now(UTC)
    campaign.last_error = None
    session.commit()

    summary: dict[str, Any] = {"campaign_id": campaign.id, "steps": {}, "status": "running"}
    operations = {"discover": discover, "analyze": analyze, "prepare": prepare}
    try:
        for step in steps:
            if should_stop and should_stop():
                break
            session.refresh(campaign)
            if campaign.status != "running":
                break
            if on_progress:
                on_progress(step, 0, 0)
            extra = {"redo": redo} if step == "analyze" else {}
            result = operations[step](
                session,
                campaign,
                settings,
                max_items=max_items,
                should_stop=should_stop,
                on_progress=on_progress,
                **extra,
            )
            summary["steps"][step] = result
            session.commit()
    except Exception as exc:
        # Une étape qui échoue (profil manquant, source en erreur) ne doit pas laisser la
        # campagne « en cours » pour toujours : elle revient en pause, reprenable, avec la cause.
        try:
            session.rollback()
            failed = session.get(Campaign, campaign_id)
            if failed is not None:
                failed.status = "paused"
                failed.last_error = str(exc)[:500]
                record_audit(
                    session,
                    entity_type="campaign",
                    entity_id=failed.id,
                    action="campaign.run_failed",
                    data={"error": failed.last_error},
                )
            session.commit()
        except Exception:  # le compte rendu ne doit jamais masquer l'erreur d'origine
            logger.warning("état de campagne non enregistré après échec", exc_info=True)
        raise

    session.refresh(campaign)
    if campaign.status == "running":
        all_steps = set(steps) == set(STEPS)
        campaign.status = "completed" if all_steps else "paused"
        if campaign.status == "completed":
            campaign.finished_at = datetime.now(UTC)
    summary["status"] = campaign.status
    record_audit(
        session,
        entity_type="campaign",
        entity_id=campaign.id,
        action="campaign.run_finished",
        data={"status": campaign.status, "steps": list(steps)},
    )
    session.commit()
    return summary
