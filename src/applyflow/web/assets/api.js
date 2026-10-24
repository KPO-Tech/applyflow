export class ApiError extends Error {
  constructor(message, status, payload) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.payload = payload;
  }
}

function detailMessage(payload, fallback) {
  if (!payload) return fallback;
  const detail = payload.detail ?? payload;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    return detail
      .map((item) => {
        if (typeof item === "string") return item;
        const location = Array.isArray(item.loc) ? item.loc.slice(1).join(".") : "";
        const message = String(item.msg || item.message || "valeur invalide").replace(/^Value error, /, "");
        return `${location ? `${location} : ` : ""}${message}`;
      })
      .join(" ; ");
  }
  if (detail && typeof detail === "object") {
    return detail.message || JSON.stringify(detail);
  }
  return fallback;
}

async function request(path, { method = "GET", body, signal, form } = {}) {
  const options = { method, signal, headers: { Accept: "application/json" } };
  if (form) {
    options.body = form;
  } else if (body !== undefined) {
    options.headers["Content-Type"] = "application/json";
    options.body = JSON.stringify(body);
  }

  let response;
  try {
    response = await fetch(path, options);
  } catch (error) {
    if (error.name === "AbortError") throw error;
    throw new ApiError("Le serveur local ne répond pas. Vérifiez qu'ApplyFlow est lancé.", 0, null);
  }

  if (response.status === 204) return null;

  const contentType = response.headers.get("content-type") || "";
  const isJson = contentType.includes("application/json");
  const payload = isJson ? await response.json().catch(() => null) : null;

  if (!response.ok) {
    throw new ApiError(
      detailMessage(payload, `La requête a échoué (HTTP ${response.status}).`),
      response.status,
      payload,
    );
  }
  return payload;
}

function query(params) {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params || {})) {
    if (value !== undefined && value !== null && value !== "") search.set(key, value);
  }
  const text = search.toString();
  return text ? `?${text}` : "";
}

export const api = {
  health: () => request("/health"),
  dashboard: () => request("/dashboard"),

  profiles: () => request("/profiles"),
  createProfile: (payload) => request("/profiles", { method: "POST", body: payload }),
  updateProfile: (id, payload) => request(`/profiles/${id}`, { method: "PUT", body: payload }),
  deactivateProfile: (id) => request(`/profiles/${id}/deactivate`, { method: "POST" }),
  activateProfile: (id) => request(`/profiles/${id}/activate`, { method: "POST" }),
  uploadResume: (id, file) => {
    const form = new FormData();
    form.append("file", file);
    return request(`/profiles/${id}/resumes`, { method: "POST", form });
  },

  jobs: (params = {}, signal) => request(`/jobs${query(params)}`, { signal }),
  job: (id, signal) => request(`/jobs/${id}`, { signal }),
  importJobs: (jobs) => request("/jobs/import", { method: "POST", body: { jobs } }),
  discovery: (payload, signal) => request("/discovery", { method: "POST", body: payload, signal }),
  startDiscovery: (payload) => request("/discovery/start", { method: "POST", body: payload }),
  discoveryTask: (id, signal) => request(`/discovery/tasks/${id}`, { signal }),
  activeDiscovery: (signal) => request("/discovery/tasks/active", { signal }),
  cancelDiscovery: (id) => request(`/discovery/tasks/${id}/cancel`, { method: "POST" }),
  sources: () => request("/sources"),
  jobCountries: (signal) => request("/jobs/countries", { signal }),
  countries: () => request("/countries"),
  contracts: () => request("/contracts"),
  collectionUsage: (signal) => request("/collection/usage", { signal }),
  testAdzuna: (payload = {}) =>
    request("/sources/adzuna/test", { method: "POST", body: payload }),

  campaigns: (signal) => request("/campaigns", { signal }),
  campaign: (id, signal) => request(`/campaigns/${id}`, { signal }),
  createCampaign: (payload) => request("/campaigns", { method: "POST", body: payload }),
  pauseCampaign: (id) => request(`/campaigns/${id}/pause`, { method: "POST" }),
  resumeCampaign: (id) => request(`/campaigns/${id}/resume`, { method: "POST" }),
  cancelCampaign: (id) => request(`/campaigns/${id}/cancel`, { method: "POST" }),
  runCampaign: (id, maxItems, steps = ["discover", "analyze", "prepare"], redo = false, minScore = null) =>
    request(`/campaigns/${id}/run`, {
      method: "POST",
      body: { steps, max_items: maxItems, redo, min_score: minScore },
    }),
  startCampaign: (id, maxItems, steps = ["discover", "analyze", "prepare"], redo = false, minScore = null) =>
    request(`/campaigns/${id}/run/start`, {
      method: "POST",
      body: { steps, max_items: maxItems, redo, min_score: minScore },
    }),
  campaignTask: (taskId, signal) => request(`/campaigns/tasks/${taskId}`, { signal }),
  activeCampaignTask: (signal) => request("/campaigns/tasks/active", { signal }),
  cancelCampaignTask: (taskId) => request(`/campaigns/tasks/${taskId}/cancel`, { method: "POST" }),
  campaignResults: (id, signal) => request(`/campaigns/${id}/results`, { signal }),
  campaignExportUrl: (id, format = "csv") => `/campaigns/${id}/export?fmt=${format}`,

  queue: (signal) => request("/queue", { signal }),
  prepareAttempt: (id) => request(`/queue/${id}/prepare`, { method: "POST" }),
  approveAttempt: (id) => request(`/queue/${id}/approve`, { method: "POST" }),
  submitAttempt: (id, reference = null) =>
    request(`/queue/${id}/submit`, {
      method: "POST",
      body: { confirmed: true, reference: reference || null },
    }),

  answers: (signal) => request("/answers", { signal }),
  saveAnswer: (payload) => request("/answers", { method: "POST", body: payload }),

  applications: (signal) => request("/applications", { signal }),
  updateApplication: (id, status) =>
    request(`/applications/${id}`, { method: "PATCH", body: { status } }),

  emailStatus: (signal) => request("/email/status", { signal }),
  connectEmail: (payload) => request("/email/connect", { method: "POST", body: payload }),
  testEmail: () => request("/email/test", { method: "POST" }),
  disconnectEmail: () => request("/email/disconnect", { method: "POST" }),
  syncEmail: () => request("/email/sync", { method: "POST" }),
  emailMessages: (scope = "all", signal) =>
    request(`/email/messages${query({ scope })}`, { signal }),
  updateEmailMessage: (id, payload) =>
    request(`/email/messages/${id}`, { method: "PATCH", body: payload }),
  followups: (signal) => request("/email/followups", { signal }),
  markFollowup: (applicationId) =>
    request(`/email/followups/${applicationId}/mark`, { method: "POST" }),

  settings: (signal) => request("/settings", { signal }),
  saveSettings: (payload) => request("/settings", { method: "PUT", body: payload }),
};
