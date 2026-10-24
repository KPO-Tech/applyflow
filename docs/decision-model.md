# Modèle de décision (Laya, Jev) : mesure et décision

Dernière mise à jour : 2026-10-24. Les chiffres de la colonne « ApplyFlow courant » sont
recalculés par le dépôt ; les autres viennent d'une campagne de mesure enregistrée le
même jour et ne sont pas rejouées (voir « Limites »).

## Décision

**Laya n'est pas intégré.** Sur le jeu d'offres étiquetées, le modèle de décision classe
moins bien que le score déterministe déjà en place : AUC de 0,58 à 0,71 contre 0,85. Un
second modèle (embeddings bge-m3) obtient de bien meilleurs résultats, ce qui déplace la
piste utile sans justifier Laya.

Cette décision est **révisable** : le jeu ne contient que 3 offres « ok », ce qui suffit à
écarter un modèle nettement moins bon, pas à départager deux modèles proches.

## Le jeu de données (`data/etiquetage/`)

| Fichier | Contenu |
|---|---|
| `selection.json` | 40 offres (identifiant, titre, entreprise, localisation, contrat, description, URL) |
| `etiquettes-claude.json` | étiquettes ok / maybe / no, profil visé, note de justification, critères |
| `comparaison.csv` | scores enregistrés de chaque approche le 2026-10-24 |
| `etiquetage.html` | page locale d'étiquetage manuel (hors application) |
| `profils.json` | noms des profils concernés |

Ces fichiers vivent hors du paquet et de la base : ce sont des données de mesure, pas des
données d'application. Le script est en lecture seule et n'écrit dans aucun d'eux.

## Comment mesurer

```bash
uv run python scripts/eval_matching.py          # tableau Markdown
uv run python scripts/eval_matching.py --json   # mêmes chiffres, exploitables
```

Le script lit `data/etiquetage/selection.json` (offres) et ses étiquettes
(`etiquettes.json` ou `etiquettes-<nom>.json`), puis :

1. recalcule le score ApplyFlow avec le **code courant**, les profils actifs de la base et
   la configuration locale — routeur puis `score_job`, comme l'analyse de campagne ;
2. classe une offre non éligible à -1, puisqu'elle sort de la file de validation ;
3. affiche à côté les colonnes enregistrées de `comparaison.csv` (Laya, embeddings) en les
   marquant « enregistré » ;
4. calcule pour chaque approche l'AUC (ok contre no), la composition du top-k et le rang
   moyen des offres « ok ».

Aucune écriture en base, aucun appel réseau.

## Résultats (40 offres : 3 ok, 12 maybe, 25 no)

| Approche | AUC (ok/no) | top 10 (ok / maybe / no) | rang moyen des ok |
|---|---|---|---|
| **ApplyFlow courant** (recalculé) | **0,847** | 1 / 5 / 4 | 11,3 |
| score ApplyFlow (enregistré) | 0,907 | 3 / 2 / 5 | 5,0 |
| bge-m3 : similarité profil/offre (enregistré) | 0,987 | 3 / 5 / 2 | 3,3 |
| bge-reranker : pertinence (enregistré) | 0,947 | 3 / 4 / 3 | 5,3 |
| règles ApplyFlow + bge-reranker (enregistré) | 0,947 | 3 / 4 / 3 | 5,3 |
| règles ApplyFlow + Laya (enregistré) | 0,707 | 1 / 4 / 5 | 13,7 |
| Laya : métier × pas senior (enregistré) | 0,667 | 1 / 4 / 5 | 14,7 |
| Laya : métier seul (enregistré) | 0,580 | 0 / 5 / 5 | 20,3 |

## Lecture

* **Laya ne bat aucune approche déjà disponible**, y compris sa combinaison avec les règles
  ApplyFlow (0,707), qui reste sous le score seul (0,847).
* Les deux lignes ApplyFlow diffèrent (0,847 contre 0,907) : la colonne enregistrée date
  d'un état antérieur des profils et du scoring ; 32 offres sur 40 y diffèrent de plus d'un
  point. La conclusion ne change pas — Laya reste loin derrière dans les deux cas —
  mais c'est bien la ligne recalculée qui décrit le comportement actuel.
* **La piste utile est ailleurs** : les embeddings (bge-m3, puis bge-reranker) séparent
  nettement mieux les offres. C'est cohérent avec le constat de départ : le score
  reconnaît des mots de vos compétences sans assez vérifier le métier. Un modèle de
  similarité le fait mieux qu'un modèle de décision à questions fermées.
* L'échantillon reste minuscule : 3 offres « ok ».

## Ce qui reste déterministe

Contrat, années exigées, localisation, autorisation de travail, niveau : ces règles ne
dépendent ni de Laya ni d'un embedding. Elles sont explicables, testables, et touchent à
votre situation de séjour. Un score de similarité ne doit pas les remplacer — au mieux
déplacer une offre dans la file, jamais franchir une porte.

## Limites de la mesure

* 40 offres, dont 3 « ok » : l'AUC a une marge d'erreur large (de l'ordre de ±0,1).
* Les étiquettes viennent d'une seule personne (Claude, pas Stéphane) avec des critères
  explicites ; elles ne sont pas un jugement humain indépendant.
* Les lignes « enregistré » (Laya, embeddings) ne sont pas rejouées par le script : les
  relancer exigerait leurs dépendances (poids locaux, modèles). Elles servent de trace.
* Le jeu est celui de vos trois profils actuels ; un quatrième profil changerait le routage.
* `selection.json` contient des titres tronqués ou dupliqués (deux « AI Engineer H/F »,
  trois « Engineer H/F »). Le script associe les lignes enregistrées par titre puis par
  préfixe puis par ordre ; il n'y a pas d'identifiant dans `comparaison.csv`. Ajouter une
  colonne `id` au CSV rendrait l'appariement trivial.

## Où le modèle de décision aiderait (hypothèse non validée)

Deux usages restent plausibles, mais aucun n'est démontré par cette mesure :

* **Questions inconnues d'un formulaire** : choisir parmi vos réponses validées, avec
  l'option « aucune » ; jamais inventer une réponse. Le besoin est réel (`needs_review`),
  la mesure ci-dessus ne le couvre pas.
* **Pertinence métier** : questions oui/non (« ce poste est-il un poste d'ingénieur data
  ou IA ? »). C'est justement là que Laya déçoit face à un embedding.

## Si on y revient

1. Porter le jeu à une quarantaine d'offres « ok » (300 à 400 offres étiquetées).
2. Étiqueter à deux, au moins sur un sous-ensemble, pour mesurer l'accord inter-annotateurs.
3. Ajouter une colonne `id` à `comparaison.csv`.
4. Tester les embeddings en local (`bge-m3`, `bge-reranker`) comme signal **ajouté** au
   score, avec repli si le modèle est absent — le mécanisme `FallbackRouter` existe déjà.
5. Ne réintégrer un modèle de décision que s'il bat le score seul **et** le score + embedding.
