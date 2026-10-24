"""Campagnes en arrière-plan : l'API rend la main, le suivi et l'arrêt fonctionnent."""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path

from applyflow import campaign_tasks
from applyflow.campaign_tasks import CampaignBusy, CampaignManager
from applyflow.campaigns.schemas import CampaignInput
from applyflow.campaigns.service import create_campaign


def _wait(predicate, *, timeout: float = 10.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.02)
    raise AssertionError("condition non atteinte avant le délai imparti")


def _jobs_file(tmp_path: Path) -> Path:
    target = tmp_path / "offres.json"
    target.write_text(
        json.dumps(
            {
                "jobs": [
                    {
                        "url": "https://acme.example/jobs/1",
                        "company": "Acme",
                        "title": "Data Engineer Junior",
                        "location": "Paris, France",
                        "description": "Python, SQL.",
                    },
                    {
                        "url": "https://acme.example/jobs/2",
                        "company": "Beta",
                        "title": "Data Analyst",
                        "location": "Lyon, France",
                        "description": "SQL, Power BI.",
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
    return target


def _campaign(session, tmp_path: Path, name: str = "Arrière-plan"):
    campaign = create_campaign(
        session,
        CampaignInput(
            name=name,
            sources=[{"kind": "json_file", "config": {"path": str(_jobs_file(tmp_path))}}],
        ),
    )
    session.commit()
    return campaign


def test_campaign_runs_in_background_and_is_followable(api_client, session, tmp_path) -> None:
    campaign = _campaign(session, tmp_path)

    started = api_client.post(
        f"/campaigns/{campaign.id}/run/start", json={"steps": ["discover"]}
    )
    assert started.status_code == 202
    task = started.json()
    assert task["campaign_id"] == campaign.id
    assert task["status"] in {"running", "done"}

    def finished() -> bool:
        return api_client.get(f"/campaigns/tasks/{task['id']}").json()["status"] != "running"

    _wait(finished)
    final = api_client.get(f"/campaigns/tasks/{task['id']}").json()
    assert final["status"] == "done"
    assert final["error"] is None
    assert final["result"]["steps"]["discover"]["created"] == 2
    assert final["result"]["steps"]["discover"]["linked"] == 2
    assert final["progress"]["step"] == "discover"

    assert api_client.get("/campaigns/tasks/active").json() is None
    # Une seule étape demandée : la campagne attend la suivante.
    assert api_client.get(f"/campaigns/{campaign.id}").json()["status"] == "paused"


def test_failed_step_leaves_the_campaign_resumable(api_client, session, tmp_path) -> None:
    campaign = _campaign(session, tmp_path, name="Sans profil")

    started = api_client.post(f"/campaigns/{campaign.id}/run/start", json={"steps": ["analyze"]})
    assert started.status_code == 202
    task_id = started.json()["id"]
    _wait(lambda: api_client.get(f"/campaigns/tasks/{task_id}").json()["status"] != "running")

    task = api_client.get(f"/campaigns/tasks/{task_id}").json()
    assert task["status"] == "error"
    assert "profil" in task["error"]
    # Sans ce retour en pause, la campagne resterait « en cours » pour toujours.
    state = api_client.get(f"/campaigns/{campaign.id}").json()
    assert state["status"] == "paused"
    assert "profil" in state["last_error"]


def test_unknown_campaign_is_refused_before_any_thread(api_client) -> None:
    response = api_client.post("/campaigns/inconnue/run/start", json={"steps": ["discover"]})
    assert response.status_code == 404
    assert api_client.get("/campaigns/tasks/active").json() is None


def test_only_one_campaign_runs_at_a_time(api_client, session, tmp_path, monkeypatch) -> None:
    release = threading.Event()
    entered = threading.Event()

    def slow_runner(session_, campaign_id, settings, **kwargs):
        entered.set()
        release.wait(10)
        return {"campaign_id": campaign_id, "steps": {}, "status": "paused"}

    monkeypatch.setattr(campaign_tasks, "run_campaign", slow_runner)
    campaign = _campaign(session, tmp_path, name="Lente")

    first = api_client.post(f"/campaigns/{campaign.id}/run/start", json={"steps": ["discover"]})
    assert first.status_code == 202
    assert entered.wait(5)

    second = api_client.post(f"/campaigns/{campaign.id}/run/start", json={"steps": ["discover"]})
    assert second.status_code == 409
    assert "déjà en cours" in second.json()["detail"]

    release.set()
    task_id = first.json()["id"]
    _wait(lambda: api_client.get(f"/campaigns/tasks/{task_id}").json()["status"] != "running")


def test_manager_progress_and_cancel(database, settings) -> None:
    manager = CampaignManager()

    def runner(session, campaign_id, settings_, *, should_stop, on_progress, **kwargs):
        on_progress("analyze", 1, 4)
        while not should_stop():
            time.sleep(0.01)
        return {"campaign_id": campaign_id, "steps": {}, "status": "paused"}

    task = manager.start(database, settings, "campagne-x", steps=["analyze"], runner=runner)
    _wait(lambda: task.progress["done"] == 1)

    assert task.progress["total"] == 4
    assert "Analyse" in task.progress["label"]
    assert manager.active() is task

    cancelled = manager.cancel(task.id)
    assert cancelled.as_dict()["cancel_requested"] is True
    _wait(lambda: task.status == "cancelled")
    assert manager.active() is None
    assert task.result["status"] == "paused"


def test_manager_refuses_a_second_start_and_reports_errors(database, settings) -> None:
    manager = CampaignManager()
    release = threading.Event()

    def blocking(session, campaign_id, settings_, **kwargs):
        release.wait(10)
        return {"campaign_id": campaign_id, "steps": {}, "status": "paused"}

    def failing(session, campaign_id, settings_, **kwargs):
        raise RuntimeError("source indisponible")

    manager.start(database, settings, "première", runner=blocking)
    try:
        manager.start(database, settings, "seconde", runner=blocking)
    except CampaignBusy as exc:
        assert "déjà en cours" in str(exc)
    else:  # pragma: no cover - le test doit échouer si la garde disparaît
        raise AssertionError("une seconde campagne aurait dû être refusée")
    finally:
        release.set()

    _wait(lambda: manager.active() is None)
    failing_task = manager.start(database, settings, "en-erreur", runner=failing)
    _wait(lambda: failing_task.status == "error")
    assert failing_task.error == "source indisponible"
