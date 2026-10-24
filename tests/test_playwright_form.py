from __future__ import annotations

import pytest

from applyflow.applications.forms import analyze_html, build_plan
from applyflow.config import PROJECT_ROOT

playwright = pytest.importorskip("playwright.sync_api")


def _chromium_available() -> bool:
    try:
        with playwright.sync_playwright() as runtime:
            browser = runtime.chromium.launch(headless=True)
            browser.close()
        return True
    except Exception:
        return False


@pytest.mark.playwright
def test_playwright_fills_demo_form_without_submitting(session, settings, profile, resume) -> None:
    if not _chromium_available():
        pytest.skip("Chromium absent : exécuter `uv run playwright install chromium`")

    from applyflow.applications.playwright_filler import fill_with_playwright

    html = (PROJECT_ROOT / "playground" / "simple_form.html").read_text(encoding="utf-8")
    analysis = analyze_html(html, "demo://simple")
    plan = build_plan(
        analysis,
        profile=profile,
        resume=resume,
        answers={},
        resume_path=str(settings.data_dir / resume.stored_path),
    )
    report = fill_with_playwright("demo://simple", plan, headless=True)
    assert report.submitted is False
    assert report.errors == []
    assert report.filled == len(plan.fills)
    assert report.filled >= 4


@pytest.mark.playwright
def test_browser_reader_reads_a_form_built_by_javascript(settings) -> None:
    """Le HTML servi ici n'a aucun champ : seul le rendu navigateur les fait apparaître."""
    if not _chromium_available():
        pytest.skip("Chromium absent : exécuter `uv run playwright install chromium`")

    from applyflow.applications.fetcher import BrowserFormFetcher, DemoFormFetcher
    from applyflow.applications.forms import NoFormFields

    static = DemoFormFetcher().fetch("demo://js")
    with pytest.raises(NoFormFields):
        analyze_html(static.html, static.url)

    rendered = BrowserFormFetcher(settings).fetch("demo://js")
    keys = {field.key for field in analyze_html(rendered.html, rendered.url).fields}
    assert {"full_name", "email", "resume"} <= keys
