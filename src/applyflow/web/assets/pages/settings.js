import { api } from "../api.js";
import { icon } from "../icons.js";
import { store } from "../store.js";
import { locationPickerHtml, mountLocationPickers, readLocations } from "../locations.js";
import {
  confirmDialog,
  emptyState,
  errorMessage,
  esc,
  fieldError,
  clearFieldError,
  num,
  relativeDay,
  setLoading,
  splitList,
  toast,
} from "../ui.js";

const SECTIONS = [
  {
    id: "matching",
    label: "Matching",
    icon: "target",
    desc: "Seuils, pondérations, séniorité",
    title: "Seuils et pondérations",
    intro:
      "Comment une offre devient prioritaire. Chaque score est calculé localement, composante par composante.",
  },
  {
    id: "routeur",
    label: "Routeur",
    icon: "spark",
    desc: "Moteur local, Laya, HTTP",
    title: "Routeur de candidatures",
    intro:
      "Le moteur qui associe chaque offre à un profil. Déterministe par défaut, explicable et sans dépendance réseau.",
  },
  {
    id: "collecte",
    label: "Collecte",
    icon: "discovery",
    desc: "Rythme, délais, connecteurs",
    title: "Collecte des offres",
    intro: "Le rythme des requêtes sortantes et les sources disponibles pour alimenter vos campagnes.",
  },
  {
    id: "email",
    label: "Boîte mail",
    icon: "mail",
    desc: "Gmail, synchronisation, relances",
    title: "Boîte mail",
    intro:
      "Branchez votre boîte Gmail en lecture seule pour retrouver les réponses et préparer vos relances. Aucun message n'est envoyé automatiquement.",
  },
  {
    id: "envoi",
    label: "Garde-fous",
    icon: "lock",
    desc: "Dry-run et limites",
    title: "Garde-fous d'envoi",
    intro:
      "ApplyFlow prépare, explique et trace. Aucune candidature ne quitte votre machine sans une validation humaine.",
  },
  {
    id: "reponses",
    label: "Réponses",
    icon: "file",
    desc: "Bibliothèque validée",
    title: "Bibliothèque de réponses",
    intro:
      "Les réponses que vous avez validées servent à compléter les questions récurrentes. Elles ne sont jamais inventées.",
  },
  {
    id: "donnees",
    label: "Données",
    icon: "database",
    desc: "Chemins et stockage local",
    title: "Données locales",
    intro: "Où vivent votre configuration, votre base et vos fichiers. Aucune télémétrie, aucun service cloud.",
  },
];

const WEIGHTS = [
  ["skills", "Compétences"],
  ["titles", "Intitulés"],
  ["seniority", "Séniorité"],
  ["experience", "Expérience"],
  ["location", "Localisation"],
  ["contract", "Contrat"],
  ["obligations", "Obligations"],
];

const PROVIDER_LABELS = {
  deterministic: "Déterministe (local)",
  laya: "Laya (local)",
  remote: "HTTP distant",
};

function thresholdVisual(high, medium, minApply) {
  return `<div class="threshold-visual" aria-hidden="true">
    <span class="threshold-zone low" style="left:0;width:${minApply}%"></span>
    <span class="threshold-zone mid" style="left:${minApply}%;width:${Math.max(0, medium - minApply)}%"></span>
    <span class="threshold-zone high" style="left:${medium}%;width:${Math.max(0, high - medium)}%"></span>
    <span class="threshold-marker" style="left:${medium}%"></span>
    <span class="threshold-marker" style="left:${high}%"></span>
    <span class="threshold-labels"><span>Faible</span><span>Moyen</span><span>Prioritaire</span></span>
  </div>`;
}

function answerRows(answers) {
  if (!answers.length) {
    return emptyState({
      iconName: "file",
      title: "Aucune réponse enregistrée",
      text: "Ajoutez les réponses que vous utilisez souvent ; elles resteront à portée de main.",
      small: true,
    });
  }
  return `<div class="answer-list">${answers
    .map(
      (answer) => `<div class="answer-row">
        <div class="answer-question">${esc(answer.question_text)}</div>
        <div class="answer-value">${esc(answer.answer)}</div>
        <div class="answer-meta"><span>${answer.approved ? "Validée" : "À relire"}</span><span>·</span><span>${num(answer.times_used)} utilisation${answer.times_used > 1 ? "s" : ""}</span></div>
      </div>`,
    )
    .join("")}</div>`;
}

function panelHead(title, text) {
  return `<div class="settings-section-head">
    <div><h3>${esc(title)}</h3><p>${esc(text)}</p></div>
  </div>`;
}

function saveRow(note = "Écrit dans votre fichier de configuration local.") {
  return `<div class="settings-actions">
    <button class="btn btn--primary" type="submit">${icon("checkCircle")} Enregistrer</button>
    <span class="settings-note">${esc(note)}</span>
  </div>`;
}

function matchingSection(settings) {
  const thresholds = settings.scoring?.thresholds || { high: 80, medium: 65, min_apply: 65 };
  const weights = settings.scoring?.weights || {};
  return `<form class="panel settings-panel" id="settings-form" data-settings="matching" novalidate>
    <div class="settings-section">
      ${panelHead("Seuils de matching", "Le seuil prioritaire remonte les offres en tête. Le minimum de préparation conditionne l'analyse.")}
      ${thresholdVisual(Number(thresholds.high), Number(thresholds.medium), Number(thresholds.min_apply))}
      <div class="form-grid form-grid--three">
        <div class="field">
          <label for="threshold-high">Priorité haute</label>
          <input class="input" id="threshold-high" name="high" type="number" min="0" max="100" value="${esc(thresholds.high)}" />
        </div>
        <div class="field">
          <label for="threshold-medium">Priorité moyenne</label>
          <input class="input" id="threshold-medium" name="medium" type="number" min="0" max="100" value="${esc(thresholds.medium)}" />
        </div>
        <div class="field">
          <label for="threshold-apply">Minimum de préparation</label>
          <input class="input" id="threshold-apply" name="min_apply" type="number" min="0" max="100" value="${esc(thresholds.min_apply)}" />
        </div>
      </div>
    </div>

    <div class="settings-section">
      ${panelHead("Pondérations", "Les poids sont normalisés : seules leurs proportions comptent. Total affiché en pourcentage du score.")}
      <div class="form-grid form-grid--four">
        ${WEIGHTS.map(
          ([key, label]) => `<div class="field">
            <label for="weight-${key}">${esc(label)}</label>
            <input class="input" id="weight-${key}" name="weight_${key}" type="number" min="1" max="100" step="1" value="${esc(weights[key] ?? 10)}" />
            <span class="hint">${esc(String(weights[key] ?? 10))} pts</span>
          </div>`,
        ).join("")}
      </div>
      <p class="hint weights-total" id="weights-total">Répartition normalisée automatiquement.</p>
    </div>

    <div class="settings-section">
      ${panelHead("Séniorité", "Les intitulés exclus sont écartés, les pénalisés sont seulement minorés. Les années obligatoires au-delà du plafond font sortir l'offre.")}
      <div class="form-grid">
        <div class="field">
          <label for="excluded-seniority">Niveaux exclus</label>
          <input class="input" id="excluded-seniority" name="excluded_seniority" value="${esc((settings.scoring?.excluded_seniority || []).join(", "))}" placeholder="lead, principal, staff" />
        </div>
        <div class="field">
          <label for="penalized-seniority">Niveaux pénalisés</label>
          <input class="input" id="penalized-seniority" name="penalized_seniority" value="${esc((settings.scoring?.penalized_seniority || []).join(", "))}" placeholder="senior" />
        </div>
        <div class="field">
          <label for="max-required-years">Années obligatoires maximum</label>
          <input class="input" id="max-required-years" name="max_required_years" type="number" min="0" max="30" step="0.5" value="${esc(settings.scoring?.max_required_years ?? 5)}" />
        </div>
      </div>
    </div>

    ${saveRow()}
  </form>`;
}

function routerSection(settings) {
  const router = settings.router || {};
  return `<form class="panel settings-panel" data-settings="router" novalidate>
    <div class="settings-section">
      ${panelHead("Moteur de routage", "Le mode déterministe fonctionne hors ligne. Un moteur distant ou Laya reste optionnel, avec repli automatique.")}
      <div class="form-grid">
        <div class="field">
          <label for="router-provider">Moteur</label>
          <select class="select" id="router-provider" name="provider">
            ${["deterministic", "laya", "remote"]
              .map(
                (provider) =>
                  `<option value="${provider}" ${router.provider === provider ? "selected" : ""}>${PROVIDER_LABELS[provider]}</option>`,
              )
              .join("")}
          </select>
        </div>
        <div class="field">
          <label for="router-laya">URL du moteur Laya</label>
          <input class="input" id="router-laya" name="laya_base_url" value="${esc(router.laya_base_url || "")}" placeholder="http://127.0.0.1:8420" />
          <span class="hint">Le jeton n'est jamais affiché. Fournissez-le via <span class="mono">APPLYFLOW_LAYA_TOKEN</span>.</span>
        </div>
        <div class="field">
          <label for="router-remote">Endpoint de routage <span class="opt">facultatif</span></label>
          <input class="input" id="router-remote" name="remote_route_url" value="${esc(router.remote_route_url || "")}" placeholder="http://127.0.0.1:8420/route" />
        </div>
        <div class="field">
          <label for="router-timeout">Timeout (secondes)</label>
          <input class="input" id="router-timeout" name="timeout_seconds" type="number" min="1" max="120" step="0.5" value="${esc(router.timeout_seconds ?? 10)}" />
        </div>
        <div class="field">
          <label for="router-margin">Marge d'incertitude</label>
          <input class="input" id="router-margin" name="uncertainty_margin" type="number" min="0" max="0.5" step="0.01" value="${esc(router.uncertainty_margin ?? 0.08)}" />
          <span class="hint">Sous cette marge, la décision est signalée comme incertaine.</span>
        </div>
      </div>
      <label class="check" style="min-height:36px;margin-top:12px">
        <input type="checkbox" name="fallback_to_deterministic" ${router.fallback_to_deterministic !== false ? "checked" : ""} />
        Revenir au routeur déterministe si le moteur configuré échoue
      </label>
    </div>
    ${saveRow("Un redémarrage du serveur applique un changement de moteur.")}
  </form>`;
}

const BOARD_SITES = [
  ["linkedin", "LinkedIn", "Détecte les rafales plus vite que les autres : gardez ce plafond bas."],
  ["indeed", "Indeed", ""],
  ["glassdoor", "Glassdoor", "Limite connue d'environ 2 requêtes par seconde."],
  ["hellowork", "HelloWork", ""],
  ["google", "Google Jobs", ""],
];

function boardsForm(settings) {
  const boards = settings.boards || {};
  const limits = boards.daily_limits || {};
  return `<form class="panel settings-panel" data-settings="boards" novalidate>
    <div class="settings-section">
      ${panelHead("Job boards — LinkedIn, Indeed, Glassdoor, HelloWork", "Lecture des pages publiques via JobSpy. Ces sites encadrent ou interdisent l'automatisation : usage personnel, volume faible, à vos risques (blocage de votre adresse IP possible). Aucun CAPTCHA n'est contourné.")}
      <label class="check" style="min-height:36px">
        <input type="checkbox" name="jobspy_enabled" data-was-enabled="${boards.jobspy_enabled ? "true" : "false"}" ${boards.jobspy_enabled ? "checked" : ""} />
        Activer la collecte sur les job boards
      </label>
      <p class="hint" style="margin-top:6px">Désactivé par défaut. L'activation demande une confirmation. Nécessite <span class="mono">uv sync --extra boards</span>.</p>
      <div class="field" style="margin-top:12px">
        <label>Sites cochés par défaut dans Découverte</label>
        <div class="site-picks">
          ${BOARD_SITES.map(
            ([site, label]) => `<label><input type="checkbox" name="boards_site" value="${site}" ${(boards.sites || []).includes(site) ? "checked" : ""} /> ${esc(label)}</label>`,
          ).join("")}
        </div>
        <span class="hint">LinkedIn n'est pas coché au départ : c'est le site qui détecte le plus vite les rafales.</span>
      </div>
      <div class="form-grid" style="margin-top:12px">
        <div class="field">
          <label for="boards-pause">Pause entre deux requêtes (secondes)</label>
          <input class="input" id="boards-pause" name="pause_seconds" type="number" min="0" max="120" step="0.5" value="${esc(boards.pause_seconds ?? 5)}" />
          <span class="hint">Plus la pause est longue, moins le risque de blocage est élevé.</span>
        </div>
        <div class="field">
          <label for="boards-max">Offres maximum par site et par collecte</label>
          <input class="input" id="boards-max" name="max_per_site" type="number" min="1" max="1000" value="${esc(boards.max_per_site ?? 100)}" />
        </div>
      </div>
    </div>
    <div class="settings-section">
      ${panelHead("Plafond quotidien par site", "Nombre maximal d'offres collectées par jour et par site, mémorisé entre les lancements. 0 = aucun plafond pour ce site. Ce sont des points de départ prudents, pas des limites officielles : montez petit à petit tant qu'aucun blocage n'apparaît.")}
      <div class="form-grid">
        ${BOARD_SITES.map(
          ([site, label, hint]) => `<div class="field">
            <label for="limit-${site}">${esc(label)}</label>
            <input class="input" id="limit-${site}" name="limit_${site}" type="number" min="0" max="5000" value="${esc(limits[site] ?? 0)}" />
            ${hint ? `<span class="hint">${esc(hint)}</span>` : ""}
          </div>`,
        ).join("")}
      </div>
    </div>
    ${saveRow("Les plafonds s'appliquent dès la prochaine collecte.")}
  </form>`;
}

function searchForm(settings) {
  const search = settings.search || {};
  return `<form class="panel settings-panel" data-settings="search" novalidate>
    <div class="settings-section">
      ${panelHead("Recherche par défaut", "Ce qui est prérempli dans l'écran Découverte : vous n'avez plus à tout retaper à chaque collecte. Vous pouvez toujours modifier la recherche avant de la lancer.")}
      <div class="form-grid">
        <div class="field">
          <label for="search-keywords">Mots-clés <span class="opt">un par ligne</span></label>
          <textarea class="textarea" id="search-keywords" name="search_keywords" rows="5">${esc((search.keywords || []).join("\n"))}</textarea>
          <span class="hint">Une recherche par mot-clé : plus il y en a, plus la collecte est longue.</span>
        </div>
        <div class="field">
          <label for="search-ats">Entreprises ATS <span class="opt">une par ligne : ats:identifiant</span></label>
          <textarea class="textarea" id="search-ats" name="search_ats" rows="5">${esc((search.ats_companies || []).join("\n"))}</textarea>
          <span class="hint">Pages carrières publiques (greenhouse, lever, ashby…). Un identifiant peut changer : un échec n'arrête pas les autres entreprises.</span>
        </div>
        <div class="field">
          <label for="search-locations">Pays et villes</label>
          ${locationPickerHtml({ id: "search-locations", values: search.locations || [] })}
          <span class="hint">Plusieurs pays possibles, pris dans la liste officielle. Un pays retrouve aussi les offres situées dans ses villes.</span>
        </div>
        <div class="field">
          <label for="search-limit">Offres maximum par collecte</label>
          <input class="input" id="search-limit" name="search_limit" type="number" min="1" max="5000" value="${esc(search.limit ?? 100)}" />
        </div>
      </div>
    </div>
    ${saveRow("Utilisé comme point de départ dans Découverte.")}
  </form>`;
}

function collecteSection(settings) {
  const discovery = settings.discovery || {};
  const adzuna = settings.adzuna || {};
  const hasKey = adzuna.app_key === "***";
  return `<div class="stack">
    ${searchForm(settings)}

    <form class="panel settings-panel" data-settings="discovery" novalidate>
      <div class="settings-section">
        ${panelHead("Rythme des requêtes", "Les collectes sont séquentielles, avec une pause entre chaque source pour rester courtois.")}
        <div class="form-grid">
          <div class="field">
            <label for="discovery-rate">Pause entre requêtes (secondes)</label>
            <input class="input" id="discovery-rate" name="rate_limit_seconds" type="number" min="0" max="30" step="0.5" value="${esc(discovery.rate_limit_seconds ?? 1)}" />
          </div>
          <div class="field">
            <label for="discovery-retry">Tentatives par requête</label>
            <input class="input" id="discovery-retry" name="retry_attempts" type="number" min="1" max="10" value="${esc(discovery.retry_attempts ?? 3)}" />
            <span class="hint">Erreur passagère seulement (timeout, 429, 5xx), avec un délai croissant.</span>
          </div>
          <div class="field">
            <label for="discovery-timeout">Timeout (secondes)</label>
            <input class="input" id="discovery-timeout" name="timeout_seconds" type="number" min="1" max="120" value="${esc(discovery.timeout_seconds ?? 20)}" />
          </div>
          <div class="field">
            <label for="discovery-max">Plafond par défaut</label>
            <input class="input" id="discovery-max" name="max_jobs_default" type="number" min="1" max="5000" value="${esc(discovery.max_jobs_default ?? 1000)}" />
            <span class="hint">Les campagnes portent leur propre plafond.</span>
          </div>
          <div class="field">
            <label for="discovery-agent">User-Agent</label>
            <input class="input" id="discovery-agent" name="user_agent" value="${esc(discovery.user_agent || "")}" />
          </div>
        </div>
      </div>

      <div class="settings-section">
        ${panelHead("Adzuna — API officielle", "Des offres réelles, en France, via une API documentée plutôt qu'une extraction de page. La clé est gratuite et personnelle.")}
        <div class="form-grid">
          <div class="field">
            <label for="adzuna-app-id">app_id</label>
            <input class="input" id="adzuna-app-id" name="adzuna_app_id" autocomplete="off" value="${esc(adzuna.app_id || "")}" />
          </div>
          <div class="field">
            <label for="adzuna-app-key">app_key</label>
            <input class="input" id="adzuna-app-key" name="adzuna_app_key" type="password" autocomplete="off" value="" placeholder="${hasKey ? "clé enregistrée · laisser vide pour conserver" : "votre clé Adzuna"}" data-has-key="${hasKey}" />
          </div>
          <div class="field">
            <label for="adzuna-country">Pays</label>
            <input class="input" id="adzuna-country" name="adzuna_country" value="${esc(adzuna.country || "fr")}" />
            <span class="hint">Code pays Adzuna : fr, gb, us…</span>
          </div>
          <div class="field">
            <label for="adzuna-pages">Pages maximales</label>
            <input class="input" id="adzuna-pages" name="adzuna_max_pages" type="number" min="1" max="20" value="${esc(adzuna.max_pages ?? 5)}" />
            <span class="hint">50 résultats par page au maximum.</span>
          </div>
        </div>
        <div class="toolbar" style="margin-top:12px">
          <button class="btn btn--secondary btn--sm" type="button" data-test-adzuna>${icon("spark")} Tester la connexion</button>
          <a class="link-btn" href="https://developer.adzuna.com/signup" target="_blank" rel="noreferrer noopener">Obtenir une clé gratuite ${icon("external")}</a>
        </div>
        <div id="adzuna-test-result" class="small muted" role="status" style="margin-top:8px"></div>
      </div>
      ${saveRow()}
    </form>

    ${boardsForm(settings)}
  </div>`;
}

function emailPrefs(settings) {
  const email = settings.email || {};
  return `<form class="panel settings-panel" data-settings="email" novalidate>
    <div class="settings-section">
      ${panelHead("Lecture et relances", "La fenêtre de lecture limite les messages examinés. Le délai de relance décide quand une candidature sans réponse apparaît dans la file.")}
      <div class="form-grid">
        <div class="field">
          <label for="email-lookback">Fenêtre de lecture (jours)</label>
          <input class="input" id="email-lookback" name="lookback_days" type="number" min="1" max="365" value="${esc(email.lookback_days ?? 45)}" />
          <span class="hint">Les messages antérieurs ne sont pas relus.</span>
        </div>
        <div class="field">
          <label for="email-relance">Relancer après (jours)</label>
          <input class="input" id="email-relance" name="relance_days" type="number" min="1" max="90" value="${esc(email.relance_days ?? 10)}" />
          <span class="hint">Sans réponse ni relance déjà envoyée.</span>
        </div>
      </div>
      <p class="hint" style="margin-top:10px">Ces réglages ne contiennent aucun identifiant.</p>
    </div>
    ${saveRow("Aucun redémarrage nécessaire.")}
  </form>`;
}

function emailSection(settings, status) {
  if (!status?.connected) {
    return `<div class="stack">
      <section class="panel settings-panel">
        <div class="settings-section">
          <div class="settings-section-head">
            <div><h3>Gmail en lecture seule</h3><p>ApplyFlow lit les messages reçus via IMAP. Il ne peut ni envoyer, ni supprimer, ni marquer vos messages comme lus.</p></div>
            <span class="chip chip--plain">Non connecté</span>
          </div>
          <ol class="setup-steps">
            <li><span class="step-index">1</span><div><strong>Activez la validation en deux étapes</strong><p>Sur votre compte Google, dans Sécurité. Le mot de passe d'application n'est proposé qu'une fois cette étape faite.</p></div></li>
            <li><span class="step-index">2</span><div><strong>Créez un mot de passe d'application</strong><p><a class="link-inline" href="https://myaccount.google.com/apppasswords" target="_blank" rel="noreferrer noopener">myaccount.google.com/apppasswords ${icon("external")}</a> — nommez-le « ApplyFlow ». Copiez les 16 caractères.</p></div></li>
            <li><span class="step-index">3</span><div><strong>Collez-le ici</strong><p>Il est conservé localement dans <span class="mono">data/secrets/gmail.json</span>, jamais dans le fichier de configuration ni dans un export.</p></div></li>
          </ol>
          <form id="email-connect" novalidate>
            <div class="form-grid">
              <div class="field">
                <label for="gmail-address">Adresse Gmail</label>
                <input class="input" id="gmail-address" name="address" type="email" autocomplete="username" placeholder="vous@gmail.com" value="${esc(status?.last_address || settings.email?.address || "")}" required />
              </div>
              <div class="field">
                <label for="gmail-password">Mot de passe d'application</label>
                <input class="input" id="gmail-password" name="password" type="password" autocomplete="off" placeholder="xxxx xxxx xxxx xxxx" required />
                <span class="hint">16 caractères, espaces acceptés.</span>
              </div>
            </div>
            <div class="safety-note" style="margin-top:14px">
              ${icon("lock")}
              <div><strong>Votre mot de passe ne quitte pas cet appareil.</strong><p>La connexion est testée immédiatement, puis stockée hors du TOML. Vous pouvez la révoquer à tout moment depuis votre compte Google.</p></div>
            </div>
            <div class="mail-actions">
              <button class="btn btn--primary" type="submit">${icon("checkCircle")} Tester et connecter</button>
              <span class="hint">Une boîte Workspace peut bloquer IMAP : demandez à votre administrateur.</span>
            </div>
          </form>
        </div>
      </section>
      ${emailPrefs(settings)}
    </div>`;
  }

  const last = status.last_sync_at ? relativeDay(status.last_sync_at) : "jamais";
  return `<div class="stack">
    <section class="panel settings-panel">
      <div class="settings-section">
        <div class="settings-section-head">
          <div><h3>Gmail</h3><p>Lecture seule via IMAP : les messages restent non lus dans votre boîte.</p></div>
          <span class="chip chip--sage"><span class="status-dot"></span>Connecté</span>
        </div>
        <div class="mail-account">
          <div class="mail-account-main">
            <span class="mail-account-icon">${icon("mail")}</span>
            <div><strong>${esc(status.address)}</strong><small>${esc(status.imap_host)} · dossier ${esc(settings.email?.folder || "INBOX")}</small></div>
          </div>
          <div class="mail-account-stats">
            <div><strong>${num(status.messages)}</strong><span>messages</span></div>
            <div><strong>${num(status.awaiting)}</strong><span>à traiter</span></div>
            <div><strong>${num(status.followups)}</strong><span>relances</span></div>
          </div>
        </div>
        <div class="mail-actions">
          <button class="btn btn--primary" type="button" data-mail="sync">${icon("refresh")} Synchroniser</button>
          <button class="btn btn--secondary" type="button" data-mail="test">${icon("checkCircle")} Vérifier la connexion</button>
          <button class="btn btn--ghost" type="button" data-mail="disconnect">Déconnecter</button>
          <span class="settings-note">Dernière synchronisation : ${esc(last)}</span>
        </div>
      </div>
    </section>
    ${emailPrefs(settings)}
    <section class="panel settings-panel">
      <div class="settings-section">
        <div class="settings-section-head">
          <div><h3>Suivi et relances</h3><p>Les réponses classées et les relances à préparer vivent dans une page dédiée.</p></div>
        </div>
        <a class="link-btn" href="#/emails">Ouvrir le suivi e-mail ${icon("arrowRight")}</a>
      </div>
    </section>
  </div>`;
}

function envoiSection(settings) {
  const application = settings.application || {};
  return `<form class="panel settings-panel" data-settings="application" novalidate>
    <div class="settings-section">
      ${panelHead("Mode d'exécution", "Le dry-run prépare les candidatures sans rien envoyer. Même en live, la soumission reste une action humaine.")}
      <label class="check" style="min-height:36px">
        <input type="checkbox" name="dry_run" ${application.dry_run !== false ? "checked" : ""} />
        Rester en dry-run
      </label>
      <p class="hint" style="margin-top:6px">Recommandé. La validation et l'enregistrement d'une soumission restent toujours des actions humaines.</p>
      <label class="check" style="min-height:36px;margin-top:10px">
        <input type="checkbox" name="headless" ${application.headless !== false ? "checked" : ""} />
        Navigateur sans fenêtre pour le préremplissage
      </label>
      <div class="safety-note" style="margin-top:14px">
        ${icon("lock")}
        <div><strong>Soumission automatique verrouillée.</strong><p>Aucun chemin de code ne clique sur « Envoyer ». La confirmation manuelle reste obligatoire.</p></div>
      </div>
    </div>
    <div class="settings-section">
      ${panelHead("Limites de fichiers", "Vos CV et les formulaires importés restent dans le répertoire de données.")}
      <div class="form-grid">
        <div class="field">
          <label for="max-resume">Taille maximale d'un CV (Mo)</label>
          <input class="input" id="max-resume" name="max_resume_mb" type="number" min="1" max="50" value="${esc(application.max_resume_mb ?? 5)}" />
        </div>
        <div class="field">
          <label for="max-form">Taille maximale d'un formulaire (octets)</label>
          <input class="input" id="max-form" name="max_form_bytes" type="number" min="1000" max="10000000" step="1000" value="${esc(application.max_form_bytes ?? 2000000)}" />
        </div>
      </div>
    </div>
    ${saveRow()}
  </form>`;
}

function reponsesSection(answers) {
  return `<section class="panel settings-panel">
    <div class="settings-section">
      <div class="settings-section-head">
        <div><h3>Réponses enregistrées</h3><p>Elles complètent les questions récurrentes des formulaires, jamais inventées par l'outil.</p></div>
        <span class="chip chip--tag">${answers.length}</span>
      </div>
      ${answerRows(answers)}
      <form id="answer-form" class="answer-form" novalidate>
        <div class="form-grid">
          <div class="field span-2">
            <label for="answer-question">Question</label>
            <input class="input" id="answer-question" name="question_text" placeholder="Ex. Êtes-vous autorisé à travailler en France ?" required />
          </div>
          <div class="field span-2">
            <label for="answer-value">Réponse validée</label>
            <textarea class="textarea" id="answer-value" name="answer" placeholder="Oui, titulaire d'un titre de séjour…" required></textarea>
          </div>
        </div>
        <button class="btn btn--secondary btn--sm" type="submit">${icon("plus")} Ajouter une réponse</button>
      </form>
    </div>
  </section>`;
}

function donneesSection(settings) {
  const dataDir = settings.app?.data_dir || "data/";
  const configPath = settings.config_path || "applyflow.toml (créé à l'enregistrement)";
  return `<div class="stack">
    <section class="panel settings-panel">
      <div class="settings-section">
        <div class="settings-section-head">
          <div><h3>Emplacements</h3><p>Tout est stocké sur cet appareil, dans des formats lisibles.</p></div>
          <span class="chip chip--sage">100 % local</span>
        </div>
        <div class="data-list">
          <div class="data-row"><span>Configuration</span><span class="mono">${esc(configPath)}</span></div>
          <div class="data-row"><span>Données</span><span class="mono">${esc(dataDir)}</span></div>
          <div class="data-row"><span>Base</span><span class="mono">${esc(settings.app?.db_url || "SQLite locale")}</span></div>
          <div class="data-row"><span>Version</span><span>${esc(store.health?.version || "0.1.0")}</span></div>
          <div class="data-row"><span>Offres suivies</span><span>${num(store.health?.jobs || 0)}</span></div>
        </div>
      </div>
    </section>

    <section class="panel settings-panel">
      <div class="panel-body">
        <div class="safety-note">${icon("lock")}<div><strong>Vos fichiers restent chez vous.</strong><p>Les CV, la base et les exports vivent dans le répertoire de données. Aucun contenu n'est envoyé à un service tiers.</p></div></div>
        <div class="eyebrow" style="color:var(--muted);margin-top:18px">À propos</div>
        <h2 class="panel-title" style="margin-top:6px;font-family:var(--font-display);font-size:21px;font-weight:500">ApplyFlow, sans boîte noire.</h2>
        <p class="small muted" style="margin-top:5px">Chaque score est motivé, chaque décision est journalisée, chaque envoi reste entre vos mains. C'est le principe de l'outil.</p>
        <a class="link-btn" style="margin-top:11px" href="#/dashboard">Retour au tableau de bord ${icon("arrowRight")}</a>
      </div>
    </section>
  </div>`;
}

export async function render(container, ctx) {
  const active =
    SECTIONS.find((section) => section.id === ctx.section) || SECTIONS[0];
  const [settings, answers, mail] = await Promise.all([
    api.settings(ctx.signal),
    active.id === "reponses" ? api.answers(ctx.signal) : Promise.resolve([]),
    active.id === "email" ? api.emailStatus(ctx.signal) : Promise.resolve(null),
  ]);
  if (ctx.signal.aborted) return;

  store.settings = settings;
  if (!ctx.section) history.replaceState(null, "", `#/reglages/${active.id}`);
  document.title = `Réglages · ${active.label} · ApplyFlow`;
  const crumb = document.getElementById("current-section");
  if (crumb) crumb.textContent = `Réglages · ${active.label}`;

  let body = "";
  if (active.id === "matching") body = matchingSection(settings);
  else if (active.id === "routeur") body = routerSection(settings);
  else if (active.id === "collecte") body = collecteSection(settings);
  else if (active.id === "email") body = emailSection(settings, mail);
  else if (active.id === "envoi") body = envoiSection(settings);
  else if (active.id === "reponses") body = reponsesSection(answers);
  else body = donneesSection(settings);

  container.innerHTML = `
    <header class="page-head">
      <div>
        <div class="eyebrow">Configuration</div>
        <h1 class="page-title">Réglages</h1>
        <p class="page-sub">${esc(active.intro)}</p>
      </div>
      <div class="head-actions">
        <a class="btn btn--ghost" href="#/reglages/donnees">${icon("database")} Données locales</a>
      </div>
    </header>

    <div class="settings-shell">
      <nav class="settings-nav" aria-label="Sections de configuration">
        <div class="settings-nav-title">Sections</div>
        ${SECTIONS.map(
          (section) => `<a class="settings-nav-item ${section.id === active.id ? "is-active" : ""}" href="#/reglages/${section.id}" ${
            section.id === active.id ? 'aria-current="page"' : ""
          }>
            <span class="settings-nav-icon">${icon(section.icon)}</span>
            <span class="settings-nav-text"><strong>${esc(section.label)}</strong><small>${esc(section.desc)}</small></span>
            ${icon("chevronRight", "settings-nav-arrow")}
          </a>`,
        ).join("")}
      </nav>
      <div class="settings-body">
        <div class="settings-body-head">
          <h2>${esc(active.title)}</h2>
        </div>
        ${body}
      </div>
    </div>`;

  mountLocationPickers(container);
  // Une section peut contenir plusieurs formulaires (ex. Collecte : rythme + job boards).
  for (const form of container.querySelectorAll("[data-settings]")) {
    form.addEventListener("input", () => {
      if (form.dataset.settings !== "matching") return;
      const visual = form.querySelector(".threshold-visual");
      const high = Number(form.elements.high?.value) || 0;
      const medium = Number(form.elements.medium?.value) || 0;
      const minApply = Number(form.elements.min_apply?.value) || 0;
      if (visual) visual.outerHTML = thresholdVisual(high, medium, minApply);
      const total = WEIGHTS.reduce((sum, [key]) => sum + (Number(form.elements[`weight_${key}`]?.value) || 0), 0);
      const totalBox = form.querySelector("#weights-total");
      if (totalBox) {
        totalBox.textContent = total
          ? `Répartition normalisée : ${WEIGHTS.map(([key, label]) => `${label} ${Math.round(((Number(form.elements[`weight_${key}`]?.value) || 0) / total) * 100)} %`).join(" · ")}`
          : "Renseignez au moins une pondération.";
      }
    });

    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      clearFieldError(form);
      const save = form.querySelector("button[type=submit]");
      let payload;
      let problem = "";

      if (form.dataset.settings === "matching") {
        const high = Number(form.elements.high.value);
        const medium = Number(form.elements.medium.value);
        const minApply = Number(form.elements.min_apply.value);
        const weights = Object.fromEntries(
          WEIGHTS.map(([key]) => [key, Number(form.elements[`weight_${key}`].value)]),
        );
        if (!(high > medium && medium >= minApply)) {
          problem = "Les seuils doivent respecter : priorité haute > priorité moyenne ≥ minimum de préparation.";
        } else if (Object.values(weights).some((value) => !(value > 0))) {
          problem = "Chaque pondération doit être strictement positive.";
        } else {
          payload = {
            scoring: {
              thresholds: { high, medium, min_apply: minApply },
              weights,
              excluded_seniority: [...new Set(String(form.elements.excluded_seniority.value || "").split(",").map((item) => item.trim().toLowerCase()).filter(Boolean))],
              penalized_seniority: [...new Set(String(form.elements.penalized_seniority.value || "").split(",").map((item) => item.trim().toLowerCase()).filter(Boolean))],
              max_required_years: Number(form.elements.max_required_years.value) || 0,
            },
          };
        }
      } else if (form.dataset.settings === "router") {
        const timeout = Number(form.elements.timeout_seconds.value);
        const margin = Number(form.elements.uncertainty_margin.value);
        if (!(timeout > 0)) problem = "Le timeout doit être supérieur à zéro.";
        else if (!(margin >= 0 && margin <= 0.5)) problem = "La marge d'incertitude doit être comprise entre 0 et 0,5.";
        else
          payload = {
            router: {
              provider: form.elements.provider.value,
              fallback_to_deterministic: form.elements.fallback_to_deterministic.checked,
              laya_base_url: String(form.elements.laya_base_url.value || "").trim(),
              remote_route_url: String(form.elements.remote_route_url.value || "").trim(),
              timeout_seconds: timeout,
              uncertainty_margin: margin,
            },
          };
      } else if (form.dataset.settings === "discovery") {
        const rate = Number(form.elements.rate_limit_seconds.value);
        const retries = Number(form.elements.retry_attempts.value);
        const timeout = Number(form.elements.timeout_seconds.value);
        const maxJobs = Number(form.elements.max_jobs_default.value);
        const adzunaId = String(form.elements.adzuna_app_id.value || "").trim();
        const adzunaKeyInput = String(form.elements.adzuna_app_key.value || "").trim();
        const adzunaKey = adzunaKeyInput || (form.elements.adzuna_app_key.dataset.hasKey === "true" ? "***" : "");
        const adzunaPages = Number(form.elements.adzuna_max_pages.value);
        const adzunaCountry = String(form.elements.adzuna_country.value || "fr").trim().toLowerCase();
        if (!(rate >= 0)) problem = "La pause entre requêtes ne peut pas être négative.";
        else if (!(Number.isInteger(retries) && retries >= 1 && retries <= 10))
          problem = "Les tentatives se comptent entre 1 et 10.";
        else if (!(timeout > 0)) problem = "Le timeout doit être supérieur à zéro.";
        else if (!(maxJobs > 0)) problem = "Le plafond doit être supérieur à zéro.";
        else if (Boolean(adzunaId) !== Boolean(adzunaKey)) {
          problem = "Renseignez app_id et app_key ensemble, ou laissez les deux vides.";
        } else if (!(adzunaPages >= 1 && adzunaPages <= 20)) {
          problem = "Adzuna accepte entre 1 et 20 pages.";
        } else if (!adzunaCountry) {
          problem = "Indiquez un code pays Adzuna (par exemple fr).";
        } else
          payload = {
            discovery: {
              rate_limit_seconds: rate,
              retry_attempts: retries,
              timeout_seconds: timeout,
              max_jobs_default: maxJobs,
              user_agent: String(form.elements.user_agent.value || "").trim(),
            },
            adzuna: {
              app_id: adzunaId,
              app_key: adzunaKey,
              country: adzunaCountry,
              max_pages: adzunaPages,
            },
          };
      } else if (form.dataset.settings === "search") {
        const keywords = splitList(form.elements.search_keywords.value);
        const locationCheck = readLocations(form.querySelector("[data-loc-picker]"));
        const locations = locationCheck.values;
        const atsCompanies = splitList(form.elements.search_ats.value);
        const limit = Number(form.elements.search_limit.value);
        if (locationCheck.error) {
          problem = locationCheck.error;
        } else if (!(Number.isInteger(limit) && limit >= 1 && limit <= 5000)) {
          problem = "Le maximum d'offres doit être un entier entre 1 et 5 000.";
        } else if (atsCompanies.some((entry) => !/^[a-z]+:\S+$/i.test(entry))) {
          problem = "Format des entreprises ATS : ats:identifiant, une par ligne (ex. lever:qonto).";
        } else {
          payload = { search: { keywords, locations, limit, ats_companies: atsCompanies } };
        }
      } else if (form.dataset.settings === "boards") {
        const sites = [...form.querySelectorAll("input[name=boards_site]:checked")].map((box) => box.value);
        const pause = Number(form.elements.pause_seconds.value);
        const maxPerSite = Number(form.elements.max_per_site.value);
        const limits = {};
        let badLimit = "";
        for (const [site, label] of BOARD_SITES) {
          const value = Number(form.elements[`limit_${site}`].value);
          if (!Number.isInteger(value) || value < 0 || value > 5000) badLimit = label;
          limits[site] = value;
        }
        const enabling =
          form.elements.jobspy_enabled.checked && form.elements.jobspy_enabled.dataset.wasEnabled !== "true";
        if (!sites.length) problem = "Cochez au moins un site par défaut.";
        else if (!(pause >= 0 && pause <= 120)) problem = "La pause doit être comprise entre 0 et 120 secondes.";
        else if (!(Number.isInteger(maxPerSite) && maxPerSite >= 1 && maxPerSite <= 1000)) {
          problem = "Le maximum par site doit être un entier entre 1 et 1 000.";
        } else if (badLimit) problem = `Plafond invalide pour ${badLimit} : entier entre 0 et 5 000.`;
        else {
          if (enabling) {
            const confirmed = await confirmDialog({
              title: "Activer la collecte sur les job boards ?",
              message:
                "LinkedIn, Indeed, Glassdoor et HelloWork encadrent ou interdisent l'automatisation dans leurs conditions. L'usage reste personnel, à faible volume et à vos risques : votre adresse IP peut être bloquée. ApplyFlow limite le débit, applique un plafond quotidien, s'arrête sur un blocage et ne contourne aucun CAPTCHA.",
              confirmLabel: "J'ai compris, activer",
            });
            if (!confirmed) {
              form.elements.jobspy_enabled.checked = false;
              return;
            }
          }
          payload = {
            boards: {
              jobspy_enabled: form.elements.jobspy_enabled.checked,
              sites,
              pause_seconds: pause,
              max_per_site: maxPerSite,
              daily_limits: limits,
            },
          };
        }
      } else if (form.dataset.settings === "email") {
        const lookback = Number(form.elements.lookback_days.value);
        const relance = Number(form.elements.relance_days.value);
        if (!(lookback >= 1 && lookback <= 365)) {
          problem = "La fenêtre de lecture doit être comprise entre 1 et 365 jours.";
        } else if (!(relance >= 1 && relance <= 90)) {
          problem = "Le délai de relance doit être compris entre 1 et 90 jours.";
        } else {
          payload = { email: { lookback_days: lookback, relance_days: relance } };
        }
      } else if (form.dataset.settings === "application") {
        const maxResume = Number(form.elements.max_resume_mb.value);
        const maxForm = Number(form.elements.max_form_bytes.value);
        if (!(maxResume >= 1)) problem = "La taille maximale d'un CV doit être d'au moins 1 Mo.";
        else if (!(maxForm >= 1000)) problem = "La taille maximale d'un formulaire doit être d'au moins 1 000 octets.";
        else
          payload = {
            application: {
              dry_run: form.elements.dry_run.checked,
              headless: form.elements.headless.checked,
              max_resume_mb: maxResume,
              max_form_bytes: maxForm,
            },
          };
      }

      if (problem) {
        fieldError(form, problem);
        toast(problem, { title: "Réglages non enregistrés", type: "warn" });
        return;
      }

      setLoading(save, true, "Enregistrement…");
      try {
        const result = await api.saveSettings(payload);
        if (form.dataset.settings === "boards") {
          form.elements.jobspy_enabled.dataset.wasEnabled = String(form.elements.jobspy_enabled.checked);
        }
        store.settings = await api.settings();
        window.dispatchEvent(new CustomEvent("applyflow:settings"));
        toast(
          result.restart_required
            ? "Réglages enregistrés. Un redémarrage du serveur applique les changements de moteur."
            : "Réglages enregistrés.",
          { title: "Configuration à jour" },
        );
      } catch (error) {
        toast(errorMessage(error), { title: "Enregistrement impossible", type: "error" });
      } finally {
        setLoading(save, false);
      }
    });
  }

  const adzunaTest = container.querySelector("[data-test-adzuna]");
  if (adzunaTest) {
    adzunaTest.addEventListener("click", async () => {
      const adzunaForm = adzunaTest.closest("form");
      const keyField = adzunaForm.elements.adzuna_app_key;
      const storedKey = keyField.dataset.hasKey === "true";
      const box = container.querySelector("#adzuna-test-result");
      setLoading(adzunaTest, true, "Test…");
      box.textContent = "Connexion à l'API Adzuna…";
      try {
        const result = await api.testAdzuna({
          app_id: String(adzunaForm.elements.adzuna_app_id.value || "").trim(),
          app_key: String(keyField.value || "").trim() || (storedKey ? "***" : ""),
          country: String(adzunaForm.elements.adzuna_country.value || "fr").trim(),
          keywords: ["data engineer"],
        });
        const sample = (result.sample || [])
          .map((item) => `${item.title} — ${item.company}${item.location ? ` (${item.location})` : ""}`)
          .join(" · ");
        box.innerHTML = `<span class="chip chip--sage">${icon("checkCircle")} Connexion réussie</span>
          <span style="margin-left:6px">${num(result.total)} offre${result.total > 1 ? "s" : ""} pour « data engineer ».</span>
          ${sample ? `<div style="margin-top:6px">${esc(sample)}</div>` : ""}`;
        toast("Adzuna répond : la clé est valide et la recherche fonctionne.", {
          title: "API Adzuna accessible",
        });
      } catch (error) {
        box.innerHTML = `<span class="chip chip--plain">${icon("alert")} Échec</span>
          <span style="margin-left:6px">${esc(errorMessage(error))}</span>`;
        toast(errorMessage(error), { title: "Test Adzuna impossible", type: "error" });
      } finally {
        setLoading(adzunaTest, false);
      }
    });
  }

  const answerForm = container.querySelector("#answer-form");
  if (answerForm) {
    answerForm.addEventListener("submit", async (event) => {
      event.preventDefault();
      clearFieldError(answerForm);
      const question = String(answerForm.elements.question_text.value || "").trim();
      const answer = String(answerForm.elements.answer.value || "").trim();
      if (!question || !answer) {
        fieldError(answerForm, "La question et la réponse sont obligatoires.");
        return;
      }
      const button = answerForm.querySelector("button[type=submit]");
      setLoading(button, true, "Ajout…");
      try {
        await api.saveAnswer({ question_text: question, answer, approved: true, kind: "text" });
        toast("Réponse ajoutée à la bibliothèque.", { title: "Réponse enregistrée" });
        ctx.refresh();
      } catch (error) {
        setLoading(button, false);
        fieldError(answerForm, errorMessage(error));
      }
    });
  }

  const connectForm = container.querySelector("#email-connect");
  if (connectForm) {
    connectForm.addEventListener("submit", async (event) => {
      event.preventDefault();
      clearFieldError(connectForm);
      const address = String(connectForm.elements.address.value || "").trim();
      const password = String(connectForm.elements.password.value || "").trim();
      if (!address.includes("@")) {
        fieldError(connectForm, "Indiquez une adresse Gmail valide.");
        return;
      }
      if (password.replace(/\s/g, "").length < 16) {
        fieldError(connectForm, "Un mot de passe d'application Google compte 16 caractères.");
        return;
      }
      const button = connectForm.querySelector("button[type=submit]");
      setLoading(button, true, "Connexion…");
      try {
        const status = await api.connectEmail({ address, password });
        toast(`${status.address} est reliée en lecture seule. Aucun message ne sera envoyé.`, {
          title: "Gmail connecté",
        });
        ctx.refresh();
      } catch (error) {
        setLoading(button, false);
        fieldError(connectForm, errorMessage(error));
      }
    });
  }

  const syncButton = container.querySelector('[data-mail="sync"]');
  if (syncButton) {
    syncButton.addEventListener("click", async () => {
      setLoading(syncButton, true, "Synchronisation…");
      try {
        const result = await api.syncEmail();
        toast(
          result.created
            ? `${num(result.created)} nouveau${result.created > 1 ? "x" : ""} message${result.created > 1 ? "s" : ""}, ${num(result.matched)} réponse${result.matched > 1 ? "s" : ""} rattachée${result.matched > 1 ? "s" : ""}.`
            : "Aucun nouveau message depuis la dernière synchronisation.",
          { title: "Boîte synchronisée" },
        );
        ctx.refresh();
      } catch (error) {
        setLoading(syncButton, false);
        toast(errorMessage(error), { title: "Synchronisation impossible", type: "error" });
      }
    });
  }

  const testButton = container.querySelector('[data-mail="test"]');
  if (testButton) {
    testButton.addEventListener("click", async () => {
      setLoading(testButton, true, "Vérification…");
      try {
        const result = await api.testEmail();
        toast(`${num(result.messages)} messages dans la boîte, connexion en lecture seule confirmée.`, {
          title: "IMAP accessible",
        });
      } catch (error) {
        toast(errorMessage(error), { title: "Connexion impossible", type: "error" });
      } finally {
        setLoading(testButton, false);
      }
    });
  }

  const disconnectButton = container.querySelector('[data-mail="disconnect"]');
  if (disconnectButton) {
    disconnectButton.addEventListener("click", async () => {
      const confirmed = await confirmDialog({
        title: "Déconnecter Gmail ?",
        message:
          "Le mot de passe d'application sera supprimé de cet appareil. Les messages déjà synchronisés restent dans votre base locale.",
        confirmLabel: "Déconnecter",
        danger: true,
      });
      if (!confirmed) return;
      setLoading(disconnectButton, true, "Déconnexion…");
      try {
        await api.disconnectEmail();
        toast("La boîte est déconnectée. Vous pouvez retirer le mot de passe depuis votre compte Google.", {
          title: "Gmail retiré",
        });
        ctx.refresh();
      } catch (error) {
        setLoading(disconnectButton, false);
        toast(errorMessage(error), { title: "Déconnexion impossible", type: "error" });
      }
    });
  }
}
