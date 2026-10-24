import { api } from "./api.js";
import { icon } from "./icons.js";
import { navigate, store } from "./store.js";
import { debounce, esc, errorMessage, skeletonPage } from "./ui.js";
import * as dashboard from "./pages/dashboard.js";
import * as campaigns from "./pages/campaigns.js";
import * as queue from "./pages/queue.js";
import * as applications from "./pages/applications.js";
import * as emails from "./pages/emails.js";
import * as profiles from "./pages/profiles.js";
import * as discovery from "./pages/discovery.js";
import * as settings from "./pages/settings.js";

const NAV = [
  {
    label: "Pilotage",
    items: [
      { id: "dashboard", label: "Tableau de bord", icon: "dashboard", page: dashboard },
      { id: "campagnes", label: "Campagnes", icon: "campaigns", page: campaigns },
    ],
  },
  {
    label: "Candidatures",
    items: [
      { id: "validation", label: "File de validation", icon: "queue", page: queue, count: "queue" },
      {
        id: "candidatures",
        label: "Candidatures",
        icon: "applications",
        page: applications,
        count: "applications",
      },
      { id: "emails", label: "Suivi e-mail", icon: "mail", page: emails },
    ],
  },
  {
    label: "Recherche",
    items: [
      { id: "profils", label: "Profils & CV", icon: "profiles", page: profiles },
      { id: "decouverte", label: "Découverte", icon: "discovery", page: discovery },
    ],
  },
  {
    label: "Système",
    items: [{ id: "reglages", label: "Réglages", icon: "settings", page: settings }],
  },
];

const ROUTES = NAV.flatMap((group) => group.items);
const TITLES = Object.fromEntries(ROUTES.map((route) => [route.id, route.label]));

let currentRoute = "dashboard";
let routeToken = 0;
let cleanupPage = null;
let controller = null;
let progressTimer = null;

function setTheme(theme) {
  document.documentElement.dataset.theme = theme;
  try {
    localStorage.setItem("applyflow-theme", theme);
  } catch {
    /* stockage indisponible : le thème reste valable pour la session */
  }
  const button = document.getElementById("theme-toggle");
  if (button) {
    button.setAttribute(
      "aria-label",
      theme === "dark" ? "Passer au thème clair" : "Passer au thème sombre",
    );
  }
}

function initTheme() {
  let theme = null;
  try {
    theme = localStorage.getItem("applyflow-theme");
  } catch {
    theme = null;
  }
  if (!theme) {
    theme = window.matchMedia?.("(prefers-color-scheme: dark)").matches ? "dark" : "light";
  }
  setTheme(theme);
  document.getElementById("theme-toggle")?.addEventListener("click", () => {
    setTheme(document.documentElement.dataset.theme === "dark" ? "light" : "dark");
  });
}

function parseRoute() {
  const raw = window.location.hash.replace(/^#\/?/, "") || "dashboard";
  const [path, search = ""] = raw.split("?");
  const [id, section = ""] = path.split("/").filter(Boolean);
  return {
    id: id || "dashboard",
    section,
    query: new URLSearchParams(search),
  };
}

function renderNav(activeId = currentRoute) {
  const container = document.getElementById("nav");
  if (!container) return;
  container.innerHTML = NAV.map(
    (group) => `
      <div class="nav-group">
        <div class="nav-label">${esc(group.label)}</div>
        ${group.items
          .map((item) => {
            const count = item.count ? store.counts[item.count] : 0;
            return `<a class="nav-link" href="#/${item.id}" data-nav-id="${item.id}" ${
              item.id === activeId ? 'aria-current="page"' : ""
            }>
              ${icon(item.icon)}
              <span>${esc(item.label)}</span>
              ${count ? `<span class="nav-count">${count}</span>` : ""}
            </a>`;
          })
          .join("")}
      </div>`,
  ).join("");
}

function updateSettingsUI() {
  const settings = store.settings;
  if (!settings) return;
  const isDryRun = settings.application?.dry_run !== false;
  document.querySelectorAll(".js-mode-label").forEach((element) => {
    element.textContent = isDryRun ? "Dry-run" : "Live";
  });
  document.querySelectorAll(".js-mode-chip").forEach((element) => {
    element.textContent = isDryRun ? "Dry-run" : "Live";
    element.classList.toggle("chip--amber", !isDryRun);
    element.classList.toggle("chip--sage", isDryRun);
  });
  document.querySelectorAll(".js-mode-pill").forEach((element) => {
    element.classList.toggle("is-live", !isDryRun);
    element.title = isDryRun
      ? "Mode dry-run : aucune candidature n'est envoyée automatiquement"
      : "Mode live : la soumission reste une action humaine";
  });
  const version = document.querySelector(".js-version");
  if (version) version.textContent = `ApplyFlow ${store.health?.version || ""}`.trim();
  const jobs = document.querySelector(".js-job-count");
  if (jobs) jobs.textContent = `${store.health?.jobs ?? 0} offres`;
}

async function refreshCounts() {
  try {
    const [queueItems, applicationItems] = await Promise.all([api.queue(), api.applications()]);
    store.counts.queue = queueItems.filter((item) =>
      ["prepared", "needs_review", "manual", "approved"].includes(item.status),
    ).length;
    store.counts.applications = applicationItems.filter((item) =>
      ["prepared", "submitted", "interview", "offer"].includes(item.status),
    ).length;
    renderNav(currentRoute);
  } catch {
    /* les compteurs sont un confort, pas un prérequis */
  }
}

function setNavActive(id) {
  currentRoute = id;
  document.querySelectorAll("[data-nav-id]").forEach((link) => {
    if (link.dataset.navId === id) link.setAttribute("aria-current", "page");
    else link.removeAttribute("aria-current");
  });
  const section = document.getElementById("current-section");
  if (section) section.textContent = TITLES[id] || "ApplyFlow";
  // La page Campagnes porte sa propre action primaire : pas de doublon dans la barre.
  const topbarCta = document.getElementById("topbar-cta");
  if (topbarCta) topbarCta.hidden = id === "campagnes";
}

function showProgress(done = false) {
  const progress = document.getElementById("route-progress");
  if (!progress) return;
  window.clearTimeout(progressTimer);
  progress.classList.remove("is-loading", "is-done");
  if (done) {
    progress.classList.add("is-done");
    progressTimer = window.setTimeout(() => progress.classList.remove("is-done"), 420);
  } else {
    // force the browser to restart the CSS transition on repeated navigations
    void progress.offsetWidth;
    progress.classList.add("is-loading");
  }
}

function renderFatal(error) {
  const view = document.getElementById("view");
  if (!view) return;
  view.innerHTML = `<div class="error-page" role="alert">
    <span class="empty-icon">${icon("alert")}</span>
    <h1>Le serveur local ne répond pas.</h1>
    <p>${esc(errorMessage(error))}</p>
    <p class="small mt-16">Vérifiez que <span class="mono">applyflow serve-ui</span> est toujours en cours d'exécution, puis réessayez.</p>
    <button class="btn btn--primary" type="button" id="fatal-retry">${icon("refresh")} Réessayer</button>
  </div>`;
  document.getElementById("fatal-retry")?.addEventListener("click", () => window.location.reload());
}

function renderNotFound() {
  const view = document.getElementById("view");
  if (!view) return;
  view.innerHTML = `<div class="error-page">
    <span class="empty-icon">${icon("search")}</span>
    <h1>Cette page n'existe pas.</h1>
    <p>Le lien est peut-être incomplet. Revenez au tableau de bord pour reprendre la main.</p>
    <a class="btn btn--primary" href="#/dashboard">${icon("dashboard")} Ouvrir le tableau de bord</a>
  </div>`;
}

async function route() {
  const { id, section, query } = parseRoute();
  const page = ROUTES.find((item) => item.id === id);
  if (!page) {
    renderNotFound();
    return;
  }

  const token = ++routeToken;
  controller?.abort();
  controller = new AbortController();
  document.querySelectorAll("#modal-root dialog").forEach((dialog) => {
    try {
      if (dialog.open) dialog.close();
    } finally {
      dialog.remove();
    }
  });
  if (cleanupPage) {
    try {
      cleanupPage();
    } catch {
      /* le nettoyage ne doit jamais bloquer la navigation */
    }
    cleanupPage = null;
  }

  setNavActive(id);
  document.title = `${page.label} · ApplyFlow`;
  showProgress();
  // Replace the view node so page-level delegated listeners cannot leak
  // from one screen into the next.
  const previousView = document.getElementById("view");
  const view = previousView.cloneNode(false);
  previousView.replaceWith(view);
  view.innerHTML = skeletonPage();
  window.scrollTo({ top: 0, behavior: "auto" });
  view.focus({ preventScroll: true });

  try {
    const cleanup = await page.page.render(view, {
      query,
      section,
      signal: controller.signal,
      navigate,
      refresh: route,
    });
    if (token !== routeToken) return;
    cleanupPage = typeof cleanup === "function" ? cleanup : null;
    showProgress(true);
  } catch (error) {
    if (error.name === "AbortError" || token !== routeToken) return;
    showProgress(true);
    view.innerHTML = `<div class="error-page" role="alert">
      <span class="empty-icon">${icon("alert")}</span>
      <h1>Impossible de charger cette page.</h1>
      <p>${esc(errorMessage(error))}</p>
      <button class="btn btn--primary" type="button" id="page-retry">${icon("refresh")} Réessayer</button>
    </div>`;
    document.getElementById("page-retry")?.addEventListener("click", () => route());
  }
}

function initShell() {
  const menu = document.getElementById("menu-toggle");
  const scrim = document.getElementById("sidebar-scrim");
  const closeNav = () => {
    document.body.classList.remove("nav-open");
    menu?.setAttribute("aria-expanded", "false");
    if (scrim) scrim.hidden = true;
  };
  const openNav = () => {
    document.body.classList.add("nav-open");
    menu?.setAttribute("aria-expanded", "true");
    if (scrim) scrim.hidden = false;
    document.querySelector("#nav .nav-link")?.focus();
  };

  menu?.addEventListener("click", () => {
    if (document.body.classList.contains("nav-open")) closeNav();
    else openNav();
  });
  scrim?.addEventListener("click", closeNav);
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && document.body.classList.contains("nav-open")) closeNav();
  });
  window.addEventListener("resize", () => {
    if (window.innerWidth > 980) closeNav();
  });
  document.addEventListener("click", (event) => {
    if (event.target.closest("#nav a")) closeNav();
  });

  document.querySelectorAll('a[href="#/campagnes?new=1"]').forEach((link) => {
    link.addEventListener("click", (event) => {
      if (window.location.hash === "#/campagnes?new=1") {
        event.preventDefault();
        navigate("campagnes?new=1");
      }
    });
  });

  window.addEventListener("hashchange", () => {
    route().catch((error) => renderFatal(error));
  });
  window.addEventListener("applyflow:settings", () => updateSettingsUI());
  window.addEventListener(
    "applyflow:changed",
    debounce(() => {
      refreshCounts();
      if (currentRoute === "dashboard") {
        // the dashboard refreshes itself when it is the current page
        route().catch(() => {});
      }
    }, 120),
  );
}

async function boot() {
  initTheme();
  initShell();
  try {
    const [settings, health] = await Promise.all([api.settings(), api.health()]);
    store.settings = settings;
    store.health = health;
    try {
      store.sources = await api.sources();
    } catch {
      store.sources = [];
    }
    updateSettingsUI();
    renderNav("dashboard");
    await route();
    refreshCounts();
  } catch (error) {
    renderFatal(error);
  }
}

boot();
