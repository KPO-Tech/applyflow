import { api } from "../api.js";
import { icon } from "../icons.js";
import {
  emptyState,
  errorMessage,
  esc,
  formatDate,
  num,
  openModal,
  relativeDay,
  setLoading,
  toast,
  truncate,
} from "../ui.js";

const REPLY = {
  interview: { label: "Entretien", tone: "blue" },
  offer: { label: "Offre", tone: "sage" },
  rejected: { label: "Refus", tone: "red" },
  acknowledgement: { label: "Accusé", tone: "plain" },
  other: { label: "Autre", tone: "plain" },
};

const REPLY_LABELS = ["interview", "offer", "rejected"];
const STATUS_LABELS = {
  prepared: "Préparée",
  submitted: "En attente",
  interview: "Entretien",
  offer: "Offre",
  rejected: "Refus",
  withdrawn: "Retirée",
};

function replyChip(label) {
  const meta = REPLY[label] || { label: label || "—", tone: "plain" };
  return `<span class="chip chip--${esc(meta.tone)}">${esc(meta.label)}</span>`;
}

function toneFor(label) {
  return (REPLY[label] || {}).tone || "plain";
}

function pendingCount(messages) {
  return messages.filter(
    (message) => REPLY_LABELS.includes(message.classification) && !message.reviewed && !message.ignored,
  ).length;
}

function replyCount(messages) {
  return messages.filter((message) => REPLY_LABELS.includes(message.classification)).length;
}

function stats(messages, followups) {
  const counts = {
    pending: pendingCount(messages),
    positive: messages.filter((message) => ["interview", "offer"].includes(message.classification)).length,
    rejected: messages.filter((message) => message.classification === "rejected").length,
  };
  return `<div class="stat-strip" style="margin-bottom:16px">
    <div class="stat-strip-item"><strong>${num(messages.length)}</strong><span>message${messages.length > 1 ? "s" : ""} suivi${messages.length > 1 ? "s" : ""}</span></div>
    <div class="stat-strip-item"><strong>${num(counts.pending)}</strong><span>à traiter</span></div>
    <div class="stat-strip-item"><strong>${num(counts.positive)}</strong><span>réponse${counts.positive > 1 ? "s" : ""} positive${counts.positive > 1 ? "s" : ""}</span></div>
    <div class="stat-strip-item"><strong>${num(counts.rejected)}</strong><span>refus</span></div>
    <div class="stat-strip-item"><strong>${num(followups.length)}</strong><span>relance${followups.length > 1 ? "s" : ""} à préparer</span></div>
  </div>`;
}

function messageRow(message) {
  const linked = message.application;
  return `<button class="mail-row" type="button" data-message-id="${esc(message.id)}" aria-label="Ouvrir le message ${esc(message.subject || "sans objet")}">
    <span class="mail-row-mark" data-tone="${esc(toneFor(message.classification))}">${icon("mail")}</span>
    <span class="mail-row-main">
      <span class="mail-row-top">
        <strong>${esc(message.subject || "(sans objet)")}</strong>
        ${replyChip(message.classification)}
        ${message.reviewed ? "" : '<span class="mail-row-new">à traiter</span>'}
      </span>
      <span class="mail-row-excerpt">${esc(truncate(message.excerpt, 150))}</span>
      <span class="mail-row-meta">${esc(message.sender_name || message.sender_email)} · ${esc(relativeDay(message.received_at))}</span>
    </span>
    <span class="mail-row-link">
      ${linked ? `<strong>${esc(linked.job_title || "Candidature")}</strong><small>${esc(linked.job_company || "")} · ${esc(STATUS_LABELS[linked.status] || linked.status)}</small>` : '<small class="muted">Non rattaché</small>'}
    </span>
    <span class="arrow-link" aria-hidden="true">${icon("arrowRight")}</span>
  </button>`;
}

function relanceRow(item) {
  return `<div class="relance-row" data-followup="${esc(item.application_id)}">
    <div class="relance-main">
      <div class="mail-row-top"><strong>${esc(item.job_title || "Candidature")}</strong><span class="chip chip--amber">${num(item.days_since)} jours</span></div>
      <div class="cell-sub">${esc(item.job_company || "Entreprise inconnue")} · postulé le ${esc(formatDate(item.submitted_at))}</div>
      <div class="mail-row-excerpt">${esc(item.suggested_subject)}</div>
    </div>
    <div class="relance-actions">
      <button class="btn btn--secondary btn--sm" type="button" data-open-followup="${esc(item.application_id)}">${icon("mail")} Préparer</button>
      <button class="btn btn--ghost btn--sm" type="button" data-mark-followup="${esc(item.application_id)}">Marquer relancée</button>
    </div>
  </div>`;
}

function messageList(messages, filter) {
  let visible = messages;
  if (filter === "review") {
    visible = messages.filter(
      (message) => REPLY_LABELS.includes(message.classification) && !message.reviewed && !message.ignored,
    );
  } else if (filter === "replies") {
    visible = messages.filter((message) => REPLY_LABELS.includes(message.classification));
  }
  if (!visible.length) {
    return emptyState({
      iconName: "checkCircle",
      title: filter === "review" ? "Tout est à jour" : "Aucun message dans ce filtre",
      text:
        filter === "review"
          ? "Les nouvelles réponses apparaîtront ici après une synchronisation."
          : "Synchronisez votre boîte pour récupérer les réponses récentes.",
    });
  }
  return `<div class="mail-list">${visible.map(messageRow).join("")}</div>`;
}

function relanceList(followups, relanceDays) {
  if (!followups.length) {
    return emptyState({
      iconName: "clock",
      title: "Aucune relance à préparer",
      text: `Une candidature sans réponse apparaît ici ${num(relanceDays)} jours après l'envoi, tant que vous ne l'avez pas relancée.`,
    });
  }
  return `<div class="mail-list">${followups.map(relanceRow).join("")}</div>`;
}

async function copyText(text) {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    const area = document.createElement("textarea");
    area.value = text;
    area.setAttribute("readonly", "");
    area.style.position = "fixed";
    area.style.opacity = "0";
    document.body.append(area);
    area.select();
    let copied = false;
    try {
      copied = document.execCommand("copy");
    } catch {
      copied = false;
    }
    area.remove();
    return copied;
  }
}

function openMessage(message, applications, ctx) {
  const linked = message.application;
  const canApply = Boolean(message.application_id);
  const options = applications
    .map((application) => {
      const job = application.job || {};
      const label = `${job.title || "Candidature"} — ${job.company || "entreprise inconnue"} (${STATUS_LABELS[application.status] || application.status})`;
      return `<option value="${esc(application.id)}" ${application.id === message.application_id ? "selected" : ""}>${esc(label)}</option>`;
    })
    .join("");

  const classificationOptions = [
    ["interview", "Entretien obtenu"],
    ["offer", "Offre reçue"],
    ["rejected", "Refus reçu"],
    ["acknowledgement", "Accusé de réception"],
    ["other", "Autre / notification"],
  ]
    .map(
      ([value, label]) =>
        `<option value="${value}" ${value === message.classification ? "selected" : ""}>${label}</option>`,
    )
    .join("");

  openModal({
    drawer: true,
    title: message.subject || "(sans objet)",
    subtitle: `${message.sender_name || message.sender_email} · ${formatDate(message.received_at)}`,
    body: `<div class="tag-list" style="margin-bottom:14px">
        ${replyChip(message.classification)}
        <span class="chip chip--plain">indice ${Math.round((message.confidence || 0) * 100)} %</span>
        ${message.reviewed ? '<span class="chip chip--plain">relu</span>' : '<span class="chip chip--amber">à confirmer</span>'}
      </div>
      <div class="mail-excerpt-box">${esc(message.excerpt || "Aucun extrait disponible pour ce message.")}</div>
      <p class="hint" style="margin-top:8px">${esc(message.reason || "")}</p>
      ${linked ? `<p class="hint">Rattaché à <strong>${esc(linked.job_title || "candidature")}</strong> · ${esc(linked.job_company || "")}${message.match_reason ? ` — ${esc(message.match_reason)}` : ""}</p>` : ""}

      <div class="mail-form-section">
        <div class="field">
          <label for="mail-application">Candidature rattachée</label>
          <select class="select" id="mail-application" name="application">
            <option value="">Aucune candidature</option>
            ${options}
          </select>
          ${applications.length ? "" : '<span class="hint">Aucune candidature suivie pour le moment.</span>'}
        </div>
        <div class="field">
          <label for="mail-classification">Interprétation du message</label>
          <select class="select" id="mail-classification" name="classification">${classificationOptions}</select>
          <span class="hint">La classification est une proposition. Rien ne change tant que vous n'enregistrez pas.</span>
        </div>
        <label class="check">
          <input type="checkbox" name="apply-status" ${canApply && ["interview", "offer", "rejected"].includes(message.classification) ? "checked" : ""} />
          Mettre à jour le statut de la candidature
        </label>
      </div>`,
    footer: `<span class="foot-left">${icon("lock")} Suivi local</span>
      <button class="btn btn--ghost" type="button" data-close>Fermer</button>
      <button class="btn btn--ghost" type="button" data-ignore>Ignorer</button>
      <button class="btn btn--primary" type="button" data-save>${icon("checkCircle")} Enregistrer</button>`,
    onMount: (element, close) => {
      const appSelect = element.querySelector("#mail-application");
      const classificationSelect = element.querySelector("#mail-classification");
      const applyCheckbox = element.querySelector('input[name="apply-status"]');
      const save = element.querySelector("[data-save]");
      const ignore = element.querySelector("[data-ignore]");

      const syncCheckbox = () => {
        const mapped = ["interview", "offer", "rejected"].includes(classificationSelect.value);
        applyCheckbox.disabled = !appSelect.value || !mapped;
        if (applyCheckbox.disabled) applyCheckbox.checked = false;
      };
      syncCheckbox();
      appSelect.addEventListener("change", syncCheckbox);
      classificationSelect.addEventListener("change", syncCheckbox);

      save.addEventListener("click", async () => {
        setLoading(save, true, "Enregistrement…");
        try {
          await api.updateEmailMessage(message.id, {
            application_id: appSelect.value || null,
            classification: classificationSelect.value,
            apply_status: applyCheckbox.checked,
          });
          close();
          toast("La réponse et son rattachement sont enregistrés.", { title: "Message traité" });
          ctx.refresh();
        } catch (error) {
          setLoading(save, false);
          toast(errorMessage(error), { title: "Enregistrement impossible", type: "error" });
        }
      });

      ignore.addEventListener("click", async () => {
        setLoading(ignore, true, "…");
        try {
          await api.updateEmailMessage(message.id, { ignored: true });
          close();
          toast("Le message est masqué du suivi.", { title: "Message ignoré" });
          ctx.refresh();
        } catch (error) {
          setLoading(ignore, false);
          toast(errorMessage(error), { title: "Action impossible", type: "error" });
        }
      });
    },
  });
}

function openRelance(item, ctx) {
  const subject = item.suggested_subject || "";
  const body = item.suggested_body || "";
  const gmailUrl = `https://mail.google.com/mail/?view=cm&fs=1&su=${encodeURIComponent(subject)}&body=${encodeURIComponent(body)}`;
  openModal({
    drawer: true,
    title: `Relance — ${item.job_title || "candidature"}`,
    subtitle: `${item.job_company || "Entreprise inconnue"} · envoyée il y a ${num(item.days_since)} jours`,
    body: `<div class="draft-box">
        <div class="draft-subject"><span>Objet</span><strong>${esc(subject)}</strong></div>
        <pre class="draft-body">${esc(body)}</pre>
      </div>
      <p class="hint" style="margin-top:10px">ApplyFlow ne devine pas l'adresse du recruteur et n'envoie rien. Le message s'ouvre dans Gmail pour que vous choisissiez le destinataire.</p>`,
    footer: `<button class="btn btn--ghost" type="button" data-close>Fermer</button>
      <button class="btn btn--secondary" type="button" data-copy>Copier le texte</button>
      <a class="btn btn--secondary" href="${gmailUrl}" target="_blank" rel="noreferrer noopener">${icon("external")} Composer dans Gmail</a>
      <button class="btn btn--primary" type="button" data-mark>${icon("checkCircle")} Marquer relancée</button>`,
    onMount: (element, close) => {
      const copy = element.querySelector("[data-copy]");
      copy.addEventListener("click", async () => {
        const copied = await copyText(`Objet : ${subject}\n\n${body}`);
        toast(
          copied ? "Le message est dans le presse-papiers." : "Copie impossible : sélectionnez le texte manuellement.",
          { title: copied ? "Message copié" : "Copie bloquée", type: copied ? "success" : "warn" },
        );
      });
      const mark = element.querySelector("[data-mark]");
      mark.addEventListener("click", async () => {
        setLoading(mark, true, "Enregistrement…");
        try {
          await api.markFollowup(item.application_id);
          close();
          toast("Cette candidature ne sera plus proposée en relance.", { title: "Relance enregistrée" });
          ctx.refresh();
        } catch (error) {
          setLoading(mark, false);
          toast(errorMessage(error), { title: "Action impossible", type: "error" });
        }
      });
    },
  });
}

export async function render(container, ctx) {
  const [status, messages, followupData, applications] = await Promise.all([
    api.emailStatus(ctx.signal),
    api.emailMessages("all", ctx.signal),
    api.followups(ctx.signal),
    api.applications(ctx.signal),
  ]);
  if (ctx.signal.aborted) return;

  const followups = followupData.items || [];
  const relanceDays = status.relance_days || 10;
  let filter = pendingCount(messages) > 0 ? "review" : messages.length ? "replies" : "relances";

  const emptyPage = !messages.length && !followups.length;

  container.innerHTML = `
    <header class="page-head">
      <div>
        <div class="eyebrow">Suivi</div>
        <h1 class="page-title">Suivi e-mail</h1>
        <p class="page-sub">Les réponses reçues dans votre boîte, classées puis confirmées par vous. Les relances se préparent ici, sans envoi automatique.</p>
      </div>
      <div class="head-actions">
        <a class="btn btn--ghost" href="#/reglages/email">${icon("settings")} Réglages de la boîte</a>
        ${
          status.connected
            ? `<button class="btn btn--primary" type="button" data-sync>${icon("refresh")} Synchroniser</button>`
            : `<a class="btn btn--primary" href="#/reglages/email">${icon("mail")} Connecter Gmail</a>`
        }
      </div>
    </header>

    ${
      status.connected
        ? ""
        : `<div class="mail-notice">
            ${icon("mail")}
            <div><strong>Gmail n'est pas connecté.</strong><p>Les messages déjà synchronisés restent consultables. Rebranchez la boîte pour récupérer les nouvelles réponses.</p></div>
            <a class="btn btn--secondary btn--sm" href="#/reglages/email">Brancher Gmail</a>
          </div>`
    }

    ${messages.length || followups.length ? stats(messages, followups) : ""}

    <section class="panel panel--flush" aria-labelledby="mail-heading">
      <div class="panel-head panel-head--bordered">
        <div><h2 class="panel-title" id="mail-heading">Réponses et relances</h2><p class="panel-sub" id="mail-count"></p></div>
        ${
          emptyPage
            ? ""
            : `<div class="status-tabs" role="tablist" aria-label="Filtrer les messages">
                <button class="tab ${filter === "review" ? "is-active" : ""}" type="button" role="tab" aria-selected="${filter === "review"}" data-filter="review">À traiter<span class="tab-count">${pendingCount(messages)}</span></button>
                <button class="tab ${filter === "replies" ? "is-active" : ""}" type="button" role="tab" aria-selected="${filter === "replies"}" data-filter="replies">Réponses<span class="tab-count">${replyCount(messages)}</span></button>
                <button class="tab ${filter === "relances" ? "is-active" : ""}" type="button" role="tab" aria-selected="${filter === "relances"}" data-filter="relances">Relances<span class="tab-count">${followups.length}</span></button>
              </div>`
        }
      </div>
      <div id="mail-content">
        ${
          emptyPage
            ? `<div class="mail-onboarding">
                <span class="empty-icon">${icon("mail")}</span>
                <h3>${status.connected ? "Aucune réponse pour l'instant" : "Reliez votre boîte Gmail"}</h3>
                <p>${status.connected ? "Synchronisez la boîte : les réponses reçues seront classées ici, sans quitter votre ordinateur." : "ApplyFlow lit les réponses par IMAP, en lecture seule. Un mot de passe d'application suffit, aucun projet Google Cloud."}</p>
                ${
                  status.connected
                    ? `<button class="btn btn--primary" type="button" data-sync>${icon("refresh")} Synchroniser la boîte</button>`
                    : `<a class="btn btn--primary" href="#/reglages/email">${icon("mail")} Connecter Gmail</a>`
                }
                <ul class="mail-onboarding-points">
                  <li>${icon("lock")} Les messages restent non lus dans Gmail.</li>
                  <li>${icon("checkCircle")} Une réponse n'est jamais appliquée sans votre confirmation.</li>
                  <li>${icon("clock")} Les relances se préparent après ${num(relanceDays)} jours sans réponse.</li>
                </ul>
              </div>`
            : ""
        }
      </div>
    </section>`;

  const content = document.getElementById("mail-content");
  const countBox = document.getElementById("mail-count");

  const describe = (key) => {
    if (key === "review") {
      const count = pendingCount(messages);
      return count
        ? `${num(count)} réponse${count > 1 ? "s" : ""} à confirmer`
        : "Aucune réponse en attente de confirmation";
    }
    if (key === "replies") {
      const count = replyCount(messages);
      return `${num(count)} réponse${count > 1 ? "s" : ""} classée${count > 1 ? "s" : ""}`;
    }
    return followups.length
      ? `${num(followups.length)} candidature${followups.length > 1 ? "s" : ""} sans réponse depuis ${num(relanceDays)} jours`
      : `Relances proposées après ${num(relanceDays)} jours sans réponse`;
  };

  const paint = () => {
    if (emptyPage) return;
    if (countBox) countBox.textContent = describe(filter);
    content.innerHTML = filter === "relances" ? relanceList(followups, relanceDays) : messageList(messages, filter);
  };

  if (!emptyPage) paint();

  container.addEventListener("click", (event) => {
    const tab = event.target.closest("[data-filter]");
    if (tab) {
      filter = tab.dataset.filter;
      container.querySelectorAll("[data-filter]").forEach((item) => {
        const active = item === tab;
        item.classList.toggle("is-active", active);
        item.setAttribute("aria-selected", String(active));
      });
      paint();
      return;
    }

    const sync = event.target.closest("[data-sync]");
    if (sync) {
      syncMailbox(sync);
      return;
    }

    const messageRowElement = event.target.closest("[data-message-id]");
    if (messageRowElement) {
      const message = messages.find((item) => item.id === messageRowElement.dataset.messageId);
      if (message) openMessage(message, applications, ctx);
      return;
    }

    const mark = event.target.closest("[data-mark-followup]");
    if (mark) {
      event.stopPropagation();
      markFollowup(mark.dataset.markFollowup);
      return;
    }

    const open = event.target.closest("[data-open-followup]");
    if (open) {
      const item = followups.find((candidate) => candidate.application_id === open.dataset.openFollowup);
      if (item) openRelance(item, ctx);
    }
  });

  async function syncMailbox(button) {
    setLoading(button, true, "Synchronisation…");
    try {
      const result = await api.syncEmail();
      toast(
        result.created
          ? `${num(result.created)} nouveau${result.created > 1 ? "x" : ""} message${result.created > 1 ? "s" : ""}, ${num(result.matched)} rattachement${result.matched > 1 ? "s" : ""}.`
          : "Aucun nouveau message depuis la dernière synchronisation.",
        { title: "Boîte synchronisée" },
      );
      ctx.refresh();
    } catch (error) {
      setLoading(button, false);
      toast(errorMessage(error), { title: "Synchronisation impossible", type: "error" });
    }
  }

  async function markFollowup(applicationId) {
    try {
      await api.markFollowup(applicationId);
      toast("Cette candidature ne sera plus proposée en relance.", { title: "Relance enregistrée" });
      ctx.refresh();
    } catch (error) {
      toast(errorMessage(error), { title: "Action impossible", type: "error" });
    }
  }
}
