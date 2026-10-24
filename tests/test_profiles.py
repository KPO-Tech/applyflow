from __future__ import annotations

import pytest
from pydantic import ValidationError

from applyflow.profiles.schemas import ProfileInput
from applyflow.profiles.service import (
    ResumeValidationError,
    active_resume,
    list_profiles,
    update_profile,
    upload_resume,
)
from applyflow.seed import SAMPLE_CV


def test_profile_requires_target_title() -> None:
    with pytest.raises(ValidationError):
        ProfileInput(name="Vide", target_titles=[])


def test_profile_rejects_invalid_email() -> None:
    with pytest.raises(ValidationError):
        ProfileInput(name="Profil", target_titles=["Data Analyst"], email="pas-un-email")


def test_profile_salary_range_validation() -> None:
    with pytest.raises(ValidationError):
        ProfileInput(
            name="Profil",
            target_titles=["Data Analyst"],
            salary_min=50000,
            salary_max=40000,
        )


def test_upload_pdf_and_duplicate_is_idempotent(session, settings, profile) -> None:
    content = SAMPLE_CV.read_bytes()
    first = upload_resume(session, settings, profile.id, filename="cv.pdf", content=content)
    second = upload_resume(session, settings, profile.id, filename="cv-copie.pdf", content=content)
    assert first.id == second.id
    assert active_resume(profile).id == first.id
    stored = settings.data_dir / first.stored_path
    assert stored.is_file()
    assert stored.read_bytes() == content


def test_upload_rejects_non_pdf(session, settings, profile) -> None:
    with pytest.raises(ResumeValidationError):
        upload_resume(
            session,
            settings,
            profile.id,
            filename="cv.txt",
            content=b"pas un pdf",
        )


def test_new_upload_becomes_active(session, settings, profile) -> None:
    first = upload_resume(
        session, settings, profile.id, filename="cv1.pdf", content=SAMPLE_CV.read_bytes()
    )
    second = upload_resume(
        session,
        settings,
        profile.id,
        filename="cv2.pdf",
        content=SAMPLE_CV.read_bytes() + b"\n% revision 2",
    )
    session.refresh(profile)
    assert active_resume(profile).id == second.id
    assert first.id != second.id
    assert first.is_active is False


def test_update_profile_and_deactivate(session, make_profile) -> None:
    created = make_profile(name="Data Analyst")
    payload = ProfileInput(
        name="Data Analyst Senior",
        target_titles=["Data Analyst"],
        technical_skills=["SQL"],
        experience_level="mid",
        years_experience=4,
        locations=["France"],
        active=True,
    )
    updated = update_profile(session, created.id, payload)
    assert updated.name == "Data Analyst Senior"
    assert updated.experience_level == "mid"
    assert [profile.name for profile in list_profiles(session)] == ["Data Analyst Senior"]


def test_uploaded_bytes_are_never_modified(session, settings, profile) -> None:
    content = SAMPLE_CV.read_bytes()
    resume = upload_resume(session, settings, profile.id, filename="cv.pdf", content=content)
    assert (settings.data_dir / resume.stored_path).read_bytes() == content
