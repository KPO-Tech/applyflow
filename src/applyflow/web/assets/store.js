export const store = {
  settings: null,
  health: null,
  sources: [],
  counts: { queue: 0, applications: 0 },
};

export function navigate(path, { replace = false } = {}) {
  const target = `#/${String(path).replace(/^#?\/?/, "")}`;
  if (replace) {
    history.replaceState(null, "", target);
    window.dispatchEvent(new HashChangeEvent("hashchange"));
  } else if (window.location.hash === target) {
    window.dispatchEvent(new HashChangeEvent("hashchange"));
  } else {
    window.location.hash = target;
  }
}

export function notifyChanged() {
  window.dispatchEvent(new CustomEvent("applyflow:changed"));
}
