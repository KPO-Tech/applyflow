"""Parcours de bout en bout : un vrai serveur, un vrai navigateur, l'interface réelle.

Les tests de routes vérifient qu'un fichier est servi ; ceux-ci vérifient qu'il *fonctionne*
une fois chargé. Un module JavaScript cassé, un formulaire qui ne se soumet plus ou une page
qui reste blanche passeraient la suite unitaire sans être vus.

Chaque test démarre son propre serveur (uvicorn) sur un port libre, avec une base temporaire :
rien n'est partagé avec la base locale de la personne qui lance les tests.
"""

from __future__ import annotations

import json
import os
import threading
import time
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
import pytest
import uvicorn

from applyflow.api.main import create_app
from applyflow.config import Settings

sync_api = pytest.importorskip("playwright.sync_api")

# L'interface est en français : les titres de page et les libellés de navigation sont des
# contrats. Le fil d'Ariane reprend le libellé du menu, pas le titre de la page.
VIEW_TITLES = {
    "dashboard": "Votre recherche, en un coup d'œil.",
    "profils": "Profils & CV",
    "decouverte": "Découverte",
    "campagnes": "Campagnes",
    "validation": "File de validation",
    "candidatures": "Candidatures",
    "emails": "Suivi e-mail",
    "reglages": "Réglages",
}
NAV_LABELS = {**VIEW_TITLES, "dashboard": "Tableau de bord"}

# Le marqueur `playwright` suffit : `make test-fast` (et `-m "not playwright"`) écartent ces
# parcours, et `make e2e` les sélectionne par fichier.
pytestmark = pytest.mark.playwright


def _chromium_available() -> bool:
    try:
        with sync_api.sync_playwright() as runtime:
            browser = runtime.chromium.launch(headless=True)
            browser.close()
        return True
    except Exception:
        return False


@dataclass
class Ui:
    """Une page de l'interface, plus les erreurs que le navigateur a signalées."""

    page: Any
    base_url: str
    errors: list[str] = field(default_factory=list)

    def open(self, route: str = "") -> None:
        self.page.goto(f"{self.base_url}/#/{route.lstrip('/')}", wait_until="domcontentloaded")


@pytest.fixture()
def live_server(settings: Settings) -> Iterator[str]:
    """Le serveur local, tel que `applyflow serve-ui` le lance, sur un port éphémère."""
    settings.config_path = settings.data_dir.parent / "applyflow-e2e.toml"
    server = uvicorn.Server(
        uvicorn.Config(
            create_app(settings),
            host="127.0.0.1",
            port=0,  # le système choisit un port libre : aucun conflit avec un serveur déjà lancé
            log_level="warning",
            access_log=False,
        )
    )
    # uvicorn refuse d'installer des gestionnaires de signaux hors du thread principal.
    server.install_signal_handlers = lambda: None  # type: ignore[method-assign]
    thread = threading.Thread(target=server.run, name="applyflow-e2e", daemon=True)
    thread.start()

    deadline = time.monotonic() + 30
    while not server.started and time.monotonic() < deadline:
        time.sleep(0.05)
    assert server.started, "le serveur local n'a pas démarré"
    port = server.servers[0].sockets[0].getsockname()[1]

    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        thread.join(timeout=20)


@pytest.fixture()
def ui(live_server: str) -> Iterator[Ui]:
    if not _chromium_available():
        message = "Chromium absent : exécuter `uv run playwright install chromium`"
        # En intégration continue, un navigateur manquant est une panne, pas une dispense :
        # sinon ces parcours disparaîtraient silencieusement de la vérification.
        if os.environ.get("CI"):
            pytest.fail(message)
        pytest.skip(message)
    with sync_api.sync_playwright() as runtime:
        browser = runtime.chromium.launch(headless=True)
        context = browser.new_context(locale="fr-FR", viewport={"width": 1440, "height": 960})
        page = context.new_page()
        handle = Ui(page=page, base_url=live_server)
        page.on("pageerror", lambda error: handle.errors.append(str(error)))
        page.on(
            "console",
            lambda message: (
                handle.errors.append(message.text) if message.type == "error" else None
            ),
        )
        try:
            yield handle
        finally:
            browser.close()


def _create_profile(base_url: str, name: str = "Profil E2E") -> None:
    """Un profil actif est la condition d'une analyse de campagne (créé par l'API ici)."""
    response = httpx.post(
        f"{base_url}/profiles",
        json={
            "name": name,
            "target_titles": ["Data Engineer", "Analytics Engineer"],
            "technical_skills": ["Python", "SQL", "dbt"],
            "experience_level": "junior",
            "locations": ["France"],
            "contract_types": ["CDI"],
        },
        timeout=10,
    )
    assert response.status_code == 201, response.text


def test_every_view_renders_without_a_javascript_error(ui: Ui) -> None:
    """Huit espaces, huit rendus : un module cassé ne doit plus passer inaperçu."""
    ui.page.goto(ui.base_url, wait_until="domcontentloaded")
    sync_api.expect(ui.page.locator("#view .page-title")).to_have_text(VIEW_TITLES["dashboard"])
    # L'écran de démarrage est bien remplacé par la page (sinon : écran figé).
    assert ui.page.locator(".boot").count() == 0
    assert ui.page.locator("[data-nav-id]").count() == len(VIEW_TITLES)

    for route, title in VIEW_TITLES.items():
        ui.open(route)
        sync_api.expect(ui.page.locator("#view .page-title")).to_have_text(title)
        # Le fil d'Ariane peut préciser une sous-section (« Réglages · Matching »).
        sync_api.expect(ui.page.locator("#current-section")).to_contain_text(NAV_LABELS[route])
        sync_api.expect(ui.page.locator(f'[data-nav-id="{route}"]')).to_have_attribute(
            "aria-current", "page"
        )

    assert ui.errors == [], "\n".join(ui.errors)


def test_create_a_profile_through_the_form(ui: Ui) -> None:
    ui.open("profils")
    ui.page.click("#new-profile")

    dialog = ui.page.locator("dialog.dialog")
    sync_api.expect(dialog).to_be_visible()
    ui.page.fill("#pf-name", "Profil E2E")
    ui.page.fill("#pf-full-name", "Camille Test")
    ui.page.fill("#pf-email", "camille@example.invalid")
    ui.page.fill("#pf-titles", "Data Engineer, Analytics Engineer")
    ui.page.fill("#pf-technical", "Python, SQL, dbt")
    dialog.get_by_role("button", name="Créer le profil").click()

    # Le dialogue se ferme, la liste se rafraîchit et la fiche apparaît.
    sync_api.expect(dialog).to_have_count(0)
    card = ui.page.locator(".profile-card")
    sync_api.expect(card).to_have_count(1)
    sync_api.expect(card).to_contain_text("Profil E2E")
    sync_api.expect(card).to_contain_text("Data Engineer")
    sync_api.expect(ui.page.locator(".toast")).to_contain_text("Profil « Profil E2E » créé.")

    # La même donnée est bien écrite côté serveur, pas seulement affichée.
    stored = httpx.get(f"{ui.base_url}/profiles", timeout=10).json()
    assert [profile["name"] for profile in stored] == ["Profil E2E"]
    assert stored[0]["technical_skills"] == ["Python", "SQL", "dbt"]

    assert ui.errors == [], "\n".join(ui.errors)


def test_import_offers_then_run_a_campaign(ui: Ui, tmp_path: Path) -> None:
    _create_profile(ui.base_url)

    offers = tmp_path / "offres-e2e.json"
    offers.write_text(
        json.dumps(
            {
                "jobs": [
                    {
                        "title": f"Data Engineer E2E {index}",
                        "company": f"Entreprise {index}",
                        "url": f"https://exemple.invalid/offres/{index}",
                        "apply_url": "demo://simple",  # formulaire local : aucun réseau
                        "location": "Paris, France",
                        "description": "Python, SQL, dbt. Poste junior en CDI.",
                    }
                    for index in range(1, 4)
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    # 1. Import des offres depuis l'écran Découverte.
    ui.open("decouverte")
    ui.page.click('[data-source="json_file"]')
    ui.page.fill("#source-path", str(offers))
    ui.page.fill("#discovery-keywords", "")  # aucun filtre : les trois offres doivent entrer
    ui.page.click("[data-collect]")

    result = ui.page.locator("#discovery-result .result-banner")
    sync_api.expect(result).to_contain_text("3 nouvelles offres", timeout=30_000)
    sync_api.expect(ui.page.locator("#jobs-table tbody tr[data-job-id]")).to_have_count(3)

    # 2. Campagne sur la bibliothèque : aucune requête réseau, même trois offres.
    ui.open("campagnes?new=1")
    dialog = ui.page.locator("dialog.dialog")
    sync_api.expect(dialog).to_be_visible()
    ui.page.fill("#campaign-name", "Campagne E2E")
    ui.page.fill("#campaign-keywords", "data")
    dialog.get_by_role("button", name="Créer la campagne").click()

    sync_api.expect(ui.page.locator(".detail-title")).to_have_text("Campagne E2E")

    # 3. Exécution : collecte → analyse → préparation, suivie en direct par la page.
    ui.page.click('[data-action="run"]')
    sync_api.expect(ui.page.get_by_text("Campagne terminée")).to_be_visible(timeout=60_000)

    first_kpi = ui.page.locator(".campaign-kpis .stat-strip-item").first.locator("strong")
    sync_api.expect(first_kpi).to_have_text("3", timeout=30_000)
    sync_api.expect(ui.page.locator(".campaign-results tbody tr")).to_have_count(3)

    # La campagne est enregistrée côté serveur avec ses trois offres suivies.
    campaigns = httpx.get(f"{ui.base_url}/campaigns", timeout=10).json()
    assert [campaign["name"] for campaign in campaigns] == ["Campagne E2E"]
    assert campaigns[0]["status"] == "completed"
    results = httpx.get(
        f"{ui.base_url}/campaigns/{campaigns[0]['id']}/results", timeout=10
    ).json()
    assert len(results) == 3

    assert ui.errors == [], "\n".join(ui.errors)
