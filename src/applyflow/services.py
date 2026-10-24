"""Services transverses : utilisateur local et journal d'audit."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from applyflow.db.models import AuditEvent, User

LOCAL_USER_EMAIL = "local@applyflow.invalid"


def ensure_local_user(session: Session) -> User:
    user = session.scalar(select(User).where(User.email == LOCAL_USER_EMAIL))
    if user is None:
        user = User(email=LOCAL_USER_EMAIL, name="Utilisateur local")
        session.add(user)
        session.flush()
    return user


def record_audit(
    session: Session,
    *,
    entity_type: str,
    entity_id: str | None,
    action: str,
    data: dict[str, Any] | None = None,
    actor: str = "local",
) -> AuditEvent:
    event = AuditEvent(
        entity_type=entity_type,
        entity_id=entity_id,
        action=action,
        data=data or {},
        actor=actor,
    )
    session.add(event)
    return event
