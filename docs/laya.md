# Intégration Laya — constat vérifié et adaptateur

> **Correction du 2026-10-24 : cet audit portait sur le mauvais projet.**
> Il existe **deux projets nommés Laya**. Celui audité ci-dessous (`aayushch/laya`) est un centre de
> notifications ; il n'est effectivement pas un routeur de CV. Mais le « Laya » dont parlait le brief
> est un autre projet : le **modèle de décision « System 1 »** de Convai Innovations, open source,
> exécutable en local et compatible avec Jev (dépôts `receptron/laya` et `NandhaKishorM/laya`,
> poids sous Apache-2.0). Il répond à des questions typées (choix, score, oui/non) sur un texte, sans
> générer de texte. Les conclusions « Laya ne fournit pas d'API de routage » ci-dessous ne
> s'appliquent donc **qu'au projet homonyme**. `laya_router.py` vise ce projet-là : il n'est utile à
> rien pour le modèle de décision, qui a depuis été **mesuré puis écarté** (AUC 0,58–0,71 contre 0,85
> pour le score déterministe, sur 40 offres étiquetées). Mesure rejouable et verdict :
> [decision-model.md](decision-model.md).


Vérification effectuée le **2026-10-23** sur <https://github.com/aayushch/laya> (README, docs
d'architecture, contrats d'API, releases, licence).

## Ce que Laya est réellement

Laya est un **centre de commandement de notifications IA local-first** : il connecte Slack, Gmail,
GitHub, Jira, Bitbucket, Notion, Outlook et des calendriers, classe les événements, prépare des
« Action Cards » et attend une approbation humaine avant d'agir.

Faits utiles :

* Licence **Apache-2.0**, application de bureau (releases macOS/Windows/Linux ; le développement
  depuis les sources demande Python 3.10+, Node.js 20+ et Rust).
* Moteur Python FastAPI local sur `127.0.0.1:8420` avec `GET /health` (exempt de jeton) et
  `POST /events` (événements JSON normalisés par n8n), plus une API REST/WebSocket interne.
* Peut utiliser des modèles locaux (Ollama, LM Studio) ou distants (Anthropic, OpenAI, Google,
  LiteLLM) ; l'usage local ne nécessite donc pas d'abonnement payant.
* `pip install laya` installe un **autre** projet PyPI, pas cette application.
* **Aucune API de routage ou de sélection de CV n'est documentée.** Laya n'est pas un produit de
  matching CV/offre, contrairement à l'hypothèse initiale du brief.

Sources : [README](https://github.com/aayushch/laya/blob/main/README.md),
[architecture](https://github.com/aayushch/laya/blob/main/docs/architecture.md),
[contrats API](https://github.com/aayushch/laya/blob/main/docs/api-contracts.md),
[schéma d'événement](https://github.com/aayushch/laya/blob/main/docs/event-schema.md),
[releases](https://github.com/aayushch/laya/releases).

## Décision d'intégration

ApplyFlow **n'invente pas** d'endpoint Laya de routage de CV. Il fournit :

1. `matching/router.py` — interface `ResumeRouter` et routeur déterministe par défaut.
2. `matching/laya_router.py` — `LayaRouter` :
   * vérifie que le moteur Laya répond sur `GET {laya_base_url}/health` (jeton Bearer optionnel) ;
   * délègue le routage à un **adaptateur local** déclaré par l'utilisateur
     (`router.remote_route_url`) qui implémente le contrat ApplyFlow ci-dessous ;
   * sans adaptateur, lève `RouterUnavailable` avec un message explicite.
3. `FallbackRouter` — si Laya/HTTP échoue et que `fallback_to_deterministic = true`, le routeur
   déterministe prend le relais et la décision est marquée `deterministic (fallback: laya)`. La
   campagne continue, aucune offre n'est perdue.

La **confiance** retournée (0–1) mesure la séparation entre profils candidats. Elle ne doit jamais
être affichée comme un score d'adéquation : ce dernier est calculé séparément par
`matching/scoring.py`, entre 0 et 100, avec ses propres raisons et portes d'éligibilité.

## Contrat d'adaptateur `applyflow.route.v1`

Ce contrat est **d'ApplyFlow**, pas de Laya. Un petit service local (FastAPI, script, workflow n8n)
peut le servir et déléguer à Laya si l'utilisateur construit un workflow adapté.

### Requête

`POST {router.remote_route_url}` avec les en-têtes :

```
Content-Type: application/json
X-ApplyFlow-Contract: applyflow.route.v1
```

```json
{
  "contract": "applyflow.route.v1",
  "job": {
    "title": "AI Engineer (Junior)",
    "description": "Python, PyTorch, LLM…",
    "company": "MediMind",
    "location": "Paris, France",
    "remote": "hybrid",
    "contract_type": "CDI",
    "skills": ["Python", "PyTorch", "LLM"]
  },
  "profiles": [
    {
      "id": "profil-1",
      "name": "AI Engineer",
      "target_titles": ["AI Engineer"],
      "technical_skills": ["Python", "PyTorch"],
      "domain_skills": [],
      "experience_level": "junior",
      "years_experience": 2,
      "locations": ["France"],
      "contract_types": ["CDI"],
      "remote_preferences": ["hybrid"],
      "exclusion_criteria": [],
      "resume_id": "cv-1",
      "resume_filename": "cv_ai.pdf"
    }
  ]
}
```

### Réponse attendue (HTTP 200)

```json
{
  "profile_id": "profil-1",
  "resume_id": "cv-1",
  "confidence": 0.72,
  "reasons": ["Intitulé et compétences proches"],
  "uncertain": false
}
```

Règles :

* `profile_id` doit appartenir à la liste envoyée, sinon `RouterUnavailable`.
* `confidence` est bornée à `[0, 1]` ; `reasons` est une liste de chaînes.
* Réseau, HTTP non-2xx, JSON invalide ou champ manquant → `RouterUnavailable` → repli éventuel.
* Aucune donnée n'est envoyée à un service distant : l'URL doit rester locale (`127.0.0.1`).

## Configuration

```toml
[router]
provider = "laya"              # ou "remote" pour un adaptateur sans Laya
fallback_to_deterministic = true
laya_base_url = "http://127.0.0.1:8420"
laya_token = ""                # préférer APPLYFLOW_LAYA_TOKEN
remote_route_url = "http://127.0.0.1:8765/route"
timeout_seconds = 10.0
uncertainty_margin = 0.08
```

`GET /settings` masque le jeton (`***`). Les erreurs de routage sont journalisées en JSON et
visibles dans les décisions de campagne.

## Limites et pistes

* Laya ne fournit pas de sélection de CV native : un adaptateur est **obligatoire** pour un
  routage Laya réel.
* Si vous construisez cet adaptateur, gardez-le local, sans clé cloud, et faites-en un projet
  séparé pour ne pas coupler ApplyFlow à une version de Laya.
* Les appels HTTP n'ont pas de retry automatique (timeout puis repli) ; une campagne peut être
  relancée sans doublon.
* Le routeur déterministe reste la référence testée : compétences, intitulés, niveau, et marge de
  confiance.
