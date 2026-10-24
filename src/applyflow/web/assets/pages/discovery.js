import { api } from "../api.js";
import { icon } from "../icons.js";
import { locationPickerHtml, mountLocationPickers, readLocations } from "../locations.js";
import {
  confirmDialog,
  debounce,
  emptyState,
  errorMessage,
  esc,
  fieldError,
  clearFieldError,
  formatDate,
  num,
  openModal,
  safeUrl,
  setLoading,
  splitList,
  toast,
} from "../ui.js";

const SOURCE_ICONS = {
  json_file: "file",
  rss: "mail",
  greenhouse: "briefcase",
  lever: "briefcase",
  manual_url: "external",
  adzuna: "discovery",
  jobspy: "search",
  ats: "briefcase",
};

const JOBSPY_SITES = {
  indeed: "Indeed",
  hellowork: "HelloWork",
  linkedin: "LinkedIn",
  glassdoor: "Glassdoor",
  google: "Google",
};

const COUNTRY_NAMES = {
  FR: "France",
  GB: "Royaume-Uni",
  DE: "Allemagne",
  ES: "Espagne",
  IT: "Italie",
  PT: "Portugal",
  NL: "Pays-Bas",
  BE: "Belgique",
  LU: "Luxembourg",
  CH: "Suisse",
  IE: "Irlande",
  US: "États-Unis",
  CA: "Canada",
  unknown: "Pays inconnu",
};

function countryName(code) {
  return COUNTRY_NAMES[code] || code || "Pays inconnu";
}

const SOURCE_LABELS = {
  jobspy: "Job boards",
  ats: "ATS",
  json_file: "JSON",
  rss: "RSS",
  greenhouse: "Greenhouse",
  lever: "Lever",
  manual_url: "URL",
  adzuna: "Adzuna",
};

const REMOTE_LABELS = {
  remote: "Télétravail",
  hybrid: "Hybride",
  onsite: "Sur site",
  unspecified: "Non précisé",
};

const SENIORITY_LABELS = {
  intern: "Stage",
  entry: "Entry level",
  junior: "Junior",
  mid: "Confirmé",
  senior: "Senior",
  lead: "Lead",
  principal: "Principal",
  unknown: "Non précisé",
};

const CONTRACT_LABELS = {
  internship: "Stage",
  permanent: "Permanent",
  freelance: "Freelance",
  "fixed-term": "CDD",
};

function jobSource(job) {
  return SOURCE_LABELS[job.source] || job.source || "—";
}

function jobSeniority(job) {
  return SENIORITY_LABELS[job.seniority] || job.seniority || "—";
}

function jobContract(job) {
  return CONTRACT_LABELS[job.contract_type] || job.contract_type || "—";
}

function jobRemote(job) {
  if (!job.remote || job.remote === "unspecified") return "";
  return REMOTE_LABELS[job.remote] || job.remote;
}

function uniqueSkills(skills) {
  const seen = new Set();
  return (skills || []).filter((skill) => {
    const key = String(skill).trim().toLowerCase();
    if (!key || seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

// Rempli au chargement de l'écran à partir de Réglages → Collecte → Recherche par défaut.
let searchDefaults = {};

function usageList(usage, sites) {
  const rows = (sites || Object.keys(usage || {}))
    .filter((site) => usage?.[site])
    .map((site) => {
      const { used = 0, limit = null } = usage[site];
      const ratio = limit ? Math.min(100, Math.round((used / limit) * 100)) : 0;
      const warn = limit && used >= limit * 0.8;
      return `<div class="usage-row">
        <span class="usage-name">${esc(JOBSPY_SITES[site] || site)}</span>
        <span class="usage-bar ${warn ? "is-warn" : ""}" role="img" aria-label="${used} sur ${limit || "illimité"}"><span style="width:${ratio}%"></span></span>
        <span class="usage-count">${num(used)} / ${limit ? num(limit) : "∞"}</span>
      </div>`;
    });
  if (!rows.length) return "";
  return `<div class="subhead" style="margin-top:12px">Plafond quotidien (aujourd'hui)</div><div class="usage-list">${rows.join("")}</div>
    <span class="hint">Protège votre adresse IP : la collecte s'arrête au plafond. Modifiable dans <a class="link-btn" href="#/reglages/collecte">Réglages → Collecte</a>.</span>`;
}

function jobspyFields(item) {
  const sites = Object.keys(JOBSPY_SITES);
  const preferred = new Set(item?.sites || ["indeed", "hellowork", "linkedin"]);
  let status;
  if (!item?.installed) {
    status = `<div class="result-banner">${icon("alert")}<div><strong>Bibliothèque non installée.</strong> Lancez <span class="mono">uv sync --extra boards</span> puis relancez ApplyFlow.</div></div>`;
  } else if (!item.enabled) {
    status = `<div class="result-banner">${icon("alert")}<div>
      <strong>Désactivé par défaut.</strong> Ces sites encadrent ou interdisent l'automatisation : usage personnel, volume faible, à vos risques (blocage de votre adresse IP possible). Aucun CAPTCHA n'est contourné.
      <div style="margin-top:8px"><button class="btn btn--secondary btn--sm" type="button" data-enable-jobspy>${icon("lock")} Je comprends, activer</button></div>
    </div></div>`;
  } else {
    status = `<div class="result-banner">${icon("checkCircle")}<div><strong>Activé.</strong> Requêtes séquentielles avec pauses ; arrêt immédiat sur un blocage (403/429).</div></div>`;
  }
  return `${status}
    <div class="field">
      <label>Sites à interroger</label>
      <div class="site-picks">
        ${sites
          .map(
            (site) => `<label><input type="checkbox" name="jobspy_site" value="${site}" ${preferred.has(site) ? "checked" : ""} /> ${esc(JOBSPY_SITES[site])}</label>`,
          )
          .join("")}
      </div>
      <span class="hint">Au moins un mot-clé est obligatoire. « Offres maximum » est réparti entre les sites choisis, sous le plafond quotidien.</span>
    </div>
    ${usageList(item?.daily_usage, sites)}`;
}

function sourceFields(kind, catalog) {
  const item = catalog.find((source) => source.kind === kind);
  const note = item?.notes || "";
  if (kind === "jobspy") return jobspyFields(item);
  if (kind === "ats") {
    return `${item?.installed ? "" : `<div class="result-banner">${icon("alert")}<div><strong>Bibliothèque non installée.</strong> Lancez <span class="mono">uv sync --extra boards</span>.</div></div>`}
    <div class="field">
      <label for="source-ats">Entreprises <span class="opt">une par ligne : ats:identifiant</span></label>
      <textarea class="textarea" id="source-ats" name="ats_companies" placeholder="greenhouse:datadog&#10;lever:qonto&#10;ashby:alan" required>${esc((searchDefaults.ats_companies || []).join("\n"))}</textarea>
      <span class="hint">ATS pris en charge : greenhouse, lever, ashby, smartrecruiters, workday, successfactors, workable, recruitee, personio, teamtailor. ${esc(note)}</span>
    </div>`;
  }
  if (kind === "json_file") {
    return `<div class="field">
      <label for="source-path">Chemin du fichier JSON</label>
      <input class="input" id="source-path" name="source_path" placeholder="data/offres.json" required />
      <span class="hint">${esc(note)} Chemin résolu depuis le dossier de lancement.</span>
    </div>`;
  }
  if (kind === "rss") {
    return `<div class="field">
      <label for="source-feeds">Flux RSS / Atom <span class="opt">une URL par ligne</span></label>
      <textarea class="textarea" id="source-feeds" name="source_feeds" placeholder="https://exemple.fr/jobs.rss" required></textarea>
      <span class="hint">${esc(note)}</span>
    </div>`;
  }
  if (kind === "greenhouse") {
    return `<div class="field">
      <label for="source-board">Board token Greenhouse</label>
      <input class="input" id="source-board" name="board_token" placeholder="acme" required />
      <span class="hint">${esc(note)}</span>
    </div>`;
  }
  if (kind === "lever") {
    return `<div class="field">
      <label for="source-company">Identifiant d'entreprise Lever</label>
      <input class="input" id="source-company" name="company" placeholder="acme" required />
      <span class="hint">${esc(note)}</span>
    </div>`;
  }
  if (kind === "adzuna") {
    const configured = catalog.find((source) => source.kind === "adzuna")?.configured;
    return `<div class="result-banner">
      ${icon(configured ? "checkCircle" : "alert")}
      <div>
        <strong>${configured ? "Clé Adzuna enregistrée." : "Clé Adzuna requise."}</strong>
        ${configured
          ? " Indiquez des mots-clés ou une localisation : la recherche passe par l'API officielle."
          : ` Ajoutez votre <span class="mono">app_id</span> et <span class="mono">app_key</span> dans <a class="link-btn" href="#/reglages/collecte">Réglages → Collecte</a>, puis revenez ici.`}
      </div>
    </div>`;
  }
  return `<div class="field">
    <label for="source-url">URL de l'annonce</label>
    <input class="input" id="source-url" name="source_url" type="url" placeholder="https://…" required />
    <span class="hint">${esc(note)} Requête unique, déclenchée par vous.</span>
  </div>`;
}

function sourceConfig(form, kind) {
  if (kind === "json_file") return { path: String(form.elements.source_path?.value || "").trim() };
  if (kind === "rss") return { feeds: splitList(form.elements.source_feeds?.value || "") };
  if (kind === "greenhouse") return { board_token: String(form.elements.board_token?.value || "").trim() };
  if (kind === "lever") return { company: String(form.elements.company?.value || "").trim() };
  if (kind === "adzuna") return {};
  if (kind === "jobspy") {
    const sites = [...form.querySelectorAll("input[name=jobspy_site]:checked")].map((box) => box.value);
    return { sites };
  }
  if (kind === "ats") return { companies: splitList(form.elements.ats_companies?.value || "") };
  return { url: String(form.elements.source_url?.value || "").trim() };
}

function validateSource(form, kind, catalog) {
  if (kind === "adzuna") {
    const configured = catalog.find((source) => source.kind === "adzuna")?.configured;
    if (!configured) return "Ajoutez d'abord votre clé Adzuna dans Réglages → Collecte.";
    if (
      !splitList(form.elements.keywords?.value || "").length &&
      !readLocations(form.querySelector("[data-loc-picker]")).values.length
    ) {
      return "Indiquez au moins un mot-clé ou une localisation pour Adzuna.";
    }
  }
  if (kind === "jobspy") {
    const item = catalog.find((source) => source.kind === "jobspy");
    if (!item?.installed) return "Installez d'abord la bibliothèque : uv sync --extra boards.";
    if (!item.enabled) return "JobSpy est désactivé : cliquez sur « Je comprends, activer » pour l'autoriser.";
    if (!form.querySelector("input[name=jobspy_site]:checked")) return "Choisissez au moins un site.";
    if (!splitList(form.elements.keywords?.value || "").length) return "Indiquez au moins un mot-clé pour les job boards.";
  }
  if (kind === "ats") {
    const lines = splitList(form.elements.ats_companies?.value || "");
    if (!lines.length) return "Indiquez au moins une entreprise, par exemple greenhouse:datadog.";
    if (lines.some((line) => !/^[a-z]+:\S+$/i.test(line))) return "Format attendu : ats:identifiant (ex. lever:qonto).";
  }
  if (kind === "json_file" && !form.elements.source_path?.value.trim()) return "Indiquez le chemin du fichier JSON.";
  if (kind === "rss" && !splitList(form.elements.source_feeds?.value || "").length) return "Ajoutez au moins une URL de flux RSS.";
  if (kind === "greenhouse" && !form.elements.board_token?.value.trim()) return "Indiquez le board token Greenhouse.";
  if (kind === "lever" && !form.elements.company?.value.trim()) return "Indiquez l'identifiant d'entreprise Lever.";
  if (kind === "manual_url" && !form.elements.source_url?.value.trim()) return "Indiquez l'URL de l'annonce.";
  return "";
}

function countryOptions(countries, selected = "") {
  const options = (countries || [])
    .map(
      (entry) => `<option value="${esc(entry.country)}" ${entry.country === selected ? "selected" : ""}>${esc(countryName(entry.country))} (${num(entry.count)})</option>`,
    )
    .join("");
  return `<option value="">Tous les pays</option>${options}`;
}

function statsTable(stats) {
  const blocks = Object.entries(stats || {}).map(([label, entry]) => {
    const rows = Object.entries(entry.details || {}).map(([name, detail]) => {
      const total = detail.total !== undefined ? ` sur ${num(detail.total)}` : "";
      const errors = (detail.errors || []).slice(0, 1).map((error) => esc(error)).join("");
      return `<tr><td>${esc(JOBSPY_SITES[name] || name)}</td><td>${num(detail.jobs)}${total}</td><td>${num(detail.seconds)} s</td><td>${errors || "—"}</td></tr>`;
    });
    if (!rows.length) return "";
    return `<div class="subhead" style="margin-top:10px">${esc(label)}</div>
      <table class="stats-table"><thead><tr><th>Source</th><th>Offres</th><th>Durée</th><th>Erreur</th></tr></thead><tbody>${rows.join("")}</tbody></table>
      ${usageList(entry.daily_usage, Object.keys(entry.details || {}))}`;
  });
  return blocks.join("");
}

function countLabel(count) {
  return `${num(count)} offre${count > 1 ? "s" : ""}`;
}

function jobRow(job) {
  const skills = uniqueSkills(job.skills).slice(0, 4);
  return `<tr class="row-link" tabindex="0" data-job-id="${esc(job.id)}">
    <td class="job-main">
      <div class="cell-title">${esc(job.title || "Sans titre")}</div>
      <div class="cell-sub">${esc(job.company || "Entreprise inconnue")}</div>
      ${skills.length ? `<div class="row-tags">${skills.map((skill) => `<span class="tag">${esc(skill)}</span>`).join("")}</div>` : ""}
    </td>
    <td>${esc(job.location || "—")}${
      job.country || jobRemote(job)
        ? `<div class="cell-sub">${esc([job.country ? countryName(job.country) : "", jobRemote(job)].filter(Boolean).join(" · "))}</div>`
        : ""
    }</td>
    <td>${esc(jobContract(job))}</td>
    <td>${esc(jobSeniority(job))}</td>
    <td><span class="chip chip--tag">${esc(jobSource(job))}</span></td>
    <td class="cell-date">${esc(formatDate(job.collected_at))}</td>
    <td><span class="arrow-link" aria-hidden="true">${icon("arrowRight")}</span></td>
  </tr>`;
}

function jobsTable(jobs) {
  if (!jobs.length) {
    return emptyState({
      iconName: "discovery",
      title: "Aucune offre dans la bibliothèque",
      text: "Choisissez une source ci-dessus, lancez une collecte, puis retrouvez ici les annonces analysables.",
    });
  }
  return `<div class="table-wrap">
    <table class="table">
      <thead><tr>
        <th>Poste</th><th>Lieu</th><th>Contrat</th><th>Séniorité</th><th>Source</th><th>Ajoutée</th><th></th>
      </tr></thead>
      <tbody>${jobs.map(jobRow).join("")}</tbody>
    </table>
  </div>`;
}

async function openJob(jobId) {
  const job = await api.job(jobId);
  const url = safeUrl(job.apply_url || job.url);
  openModal({
    drawer: true,
    title: job.title || "Offre",
    subtitle: `${job.company || "Entreprise inconnue"} · ${job.location || "Localisation inconnue"}`,
    body: `
      <div class="tag-list" style="margin-bottom:14px">
        ${jobRemote(job) ? `<span class="chip chip--sage">${esc(jobRemote(job))}</span>` : ""}
        ${job.contract_type ? `<span class="chip chip--tag">${esc(jobContract(job))}</span>` : ""}
        ${job.seniority ? `<span class="chip chip--tag">${esc(jobSeniority(job))}</span>` : ""}
        ${job.source ? `<span class="chip chip--tag">${esc(jobSource(job))}</span>` : ""}
      </div>
      <div class="meta-grid">
        <div class="meta-item"><div class="stat-label">Publiée</div><div class="meta-value">${esc(formatDate(job.published_at))}</div></div>
        <div class="meta-item"><div class="stat-label">Collectée</div><div class="meta-value">${esc(formatDate(job.collected_at))}</div></div>
        <div class="meta-item"><div class="stat-label">Salaire</div><div class="meta-value">${job.salary_min || job.salary_max ? `${num(job.salary_min)} – ${num(job.salary_max)} ${esc(job.salary_currency || "EUR")}` : "Non précisé"}</div></div>
        <div class="meta-item"><div class="stat-label">Identifiant source</div><div class="meta-value mono">${esc(job.external_id || "—")}</div></div>
      </div>
      ${uniqueSkills(job.skills).length ? `<div class="subhead">Compétences demandées</div><div class="tag-list">${uniqueSkills(job.skills).map((skill) => `<span class="tag">${esc(skill)}</span>`).join("")}</div>` : ""}
      <div class="subhead">Description</div>
      <div class="small" style="white-space:pre-line;line-height:1.65;color:var(--ink-2)">${esc(job.description || "Aucune description fournie par la source.")}</div>`,
    footer: `<span class="foot-left">${icon("lock")} Offre en lecture seule</span>
      ${url !== "#" ? `<a class="btn btn--secondary" href="${esc(url)}" target="_blank" rel="noreferrer noopener">${icon("external")} Ouvrir l'annonce</a>` : ""}
      <button class="btn btn--ghost" type="button" data-close>Fermer</button>`,
  });
}

export async function render(container, ctx) {
  const [catalog, jobs, countries, settings] = await Promise.all([
    api.sources(),
    api.jobs({ limit: 100 }, ctx.signal),
    api.jobCountries(ctx.signal).catch(() => []),
    api.settings(ctx.signal).catch(() => ({})),
  ]);
  // Recherche par défaut (Réglages → Collecte) : prérempli, toujours modifiable avant le lancement.
  searchDefaults = settings.search || {};
  if (ctx.signal.aborted) return;

  const available = catalog.filter((source) => source.available && source.kind !== "fixture");
  let selectedKind = available.find((source) => source.kind === "manual_url")?.kind || available[0]?.kind || "";
  let currentJobs = jobs;
  let keyword = "";
  let sourceFilter = "";
  let countryFilter = "";
  let resultHtml = "";

  container.innerHTML = `
    <header class="page-head">
      <div>
        <div class="eyebrow">Sourcing</div>
        <h1 class="page-title">Découverte</h1>
        <p class="page-sub">Des sources lisibles, des requêtes explicites. ApplyFlow collecte ce que vous demandez, avec des pauses, des plafonds quotidiens et sans contourner aucune protection.</p>
      </div>
      <div class="head-actions">
        <a class="btn btn--secondary" href="#/campagnes?new=1">${icon("campaigns")} Lancer une campagne</a>
      </div>
    </header>

    <div class="discovery-layout">
      <section class="panel panel--flush" aria-labelledby="collect-heading">
        <div class="panel-head panel-head--bordered">
          <div>
            <h2 class="panel-title" id="collect-heading">Nouvelle collecte</h2>
            <p class="panel-sub">Une source, une requête, un lancement explicite.</p>
          </div>
          <span class="chip chip--tag">${available.length} source${available.length > 1 ? "s" : ""} disponible${available.length > 1 ? "s" : ""}</span>
        </div>
        <form id="discovery-form" class="collect-form" novalidate>
          <div class="collect-step">
            <div class="collect-step-head">
              <span class="step-index">1</span>
              <div><strong>Source</strong><small>D'où viennent les annonces.</small></div>
            </div>
            <div class="source-grid source-grid--compact" id="source-grid">
              ${available
                .map(
                  (source) => `<button class="source-card ${source.kind === selectedKind ? "is-selected" : ""}" type="button" data-source="${esc(source.kind)}" aria-pressed="${source.kind === selectedKind}">
                    <span class="source-icon">${icon(SOURCE_ICONS[source.kind] || "discovery")}</span>
                    <span class="source-name">${esc(source.label)}</span>
                    <span class="source-note">${esc(source.notes)}</span>
                  </button>`,
                )
                .join("")}
            </div>
          </div>

          <div class="collect-step">
            <div class="collect-step-head">
              <span class="step-index">2</span>
              <div><strong>Recherche</strong><small>Ce que vous cherchez et combien d'offres garder.</small></div>
            </div>
            <input type="hidden" name="source_kind" value="${esc(selectedKind)}" />
            <div id="source-fields" class="collect-fields">${sourceFields(selectedKind, catalog)}</div>
            <div class="form-grid form-grid--three collect-query">
              <div class="field">
                <label for="discovery-keywords">Mots-clés</label>
                <input class="input" id="discovery-keywords" name="keywords" placeholder="data engineer, python" value="${esc((searchDefaults.keywords || []).join(", "))}" />
              </div>
              <div class="field">
                <label for="discovery-locations">Localisations</label>
                ${locationPickerHtml({ id: "discovery-locations", values: searchDefaults.locations || [] })}
              </div>
              <div class="field">
                <label for="discovery-limit">Offres maximum</label>
                <input class="input" id="discovery-limit" name="limit" type="number" min="1" max="5000" value="${esc(searchDefaults.limit ?? 100)}" />
              </div>
            </div>
          </div>

          <div class="collect-step collect-step--action">
            <div class="collect-step-head">
              <span class="step-index">3</span>
              <div><strong>Lancer</strong><small>Une requête unique, séquentielle et sans candidature.</small></div>
            </div>
            <div class="collect-submit">
              <p class="hint">${icon("lock")} Aucune offre n'est modifiée chez la source. Aucun e-mail n'est envoyé.</p>
              <button class="btn btn--primary" type="submit" data-collect>${icon("discovery")} Lancer la collecte</button>
            </div>
          </div>

          <div id="discovery-result">${resultHtml}</div>
        </form>
      </section>

    </div>

    <section class="panel panel--flush" style="margin-top:16px" aria-labelledby="jobs-heading">
      <div class="panel-head panel-head--bordered">
        <div>
          <h2 class="panel-title" id="jobs-heading">Bibliothèque d'offres</h2>
          <p class="panel-sub" id="jobs-count">${countLabel(currentJobs.length)} affichée${currentJobs.length > 1 ? "s" : ""}</p>
        </div>
        <div class="toolbar">
          <label class="search-field">${icon("search")}<span class="sr-only">Filtrer les offres</span><input class="input" id="job-search" type="search" placeholder="Filtrer par mot-clé…" /></label>
          <select class="select" id="job-country" aria-label="Filtrer par pays">
            ${countryOptions(countries)}
          </select>
          <select class="select" id="job-source" aria-label="Filtrer par source">
            <option value="">Toutes les sources</option>
            ${available.map((source) => `<option value="${esc(source.kind)}">${esc(source.label)}</option>`).join("")}
          </select>
        </div>
      </div>
      <div id="jobs-table">${jobsTable(currentJobs)}</div>
    </section>`;

  mountLocationPickers(container);
  const form = document.getElementById("discovery-form");
  const sourceGrid = document.getElementById("source-grid");
  const fields = document.getElementById("source-fields");
  const resultBox = document.getElementById("discovery-result");
  const jobsBox = document.getElementById("jobs-table");
  const countBox = document.getElementById("jobs-count");
  const submit = form.querySelector("[data-collect]");
  const emptyResults = jobsTable([]);

  sourceGrid.addEventListener("click", (event) => {
    const card = event.target.closest("[data-source]");
    if (!card) return;
    selectedKind = card.dataset.source;
    form.elements.source_kind.value = selectedKind;
    sourceGrid.querySelectorAll(".source-card").forEach((item) => {
      const selected = item === card;
      item.classList.toggle("is-selected", selected);
      item.setAttribute("aria-pressed", String(selected));
    });
    fields.innerHTML = sourceFields(selectedKind, catalog);
  });

  const loadJobs = async () => {
    try {
      currentJobs = await api.jobs(
        { keyword, source: sourceFilter, country: countryFilter, limit: 100 },
        ctx.signal,
      );
      jobsBox.innerHTML = currentJobs.length ? jobsTable(currentJobs) : emptyResults;
      countBox.textContent = `${countLabel(currentJobs.length)} affichée${currentJobs.length > 1 ? "s" : ""}`;
    } catch (error) {
      if (error.name !== "AbortError") toast(errorMessage(error), { title: "Filtre impossible", type: "error" });
    }
  };

  document.getElementById("job-search").addEventListener(
    "input",
    debounce((event) => {
      keyword = event.target.value.trim();
      loadJobs();
    }, 280),
  );
  document.getElementById("job-source").addEventListener("change", (event) => {
    sourceFilter = event.target.value;
    loadJobs();
  });
  const countrySelect = document.getElementById("job-country");
  countrySelect.addEventListener("change", (event) => {
    countryFilter = event.target.value;
    loadJobs();
  });
  const refreshCountries = async () => {
    try {
      countrySelect.innerHTML = countryOptions(await api.jobCountries(ctx.signal), countryFilter);
    } catch (error) {
      if (error.name !== "AbortError") countrySelect.innerHTML = countryOptions([], countryFilter);
    }
  };

  // Activation explicite de JobSpy : jamais automatique, toujours après confirmation.
  fields.addEventListener("click", async (event) => {
    if (!event.target.closest("[data-enable-jobspy]")) return;
    const confirmed = await confirmDialog({
      title: "Activer la collecte sur les job boards ?",
      message:
        "LinkedIn, Indeed, Glassdoor et HelloWork encadrent ou interdisent l'automatisation dans leurs conditions. L'usage reste personnel, à faible volume et à vos risques : votre adresse IP peut être bloquée. ApplyFlow limite le débit, applique un plafond quotidien, s'arrête sur un blocage et ne contourne aucun CAPTCHA.",
      confirmLabel: "J'ai compris, activer",
    });
    if (!confirmed) return;
    try {
      await api.saveSettings({ boards: { jobspy_enabled: true } });
      const item = catalog.find((source) => source.kind === "jobspy");
      if (item) item.enabled = true;
      fields.innerHTML = sourceFields("jobspy", catalog);
      toast("Collecte job boards activée.", { title: "Réglage enregistré" });
    } catch (error) {
      toast(errorMessage(error), { title: "Activation impossible", type: "error" });
    }
  });

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    clearFieldError(form);
    const locationCheck = readLocations(form.querySelector("[data-loc-picker]"));
    if (locationCheck.error) {
      fieldError(form, locationCheck.error);
      form.querySelector("[data-country-input]").focus();
      return;
    }
    const validation = validateSource(form, selectedKind, catalog);
    if (validation) {
      fieldError(form, validation);
      return;
    }
    const payload = {
      source: { kind: selectedKind, config: sourceConfig(form, selectedKind) },
      keywords: splitList(form.elements.keywords.value),
      locations: locationCheck.values,
      limit: Number(form.elements.limit.value) || 200,
    };
    setLoading(submit, true, "Collecte…");
    resultBox.innerHTML = "";
    try {
      await followTask(await api.startDiscovery(payload));
    } catch (error) {
      setLoading(submit, false);
      fieldError(form, errorMessage(error));
      toast(errorMessage(error), { title: "Collecte impossible", type: "error" });
    }
  });

  // Suivi d'une collecte en arrière-plan : progression, annulation, reprise après navigation.
  const progressHtml = (task) => {
    const { done = 0, total = 0, label = "", collected = 0 } = task.progress || {};
    const ratio = total ? Math.min(100, Math.round((done / total) * 100)) : 0;
    return `<div class="result-banner" role="status" aria-live="polite">
      ${icon("clock")}
      <div style="flex:1">
        <strong>${task.cancel_requested ? "Annulation en cours…" : "Collecte en cours…"}</strong>
        <div class="usage-row" style="grid-template-columns:1fr auto;margin-top:8px">
          <span class="usage-bar" role="progressbar" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${ratio}"><span style="width:${ratio}%"></span></span>
          <span class="usage-count">${num(done)} / ${num(total) || "?"} étapes</span>
        </div>
        <div class="small muted" style="margin-top:6px">${esc(label)} · ${num(collected)} offre${collected > 1 ? "s" : ""} trouvée${collected > 1 ? "s" : ""}</div>
        <div style="margin-top:8px"><button class="btn btn--secondary btn--sm" type="button" data-cancel-task ${task.cancel_requested ? "disabled" : ""}>${icon("stop")} Annuler</button></div>
      </div>
    </div>`;
  };

  const taskResultHtml = (task) => {
    if (task.status === "error") {
      return `<div class="result-banner">${icon("alert")}<div><strong>La collecte a échoué.</strong> ${esc(task.error || "Erreur inconnue.")}</div></div>`;
    }
    const result = task.result || {};
    const errors = [...new Set([...(result.errors || []), ...(result.source_errors || [])])];
    const created = Number(result.created) || 0;
    const duplicates = Number(result.duplicates) || 0;
    const cancelled = task.status === "cancelled";
    const headline = created
      ? `${num(created)} nouvelle${created > 1 ? "s" : ""} offre${created > 1 ? "s" : ""}`
      : "Aucune nouvelle offre";
    return `<div class="result-banner">
      ${icon(cancelled ? "alert" : created ? "checkCircle" : "info")}
      <div>
        <strong>${cancelled ? "Collecte annulée : " : ""}${headline}, ${num(duplicates)} doublon${duplicates > 1 ? "s" : ""}.</strong>
        ${cancelled ? `<div class="small muted">Les offres déjà trouvées ont été enregistrées.</div>` : ""}
        ${errors.length ? `<ul>${errors.slice(0, 5).map((error) => `<li>${esc(error)}</li>`).join("")}</ul>` : ""}
        ${statsTable(result.stats)}
      </div>
    </div>`;
  };

  const finishTask = async (task) => {
    resultBox.innerHTML = taskResultHtml(task);
    setLoading(submit, false);
    const created = Number(task.result?.created) || 0;
    if (task.status === "error") {
      toast(task.error || "La collecte a échoué.", { title: "Collecte impossible", type: "error" });
    } else {
      toast(
        created
          ? `${num(created)} offre${created > 1 ? "s" : ""} ajoutée${created > 1 ? "s" : ""} à la bibliothèque.`
          : "La collecte n'a rien ajouté : toutes les offres étaient déjà connues.",
        { title: task.status === "cancelled" ? "Collecte annulée" : "Collecte terminée" },
      );
    }
    await loadJobs();
    await refreshCountries();
    const fresh = await api.sources().catch(() => null);
    const jobspy = fresh?.find((source) => source.kind === "jobspy");
    const known = catalog.find((source) => source.kind === "jobspy");
    if (jobspy && known) known.daily_usage = jobspy.daily_usage;
  };

  async function followTask(initial) {
    let task = initial;
    resultBox.dataset.taskId = task.id;
    setLoading(submit, true, "Collecte en cours…");
    resultBox.innerHTML = progressHtml(task);
    while (task.status === "running") {
      await new Promise((resolve) => setTimeout(resolve, 1000));
      if (ctx.signal.aborted) return; // l'utilisateur a quitté la page : la collecte continue côté serveur
      try {
        task = await api.discoveryTask(task.id, ctx.signal);
      } catch (error) {
        if (error.name === "AbortError") return;
        setLoading(submit, false);
        fieldError(form, errorMessage(error));
        return;
      }
      if (task.status === "running") resultBox.innerHTML = progressHtml(task);
    }
    await finishTask(task);
  }

  resultBox.addEventListener("click", async (event) => {
    if (!event.target.closest("[data-cancel-task]")) return;
    const taskId = resultBox.dataset.taskId;
    if (!taskId) return;
    event.target.closest("[data-cancel-task]").disabled = true;
    try {
      await api.cancelDiscovery(taskId);
    } catch (error) {
      toast(errorMessage(error), { title: "Annulation impossible", type: "error" });
    }
  });

  // Reprise : une collecte lancée avant de quitter l'écran continue côté serveur.
  api
    .activeDiscovery(ctx.signal)
    .then((active) => {
      if (active && !ctx.signal.aborted) followTask(active);
    })
    .catch(() => {});

  const openFromRow = (row) => {
    openJob(row.dataset.jobId).catch((error) =>
      toast(errorMessage(error), { title: "Offre indisponible", type: "error" }),
    );
  };
  jobsBox.addEventListener("click", (event) => {
    const row = event.target.closest("[data-job-id]");
    if (row) openFromRow(row);
  });
  jobsBox.addEventListener("keydown", (event) => {
    if (event.key !== "Enter" && event.key !== " ") return;
    const row = event.target.closest("[data-job-id]");
    if (row) {
      event.preventDefault();
      openFromRow(row);
    }
  });
}
