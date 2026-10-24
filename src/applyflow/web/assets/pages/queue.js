import { api } from "../api.js";
import { icon } from "../icons.js";
import {
  ATTEMPT_STATUS,
  confirmDialog,
  emptyState,
  errorMessage,
  esc,
  formatDate,
  num,
  openModal,
  safeUrl,
  setLoading,
  statusChip,
  toast,
  truncate,
} from "../ui.js";

const STATUS_ORDER = { needs_review: 0, prepared: 1, manual: 2, approved: 3, blocked: 4, submitted: 5, failed: 6 };
// Formulaire non lisible (connexion, JavaScript) ou inaccessible : on postule à la main avec un dossier.
const HANDS_ON = new Set(["manual", "blocked"]);
const SOURCE_LABELS = { profile: "Profil", resume: "CV", answer_library: "Réponse validée" };
const MODE_LABELS = { dry_run: "Dry-run", live: "Live" };

function attemptTitle(attempt) {
  return attempt.job?.title || "Offre sans titre";
}

function attemptCompany(attempt) {
  return attempt.job?.company || "Entreprise inconnue";
}

function unknownQuestions(attempt) {
  const plan = attempt.plan || {};
  return Array.isArray(plan.unknown_questions)
    ? plan.unknown_questions
    : Array.isArray(attempt.unknown_questions)
      ? attempt.unknown_questions
      : [];
}

function fills(attempt) {
  return Array.isArray(attempt.plan?.fills) ? attempt.plan.fills : [];
}

function kitItems(attempt) {
  return Array.isArray(attempt.plan?.manual_kit) ? attempt.plan.manual_kit : [];
}

// Dossier à copier pour postuler à la main : CV à envoyer, puis les informations du profil.
function kitPanel(attempt, resumeNames) {
  const items = kitItems(attempt);
  const resume = attempt.resume_id ? resumeNames[attempt.resume_id] || "CV du profil" : "Aucun CV associé";
  const rows = [
    ["CV à envoyer", resume, false],
    ...items.map((item) => [item.label, item.value, true]),
  ];
  return `<div class="subhead">Dossier de candidature <span class="chip chip--tag">${rows.length}</span></div>
    <div class="kit-list">${rows
      .map(
        ([label, value, copyable]) => `<div class="kit-row">
          <span class="kit-label">${esc(label)}</span>
          <span class="kit-value">${esc(value)}</span>
          ${copyable ? `<button class="btn btn--ghost btn--sm" type="button" data-copy="${esc(value)}" aria-label="Copier ${esc(label)}">${icon("file")} Copier</button>` : "<span></span>"}
        </div>`,
      )
      .join("")}</div>`;
}

function queueItem(attempt, selectedId) {
  const unknown = unknownQuestions(attempt);
  return `<button class="queue-item ${attempt.id === selectedId ? "is-active" : ""}" type="button" data-attempt-id="${esc(attempt.id)}">
    <div class="queue-item-top">
      <div>
        <div class="queue-item-title">${esc(attemptTitle(attempt))}</div>
        <div class="queue-item-company">${esc(attemptCompany(attempt))}</div>
      </div>
      ${statusChip(attempt.status)}
    </div>
    <div class="queue-item-meta">
      <span>${esc(attempt.profile_name || "Profil")}</span>
      <span aria-hidden="true">·</span>
      ${
        HANDS_ON.has(attempt.status)
          ? `<span>${kitItems(attempt).length} information${kitItems(attempt).length > 1 ? "s" : ""} à copier</span>`
          : `<span>${fills(attempt).length} champ${fills(attempt).length > 1 ? "s" : ""}</span>`
      }
      ${unknown.length ? `<span class="chip chip--amber">${unknown.length} question${unknown.length > 1 ? "s" : ""}</span>` : ""}
    </div>
  </button>`;
}

function displayFillValue(fill, resumeLabel) {
  if (fill.key === "resume" || fill.source === "resume") {
    // `display` vient des plans récents ; `resumeLabel` couvre ceux préparés avant.
    return fill.display || resumeLabel || String(fill.value || "").split(/[\\/]/).pop() || "CV";
  }
  return fill.value;
}

function fillTable(items, resumeLabel) {
  return `<div class="table-wrap">
    <table class="table">
      <thead><tr><th>Champ</th><th>Valeur prévue</th><th>Source</th></tr></thead>
      <tbody>
        ${items
          .map(
            (fill) => `<tr>
              <td><div class="cell-title">${esc(fill.label)}</div><div class="cell-sub mono">${esc(fill.selector || "")}</div></td>
              <td><span class="small">${esc(truncate(displayFillValue(fill, resumeLabel), 110))}</span></td>
              <td><span class="chip chip--tag">${esc(SOURCE_LABELS[fill.source] || fill.source || "—")}</span></td>
            </tr>`,
          )
          .join("")}
      </tbody>
    </table>
  </div>`;
}

function detailPanel(attempt, resumeNames = {}) {
  const plan = attempt.plan || {};
  const unknown = unknownQuestions(attempt);
  const planned = fills(attempt);
  const url = safeUrl(attempt.job?.apply_url || attempt.job?.url);
  const handsOn = HANDS_ON.has(attempt.status);
  const resumeLabel = attempt.resume_id ? resumeNames[attempt.resume_id] : null;
  const canPrepare = !["approved", "submitted"].includes(attempt.status);
  const canApprove = attempt.status === "prepared";
  // Une question obligatoire peut rester ouverte alors que vous avez postulé vous-même :
  // la soumission doit pouvoir être enregistrée pour que le suivi démarre.
  const canSubmit = ["approved", "needs_review"].includes(attempt.status) || handsOn;
  return `<div class="panel">
    <div class="panel-body">
      <div class="detail-head">
        <div>
          <div class="eyebrow">Revue humaine</div>
          <h2 style="margin-top:5px">${esc(attemptTitle(attempt))}</h2>
          <p class="company">${esc(attemptCompany(attempt))} · ${esc(attempt.job?.location || "Localisation inconnue")}</p>
        </div>
        <div class="detail-actions">
          ${statusChip(attempt.status)}
          ${url !== "#" ? `<a class="btn ${handsOn ? "btn--primary" : "btn--secondary"} btn--sm" href="${esc(url)}" target="_blank" rel="noreferrer noopener">${icon("external")} ${handsOn ? "Ouvrir l'offre et postuler" : "Annonce"}</a>` : ""}
        </div>
      </div>

      <div class="meta-grid">
        <div class="meta-item"><div class="stat-label">Profil</div><div class="meta-value">${esc(attempt.profile_name || "—")}</div></div>
        <div class="meta-item"><div class="stat-label">CV associé</div><div class="meta-value mono">${esc(attempt.resume_id ? resumeNames[attempt.resume_id] || `${attempt.resume_id.slice(0, 8)}…` : "Aucun")}</div></div>
        <div class="meta-item"><div class="stat-label">Mode</div><div class="meta-value">${esc(MODE_LABELS[attempt.mode] || attempt.mode || "—")}</div></div>
        <div class="meta-item"><div class="stat-label">Dernière mise à jour</div><div class="meta-value">${esc(formatDate(attempt.updated_at))}</div></div>
      </div>

      ${attempt.error ? `<div class="alert" style="margin-bottom:12px">${icon("alert")}<div>${esc(attempt.error)}</div></div>` : ""}
      ${plan.blocked_reason ? `<div class="alert" style="margin-bottom:12px">${icon("alert")}<div><strong>Préparation bloquée.</strong> ${esc(plan.blocked_reason)}</div></div>` : ""}

      ${
        attempt.status === "manual"
          ? `<div class="info-strip" style="margin-bottom:14px">${icon("info")}<div><strong>Ce site demande une connexion ou un formulaire que l'on ne peut pas lire automatiquement.</strong> ApplyFlow ne se connecte jamais à votre place : ouvrez l'offre, postulez, et copiez les informations ci-dessous. Cliquez ensuite sur « J'ai postulé » pour garder la trace.</div></div>`
          : `<div class="info-strip" style="margin-bottom:14px">${icon("lock")}<div><strong>Aucune soumission automatique.</strong> ApplyFlow prépare et trace ; vous relisez, vous validez, puis vous enregistrez la soumission effectuée.</div></div>`
      }

      ${handsOn ? kitPanel(attempt, resumeNames) : ""}

      ${handsOn ? "" : `<div class="subhead">Champs prévus <span class="chip chip--tag">${planned.length}</span></div>`}
      ${
        handsOn
          ? ""
          : planned.length
          ? fillTable(planned, resumeLabel)
          : emptyState({
              iconName: "file",
              title: "Aucun champ prévu",
              text: "La candidature n'a pas encore été préparée, ou le formulaire ne contenait aucun champ exploitable.",
              small: true,
            })
      }

      ${handsOn ? "" : `<div class="subhead">Questions sans réponse validée <span class="chip ${unknown.length ? "chip--amber" : "chip--sage"}">${unknown.length}</span></div>
      ${
        unknown.length
          ? `<div class="unknown-list">${unknown
              .map(
                (question) => `<div class="unknown-item">
                  <div class="unknown-question">
                    <span>${esc(question.label)}</span>
                    ${question.required ? '<span class="chip chip--amber">Obligatoire</span>' : '<span class="chip chip--tag">Facultatif</span>'}
                  </div>
                  <form class="unknown-form" data-question="${esc(question.label)}">
                    <input class="input" name="answer" placeholder="Votre réponse validée…" aria-label="Réponse pour ${esc(question.label)}" required />
                    <button class="btn btn--secondary btn--sm" type="submit">${icon("checkCircle")} Enregistrer</button>
                  </form>
                </div>`,
              )
              .join("")}</div>`
          : `<p class="small muted">Toutes les questions obligatoires disposent d'une réponse validée.</p>`
      }`}

      ${(plan.warnings || []).length ? `<div class="subhead">Avertissements</div><ul class="small muted" style="padding-left:18px;line-height:1.7">${plan.warnings.slice(0, 8).map((warning) => `<li>${esc(warning)}</li>`).join("")}</ul>` : ""}

      <div class="action-row" style="margin-top:18px;padding-top:14px;border-top:1px solid var(--line-faint)">
        <button class="btn btn--secondary btn--sm" type="button" data-action="prepare" ${canPrepare ? "" : "disabled"}>${icon("refresh")} Re-préparer</button>
        ${
          handsOn
            ? `<button class="btn btn--primary btn--sm" type="button" data-action="submit">${icon("checkCircle")} J'ai postulé à la main</button>`
            : `<button class="btn btn--primary btn--sm" type="button" data-action="approve" ${canApprove ? "" : "disabled"}>${icon("checkCircle")} Valider la candidature</button>
        <button class="btn btn--secondary btn--sm" type="button" data-action="submit" ${canSubmit ? "" : "disabled"}>${icon("mail")} Marquer comme soumise</button>`
        }
      </div>
      <p class="hint" style="margin-top:7px">${
        handsOn
          ? "« J'ai postulé à la main » consigne une candidature que vous avez réellement envoyée vous-même sur le site de l'employeur."
          : "La validation enregistre la candidature et son CV. La soumission n'est enregistrée qu'après votre action sur le site employeur."
      }</p>
    </div>
  </div>`;
}

function submitDialog(attempt, ctx) {
  const dialog = openModal({
    title: "Enregistrer la soumission",
    subtitle: "À utiliser après avoir réellement envoyé la candidature depuis le site de l'employeur.",
    body: `<form id="submit-form" novalidate>
      <div class="info-strip" style="margin-bottom:14px">${icon("info")}<div>ApplyFlow n'envoie rien. Cette action consigne la soumission que vous avez effectuée.</div></div>
      <div class="field">
        <label for="submit-reference">Référence externe <span class="opt">facultatif</span></label>
        <input class="input" id="submit-reference" name="reference" placeholder="Identifiant de candidature, accusé de réception…" />
        <span class="hint">Utile pour retrouver la candidature sur le site employeur.</span>
      </div>
      <label class="check" style="margin-top:14px"><input type="checkbox" name="confirmed" required /> J'ai effectivement soumis cette candidature.</label>
    </form>`,
    footer: `<button class="btn btn--ghost" type="button" data-close>Annuler</button>
      <button class="btn btn--primary" type="submit" form="submit-form" data-submit>Enregistrer la soumission</button>`,
    onMount: (element, close) => {
      const form = element.querySelector("#submit-form");
      const button = element.querySelector("[data-submit]");
      form.addEventListener("submit", async (event) => {
        event.preventDefault();
        if (!form.elements.confirmed.checked) {
          toast("Cochez la confirmation pour enregistrer la soumission.", {
            title: "Confirmation requise",
            type: "warn",
          });
          return;
        }
        setLoading(button, true, "Enregistrement…");
        try {
          await api.submitAttempt(attempt.id, String(form.elements.reference.value || "").trim() || null);
          close();
          toast("La candidature est maintenant marquée comme soumise.", { title: "Soumission enregistrée" });
          ctx.refresh();
        } catch (error) {
          setLoading(button, false);
          toast(errorMessage(error), { title: "Enregistrement impossible", type: "error" });
        }
      });
    },
  });
  return dialog;
}

export async function render(container, ctx) {
  const [attempts, profiles] = await Promise.all([api.queue(ctx.signal), api.profiles()]);
  if (ctx.signal.aborted) return;
  const resumeNames = Object.fromEntries(
    profiles.flatMap((profile) =>
      (profile.resumes || []).map((resume) => [resume.id, resume.filename]),
    ),
  );

  const sorted = [...attempts].sort(
    (a, b) => (STATUS_ORDER[a.status] ?? 9) - (STATUS_ORDER[b.status] ?? 9),
  );
  const requested = ctx.query.get("attempt");
  const selected = sorted.find((attempt) => attempt.id === requested) || sorted[0] || null;
  if (selected && requested !== selected.id) {
    history.replaceState(null, "", `#/validation?attempt=${selected.id}`);
  }

  const counts = {
    prepared: attempts.filter((attempt) => attempt.status === "prepared").length,
    review: attempts.filter((attempt) => attempt.status === "needs_review").length,
    approved: attempts.filter((attempt) => attempt.status === "approved").length,
    manual: attempts.filter((attempt) => attempt.status === "manual").length,
    blocked: attempts.filter((attempt) => attempt.status === "blocked").length,
  };

  container.innerHTML = `
    <header class="page-head">
      <div>
        <div class="eyebrow">Décision humaine</div>
        <h1 class="page-title">File de validation</h1>
        <p class="page-sub">Chaque candidature passe par votre regard. Complétez les questions ouvertes, vérifiez le plan, puis validez.</p>
      </div>
      <div class="head-actions">
        <button class="btn btn--secondary" type="button" id="queue-refresh">${icon("refresh")} Actualiser</button>
        <a class="btn btn--ghost" href="#/candidatures">${icon("applications")} Candidatures</a>
      </div>
    </header>

    <div class="stat-strip" style="margin-bottom:16px">
      <div class="stat-strip-item"><strong>${num(counts.prepared)}</strong><span>prête${counts.prepared > 1 ? "s" : ""} à valider</span></div>
      <div class="stat-strip-item"><strong>${num(counts.review)}</strong><span>à compléter</span></div>
      <div class="stat-strip-item"><strong>${num(counts.approved)}</strong><span>validée${counts.approved > 1 ? "s" : ""}</span></div>
      <div class="stat-strip-item"><strong>${num(counts.manual)}</strong><span>à postuler à la main</span></div>
      <div class="stat-strip-item"><strong>${num(counts.blocked)}</strong><span>bloquée${counts.blocked > 1 ? "s" : ""}</span></div>
    </div>

    ${
      attempts.length
        ? `<div class="queue-layout">
            <section class="queue-side" aria-labelledby="queue-list-heading">
              <div class="queue-side-inner">
                <div class="section-head"><div><h2 class="section-title" id="queue-list-heading">À examiner</h2><p class="section-sub">${num(attempts.length)} tentative${attempts.length > 1 ? "s" : ""} · triées par action attendue</p></div></div>
                <div class="queue-list">${sorted.map((attempt) => queueItem(attempt, selected?.id)).join("")}</div>
              </div>
            </section>
            <section class="queue-detail" aria-label="Détail de la candidature">
              ${selected ? detailPanel(selected, resumeNames) : ""}
            </section>
          </div>`
        : `<div class="panel">${emptyState({
            iconName: "queue",
            title: "La file est vide",
            text: "Aucune candidature à relire. Lancez une campagne pour préparer les offres qui correspondent à vos profils.",
            action: '<a class="btn btn--primary" href="#/campagnes?new=1">Créer une campagne</a>',
          })}</div>`
    }`;

  document.getElementById("queue-refresh")?.addEventListener("click", () => ctx.refresh());
  if (requested && window.innerWidth < 980) {
    requestAnimationFrame(() => {
      document.querySelector(".queue-detail")?.scrollIntoView({ block: "start", behavior: "smooth" });
    });
  }

  container.addEventListener("click", async (event) => {
    const item = event.target.closest("[data-attempt-id]");
    if (item) {
      ctx.navigate(`validation?attempt=${item.dataset.attemptId}`);
      return;
    }
    const copyButton = event.target.closest("[data-copy]");
    if (copyButton) {
      const text = copyButton.dataset.copy;
      try {
        await navigator.clipboard.writeText(text);
      } catch {
        const area = document.createElement("textarea"); // repli : page sans accès au presse-papiers
        area.value = text;
        document.body.appendChild(area);
        area.select();
        document.execCommand("copy");
        area.remove();
      }
      toast(text.length > 70 ? `${text.slice(0, 70)}…` : text, { title: "Copié", duration: 1800 });
      return;
    }
    if (!selected) return;
    const actionButton = event.target.closest("[data-action]");
    if (!actionButton) return;
    const action = actionButton.dataset.action;

    if (action === "prepare") {
      setLoading(actionButton, true, "Préparation…");
      try {
        await api.prepareAttempt(selected.id);
        toast("La candidature a été ré-analysée.", { title: "Préparation terminée" });
        ctx.refresh();
      } catch (error) {
        setLoading(actionButton, false);
        toast(errorMessage(error), { title: "Préparation impossible", type: "error" });
      }
      return;
    }

    if (action === "approve") {
      const ok = await confirmDialog({
        title: "Valider cette candidature ?",
        message: `La candidature à « ${attemptTitle(selected)} » chez ${attemptCompany(selected)} sera enregistrée avec le CV associé.`,
        details:
          "<p>Vous pourrez ensuite la retrouver dans <strong>Candidatures</strong>. ApplyFlow ne soumettra rien à votre place.</p>",
        confirmLabel: "Valider la candidature",
      });
      if (!ok) return;
      setLoading(actionButton, true, "Validation…");
      try {
        await api.approveAttempt(selected.id);
        toast("Candidature validée. Pensez à enregistrer la soumission après l'avoir effectuée.", {
          title: "Validée",
        });
        ctx.refresh();
      } catch (error) {
        setLoading(actionButton, false);
        toast(errorMessage(error), { title: "Validation impossible", type: "error" });
      }
      return;
    }

    if (action === "submit") {
      submitDialog(selected, ctx);
    }
  });

  container.querySelectorAll(".unknown-form").forEach((form) => {
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      const answer = String(form.elements.answer.value || "").trim();
      if (!answer) {
        form.elements.answer.focus();
        return;
      }
      const button = form.querySelector("button[type=submit]");
      setLoading(button, true, "Enregistrement…");
      try {
        await api.saveAnswer({
          question_text: form.dataset.question,
          answer,
          approved: true,
          kind: "text",
        });
        await api.prepareAttempt(selected.id);
        toast("Réponse enregistrée. La candidature a été re-préparée.", {
          title: "Question résolue",
        });
        ctx.refresh();
      } catch (error) {
        setLoading(button, false);
        toast(errorMessage(error), { title: "Réponse impossible", type: "error" });
      }
    });
  });
}
