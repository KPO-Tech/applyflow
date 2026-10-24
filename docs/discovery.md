# Collecte étendue : JobSpy

Dépôt de référence : <https://github.com/speedyapply/JobSpy> (MIT, v1.4.1, commit
`a606f9cf077c34f6ce6cbfcc76238f57b3c20671`). Utilisé comme **bibliothèque**, sans copie de code.

## Activation

```bash
uv sync --extra boards
```

Dans `applyflow.toml` : `[boards] jobspy_enabled = true`. Un réglage de campagne ne peut pas
l'activer à votre place.

## Ce que fait ApplyFlow

* Requêtes **séquentielles** avec pause (`pause_seconds`), volume plafonné (`max_per_site`).
* Un site qui répond 403/429 est abandonné pour la collecte en cours ; si tous bloquent, la
  source échoue avec un message clair. Aucun contournement de CAPTCHA ou de connexion.
* Statistiques par site (`JobSpyProvider.last_stats` : offres, erreurs, durée).
* Les valeurs absentes ne sont pas inventées (ex. entreprise « non communiquée »).

## Avertissement

LinkedIn, Indeed, Glassdoor et HelloWork encadrent ou interdisent l'automatisation. JobSpy
imite l'empreinte TLS d'un navigateur pour être accepté ; c'est une zone grise vis-à-vis de leurs
conditions. Usage personnel, faible volume, à vos risques : blocage d'IP ou de compte possible.

## Test réel du 2026-10-23 (10 offres/site, « Data Engineer junior », France)

| Site | Offres | Descriptions > 200 car. | Erreurs |
|---|---|---|---|
| Indeed | 10 | 10 | 0 |
| HelloWork | 7 | 7 | 0 |
| LinkedIn | 10 | 10 | 0 |
| Glassdoor | 10 | 10 | 0 |

Limites connues : environ 1 000 offres max par recherche et par site ; LinkedIn est le plus lent
(~1 s/offre avec description) et le plus sujet aux 429.

---

# ATS publics : ats-scrapers

Dépôt de référence : <https://github.com/kalil0321/ats-scrapers> (MIT, v0.3.0, commit
`6b44a1badc9bfbf5cf176f75265cc5729e520e99`), utilisé comme bibliothèque (extra `boards`).

Connecteur `ats` : [ats_provider.py](../src/applyflow/providers/ats_provider.py). Exemple de source
de campagne :

```json
{"kind": "ats", "config": {"companies": ["greenhouse:datadog", "lever:qonto", "ashby:alan"],
                            "concurrency": 4}}
```

* ATS autorisés : greenhouse, lever, ashby, smartrecruiters, workday, successfactors, workable,
  recruitee, personio, teamtailor (API publiques répondant à un client HTTP ordinaire). Les
  scrapers d'ats-scrapers qui exigent une usurpation TLS ou un navigateur furtif sont refusés.
* Une entreprise = un appel qui renvoie **toutes** ses offres ; ApplyFlow filtre ensuite par
  mots-clés et localisation. Concurrence bornée (`concurrency`, 16 max), retries/backoff gérés
  par la bibliothèque. Une entreprise en échec n'arrête pas les autres.
* `search()` de la bibliothèque (jeu de données hébergé) n'est **pas utilisé** : mesuré à 575 s
  pour 1 résultat.
* Les listes d'entreprises par ATS sont dans `private/references/ats-scrapers/ats-companies/*.csv`
  (colonnes `name,slug,url`).

## Test réel du 2026-10-23 (12 entreprises, mots-clés data/ML/AI, France ou Paris)

12 entreprises en 23,5 s, **238 offres retenues, 100 % avec description complète**.
Datadog 47/437, Doctolib 56/156, Alan 55/130, Mirakl 26/28, Back Market 17/33, Algolia 16/32,
Qonto 10/33, BlaBlaCar 7/7, Dataiku 4/13. Échecs : `lever:ledger` (introuvable : la liste CSV
est périmée), `lever:mistral` (0 offre, probablement un autre ATS aujourd'hui). Toujours vérifier
un slug avant de le garder.

---

# Plafond quotidien par site

Pour protéger votre adresse IP, chaque site JobSpy a un **plafond d'offres collectées par jour**,
mémorisé entre les lancements dans `data/collection_usage.json` (remis à zéro chaque jour, fuseau
local, 30 jours d'historique).

| Site | Plafond par défaut |
|---|---|
| LinkedIn | 75 |
| Indeed | 200 |
| Glassdoor | 150 |
| HelloWork | 150 |
| Google | 100 |

* Réglage : `[boards.daily_limits]` dans `applyflow.toml` (`0` = pas de plafond pour ce site).
  Un réglage de campagne ne peut pas le contourner.
* Chaque requête est réduite au budget restant ; un site épuisé est ignoré (message dans les
  statistiques) et, si tous les sites choisis sont épuisés, la collecte est refusée **sans
  aucune requête**.
* Ces valeurs sont des points de départ prudents, pas des limites officielles (les sites n'en
  publient pas). Montez progressivement tant qu'aucun 429 n'apparaît ; en cas de blocage,
  baissez.
* Les ATS publics (connecteur `ats`) n'ont pas de plafond : un appel renvoie toutes les offres
  d'une entreprise.

# Pays des offres

Chaque offre a un champ `country` (code ISO 3166-1 : `FR`, `GB`, `DE`…), indexé pour filtrer.

* Ordre de détection : pays fourni par la source (Adzuna, ATS), sinon pays écrit dans la
  localisation (« Paris, Île-de-France, France »), sinon ville connue (« Berlin »), sinon pays de
  la recherche (indice faible). Sinon `unknown` : on ne devine pas.
* Un pays écrit prime sur une ville : « Paris, Texas, United States » vaut `US`.
* API : `GET /jobs?country=FR`, `GET /jobs?country=fr,gb`, `GET /jobs?country=unknown` et
  `GET /jobs/countries` (nombre d'offres par pays).
* Les offres déjà en base reçoivent leur pays à la migration ; `applyflow rebuild-dedupe` rattrape
  celles ajoutées depuis.
* Limite : un seul pays par offre (le premier cité pour les offres multi-pays) ; les villes
  inconnues de la liste restent `unknown` si la localisation n'écrit pas le pays.

---

# Dans l'interface (écran Découverte)

* **Sources « Job boards » et « ATS »** : cases à cocher pour les sites JobSpy, liste
  `ats:identifiant` pour les ATS (validée avant l'envoi).
* **Activation explicite de JobSpy** : la source reste désactivée tant que vous n'avez pas cliqué
  sur « Je comprends, activer » et confirmé l'avertissement. Le réglage `[boards] jobspy_enabled`
  est alors enregistré.
* **Plafonds quotidiens** : une barre par site (utilisé / plafond), mise à jour après chaque
  collecte. API : `GET /collection/usage`.
* **Statistiques après collecte** : offres, durée et erreur par site ou par entreprise
  (`stats` dans la réponse de `POST /discovery`).
* **Pays** : filtre « Tous les pays » avec le nombre d'offres par pays, et le pays dans la colonne
  Lieu du tableau.
* Les plafonds, la pause et l'activation de JobSpy se modifient dans **Réglages → Collecte**
  (formulaire « Job boards »). L'activation demande une confirmation.

# Collecte en arrière-plan

`POST /discovery/start` lance la collecte dans un thread et rend `202` avec un identifiant ;
l'écran suit l'avancement. L'ancien `POST /discovery` (synchrone) reste disponible.

* `GET /discovery/tasks/{id}` : état (`running`, `done`, `cancelled`, `error`), progression
  (`done`/`total`/`label`/`collected`) et résultat avec statistiques.
* `GET /discovery/tasks/active` : collecte en cours (l'écran la reprend si vous revenez dessus).
* `POST /discovery/tasks/{id}/cancel` : annulation. Elle prend effet entre deux requêtes ; les
  offres déjà trouvées sont **enregistrées**. Elle interrompt aussi les pauses.
* **Une seule collecte à la fois** (`409` sinon) : lancer plusieurs recherches en parallèle
  multiplierait les requêtes vers les mêmes sites.
* Limite : une requête JobSpy en cours (jusqu'à `max_per_site` offres avec descriptions) ne peut
  pas être coupée au milieu ; l'annulation attend sa fin. Les tâches sont gardées en mémoire
  (20 dernières) et disparaissent au redémarrage du serveur.
* Performance ATS : les offres sont d'abord filtrées sur la localisation, puis seulement
  normalisées (la normalisation coûte ~20 ms par offre).
