"""Recherche par défaut : l'écran Découverte est prérempli, les réglages restent modifiables."""

from __future__ import annotations

import pytest

from applyflow.config import Settings
from applyflow.providers.ats_provider import parse_company


def test_out_of_the_box_defaults_are_usable() -> None:
    search = Settings().search
    assert search.keywords and search.locations == ["France"]
    assert 1 <= search.limit <= 5000
    # Chaque entreprise par défaut est acceptée par le connecteur ATS (format et liste blanche).
    assert [parse_company(entry) for entry in search.ats_companies]
    assert len(search.ats_companies) == len(set(search.ats_companies))


def test_linkedin_is_not_checked_by_default() -> None:
    boards = Settings().boards
    assert "linkedin" not in boards.sites
    assert boards.jobspy_enabled is False  # l'activation reste un choix explicite


def test_api_exposes_the_defaults(api_client) -> None:
    search = api_client.get("/settings").json()["search"]
    assert "Data Engineer junior" in search["keywords"]
    assert "lever:qonto" in search["ats_companies"]


def test_defaults_can_be_changed_and_are_cleaned(api_client) -> None:
    response = api_client.put(
        "/settings",
        json={"search": {
            "keywords": ["  ML Engineer ", "", "ML Engineer", "Data Analyst"],
            "locations": ["Paris", " "],
            "limit": 40,
            "ats_companies": ["Lever:QontoCo", "ashby:alan", "ashby:alan"],
        }},
    )
    assert response.status_code == 200
    search = api_client.get("/settings").json()["search"]
    assert search["keywords"] == ["ML Engineer", "Data Analyst"]  # nettoyé, sans doublon
    assert search["locations"] == ["Paris"] and search["limit"] == 40
    # Seul le nom de l'ATS passe en minuscules : l'identifiant d'entreprise garde sa casse.
    assert search["ats_companies"] == ["lever:QontoCo", "ashby:alan"]


@pytest.mark.parametrize(
    "bad",
    [
        {"ats_companies": ["lever qonto"]},
        {"ats_companies": ["qonto"]},
        {"limit": 0},
        {"limit": 99999},
    ],
)
def test_invalid_defaults_are_rejected(api_client, bad: dict) -> None:
    assert api_client.put("/settings", json={"search": bad}).status_code in (400, 422)
    assert api_client.get("/settings").json()["search"]["limit"] == 100  # rien n'a été écrit


def test_default_sites_can_be_changed(api_client) -> None:
    api_client.put("/settings", json={"boards": {"sites": ["indeed", "glassdoor"]}})
    sources = {item["kind"]: item for item in api_client.get("/sources").json()}
    assert sources["jobspy"]["sites"] == ["indeed", "glassdoor"]
    assert api_client.get("/settings").json()["boards"]["jobspy_enabled"] is False
