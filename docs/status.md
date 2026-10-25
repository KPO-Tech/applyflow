# État du projet : terminé, partiel, à faire

Dernière mise à jour : 2026-10-25. Ce document remplace toute promesse implicite du brief.

## Synthèse

| Phase | État | Commentaire |
|---|---|---|
| 1 — Fondations | ✅ Terminée | Paquet Python, configuration TOML validée, SQLite/SQLAlchemy/Alembic, UI minimale, tests |
| 2 — Profils | ✅ Terminée | CRUD profils, CV PDF validés et stockés, préférences, identité candidat ; jeu de démo facultatif via `seed` |
| 3 — Collecte | ✅ Terminée (périmètre conforme) | Fixture, JSON, RSS, Greenhouse, Lever, URL, **Adzuna** ; **JobSpy et ATS publics en opt-in** ; normalisation et dédoublonnage |
| 4 — Intelligence | 🟡 Partielle | Routage déterministe + scoring complets ; Laya natif impossible (pas d'API CV), adaptateur fourni ; modèle de décision **mesuré et écarté** |
| 5 — Candidatures | 🟡 Partielle | Dry-run, analyse/préremplissage HTML, réponses, approbation, suivi ; pas de soumission automatique |
| 6 — Campagnes | ✅ Terminée | 1 000 offres, **exécution en arrière-plan**, pause/reprise/annulation, idempotence, tableau de bord, exports |
| Transverse | ✅ Terminée | API locale, CLI, site web 8 espaces, logs structurés, audit, docs, 401 tests (91 % de couverture) dont 3 parcours de bout en bout dans le navigateur, benchmark 1 000 |

## Détail

### Phase 1 — Fondations ✅

* Structure `src/applyflow`, `pyproject.toml`, uv, Python 3.12.
* Configuration Pydantic + TOML + variables d'environnement, exemple fourni.
* Modèles SQLAlchemy, contraintes d'unicité, migration Alembic initiale.
* Journalisation JSON/texte, journal d'audit (`audit_events`).
* Site web local 8 espaces (HTML/CSS/JS sans build), FastAPI locale, CLI.

### Phase 2 — Profils ✅

* CRUD profils, activation/désactivation, validation des champs et salaires.
* Aucun profil fictif dans l'application : les profils de test n'existent que dans la suite de tests.
* Import PDF uniquement, contrôle `%PDF-`, taille maximale, SHA-256, stockage local, CV actif unique.
* Identité de préremplissage : nom complet, e-mail, téléphone, ville, LinkedIn, GitHub, site.
* Préférences : localisations, contrats, télétravail, salaire, exclusions, autorisation de travail.
* Les CV ne sont jamais modifiés ni générés.

### Phase 3 — Collecte ✅

* `JobProvider` + registre extensible.
* 34 annonces fictives (33 uniques), sans réseau.
* Import JSON documenté, flux RSS, API publiques Greenhouse/Lever, import d'une URL (JSON-LD).
* Adzuna : API officielle, clé gratuite, pagination (50 résultats/page), identifiants stockés
  localement, masqués dans l'API et testables depuis Réglages → Collecte.
* Normalisation : HTML, télétravail, contrat, séniorité, compétences, salaire, dates.
* Dédoublonnage interplateformes (empreinte métier + URL canonique) et testé.
* JobSpy (job boards) et ats-scrapers (ATS publics) en **opt-in** : désactivés par défaut dans
  le code et l'exemple, activés par un `applyflow.toml` local après confirmation dans l'interface.
  WTTJ et Workday restent non moissonnés ; conditions documentées.
* HelloWork : pas d'API de recherche publique ; hors connecteur JobSpy opt-in, seules les voies
  conformes sont documentées (Adzuna, alertes e-mail, import manuel).

### Phase 4 — Intelligence 🟡

**Fait**

* `laya_router.py` : santé du moteur Laya + adaptateur HTTP documenté, erreurs typées.
* Fallback déterministe, journalisé, sans interruption de campagne.
* Banc de mesure rejouable (`scripts/eval_matching.py`, `matching/evaluation.py`) : AUC, top-k
  et rang moyen sur 40 offres étiquetées ; le score ApplyFlow y est recalculé à chaque
  exécution. **Mesure : Laya (AUC 0,58–0,71) reste sous le score déterministe (0,85)** —
  non intégré, voir [decision-model.md](decision-model.md).
* Routeur déterministe explicable : intitulés, compétences, niveau, confiance par marge.
* Détection contextuelle de séniorité (évite « senior stakeholders »), années obligatoires vs
  souhaitées, plafond configurable.
* Scoring 0–100 à 7 composantes, portes d'éligibilité, raisons détaillées, seuils et priorités.
* Séparation stricte confiance routeur / score d'adéquation.

**Partiel / non réalisable tel quel**

* Laya **ne fournit pas** de routage de CV ; aucun modèle de matching n'est appelé. Un adaptateur
  local est nécessaire pour un usage Laya réel (voir [laya.md](laya.md)). Le modèle de décision
  homonyme a été mesuré : écarté pour l'instant (voir [decision-model.md](decision-model.md)).
* Le routage est lexical, pas sémantique vectoriel : les synonymes hors vocabulaire peuvent être
  manqués. Les choix incertains sont marqués.
* Pas d'extraction de texte du CV pour enrichir la décision (le CV est choisi via le profil).

### Phase 5 — Candidatures 🟡

**Fait**

* Analyse HTML des champs (labels, types, requis, options, sélecteurs).
* Mapping vers les données du profil, CV actif, bibliothèque de réponses **validées**.
* Détection des questions inconnues ; statut `needs_review` au lieu d'inventer une réponse.
* Aucune valeur inventée : sources `profile`, `resume`, `answer_library` uniquement.
* Dry-run par défaut ; Playwright remplit sans jamais cliquer sur « Envoyer ».
* Validation explicite, création d'`Application`, enregistrement de soumission, unicité par offre.
* Gestion des formulaires indisponibles (`blocked`) sans crash.
* Tests Playwright sur formulaire fictif local.
* Suivi e-mail IMAP en lecture seule : classification des réponses, rapprochement avec les
  candidatures, relances suggérées, mot de passe rangé dans le trousseau du système.

**Partiel / à faire**

* Un formulaire construit en JavaScript est maintenant lu dans un navigateur quand le HTML
  servi ne contient aucun champ (`application.render_forms`, aucun clic). Sur les 21 offres en
  attente du 24/10, cette relecture n'a rien débloqué : la candidature y est derrière une page
  séparée, une saisie d'e-mail ou une connexion (voir [measure-rendering](../scripts/measure_rendering.py)).
* Parcours à plusieurs étapes (page de candidature distincte, e-mail d'entrée, compte) et
  CAPTCHA : à faire à la main. La suite est spécifiée, sans être construite : suivre le lien de
  candidature, session de navigateur persistante, puis agent borné — voir
  [agent-navigation.md](agent-navigation.md).
* Pas d'adaptateur de soumission par ATS ; la soumission humaine reste la norme.
* Pas de génération de lettre de motivation ni de réponses libres par IA (choix).
* Un seul CV actif par profil ; pas de variantes multiples.

### Phase 6 — Campagnes ✅

* Découverte, analyse et préparation par étapes, état persisté par offre.
* **Exécution en arrière-plan** (`POST /campaigns/{id}/run/start`) : progression par étape,
  arrêt entre deux offres, reprise après navigation, une seule campagne à la fois.
* Une étape qui échoue remet la campagne **en pause** avec sa cause (`last_error`) au lieu de la
  laisser « en cours » : elle reste reprenable.
* Pause, reprise, annulation, reprise après interruption (commit par offre).
* Idempotence : pas de double préparation ni de double candidature.
* Plafond `max_jobs` (jusqu'à 5 000 configurable), seuil de score, niveaux autorisés.
* Tableau de bord, file de validation, historique, export CSV/JSON.
* Benchmark 1 000 offres : ~12,7 s pour collecte + analyse, 0 erreur.

**Partiel**

* Les tâches vivent en mémoire : un redémarrage du serveur interrompt le suivi affiché (la
  campagne, elle, reste reprenable puisque chaque offre est commitée).
* Pas de planificateur récurrent.
* Pagination limitée à ce que chaque API expose ; pas d'orchestrateur de pages multiples.

## Priorités restantes

### P0 — avant usage réel avec vos données

1. Remplacer le CV fictif par vos PDF et vérifier chaque profil (identité, autorisation, salaire).
2. Vérifier les conditions des sites que vous collectez ; n'activer que les sources autorisées.
3. Garder `dry_run = true` et valider manuellement chaque candidature avant de la soumettre.
4. Sauvegarder `data/` (base + CV) ; ne pas exposer l'API sur un réseau public.

### P1 — prochaines améliorations utiles

1. Retry/backoff par connecteur et limites de débit par source.
2. Signal d'embeddings local (bge-m3 / bge-reranker) ajouté au score, avec repli : seule piste
   nettement supérieure au score actuel dans la mesure ([decision-model.md](decision-model.md)).
3. Extraction texte des CV (pypdf) pour des raisons de routage plus riches.
4. Adaptateurs de préremplissage par ATS lorsque leurs conditions l'autorisent ; palier 1 de
   [agent-navigation.md](agent-navigation.md) (suivre le lien « Postuler ») avant tout agent.
5. Test de bout en bout du parcours de validation (préparation → approbation → enregistrement de
   la soumission) : les parcours profil, import d'offres et campagne sont désormais couverts dans
   `tests/test_e2e_ui.py`.

### P2 — qualité et échelle

1. Pagination multi-pages et connecteurs supplémentaires (API publiques uniquement).
2. Amélioration du dédoublonnage (variantes de localisation, entreprises).
3. Filtres avancés et vues sauvegardées dans l'UI.
4. Export PDF/rapport de campagne.
5. PostgreSQL optionnel pour un usage multi-utilisateur.

## Non prévu (choix explicites)

* soumission automatique en masse ;
* contournement de CAPTCHA, de login ou de limites d'accès ;
* scraping de HelloWork/LinkedIn/Indeed/Glassdoor hors connecteur JobSpy opt-in, et de
  WTTJ/Workday dans tous les cas ;
* dépendance obligatoire à un LLM ou à un abonnement payant ;
* réécriture automatique des CV.
