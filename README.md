# ApplyFlow

[![CI](https://github.com/EngineerProjects/applyflow/actions/workflows/ci.yml/badge.svg)](https://github.com/EngineerProjects/applyflow/actions/workflows/ci.yml)

Application **locale**, **exécutable** et **explicable** de gestion de candidatures : backend
Python 3.12, interface web HTML/CSS/JS sans étape de build. Elle collecte des offres, sélectionne
le profil/ CV le plus adapté,
calcule un score d'adéquation motivé, prépare les formulaires en mode sécurisé et suit les
candidatures. Aucun abonnement IA payant n'est requis.

> **État : première version utilisable (MVP vertical).** Les phases 1 à 6 disposent d'une
> implémentation fonctionnelle, testée et documentée. Les limites et le reste à faire sont
> listés dans [docs/status.md](docs/status.md).

---

## Avertissement conformité — à lire avant utilisation

ApplyFlow n'est **pas** un robot de soumission massive.

* Il ne contourne **ni CAPTCHA, ni antibot, ni limitation d'accès**.
* **LinkedIn, Indeed, Glassdoor et HelloWork** ne sont lisibles que via le connecteur **JobSpy**,
  **désactivé par défaut** (extra `boards`, `[boards] jobspy_enabled = true`). Ces sites encadrent
  ou interdisent l'automatisation dans leurs conditions : usage personnel, volume faible, à vos
  risques (blocage d'IP possible). ApplyFlow limite le débit, s'arrête sur un 403/429 et ne
  résout aucun CAPTCHA. Welcome to the Jungle et Workday restent non moissonnés. Les valeurs de
  référence (`config.py`, `applyflow.example.toml`) le désactivent ; seul un `applyflow.toml` local
  peut l'activer, et l'interface demande alors une confirmation explicite. Ce dépôt-ci a fait ce
  choix pour ses propres collectes (`[boards] jobspy_enabled = true`).
* La collecte s'appuie sur des API officielles en lecture seule (Adzuna, Greenhouse, Lever), des
  flux RSS fournis par l'utilisateur, des fichiers JSON et des formulaires fictifs locaux.
* **Aucune candidature n'est envoyée automatiquement.** Par défaut, tout est en `dry-run` ; après
  revue humaine, la soumission est effectuée par la personne puis enregistrée dans ApplyFlow.
* Le respect des conditions d'utilisation de chaque site et la véracité des informations
  transmises relèvent de l'utilisateur.

---

## Ce qui fonctionne aujourd'hui

| Domaine | Implémentation |
|---|---|
| Profils | 5 profils de démonstration (Data Engineer, Data Analyst/BI, AI Engineer, Data Scientist, Python Developer), création illimitée, identité candidat, compétences, niveau, localisations, contrats, télétravail, salaire, exclusions, autorisation de travail |
| CV | Import PDF uniquement, validation de l'en-tête, empreinte SHA-256, stockage local, CV actif par profil, aucun CV réécrit |
| Collecte | Jeu fictif local (34 annonces, 33 uniques), **Adzuna (API officielle, clé gratuite)**, **Job boards via JobSpy et ATS publics via ats-scrapers (opt-in, extra `boards`)**, import JSON, RSS, Greenhouse, Lever, import d'une URL (JSON-LD/OpenGraph) |
| Dédoublonnage | Empreinte interplateformes entreprise + intitulé + localisation, canonicalisation d'URL, variantes H/F et suffixes juridiques |
| Routage | `laya_router.py` + routeur déterministe de secours, confiance distincte du score d'adéquation. **Le projet Laya audité (`aayushch/laya`) n'est pas un routeur ; le modèle de décision Laya de Convai Innovations est un autre projet, mesuré puis écarté — voir [docs/decision-model.md](docs/decision-model.md)** (voir [docs/laya.md](docs/laya.md)) |
| Scoring | Score 0–100 pondéré, explicable, portes d'éligibilité (séniorité, localisation, contrat, autorisation de travail, exclusions), seuils configurables, 0 à 2 ans prioritaire sans exclure les « 3 ans » non obligatoires |
| Préparation | Analyse HTML des formulaires, préremplissage depuis le profil et la bibliothèque de réponses validées, questions inconnues signalées, tests Playwright sur formulaires locaux, **jamais de clic sur « Envoyer »** |
| Validation | File de validation, approbation explicite, enregistrement de soumission, statuts, unicité par offre (aucun doublon) |
| Campagnes | Découverte → analyse → préparation, **exécution en arrière-plan avec progression et arrêt**, pause/reprise/annulation, reprise après interruption, idempotence, plafond 1 000+ offres, export CSV/JSON |
| Interface | Site web local 8 espaces : Tableau de bord, Profils & CV, Découverte, Campagnes, File de validation, Candidatures, Suivi e-mail, Réglages. Modules JS natifs, SVG et CSS, aucun framework front |
| API | FastAPI locale sur `127.0.0.1`, documentation OpenAPI automatique |
| Données | SQLite + SQLAlchemy 2 + migrations Alembic, journal d'audit, logs structurés JSON ou texte |
| Qualité | 401 tests pytest (unitaires, intégration, API, CLI, Playwright), dont 3 parcours de bout en bout dans un vrai navigateur, Ruff, couverture globale 91 % |

### Capacité 1 000 offres

Un banc d'essai reproductible collecte et analyse **1 000 offres synthétiques** dans une base
temporaire :

```bash
uv run python scripts/benchmark_1000.py
```

Résultat mesuré sur la machine de développement : **1 000 offres collectées et analysées en
12,7 s (~79 offres/s)**, 0 erreur. La préparation de formulaire est plus lente par construction
(une requête/lecture et une analyse par offre) et reste séquentielle.

### Qualité du classement

Sur un jeu de 40 offres étiquetées à la main, le banc de mesure recalcule le score ApplyFlow à
chaque exécution et le compare aux approches testées :

```bash
uv run python scripts/eval_matching.py
```

Mesure du 2026-10-24 : score ApplyFlow **AUC 0,85**, modèle de décision Laya **0,58–0,71**,
embeddings bge-m3 **0,99**. Laya n'est donc pas intégré ; la piste retenue est un signal
d'embeddings local. Protocole, limites et décision :
[docs/decision-model.md](docs/decision-model.md).

---

## Démarrage rapide

Prérequis : **Python 3.12+**, **[uv](https://docs.astral.sh/uv/)**. Aucun compte externe.

```bash
# 1. Dépendances (environnement local .venv)
uv sync

# 2. Navigateur pour le préremplissage Playwright (facultatif pour le reste)
uv run playwright install chromium

# 3. Configuration (facultative : les valeurs par défaut fonctionnent)
cp applyflow.example.toml applyflow.toml

# 4. Base locale vide (schéma + utilisateur local)
uv run applyflow init-db

# 5. Interface locale
uv run applyflow serve-ui
#    -> http://127.0.0.1:8501
```

L'application démarre **sans aucune donnée fictive**. Dans l'interface : créez votre profil et
déposez un CV PDF réel (**Profils**), puis lancez votre première collecte réelle
(**Découverte** : import d'une URL, board Greenhouse/Lever ou flux RSS). Une campagne se crée
ensuite dans **Campagnes** avec les sources et le profil choisis.

API locale (documentation interactive sur `/docs`) :

```bash
uv run applyflow serve-api
#    -> http://127.0.0.1:8000/docs
```

Aucune donnée fictive n'est chargée ni proposée dans l'application. Les jeux de données de test
(profils, CV, annonces fictifs) ne servent qu'à la suite de tests. Toutes vos données restent dans
`data/` (ignoré par Git).

### Tester avec le Makefile

Prérequis : `uv` et GNU make (`winget install ezwinports.make` sous Windows). `make` seul liste
les commandes.

| Commande | Rôle |
|---|---|
| `make install` | Dépendances, y compris JobSpy et ats-scrapers (extra `boards`) |
| `make ui` | Base (créée ou mise à jour) + interface sur <http://127.0.0.1:8501> |
| `make check` | Ruff + tous les tests (à lancer avant de commiter) |
| `make live-ats` | Test **réel** des ATS publics (Greenhouse, Lever, Ashby), base temporaire |
| `make live-boards CONFIRM=yes` | Test **réel** LinkedIn/Indeed/Glassdoor/HelloWork (~35 offres, à vos risques) |
| `make usage` | Offres collectées aujourd'hui par site, avec les plafonds |
| `make dedupe` | Recalcule empreintes de dédoublonnage et pays des offres déjà en base |
| `make measure-render` | Compare la lecture HTTP et la page rendue sur les offres en attente |

Les tests réels utilisent une base, des plafonds et une configuration **temporaires** : votre
`applyflow.toml` et votre compteur quotidien ne sont pas modifiés.

### Commandes

| Commande | Rôle |
|---|---|
| `uv run applyflow init-db` | Crée/met à jour le schéma via Alembic |
| `uv run applyflow status` | Métriques du tableau de bord |
| `uv run applyflow run-campaign [--id ID] [--name NOM] [--steps discover,analyze,prepare] [--max-items N]` | Exécute ou reprend une campagne |
| `uv run applyflow import-json --file offres.json` | Importe des annonces locales |
| `uv run applyflow export --campaign ID [--format csv\|json]` | Exporte les résultats |
| `uv run applyflow serve-ui` | Site web local (FastAPI + assets statiques) |
| `uv run applyflow serve-api` | API FastAPI |
| `uv run applyflow fill --attempt ID` | Préremplit une candidature **validée** avec Playwright, sans soumettre |
| `uv run applyflow record-submission --attempt ID` | Enregistre une soumission effectuée manuellement |
| `uv run applyflow providers` | Catalogue des connecteurs et limites |
| `uv run pytest` | Suite de tests (Chromium requis pour le test Playwright) |
| `uv run ruff check .` | Linting |

---

## Configuration

`applyflow.toml` (copié depuis `applyflow.example.toml`) est validé par Pydantic. Les chemins
relatifs partent du dossier du fichier. Variables d'environnement acceptées :

| Variable | Effet |
|---|---|
| `APPLYFLOW_CONFIG` | Chemin du fichier TOML |
| `APPLYFLOW_DATA_DIR` | Répertoire des données (SQLite, CV, exports) |
| `APPLYFLOW_DB_URL` | URL SQLAlchemy (par défaut `sqlite:///<data_dir>/applyflow.db`) |
| `APPLYFLOW_LOG_LEVEL` | `DEBUG`, `INFO`, `WARNING`… |
| `APPLYFLOW_DRY_RUN` | `true`/`false` (laisser `true` par défaut) |
| `APPLYFLOW_LAYA_TOKEN` | Jeton local Laya, à préférer au fichier de configuration |

Points clés :

* `[scoring.thresholds]` : `high`, `medium`, `min_apply` (80/65/65 par défaut).
* `[scoring]` : niveaux exclus (lead, principal, staff, head, director) et `max_required_years`.
* `[router]` : `deterministic` par défaut ; `laya`/`remote` optionnels avec repli automatique.
* `[application]` : `dry_run = true`, `allow_submit = false`. Le mode live n'active **pas** une
  soumission automatique : ApplyFlow ne clique jamais sur le bouton d'envoi.
* `[discovery]` : User-Agent, timeout, pause entre connecteurs.

Référence exhaustive des clés et précédence : [docs/configuration.md](docs/configuration.md).

---

## Architecture (monolithe Python, sans microservices)

```
src/applyflow/
├── config.py              # Settings Pydantic + TOML + environnement
├── db/                    # SQLAlchemy 2, modèles, migrations Alembic
├── schemas.py             # annonce normalisée, requête de découverte
├── text.py                # normalisation accents/tokens
├── providers/             # JobProvider + fixture, JSON, RSS, Greenhouse, Lever, URL
├── jobs/                  # ingestion, dédoublonnage, collecte séquentielle
├── matching/
│   ├── skills.py          # vocabulaire et alias de compétences
│   ├── seniority.py       # séniorité contextuelle + années exigées/souhaitées
│   ├── scoring.py         # score 0–100 + portes d'éligibilité
│   ├── router.py          # routeur déterministe + fallback
│   └── laya_router.py     # adaptateur Laya / contrat HTTP explicite
├── applications/          # analyse de formulaire, plan, réponses, Playwright, validation
├── campaigns/             # machine à états discover/analyze/prepare, reprise, idempotence
├── profiles/              # CRUD profils, import CV PDF
├── dashboard.py, export.py
├── api/                   # FastAPI locale (même logique métier que l'UI/CLI)
├── web/                   # Site local : index HTML, design system CSS, modules JS, pages
├── cli.py, seed.py
└── data/fixtures/jobs.json
```

**Flux** : `JobProvider.fetch` → normalisation → dédoublonnage → `Job` → campagne
(`discover` → `analyze` → `prepare`) → `RoutingDecision` + `ScoreResult` → `ApplicationAttempt`
(dry-run) → validation humaine → `Application`.

Décisions techniques majeures et compromis : [docs/architecture.md](docs/architecture.md).

### Base de données

Alembic crée : `users`, `profiles`, `resumes`, `jobs`, `job_sources`, `campaigns`,
`campaign_jobs`, `routing_decisions`, `application_attempts`, `applications`,
`application_answers`, `email_messages`, `audit_events`.

* Aucun mot de passe n'est stocké (pas de comptes : application locale mono-utilisateur).
* `applications.job_id` est **unique** : une offre ne peut pas être enregistrée deux fois.
* Les tentatives utilisent une clé d'idempotence (`offre + profil + CV + mode`).
* Chaque décision de routage et chaque étape sont journalisées.

---

## Audit des bibliothèques et projets voisins

Audit effectué le 2026-10-23 ; détails, licences et sources dans
[docs/audit.md](docs/audit.md).

* **Laya (`aayushch/laya`)** : Apache-2.0, application de bureau « centre de notifications IA ».
  **Ce n'est pas un routeur de CV** ; aucune API de sélection de CV n'est documentée. ApplyFlow
  n'invente donc pas d'appel : adaptateur explicite + routeur déterministe de secours.
* **JobSpy** : MIT, Python, schéma normalisé et séparation par plateforme. Ajouté comme
  **dépendance optionnelle** (`uv sync --extra boards`) et branché sur le connecteur `jobspy`,
  désactivé par défaut ; le scraping de LinkedIn/Indeed reste soumis à leurs conditions.
* **jobRabbit** : MIT mais en Rust ; inspiration architecturale (revue humaine, états persistés,
  approbation avant envoi), aucun code copié.
* **AIHawk** : licence du fork accessible restrictive, dépôt d'origine incertain ; **non réutilisé**.
* Aucun code de ces projets n'a été copié. Les seules dépendances ajoutées sont des bibliothèques
  génériques (SQLAlchemy, Pydantic, FastAPI, Playwright, httpx, BeautifulSoup, feedparser,
  Alembic). L'interface n'ajoute aucune dépendance : HTML, CSS et modules JavaScript natifs.

## Laya : ce qui est réellement intégré

Résumé (détail et contrat dans [docs/laya.md](docs/laya.md)) :

1. `LayaRouter` vérifie `GET /health` du moteur local (endpoint documenté).
2. S'il existe un **adaptateur local** (`router.remote_route_url`) implémentant le contrat
   ApplyFlow `applyflow.route.v1`, il l'appelle.
3. Sinon, il signale l'indisponibilité et le routeur déterministe prend le relais, sans bloquer la
   campagne. La **confiance du routeur** n'est jamais confondue avec le **score d'adéquation**.

---

## Connecteurs et limites

Tableau complet, formats d'import et règles de conformité : [docs/connectors.md](docs/connectors.md).

* **Adzuna** : API officielle d'un moteur de recherche d'offres, **clé gratuite** sur
  [developer.adzuna.com](https://developer.adzuna.com/signup). Renseignez `app_id` et `app_key`
  dans **Réglages → Collecte**, puis testez la connexion. C'est la voie recommandée pour chercher
  de vraies offres françaises sans extraction de page.
* Greenhouse / Lever : API publiques **en lecture seule**, aucun envoi automatique.
* RSS / JSON / URL : entrées fournies par l'utilisateur, requêtes séquentielles avec pause.
* HelloWork / LinkedIn / Indeed / Glassdoor : lisibles **uniquement** via le connecteur JobSpy
  opt-in, jamais activé par défaut ; les voies sûres restent Adzuna, les alertes e-mail et l'import
  manuel. WTTJ et Workday ne sont pas moissonnés. Détail des alternatives dans
  [docs/connectors.md](docs/connectors.md#hellowork-indeed-et-les-autres--ce-qui-est-possible).

## Données personnelles et sécurité

* Données locales par défaut : `data/applyflow.db`, CV dans `data/resumes/`, exports dans
  `data/exports/`. Aucune télémétrie, aucun appel à un LLM distant.
* **Protection contre les autres pages web** : l'API refuse (403) toute requête dont l'en-tête
  `Origin` n'est pas l'interface elle-même, et tout en-tête `Host` hors de `api.allowed_hosts`
  (par défaut `127.0.0.1`, `localhost`, `::1`). Sans cela, une page quelconque ouverte dans votre
  navigateur pourrait lire vos CV ou lancer des collectes sur `127.0.0.1`. Les appels sans `Origin`
  (curl, CLI, scripts locaux) restent autorisés.
* **Mot de passe Gmail** : rangé dans le trousseau du système (Gestionnaire d'identifiants
  Windows, Trousseau macOS, Secret Service), jamais dans `data/`. Un ancien fichier en clair est
  migré à la première lecture. Sans trousseau utilisable (ou `APPLYFLOW_NO_KEYRING=1`), il reste
  dans `data/secrets/gmail.json` et `GET /email/status` l'indique (`secret_storage: "file"`).
* L'API et l'UI écoutent sur `127.0.0.1` : ne pas les exposer publiquement sans ajouter
  authentification et HTTPS.
* Le jeton Laya et la clé Adzuna ne sont jamais renvoyés par l'API (`***`) ; ils peuvent être
  fournis par `APPLYFLOW_LAYA_TOKEN`, `APPLYFLOW_ADZUNA_APP_ID` et `APPLYFLOW_ADZUNA_APP_KEY`
  pour éviter de les écrire dans `applyflow.toml`.
* Les CV ne sont jamais modifiés ; ApplyFlow ne génère ni diplôme, ni expérience, ni autorisation.
* Sauvegarde/effacement = copie/suppression du répertoire `data/` (l'application ne gère pas encore
  de purge automatique).

## Tests

```bash
uv run pytest                 # 401 tests, dont 5 Playwright (skippés si Chromium est absent)
uv run pytest tests/test_e2e_ui.py  # 3 parcours complets : serveur local + navigateur
uv run pytest --cov=applyflow # couverture (~91 % global)
uv run ruff check .           # ou : make check (lint + tests)
```

Couverture fonctionnelle testée : configuration, migrations, dédoublonnage, séniorité
contextuelle, scoring/portes, routeur + fallback + contrat HTTP, connecteurs (MockTransport),
profils/CV, analyse de formulaires, préparation dry-run, questions inconnues, approbation,
soumission unique, reprise de campagne, idempotence, campagnes en arrière-plan (progression,
arrêt, une seule à la fois), CLI, parsing IMAP des réponses, export, API.

Les **parcours de bout en bout** ([test_e2e_ui.py](tests/test_e2e_ui.py)) démarrent un vrai serveur
sur un port libre, avec une base temporaire, puis pilotent Chromium comme une personne : les huit
écrans doivent s'afficher sans erreur JavaScript, un profil se crée par le formulaire, trois offres
s'importent depuis un fichier JSON et une campagne va jusqu'au bout (collecte → analyse →
préparation). Une page blanche ou un module cassé ne passe plus la suite.

## Intégration continue et publication

Chaque poussée sur `main` et chaque proposition de fusion rejoue sur GitHub Actions ce que
`make check` fait en local, et davantage ([ci.yml](.github/workflows/ci.yml)) :

| Job | Contenu |
|---|---|
| Ruff | analyse statique, dépendances installées depuis `uv.lock` |
| Tests | suite complète, Chromium installé au préalable : unitaires, API, Playwright et parcours de bout en bout de l'interface |
| Paquet | `uv build`, ressources web présentes dans le wheel, installation du wheel dans un environnement vierge et `applyflow --help` |

**Publier une version.** Le tag doit correspondre exactement à `version` dans `pyproject.toml` :

```bash
uv version --bump minor        # ou modifier `version` à la main
git commit -am "chore: version 0.2.0"
git tag v0.2.0
git push origin main --tags
```

[release.yml](.github/workflows/release.yml) appelle d'abord `ci.yml` comme workflow réutilisable :
rien n'est publié si les vérifications échouent. La version GitHub est ensuite créée avec les notes
calculées depuis le tag précédent et les artefacts `dist/` (wheel + archive source). Aucun secret à
créer : `GITHUB_TOKEN` suffit, et rien n'est envoyé vers PyPI.

## Limites connues

* Préparation limitée au HTML statique : les formulaires rendus uniquement en JavaScript ou derrière
  un CAPTCHA sont **bloqués**, jamais contournés.
* Pas d'adaptateurs de soumission spécifiques par ATS ; la soumission reste humaine.
* Pas de génération de lettre de motivation ni de réécriture de CV (choix assumé).
* Collecte séquentielle, sans pagination automatique au-delà de ce que le connecteur expose.
* Un seul CV actif par profil (conforme au choix « un CV fixe par profil »).

Voir [docs/status.md](docs/status.md) pour la liste « terminé / partiel / à faire ».

## Licence

MIT — voir [LICENSE](LICENSE).
