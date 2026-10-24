"""Préparation des candidatures, validation humaine et suivi."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from applyflow.applications.answers import approved_answers
from applyflow.applications.fetcher import (
    DemoAndHttpFetcher,
    FormFetcher,
    FormFetchError,
)
from applyflow.applications.forms import (
    ApplicationPlan,
    FormAnalysisError,
    NoFormFields,
    analyze_html,
    build_plan,
    manual_kit,
    plan_requires_review,
)
from applyflow.config import Settings
from applyflow.db.models import Application, ApplicationAttempt, Job, Profile, Resume
from applyflow.logging_setup import get_logger
from applyflow.profiles.service import active_resume
from applyflow.services import record_audit

logger = get_logger("applications")

# `approved` reste visible dans la file : c'est l'étape où la personne soumet la
# candidature puis enregistre la soumission (aucune soumission automatique).
PENDING_STATUSES = ("prepared", "needs_review", "manual", "blocked", "approved")


class PreparationError(RuntimeError):
    pass


class DuplicateApplication(PreparationError):
    pass


class SubmissionNotAllowed(PreparationError):
    pass


def idempotency_key(job_id: str, profile_id: str, resume_id: str | None, mode: str) -> str:
    raw = f"{job_id}:{profile_id}:{resume_id or 'no-resume'}:{mode}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def prepare_attempt(
    session: Session,
    settings: Settings,
    job: Job,
    profile: Profile,
    *,
    campaign_id: str | None = None,
    mode: str | None = None,
    fetcher: FormFetcher | None = None,
    force: bool = False,
) -> ApplicationAttempt:
    existing_application = session.scalar(
        select(Application).where(Application.job_id == job.id)
    )
    if existing_application is not None and not force:
        raise DuplicateApplication(
            f"une candidature existe déjà pour cette offre ({existing_application.status})"
        )

    resume: Resume | None = active_resume(profile)
    mode = mode or ("dry_run" if settings.application.dry_run else "live")
    key = idempotency_key(job.id, profile.id, resume.id if resume else None, mode)
    attempt = session.scalar(
        select(ApplicationAttempt).where(ApplicationAttempt.idempotency_key == key)
    )
    if attempt is not None and attempt.status in {"approved", "submitted"} and not force:
        return attempt
    if attempt is None:
        attempt = ApplicationAttempt(
            campaign_id=campaign_id,
            job_id=job.id,
            profile_id=profile.id,
            resume_id=resume.id if resume else None,
            mode=mode,
            idempotency_key=key,
        )
        session.add(attempt)

    form_url = job.apply_url or job.url
    plan = ApplicationPlan(source_url=form_url, mode=mode)
    analysis = None
    error: str | None = None
    manual = False
    rendered = False
    reader = fetcher or DemoAndHttpFetcher(settings)
    try:
        form = reader.fetch(form_url)
        try:
            analysis = analyze_html(form.html, form.url)
        except NoFormFields:
            # Un ATS construit son formulaire en JavaScript : la page servie n'a aucun champ.
            # On la relit dans un navigateur avant de conclure qu'il faut postuler à la main.
            render = getattr(reader, "render", None)
            if render is None:
                raise
            rendered_form = render(form_url)
            analysis = analyze_html(rendered_form.html, rendered_form.url)
            rendered = True
        plan = build_plan(
            analysis,
            profile=profile,
            resume=resume,
            answers=approved_answers(session),
            resume_path=str(settings.data_dir / resume.stored_path) if resume else None,
            mode=mode,
        )
        if rendered:
            plan.warnings.append(
                "Formulaire lu dans un navigateur : la page le construit en JavaScript."
            )
    except NoFormFields:
        # Page lue, mais sans formulaire lisible (connexion, JavaScript) : candidature à la main.
        manual = True
        plan.warnings.append(
            "Formulaire non lisible automatiquement (connexion ou JavaScript requis) : "
            "postulez à la main avec le dossier ci-dessous."
        )
    except (FormFetchError, FormAnalysisError) as exc:
        error = str(exc)
        plan.warnings.append(error)
    except Exception as exc:  # formulaire exotique : ne pas perdre la trace
        error = f"échec de préparation : {exc}"
        logger.exception("échec de préparation", extra={"data": {"job_id": job.id}})

    if manual:
        status = "manual"
        plan.can_prepare = False
        plan.blocked_reason = None
    elif error:
        status = "blocked"
        plan.can_prepare = False
        plan.blocked_reason = error
    elif not plan.can_prepare:
        status = "blocked"
    elif plan_requires_review(plan):
        status = "needs_review"
    else:
        status = "prepared"

    if status in {"manual", "blocked"}:
        plan.manual_kit = manual_kit(profile)
    attempt.mode = mode
    attempt.status = status
    attempt.error = error
    attempt.plan = plan.model_dump()
    attempt.unknown_questions = [question.model_dump() for question in plan.unknown_questions]
    attempt.form_snapshot = analysis.model_dump() if analysis else {}
    attempt.resume_id = resume.id if resume else None
    session.flush()
    record_audit(
        session,
        entity_type="application_attempt",
        entity_id=attempt.id,
        action="application.prepared",
        data={
            "job_id": job.id,
            "profile_id": profile.id,
            "status": status,
            "mode": mode,
            "fills": len(plan.fills),
        },
    )
    logger.info(
        "candidature préparée",
        extra={"data": {"attempt_id": attempt.id, "status": status, "job_id": job.id}},
    )
    return attempt


def approve_attempt(session: Session, attempt: ApplicationAttempt) -> Application:
    if attempt.status != "prepared":
        raise SubmissionNotAllowed(
            f"seule une candidature préparée peut être validée (statut : {attempt.status})"
        )
    required_unknowns = [
        question for question in attempt.unknown_questions if question.get("required")
    ]
    if required_unknowns:
        raise SubmissionNotAllowed("des questions obligatoires restent sans réponse")

    application = session.scalar(select(Application).where(Application.job_id == attempt.job_id))
    if application is None:
        application = Application(
            job_id=attempt.job_id,
            profile_id=attempt.profile_id,
            resume_id=attempt.resume_id,
            campaign_id=attempt.campaign_id,
            attempt_id=attempt.id,
            status="prepared",
        )
        session.add(application)
        session.flush()
    attempt.status = "approved"
    record_audit(
        session,
        entity_type="application",
        entity_id=application.id,
        action="application.approved",
        data={"job_id": attempt.job_id, "profile_id": attempt.profile_id},
    )
    return application


def record_submission(
    session: Session,
    attempt: ApplicationAttempt,
    *,
    confirmed: bool,
    reference: str | None = None,
) -> Application:
    if not confirmed:
        raise SubmissionNotAllowed("une confirmation explicite est requise")
    # « manual » et « blocked » : le formulaire n'est pas lisible, vous avez postulé à la main.
    # « needs_review » : une question obligatoire restait ouverte, vous avez tout de même
    # envoyé la candidature vous-même — le suivi doit pouvoir commencer.
    if attempt.status not in {"approved", "manual", "blocked", "needs_review"}:
        raise SubmissionNotAllowed(
            f"la candidature doit être validée avant enregistrement (statut : {attempt.status})"
        )
    application = session.scalar(select(Application).where(Application.job_id == attempt.job_id))
    if application is None:
        application = Application(
            job_id=attempt.job_id,
            profile_id=attempt.profile_id,
            resume_id=attempt.resume_id,
            campaign_id=attempt.campaign_id,
            attempt_id=attempt.id,
            status="prepared",
        )
        session.add(application)
    if application.status in {"submitted", "withdrawn"}:
        raise DuplicateApplication("cette offre a déjà été enregistrée comme soumise")
    application.status = "submitted"
    application.submitted_at = datetime.now(UTC)
    application.external_reference = reference or application.external_reference
    attempt.status = "submitted"
    session.flush()
    record_audit(
        session,
        entity_type="application",
        entity_id=application.id,
        action="application.submitted",
        data={"job_id": attempt.job_id, "reference": reference},
    )
    return application


def update_application_status(session: Session, application_id: str, status: str) -> Application:
    allowed = {"prepared", "submitted", "interview", "offer", "rejected", "withdrawn"}
    if status not in allowed:
        raise ValueError(f"statut inconnu : {status}")
    application = session.get(Application, application_id)
    if application is None:
        raise LookupError(f"candidature introuvable : {application_id}")
    application.status = status
    record_audit(
        session,
        entity_type="application",
        entity_id=application.id,
        action="application.status_changed",
        data={"status": status},
    )
    return application


def list_attempts(
    session: Session, *, statuses: tuple[str, ...] = PENDING_STATUSES, limit: int = 200
) -> list[ApplicationAttempt]:
    return list(
        session.scalars(
            select(ApplicationAttempt)
            .where(ApplicationAttempt.status.in_(statuses))
            .order_by(ApplicationAttempt.updated_at.desc())
            .limit(limit)
        )
    )


def list_applications(session: Session, limit: int = 500) -> list[Application]:
    return list(
        session.scalars(
            select(Application).order_by(Application.created_at.desc()).limit(limit)
        )
    )


def get_attempt(session: Session, attempt_id: str) -> ApplicationAttempt:
    attempt = session.get(ApplicationAttempt, attempt_id)
    if attempt is None:
        raise LookupError(f"tentative introuvable : {attempt_id}")
    return attempt
