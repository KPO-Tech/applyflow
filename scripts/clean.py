"""Supprime les caches de test et de lint (portable : Windows, macOS, Linux)."""

from __future__ import annotations

import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

for name in (".pytest_cache", ".ruff_cache", ".coverage", "htmlcov", "build", "dist"):
    target = ROOT / name
    if target.is_dir():
        shutil.rmtree(target, ignore_errors=True)
        print(f"supprimé : {name}/")
    elif target.is_file():
        target.unlink()
        print(f"supprimé : {name}")

for cache in ROOT.glob("src/**/__pycache__"):
    shutil.rmtree(cache, ignore_errors=True)
for cache in ROOT.glob("tests/__pycache__"):
    shutil.rmtree(cache, ignore_errors=True)
print("Caches nettoyés. Vos données (data/) ne sont jamais touchées.")
