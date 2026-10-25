# Connecteurs, formats et limites

## Principe

Tout connecteur implémente `JobProvider` (`providers/base.py`) :

```python
class JobProvider(Protocol):
    kind: str
    capabilities: ProviderCapabilities
    def fetch(self, query: JobQuery) -> list[NormalizedJob]: ...
```

Ajouter une source = ajouter une classe + l'enregistrer dans `providers/registry.py`, sans toucher
aux campagnes, au scoring ni à l'interface. Les appels sont **séquentiels** ; `collect_jobs` marque
une pause configurable entre connecteurs (`discovery.rate_limit_seconds`). Les connecteurs HTTP
partagent en plus des nouvelles tentatives sur erreur passagère et un intervalle minimal par hôte
(`request_interval_seconds`, `delay_seconds` pour RSS) : voir [discovery.md](discovery.md).

## Connecteurs disponibles

| `kind` | Configuration | Accès | Automatisation de candidature | Notes |
|---|---|---|---|---|
| `fixture` | `path` (facultatif) | Local | Non | 34 annonces fictives, 33 uniques (un doublon volontaire), formulaires `demo://` |
| `json_file` | `path` | Local | Non | Import d'un export/JSON fourni par l'utilisateur |
| `rss` | `feeds`, `company`, `delay_seconds` | Réseau (flux choisis) | Non | Lecture du flux ; conditions du site à vérifier |
| `greenhouse` | `board_token`, `base_url` | API publique en lecture | Non | `boards-api.greenhouse.io`, offres publiées du board |
| `lever` | `company`, `base_url` | API publique en lecture | Non | `api.lever.co/v0/postings/{company}` |
| `manual_url` | `url` | Une page fournie par l'utilisateur | Non | Extraction JSON-LD `JobPosting`, sinon OpenGraph |
| `adzuna` | `app_id`, `app_key` (réglages), `country`, `max_pages` | API officielle en lecture | Non | `api.adzuna.com`, 50 résultats/page ; clé gratuite sur developer.adzuna.com |
| `jobspy` | `sites`, `country`, `max_per_site`, `pause_seconds`, plafonds quotidiens | Job boards (opt-in, extra `boards`) | Non | LinkedIn, Indeed, Glassdoor, HelloWork, Google ; 403/429 arrête le site ; voir [discovery.md](discovery.md) |
| `ats` | `companies` (`ats:identifiant`), `concurrency` | API publiques d'ATS (extra `boards`) | Non | 10 ATS autorisés ; scrapers furtifs refusés |
| `linkedin` | — | — | — | **Désactivé** : logiciels tiers d'automatisation/moissonnage interdits |
| `indeed` | — | — | — | **Désactivé** : Indeed Apply automatisé hors partenaires interdit |
| `welcome_to_the_jungle` | — | — | — | **Désactivé** : pas d'API publique ; import manuel |
| `workday` | — | — | — | **Désactivé** : formulaires propres à chaque tenant ; import manuel |

Les `kind` désactivés existent dans le catalogue (`GET /sources`, `applyflow providers`) avec une
explication, afin d'être explicites plutôt que silencieusement absents.

### Conditions d'utilisation (à vérifier avant usage)

* Adzuna : <https://developer.adzuna.com/docs/terms_of_service>
* LinkedIn : <https://www.linkedin.com/help/linkedin/answer/a1341387/prohibited-software-and-extensions>
* Indeed : <https://www.indeed.com/legal> (section « Applying to Jobs »)
* Greenhouse : <https://www.greenhouse.io/legal>
* Lever : <https://www.lever.co/terms>

ApplyFlow ne contourne ni CAPTCHA, ni protection antibot, ni authentification. Si une page refuse
l'accès (403, contenu non HTML, challenge), le connecteur retourne une erreur explicite. Utilisez
l'import d'URL/JSON à la place.

> Depuis l'ajout du connecteur `jobspy` (opt-in, voir [discovery.md](discovery.md)), ces sites
> peuvent aussi être lus à vos risques. Les voies ci-dessous restent les plus sûres.

## HelloWork, Indeed et les autres : ce qui est possible

HelloWork et Indeed **n'exposent pas d'API publique de recherche** : seule une diffusion d'annonces
via un programme partenaire existe, sur candidature. Les conditions de HelloWork interdisent par
ailleurs l'extraction automatisée de ses pages, y compris sans usage commercial. ApplyFlow ne
propose donc pas de scraper pour ces sites et n'utilise pas de navigateur pour les contourner.

Trois voies conformes permettent malgré tout de chercher de vraies offres françaises :

1. **Adzuna** (intégré) : recherche multi-sources via API officielle, clé gratuite. C'est le
   connecteur à utiliser pour une collecte large automatisée.
2. **Alertes e-mail** : créez une alerte sur HelloWork ou Indeed, recevez les offres dans votre
   boîte (Gmail), puis laissez la synchronisation IMAP d'ApplyFlow lire ces messages. Aucun
   scraping, et les offres sont celles que vous avez explicitement demandées.
3. **Import manuel** : collez l'URL d'une annonce précise (`manual_url`) ou exportez un fichier
   JSON. ApplyFlow en extrait les données structurées et la prépare comme les autres offres.

Pour aller plus loin sur un site précis, la seule voie fiable est de vérifier ses conditions et,
si nécessaire, d'obtenir un accès partenaire écrit.

## Schéma d'import JSON

```json
{
  "jobs": [
    {
      "external_id": "acme-42",
      "url": "https://exemple.invalid/offres/data-analyst-42",
      "apply_url": "https://exemple.invalid/offres/data-analyst-42/postuler",
      "company": "Acme",
      "title": "Data Analyst Junior",
      "description": "SQL, Power BI. Jeune diplômé accepté. Paris, CDI.",
      "location": "Paris, France",
      "remote": "hybrid",
      "contract_type": "CDI",
      "salary_min": 36000,
      "salary_max": 42000,
      "salary_currency": "EUR",
      "published_at": "2026-10-01T09:00:00+00:00",
      "skills": ["SQL", "Power BI"]
    }
  ]
}
```

Seuls `url`, `company` et `title` sont strictement nécessaires. Champs normalisés :

| Champ | Traitement |
|---|---|
| `description` | HTML converti en texte, entités décodées |
| `remote` | `remote` / `hybrid` / `onsite` / `unspecified` ; déduit de la localisation et du texte |
| `contract_type` | `CDI`, `CDD`, `permanent`, `fixed-term`, `internship`, `freelance`, `full-time`… |
| `seniority` | déduit si absent via `matching/seniority.py` |
| `skills` | fournies ou extraites du vocabulaire (`matching/skills.py`) |
| salaire | fourni, sinon heuristique prudente `k€`, `k$` |
| `id` interne | UUID ; `fingerprint` et `url_key` calculés |

Les dates `published_at` acceptent ISO 8601, timestamps (secondes ou millisecondes).

## Dédoublonnage interplateformes

Deux clés sont calculées à l'ingestion :

1. **Empreinte métier** : `sha256(entreprise normalisée | intitulé normalisé | localisation
   normalisée)`. Retire les suffixes juridiques (`SAS`, `Inc`, `GmbH`…), les variantes H/F,
   `(m/f/d)`, la casse et les accents.
2. **URL canonique** : hôte sans `www`, chemin sans slash final, paramètres de tracking supprimés
   (`utm_*`, `ref`, `gh_src`…), paramètres d'identifiant de poste conservés (`gh_jid`, `job_id`…).

Si l'une des deux clés existe déjà, l'annonce est un doublon : aucun nouvel enregistrement, l'offre
existante est liée à la campagne. Les champs manquants (URL de candidature, compétences, salaire)
sont complétés sans écraser l'existant. Le jeu fictif contient volontairement un doublon
« Nova Retail » / « Nova Retail SAS » publié sur deux URLs.

Limites : deux offres réellement distinctes avec le même intitulé, la même entreprise et la même
localisation fusionneront. À l'inverse, une entreprise ou une localisation très différemment
orthographiée peut échapper au dédoublonnage.

## Formulaires de démonstration

Les URLs `demo://` ne contactent aucun site :

| URL | Page locale |
|---|---|
| `demo://simple` | `playground/simple_form.html` (champs standards uniquement) |
| `demo://greenhouse` | `playground/greenhouse_form.html` (questions ouvertes + choix d'autorisation) |
| `demo://lever` | `playground/lever_form.html` (préavis, aménagement) |
| `demo://custom` / `demo://custom-unknown` | `playground/custom_form.html` (sponsoring, date de début) |

Elles servent aux tests et à la campagne de démonstration. Désactiver avec
`app.demo_forms = false`. Les pages réelles passent par `HttpFormFetcher` (HTML uniquement, taille
limitée, pas de JS requis).

## Ce qui n'est pas supporté (volontairement)

* soumission automatique sur les ATS ;
* contournement de CAPTCHA / Cloudflare / login ;
* scraping de WTTJ et Workday ; LinkedIn, Indeed, Glassdoor et HelloWork uniquement via le connecteur JobSpy opt-in (voir [discovery.md](discovery.md)) ;
* exécution de JavaScript pour découvrir des formulaires rendus côté client ;
* pagination automatique au-delà de ce que l'API du board expose.

Pour ces cas, utiliser `manual_url`, `json_file` ou coller les informations dans les profils et la
file de validation.
