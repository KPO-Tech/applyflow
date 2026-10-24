"""Bibliothèque de réponses validées, réutilisées d'une candidature à l'autre."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from applyflow.db.models import ApplicationAnswer
from applyflow.services import ensure_local_user, record_audit
from applyflow.text import slugify, token_set


def normalize_question(text: str) -> str:
    return slugify(text, max_length=300)


def list_answers(session: Session, *, approved_only: bool = False) -> list[ApplicationAnswer]:
    user = ensure_local_user(session)
    query = select(ApplicationAnswer).where(ApplicationAnswer.user_id == user.id)
    if approved_only:
        query = query.where(ApplicationAnswer.approved.is_(True))
    return list(session.scalars(query.order_by(ApplicationAnswer.question_key)))


def upsert_answer(
    session: Session,
    *,
    question_text: str,
    answer: str,
    approved: bool = True,
    kind: str = "text",
) -> ApplicationAnswer:
    question_text = question_text.strip()
    answer = answer.strip()
    if not question_text or not answer:
        raise ValueError("question et réponse obligatoires")
    user = ensure_local_user(session)
    key = normalize_question(question_text)
    existing = session.scalar(
        select(ApplicationAnswer).where(
            ApplicationAnswer.user_id == user.id, ApplicationAnswer.question_key == key
        )
    )
    if existing is None:
        existing = ApplicationAnswer(
            user_id=user.id,
            question_key=key,
            question_text=question_text,
            answer=answer,
            approved=approved,
            kind=kind,
        )
        session.add(existing)
    else:
        existing.answer = answer
        existing.approved = approved
        existing.question_text = question_text
        existing.kind = kind
    session.flush()
    record_audit(
        session,
        entity_type="application_answer",
        entity_id=existing.id,
        action="answer.saved",
        data={"question": question_text},
    )
    return existing


def approved_answers(session: Session) -> dict[str, ApplicationAnswer]:
    return {answer.question_key: answer for answer in list_answers(session, approved_only=True)}


def find_answer(
    answers: dict[str, ApplicationAnswer], label: str
) -> ApplicationAnswer | None:
    key = normalize_question(label)
    if key in answers:
        return answers[key]
    label_tokens = token_set(label)
    if not label_tokens:
        return None
    best: tuple[float, ApplicationAnswer] | None = None
    for answer in answers.values():
        answer_tokens = token_set(answer.question_text)
        if not answer_tokens:
            continue
        overlap = len(label_tokens & answer_tokens) / len(label_tokens | answer_tokens)
        if overlap >= 0.75 and (best is None or overlap > best[0]):
            best = (overlap, answer)
    return best[1] if best else None
