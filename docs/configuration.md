# Configuration

Fichier par défaut : `applyflow.toml` à la racine (copié depuis `applyflow.example.toml`).
Sans fichier, les valeurs par défaut s'appliquent et les données vont dans `./data/`.

## Précédence

1. Arguments CLI (`--config`).
2. Variable `APPLYFLOW_CONFIG` (chemin du TOML).
3. `./applyflow.toml` s'il existe.
4. Valeurs par défaut.

Les surcharges d'environnement suivantes s'appliquent après lecture du TOML :
`APPLYFLOW_DATA_DIR`, `APPLYFLOW_DB_URL`, `APPLYFLOW_LOG_LEVEL`, `APPLYFLOW_DRY_RUN`,
`APPLYFLOW_LAYA_TOKEN`, `APPLYFLOW_ADZUNA_APP_ID`, `APPLYFLOW_ADZUNA_APP_KEY`.

Les chemins relatifs de `data_dir` sont résolus depuis le dossier du fichier de configuration.

## Référence

### `[app]`

| Clé | Défaut | Rôle |
|---|---|---|
| `data_dir` | `data` | Base SQLite, CV, exports |
| `db_url` | vide | URL SQLAlchemy ; vide ⇒ `sqlite:///<data_dir>/applyflow.db` |
| `log_level` | `INFO` | Niveau des logs |
| `log_json` | `false` | Logs JSON structurés |
| `demo_forms` | `true` | Autorise les URLs `demo://` fournies avec le projet |

### `[router]`

| Clé | Défaut | Rôle |
|---|---|---|
| `provider` | `deterministic` | `deterministic`, `laya`, `remote` |
| `fallback_to_deterministic` | `true` | Repli si Laya/HTTP indisponible |
| `laya_base_url` | `http://127.0.0.1:8420` | Moteur Laya local (santé) |
| `laya_token` | vide | Jeton éventuel ; préférer `APPLYFLOW_LAYA_TOKEN` |
| `remote_route_url` | vide | Adaptateur local au contrat `applyflow.route.v1` |
| `timeout_seconds` | `10` | Timeout HTTP du routeur |
| `uncertainty_margin` | `0.08` | Marge sous laquelle le choix est incertain |

Voir [laya.md](laya.md) pour le contrat et ses limites.

### `[discovery]`

| Clé | Défaut | Rôle |
|---|---|---|
| `user_agent` | `ApplyFlow/0.1 …` | User-Agent des requêtes |
| `timeout_seconds` | `20` | Timeout des connecteurs |
| `rate_limit_seconds` | `1.0` | Pause entre connecteurs (séquentiel) |
| `max_jobs_default` | `1000` | Référence de capacité (les campagnes portent leur propre plafond) |

### `[adzuna]`

| Clé | Défaut | Rôle |
|---|---|---|
| `app_id` | vide | Identifiant d'application Adzuna (gratuit) |
| `app_key` | vide | Clé Adzuna ; masquée par l'API, préférer `APPLYFLOW_ADZUNA_APP_KEY` |
| `country` | `fr` | Pays interrogé (`fr`, `gb`, `us`…) |
| `max_pages` | `5` | Pages maximales par collecte (1 à 20) |

Sans `app_id`/`app_key`, le connecteur refuse de démarrer avec un message explicite ; les autres
sources restent utilisables. La clé s'obtient sur <https://developer.adzuna.com/signup>.

### `[scoring]`

| Clé | Défaut | Rôle |
|---|---|---|
| `weights.*` | 30/20/20/15/5/5/5 | Compétences, intitulés, séniorité, expérience, localisation, contrat, obligations |
| `thresholds.high` | `80` | Priorité haute |
| `thresholds.medium` | `65` | Priorité moyenne |
| `thresholds.min_apply` | `65` | Score minimal de préparation |
| `excluded_seniority` | lead, principal, staff, head, director | Portes d'exclusion |
| `penalized_seniority` | senior | Pénalisé, pas nécessairement exclu |
| `max_required_years` | `5.0` | Au-delà d'années **obligatoires**, offre inéligible |

Contrainte : `high > medium >= min_apply`. Les poids doivent être strictement positifs.

### `[application]`

| Clé | Défaut | Rôle |
|---|---|---|
| `dry_run` | `true` | Aucune soumission ; préparation et analyse seulement |
| `allow_submit` | `false` | Réservé à un usage futur ; ApplyFlow ne soumet pas |
| `headless` | `true` | Navigateur Playwright sans fenêtre |
| `render_forms` | `true` | Relit la page dans un navigateur quand le HTML servi ne contient aucun champ (formulaires construits en JavaScript) ; aucune interaction, aucun envoi |
| `max_resume_mb` | `5` | Taille maximale d'un CV |
| `max_form_bytes` | `2000000` | Taille maximale d'un formulaire HTML |

### `[search]`

Recherche préremplie dans l'écran Découverte (modifiable dans Réglages → Collecte → « Recherche
par défaut »).

| Clé | Défaut | Rôle |
|---|---|---|
| `keywords` | Data Engineer junior, Data Analyst junior, AI Engineer junior, Data Scientist junior, Graduate Data Engineer | Une recherche par mot-clé |
| `locations` | `["France"]` | Un pays retrouve aussi les offres de ses villes |
| `limit` | `100` | Offres maximum par collecte (1 à 5 000) |
| `ats_companies` | 10 entreprises (Datadog, Doctolib, Algolia, Mirakl, Dataiku, Qonto, Contentsquare, BlaBlaCar, Alan, Back Market) | Format `ats:identifiant`. Identifiants vérifiés le 2026-10-23 : ils peuvent changer |

### `[boards]`

| Clé | Défaut | Rôle |
|---|---|---|
| `jobspy_enabled` | `false` | Autorise la collecte sur LinkedIn/Indeed/Glassdoor/HelloWork (voir [discovery.md](discovery.md)) |
| `sites` | `["indeed", "hellowork"]` | Sites cochés par défaut (LinkedIn n'y est pas : il détecte le plus vite les rafales) |
| `country` | `france` | Pays de la recherche (indice faible pour le pays des offres) |
| `max_per_site` | `100` | Offres maximum par site et par collecte |
| `pause_seconds` | `5` | Pause entre deux requêtes |
| `daily_limits.<site>` | linkedin 75, indeed 200, glassdoor 150, hellowork 150, google 100 | Plafond d'offres par jour et par site (`0` = aucun) |

JobSpy est **désactivé par défaut** dans le code et dans `applyflow.example.toml`. Seul un
`applyflow.toml` local peut l'activer, et l'interface demande alors une confirmation explicite :
c'est un choix de l'utilisateur, jamais un réglage de campagne.

Variable d'environnement : `APPLYFLOW_NO_KEYRING=1` désactive le trousseau du système pour le mot
de passe Gmail.

### `[api]` / `[ui]`

| Clé | Défaut | Rôle |
|---|---|---|
| `api.host` / `api.port` | `127.0.0.1` / `8000` | Écoute FastAPI |
| `ui.port` | `8501` | Écoute du site local (hôte forcé à `127.0.0.1`) |
| `api.allowed_hosts` | `["127.0.0.1", "localhost", "::1"]` | Noms d'hôte acceptés dans l'en-tête `Host` (anti « DNS rebinding »). Une requête dont l'`Origin` n'est pas celle de l'interface est aussi refusée |

## Enregistrement depuis l'UI

La page **Réglages** écrit les seuils, le routeur, le dry-run et la pause de collecte dans
`applyflow.toml` (ou le chemin `config_path` chargé), puis demande un redémarrage. Les valeurs
`None` sont omises pour rester valides en TOML. Le jeton Laya n'est jamais affiché par l'API.

## Sécurité

* Ne pas exposer `[api]`/`[ui]` sur une interface réseau publique : aucune authentification intégrée.
* Protéger `applyflow.toml` si vous y mettez un jeton ou une clé ; préférer les variables
  `APPLYFLOW_LAYA_TOKEN`, `APPLYFLOW_ADZUNA_APP_ID` et `APPLYFLOW_ADZUNA_APP_KEY`.
* La clé Adzuna n'est jamais renvoyée par `GET /settings` (valeur `***`).
* Les CV et la base contiennent des données personnelles : sauvegardes chiffrées et permissions
  de fichiers adaptées recommandées.
