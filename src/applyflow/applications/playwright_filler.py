"""Préremplissage Playwright — ne clique jamais sur « Envoyer »."""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field

from applyflow.applications.fetcher import browser_url
from applyflow.applications.forms import ApplicationPlan


class FillError(RuntimeError):
    pass


class FillReport(BaseModel):
    filled: int = 0
    skipped: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    submitted: bool = False


def fill_with_playwright(
    url: str,
    plan: ApplicationPlan,
    *,
    headless: bool = True,
    headed_timeout_ms: int = 20_000,
) -> FillReport:
    """Ouvre le formulaire et applique le plan. Aucune soumission, par construction."""
    try:
        from playwright.sync_api import Error as PlaywrightError
        from playwright.sync_api import sync_playwright
    except ImportError as exc:  # pragma: no cover - dépendance déclarée
        raise FillError("Playwright n'est pas installé") from exc

    report = FillReport()
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=headless)
        page = browser.new_page()
        try:
            page.goto(browser_url(url), wait_until="domcontentloaded")
            for fill in plan.fills:
                if not fill.selector:
                    report.skipped.append(fill.label)
                    continue
                try:
                    locator = page.locator(fill.selector).first
                    if fill.input_type == "file":
                        path = Path(fill.value)
                        if not path.is_file():
                            report.errors.append(f"CV introuvable : {path.name}")
                            continue
                        # Le fichier est stocké sous son identifiant : on l'envoie sous son nom
                        # d'origine, sans quoi le recruteur reçoit « <empreinte>.pdf ».
                        locator.set_input_files(
                            {
                                "name": fill.display or path.name,
                                "mimeType": "application/pdf",
                                "buffer": path.read_bytes(),
                            }
                        )
                    elif fill.input_type in {"select", "select-one"}:
                        try:
                            locator.select_option(value=fill.value)
                        except PlaywrightError:
                            locator.select_option(label=fill.value)
                    else:
                        locator.fill(fill.value)
                    report.filled += 1
                except PlaywrightError as exc:
                    report.errors.append(f"{fill.label} : {exc}")
            page.wait_for_timeout(300)
        finally:
            browser.close()
    report.submitted = False
    return report
