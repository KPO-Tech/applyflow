# Audit des projets et bibliothèques open source

Audit réalisé le **2026-10-23**, complété le **2026-10-24** (dépendances optionnelles). Objectif : vérifier avant réutilisation la licence, la
maintenance, les dépendances et la conformité d'usage. Aucun code de ces dépôts n'a été copié dans
ApplyFlow ; les composants listés sont des références de conception ou des dépendances génériques.

## Synthèse

| Projet | Langue / licence | Activité observée | Réutilisable ? | Décision ApplyFlow |
|---|---|---|---|---|
| [Laya](https://github.com/aayushch/laya) | Python + Node + Rust, **Apache-2.0** | Releases récentes (v2.3.0 au moment de l'audit) | Oui comme application locale, mais **pas un routeur de CV** | Adaptateur explicite + limite documentée + fallback déterministe. Aucune API inventée |
| [JobSpy](https://github.com/speedyapply/JobSpy) | Python, **MIT** | Commits jusqu'à octobre 2026 | Schéma normalisé et séparation par plateforme | **Dépendance optionnelle** (extra `boards`) ; connecteur `jobspy` désactivé par défaut |
| [jobRabbit](https://github.com/renanmpimentel/jobrabbit) | Rust, **MIT** | Commits jusqu'à juillet 2026 | Architecture de revue humaine et états persistés | Inspiration (approbation avant envoi, suivi d'états) ; aucun code Rust porté |
| [AIHawk (fork accessible)](https://github.com/11844/Auto_Jobs_Applier_AIHawk) | Python, licence **restrictive personnalisée** | Dernier commit inspecté : octobre 2024 | Non sans autorisation/revue juridique | Non utilisé |
| [Auto_job_applier_linkedIn](https://github.com/GodsScion/Auto_job_applier_linkedIn) | Python, MIT **depuis août 2026** (AGPL avant) | Commits jusqu'à septembre 2026 | Automatisation LinkedIn contraire aux règles de la plateforme | Non utilisé |
| [job-application-automator](https://github.com/tarunmovva/job-application-automator) | Python, **MIT** | Septembre 2025 | Analyse de formulaire Playwright, revue avant envoi | Idées générales ; approche « stealth » non reprise |
| [linkedin_scraper](https://github.com/joeyism/linkedin_scraper) | Python | Avril 2026 | Incohérence de licence (`pyproject` Apache-2.0 vs `LICENSE` GPL-3.0) | Écarté |

## Constat Laya (concerne `aayushch/laya` uniquement)

> Correction du 2026-10-24 : le modèle de décision « Laya » de Convai Innovations est un **autre** projet,
> voir [laya.md](laya.md) et [decision-model.md](decision-model.md).

Le brief supposait que `aayushch/laya` était un outil de routage de CV. La documentation réelle
décrit un **centre de notifications IA local** (Slack, Gmail, GitHub, Jira, Outlook, calendriers),
avec :

* un moteur FastAPI local (`/health`, `/events`) et des Action Cards approuvées par l'humain ;
* n8n, SQLite et ChromaDB en local ;
* des modèles locaux (Ollama/LM Studio) ou distants optionnels ;
* **aucune API de matching/sélection de CV documentée** ;
* une installation par release de bureau (le paquet PyPI `laya` est un autre projet).

Conséquence : ApplyFlow implémente une interface de routage, un adaptateur Laya/HTTP et un fallback
déterministe. Voir [laya.md](laya.md) pour le contrat exact et les sources.

## jobRabbit

* Licence MIT, application Rust (Axum, React, SQLite), exécution de Claude Code en sous-processus.
* Fonctionnalités intéressantes : revue humaine avant remplissage/soumission, états de candidature,
  playbooks par ATS, import/export, avertissement sur les conditions des sites.
* Non réutilisé : Rust, dépendance à Claude Code, architecture différente. Les principes
  (approbation, reprise, état explicite) sont réimplémentés en Python.
* Le README du projet signale lui-même que l'usage peut entrer en conflit avec les conditions des
  plateformes.

## JobSpy

* MIT, Python ≥3.10, dépendances `requests`, `beautifulsoup4`, `pandas`, `pydantic`, `curl_cffi`,
  `markdownify`.
* Bonne séparation par plateforme et schéma normalisé.
* **Ajouté comme dépendance optionnelle** : `uv sync --extra boards` installe
  `python-jobspy` (avec pandas/curl_cffi). Sans cet extra, ApplyFlow fonctionne normalement et le
  connecteur signale que la bibliothèque manque.
* Le connecteur `jobspy` reste **désactivé par défaut** (`[boards] jobspy_enabled = false`) :
  l'activer relève d'un choix explicite, confirmé dans l'interface, et le scraping de
  LinkedIn/Indeed reste régi par leurs conditions. Les API publiques (Adzuna, Greenhouse, Lever),
  le RSS et les imports explicites demeurent les voies recommandées.
* Avant redistribution, vérifiez la licence des dépendances de l'extra et les conditions de chaque
  site.

## AIHawk et automatisation LinkedIn

* Le dépôt d'origine `feder-cr/Jobs_Applier_AI_Agent_AIHawk` redirige vers un autre compte ; sa
  licence actuelle n'a pas pu être vérifiée depuis cette redirection.
* Le fork accessible `11844/Auto_Jobs_Applier_AIHawk` utilise une **licence personnalisée non
  permissive** (usage non commercial, dérivés publics, restrictions).
* Le projet GodsScion indique MIT pour les versions récentes, mais AGPL-3.0 avant août 2026.
* Les deux automatisent LinkedIn Easy Apply, ce que LinkedIn interdit aux logiciels tiers. Aucun
  code, sélecteur ou scénario de soumission n'a été repris.

## Licences des dépendances ajoutées

Toutes les dépendances directes sont des bibliothèques génériques à licence permissive (MIT/BSD/
Apache) : FastAPI, Starlette, Uvicorn, SQLAlchemy, Alembic, Pydantic, httpx, BeautifulSoup4,
feedparser, Playwright, tomli-w, keyring, pycountry. Les extras `boards` ajoutent deux
bibliothèques MIT (`python-jobspy`, `ats-scrapers`) et `decision` ajoute Laya (Apache-2.0) ; ils
restent facultatifs. L'interface web n'ajoute aucune dépendance : HTML, CSS et modules JavaScript
natifs sont servis par FastAPI. Vérifier `uv.lock` et les notices lors d'une
redistribution ; la licence du navigateur Playwright s'applique séparément.

## Sources inspectées

* Laya : README, `docs/architecture.md`, `docs/api-contracts.md`, `docs/event-schema.md`,
  `docs/tuning-parameters.md`, releases, `engine/requirements.txt`, LICENSE.
* JobSpy : README, `pyproject.toml`, LICENSE, historique des commits.
* ats-scrapers : README, `pyproject.toml`, LICENSE, dossier `ats-companies/`, historique.
* jobRabbit : README, `Cargo.toml`, historique des commits.
* AIHawk : README du fork, `requirements.txt`, LICENSE, historique.
* GodsScion : README, requirements, LICENSE, historique.
* tarunmovva : README, requirements, LICENSE, historique.
* joeyism `linkedin_scraper` : `pyproject.toml`, LICENSE, historique.
* Conditions : LinkedIn (logiciels interdits), Indeed (limites d'application), Greenhouse, Lever.

Les informations d'activité et de licence reflètent l'état observé à la date de l'audit et peuvent
changer ; revérifier avant toute réutilisation ou redistribution.
