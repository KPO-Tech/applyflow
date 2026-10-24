"""Compteur quotidien de collecte par plateforme, mémorisé entre les lancements.

Le plafond protège votre adresse IP : il compte les offres collectées par site et par jour
(fuseau local) et reste valable même si l'application est relancée.
"""

from __future__ import annotations

import contextlib
import json
import os
from collections.abc import Callable
from datetime import date
from pathlib import Path

KEEP_DAYS = 30

# Plafonds par défaut (offres/jour/site). Prudents : LinkedIn détecte les rafales plus vite
# que les autres. Ajustables dans [boards.daily_limits].
DEFAULT_DAILY_LIMITS: dict[str, int] = {
    "linkedin": 75,
    "indeed": 200,
    "glassdoor": 150,
    "hellowork": 150,
    "google": 100,
}


class UsageStore:
    """`{jour: {site: nombre}}` dans un petit fichier JSON, écrit de façon atomique."""

    def __init__(
        self,
        path: Path,
        limits: dict[str, int] | None = None,
        today: Callable[[], date] = date.today,
    ) -> None:
        self.path = Path(path)
        self.limits = {**DEFAULT_DAILY_LIMITS, **(limits or {})}
        self._today = today

    def _load(self) -> dict[str, dict[str, int]]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}

    def _save(self, data: dict[str, dict[str, int]]) -> None:
        days = sorted(data)[-KEEP_DAYS:]
        data = {day: data[day] for day in days}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
        temporary.replace(self.path)

    def limit(self, site: str) -> int | None:
        value = self.limits.get(site)
        return None if value is None or value <= 0 else int(value)

    def used(self, site: str) -> int:
        return int(self._load().get(self._today().isoformat(), {}).get(site, 0))

    def remaining(self, site: str) -> int | None:
        """Offres encore autorisées aujourd'hui ; None si le site n'a pas de plafond."""
        limit = self.limit(site)
        return None if limit is None else max(0, limit - self.used(site))

    def consume(self, site: str, count: int) -> None:
        if count <= 0:
            return
        data = self._load()
        day = data.setdefault(self._today().isoformat(), {})
        day[site] = int(day.get(site, 0)) + int(count)
        with contextlib.suppress(OSError):
            self._save(data)

    def snapshot(self) -> dict[str, dict[str, int | None]]:
        """État du jour pour l'affichage : utilisé, plafond, reste, par site."""
        sites = sorted(set(self.limits) | set(self._load().get(self._today().isoformat(), {})))
        return {
            site: {"used": self.used(site), "limit": self.limit(site), "remaining": self.remaining(site)}
            for site in sites
        }


def usage_path(data_dir: Path) -> Path:
    return Path(os.fspath(data_dir)) / "collection_usage.json"
