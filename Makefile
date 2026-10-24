# ApplyFlow : commandes d'installation, d'exécution et de test.
#   make            affiche cette aide
#   make ui         lancer l'interface (la base est créée ou mise à jour au besoin)
# Prérequis : Python 3.12+, uv (https://docs.astral.sh/uv/), GNU make.

UV      ?= uv
UI_PORT ?= 8501

.DEFAULT_GOAL := help
.PHONY: help install browsers config init ui api status providers usage dedupe \
        test test-fast cov lint fix check bench eval measure-render live-ats live-boards clean

help:
	@echo "ApplyFlow - commandes"
	@echo ""
	@echo "Installation"
	@echo "  make install       dependances (y compris JobSpy et ats-scrapers)"
	@echo "  make browsers      navigateur Chromium pour le prerempliage et les tests"
	@echo "  make config        cree applyflow.toml depuis l'exemple (sans ecraser)"
	@echo "  make init          cree ou met a jour la base locale"
	@echo ""
	@echo "Utilisation"
	@echo "  make ui            interface web locale (http://127.0.0.1:$(UI_PORT))"
	@echo "  make api           API locale (http://127.0.0.1:8000/docs)"
	@echo "  make status        metriques du tableau de bord"
	@echo "  make providers     connecteurs disponibles et limites"
	@echo "  make usage         offres collectees aujourd'hui par site, avec les plafonds"
	@echo "  make dedupe        recalcule les empreintes de dedoublonnage et les pays"
	@echo ""
	@echo "Qualite"
	@echo "  make test          tous les tests"
	@echo "  make test-fast     tests sans le navigateur"
	@echo "  make cov           tests avec couverture"
	@echo "  make lint          ruff"
	@echo "  make fix           ruff avec corrections automatiques"
	@echo "  make check         lint + tests (a lancer avant de commiter)"
	@echo "  make bench         1 000 offres synthetiques (hors reseau)"
	@echo "  make eval          qualite du classement sur les offres etiquetees"
	@echo ""
	@echo "Tests reels (reseau, base et plafonds TEMPORAIRES : votre config n'est pas touchee)"
	@echo "  make live-ats                    ATS publics (Greenhouse, Lever, Ashby)"
	@echo "  make live-boards CONFIRM=yes     LinkedIn/Indeed/Glassdoor/HelloWork, ~35 offres, a vos risques"
	@echo ""
	@echo "  make clean         supprime les caches (jamais data/)"

install:
	$(UV) sync --extra boards

browsers:
	$(UV) run playwright install chromium

config:
	$(UV) run python -c "import pathlib, shutil; p = pathlib.Path('applyflow.toml'); print('applyflow.toml existe deja') if p.exists() else (shutil.copy('applyflow.example.toml', p), print('applyflow.toml cree'))"

init:
	$(UV) run applyflow init-db

ui: init
	@echo "Interface : http://127.0.0.1:$(UI_PORT)  (Ctrl+C pour arreter)"
	$(UV) run applyflow serve-ui

api: init
	$(UV) run applyflow serve-api

status:
	$(UV) run applyflow status

providers:
	$(UV) run applyflow providers

usage:
	$(UV) run python scripts/usage.py

dedupe: init
	$(UV) run applyflow rebuild-dedupe

test:
	$(UV) run pytest

test-fast:
	$(UV) run pytest -m "not playwright"

cov:
	$(UV) run pytest --cov=applyflow --cov-report=term-missing:skip-covered

lint:
	$(UV) run ruff check .

fix:
	$(UV) run ruff check . --fix

check: lint test

bench:
	$(UV) run python scripts/benchmark_1000.py

eval:
	$(UV) run python scripts/eval_matching.py

measure-render:
	$(UV) run python scripts/measure_rendering.py

live-ats:
	$(UV) run python scripts/live_check.py ats

live-boards:
ifeq ($(CONFIRM),yes)
	$(UV) run python scripts/live_check.py boards --confirm
else
	@echo "Refuse : live-boards interroge LinkedIn, Indeed, Glassdoor et HelloWork."
	@echo "Ces sites encadrent l'automatisation (usage personnel, a vos risques)."
	@echo "Relancez avec : make live-boards CONFIRM=yes"
	@exit 1
endif

clean:
	$(UV) run python scripts/clean.py
