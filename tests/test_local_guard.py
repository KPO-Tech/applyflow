"""L'API locale refuse les requêtes venues d'une autre page web ou d'un autre nom d'hôte."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from applyflow.api.main import create_app
from applyflow.config import Settings

SAME_ORIGIN = "http://127.0.0.1:8000"


def test_normal_requests_still_work(api_client) -> None:
    assert api_client.get("/health").status_code == 200
    assert api_client.get("/jobs").status_code == 200
    # Appel sans Origin (curl, scripts locaux, CLI) : autorisé.
    assert api_client.post("/discovery", json={"source": {"kind": "fixture"}, "limit": 1}).status_code == 200


def test_same_origin_post_from_the_ui_is_allowed(api_client) -> None:
    response = api_client.post(
        "/discovery", json={"source": {"kind": "fixture"}, "limit": 1}, headers={"Origin": SAME_ORIGIN}
    )
    assert response.status_code == 200


@pytest.mark.parametrize(
    "origin",
    [
        "http://evil.example",  # une page web quelconque
        "http://127.0.0.1:3000",  # un autre service local, autre port
        "http://localhost:8000",  # même machine mais autre nom : pas la même origine
        "null",  # iframe sandboxée, fichier local
    ],
)
def test_cross_origin_requests_are_refused(api_client, origin: str) -> None:
    for method, path in (("post", "/settings"), ("get", "/jobs"), ("post", "/discovery/start")):
        response = getattr(api_client, method)(path, headers={"Origin": origin})
        assert response.status_code == 403, (method, path, origin)
        assert "ApplyFlow" in response.json()["detail"]


def test_settings_cannot_be_changed_by_another_site(api_client) -> None:
    before = api_client.get("/settings").json()["boards"]["jobspy_enabled"]
    api_client.put(
        "/settings", json={"boards": {"jobspy_enabled": True}}, headers={"Origin": "http://evil.example"}
    )
    assert api_client.get("/settings").json()["boards"]["jobspy_enabled"] == before


@pytest.mark.parametrize("host", ["evil.example", "evil.example:8000", "192.168.1.20:8000", ""])
def test_dns_rebinding_hosts_are_refused(api_client, host: str) -> None:
    response = api_client.get("/jobs", headers={"Host": host})
    assert response.status_code == 403
    assert "api.allowed_hosts" in response.json()["detail"]


@pytest.mark.parametrize("host", ["127.0.0.1", "localhost:8501", "LOCALHOST", "[::1]:8000"])
def test_local_hosts_are_accepted(api_client, host: str) -> None:
    assert api_client.get("/health", headers={"Host": host}).status_code == 200


def test_allowed_hosts_is_configurable(settings: Settings) -> None:
    settings.api.allowed_hosts = ["127.0.0.1", "applyflow.maison"]
    settings.config_path = settings.data_dir.parent / "guard.toml"
    with TestClient(create_app(settings), base_url="http://applyflow.maison") as client:
        assert client.get("/health").status_code == 200
    with TestClient(create_app(settings), base_url="http://localhost") as client:
        assert client.get("/health").status_code == 403  # retiré de la liste : refusé
