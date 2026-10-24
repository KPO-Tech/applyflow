"""Affiche le compteur quotidien de collecte (utilisé / plafond / reste) par site."""

from __future__ import annotations

from applyflow.config import load_settings
from applyflow.usage import UsageStore, usage_path

settings = load_settings()
store = UsageStore(usage_path(settings.app.data_dir), limits=settings.boards.daily_limits)
print(f"Compteur : {usage_path(settings.app.data_dir)}")
print(f"JobSpy activé : {'oui' if settings.boards.jobspy_enabled else 'non'}\n")
print(f"{'site':<12}{'utilisé':>8}{'plafond':>9}{'reste':>8}")
for site, row in store.snapshot().items():
    limit = "illimité" if row["limit"] is None else row["limit"]
    remaining = "-" if row["remaining"] is None else row["remaining"]
    print(f"{site:<12}{row['used']:>8}{limit!s:>9}{remaining!s:>8}")
