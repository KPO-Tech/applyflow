import { api } from "../api.js";
import { icon } from "../icons.js";
import {
  emptyState,
  errorMessage,
  esc,
  fieldError,
  clearFieldError,
  initials,
  LEVELS,
  openModal,
  setLoading,
  splitList,
  toast,
} from "../ui.js";
import { notifyChanged } from "../store.js";
import { locationPickerHtml, mountLocationPickers, readLocations } from "../locations.js";

const REMOTE_OPTIONS = [
  ["remote", "Télétravail"],
  ["hybrid", "Hybride"],
  ["onsite", "Sur site"],
];

function checked(values, value) {
  return Array.isArray(values) && values.includes(value) ? "checked" : "";
}

function value(profile, key, fallback = "") {
  const item = profile?.[key];
  if (item === null || item === undefined) return fallback;
  return item;
}

function activeCv(profile) {
  return (profile.resumes || []).find((resume) => resume.is_active) || null;
}

// Les dates SQLite arrivent en « AAAA-MM-JJ hh:mm:ss » : on les formate sans passer par
// Date(), dont l'interprétation de ce format varie selon les navigateurs.
function cvDate(resume) {
  const [year, month, day] = String(resume?.uploaded_at || "").slice(0, 10).split("-");
  return year && month && day ? `${day}/${month}/${year}` : "date inconnue";
}

function cvSize(resume) {
  const size = Number(resume?.size_bytes || 0);
  return size > 0 ? `${Math.round(size / 1024)} Ko` : "taille inconnue";
}

function cvState(profile) {
  const cv = activeCv(profile);
  if (!cv) return `<span class="cv-state">${icon("upload")} Aucun CV actif</span>`;
  const href = `/profiles/${encodeURIComponent(profile.id)}/resumes/${encodeURIComponent(cv.id)}/file`;
  const title = `${cv.filename} — importé le ${cvDate(cv)} (${cvSize(cv)}). Cliquer pour prévisualiser.`;
  return `<a class="cv-state is-ready" href="${href}" target="_blank" rel="noopener" title="${esc(title)}">${icon("file")} ${esc(cv.filename)}</a>`;
}

function profileCard(profile) {
  const skills = profile.technical_skills || [];
  const shown = skills.slice(0, 4);
  const extra = Math.max(0, skills.length - shown.length);
  return `<article class="profile-card">
    <div class="profile-head">
      <div class="avatar avatar--lg" aria-hidden="true">${esc(initials(profile.name))}</div>
      <div class="profile-identity">
        <div class="profile-name"><span>${esc(profile.name)}</span></div>
        <div class="profile-title">${esc((profile.target_titles || []).join(" · ") || "Aucun intitulé cible")}</div>
      </div>
      <span class="chip ${profile.active ? "chip--sage" : "chip--plain"}">${profile.active ? "Actif" : "Inactif"}</span>
    </div>
    <div class="profile-tags">
      ${shown.map((skill) => `<span class="tag">${esc(skill)}</span>`).join("")}
      ${extra ? `<span class="tag tag--more">+${extra}</span>` : ""}
      ${!shown.length ? `<span class="tag tag--more">Compétences à compléter</span>` : ""}
    </div>
    <div class="profile-stats">
      <div>
        <div class="stat-label">Niveau</div>
        <div class="stat-value">${esc(LEVELS[profile.experience_level] || profile.experience_level || "—")}${profile.years_experience ? ` · ${esc(profile.years_experience)} ans` : ""}</div>
      </div>
      <div>
        <div class="stat-label">Mobilité</div>
        <div class="stat-value">${esc((profile.locations || []).slice(0, 2).join(" · ") || "Non précisée")}</div>
      </div>
    </div>
    <div class="profile-foot">
      ${cvState(profile)}
      <button class="btn btn--ghost btn--sm" type="button" data-profile-cv="${esc(profile.id)}">${icon("upload")} CV</button>
      <button class="btn btn--secondary btn--sm" type="button" data-profile-edit="${esc(profile.id)}">${icon("settings")} Modifier</button>
      <button class="btn btn--ghost btn--sm" type="button" data-profile-toggle="${esc(profile.id)}" data-active="${profile.active ? "1" : "0"}">${profile.active ? "Désactiver" : "Réactiver"}</button>
    </div>
  </article>`;
}

const MAX_LINKS = 10;

// Mêmes libellés que le serveur (applyflow/contracts.py), vérifiés par un test.
const CONTRACT_OPTIONS = ["CDI", "CDD", "Stage", "Alternance", "Freelance", "Intérim", "Temps partiel", "VIE"];

// Cases à cocher : les types connus, plus ceux d'un ancien profil qui n'y figureraient pas.
function contractChoices(selected) {
  const known = new Set(CONTRACT_OPTIONS.map((label) => label.toLowerCase()));
  const chosen = new Set(selected.map((label) => String(label).toLowerCase()));
  const extra = selected.filter((label) => !known.has(String(label).toLowerCase()));
  return [
    ...CONTRACT_OPTIONS.map((label) => [label, chosen.has(label.toLowerCase())]),
    ...extra.map((label) => [label, true]),
  ];
}

function linkRow(link = {}) {
  return `<div class="link-row" data-link-row>
    <input class="input" name="link_label" value="${esc(link.label || "")}" placeholder="Nom (ex. Mon entreprise)" aria-label="Nom du lien" />
    <input class="input" name="link_url" value="${esc(link.url || "")}" placeholder="https://votre-site.com" aria-label="Adresse du lien" autocomplete="url" />
    <button class="icon-btn" type="button" data-remove-link aria-label="Retirer ce lien">${icon("close")}</button>
  </div>`;
}

function profileFormFields(profile) {
  return `
    <div class="form-section">
      <div class="form-section-title">Identité candidat</div>
      <div class="form-grid">
        <div class="field">
          <label for="pf-full-name">Nom complet</label>
          <input class="input" id="pf-full-name" name="full_name" value="${esc(value(profile, "full_name"))}" autocomplete="name" />
        </div>
        <div class="field">
          <label for="pf-email">E-mail</label>
          <input class="input" id="pf-email" name="email" type="email" value="${esc(value(profile, "email"))}" autocomplete="email" />
        </div>
        <div class="field">
          <label for="pf-phone">Téléphone</label>
          <input class="input" id="pf-phone" name="phone" value="${esc(value(profile, "phone"))}" autocomplete="tel" />
        </div>
        <div class="field">
          <label for="pf-city">Ville</label>
          <input class="input" id="pf-city" name="city" value="${esc(value(profile, "city"))}" autocomplete="address-level2" />
        </div>
        <div class="field">
          <label for="pf-linkedin">LinkedIn</label>
          <input class="input" id="pf-linkedin" name="linkedin_url" value="${esc(value(profile, "linkedin_url"))}" placeholder="https://…" />
        </div>
        <div class="field">
          <label for="pf-github">GitHub</label>
          <input class="input" id="pf-github" name="github_url" value="${esc(value(profile, "github_url"))}" placeholder="https://…" />
        </div>
        <div class="field span-2">
          <label for="pf-website">Portfolio / site personnel</label>
          <input class="input" id="pf-website" name="website" value="${esc(value(profile, "website"))}" placeholder="https://votre-portfolio.vercel.app" autocomplete="url" />
          <span class="hint">Écrit tel quel dans les champs « portfolio » ou « site web » des formulaires. « https:// » est ajouté si vous l'oubliez.</span>
        </div>
        <div class="field span-2">
          <label>Autres sites ou liens <span class="opt">projet, entreprise, publication…</span></label>
          <div id="pf-links" class="link-list">${(profile?.other_links || []).map(linkRow).join("")}</div>
          <div><button class="btn btn--ghost btn--sm" type="button" data-add-link>${icon("plus")} Ajouter un site</button></div>
          <span class="hint">Jusqu'à ${MAX_LINKS} liens. Le premier sert à remplir un champ « autre site » ou « lien supplémentaire » quand un formulaire en demande un.</span>
        </div>
      </div>
    </div>

    <div class="form-section">
      <div class="form-section-title">Positionnement</div>
      <div class="form-grid">
        <div class="field span-2">
          <label for="pf-name">Nom du profil <span class="opt">obligatoire</span></label>
          <input class="input" id="pf-name" name="name" required value="${esc(value(profile, "name"))}" placeholder="Ex. Data Engineer" />
          <span class="hint">Le nom interne utilisé pour reconnaître ce profil dans les campagnes.</span>
        </div>
        <div class="field span-2">
          <label for="pf-titles">Intitulés visés <span class="opt">obligatoire, séparés par des virgules</span></label>
          <input class="input" id="pf-titles" name="target_titles" required value="${esc((profile?.target_titles || []).join(", "))}" placeholder="Data Engineer, Analytics Engineer" />
        </div>
        <div class="field">
          <label for="pf-level">Niveau</label>
          <select class="select" id="pf-level" name="experience_level">
            ${Object.entries(LEVELS)
              .map(
                ([key, label]) =>
                  `<option value="${key}" ${value(profile, "experience_level", "junior") === key ? "selected" : ""}>${esc(label)}</option>`,
              )
              .join("")}
          </select>
        </div>
        <div class="field">
          <label for="pf-years">Années d'expérience</label>
          <input class="input" id="pf-years" name="years_experience" type="number" min="0" max="50" step="0.5" value="${esc(value(profile, "years_experience", 0))}" />
        </div>
        <div class="field span-2">
          <label for="pf-auth">Autorisation de travail déclarée</label>
          <input class="input" id="pf-auth" name="work_authorization" value="${esc(value(profile, "work_authorization"))}" placeholder="Ex. France / Union européenne" />
          <span class="hint">Cette valeur n'est jamais inventée : elle est reprise telle quelle dans les formulaires.</span>
        </div>
      </div>
    </div>

    <div class="form-section">
      <div class="form-section-title">Critères de recherche</div>
      <div class="form-grid">
        <div class="field span-2">
          <label for="pf-locations">Pays et villes acceptés</label>
          ${locationPickerHtml({ id: "pf-locations", values: profile?.locations || ["France"] })}
          <span class="hint">Plusieurs pays possibles, pris dans la liste officielle. Un pays accepte aussi ses villes ; ajoutez des villes seulement pour restreindre.</span>
        </div>
        <div class="field span-2">
          <span class="field-label">Types de contrats acceptés <span class="opt">plusieurs choix possibles</span></span>
          <div class="check-row">
            ${contractChoices(profile?.contract_types || ["CDI"])
              .map(
                ([label, checked]) =>
                  `<label class="check"><input type="checkbox" name="contract_types" value="${esc(label)}" ${checked ? "checked" : ""} /> ${esc(label)}</label>`,
              )
              .join("")}
          </div>
          <span class="hint">Aucun choix : tous les types sont acceptés.</span>
        </div>
        <div class="field span-2">
          <span class="field-label">Télétravail</span>
          <div class="check-row">
            ${REMOTE_OPTIONS.map(
              ([key, label]) => `<label class="check"><input type="checkbox" name="remote_preferences" value="${key}" ${checked(profile?.remote_preferences, key)} /> ${esc(label)}</label>`,
            ).join("")}
          </div>
        </div>
        <div class="field">
          <label for="pf-salary-min">Salaire minimum</label>
          <input class="input" id="pf-salary-min" name="salary_min" type="number" min="0" step="1000" value="${esc(value(profile, "salary_min"))}" />
        </div>
        <div class="field">
          <label for="pf-salary-max">Salaire maximum</label>
          <input class="input" id="pf-salary-max" name="salary_max" type="number" min="0" step="1000" value="${esc(value(profile, "salary_max"))}" />
        </div>
        <div class="field">
          <label for="pf-currency">Devise</label>
          <input class="input" id="pf-currency" name="salary_currency" value="${esc(value(profile, "salary_currency", "EUR"))}" maxlength="8" />
        </div>
        <div class="field">
          <label for="pf-exclusions">Critères d'exclusion</label>
          <input class="input" id="pf-exclusions" name="exclusion_criteria" value="${esc((profile?.exclusion_criteria || []).join(", "))}" placeholder="Ex. vente, management" />
        </div>
      </div>
    </div>

    <div class="form-section">
      <div class="form-section-title">Compétences</div>
      <div class="form-grid">
        <div class="field span-2">
          <label for="pf-technical">Compétences techniques</label>
          <textarea class="textarea" id="pf-technical" name="technical_skills" placeholder="Python, SQL, dbt, Airflow…">${esc((profile?.technical_skills || []).join(", "))}</textarea>
        </div>
        <div class="field span-2">
          <label for="pf-domain">Compétences métier</label>
          <textarea class="textarea" id="pf-domain" name="domain_skills" placeholder="Finance, e-commerce, santé…">${esc((profile?.domain_skills || []).join(", "))}</textarea>
        </div>
      </div>
    </div>

    <div class="form-section">
      <div class="form-section-title">Notes internes</div>
      <div class="field">
        <label for="pf-notes">Notes <span class="opt">facultatif</span></label>
        <textarea class="textarea" id="pf-notes" name="notes" placeholder="Contexte, contraintes, préférences…">${esc(value(profile, "notes"))}</textarea>
      </div>
    </div>`;
}

function openProfileDialog(profile, ctx) {
  const editing = Boolean(profile);
  const dialog = openModal({
    title: editing ? "Modifier le profil" : "Créer un profil",
    subtitle: editing
      ? "Les modifications s'appliquent aux prochaines analyses. Les candidatures déjà préparées ne sont pas réécrites."
      : "Un profil décrit qui vous êtes et ce que vous cherchez. Il alimente le matching et le préremplissage.",
    wide: true,
    body: `<form id="profile-form" novalidate>${profileFormFields(profile)}</form>`,
    footer: `<span class="foot-left">${icon("lock")} Données locales · CV PDF uniquement</span>
      <button class="btn btn--ghost" type="button" data-close>Annuler</button>
      <button class="btn btn--primary" type="submit" form="profile-form" data-save>${icon(editing ? "checkCircle" : "plus")} ${editing ? "Enregistrer" : "Créer le profil"}</button>`,
    onMount: (element, close) => {
      const form = element.querySelector("#profile-form");
      const submit = element.querySelector("[data-save]");
      mountLocationPickers(form);
      const links = form.querySelector("#pf-links");
      const addButton = form.querySelector("[data-add-link]");
      const syncAddButton = () => {
        addButton.disabled = links.querySelectorAll("[data-link-row]").length >= MAX_LINKS;
      };
      addButton.addEventListener("click", () => {
        if (links.querySelectorAll("[data-link-row]").length >= MAX_LINKS) return;
        links.insertAdjacentHTML("beforeend", linkRow());
        links.lastElementChild.querySelector('[name="link_label"]').focus();
        syncAddButton();
      });
      links.addEventListener("click", (event) => {
        const remove = event.target.closest("[data-remove-link]");
        if (!remove) return;
        remove.closest("[data-link-row]").remove();
        syncAddButton();
      });
      syncAddButton();
      form.addEventListener("submit", async (event) => {
        event.preventDefault();
        clearFieldError(form);
        const locationCheck = readLocations(form.querySelector("[data-loc-picker]"));
        if (locationCheck.error) {
          fieldError(form, locationCheck.error);
          form.querySelector("[data-country-input]").focus();
          return;
        }
        const payload = buildProfilePayload(form, profile);
        if (!payload.name || payload.name.length < 2) {
          fieldError(form, "Le nom du profil doit contenir au moins 2 caractères.");
          form.elements.name.focus();
          return;
        }
        if (!payload.target_titles.length) {
          fieldError(form, "Ajoutez au moins un intitulé visé.");
          form.elements.target_titles.focus();
          return;
        }
        if (payload.salary_max !== null && payload.salary_min !== null && payload.salary_max < payload.salary_min) {
          fieldError(form, "Le salaire maximum doit être supérieur ou égal au salaire minimum.");
          form.elements.salary_max.focus();
          return;
        }
        setLoading(submit, true, editing ? "Enregistrement…" : "Création…");
        try {
          if (editing) await api.updateProfile(profile.id, payload);
          else await api.createProfile(payload);
          close();
          toast(editing ? "Profil mis à jour." : `Profil « ${payload.name} » créé.`, {
            title: editing ? "Modifications enregistrées" : "Profil prêt",
          });
          notifyChanged();
          ctx.refresh();
        } catch (error) {
          setLoading(submit, false);
          fieldError(form, errorMessage(error));
        }
      });
    },
  });
  return dialog;
}

function buildProfilePayload(form, profile) {
  const data = new FormData(form);
  const remote = [...form.querySelectorAll('input[name="remote_preferences"]:checked')].map(
    (input) => input.value,
  );
  const numeric = (key) => {
    const raw = String(data.get(key) ?? "").trim();
    if (!raw) return null;
    const parsed = Number(raw);
    return Number.isFinite(parsed) ? parsed : null;
  };
  return {
    name: String(data.get("name") || "").trim(),
    full_name: String(data.get("full_name") || "").trim() || null,
    email: String(data.get("email") || "").trim() || null,
    phone: String(data.get("phone") || "").trim() || null,
    linkedin_url: String(data.get("linkedin_url") || "").trim() || null,
    github_url: String(data.get("github_url") || "").trim() || null,
    website: String(data.get("website") || "").trim() || null,
    other_links: [...form.querySelectorAll("[data-link-row]")]
      .map((row) => ({
        label: String(row.querySelector('[name="link_label"]').value || "").trim(),
        url: String(row.querySelector('[name="link_url"]').value || "").trim(),
      }))
      .filter((link) => link.url),
    city: String(data.get("city") || "").trim() || null,
    target_titles: splitList(data.get("target_titles")),
    technical_skills: splitList(data.get("technical_skills")),
    domain_skills: splitList(data.get("domain_skills")),
    experience_level: String(data.get("experience_level") || "junior"),
    years_experience: numeric("years_experience") ?? 0,
    locations: readLocations(form.querySelector("[data-loc-picker]")).values,
    contract_types: data.getAll("contract_types").map((value) => String(value)),
    remote_preferences: remote,
    salary_min: numeric("salary_min"),
    salary_max: numeric("salary_max"),
    salary_currency: String(data.get("salary_currency") || "EUR").trim() || "EUR",
    exclusion_criteria: splitList(data.get("exclusion_criteria")),
    work_authorization: String(data.get("work_authorization") || "").trim() || null,
    notes: String(data.get("notes") || "").trim() || null,
    active: profile?.active ?? true,
  };
}

export async function render(container, ctx) {
  const profiles = await api.profiles();
  if (ctx.signal.aborted) return;

  const active = profiles.filter((profile) => profile.active).length;
  const withCv = profiles.filter((profile) => activeCv(profile)).length;

  container.innerHTML = `
    <header class="page-head">
      <div>
        <div class="eyebrow">Identité & recherche</div>
        <h1 class="page-title">Profils & CV</h1>
        <p class="page-sub">Chaque profil porte une recherche cohérente. Les CV restent sur votre machine, intacts et jamais réécrits.</p>
      </div>
      <div class="head-actions">
        <button class="btn btn--primary" type="button" id="new-profile">${icon("plus")} Nouveau profil</button>
      </div>
    </header>

    <div class="stat-strip" style="margin-bottom:18px">
      <div class="stat-strip-item"><strong>${profiles.length}</strong><span>profil${profiles.length > 1 ? "s" : ""}</span></div>
      <div class="stat-strip-item"><strong>${active}</strong><span>actif${active > 1 ? "s" : ""}</span></div>
      <div class="stat-strip-item"><strong>${withCv}</strong><span>CV actif${withCv > 1 ? "s" : ""}</span></div>
      <div class="stat-strip-item"><strong>${profiles.length - withCv}</strong><span>sans CV</span></div>
    </div>

    ${
      profiles.length
        ? `<div class="profile-grid">${profiles.map(profileCard).join("")}</div>
           <p class="small muted" style="margin-top:14px">${icon("info")} Un seul CV actif par profil. L'import remplace le CV actif sans modifier les candidatures déjà préparées.</p>`
        : `<div class="panel">${emptyState({
            iconName: "profiles",
            title: "Votre premier profil",
            text: "Créez un profil pour décrire vos compétences, vos cibles et vos contraintes. C'est la base du matching.",
            action: '<button class="btn btn--primary" type="button" id="empty-new-profile">Créer un profil</button>',
          })}</div>`
    }
    <input type="file" id="cv-file" accept="application/pdf,.pdf" hidden />
  `;

  const openCreate = () => openProfileDialog(null, ctx);
  document.getElementById("new-profile")?.addEventListener("click", openCreate);
  document.getElementById("empty-new-profile")?.addEventListener("click", openCreate);

  container.addEventListener("click", async (event) => {
    const edit = event.target.closest("[data-profile-edit]");
    if (edit) {
      const profile = profiles.find((item) => item.id === edit.dataset.profileEdit);
      if (profile) openProfileDialog(profile, ctx);
      return;
    }

    const cvButton = event.target.closest("[data-profile-cv]");
    if (cvButton) {
      const input = document.getElementById("cv-file");
      input.dataset.profileId = cvButton.dataset.profileCv;
      input.click();
      return;
    }

    const toggle = event.target.closest("[data-profile-toggle]");
    if (toggle) {
      const profile = profiles.find((item) => item.id === toggle.dataset.profileToggle);
      if (!profile) return;
      const activeNow = toggle.dataset.active === "1";
      setLoading(toggle, true, activeNow ? "Désactivation…" : "Réactivation…");
      try {
        if (activeNow) await api.deactivateProfile(profile.id);
        else await api.activateProfile(profile.id);
        toast(activeNow ? "Profil désactivé." : "Profil réactivé.", {
          title: activeNow ? "Profil mis de côté" : "Profil de retour",
        });
        notifyChanged();
        ctx.refresh();
      } catch (error) {
        setLoading(toggle, false);
        toast(errorMessage(error), { title: "Action impossible", type: "error" });
      }
    }
  });

  const fileInput = document.getElementById("cv-file");
  fileInput.addEventListener("change", async () => {
    const file = fileInput.files?.[0];
    const profileId = fileInput.dataset.profileId;
    if (!file || !profileId) return;
    toast(`Import de « ${file.name} » en cours…`, { title: "CV", duration: 2200 });
    try {
      await api.uploadResume(profileId, file);
      toast("Le CV actif a été remplacé. Il n'a pas été modifié.", { title: "CV importé" });
      notifyChanged();
      ctx.refresh();
    } catch (error) {
      toast(errorMessage(error), { title: "Import impossible", type: "error" });
    } finally {
      fileInput.value = "";
      delete fileInput.dataset.profileId;
    }
  });
}
