from __future__ import annotations

from applyflow.config import load_settings
from applyflow.jobs.service import collect_jobs
from applyflow.schemas import JobQuery


def test_laya_token_env_override(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("APPLYFLOW_LAYA_TOKEN", "jeton-local")
    monkeypatch.setenv("APPLYFLOW_DATA_DIR", str(tmp_path / "data"))
    settings = load_settings()
    assert settings.router.laya_token == "jeton-local"


def test_api_redacts_laya_token(api_client) -> None:
    api_client.app.state.settings.router.laya_token = "secret-local"
    payload = api_client.get("/settings").json()
    assert payload["router"]["laya_token"] == "***"


def test_collection_pauses_between_sources(session, settings, monkeypatch) -> None:
    settings.discovery.rate_limit_seconds = 0.5
    calls: list[float] = []
    monkeypatch.setattr("applyflow.jobs.service.time.sleep", lambda seconds: calls.append(seconds))
    sources = [{"kind": "fixture"}, {"kind": "fixture", "name": "deuxième"}]
    collect_jobs(session, sources, JobQuery(limit=2), settings)
    assert calls == [0.5]
