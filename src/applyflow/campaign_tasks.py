"""Campagnes en arrière-plan : progression, arrêt, une seule exécution à la fois.

Une campagne prépare des dizaines de formulaires : chaque offre coûte une requête HTTP et une
analyse HTML. L'exécution tourne donc dans un thread avec sa propre session, pendant que
l'interface suit l'avancement. Comme pour la collecte, une seule exécution à la fois : deux
campagnes simultanées écriraient dans la même base SQLite et prépareraient les mêmes offres.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from applyflow.campaigns.service import STEPS, run_campaign
from applyflow.config import Settings
from applyflow.db.base import Database
from applyflow.logging_setup import get_logger

logger = get_logger("campaigns")

KEEP_TASKS = 20

STEP_LABELS = {
    "discover": "Collecte des offres",
    "analyze": "Analyse et score",
    "prepare": "Préparation des candidatures",
}


class CampaignBusy(RuntimeError):
    """Une campagne est déjà en cours d'exécution."""


@dataclass
class CampaignTask:
    id: str
    campaign_id: str
    status: str = "running"  # running | done | cancelled | error
    started_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    finished_at: str | None = None
    progress: dict[str, Any] = field(
        default_factory=lambda: {"step": "", "done": 0, "total": 0, "label": "Démarrage…"}
    )
    result: dict[str, Any] | None = None
    error: str | None = None
    cancel_event: threading.Event = field(default_factory=threading.Event, repr=False)

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "campaign_id": self.campaign_id,
            "status": self.status,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "progress": dict(self.progress),
            "cancel_requested": self.cancel_event.is_set(),
            "result": self.result,
            "error": self.error,
        }


Runner = Callable[..., Any]


class CampaignManager:
    def __init__(self) -> None:
        self._tasks: dict[str, CampaignTask] = {}
        self._lock = threading.Lock()

    def active(self) -> CampaignTask | None:
        with self._lock:
            return next((t for t in self._tasks.values() if t.status == "running"), None)

    def get(self, task_id: str) -> CampaignTask:
        with self._lock:
            task = self._tasks.get(task_id)
        if task is None:
            raise LookupError(f"exécution de campagne introuvable : {task_id}")
        return task

    def start(
        self,
        database: Database,
        settings: Settings,
        campaign_id: str,
        *,
        steps: Sequence[str] = STEPS,
        max_items: int | None = None,
        redo: bool = False,
        min_score: int | None = None,
        runner: Runner | None = None,
    ) -> CampaignTask:
        with self._lock:
            if any(t.status == "running" for t in self._tasks.values()):
                raise CampaignBusy(
                    "Une campagne est déjà en cours. Attendez sa fin ou arrêtez-la : "
                    "ApplyFlow n'exécute jamais deux campagnes en parallèle."
                )
            task = CampaignTask(id=uuid4().hex[:12], campaign_id=campaign_id)
            self._tasks[task.id] = task
            for old in list(self._tasks)[:-KEEP_TASKS]:
                self._tasks.pop(old, None)
        threading.Thread(
            target=self._run,
            args=(task, database, settings),
            kwargs={
                "steps": steps,
                "max_items": max_items,
                "redo": redo,
                "min_score": min_score,
                "runner": runner or run_campaign,
            },
            name=f"campaign-{task.id}",
            daemon=True,
        ).start()
        return task

    def cancel(self, task_id: str) -> CampaignTask:
        """Demande l'arrêt : la campagne s'interrompt entre deux offres et reste reprenable."""
        task = self.get(task_id)
        if task.status == "running":
            task.cancel_event.set()
            task.progress["label"] = "Arrêt en cours…"
        return task

    def _run(
        self,
        task: CampaignTask,
        database: Database,
        settings: Settings,
        *,
        steps: Sequence[str],
        max_items: int | None,
        redo: bool,
        min_score: int | None,
        runner: Runner,
    ) -> None:
        started = time.monotonic()

        def on_progress(step: str, done: int, total: int) -> None:
            label = STEP_LABELS.get(step, step or "Démarrage")
            task.progress = {
                "step": step,
                "done": done,
                "total": total,
                "label": f"{label} · {done}/{total}" if total else label,
            }

        try:
            with database.session() as session:
                result = runner(
                    session,
                    task.campaign_id,
                    settings,
                    steps=steps,
                    max_items=max_items,
                    redo=redo,
                    min_score=min_score,
                    should_stop=task.cancel_event.is_set,
                    on_progress=on_progress,
                )
            task.result = result
            task.status = "cancelled" if task.cancel_event.is_set() else "done"
        except Exception as exc:  # la tâche ne doit jamais faire tomber le serveur
            logger.exception("campagne en échec")
            task.status = "error"
            task.error = str(exc) or type(exc).__name__
        finally:
            task.finished_at = datetime.now(UTC).isoformat()
            logger.info(
                "campagne arrière-plan terminée",
                extra={
                    "data": {
                        "id": task.id,
                        "campaign_id": task.campaign_id,
                        "status": task.status,
                        "seconds": round(time.monotonic() - started, 1),
                    }
                },
            )
