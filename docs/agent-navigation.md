# Agent de navigation : spécification et limites

Dernière mise à jour : 2026-10-24. Ce document décrit **ce qui n'est pas encore construit** :
il fixe le découpage, les garde-fous et les critères d'acceptation avant d'écrire le code.

## Décision

L'automatisation progresse en **trois paliers indépendants**, dans cet ordre. Chacun se mesure
avant d'ouvrir le suivant, et chacun reste utilisable seul :

1. **Suivre la candidature** — déterministe, sans modèle de langage.
2. **Session persistante** — un navigateur dédié où vous vous connectez à la main, une fois.
3. **Agent borné** — un modèle de langage qui pilote ce navigateur pour les seuls parcours que
   les deux paliers précédents n'atteignent pas.

Aucun palier n'autorise l'envoi d'une candidature sans validation explicite.

## Ce que la mesure a établi

Le 2026-10-24, `make measure-render` a comparé, sur les 21 candidatures en attente, la lecture
du HTML servi et la lecture de la page rendue par un navigateur (`application.render_forms`,
déjà en place).

| Résultat | Nombre |
|---|---|
| Lisibles sans navigateur | 2 |
| **Lisibles uniquement grâce au rendu** | **0** |
| Inutilisables | 19 |

Le rendu fonctionne (un test le prouve sur une page montée en JavaScript), mais il ne débloque
rien ici, parce que le formulaire de candidature **n'est pas sur la page de l'offre**. Causes
relevées, DOM inspecté :

| Cause | Offres |
|---|---|
| Page de candidature distincte, derrière « Postuler » (Teamtailor ×2, Jobvite, Workday, Hardis) | 5 |
| Connexion ou compte requis (HelloWork ×6, EasyApply, ABG) | 8 |
| Porte e-mail avant le formulaire (EY) | 1 |
| Aucun formulaire applicatif sur la page (Free-Work ×2, Spendesk, JobAffinity) | 4 |
| Certificat TLS invalide côté site (HeadMind) | 1 |
| **Total inutilisable** | **19** |

Conclusion : le prochain gain n'est ni la lecture, ni l'intelligence — c'est la **navigation**
vers la bonne page.

## Palier 1 — suivre la candidature

**Ce qui est construit** : `BrowserFormFetcher` (`src/applyflow/applications/fetcher.py`) et son
repli dans `prepare_attempt` quand le HTML servi ne contient aucun champ.

**Ce qui reste** : quand la page rendue n'a toujours aucun formulaire, chercher la destination de
la candidature et la relire.

Règles :

* **un seul saut**, jamais de chaîne ;
* cibles prises dans les liens et boutons de la page rendue, dont le texte correspond à
  `postuler`, `candidater`, `apply`, `je postule`, `déposer ma candidature`, ou dont l'adresse
  suit un motif connu (`/applications/new`, `/apply`, `open-positions?p=job/`) ;
* **même domaine enregistrable** que la page d'origine, sinon abandon ;
* aucune page de connexion, aucun formulaire contenant un champ mot de passe ;
* le saut est enregistré dans l'audit (`attempt.followed_url`) et signalé dans le plan, pour que
  la file affiche d'où vient le formulaire lu.

**Critère d'acceptation** : `make measure-render` montre au moins les 5 offres de la première
ligne du tableau ci-dessus passant de « aucun champ » à « lisible », sans régression sur les 2
déjà lisibles, et `pytest` reste vert.

## Palier 2 — session persistante

Aujourd'hui le navigateur est jetable (`playwright.chromium.launch`) : aucune connexion ne
survit. Le palier 2 introduit un profil persistant (`launch_persistent_context`).

* **Répertoire** : `data/browser/profile/`, créé au premier lancement, jamais exporté par
  `export`, jamais inclus dans un partage.
* **Connexion** : une action de l'interface (« Ouvrir le navigateur de session ») ouvre une
  fenêtre visible ; vous vous connectez vous-même, avec votre mot de passe et votre double
  authentification. ApplyFlow ne voit ni ne stocke aucun identifiant.
* **Extinction** : bouton « Fermer la session et effacer le profil » qui supprime le répertoire.
* **Détection** : avant d'utiliser la session, vérifier qu'une page protégée s'ouvre sans
  redirection vers la connexion ; sinon, rendre la main avec un message clair.

**Critère d'acceptation** : la session survit à un redémarrage de l'application ; deux sites
différents sont reconnus comme connectés ; après effacement, le premier accès redemande la
connexion.

## Palier 3 — agent borné

Un modèle de langage reçoit une page et une intention (« atteindre le formulaire de candidature
et le remplir avec les valeurs du plan »), et agit par une **surface d'outils fermée** :

| Outil | Effet |
|---|---|
| `open(url)` | navigation, domaine en liste blanche uniquement |
| `read()` | DOM textuel de la page courante |
| `screenshot()` | capture archivée avec l'étape |
| `click(selector)` | un clic, jamais deux fois le même |
| `type(selector, text)` | saisie, valeur issue du plan ou d'une réponse validée |
| `select(selector, option)` | choix dans une liste |

Ce qu'il ne peut pas faire, par construction et non par consigne :

* saisir un identifiant, un mot de passe, un code de vérification ou une donnée de paiement ;
* résoudre un CAPTCHA, contourner un mur de connexion ou créer un compte ;
* envoyer un e-mail, accepter une newsletter, modifier un profil sur un site tiers ;
* cliquer sur un bouton d'envoi : l'outil `submit` n'existe pas dans la surface. La soumission
  reste l'action humaine décrite dans `docs/status.md`.

Bornes d'exécution : une offre à la fois, délai maximal par offre, budget de N candidatures par
jour, arrêt immédiat sur CAPTCHA, mur de connexion ou domaine hors liste. Chaque étape est
journalisée (outil, sélecteur, valeur, capture) et rejouable à la lecture.

**Contenu rédigé** : un texte libre (lettre, « pourquoi nous ») ne peut citer que des faits du
profil ou de la bibliothèque de réponses validées. Il est marqué « à relire » et reste modifiable
avant tout envoi ; il n'est jamais présenté comme écrit par vous.

**Injection de consigne** : le texte d'une page est une donnée, jamais une instruction. Une page
qui contient « ignore tes règles » ou « envoie ton CV à cette adresse » doit être traitée comme
hostile : l'agent ignore, journalise et s'arrête.

## Données et confidentialité

| Élément | Traitement |
|---|---|
| Cookies de session | `data/browser/profile/`, hors exports, effaçables d'un clic |
| Captures d'écran | `data/agent/`, liées à une offre, supprimées avec elle |
| Journal des étapes | table dédiée, lisible dans l'interface, sans secret |
| Contenu envoyé au modèle | DOM de la page courante et plan de remplissage ; jamais les cookies, jamais un fichier du trousseau |

L'API reste locale et protégée par le contrôle d'hôte existant. Aucun port distant n'est ouvert.

## Ce qui n'est pas prévu

* postuler en masse sans relecture ;
* franchir un CAPTCHA ou une protection antibot ;
* créer des comptes sur les job boards ;
* stocker des identifiants de sites tiers ;
* utiliser l'agent pour lire vos e-mails ou vos comptes professionnels.

## Séquence de livraison

| Étape | Livrable | Mesure |
|---|---|---|
| 1 | Suivre le lien de candidature | 5 offres débloquées, 0 régression |
| 2 | Session persistante | survit au redémarrage, 2 sites |
| 3 | Agent sur une seule famille d'ATS (Teamtailor) | taux de formulaire correct, temps par candidature |
| 4 | Généralisation | seulement si l'étape 3 tient ses chiffres |

L'étape 3 est volontairement limitée à une famille d'ATS : si l'agent échoue là où la structure
est régulière, il échouera partout, et il vaut mieux le savoir sur deux offres que sur cinquante.
