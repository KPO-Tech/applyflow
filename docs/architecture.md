# Décisions techniques (ADR synthétiques)

Date : 2026-10-23. Objectif : une première version utilisable rapidement, fiable, testable,
avec un backend Python et une interface web sans build, sans surarchitecture ni coût d'API.

## 1. Monolithe modulaire plutôt que microservices

**Décision** : un seul paquet `applyflow`, une seule base SQLite, une couche services réutilisée
par la CLI, l'API FastAPI et le site local. Aucun broker, aucune file distribuée, aucun conteneur.

**Pourquoi** : le volume cible (1 000 offres par campagne) et un utilisateur unique ne justifient
pas une architecture distribuée. Le déploiement tient en `uv sync` + une commande.

**Conséquence** : les campagnes s'exécutent dans le processus appelant. L'API locale bloque
pendant une campagne ; pour un usage intensif, lancer la CLI ou un worker dédié plus tard.

## 2. SQLite + SQLAlchemy 2 + Alembic

**Décision** : persistance locale typée, migrations versionnées, `PRAGMA foreign_keys=ON`.

**Pourquoi** : simplicité de sauvegarde (un fichier), transactions fiables, aucune administration.
Les contraintes d'unicité portent des invariants métier, pas seulement la forme :

* `applications.job_id` unique → une offre ne peut pas être enregistrée deux fois ;
* `application_attempts.idempotency_key` unique → reprise sans doublon ;
* `campaign_jobs(campaign_id, job_id)` unique → une offre une seule fois par campagne.

**Conséquence** : SQLite sérialise les écritures. Pour un serveur multi-utilisateur, migrer vers
PostgreSQL ; le code SQLAlchemy reste compatible hors quelques spécificités de type.

## 3. Le routeur de CV est indépendant du score d'adéquation

**Décision** : `ResumeRouter` choisit un profil/CV et retourne une **confiance** ; le moteur de
scoring retourne un **score 0–100** et des raisons d'éligibilité. Les deux objets sont séparés en
base (`routing_decisions` vs champs de `campaign_jobs`).

**Pourquoi** : éviter de présenter la confiance du modèle de routage comme une probabilité de
recrutement. Une confiance de 0,8 signifie « le choix entre profils est net », pas « le candidat a
80 % de chances d'être pris ».

**Routeur par défaut** : déterministe (intitulés + compétences + alignement de niveau), donc
explicable, hors ligne, sans modèle ni coût. Un adaptateur Laya/HTTP optionnel peut le remplacer
avec repli automatique.

## 4. Portes d'éligibilité séparées du score

**Décision** : localisation, contrat, autorisation de travail, critères d'exclusion et niveaux
interdits (lead/principal/staff/head/director) rendent une offre **inéligible**, même si son score
est élevé. Un « 3 ans » explicitement obligatoire n'est pas une porte : il pénalise le score et
l'expérience. La distinction obligatoire/souhaité est extraite de la phrase.

**Pourquoi** : un score élevé sur une offre inaccessible produit des candidatures absurdes ; à
l'inverse, exclure automatiquement toute mention d'années ferait perdre des offres entry-level
réalistes.

## 5. Dry-run et validation humaine par construction

**Décision** : mode `dry_run` par défaut, `allow_submit = false`, aucun code ne clique sur un
bouton d'envoi. La séquence est : préparation → revue → approbation (`approved`) → soumission
humaine → `record_submission` (confirmation explicite).

**Pourquoi** : impossibilité de soumettre une candidature par accident, même si un sélecteur
Playwright est mal interprété. Le remplissage Playwright est une commande séparée réservée aux
candidatures approuvées.

**Conséquence** : le « taux de soumission automatique » est nul par choix ; ApplyFlow automatise
la collecte, l'analyse et la préparation, pas l'envoi.

## 6. Campagnes idempotentes et reprenables

**Décision** : machine à états persistée par offre (`discovered` → `analyzed`/`rejected` →
`prepared`/`needs_review`/`blocked`/`duplicate`), commit après chaque offre, pause lue en base à
chaque itération, aucune concurrence.

**Pourquoi** : une interruption (arrêt du process, erreur réseau) ne doit ni perdre le travail ni
dupliquer une candidature. Chaque étape ne traite que les offres à l'état précédent, donc la
relancer est sûr.

**Conséquence** : le débit dépend du nombre de commits. Mesure locale : 1 000 offres collectées et
analysées en 12,7 s ; la préparation est plus lente car elle analyse un formulaire par offre.

## 7. Collecte séquentielle et limites respectées

**Décision** : `collect_jobs` parcourt les sources une par une, avec une pause configurable entre
connecteurs ; le connecteur RSS applique aussi une pause entre flux. Pas de parallélisme.

**Pourquoi** : éviter de contourner les limites de débit des plateformes et rendre les erreurs
attribuables. Un connecteur en échec n'interrompt pas les autres.

## 8. Site web natif + API FastAPI sur la même couche services

**Décision** : FastAPI sert l'API et les assets du site (`index.html`, CSS, modules JS natifs).
L'interface consomme les mêmes services que la CLI ; aucune règle métier n'est dupliquée côté
client. Le routage est porté par le hash (`#/dashboard`, `#/campagnes`), ce qui évite un serveur
SPA et conserve des URLs partageables.

**Pourquoi** : un site réellement designé et réactif sans toolchain Node, sans build et sans
dépendance front. Les modules ES permettent de garder chaque écran isolé et testable via ses
routes ; le CSS est un design system à tokens (clair/sombre, espacements, états).

**Conséquence** : pas de rendu serveur ni de temps réel ; l'interface et l'API doivent tourner sur
la même origine pour partager la base SQLite. Une version React/TypeScript pourra remplacer les
modules si l'interface gagne beaucoup en complexité.

## 9. Aucun LLM requis

**Décision** : scoring lexical déterministe, vocabulaire de compétences explicite, séniorité par
règles contextuelles. Laya/HTTP est optionnel et local.

**Pourquoi** : pas d'abonnement, pas de coût par candidature, résultats reproductibles et
auditables. Les réponses de formulaire proviennent uniquement du profil ou de la bibliothèque
validée, jamais d'une génération.

**Conséquence** : moins de compréhension sémantique qu'un grand modèle ; le routeur marque les
choix incertains et l'utilisateur garde la main.

## Flux de données

```
Provider.fetch() ──► NormalizedJob ──► dédoublonnage ──► Job
                                                   │
Campaign(sources, profils, filtres, max_jobs) ─────┘
        │
        ├── discover : collecte + liens campaign_jobs (stage=discovered)
        ├── analyze  : router.route() + score_job() → routing_decisions + campaign_jobs
        └── prepare  : fetch HTML → analyse → plan → application_attempts (dry-run)
                                   │
                     revue humaine / réponses validées
                                   │
                     approve_attempt() → applications (status=prepared)
                                   │
              soumission humaine → record_submission() → submitted (unique par offre)
```
