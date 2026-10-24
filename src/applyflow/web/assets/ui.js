import { icon } from "./icons.js";

const NUMBER = new Intl.NumberFormat("fr-FR");
const DATE = new Intl.DateTimeFormat("fr-FR", { day: "numeric", month: "short", year: "numeric" });
const DATE_SHORT = new Intl.DateTimeFormat("fr-FR", { day: "2-digit", month: "2-digit" });

export function esc(value) {
  return String(value ?? "").replace(/[&<>"']/g, (char) => {
    switch (char) {
      case "&":
        return "&amp;";
      case "<":
        return "&lt;";
      case ">":
        return "&gt;";
      case '"':
        return "&quot;";
      default:
        return "&#39;";
    }
  });
}

export function raw(value) {
  return value;
}

export function safeUrl(value) {
  if (!value) return "#";
  try {
    const url = new URL(String(value), window.location.origin);
    if (url.protocol === "http:" || url.protocol === "https:") return url.href;
  } catch {
    return "#";
  }
  return "#";
}

export function num(value) {
  return NUMBER.format(Number(value) || 0);
}

export function pct(value, total) {
  if (!total) return 0;
  return Math.round((Number(value) / Number(total)) * 100);
}

export function formatDate(value, short = false) {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  return (short ? DATE_SHORT : DATE).format(date);
}

export function plural(count, singular, pluralForm = `${singular}s`) {
  return `${count} ${count > 1 ? pluralForm : singular}`;
}

export function initials(name) {
  const parts = String(name || "?")
    .trim()
    .split(/\s+/)
    .filter(Boolean);
  if (!parts.length) return "?";
  return (parts[0][0] + (parts.length > 1 ? parts[parts.length - 1][0] : "")).toUpperCase();
}

export function splitList(value) {
  return [
    ...new Set(
      String(value || "")
        .split(/[,;\n]/)
        .map((item) => item.trim())
        .filter(Boolean),
    ),
  ];
}

export function listText(value, fallback = "Non précisé") {
  if (Array.isArray(value)) return value.length ? value.join(" · ") : fallback;
  return value || fallback;
}

export const LEVELS = {
  intern: "Stage / alternance",
  entry: "Entry level",
  junior: "Junior",
  mid: "Confirmé",
  senior: "Senior",
};

export const ATTEMPT_STATUS = {
  prepared: { label: "Prête", tone: "sage" },
  needs_review: { label: "À compléter", tone: "amber" },
  manual: { label: "À postuler à la main", tone: "blue" },
  blocked: { label: "Bloquée", tone: "red" },
  approved: { label: "Validée", tone: "blue" },
  submitted: { label: "Soumise", tone: "sage" },
  failed: { label: "Échec", tone: "red" },
};

export const CAMPAIGN_STATUS = {
  draft: { label: "Brouillon", tone: "plain" },
  running: { label: "En cours", tone: "amber" },
  paused: { label: "En pause", tone: "blue" },
  completed: { label: "Terminée", tone: "sage" },
  cancelled: { label: "Annulée", tone: "red" },
};

export const APPLICATION_STATUS = {
  prepared: { label: "Préparée", tone: "plain" },
  submitted: { label: "Soumise", tone: "sage" },
  interview: { label: "Entretien", tone: "blue" },
  offer: { label: "Offre", tone: "sage" },
  rejected: { label: "Refusée", tone: "red" },
  withdrawn: { label: "Retirée", tone: "plain" },
};

export const STAGES = {
  discovered: { label: "Collectée", tone: "plain" },
  analyzed: { label: "Analysée", tone: "blue" },
  rejected: { label: "Écartée", tone: "plain" },
  prepared: { label: "Préparée", tone: "sage" },
  needs_review: { label: "À compléter", tone: "amber" },
  manual: { label: "À la main", tone: "blue" },
  blocked: { label: "Bloquée", tone: "red" },
  duplicate: { label: "Doublon", tone: "plain" },
  approved: { label: "Validée", tone: "blue" },
  submitted: { label: "Soumise", tone: "sage" },
};

export function statusChip(status, map = ATTEMPT_STATUS, extra = "") {
  const meta = map[status] || { label: status || "Inconnu", tone: "plain" };
  return `<span class="chip chip--${esc(meta.tone)} ${extra}">${esc(meta.label)}</span>`;
}

export function scoreBadge(score) {
  const value = Number(score);
  if (!Number.isFinite(value)) return `<span class="score score--low">—</span>`;
  const tone = value >= 80 ? "" : value >= 65 ? " score--mid" : " score--low";
  return `<span class="score${tone}">${Math.round(value)}</span>`;
}

export function emptyState({ iconName = "info", title, text, action = "", small = false }) {
  return `<div class="empty ${small ? "empty--sm" : ""}">
    <span class="empty-icon">${icon(iconName)}</span>
    <h3>${esc(title)}</h3>
    <p>${esc(text)}</p>
    ${action}
  </div>`;
}

export function skeletonPage() {
  return `<div class="skeleton-page" aria-busy="true" aria-label="Chargement">
    <div class="skeleton skeleton-head"></div>
    <div class="skeleton skeleton-line"></div>
    <div class="skeleton skeleton-metrics"></div>
    <div class="skeleton skeleton-hero"></div>
    <div class="skeleton-grid">
      <div class="skeleton"></div>
      <div class="skeleton"></div>
    </div>
  </div>`;
}

export function sectionHead(title, sub = "", action = "") {
  return `<div class="section-head">
    <div><h2 class="section-title">${esc(title)}</h2>${sub ? `<p class="section-sub">${esc(sub)}</p>` : ""}</div>
    ${action}
  </div>`;
}

export function toast(message, { title = "", type = "success", duration = 4800 } = {}) {
  const region = document.getElementById("toast-region");
  if (!region) return;
  const element = document.createElement("div");
  element.className = `toast toast--${type}`;
  element.setAttribute("role", type === "error" ? "alert" : "status");
  const iconName = type === "error" ? "alert" : type === "warn" ? "alert" : "checkCircle";
  element.innerHTML = `
    ${icon(iconName)}
    <div>${title ? `<strong>${esc(title)}</strong>` : ""}<p>${esc(message)}</p></div>
    <button class="toast-close" type="button" aria-label="Fermer la notification">×</button>`;
  region.append(element);

  const remove = () => {
    if (!element.isConnected) return;
    element.classList.add("is-leaving");
    window.setTimeout(() => element.remove(), 190);
  };
  element.querySelector(".toast-close").addEventListener("click", remove);
  const timer = window.setTimeout(remove, duration);
  element.addEventListener("mouseenter", () => window.clearTimeout(timer), { once: true });
  return element;
}

export function openModal({
  title,
  subtitle = "",
  body,
  footer,
  wide = false,
  drawer = false,
  onMount,
}) {
  const root = document.getElementById("modal-root");
  const dialog = document.createElement("dialog");
  dialog.className = `dialog ${wide ? "dialog--wide" : ""} ${drawer ? "dialog--drawer" : ""}`;
  dialog.innerHTML = `
    <div class="dialog-form">
      <header class="dialog-head">
        <div>
          <h2>${esc(title)}</h2>
          ${subtitle ? `<p>${esc(subtitle)}</p>` : ""}
        </div>
        <button class="close-btn" type="button" data-close aria-label="Fermer">${icon("close")}</button>
      </header>
      <div class="dialog-body">${body}</div>
      ${footer ? `<footer class="dialog-foot">${footer}</footer>` : ""}
    </div>`;
  root.append(dialog);

  const close = () => {
    if (dialog.open) dialog.close();
    dialog.remove();
  };
  dialog.addEventListener("click", (event) => {
    if (event.target === dialog) close();
  });
  dialog.addEventListener("cancel", (event) => {
    event.preventDefault();
    close();
  });
  dialog.querySelectorAll("[data-close]").forEach((button) => {
    button.addEventListener("click", close);
  });
  dialog._close = close;
  dialog.showModal();
  if (onMount) onMount(dialog, close);
  return dialog;
}

export function confirmDialog({
  title,
  message,
  details = "",
  confirmLabel = "Confirmer",
  cancelLabel = "Annuler",
  danger = false,
}) {
  return new Promise((resolve) => {
    let settled = false;
    const finish = (value) => {
      if (settled) return;
      settled = true;
      resolve(value);
    };
    const dialog = openModal({
      title,
      subtitle: "Cette action demande une confirmation explicite.",
      body: `<div class="confirm-body">
        <p>${esc(message)}</p>
        ${details ? `<div class="mt-16">${details}</div>` : ""}
      </div>`,
      footer: `<button class="btn btn--ghost" type="button" data-cancel>${esc(cancelLabel)}</button>
        <button class="btn ${danger ? "btn--danger" : "btn--primary"}" type="button" data-confirm>${esc(confirmLabel)}</button>`,
      onMount: (element, close) => {
        element.querySelector("[data-cancel]").addEventListener("click", () => {
          finish(false);
          close();
        });
        element.querySelector("[data-confirm]").addEventListener("click", () => {
          finish(true);
          close();
        });
        element.addEventListener("close", () => finish(false));
        const confirmButton = element.querySelector("[data-confirm]");
        if (!danger) confirmButton.focus();
      },
    });
    dialog.addEventListener("remove", () => finish(false));
  });
}

export function setLoading(button, loading, label = "Traitement…") {
  if (!button) return;
  if (loading) {
    // Idempotent : un second appel ne doit pas mémoriser l'état « en cours » comme état normal.
    if (!button.classList.contains("is-busy")) button.dataset.originalHtml = button.innerHTML;
    button.disabled = true;
    button.classList.add("is-busy");
    button.innerHTML = `<span class="btn-spinner" aria-hidden="true"></span>${esc(label)}`;
  } else {
    button.disabled = false;
    button.classList.remove("is-busy");
    if (button.dataset.originalHtml) {
      button.innerHTML = button.dataset.originalHtml;
      delete button.dataset.originalHtml;
    }
  }
}

export function debounce(fn, delay = 300) {
  let timer;
  return (...args) => {
    window.clearTimeout(timer);
    timer = window.setTimeout(() => fn(...args), delay);
  };
}

export function errorMessage(error) {
  if (!error) return "Une erreur inconnue est survenue.";
  return error.message || String(error);
}

export function fieldError(form, message) {
  let box = form.querySelector(".form-error");
  if (!box) {
    box = document.createElement("div");
    box.className = "form-error";
    form.prepend(box);
  }
  box.textContent = message;
  box.classList.add("is-visible");
  box.setAttribute("role", "alert");
}

export function clearFieldError(form) {
  const box = form?.querySelector(".form-error");
  if (box) {
    box.textContent = "";
    box.classList.remove("is-visible");
  }
}

export function formDataObject(form) {
  return Object.fromEntries(new FormData(form).entries());
}

export function relativeDay(value) {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  const days = Math.round((Date.now() - date.getTime()) / 86_400_000);
  if (days <= 0) return "aujourd'hui";
  if (days === 1) return "hier";
  if (days < 7) return `il y a ${days} jours`;
  return formatDate(value);
}

export function truncate(value, length = 90) {
  const text = String(value || "");
  return text.length > length ? `${text.slice(0, length - 1)}…` : text;
}
