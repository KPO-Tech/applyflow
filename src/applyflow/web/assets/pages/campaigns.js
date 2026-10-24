import { api } from "../api.js";
import { icon } from "../icons.js";
import { locationPickerHtml, mountLocationPickers, readLocations } from "../locations.js";
import {
  CAMPAIGN_STATUS,
  STAGES,
  confirmDialog,
  emptyState,
  errorMessage,
  esc,
  fieldError,
  clearFieldError,
  formatDate,
  num,
  openModal,
  scoreBadge,
  setLoading,
  splitList,
  statusChip,
  toast,
} from "../ui.js";

const LEVELS = [
  ["intern", "Stage"],
  ["entry", "Entry level"],
  ["junior", "Junior"],
  ["mid", "Confirmé"],
  ["unknown", "Non précisé"],
];

const SOURCE_LABELS = {
  fixture: "Démo",
  json_file: "JSON",
  rss: "RSS",
  greenhouse: "Greenhouse",
  lever: "Lever",
  manual_url: "URL",
  library: "Bibliothèque",
  jobspy: "Job boards",
  ats: "ATS",
  adzuna: "Adzuna",
};

const STATUS_PHRASE = {
  draft: "Paramètres prêts, aucune exécution",
  running: "Exécution en cours",
  paused: "En attente de la prochaine étape",
  completed: "Les trois étapes ont été exécutées",
  cancelled: "Campagne arrêtée",
};

// Une offre est dans une seule étape à la fois. « Retenues » = ont passé les critères et attendent
// d'être préparées ; « Écartées » = refusées par un critère ou sous le score minimal.
function stageCounts(stages = {}) {
  const n = (key) => Number(stages[key] || 0);
  const all = Object.values(stages).reduce((sum, value) => sum + Number(value || 0), 0);
  return {
    total: all,
    waiting: n("discovered"),
    kept: n("analyzed"),
    discarded: n("rejected") + n("duplicate"),
    prepared: n("prepared") + n("approved") + n("submitted"),
    review: n("needs_review"),
    manual: n("manual"),
    blocked: n("blocked"),
  };
}

function progressValue(stages = {}) {
  const { total, waiting } = stageCounts(stages);
  return total ? Math.round(((total - waiting) / total) * 100) : 0;
}

function railItem(campaign, selectedId) {
  const counts = stageCounts(campaign.stages);
  return `<button class="rail-item ${campaign.id === selectedId ? "is-active" : ""}" type="button" data-campaign-id="${esc(campaign.id)}">
    <div class="rail-item-top">
      <span class="rail-item-name">${esc(campaign.name)}</span>
      ${statusChip(campaign.status, CAMPAIGN_STATUS)}
    </div>
    <div class="rail-item-meta">${esc(formatDate(campaign.created_at))} · ${num(counts.total)} offre${counts.total > 1 ? "s" : ""}</div>
    <div class="rail-progress" aria-hidden="true"><span style="width:${progressValue(campaign.stages)}%"></span></div>
    <div class="rail-item-foot"><span>${num(counts.kept)} retenue${counts.kept > 1 ? "s" : ""}</span><span>${num(counts.prepared)} préparée${counts.prepared > 1 ? "s" : ""}</span></div>
  </button>`;
}

function kpiStrip(stages = {}) {
  const c = stageCounts(stages);
  const tiles = [
    ["Offres", c.total, "briefcase"],
    ["En attente", c.waiting, "clock"],
    ["Retenues", c.kept, "target"],
    ["Écartées", c.discarded, "stop"],
    ["Préparées", c.prepared, "queue"],
    ["À relire", c.review, "file"],
    ["À la main", c.manual, "external"],
    ["Bloquées", c.blocked, "alert"],
  ];
  return `<div class="stat-strip campaign-kpis">${tiles
    .map(
      ([label, value, iconName]) =>
        `<div class="stat-strip-item"><span class="kpi-icon">${icon(iconName)}</span><strong>${num(value)}</strong><span>${esc(label)}</span></div>`,
    )
    .join("")}</div>`;
}

function resultsTable(results) {
  if (!results.length) {
    return emptyState({
      iconName: "campaigns",
      title: "Aucune offre suivie",
      text: "Lancez l'exécution ci-dessus : les offres apparaîtront ici au fil de la collecte, de l'analyse et de la préparation.",
      small: true,
    });
  }
  const visible = results.slice(0, 80);
  return `<div class="table-wrap">
    <table class="table">
      <thead><tr><th>Score</th><th>Offre</th><th>Étape</th><th>Profil</th><th>Routeur</th><th>Raisons</th></tr></thead>
      <tbody>
        ${visible
          .map((row) => {
            const job = row.job || {};
            const decision = row.decision || {};
            const reasons = (row.reasons || [])
              .map((reason) => reason.label)
              .filter(Boolean)
              .slice(0, 2)
              .join(" · ");
            const confidence =
              typeof decision.confidence === "number" ? `${Math.round(decision.confidence * 100)} %` : "—";
            return `<tr>
              <td>${scoreBadge(row.score)}</td>
              <td><div class="cell-title">${esc(job.title || "—")}</div><div class="cell-sub">${esc(job.company || "")}</div></td>
              <td>${statusChip(row.stage, STAGES)}</td>
              <td>${esc(decision.profile_name || "—")}${decision.uncertain ? ' <span class="chip chip--amber">incertain</span>' : ""}</td>
              <td>${esc(confidence)}</td>
              <td><span class="small muted">${esc(reasons || row.error || "—")}</span></td>
            </tr>`;
          })
          .join("")}
      </tbody>
    </table>
  </div>
  ${
    results.length > visible.length
      ? `<p class="table-foot">${num(visible.length)} premières lignes sur ${num(results.length)} · exportez le CSV pour la liste complète.</p>`
      : ""
  }`;
}

function campaignParams(campaign, profiles, catalog) {
  const selectedProfiles = (campaign.profile_ids || [])
    .map((id) => profiles.find((profile) => profile.id === id)?.name)
    .filter(Boolean);
  const sourceNames = (campaign.sources || [])
    .map(
      (source) =>
        catalog.find((item) => item.kind === source.kind)?.label ||
        SOURCE_LABELS[source.kind] ||
        source.kind,
    )
    .filter(Boolean);
  return `<details class="campaign-params">
    <summary>${icon("settings")}<span>Paramètres de la campagne</span>${icon("chevronDown", "params-caret")}</summary>
    <div class="meta-grid">
      <div class="meta-item"><div class="stat-label">Offres maximum</div><div class="meta-value">${num(campaign.max_jobs)}</div></div>
      <div class="meta-item"><div class="stat-label">Score minimal</div><div class="meta-value">${num(campaign.min_score)} / 100</div></div>
      <div class="meta-item"><div class="stat-label">Profils</div><div class="meta-value">${esc(selectedProfiles.join(" · ") || "Tous les profils actifs")}</div></div>
      <div class="meta-item"><div class="stat-label">Sources</div><div class="meta-value">${esc(sourceNames.join(" · ") || "Aucune source")}</div></div>
      <div class="meta-item"><div class="stat-label">Mots-clés</div><div class="meta-value">${esc((campaign.keywords || []).join(" · ") || "Aucun filtre")}</div></div>
      <div class="meta-item"><div class="stat-label">Localisations</div><div class="meta-value">${esc((campaign.locations || []).join(" · ") || "Toutes")}</div></div>
      <div class="meta-item"><div class="stat-label">Niveaux acceptés</div><div class="meta-value">${esc((campaign.experience_levels || []).map((key) => LEVELS.find(([value]) => value === key)?.[1] || key).join(" · ") || "Tous")}</div></div>
      <div class="meta-item"><div class="stat-label">Exclusions</div><div class="meta-value">${esc((campaign.exclusions || []).join(" · ") || "Aucune")}</div></div>
    </div>
  </details>`;
}

// Les trois étapes d'une campagne, lançables une à une pour tester et ajuster chacune.
const STEP_DEFS = [
  {
    key: "discover",
    title: "Rassembler les offres",
    text: "Reprend les offres de votre bibliothèque (ou collecte via les sources choisies) qui correspondent aux mots-clés et aux lieux de la campagne.",
    count: (stages) => `${num(stageCounts(stages).total)} offre(s) dans la campagne`,
  },
  {
    key: "analyze",
    title: "Analyser",
    text: "Choisit le profil et le CV les mieux adaptés, puis note chaque offre de 0 à 100 avec ses raisons. Aucune candidature n'est créée.",
    count: (stages) => {
      const c = stageCounts(stages);
      return `${num(c.kept + c.discarded + c.prepared + c.review + c.manual + c.blocked)} analysée(s) : ${num(c.kept)} retenue(s), ${num(c.discarded)} écartée(s) · ${num(c.waiting)} en attente`;
    },
  },
  {
    key: "prepare",
    title: "Préparer",
    text: "Pour les offres au-dessus du score minimal : analyse le formulaire et le préremplit à partir de votre profil (dry-run, jamais d'envoi).",
    count: (stages) => {
      const c = stageCounts(stages);
      return `${num(c.prepared)} préparée(s), ${num(c.review)} à relire, ${num(c.manual)} à la main, ${num(c.blocked)} bloquée(s) · ${num(c.kept)} prête(s) à préparer`;
    },
  },
];

// Score minimal saisi sur la carte « Préparer » (null : on garde celui de la campagne).
function readMinScore() {
  const raw = document.getElementById("min-score")?.value;
  return raw === undefined || raw === "" ? null : Math.max(0, Math.min(100, Number(raw)));
}

// Dernier résultat de chaque étape, gardé pendant la navigation (clé : identifiant de campagne).
const lastStepResult = {};

function describeStep(step, summary = {}) {
  const n = (value) => num(Number(value) || 0);
  let text;
  if (step === "discover") {
    const fromLibrary = Number(summary.from_library) || 0;
    const collected = Number(summary.created) || 0;
    const parts = [`${n(summary.linked)} offre(s) ajoutée(s) à la campagne`];
    if (fromLibrary) parts.push(`dont ${n(fromLibrary)} depuis la bibliothèque`);
    if (collected) parts.push(`${n(collected)} nouvelle(s) collectée(s)`);
    text = `${parts.join(" · ")}.`;
  } else if (step === "analyze") {
    text = `${n(summary.analyzed)} retenue(s), ${n(summary.rejected)} écartée(s), ${n(summary.errors)} erreur(s).`;
  } else {
    text = `${n(summary.prepared)} préparée(s), ${n(summary.needs_review)} à relire, ${n(summary.manual)} à postuler à la main, ${n(summary.blocked)} bloquée(s), ${n(summary.skipped)} sous le score minimal, ${n(summary.duplicates)} doublon(s), ${n(summary.errors)} erreur(s).`;
  }
  const remaining = Number(summary.remaining) || 0;
  if (remaining) {
    text += ` ${n(remaining)} offre(s) restent en attente : la limite est atteinte, videz le champ « Limite / étape » pour tout traiter.`;
  }
  return text;
}

// Exécution en arrière-plan : l'API rend la main tout de suite, cette page suit l'avancement.
const STEP_RUN_LABELS = {
  discover: "Collecte des offres",
  analyze: "Analyse et score",
  prepare: "Préparation des candidatures",
};

function runProgressHtml(task) {
  const { step = "", done = 0, total = 0, label = "" } = task.progress || {};
  const ratio = total ? Math.min(100, Math.round((done / total) * 100)) : 0;
  return `<div class="result-banner" role="status" aria-live="polite">
    ${icon("clock")}
    <div style="flex:1">
      <strong>${task.cancel_requested ? "Arrêt demandé…" : "Exécution en cours…"}</strong>
      <div class="usage-row" style="grid-template-columns:1fr auto;margin-top:8px">
        <span class="usage-bar" role="progressbar" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${ratio}"><span style="width:${ratio}%"></span></span>
        <span class="usage-count">${num(done)} / ${num(total) || "?"}</span>
      </div>
      <div class="small muted" style="margin-top:6px">${esc(label || STEP_RUN_LABELS[step] || "Démarrage…")}</div>
      <div style="margin-top:8px"><button class="btn btn--secondary btn--sm" type="button" data-stop-task ${task.cancel_requested ? "disabled" : ""}>${icon("stop")} Arrêter</button></div>
    </div>
  </div>`;
}

async function followCampaignTask(initial, ctx) {
  let task = initial;
  const paint = () => {
    const target = document.getElementById("campaign-run-progress");
    if (!target) return;
    target.dataset.taskId = task.id;
    target.innerHTML = runProgressHtml(task);
  };
  paint();
  while (task.status === "running") {
    await new Promise((resolve) => setTimeout(resolve, 1000));
    if (ctx.signal.aborted) return null; // l'utilisateur a quitté l'écran : le serveur continue
    try {
      task = await api.campaignTask(task.id, ctx.signal);
    } catch (error) {
      if (error.name === "AbortError") return null;
      const target = document.getElementById("campaign-run-progress");
      if (target) target.innerHTML = "";
      toast(errorMessage(error), { title: "Suivi interrompu", type: "error" });
      // 404 : le serveur a redémarré et la tâche n'existe plus ; l'état de la campagne fait foi.
      if (error.status === 404) ctx.refresh();
      return null;
    }
    if (task.status === "running") paint();
  }
  const target = document.getElementById("campaign-run-progress");
  if (target) target.innerHTML = "";
  return task;
}

function stepsPanel(campaign, status, canPause, canCancel) {
  const stages = campaign.stages || {};
  const last = lastStepResult[campaign.id];
  const locked = status === "cancelled" ? "disabled" : "";
  return `<section class="campaign-steps" aria-labelledby="campaign-steps-title">
    <div class="campaign-steps-head">
      <div>
        <strong id="campaign-steps-title">Étapes</strong>
        <p>Lancez-les une à une pour vérifier le résultat de chacune dans « Offres suivies », ou enchaînez tout.</p>
      </div>
      <label class="run-limit" for="run-limit">
        <span>Limite / étape</span>
        <input class="input" id="run-limit" type="number" min="1" max="5000" placeholder="Toutes" />
      </label>
    </div>
    <ol class="step-list">
      ${STEP_DEFS.map(
        (step, index) => `<li class="step-card">
          <span class="step-index">${index + 1}</span>
          <div class="step-card-body">
            <strong>${esc(step.title)}</strong>
            <p>${esc(step.text)}</p>
            <span class="small muted">${esc(step.count(stages))}</span>
            ${step.key === "analyze" ? `<label class="check step-redo"><input type="checkbox" id="redo-analyze" /> Ré-analyser aussi les offres déjà notées</label>` : ""}
            ${
              step.key === "prepare"
                ? `<label class="check step-redo">Score minimal <input class="input" id="min-score" type="number" min="0" max="100" value="${esc(campaign.min_score ?? 65)}" style="width:72px;min-height:28px;padding:2px 8px" aria-label="Score minimal pour préparer une offre" /> <span class="muted">abaissez-le pour récupérer des offres écartées de peu</span></label>`
                : ""
            }
          </div>
          <button class="btn btn--secondary btn--sm" type="button" data-action="run-step" data-step="${step.key}" ${locked}>${icon("play")} Lancer</button>
        </li>`,
      ).join("")}
    </ol>
    ${last ? `<div class="result-banner step-result" role="status">${icon("checkCircle")}<div><strong>${esc(STEP_DEFS.find((s) => s.key === last.step)?.title || last.step)}</strong> · ${esc(last.text)}</div></div>` : ""}
    <div id="campaign-run-progress" class="campaign-run-progress"></div>
    <div class="campaign-run-controls">
      <button class="btn btn--primary" type="button" data-action="run" ${locked}>${icon("play")} Tout enchaîner</button>
      ${canPause ? `<button class="btn btn--secondary" type="button" data-action="pause">${icon("pause")} Pause</button>` : ""}
      ${status === "paused" ? `<button class="btn btn--secondary" type="button" data-action="resume">${icon("refresh")} Reprendre</button>` : ""}
      ${canCancel ? `<button class="btn btn--ghost btn--sm campaign-cancel" type="button" data-action="cancel">${icon("stop")} Annuler la campagne</button>` : ""}
    </div>
  </section>`;
}

function detailPanel(campaign, results, profiles, catalog) {
  const status = campaign.status;
  const canPause = status === "running";
  const canCancel = !["cancelled", "completed"].includes(status);

  return `<article class="panel campaign-detail-card" aria-labelledby="campaign-detail-heading">
    <header class="campaign-detail-head">
      <div>
        <div class="eyebrow">Campagne</div>
        <h2 class="detail-title" id="campaign-detail-heading">${esc(campaign.name)}</h2>
        <p class="detail-sub">Créée le ${esc(formatDate(campaign.created_at))} · ${esc(STATUS_PHRASE[status] || status)}</p>
      </div>
      <div class="campaign-head-side">
        ${statusChip(status, CAMPAIGN_STATUS)}
        <div class="export-row">
          <a class="btn btn--ghost btn--sm" href="${api.campaignExportUrl(campaign.id, "csv")}" download>${icon("download")} CSV</a>
          <a class="btn btn--ghost btn--sm" href="${api.campaignExportUrl(campaign.id, "json")}" download>${icon("download")} JSON</a>
        </div>
      </div>
    </header>

    ${campaign.last_error ? `<div class="alert campaign-alert">${icon("alert")}<div>${esc(campaign.last_error)}</div></div>` : ""}

    ${kpiStrip(campaign.stages)}

    ${stepsPanel(campaign, status, canPause, canCancel)}

    ${campaignParams(campaign, profiles, catalog)}
  </article>

  <section class="panel panel--flush campaign-results" aria-labelledby="campaign-results-heading">
    <div class="panel-head panel-head--bordered">
      <div>
        <h2 class="panel-title" id="campaign-results-heading">Offres suivies</h2>
        <p class="panel-sub">Scores, décision de routage et raisons détaillées.</p>
      </div>
      <span class="chip chip--tag">${num(results.length)}</span>
    </div>
    ${resultsTable(results)}
  </section>`;
}

function onboarding() {
  return `<section class="onboarding" aria-labelledby="campaign-onboarding-title">
    <div class="onboarding-head">
      <span class="empty-icon">${icon("campaigns")}</span>
      <h2 id="campaign-onboarding-title">Lancez votre première campagne</h2>
      <p>Un cadre, trois étapes, une trace. Rien n'est envoyé à votre place.</p>
    </div>
    <ol class="onboarding-steps">
      <li>
        <span class="step-index">1</span>
        <div><strong>Collecter</strong><p>Importez une URL, un board Greenhouse/Lever ou un flux RSS. Les doublons sont écartés.</p></div>
      </li>
      <li>
        <span class="step-index">2</span>
        <div><strong>Analyser</strong><p>Chaque offre est routée vers un profil et notée de 0 à 100, avec ses raisons.</p></div>
      </li>
      <li>
        <span class="step-index">3</span>
        <div><strong>Préparer</strong><p>Les candidatures retenues sont préremplies en dry-run, à relire avant tout envoi.</p></div>
      </li>
    </ol>
    <div class="onboarding-actions">
      <button class="btn btn--primary" type="button" id="empty-new-campaign">${icon("plus")} Créer une campagne</button>
      <a class="btn btn--ghost" href="#/decouverte">${icon("discovery")} Ajouter des offres d'abord</a>
    </div>
    <p class="hint">Pour que l'analyse ait une base, commencez par <a class="link-btn" href="#/profils">créer un profil et déposer un CV</a>.</p>
  </section>`;
}

function createCampaignDialog(ctx, profiles, catalog) {
  const available = [
    {
      kind: "library",
      label: "Mes offres déjà collectées (bibliothèque)",
      available: true,
    },
    ...catalog.filter(
      (source) => source.available && source.kind !== "fixture" && source.configured !== false,
    ),
  ];
  const activeProfiles = profiles.filter((profile) => profile.active);
  const dialog = openModal({
    title: "Nouvelle campagne",
    subtitle: "Un cadre clair pour collecter, analyser et préparer. Rien n'est envoyé automatiquement.",
    wide: true,
    body: `<form id="campaign-form" novalidate>
      <div class="form-section">
        <div class="form-section-title">Cadre de la campagne</div>
        <div class="form-grid">
          <div class="field span-2">
            <label for="campaign-name">Nom de la campagne <span class="opt">obligatoire</span></label>
            <input class="input" id="campaign-name" name="name" required placeholder="Ex. Data Engineer — Île-de-France" />
          </div>
          <div class="field">
            <label for="campaign-max">Nombre maximum d'offres</label>
            <input class="input" id="campaign-max" name="max_jobs" type="number" min="1" max="5000" value="250" />
          </div>
          <div class="field">
            <label for="campaign-score">Score minimal</label>
            <input class="input" id="campaign-score" name="min_score" type="number" min="0" max="100" value="65" />
          </div>
          <div class="field">
            <label for="campaign-keywords">Mots-clés</label>
            <input class="input" id="campaign-keywords" name="keywords" placeholder="data engineer, analytics" />
          </div>
          <div class="field">
            <label for="campaign-locations">Localisations</label>
            ${locationPickerHtml({ id: "campaign-locations", values: [] })}
          </div>
          <div class="field span-2">
            <span class="field-label">Niveaux acceptés</span>
            <div class="check-row">
              ${LEVELS.map(
                ([key, label]) =>
                  `<label class="check"><input type="checkbox" name="experience_levels" value="${key}" ${
                    ["intern", "entry", "junior", "unknown"].includes(key) ? "checked" : ""
                  } /> ${esc(label)}</label>`,
              ).join("")}
            </div>
          </div>
          <div class="field span-2">
            <label for="campaign-exclusions">Exclusions</label>
            <input class="input" id="campaign-exclusions" name="exclusions" placeholder="management, vente, alternance…" />
            <span class="hint">Mots-clés qui écartent une offre, en plus des portes d'éligibilité.</span>
          </div>
        </div>
      </div>

      <div class="form-section">
        <div class="form-section-title">Sources</div>
        <div class="check-row">
          ${available
            .map(
              (source) =>
                `<label class="check"><input type="checkbox" name="sources" value="${esc(source.kind)}" ${source.kind === "library" ? "checked" : ""} /> ${esc(source.label)}</label>`,
            )
            .join("")}
        </div>
        <details style="margin-top:10px">
          <summary class="small muted" style="cursor:pointer">Configuration avancée des sources (JSON)</summary>
          <div class="field" style="margin-top:8px">
            <label for="campaign-source-config">Tableau JSON <span class="opt">facultatif</span></label>
            <textarea class="textarea mono" id="campaign-source-config" name="source_config" placeholder='[{"kind":"greenhouse","config":{"board_token":"acme"}}]'></textarea>
            <span class="hint">Si rempli, ce tableau remplace les cases à cocher ci-dessus. Chaque entrée doit contenir un champ <span class="mono">kind</span>.</span>
          </div>
        </details>
      </div>

      <div class="form-section">
        <div class="form-section-title">Profils autorisés</div>
        ${
          activeProfiles.length
            ? `<div class="check-row">${activeProfiles
                .map(
                  (profile) =>
                    `<label class="check"><input type="checkbox" name="profile_ids" value="${esc(profile.id)}" checked /> ${esc(profile.name)}</label>`,
                )
                .join("")}</div>
               <p class="hint" style="margin-top:6px">Décochez tout pour laisser ApplyFlow utiliser tous les profils actifs.</p>`
            : `<div class="alert">${icon("alert")}<div>Aucun profil actif. <a class="link-btn" href="#/profils">Créez un profil</a> avant de lancer une analyse.</div></div>`
        }
      </div>
    </form>`,
    footer: `<span class="foot-left">${icon("lock")} Dry-run par défaut</span>
      <button class="btn btn--ghost" type="button" data-close>Annuler</button>
      <button class="btn btn--primary" type="submit" form="campaign-form" data-create>${icon("plus")} Créer la campagne</button>`,
    onMount: (element, close) => {
      const form = element.querySelector("#campaign-form");
      mountLocationPickers(form);
      const submit = element.querySelector("[data-create]");
      form.addEventListener("submit", async (event) => {
        event.preventDefault();
        clearFieldError(form);
        const name = String(form.elements.name.value || "").trim();
        if (name.length < 2) {
          fieldError(form, "Donnez un nom d'au moins 2 caractères à la campagne.");
          form.elements.name.focus();
          return;
        }
        const locationCheck = readLocations(form.querySelector("[data-loc-picker]"));
        if (locationCheck.error) {
          fieldError(form, locationCheck.error);
          form.querySelector("[data-country-input]").focus();
          return;
        }
        let sources;
        const rawConfig = String(form.elements.source_config.value || "").trim();
        if (rawConfig) {
          try {
            sources = JSON.parse(rawConfig);
          } catch {
            fieldError(form, "La configuration JSON des sources n'est pas valide.");
            return;
          }
          if (!Array.isArray(sources) || !sources.length) {
            fieldError(form, "La configuration avancée doit être un tableau non vide.");
            return;
          }
        } else {
          const checkedSources = [...form.querySelectorAll('input[name="sources"]:checked')].map(
            (input) => input.value,
          );
          if (!checkedSources.length) {
            fieldError(form, "Choisissez au moins une source.");
            return;
          }
          sources = checkedSources.map((kind) => ({ kind, config: {} }));
        }
        const payload = {
          name,
          sources,
          profile_ids: [...form.querySelectorAll('input[name="profile_ids"]:checked')].map(
            (input) => input.value,
          ),
          keywords: splitList(form.elements.keywords.value),
          locations: locationCheck.values,
          experience_levels: [
            ...form.querySelectorAll('input[name="experience_levels"]:checked'),
          ].map((input) => input.value),
          max_jobs: Number(form.elements.max_jobs.value) || 250,
          min_score: Number(form.elements.min_score.value) || 65,
          exclusions: splitList(form.elements.exclusions.value),
        };
        setLoading(submit, true, "Création…");
        try {
          const created = await api.createCampaign(payload);
          close();
          toast(`Campagne « ${created.name} » créée.`, { title: "Prête à être lancée" });
          ctx.navigate(`campagnes?campaign=${created.id}`);
        } catch (error) {
          setLoading(submit, false);
          fieldError(form, errorMessage(error));
        }
      });
    },
  });
  return dialog;
}

export async function render(container, ctx) {
  const [campaigns, profiles, catalog] = await Promise.all([
    api.campaigns(ctx.signal),
    api.profiles(),
    api.sources(),
  ]);
  if (ctx.signal.aborted) return;

  const requested = ctx.query.get("campaign");
  const selected = campaigns.find((campaign) => campaign.id === requested) || campaigns[0] || null;
  let results = [];
  if (selected) {
    try {
      results = await api.campaignResults(selected.id, ctx.signal);
    } catch (error) {
      if (error.name !== "AbortError") results = [];
    }
  }
  if (ctx.signal.aborted) return;

  container.innerHTML = `
    <header class="page-head">
      <div>
        <div class="eyebrow">Pilotage</div>
        <h1 class="page-title">Campagnes</h1>
        <p class="page-sub">Collectez large, analysez avec vos règles, préparez sans jamais envoyer à votre place.</p>
      </div>
      <div class="head-actions">
        <button class="btn btn--primary" type="button" id="new-campaign">${icon("plus")} Nouvelle campagne</button>
      </div>
    </header>

    ${
      !campaigns.length
        ? onboarding()
        : `<div class="campaign-board">
            <aside class="campaign-rail" aria-label="Vos campagnes">
              <div class="rail-head">
                <h2>Vos campagnes</h2>
                <span class="chip chip--tag">${num(campaigns.length)}</span>
              </div>
              <div class="rail-list">${campaigns.map((campaign) => railItem(campaign, selected?.id)).join("")}</div>
              <a class="rail-new" href="#/campagnes?new=1">${icon("plus")} Nouvelle campagne</a>
            </aside>
            <div class="campaign-main">${detailPanel(selected, results, profiles, catalog)}</div>
          </div>`
    }`;

  const openCreate = () => {
    if (ctx.query.get("new") === "1") history.replaceState(null, "", "#/campagnes");
    createCampaignDialog(ctx, profiles, catalog);
  };
  document.getElementById("new-campaign")?.addEventListener("click", openCreate);
  document.getElementById("empty-new-campaign")?.addEventListener("click", openCreate);
  if (ctx.query.get("new") === "1") openCreate();

  const runInBackground = async (button, { steps, maxItems, redo }) => {
    try {
      const task = await api.startCampaign(selected.id, maxItems, steps, redo, readMinScore());
      const finished = await followCampaignTask(task, ctx);
      if (!finished) return; // navigation : l'exécution continue côté serveur
      if (finished.status === "error") {
        setLoading(button, false);
        toast(finished.error || "L'exécution a échoué.", {
          title: "Campagne interrompue",
          type: "error",
        });
        return;
      }
      const result = finished.result || {};
      if (steps.length === 1) {
        const step = steps[0];
        const text = describeStep(step, result.steps?.[step]);
        lastStepResult[selected.id] = { step, text };
        toast(text, {
          title: `${STEP_DEFS.find((item) => item.key === step)?.title || "Étape terminée"}${finished.status === "cancelled" ? " (interrompue)" : ""}`,
          duration: 6000,
        });
      } else {
        toast(`Statut final : ${result.status}. Les résultats sont à jour.`, {
          title: finished.status === "cancelled" ? "Campagne arrêtée" : "Campagne terminée",
          duration: 7000,
        });
      }
      ctx.refresh();
    } catch (error) {
      setLoading(button, false);
      toast(errorMessage(error), { title: "Exécution impossible", type: "error" });
    }
  };

  container.addEventListener("click", async (event) => {
    const railButton = event.target.closest("[data-campaign-id]");
    if (railButton) {
      if (railButton.dataset.campaignId === selected?.id) return;
      ctx.navigate(`campagnes?campaign=${railButton.dataset.campaignId}`);
      return;
    }
    if (!selected) return;
    const action = event.target.closest("[data-action]")?.dataset.action;
    if (!action) return;

    if (action === "resume") {
      const button = event.target.closest("[data-action]");
      setLoading(button, true, "Reprise…");
      try {
        await api.resumeCampaign(selected.id);
        toast("La campagne est prête à être exécutée.", { title: "Campagne reprise" });
        ctx.refresh();
      } catch (error) {
        setLoading(button, false);
        toast(errorMessage(error), { title: "Reprise impossible", type: "error" });
      }
      return;
    }

    if (action === "pause") {
      const button = event.target.closest("[data-action]");
      setLoading(button, true, "Pause…");
      try {
        await api.pauseCampaign(selected.id);
        toast("L'exécution s'arrêtera à la prochaine étape.", { title: "Campagne en pause" });
        ctx.refresh();
      } catch (error) {
        setLoading(button, false);
        toast(errorMessage(error), { title: "Pause impossible", type: "error" });
      }
      return;
    }

    if (action === "cancel") {
      const ok = await confirmDialog({
        title: "Annuler cette campagne ?",
        message: `La campagne « ${selected.name} » sera arrêtée et ne pourra plus être reprise.`,
        details: "<p>Les offres déjà analysées et les candidatures préparées restent disponibles.</p>",
        confirmLabel: "Annuler la campagne",
        danger: true,
      });
      if (!ok) return;
      try {
        await api.cancelCampaign(selected.id);
        toast("La campagne est annulée. Les candidatures existantes sont conservées.", {
          title: "Campagne annulée",
        });
        ctx.refresh();
      } catch (error) {
        toast(errorMessage(error), { title: "Annulation impossible", type: "error" });
      }
      return;
    }

    if (action === "run-step") {
      const button = event.target.closest("[data-action]");
      const step = button.dataset.step;
      const limit = Number(document.getElementById("run-limit")?.value) || null;
      const redo = step === "analyze" && Boolean(document.getElementById("redo-analyze")?.checked);
      setLoading(button, true, "En cours…");
      await runInBackground(button, { steps: [step], maxItems: limit, redo });
      return;
    }

    if (action === "run") {
      const button = event.target.closest("[data-action]");
      const limit = Number(document.getElementById("run-limit")?.value) || null;
      setLoading(button, true, "Campagne en cours…");
      await runInBackground(button, {
        steps: ["discover", "analyze", "prepare"],
        maxItems: limit,
        redo: false,
      });
    }
  });

  document.getElementById("campaign-run-progress")?.addEventListener("click", async (event) => {
    const stop = event.target.closest("[data-stop-task]");
    const box = document.getElementById("campaign-run-progress");
    if (!stop || !box?.dataset.taskId) return;
    stop.disabled = true;
    try {
      await api.cancelCampaignTask(box.dataset.taskId);
    } catch (error) {
      stop.disabled = false;
      toast(errorMessage(error), { title: "Arrêt impossible", type: "error" });
    }
  });

  // Reprise : une campagne lancée avant de quitter l'écran continue côté serveur.
  api
    .activeCampaignTask(ctx.signal)
    .then(async (active) => {
      if (!active || ctx.signal.aborted || !selected || active.campaign_id !== selected.id) return;
      const finished = await followCampaignTask(active, ctx);
      if (finished) ctx.refresh();
    })
    .catch(() => {});
}
