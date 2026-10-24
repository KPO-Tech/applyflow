from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from applyflow.db.models import Application, EmailMessage, Job
from applyflow.email import gmail as gmail_module
from applyflow.email.account import load_credentials, save_credentials
from applyflow.email.classify import classify
from applyflow.email.gmail import InboundEmail
from applyflow.email.service import (
    email_status,
    followup_candidates,
    mark_followed_up,
    sync_mailbox,
    update_message,
)


def _job(session, **overrides) -> Job:
    data = {
        "source_kind": "manual_url",
        "url": "https://acme.example/jobs/1",
        "url_key": "https://acme.example/jobs/1",
        "company": "Acme",
        "title": "Data Engineer",
        "description": "Python, SQL.",
        "fingerprint": "f" * 64,
    }
    data.update(overrides)
    job = Job(**data)
    session.add(job)
    session.flush()
    return job


def _application(session, profile, job, *, days_ago: int = 15, status: str = "submitted") -> Application:
    application = Application(
        job_id=job.id,
        profile_id=profile.id,
        status=status,
        submitted_at=datetime.now(UTC) - timedelta(days=days_ago),
    )
    session.add(application)
    session.flush()
    return application


def _message(**overrides) -> InboundEmail:
    data = {
        "remote_id": "<reply-1@acme.example>",
        "subject": "Votre candidature Data Engineer",
        "sender_name": "Acme Recruiting",
        "sender_email": "recruiting@acme.example",
        "body": "Bonjour, malheureusement nous ne donnons pas suite à votre candidature.",
        "received_at": datetime.now(UTC),
    }
    data.update(overrides)
    return InboundEmail(**data)


@pytest.mark.parametrize(
    ("subject", "body", "label"),
    [
        ("Votre candidature", "Nous ne donnons pas suite à votre candidature.", "rejected"),
        ("Suite à votre entretien", "Malheureusement, nous avons choisi un autre profil.", "rejected"),
        ("Entretien technique", "Quelles sont vos disponibilités pour un entretien ?", "interview"),
        ("Votre candidature", "Nous avons bien reçu votre candidature.", "acknowledgement"),
        ("Offre d'embauche", "Nous avons le plaisir de vous proposer un contrat.", "offer"),
        ("5 nouvelles offres d'emploi", "Découvrez les postes sélectionnés pour vous.", "other"),
        ("Newsletter", "Les articles de la semaine.", "other"),
    ],
)
def test_classification(subject: str, body: str, label: str) -> None:
    result = classify(subject, body, "rh@example.invalid")
    assert result.label == label
    assert 0 <= result.confidence <= 1


class _FakeIMAP:
    """Répond comme un serveur IMAP à un seul FETCH de littéral."""

    def select(self, folder: str, readonly: bool = True):
        return "OK", [b"2"]

    def uid(self, command: str, *args):
        if command == "search":
            return "OK", [b"2 1"]
        uid = args[0]
        header = (
            "From: Acme Recruiting <rh@acme.example>\r\n"
            f"Subject: Entretien {uid}\r\n"
            "Date: Thu, 22 Oct 2026 10:00:00 +0000\r\n"
            f"Message-ID: <{uid}@acme.example>\r\n\r\n"
        )
        body = f"{header}Bonjour, nous souhaitons échanger avec vous. Quelles sont vos disponibilités ?"
        raw = (header if "HEADER" in args[1] else body).encode("utf-8")
        return "OK", [(f"1 (BODY[] {{{len(raw)}}}".encode(), raw), b")"]

    def logout(self) -> None:
        return None


def test_imap_fetch_parses_and_skips_known(settings, monkeypatch) -> None:
    monkeypatch.setattr(gmail_module, "_connect", lambda *args, **kwargs: _FakeIMAP())
    messages = gmail_module.fetch_messages(
        address="camille@gmail.com",
        password="abcd efgh ijkl mnop",
        settings=settings,
        known_ids=set(),
    )
    assert len(messages) == 2
    first = messages[0]
    assert first.sender_email == "rh@acme.example"
    assert first.sender_name == "Acme Recruiting"
    assert first.subject.startswith("Entretien")
    assert "disponibilités" in first.body
    assert first.received_at.year == 2026

    known = gmail_module.fetch_messages(
        address="camille@gmail.com",
        password="abcd efgh ijkl mnop",
        settings=settings,
        known_ids={"<2@acme.example>"},
    )
    assert [message.remote_id for message in known] == ["<1@acme.example>"]


def test_sync_matches_application_and_is_idempotent(session, settings, profile) -> None:
    save_credentials(settings, address="camille@gmail.com", password="abcd efgh ijkl mnop")
    job = _job(session)
    application = _application(session, profile, job)
    calls: list[dict] = []

    def fetcher(**kwargs):
        calls.append(kwargs)
        return [_message()]

    now = datetime.now(UTC)
    result = sync_mailbox(session, settings, fetcher=fetcher, now=now)
    assert result == {"created": 1, "matched": 1, "fetched": 1}
    message = session.query(EmailMessage).one()
    assert message.classification == "rejected"
    assert message.application_id == application.id
    assert message.match_reason
    assert calls[0]["address"] == "camille@gmail.com"
    assert calls[0]["password"] == "abcdefghijklmnop"

    credentials = load_credentials(settings)
    assert credentials is not None
    assert credentials["last_sync_at"] == now.isoformat()
    assert load_credentials(settings)["last_sync"]["created"] == 1

    again = sync_mailbox(session, settings, fetcher=fetcher, now=now)
    assert again["created"] == 0
    assert session.query(EmailMessage).count() == 1


def test_status_and_message_review(session, settings, profile) -> None:
    save_credentials(settings, address="camille@gmail.com", password="abcd efgh ijkl mnop")
    job = _job(session)
    application = _application(session, profile, job)

    def fetcher(**_kwargs):
        return [_message()]

    sync_mailbox(session, settings, fetcher=fetcher)
    status = email_status(session, settings)
    assert status["connected"] is True
    assert status["address"] == "camille@gmail.com"
    assert status["messages"] == 1
    assert status["awaiting"] == 1
    assert status["replies"] == 1

    message = session.query(EmailMessage).one()
    update_message(session, message.id, classification="interview", apply_status=True)
    assert session.get(Application, application.id).status == "interview"
    assert message.reviewed is True
    assert email_status(session, settings)["awaiting"] == 0


def test_followup_candidates_and_mark(session, settings, profile) -> None:
    job = _job(session)
    application = _application(session, profile, job, days_ago=21)
    candidates = followup_candidates(session, settings)
    assert len(candidates) == 1
    assert candidates[0]["application_id"] == application.id
    assert candidates[0]["days_since"] >= 21
    assert "Data Engineer" in candidates[0]["suggested_subject"]
    assert "Camille Martin" in candidates[0]["suggested_body"]

    mark_followed_up(session, application.id)
    assert followup_candidates(session, settings) == []


def test_followup_skips_recent_application(session, settings, profile) -> None:
    job = _job(session)
    _application(session, profile, job, days_ago=2)
    assert followup_candidates(session, settings) == []


def test_email_api_flow(api_client, monkeypatch) -> None:
    status = api_client.get("/email/status")
    assert status.status_code == 200
    assert status.json()["connected"] is False
    assert api_client.get("/email/messages").json() == []
    assert api_client.post("/email/sync").status_code == 409

    invalid = api_client.post(
        "/email/connect",
        json={"address": "pas-une-adresse", "password": "abcd efgh ijkl mnop"},
    )
    assert invalid.status_code == 400

    monkeypatch.setattr(
        "applyflow.api.main.test_connection",
        lambda *args, **kwargs: {"address": args[0], "messages": 12},
    )
    connected = api_client.post(
        "/email/connect",
        json={"address": "Camille@Gmail.com", "password": "abcd efgh ijkl mnop"},
    )
    assert connected.status_code == 200
    payload = connected.json()
    assert payload["connected"] is True
    assert payload["address"] == "camille@gmail.com"
    assert "password" not in str(payload)

    settings = api_client.get("/settings").json()
    assert settings["email"]["relance_days"] == 10

    disconnected = api_client.post("/email/disconnect")
    assert disconnected.status_code == 200
    assert disconnected.json()["connected"] is False


def test_email_message_api_review(api_client, session, profile) -> None:
    job = _job(session)
    application = _application(session, profile, job)
    message = EmailMessage(
        remote_id="<api-review@acme.example>",
        account="camille@gmail.com",
        subject="Entretien",
        sender_email="rh@acme.example",
        excerpt="Nous souhaitons échanger avec vous.",
        received_at=datetime.now(UTC),
        classification="interview",
        confidence=0.8,
        reason="Indices : entretien",
    )
    session.add(message)
    session.commit()

    reviewed = api_client.patch(
        f"/email/messages/{message.id}",
        json={
            "application_id": application.id,
            "classification": "interview",
            "apply_status": True,
        },
    )
    assert reviewed.status_code == 200
    assert reviewed.json()["application"]["id"] == application.id
    assert reviewed.json()["reviewed"] is True
    applications = api_client.get("/applications").json()
    assert applications[0]["status"] == "interview"

    detached = api_client.patch(
        f"/email/messages/{message.id}", json={"application_id": None}
    )
    assert detached.status_code == 200
    assert detached.json()["application_id"] is None
    assert api_client.get("/email/followups").json()["total"] == 0
