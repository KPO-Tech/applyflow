"""Garde-fous de l'interface : chaque module JS doit se charger, les nouveaux points d'accès répondent."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

ASSETS = Path(__file__).resolve().parents[1] / "src" / "applyflow" / "web" / "assets"


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js absent")
@pytest.mark.parametrize(
    "script", sorted(ASSETS.rglob("*.js")), ids=lambda p: str(p.relative_to(ASSETS))
)
def test_every_js_module_parses(script: Path) -> None:
    """Une erreur de syntaxe (ex. gabarit mal fermé) rend toute la page blanche."""
    result = subprocess.run(
        ["node", "--input-type=module", "--check"],
        input=script.read_text(encoding="utf-8"),
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert result.returncode == 0, result.stderr


def test_sources_expose_board_state(api_client) -> None:
    sources = {entry["kind"]: entry for entry in api_client.get("/sources").json()}
    jobspy = sources["jobspy"]
    assert jobspy["enabled"] is False  # désactivé tant que l'utilisateur ne l'active pas
    assert isinstance(jobspy["installed"], bool)
    assert jobspy["daily_usage"]["linkedin"]["limit"] == 75
    assert "installed" in sources["ats"]


def test_enable_jobspy_through_settings_and_read_usage(api_client) -> None:
    saved = api_client.put("/settings", json={"boards": {"jobspy_enabled": True}})
    assert saved.status_code == 200
    assert api_client.get("/settings").json()["boards"]["jobspy_enabled"] is True
    sites = api_client.get("/collection/usage").json()["sites"]
    assert sites["indeed"] == {"used": 0, "limit": 200, "remaining": 200}


def test_discovery_reports_site_stats(api_client) -> None:
    """Une collecte ATS renvoie les statistiques par entreprise (ici : échec réseau simulé)."""
    response = api_client.post(
        "/discovery",
        json={
            "source": {"kind": "ats", "config": {"companies": ["tesla:tesla"]}},
            "keywords": ["data"],
        },
    )
    assert response.status_code == 200
    assert any("non pris en charge" in error for error in response.json()["source_errors"])


def test_interface_files_are_always_revalidated(api_client) -> None:
    """Sans consigne de cache, le navigateur garde d'anciens CSS/JS après une mise à jour."""
    for path in ("/", "/assets/styles.css", "/assets/pages/discovery.js"):
        response = api_client.get(path)
        assert response.status_code == 200
        assert response.headers["cache-control"] == "no-cache", path
    html = api_client.get("/").text
    assert "/assets/styles.css?v=" in html and "/assets/app.js?v=" in html  # adresse versionnée
    assert api_client.get("/assets/styles.css?v=abc").status_code == 200
    etag = api_client.get("/assets/styles.css").headers["etag"]
    again = api_client.get("/assets/styles.css", headers={"If-None-Match": etag})
    assert again.status_code == 304  # revérification légère : rien n'est retéléchargé


def test_contract_options_in_the_ui_match_the_server_list() -> None:
    """Les cases à cocher du profil doivent proposer exactement les types connus du serveur."""
    import re

    from applyflow.contracts import CONTRACT_TYPES

    source = (ASSETS / "pages" / "profiles.js").read_text(encoding="utf-8")
    block = re.search(r"const CONTRACT_OPTIONS = \[(.*?)\];", source, re.S)
    assert block, "constante CONTRACT_OPTIONS introuvable"
    labels = re.findall(r'"([^"]+)"', block.group(1))
    assert labels == [label for _, label in CONTRACT_TYPES]
