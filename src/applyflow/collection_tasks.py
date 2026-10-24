"""Collectes en arrière-plan : progression, annulation, une seule collecte à la fois.

Une collecte sur les job boards peut durer plusieurs minutes. Elle s'exécute dans un thread, avec
sa propre session de base de données ; l'interface suit l'avancement par interrogation. Une seule
collecte tourne à la fois : lancer plusieurs recherches en parallèle multiplierait les requêtes
vers les mêmes sites et ferait sauter les protections de débit.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from applyflow.config import Settings
from applyflow.db.base import Database
from applyflow.jobs.service import collect_jobs
from applyflow.logging_setup import get_logger
from applyflow.schemas import JobQuery

logger = get_logger("collection")

KEEP_TASKS = 20


class CollectionBusy(RuntimeError):
    """Une collecte est déjà en cours."""


@dataclass
class CollectionTask:
    id: str
    status: str = "running"  # running | done | cancelled | error
    started_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    finished_at: str | None = None
    progress: dict[str, Any] = field(
        default_factory=lambda: {"done": 0, "total": 0, "label": "Démarrage…", "collected": 0}
    )
    result: dict[str, Any] | None = None
    error: str | None = None
    cancel_event: threading.Event = field(default_factory=threading.Event, repr=False)

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "status": self.status,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "progress": dict(self.progress),
            "cancel_requested": self.cancel_event.is_set(),
            "result": self.result,
            "error": self.error,
        }


Runner = Callable[..., Any]


class CollectionManager:
    def __init__(self) -> None:
        self._tasks: dict[str, CollectionTask] = {}
        self._lock = threading.Lock()

    def active(self) -> CollectionTask | None:
        with self._lock:
            return next((t for t in self._tasks.values() if t.status == "running"), None)

    def get(self, task_id: str) -> CollectionTask:
        with self._lock:
            task = self._tasks.get(task_id)
        if task is None:
            raise LookupError(f"collecte introuvable : {task_id}")
        return task

    def start(
        self,
        database: Database,
        settings: Settings,
        specs: list[dict[str, Any]],
        query: JobQuery,
        *,
        runner: Runner | None = None,
    ) -> CollectionTask:
        with self._lock:
            if any(t.status == "running" for t in self._tasks.values()):
                raise CollectionBusy(
                    "Une collecte est déjà en cours. Attendez sa fin ou annulez-la : "
                    "ApplyFlow ne lance jamais deux collectes en parallèle."
                )
            task = CollectionTask(id=uuid4().hex[:12])
            self._tasks[task.id] = task
            for old in list(self._tasks)[:-KEEP_TASKS]:
                self._tasks.pop(old, None)
        threading.Thread(
            target=self._run,
            args=(task, database, settings, specs, query, runner or collect_jobs),
            name=f"collection-{task.id}",
            daemon=True,
        ).start()
        return task

    def cancel(self, task_id: str) -> CollectionTask:
        task = self.get(task_id)
        if task.status == "running":
            task.cancel_event.set()
            task.progress["label"] = "Annulation en cours…"
        return task

    def _run(
        self,
        task: CollectionTask,
        database: Database,
        settings: Settings,
        specs: list[dict[str, Any]],
        query: JobQuery,
        runner: Runner,
    ) -> None:
        started = time.monotonic()

        def on_progress(done: int, total: int, label: str, collected: int) -> None:
            task.progress = {"done": done, "total": total, "label": label, "collected": collected}

        try:
            with database.session() as session:
                result, errors = runner(
                    session, specs, query, settings,
                    on_progress=on_progress, cancel_event=task.cancel_event,
                )
            task.result = {**result.model_dump(), "source_errors": errors}
            task.status = "cancelled" if task.cancel_event.is_set() else "done"
            if task.status == "done":
                task.progress["done"] = max(task.progress["total"], task.progress["done"])
        except Exception as exc:  # la tâche ne doit jamais faire tomber le serveur
            logger.exception("collecte en échec")
            task.status = "error"
            task.error = str(exc) or type(exc).__name__
        finally:
            task.finished_at = datetime.now(UTC).isoformat()
            logger.info(
                "collecte arrière-plan terminée",
                extra={"data": {"id": task.id, "status": task.status,
                                "seconds": round(time.monotonic() - started, 1)}},
            )
