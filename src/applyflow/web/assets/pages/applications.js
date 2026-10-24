import { api } from "../api.js";
import { icon } from "../icons.js";
import {
  emptyState,
  errorMessage,
  esc,
  formatDate,
  num,
  openModal,
  safeUrl,
  setLoading,
  toast,
} from "../ui.js";

const OUTCOME = {
  prepared: { key: "pending", label: "À envoyer", tone: "plain" },
  submitted: { key: "pending", label: "En attente", tone: "amber" },
  interview: { key: "positive", label: "Entretien", tone: "blue" },
  offer: { key: "positive", label: "Offre", tone: "sage" },
  rejected: { key: "negative", label: "Refus", tone: "red" },
  withdrawn: { key: "neutral", label: "Retirée", tone: "plain" },
};

const FILTERS = [
  ["all", "Toutes", () => true],
  ["pending", "En attente", (application) => ["prepared", "submitted"].includes(application.status)],
  ["interview", "Entretiens", (application) => application.status === "interview"],
  ["offer", "Offres", (application) => application.status === "offer"],
  ["rejected", "Refus", (application) => application.status === "rejected"],
];

const STATUS_OPTIONS = [
  { group: "Sans réponse", items: [
    { value: "submitted", title: "En attente de réponse", note: "Envoyée, pas encore de retour" },
  ] },
  { group: "Réponse positive", items: [
    { value: "interview", title: "Entretien obtenu", note: "Un échange est planifié" },
    { value: "offer", title: "Offre reçue", note: "Proposition reçue" },
  ] },
  { group: "Réponse négative", items: [
    { value: "rejected", title: "Refus reçu", note: "Candidature écartée" },
  ] },
  { group: "Hors suivi", items: [
    { value: "withdrawn", title: "Retirée", note: "Vous avez retiré votre candidature" },
  ] },
];

function outcomeChip(status) {
  const meta = OUTCOME[status] || { label: status || "—", tone: "plain" };
  return `<span class="chip chip--${esc(meta.tone)}">${esc(meta.label)}</span>`;
}

function applicationRow(application) {
  const job = application.job || {};
  const outcome = OUTCOME[application.status]?.key || "pending";
  return `<tr class="row-link" tabindex="0" data-app-id="${esc(application.id)}" data-outcome="${esc(outcome)}">
    <td>${outcomeChip(application.status)}</td>
    <td><div class="cell-title">${esc(job.title || "—")}</div><div class="cell-sub">${esc(job.company || "")}</div></td>
    <td>${esc(application.profile_name || "—")}</td>
    <td>${esc(formatDate(application.submitted_at || application.created_at))}</td>
    <td>${esc(application.external_reference || "—")}</td>
    <td><span class="arrow-link" aria-hidden="true">${icon("arrowRight")}</span></td>
  </tr>`;
}

function table(applications, filter) {
  const predicate = FILTERS.find(([key]) => key === filter)?.[2] || (() => true);
  const filtered = applications.filter(predicate);
  if (!filtered.length) {
    return emptyState({
      iconName: "applications",
      title: applications.length ? "Aucune candidature dans ce filtre" : "Aucune candidature suivie",
      text: applications.length
        ? "Changez de filtre pour retrouver vos candidatures."
        : "Les candidatures validées depuis la file de validation apparaîtront ici.",
      action: applications.length
        ? ""
        : '<a class="btn btn--primary" href="#/validation">Ouvrir la file de validation</a>',
    });
  }
  return `<div class="table-wrap">
    <table class="table">
      <thead><tr><th>Réponse</th><th>Poste</th><th>Profil</th><th>Postulé le</th><th>Référence</th><th></th></tr></thead>
      <tbody>${filtered.map(applicationRow).join("")}</tbody>
    </table>
  </div>`;
}

function outcomeOptions(application) {
  const current = application.status;
  const prepared = current === "prepared"
    ? `<div class="outcome-group">
        <div class="outcome-group-title">Pas encore envoyée</div>
        ${option({ value: "prepared", title: "Prête à envoyer", note: "Préparée, en attente de votre action" }, current)}
      </div>`
    : "";
  return `<fieldset class="outcome-fieldset">
    <legend>Où en est cette candidature ?</legend>
    ${prepared}
    ${STATUS_OPTIONS.map(
      (group) => `<div class="outcome-group">
        <div class="outcome-group-title">${esc(group.group)}</div>
        ${group.items.map((item) => option(item, current)).join("")}
      </div>`,
    ).join("")}
  </fieldset>
  <span class="hint">Ce statut est local : il ne modifie rien chez l'employeur et ne déclenche aucun e-mail.</span>`;
}

function option(item, current) {
  const meta = OUTCOME[item.value] || { tone: "plain" };
  return `<label class="outcome-option" data-tone="${esc(meta.tone)}">
    <input type="radio" name="app-status" value="${esc(item.value)}" ${item.value === current ? "checked" : ""} />
    <span class="outcome-mark" aria-hidden="true"></span>
    <span class="outcome-text"><strong>${esc(item.title)}</strong><small>${esc(item.note)}</small></span>
  </label>`;
}

function openApplication(application, ctx) {
  const job = application.job || {};
  const url = safeUrl(job.apply_url || job.url);
  openModal({
    drawer: true,
    title: job.title || "Candidature",
    subtitle: `${job.company || "Entreprise inconnue"} · ${job.location || "Localisation inconnue"}`,
    body: `<div class="tag-list" style="margin-bottom:15px">${outcomeChip(application.status)}${job.remote ? `<span class="chip chip--tag">${esc(job.remote)}</span>` : ""}</div>
      <div class="meta-grid">
        <div class="meta-item"><div class="stat-label">Profil</div><div class="meta-value">${esc(application.profile_name || "—")}</div></div>
        <div class="meta-item"><div class="stat-label">Créée le</div><div class="meta-value">${esc(formatDate(application.created_at))}</div></div>
        <div class="meta-item"><div class="stat-label">Postulé le</div><div class="meta-value">${esc(formatDate(application.submitted_at))}</div></div>
        <div class="meta-item"><div class="stat-label">Référence</div><div class="meta-value">${esc(application.external_reference || "—")}</div></div>
      </div>
      ${url !== "#" ? `<a class="btn btn--secondary btn--sm" style="margin-bottom:16px" href="${esc(url)}" target="_blank" rel="noreferrer noopener">${icon("external")} Ouvrir l'annonce</a>` : ""}
      <div class="form-section" style="border-top:1px solid var(--line-faint);padding-top:15px">
        ${outcomeOptions(application)}
      </div>`,
    footer: `<span class="foot-left">${icon("lock")} Suivi local</span>
      <button class="btn btn--ghost" type="button" data-close>Fermer</button>
      <button class="btn btn--primary" type="button" data-save>${icon("checkCircle")} Mettre à jour</button>`,
    onMount: (element, close) => {
      const save = element.querySelector("[data-save]");
      save.addEventListener("click", async () => {
        const status = element.querySelector('input[name="app-status"]:checked')?.value;
        if (!status) {
          toast("Choisissez un statut avant d'enregistrer.", {
            title: "Aucun changement",
            type: "warn",
          });
          return;
        }
        if (status === application.status) {
          close();
          return;
        }
        setLoading(save, true, "Enregistrement…");
        try {
          await api.updateApplication(application.id, status);
          close();
          toast("Le suivi de la candidature a été mis à jour.", { title: "Réponse enregistrée" });
          ctx.refresh();
        } catch (error) {
          setLoading(save, false);
          toast(errorMessage(error), { title: "Mise à jour impossible", type: "error" });
        }
      });
    },
  });
}

export async function render(container, ctx) {
  const applications = await api.applications(ctx.signal);
  if (ctx.signal.aborted) return;

  const counts = {
    pending: applications.filter((application) => ["prepared", "submitted"].includes(application.status)).length,
    positive: applications.filter((application) => ["interview", "offer"].includes(application.status)).length,
    interview: applications.filter((application) => application.status === "interview").length,
    offer: applications.filter((application) => application.status === "offer").length,
    negative: applications.filter((application) => application.status === "rejected").length,
  };
  let filter = "all";

  container.innerHTML = `
    <header class="page-head">
      <div>
        <div class="eyebrow">Suivi</div>
        <h1 class="page-title">Candidatures</h1>
        <p class="page-sub">Ce que vous avez envoyé, et où en est la réponse. Tenez le statut à jour : c'est lui qui alimente votre suivi.</p>
      </div>
      <div class="head-actions">
        <a class="btn btn--secondary" href="#/validation">${icon("queue")} File de validation</a>
      </div>
    </header>

    <div class="stat-strip" style="margin-bottom:16px">
      <div class="stat-strip-item"><strong>${num(applications.length)}</strong><span>candidature${applications.length > 1 ? "s" : ""} suivie${applications.length > 1 ? "s" : ""}</span></div>
      <div class="stat-strip-item"><strong>${num(counts.pending)}</strong><span>en attente de réponse</span></div>
      <div class="stat-strip-item"><strong>${num(counts.interview)}</strong><span>entretien${counts.interview > 1 ? "s" : ""}</span></div>
      <div class="stat-strip-item"><strong>${num(counts.offer)}</strong><span>offre${counts.offer > 1 ? "s" : ""}</span></div>
      <div class="stat-strip-item"><strong>${num(counts.negative)}</strong><span>refus</span></div>
    </div>

    <section class="panel panel--flush" aria-labelledby="apps-heading">
      <div class="panel-head panel-head--bordered">
        <div><h2 class="panel-title" id="apps-heading">Votre suivi</h2><p class="panel-sub" id="apps-count">${num(applications.length)} candidature${applications.length > 1 ? "s" : ""}</p></div>
        <div class="status-tabs" role="tablist" aria-label="Filtrer par statut">
          ${FILTERS.map(
            ([key, label, predicate]) =>
              `<button class="tab ${key === filter ? "is-active" : ""}" type="button" role="tab" aria-selected="${key === filter}" data-filter="${key}">${esc(label)}${key !== "all" ? `<span class="tab-count">${applications.filter(predicate).length}</span>` : ""}</button>`,
          ).join("")}
        </div>
      </div>
      <div id="apps-table">${table(applications, filter)}</div>
    </section>

    <p class="hint" style="margin-top:12px">Comment changer une réponse ? Ouvrez une ligne et choisissez « Entretien obtenu », « Offre reçue » ou « Refus reçu ».</p>`;

  const tableBox = document.getElementById("apps-table");
  const countBox = document.getElementById("apps-count");

  container.addEventListener("click", (event) => {
    const tab = event.target.closest("[data-filter]");
    if (tab) {
      filter = tab.dataset.filter;
      container.querySelectorAll("[data-filter]").forEach((item) => {
        const active = item === tab;
        item.classList.toggle("is-active", active);
        item.setAttribute("aria-selected", String(active));
      });
      tableBox.innerHTML = table(applications, filter);
      const predicate = FILTERS.find(([key]) => key === filter)?.[2] || (() => true);
      const count = applications.filter(predicate).length;
      countBox.textContent = `${num(count)} candidature${count > 1 ? "s" : ""}`;
      return;
    }
    const row = event.target.closest("[data-app-id]");
    if (row) {
      const application = applications.find((item) => item.id === row.dataset.appId);
      if (application) openApplication(application, ctx);
    }
  });

  container.addEventListener("keydown", (event) => {
    if (event.key !== "Enter" && event.key !== " ") return;
    const row = event.target.closest("[data-app-id]");
    if (!row) return;
    event.preventDefault();
    const application = applications.find((item) => item.id === row.dataset.appId);
    if (application) openApplication(application, ctx);
  });
}
