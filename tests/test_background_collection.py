"""Collecte en arrière-plan : progression, annulation, une seule collecte à la fois."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from typing import Any

import pandas as pd
import pytest

from applyflow import collection_tasks
from applyflow.collection_tasks import CollectionBusy, CollectionManager
from applyflow.providers.ats_provider import AtsProvider
from applyflow.providers.jobspy_provider import JobSpyProvider
from applyflow.schemas import ImportResult, JobQuery


def wait_for(condition: Callable[[], bool], timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return
        time.sleep(0.02)
    raise AssertionError("condition non atteinte à temps")


def blocking_runner(started: threading.Event) -> Callable[..., Any]:
    """Faux `collect_jobs` : progresse, puis attend l'annulation ou la fin."""

    def run(session, specs, query, settings, *, on_progress, cancel_event):  # noqa: ANN001
        on_progress(1, 4, "Indeed · data", 7)
        started.set()
        cancelled = cancel_event.wait(timeout=5)
        result = ImportResult(created=3 if cancelled else 9)
        return result, []

    return run


# ---------------------------------------------------------------- connecteurs


def frame(site: str, count: int) -> pd.DataFrame:
    rows = [
        {"id": f"{site}-{i}", "job_url": f"https://{site}.example/{i}", "title": f"Data {i}",
         "company": "Acme", "location": "Paris, France", "description": "SQL " * 40}
        for i in range(count)
    ]
    result = pd.DataFrame(rows)
    result.attrs = {"errors": {}}
    return result


def test_jobspy_reports_progress_and_stops_on_cancel() -> None:
    cancel = threading.Event()
    reports: list[tuple[int, int, str, int]] = []
    calls: list[str] = []

    def scrape(**kwargs: Any) -> pd.DataFrame:
        calls.append(kwargs["search_term"])
        cancel.set()  # annulation demandée pendant la première requête
        return frame(kwargs["site_name"][0], 3)

    provider = JobSpyProvider(
        sites=["indeed", "hellowork"], scrape=scrape, sleep=lambda _: None, max_per_site=10
    )
    provider.bind_control(lambda *args: reports.append(args), cancel)
    jobs = provider.fetch(JobQuery(keywords=["a", "b"], limit=100))
    assert len(calls) == 1  # aucune requête après l'annulation
    assert len(jobs) == 3  # les offres déjà récupérées sont rendues, pas perdues
    assert reports[0][:2] == (0, 4) and "Indeed" in reports[0][2]


def test_jobspy_progress_reaches_total_when_not_cancelled() -> None:
    reports: list[tuple[int, int, str, int]] = []
    provider = JobSpyProvider(
        sites=["indeed"], scrape=lambda **k: frame("indeed", 2), sleep=lambda _: None
    )
    provider.bind_control(lambda *args: reports.append(args), None)
    provider.fetch(JobQuery(keywords=["a", "b"]))
    assert reports[-1] == (2, 2, "Terminé", 4)


def test_cancelled_pause_returns_immediately() -> None:
    cancel = threading.Event()
    provider = JobSpyProvider(
        sites=["indeed", "linkedin"], scrape=lambda **k: frame(k["site_name"][0], 1),
        pause_seconds=30,
    )
    provider.bind_control(None, cancel)
    threading.Timer(0.2, cancel.set).start()
    started = time.monotonic()
    provider.fetch(JobQuery(keywords=["a"]))
    assert time.monotonic() - started < 5  # la pause de 30 s a été interrompue


def test_ats_skips_remaining_companies_after_cancel() -> None:
    cancel = threading.Event()
    seen: list[str] = []

    def make(ats: str, slug: str, timeout: float) -> Any:
        class Scraper:
            async def afetch(self) -> list[Any]:
                seen.append(slug)
                cancel.set()
                return []

        return Scraper()

    provider = AtsProvider(
        companies=["greenhouse:a", "greenhouse:b", "greenhouse:c"], make_scraper=make, concurrency=1
    )
    provider.bind_control(None, cancel)
    assert provider.fetch(JobQuery(keywords=["x"])) == []  # annulation : pas d'erreur
    assert seen == ["a"]
    assert provider.last_stats["greenhouse:c"]["errors"] == ["annulé"]


# ---------------------------------------------------------------- gestionnaire


def test_manager_runs_one_collection_at_a_time_and_cancels(database, settings) -> None:
    manager = CollectionManager()
    started = threading.Event()
    task = manager.start(
        database, settings, [{"kind": "fixture"}], JobQuery(), runner=blocking_runner(started)
    )
    assert started.wait(2)
    assert task.status == "running"
    assert manager.active() is task
    assert task.as_dict()["progress"]["label"] == "Indeed · data"
    with pytest.raises(CollectionBusy, match="déjà en cours"):
        manager.start(database, settings, [], JobQuery(), runner=blocking_runner(started))

    manager.cancel(task.id)
    wait_for(lambda: task.status != "running")
    assert task.status == "cancelled" and task.result["created"] == 3
    assert manager.active() is None
    again = manager.start(  # une fois terminée, une nouvelle collecte est possible
        database, settings, [], JobQuery(), runner=lambda *a, **k: (ImportResult(created=1), [])
    )
    wait_for(lambda: again.status != "running")
    assert again.status == "done"


def test_manager_reports_runner_failure(database, settings) -> None:
    def boom(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("panne réseau")

    manager = CollectionManager()
    task = manager.start(database, settings, [], JobQuery(), runner=boom)
    wait_for(lambda: task.status != "running")
    assert task.status == "error" and task.error == "panne réseau"
    with pytest.raises(LookupError):
        manager.get("inconnu")


# ---------------------------------------------------------------- API


def test_api_start_poll_cancel_and_busy(api_client, monkeypatch) -> None:
    started = threading.Event()
    monkeypatch.setattr(collection_tasks, "collect_jobs", blocking_runner(started))
    body = {"source": {"kind": "fixture"}, "keywords": ["data"]}

    first = api_client.post("/discovery/start", json=body)
    assert first.status_code == 202
    task_id = first.json()["id"]
    assert started.wait(2)

    busy = api_client.post("/discovery/start", json=body)
    assert busy.status_code == 409 and "déjà en cours" in busy.json()["detail"]
    assert api_client.get("/discovery/tasks/active").json()["id"] == task_id
    running = api_client.get(f"/discovery/tasks/{task_id}").json()
    assert running["status"] == "running" and running["progress"]["total"] == 4

    assert api_client.post(f"/discovery/tasks/{task_id}/cancel").status_code == 200
    wait_for(lambda: api_client.get(f"/discovery/tasks/{task_id}").json()["status"] == "cancelled")
    assert api_client.get("/discovery/tasks/active").json() is None
    assert api_client.get("/discovery/tasks/inconnu").status_code == 404


def test_api_real_collection_end_to_end(api_client) -> None:
    """Sans simulation : la source de démonstration passe par le vrai chemin asynchrone."""
    response = api_client.post(
        "/discovery/start", json={"source": {"kind": "fixture"}, "keywords": [], "limit": 5}
    )
    assert response.status_code == 202
    task_id = response.json()["id"]
    wait_for(lambda: api_client.get(f"/discovery/tasks/{task_id}").json()["status"] != "running")
    task = api_client.get(f"/discovery/tasks/{task_id}").json()
    result = task["result"]
    assert task["status"] == "done"
    # le jeu de démonstration contient un doublon parmi ses premières annonces
    assert result["created"] + result["duplicates"] == 5 and result["created"] >= 4
    assert len(api_client.get("/jobs").json()) == result["created"]


# ---------------------------------------------------------------- réglages


def test_settings_reject_invalid_daily_limits(api_client) -> None:
    bad = api_client.put("/settings", json={"boards": {"daily_limits": {"linkedin": -5}}})
    assert bad.status_code in (400, 422)
    too_high = api_client.put("/settings", json={"boards": {"daily_limits": {"indeed": 99999}}})
    assert too_high.status_code in (400, 422)
    ok = api_client.put(
        "/settings",
        json={"boards": {"daily_limits": {"linkedin": 30, "indeed": 0}, "pause_seconds": 8}},
    )
    assert ok.status_code == 200
    saved = api_client.get("/settings").json()["boards"]
    assert saved["daily_limits"] == {"linkedin": 30, "indeed": 0}
    assert saved["pause_seconds"] == 8
    usage = api_client.get("/collection/usage").json()["sites"]
    assert usage["linkedin"]["limit"] == 30 and usage["indeed"]["limit"] is None
