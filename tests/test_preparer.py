from __future__ import annotations

import pytest
from sqlalchemy import func, select

from applyflow.applications.answers import upsert_answer
from applyflow.applications.preparer import (
    DuplicateApplication,
    SubmissionNotAllowed,
    approve_attempt,
    list_attempts,
    prepare_attempt,
    record_submission,
)
from applyflow.db.models import Application, ApplicationAttempt, Job
from applyflow.jobs.service import ingest_jobs
from applyflow.providers.fixture import FixtureProvider
from applyflow.schemas import JobQuery


def _fixture_job(session, external_id: str) -> Job:
    ingest_jobs(session, FixtureProvider().fetch(JobQuery(limit=1000)))
    job = session.scalar(select(Job).where(Job.external_id == external_id))
    assert job is not None
    return job


def test_prepare_simple_form_is_dry_run_and_complete(session, settings, profile, resume) -> None:
    job = _fixture_job(session, "cloudforge-501")
    attempt = prepare_attempt(session, settings, job, profile)
    assert attempt.mode == "dry_run"
    assert attempt.status == "prepared"
    assert attempt.plan["fills"]
    assert attempt.unknown_questions == []
    assert any(fill["key"] == "resume" for fill in attempt.plan["fills"])
    assert attempt.form_snapshot["fields"]
    assert attempt.form_snapshot.get("submit_label")


def test_prepare_is_idempotent(session, settings, profile, resume) -> None:
    job = _fixture_job(session, "cloudforge-501")
    first = prepare_attempt(session, settings, job, profile)
    second = prepare_attempt(session, settings, job, profile)
    assert first.id == second.id
    count = session.scalar(select(func.count()).select_from(ApplicationAttempt))
    assert count == 1


def test_needs_review_then_answer_reuse(session, settings, profile, resume) -> None:
    job = _fixture_job(session, "nova-101")
    attempt = prepare_attempt(session, settings, job, profile)
    assert attempt.status == "needs_review"
    with pytest.raises(SubmissionNotAllowed):
        approve_attempt(session, attempt)

    upsert_answer(
        session,
        question_text="Why do you want to join this company?",
        answer="Je souhaite contribuer à des pipelines data fiables.",
    )
    upsert_answer(
        session,
        question_text="Are you authorized to work in France?",
        answer="Yes",
    )
    updated = prepare_attempt(session, settings, job, profile)
    assert updated.id == attempt.id
    assert updated.status == "prepared"
    assert updated.unknown_questions == []
    keys = {fill["key"] for fill in updated.plan["fills"]}
    assert {"work_authorization", "first_name", "last_name"}.issubset(keys)


def test_missing_resume_blocks(session, settings, make_profile) -> None:
    profile = make_profile(name="Sans CV", target_titles=["Python Developer"])
    job = _fixture_job(session, "cloudforge-501")
    attempt = prepare_attempt(session, settings, job, profile)
    assert attempt.status == "blocked"
    assert attempt.error is None
    assert "CV" in (attempt.plan.get("blocked_reason") or "")


def test_unavailable_form_blocks_without_crashing(session, settings, profile, resume) -> None:
    job = _fixture_job(session, "cloudforge-501")
    job.apply_url = "demo://formulaire-inexistant"
    attempt = prepare_attempt(session, settings, job, profile)
    assert attempt.status == "blocked"
    assert attempt.error


def test_approval_and_submission_are_explicit(session, settings, profile, resume) -> None:
    job = _fixture_job(session, "cloudforge-501")
    attempt = prepare_attempt(session, settings, job, profile)
    application = approve_attempt(session, attempt)
    assert application.status == "prepared"
    assert attempt.status == "approved"
    assert attempt.id in {item.id for item in list_attempts(session)}

    with pytest.raises(SubmissionNotAllowed):
        record_submission(session, attempt, confirmed=False)

    submitted = record_submission(session, attempt, confirmed=True)
    assert submitted.status == "submitted"
    assert submitted.submitted_at is not None
    assert attempt.status == "submitted"

    with pytest.raises(SubmissionNotAllowed):
        record_submission(session, attempt, confirmed=True)


def test_duplicate_application_is_prevented_across_profiles(
    session, settings, profile, resume, make_profile
) -> None:
    job = _fixture_job(session, "cloudforge-501")
    attempt = prepare_attempt(session, settings, job, profile)
    approve_attempt(session, attempt)
    record_submission(session, attempt, confirmed=True)

    other = make_profile(name="Autre profil", target_titles=["Python Developer"])
    from applyflow.profiles.service import upload_resume
    from applyflow.seed import SAMPLE_CV

    upload_resume(
        session,
        settings,
        other.id,
        filename="cv.pdf",
        content=SAMPLE_CV.read_bytes() + b"\n% other",
    )
    with pytest.raises(DuplicateApplication):
        prepare_attempt(session, settings, job, other)
    count = session.scalar(select(func.count()).select_from(Application))
    assert count == 1


def test_attempt_values_come_only_from_profile_and_answers(
    session, settings, profile, resume
) -> None:
    job = _fixture_job(session, "nova-101")
    attempt = prepare_attempt(session, settings, job, profile)
    for fill in attempt.plan["fills"]:
        assert fill["source"] in {"profile", "resume", "answer_library"}
    # Aucune couverture ni lettre de motivation inventée.
    assert not any(fill["key"] == "cover_letter" for fill in attempt.plan["fills"])
