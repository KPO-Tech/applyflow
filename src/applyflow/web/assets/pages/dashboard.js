import { api } from "../api.js";
import { icon } from "../icons.js";
import {
  ATTEMPT_STATUS,
  CAMPAIGN_STATUS,
  emptyState,
  esc,
  formatDate,
  num,
  pct,
  statusChip,
} from "../ui.js";

const REVIEW_STATUSES = new Set(["prepared", "needs_review", "manual", "approved"]);
const STATUS_ORDER = { needs_review: 0, prepared: 1, manual: 2, approved: 3, blocked: 4, submitted: 5 };

function pipelineSegments(metrics) {
  return [
    ["Offres collectées", metrics.jobs_collected],
    ["Analysées", metrics.jobs_analyzed],
    ["Pertinentes", metrics.jobs_relevant],
    ["Préparées", metrics.applications_prepared],
    ["Soumises", metrics.applications_submitted],
  ];
}

function campaignProgress(stages = {}) {
  const groups = {
    collected: Number(stages.discovered || 0),
    analyzed:
      Number(stages.analyzed || 0) +
      Number(stages.rejected || 0) +
      Number(stages.duplicate || 0),
    prepared: Number(stages.prepared || 0) + Number(stages.approved || 0) + Number(stages.submitted || 0),
    review: Number(stages.needs_review || 0),
    blocked: Number(stages.blocked || 0),
  };
  return groups;
}

function miniBar(stages = {}) {
  const groups = campaignProgress(stages);
  const total = Object.values(groups).reduce((sum, value) => sum + value, 0);
  if (!total) {
    return `<div class="mini-bar" aria-hidden="true"><span style="width:100%;opacity:.18"></span></div>`;
  }
  return `<div class="mini-bar" aria-hidden="true">
    <span style="width:${(groups.prepared / total) * 100}%"></span>
    <span style="width:${(groups.review / total) * 100}%"></span>
    <span style="width:${(groups.blocked / total) * 100}%"></span>
  </div>`;
}

function campaignStages(stages = {}) {
  const groups = campaignProgress(stages);
  const cells = [
    ["Collecte", groups.collected > 0],
    ["Analyse", groups.analyzed > 0],
    ["Préparation", groups.prepared > 0],
    ["Relecture", groups.review > 0],
    ["Soumission", Number(stages.submitted || 0) > 0],
  ];
  return `<div class="campaign-stages" aria-hidden="true">
    ${cells
      .map(
        ([label, done]) =>
          `<span class="stage-seg ${done ? "is-done" : ""}" title="${esc(label)}"></span>`,
      )
      .join("")}
  </div>`;
}

function metricBlock(label, value, note, bar, iconName) {
  return `<div class="metric">
    <div class="metric-label"><span>${esc(label)}</span>${icon(iconName)}</div>
    <div class="metric-value">${num(value)}</div>
    <div class="metric-note">${note}</div>
    <div class="metric-bar" aria-hidden="true"><span style="width:${Math.min(100, Math.max(2, bar))}%"></span></div>
  </div>`;
}

function renderQueueItem(attempt) {
  const job = attempt.job || {};
  const meta = ATTEMPT_STATUS[attempt.status] || ATTEMPT_STATUS.prepared;
  const fills = Array.isArray(attempt.plan?.fills) ? attempt.plan.fills.length : 0;
  const unknown = Array.isArray(attempt.unknown_questions)
    ? attempt.unknown_questions.length
    : Array.isArray(attempt.plan?.unknown_questions)
      ? attempt.plan.unknown_questions.length
      : 0;
  return `<a class="row-item" href="#/validation?attempt=${esc(attempt.id)}">
    <div class="row-main">
      <div class="row-title"><span>${esc(job.title || "Offre sans titre")}</span></div>
      <div class="row-sub">
        <span>${esc(job.company || "Entreprise inconnue")}</span>
        <span class="sep">·</span>
        <span>${esc(attempt.profile_name || "Profil")}</span>
        <span class="sep">·</span>
        <span>${fills} champ${fills > 1 ? "s" : ""}${unknown ? ` · ${unknown} question${unknown > 1 ? "s" : ""}` : ""}</span>
      </div>
    </div>
    <div class="row-end">${statusChip(attempt.status)}<span class="arrow-link">${icon("arrowRight")}</span></div>
  </a>`;
}

function renderCampaignItem(campaign) {
  const status = CAMPAIGN_STATUS[campaign.status] || { label: campaign.status, tone: "plain" };
  return `<a class="campaign-mini" href="#/campagnes?campaign=${esc(campaign.id)}">
    <div class="campaign-mini-top">
      <div>
        <div class="campaign-mini-name">${esc(campaign.name)}</div>
        <div class="campaign-mini-meta">${esc(status.label)} · ${campaign.max_jobs} offres max · ${formatDate(campaign.created_at)}</div>
      </div>
      ${statusChip(campaign.status, CAMPAIGN_STATUS)}
    </div>
    ${miniBar(campaign.stages)}
  </a>`;
}

export async function render(container, ctx) {
  const [metrics, campaigns, queue] = await Promise.all([
    api.dashboard(),
    api.campaigns(ctx.signal),
    api.queue(ctx.signal),
  ]);
  if (ctx.signal.aborted) return;

  const reviewItems = queue
    .filter((item) => REVIEW_STATUSES.has(item.status))
    .sort((a, b) => (STATUS_ORDER[a.status] ?? 9) - (STATUS_ORDER[b.status] ?? 9));
  const preparedCount = queue.filter((item) => item.status === "prepared").length;
  const reviewCount = queue.filter((item) => item.status === "needs_review").length;
  const approvedCount = queue.filter((item) => item.status === "approved").length;
  const toReview = reviewItems.length;
  const analyzed = Number(metrics.jobs_analyzed || 0);
  const relevant = Number(metrics.jobs_relevant || 0);
  const prepared = Number(metrics.applications_prepared || 0);
  const submitted = Number(metrics.applications_submitted || 0);
  const collected = Number(metrics.jobs_collected || 0);
  const failures = Number(metrics.failures || 0);
  const preparationRate = analyzed ? Math.round((prepared / analyzed) * 100) : 0;
  const circumference = 2 * Math.PI * 40;

  const perProfile = Array.isArray(metrics.per_profile) ? metrics.per_profile : [];
  const profileMax = Math.max(1, ...perProfile.map((row) => Number(row.jobs) || 0));
  const latestCampaigns = campaigns.slice(0, 4);
  const topQueue = reviewItems.slice(0, 4);

  const heroTitle =
    collected === 0
      ? `Votre pipeline commence par une <em>première offre.</em>`
      : relevant > 0
        ? `${num(relevant)} offre${relevant > 1 ? "s" : ""} passent le filtre. <em>${num(toReview)} attende${toReview > 1 ? "nt" : ""} votre relecture.</em>`
        : `Tout est collecté. <em>Affinez vos critères pour faire émerger les bonnes offres.</em>`;

  const heroSub =
    collected === 0
      ? "Lancez une campagne ou importez une poignée d'annonces. Le reste — dédoublonnage, analyse, préparation — se fait ici, sans quitter votre machine."
      : `${num(analyzed)} offres analysées sur ${num(collected)} collectées, réparties sur ${perProfile.length || "vos"} profil${perProfile.length > 1 ? "s" : ""}. Aucune candidature ne part sans votre validation.`;

  container.innerHTML = `
    <header class="page-head">
      <div>
        <div class="eyebrow">Vue d'ensemble</div>
        <h1 class="page-title">Votre recherche, en un coup d'œil.</h1>
        <p class="page-sub">Le pouls de votre pipeline, les candidatures à relire et les campagnes qui travaillent pour vous.</p>
      </div>
      <div class="head-actions">
        <button class="btn btn--secondary" type="button" id="dash-refresh">${icon("refresh")} Actualiser</button>
        <a class="btn btn--primary" href="#/campagnes?new=1">${icon("plus")} Nouvelle campagne</a>
      </div>
    </header>

    <div class="dash-grid">
      <section class="metrics" aria-label="Indicateurs clés">
        ${metricBlock(
          "Offres collectées",
          collected,
          `<strong>${pct(analyzed, collected)} %</strong> déjà analysées`,
          pct(analyzed, collected),
          "briefcase",
        )}
        ${metricBlock(
          "Offres pertinentes",
          relevant,
          `<strong>${pct(relevant, analyzed)} %</strong> des offres analysées`,
          pct(relevant, collected),
          "target",
        )}
        ${metricBlock(
          "À relire",
          preparedCount + reviewCount,
          `<strong>${approvedCount}</strong> validée${approvedCount > 1 ? "s" : ""} · ${reviewCount} à compléter`,
          pct(preparedCount + reviewCount, prepared + reviewCount + approvedCount),
          "queue",
        )}
        ${metricBlock(
          "Candidatures soumises",
          submitted,
          failures ? `<strong>${failures}</strong> blocage${failures > 1 ? "s" : ""} à examiner` : "Aucun blocage signalé",
          pct(submitted, Math.max(prepared, 1)),
          "applications",
        )}
      </section>

      <section class="pulse" aria-labelledby="pulse-title">
        <div class="pulse-main">
          <div class="eyebrow">Le pipeline</div>
          <h2 class="pulse-title" id="pulse-title">${heroTitle}</h2>
          <p class="pulse-sub">${esc(heroSub)}</p>
          <div class="pulse-actions">
            <a class="btn btn--cream" href="#/validation">${icon("queue")} Ouvrir la file ${toReview ? `<span aria-hidden="true">· ${toReview}</span>` : ""}</a>
            <a class="btn btn--hero-ghost" href="#/decouverte">${icon("discovery")} Ajouter des offres</a>
          </div>
        </div>
        <div class="pulse-side">
          <div class="pulse-ring" role="img" aria-label="Taux de préparation : ${preparationRate} %">
            <svg viewBox="0 0 92 92" aria-hidden="true">
              <circle class="ring-track" cx="46" cy="46" r="40" />
              <circle class="ring-value" cx="46" cy="46" r="40"
                stroke-dasharray="${(circumference * preparationRate) / 100} ${circumference}" />
            </svg>
            <div class="pulse-ring-label"><strong>${preparationRate}%</strong><span>préparé</span></div>
          </div>
          <div class="pulse-stats">
            <div class="pulse-stat"><span>Profils concernés</span><strong>${perProfile.length}</strong></div>
            <div class="pulse-stat"><span>Campagnes</span><strong>${campaigns.length}</strong></div>
            <div class="pulse-stat"><span>Blocages</span><strong>${failures}</strong></div>
          </div>
        </div>
        <div class="pipeline">
          <div class="pipeline-meta"><span>Du sourcing à la soumission</span><span>${collected ? `${pct(relevant, collected)} % de pertinence` : "en attente de données"}</span></div>
          <div class="pipeline-bar" aria-hidden="true">
            ${pipelineSegments(metrics)
              .map(
                ([, value]) =>
                  `<span class="pipeline-seg" style="flex:${Math.max(Number(value) || 0, 0.04)}"></span>`,
              )
              .join("")}
          </div>
          <div class="pipeline-labels">
            ${pipelineSegments(metrics)
              .map(
                ([label, value]) =>
                  `<div class="pipeline-label"><strong>${num(value)}</strong>${esc(label)}</div>`,
              )
              .join("")}
          </div>
        </div>
      </section>

      <div class="dash-split">
        <section class="panel panel--flush" aria-labelledby="queue-heading">
          <div class="panel-head panel-head--bordered">
            <div>
              <h2 class="panel-title" id="queue-heading">À traiter maintenant</h2>
              <p class="panel-sub">${toReview ? "Les candidatures qui demandent une décision de votre part." : "La file se remplira après votre première analyse."}</p>
            </div>
            <a class="link-btn" href="#/validation">Tout voir ${icon("arrowRight")}</a>
          </div>
          ${
            topQueue.length
              ? `<div class="row-list">${topQueue.map(renderQueueItem).join("")}</div>`
              : emptyState({
                  iconName: "queue",
                  title: "Rien à relire pour l'instant",
                  text: "Lancez une campagne pour préparer vos premières candidatures.",
                  action: '<a class="btn btn--secondary btn--sm" href="#/campagnes?new=1">Créer une campagne</a>',
                  small: true,
                })
          }
        </section>

        <section class="panel panel--flush" aria-labelledby="campaigns-heading">
          <div class="panel-head panel-head--bordered">
            <div>
              <h2 class="panel-title" id="campaigns-heading">Campagnes récentes</h2>
              <p class="panel-sub">Le travail de fond, sans bruit.</p>
            </div>
            <a class="link-btn" href="#/campagnes">Gérer ${icon("arrowRight")}</a>
          </div>
          ${
            latestCampaigns.length
              ? latestCampaigns.map(renderCampaignItem).join("")
              : emptyState({
                  iconName: "campaigns",
                  title: "Aucune campagne",
                  text: "Une campagne enchaîne collecte, analyse et préparation.",
                  action: '<a class="btn btn--secondary btn--sm" href="#/campagnes?new=1">Créer la première</a>',
                  small: true,
                })
          }
        </section>
      </div>

      <div class="split">
        <section class="panel" aria-labelledby="profiles-heading">
          <div class="panel-head">
            <div>
              <h2 class="panel-title" id="profiles-heading">Répartition par profil</h2>
              <p class="panel-sub">Les profils qui portent le plus d'offres analysées.</p>
            </div>
          </div>
          <div class="panel-body">
            ${
              perProfile.length
                ? `<div class="profile-bars">${perProfile
                    .slice(0, 6)
                    .map(
                      (row) => `<div class="profile-bar-row">
                        <div>
                          <div class="profile-bar-label"><span>${esc(row.name)}</span><span>${num(row.jobs)} offres</span></div>
                          <div class="profile-bar-track"><span style="width:${Math.max(4, (Number(row.jobs) / profileMax) * 100)}%"></span></div>
                        </div>
                        <div class="profile-bar-total">${pct(row.jobs, analyzed)}%</div>
                      </div>`,
                    )
                    .join("")}</div>`
                : emptyState({
                    iconName: "profiles",
                    title: "Pas encore de répartition",
                    text: "Les profils apparaîtront ici dès la première analyse.",
                    small: true,
                  })
            }
          </div>
        </section>

        <div class="stack">
          <div class="safety-note">
            ${icon("lock")}
            <div>
              <strong>Le dernier mot vous revient.</strong>
              <p>ApplyFlow prépare, explique et trace. Il ne clique jamais sur « Envoyer » : chaque candidature est validée puis soumise par vous.</p>
            </div>
          </div>
          <section class="panel" aria-labelledby="next-heading">
            <div class="panel-body">
              <div class="eyebrow" style="color:var(--muted)">Prochaine étape</div>
              <h2 class="panel-title mt-8" id="next-heading" style="font-family:var(--font-display);font-size:22px;font-weight:500;line-height:1.15;margin-top:8px">
                ${reviewCount ? "Complétez les questions ouvertes." : preparedCount ? "Relisez les candidatures prêtes." : "Donnez le coup d'envoi à une campagne."}
              </h2>
              <p class="small muted" style="margin-top:6px">${
                reviewCount
                  ? `${reviewCount} candidature${reviewCount > 1 ? "s" : ""} attend${reviewCount > 1 ? "ent" : ""} une réponse validée pour continuer.`
                  : preparedCount
                    ? `${preparedCount} candidature${preparedCount > 1 ? "s sont prêtes" : " est prête"} à être relue${preparedCount > 1 ? "s" : ""} avant validation.`
                    : "Collectez des offres, laissez ApplyFlow les analyser, puis retrouvez les meilleures dans la file de validation."
              }</p>
              <a class="link-btn" style="margin-top:12px" href="${reviewCount ? "#/validation" : preparedCount ? "#/validation" : "#/campagnes?new=1"}">
                ${reviewCount || preparedCount ? "Ouvrir la file" : "Créer une campagne"} ${icon("arrowRight")}
              </a>
            </div>
          </section>
        </div>
      </div>
    </div>`;

  document.getElementById("dash-refresh")?.addEventListener("click", () => ctx.refresh());
}
