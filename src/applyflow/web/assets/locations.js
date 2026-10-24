// Choix de lieux : plusieurs pays pris dans la liste officielle (ISO 3166-1) avec
// autocomplétion et vérification, plus des villes ou régions en texte libre.
import { api } from "./api.js";
import { esc, splitList } from "./ui.js";

let catalogPromise = null;
let lookup = null;

// Même normalisation que le serveur : sans accents, minuscules, ponctuation neutralisée.
export function normalizeText(value) {
  return String(value || "")
    .normalize("NFD")
    .replace(/[̀-ͯ]/g, "")
    .toLowerCase()
    .replace(/[’]/g, "'")
    .replace(/[–—]/g, "-")
    .replace(/[^a-z0-9+#.\-\s]/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

export function loadCountries() {
  if (!catalogPromise) {
    catalogPromise = api.countries().then((catalog) => {
      lookup = new Map();
      for (const country of catalog) {
        for (const text of [country.name_fr, country.name, ...(country.aliases || [])]) {
          const key = normalizeText(text);
          if (key && !lookup.has(key)) lookup.set(key, country);
        }
        lookup.set(country.code.toLowerCase(), country); // « de », « fr »…
      }
      return catalog;
    });
    catalogPromise.catch(() => {
      catalogPromise = null; // réessayer à la prochaine ouverture
    });
  }
  return catalogPromise;
}

// Pays correspondant à un texte saisi (nom français, anglais, écriture locale ou code), ou null.
export function matchCountry(text) {
  if (!lookup) return null;
  return lookup.get(normalizeText(text)) || null;
}

function ensureDatalist(catalog) {
  if (document.getElementById("country-options")) return;
  const list = document.createElement("datalist");
  list.id = "country-options";
  list.innerHTML = catalog
    .map((country) => `<option value="${esc(country.name_fr)}" label="${esc(country.name)}"></option>`)
    .join("");
  document.body.appendChild(list);
}

function chipHtml(country) {
  return `<span class="chip chip--tag loc-chip" data-code="${esc(country.code)}" data-name="${esc(country.name)}">
    ${esc(country.name_fr)}
    <button type="button" class="chip-x" data-remove-country aria-label="Retirer ${esc(country.name_fr)}">×</button>
  </span>`;
}

// HTML du sélecteur. `values` : lieux déjà enregistrés (pays et villes mélangés).
export function locationPickerHtml({ id, values = [], countryHint, cityHint }) {
  return `<div class="loc-picker" data-loc-picker data-initial="${esc(JSON.stringify(values))}">
    <div class="loc-chips" data-chips aria-live="polite"></div>
    <input class="input" id="${esc(id)}" data-country-input list="country-options" autocomplete="off"
      placeholder="${esc(countryHint || "Ajouter un pays : Allemagne, Canada, Japon…")}" aria-label="Ajouter un pays" />
    <span class="hint loc-error" data-country-error hidden></span>
    <input class="input" data-cities autocomplete="off"
      placeholder="${esc(cityHint || "Villes ou régions, séparées par des virgules (Paris, Lyon, Remote)")}" aria-label="Villes ou régions" />
  </div>`;
}

function addCountry(picker, country) {
  const chips = picker.querySelector("[data-chips]");
  if ([...chips.children].some((chip) => chip.dataset.code === country.code)) return false;
  chips.insertAdjacentHTML("beforeend", chipHtml(country));
  return true;
}

function showError(picker, message) {
  const box = picker.querySelector("[data-country-error]");
  box.textContent = message || "";
  box.hidden = !message;
  picker.querySelector("[data-country-input]").setAttribute("aria-invalid", message ? "true" : "false");
}

// Valide le texte en attente dans le champ pays : ajoute le pays s'il est officiel, sinon signale.
function commit(picker) {
  const input = picker.querySelector("[data-country-input]");
  const text = input.value.trim();
  if (!text) {
    showError(picker, "");
    return true;
  }
  const country = matchCountry(text);
  if (!country) {
    showError(picker, `« ${text} » n'est pas dans la liste officielle des pays. Choisissez une suggestion.`);
    return false;
  }
  addCountry(picker, country);
  input.value = "";
  showError(picker, "");
  return true;
}

// À appeler une fois le HTML inséré dans la page : charge la liste, place les pays existants.
export async function mountLocationPickers(root) {
  const catalog = await loadCountries().catch(() => null);
  if (catalog) ensureDatalist(catalog);
  for (const picker of root.querySelectorAll("[data-loc-picker]")) {
    if (picker.dataset.ready) continue;
    picker.dataset.ready = "true";
    const cities = [];
    let initial = [];
    try {
      initial = JSON.parse(picker.dataset.initial || "[]");
    } catch {
      initial = [];
    }
    for (const value of initial) {
      const country = matchCountry(value);
      if (country) addCountry(picker, country);
      else cities.push(value);
    }
    picker.querySelector("[data-cities]").value = cities.join(", ");

    const input = picker.querySelector("[data-country-input]");
    input.addEventListener("change", () => commit(picker)); // choix d'une suggestion
    input.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === ",") {
        event.preventDefault();
        commit(picker);
      }
    });
    input.addEventListener("input", () => showError(picker, ""));
    picker.addEventListener("click", (event) => {
      const remove = event.target.closest("[data-remove-country]");
      if (remove) remove.closest(".loc-chip").remove();
    });
  }
}

// Valeurs du sélecteur : noms anglais des pays choisis, puis villes. Retourne
// { values, error } ; `error` est renseigné si un texte saisi n'est pas un pays officiel.
export function readLocations(picker) {
  if (!picker.dataset.ready) {
    // Liste pas encore chargée : on rend les valeurs d'origine plutôt que de les perdre.
    try {
      return { values: JSON.parse(picker.dataset.initial || "[]"), error: "" };
    } catch {
      return { values: [], error: "" };
    }
  }
  const ok = commit(picker);
  const countries = [...picker.querySelectorAll(".loc-chip")].map((chip) => chip.dataset.name);
  const cities = splitList(picker.querySelector("[data-cities]").value);
  return {
    values: [...new Set([...countries, ...cities])],
    error: ok ? "" : "Un pays saisi n'est pas dans la liste officielle : choisissez-en un dans les suggestions ou effacez le champ.",
  };
}
