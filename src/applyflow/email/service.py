"""Synchronisation de la boîte, rattachement aux candidatures et relances."""

from __future__ import annotations

import re
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from applyflow.applications.preparer import update_application_status
from applyflow.config import Settings
from applyflow.db.models import Application, EmailMessage, Job, Profile
from applyflow.email.account import load_credentials, mark_synced, secret_storage
from applyflow.email.classify import classify, fold
from applyflow.email.gmail import InboundEmail, MailboxError, fetch_messages
from applyflow.logging_setup import get_logger
from applyflow.services import record_audit

logger = get_logger("email")

REPLY_LABELS = ("interview", "offer", "rejected")
CLASSIFICATIONS = ("interview", "offer", "rejected", "acknowledgement", "other")
UNSET = object()

_LEGAL_SUFFIXES = {
    "sas",
    "sa",
    "sarl",
    "sasu",
    "gmbh",
    "inc",
    "ltd",
    "llc",
    "bv",
    "ag",
    "plc",
    "corp",
    "group",
    "groupe",
    "france",
}
_TITLE_STOPWORDS = {
    "pour",
    "avec",
    "dans",
    "chez",
    "des",
    "les",
    "une",
    "and",
    "the",
    "for",
    "job",
    "poste",
    "offre",
}


class MailboxNotConnected(RuntimeError):
    """Aucun identifiant Gmail enregistré."""


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def _company_parts(name: str) -> tuple[str, list[str]]:
    folded = fold(name)
    cleaned = re.sub(r"[^a-z0-9 ]", " ", folded)
    tokens = [token for token in cleaned.split() if token and token not in _LEGAL_SUFFIXES]
    return "".join(tokens), tokens


def _title_tokens(title: str) -> list[str]:
    folded = fold(title)
    tokens = [
        token
        for token in re.findall(r"[a-z0-9]{3,}", folded)
        if token not in _TITLE_STOPWORDS
    ]
    return tokens[:6]


def match_application(
    session: Session,
    *,
    subject: str,
    body: str,
    sender_email: str,
    sender_name: str = "",
    now: datetime | None = None,
) -> tuple[Application | None, str | None]:
    """Rattache un message à une candidature, avec des indices lisibles."""
    now = now or datetime.now(UTC)
    subject_key = fold(subject)
    body_key = fold(body)
    domain = sender_email.split("@")[-1].lower() if "@" in sender_email else ""
    sender_key = fold(sender_name)

    rows = session.execute(
        select(Application, Job)
        .join(Job, Job.id == Application.job_id)
        .where(Application.status.in_(("submitted", "interview", "offer", "rejected")))
        .order_by(Application.created_at.desc())
        .limit(300)
    ).all()
    scored: list[tuple[int, Application, list[str]]] = []
    for application, job in rows:
        submitted = _aware(application.submitted_at or application.created_at)
        if submitted is not None and (now - submitted).days > 180:
            continue
        compact, company_tokens = _company_parts(job.company or "")
        if len(compact) < 3:
            continue
        score = 0
        reasons: list[str] = []

        if domain and compact in domain:
            score += 3
            reasons.append(f"domaine {domain}")
        elif domain and any(len(token) >= 5 and token in domain for token in company_tokens):
            score += 1
            reasons.append(f"domaine {domain}")

        if len(compact) >= 4 and compact in subject_key:
            score += 3
            reasons.append("entreprise dans l'objet")
        elif company_tokens and len(company_tokens) <= 3 and all(
            token in subject_key for token in company_tokens
        ):
            score += 2
            reasons.append("entreprise dans l'objet")

        if len(compact) >= 4 and compact in body_key:
            score += 1

        title_tokens = _title_tokens(job.title or "")
        if title_tokens:
            in_subject = [token for token in title_tokens if token in subject_key]
            in_body = [token for token in title_tokens if token in body_key]
            if len(in_subject) >= max(2, len(title_tokens) - 1):
                score += 3
                reasons.append("intitulé du poste dans l'objet")
            elif in_subject:
                score += 1
            if in_body and len(in_body) >= 2:
                score += 1

        if compact and len(compact) >= 4 and compact in sender_key:
            score += 1
            reasons.append("nom de l'expéditeur")

        if score >= 3:
            scored.append((score, application, reasons))

    if not scored:
        return None, None
    scored.sort(key=lambda item: item[0], reverse=True)
    best_score, best_application, best_reasons = scored[0]
    if len(scored) > 1 and scored[1][0] == best_score:
        return None, None
    return best_application, " · ".join(best_reasons) or "correspondance de contenu"


def _message_dict(session: Session, message: EmailMessage) -> dict[str, Any]:
    application = session.get(Application, message.application_id) if message.application_id else None
    job = session.get(Job, application.job_id) if application else None
    return {
        "id": message.id,
        "subject": message.subject,
        "sender_name": message.sender_name,
        "sender_email": message.sender_email,
        "excerpt": message.excerpt,
        "received_at": message.received_at.isoformat() if message.received_at else None,
        "classification": message.classification,
        "confidence": message.confidence,
        "reason": message.reason,
        "reviewed": message.reviewed,
        "ignored": message.ignored,
        "application_id": message.application_id,
        "match_reason": message.match_reason,
        "application": (
            {
                "id": application.id,
                "status": application.status,
                "submitted_at": (
                    application.submitted_at.isoformat() if application.submitted_at else None
                ),
                "job_title": job.title if job else None,
                "job_company": job.company if job else None,
            }
            if application
            else None
        ),
    }


def email_status(session: Session, settings: Settings) -> dict[str, Any]:
    credentials = load_credentials(settings)
    total = int(session.scalar(select(func.count()).select_from(EmailMessage)) or 0)
    awaiting = int(
        session.scalar(
            select(func.count())
            .select_from(EmailMessage)
            .where(
                EmailMessage.classification.in_(REPLY_LABELS),
                EmailMessage.reviewed.is_(False),
                EmailMessage.ignored.is_(False),
            )
        )
        or 0
    )
    replies = int(
        session.scalar(
            select(func.count())
            .select_from(EmailMessage)
            .where(EmailMessage.classification.in_(REPLY_LABELS))
        )
        or 0
    )
    last_sync = (credentials or {}).get("last_sync") or {}
    return {
        "provider": "gmail",
        "connected": credentials is not None,
        "secret_storage": secret_storage(settings),
        "address": (credentials or {}).get("address") or "",
        "last_address": settings.email.address or "",
        "imap_host": settings.email.imap_host,
        "last_sync_at": (credentials or {}).get("last_sync_at"),
        "last_sync": last_sync,
        "messages": total,
        "awaiting": awaiting,
        "replies": replies,
        "followups": len(followup_candidates(session, settings)),
        "lookback_days": settings.email.lookback_days,
        "relance_days": settings.email.relance_days,
    }


def sync_mailbox(
    session: Session,
    settings: Settings,
    *,
    fetcher: Callable[..., list[InboundEmail]] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    credentials = load_credentials(settings)
    if credentials is None:
        raise MailboxNotConnected(
            "Aucune boîte n'est connectée. Ajoutez votre mot de passe d'application dans Réglages → Boîte mail."
        )
    now = now or datetime.now(UTC)
    known_ids = set(session.scalars(select(EmailMessage.remote_id)))
    reader = fetcher or fetch_messages
    messages = reader(
        address=credentials["address"],
        password=credentials["password"],
        settings=settings,
        known_ids=known_ids,
        now=now,
    )

    created = 0
    matched = 0
    for item in messages:
        if not item.remote_id or item.remote_id in known_ids:
            continue
        classification = classify(item.subject, item.body, item.sender_email)
        message = EmailMessage(
            remote_id=item.remote_id,
            account=credentials["address"],
            folder=settings.email.folder,
            subject=item.subject,
            sender_name=item.sender_name or None,
            sender_email=item.sender_email,
            excerpt=item.body[:1200],
            received_at=item.received_at,
            classification=classification.label,
            confidence=classification.confidence,
            reason=classification.reason,
        )
        if classification.label != "other":
            application, match_reason = match_application(
                session,
                subject=item.subject,
                body=item.body,
                sender_email=item.sender_email,
                sender_name=item.sender_name,
                now=now,
            )
            if application is not None:
                message.application_id = application.id
                message.match_reason = match_reason
                matched += 1
                logger.info(
                    "réponse rattachée",
                    extra={"data": {"application_id": application.id, "label": classification.label}},
                )
        session.add(message)
        known_ids.add(item.remote_id)
        created += 1

    summary = {"created": created, "matched": matched, "fetched": len(messages)}
    mark_synced(settings, at=now, summary=summary)
    record_audit(
        session,
        entity_type="email_message",
        entity_id=None,
        action="email.synced",
        data=summary,
    )
    session.flush()
    return summary


def list_messages(session: Session, *, scope: str = "all") -> list[EmailMessage]:
    query = select(EmailMessage).order_by(EmailMessage.received_at.desc()).limit(250)
    if scope == "review":
        query = query.where(
            EmailMessage.classification.in_(REPLY_LABELS),
            EmailMessage.reviewed.is_(False),
            EmailMessage.ignored.is_(False),
        )
    elif scope == "replies":
        query = query.where(EmailMessage.classification.in_(REPLY_LABELS))
    elif scope == "ignored":
        query = query.where(EmailMessage.ignored.is_(True))
    else:
        query = query.where(EmailMessage.ignored.is_(False))
    return list(session.scalars(query))


def serialize_messages(session: Session, messages: list[EmailMessage]) -> list[dict[str, Any]]:
    return [_message_dict(session, message) for message in messages]


def update_message(
    session: Session,
    message_id: str,
    *,
    application_id: Any = UNSET,
    classification: Any = UNSET,
    ignored: Any = UNSET,
    apply_status: bool = False,
) -> EmailMessage:
    message = session.get(EmailMessage, message_id)
    if message is None:
        raise LookupError(f"message introuvable : {message_id}")

    if classification is not UNSET:
        if classification not in CLASSIFICATIONS:
            raise ValueError(f"classification inconnue : {classification}")
        message.classification = classification
        message.reviewed = True
    if application_id is not UNSET:
        if application_id:
            if session.get(Application, application_id) is None:
                raise LookupError(f"candidature introuvable : {application_id}")
            message.match_reason = "Rattachement manuel"
        else:
            message.match_reason = None
        message.application_id = application_id or None
        message.reviewed = True
    if ignored is not UNSET:
        message.ignored = bool(ignored)
        if message.ignored:
            message.reviewed = True

    if apply_status and message.application_id:
        target = {
            "interview": "interview",
            "offer": "offer",
            "rejected": "rejected",
        }.get(message.classification)
        if target:
            update_application_status(session, message.application_id, target)

    session.flush()
    record_audit(
        session,
        entity_type="email_message",
        entity_id=message.id,
        action="email.reviewed",
        data={
            "classification": message.classification,
            "application_id": message.application_id,
            "ignored": message.ignored,
        },
    )
    return message


def followup_draft(
    job: Job | None, application: Application, profile: Profile | None
) -> tuple[str, str]:
    name = (profile.full_name or profile.name) if profile else ""
    submitted = _aware(application.submitted_at)
    sent_on = submitted.strftime("%d/%m/%Y") if submitted else ""
    title = job.title if job else "le poste"
    company = job.company if job else "votre entreprise"
    subject = f"Relance — candidature {title}"
    lines = [
        "Bonjour,",
        "",
        (
            f"Je me permets de revenir vers vous concernant ma candidature au poste de "
            f"{title} chez {company}"
            + (f", envoyée le {sent_on}" if sent_on else "")
            + "."
        ),
        "Je reste très intéressé(e) par cette opportunité et me tiens à votre disposition "
        "pour tout complément d'information.",
        "",
        "Bien cordialement,",
        name,
    ]
    return subject, "\n".join(line for line in lines if line is not None)


def followup_candidates(
    session: Session, settings: Settings, *, now: datetime | None = None
) -> list[dict[str, Any]]:
    now = now or datetime.now(UTC)
    delay = settings.email.relance_days
    applications = list(
        session.scalars(
            select(Application)
            .where(Application.status == "submitted")
            .order_by(Application.submitted_at.asc())
        )
    )
    candidates: list[dict[str, Any]] = []
    for application in applications:
        submitted = _aware(application.submitted_at)
        if submitted is None:
            continue
        days = (now - submitted).days
        if days < delay or application.followed_up_at is not None:
            continue
        replied = session.scalar(
            select(func.count())
            .select_from(EmailMessage)
            .where(
                EmailMessage.application_id == application.id,
                EmailMessage.classification.in_(("interview", "offer", "rejected")),
            )
        )
        if replied:
            continue
        job = session.get(Job, application.job_id)
        profile = session.get(Profile, application.profile_id)
        subject, body = followup_draft(job, application, profile)
        candidates.append(
            {
                "application_id": application.id,
                "status": application.status,
                "submitted_at": submitted.isoformat(),
                "days_since": days,
                "job_title": job.title if job else None,
                "job_company": job.company if job else None,
                "job_url": (job.apply_url or job.url) if job else None,
                "profile_name": profile.name if profile else None,
                "suggested_subject": subject,
                "suggested_body": body,
            }
        )
    return candidates


def mark_followed_up(
    session: Session, application_id: str, *, now: datetime | None = None
) -> dict[str, Any]:
    application = session.get(Application, application_id)
    if application is None:
        raise LookupError(f"candidature introuvable : {application_id}")
    application.followed_up_at = now or datetime.now(UTC)
    session.flush()
    record_audit(
        session,
        entity_type="application",
        entity_id=application.id,
        action="application.followed_up",
        data={"followed_up_at": application.followed_up_at.isoformat()},
    )
    return {
        "application_id": application.id,
        "followed_up_at": application.followed_up_at.isoformat(),
    }


__all__ = [
    "CLASSIFICATIONS",
    "MailboxError",
    "MailboxNotConnected",
    "email_status",
    "followup_candidates",
    "list_messages",
    "mark_followed_up",
    "match_application",
    "serialize_messages",
    "sync_mailbox",
    "update_message",
]
