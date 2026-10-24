from __future__ import annotations

from pathlib import Path

from applyflow.applications.forms import analyze_html, build_plan
from applyflow.config import PROJECT_ROOT


def _html(name: str) -> str:
    return (PROJECT_ROOT / "playground" / name).read_text(encoding="utf-8")


def test_analyze_greenhouse_form() -> None:
    analysis = analyze_html(_html("greenhouse_form.html"), "demo://greenhouse")
    keys = {field.key for field in analysis.fields}
    assert {"first_name", "last_name", "email", "phone", "resume", "work_authorization"} <= keys
    resume_field = next(field for field in analysis.fields if field.key == "resume")
    assert resume_field.required is True
    assert resume_field.input_type == "file"
    assert analysis.submit_label == "Submit application"


def test_analyze_simple_form_selects() -> None:
    analysis = analyze_html(_html("simple_form.html"))
    remote = next(field for field in analysis.fields if field.key == "remote")
    assert remote.options == ["onsite", "hybrid", "remote"]
    assert remote.required is False


def test_build_plan_fills_from_profile_and_resume(session, settings, profile, resume) -> None:
    analysis = analyze_html(_html("simple_form.html"), "demo://simple")
    plan = build_plan(
        analysis,
        profile=profile,
        resume=resume,
        answers={},
        resume_path=str(settings.data_dir / resume.stored_path),
    )
    values = {fill.key: fill for fill in plan.fills}
    assert values["full_name"].value == "Camille Martin"
    assert values["email"].value == profile.email
    assert values["resume"].value.endswith(".pdf")
    # Le CV est stocké sous son identifiant ; l'interface et l'envoi doivent montrer son nom.
    assert values["resume"].display == resume.filename
    assert values["resume"].value != resume.filename
    assert values["remote"].value == "hybrid"
    assert values["remote"].source == "profile"
    assert plan.can_prepare is True
    assert plan.unknown_questions == []


def test_required_unknown_questions_need_review(session, settings, profile, resume) -> None:
    analysis = analyze_html(_html("greenhouse_form.html"), "demo://greenhouse")
    plan = build_plan(
        analysis,
        profile=profile,
        resume=resume,
        answers={},
        resume_path=str(settings.data_dir / resume.stored_path),
    )
    labels = {question.label for question in plan.unknown_questions}
    assert "Why do you want to join this company?" in labels
    assert "Are you authorized to work in France?" in labels
    assert all(question.required for question in plan.unknown_questions)
    assert plan.can_prepare is True


def test_missing_resume_blocks_preparation(session, settings, profile) -> None:
    analysis = analyze_html(_html("simple_form.html"), "demo://simple")
    plan = build_plan(analysis, profile=profile, resume=None, answers={})
    assert plan.can_prepare is False
    assert "CV" in (plan.blocked_reason or "")


def test_missing_identity_values_are_not_invented(session, settings, profile, resume) -> None:
    profile.email = None
    profile.phone = None
    profile.full_name = None
    analysis = analyze_html(_html("simple_form.html"), "demo://simple")
    plan = build_plan(
        analysis,
        profile=profile,
        resume=resume,
        answers={},
        resume_path=str(settings.data_dir / resume.stored_path),
    )
    assert plan.can_prepare is False
    assert "Full name" in plan.missing_values
    assert "Email" in plan.missing_values
    filled_keys = {fill.key for fill in plan.fills}
    assert "full_name" not in filled_keys
    assert "email" not in filled_keys


def test_select_value_must_match_an_option(session, settings, profile, resume) -> None:
    analysis = analyze_html(_html("custom_form.html"), "demo://custom")
    plan = build_plan(
        analysis,
        profile=profile,
        resume=resume,
        answers={},
        resume_path=str(settings.data_dir / resume.stored_path),
    )
    work_auth = next(
        (question for question in plan.unknown_questions if question.key == "work_authorization"),
        None,
    )
    assert work_auth is not None
    assert any(fill.key == "salary" for fill in plan.fills)


def test_file_without_form_raises() -> None:
    import pytest

    from applyflow.applications.forms import FormAnalysisError

    with pytest.raises(FormAnalysisError):
        analyze_html("<html><body><p>Pas de formulaire</p></body></html>")


def test_analysis_of_local_page_path(tmp_path: Path) -> None:
    page = tmp_path / "page.html"
    page.write_text(_html("lever_form.html"), encoding="utf-8")
    analysis = analyze_html(page.read_text(encoding="utf-8"))
    assert any(field.label.startswith("What is your notice period") for field in analysis.fields)


def test_lever_posting_urls_point_to_the_apply_form() -> None:
    """Sur Lever, la page de l'offre n'a pas de formulaire : il est sous /apply."""
    from applyflow.applications.fetcher import form_page_url

    posting = "https://jobs.lever.co/sfeir/f5bae950-7a3c-46c3-a4c2-3ffd980484ed"
    assert form_page_url(posting) == posting + "/apply"
    assert form_page_url(posting + "/") == posting + "/apply"
    assert form_page_url(posting + "?lever-source=x") == posting + "/apply?lever-source=x"
    assert form_page_url(posting + "/apply") == posting + "/apply"  # déjà la bonne page
    # Rien ne change pour les autres sites ni pour une adresse Lever d'un autre format.
    assert form_page_url("https://jobs.lever.co/sfeir") == "https://jobs.lever.co/sfeir"
    assert form_page_url("https://jobs.ashbyhq.com/acme/abc") == "https://jobs.ashbyhq.com/acme/abc"
    assert form_page_url("https://evil.example/a/" + "0" * 36) == "https://evil.example/a/" + "0" * 36


def test_http_fetcher_requests_the_lever_apply_page(settings) -> None:
    import httpx

    from applyflow.applications.fetcher import HttpFormFetcher

    requested: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested.append(str(request.url))
        return httpx.Response(
            200, text="<form><input name='name'></form>", headers={"content-type": "text/html"}
        )

    posting = "https://jobs.lever.co/sfeir/f5bae950-7a3c-46c3-a4c2-3ffd980484ed"
    HttpFormFetcher(settings=settings, transport=httpx.MockTransport(handler)).fetch(posting)
    assert requested == [posting + "/apply"]
