"""Empreintes de dédoublonnage interplateformes."""

from __future__ import annotations

import hashlib
import re
from difflib import SequenceMatcher
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from applyflow.text import normalize_text

_LEGAL_SUFFIXES = {
    "inc",
    "ltd",
    "limited",
    "llc",
    "gmbh",
    "sas",
    "sa",
    "sarl",
    "bv",
    "ag",
    "plc",
    "corp",
    "corporation",
    "group",
    "holding",
}

_TRACKING_PARAMS = {
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_term",
    "utm_content",
    "gh_src",
    "lever-source",
    "lever-origin",
    "ref",
    "source",
    "fbclid",
    "gclid",
}

# Paramètres qui identifient l'offre elle-même (Indeed : jk/vjk, Glassdoor : jl, LinkedIn : currentJobId).
_ID_PARAMS = {
    "id", "jobid", "job_id", "gh_jid", "jid", "posting", "postingid", "job",
    "jk", "vjk", "jl", "currentjobid", "reqid", "requisitionid",
}


def normalize_company(value: str) -> str:
    tokens = [
        token
        for token in normalize_text(value).split()
        if token not in _LEGAL_SUFFIXES and token not in {"the"}
    ]
    return " ".join(tokens)


_NON_CITY = {
    "france", "ile de france", "region parisienne", "idf", "remote", "hybride", "hybrid",
    "teletravail", "unspecified", "emea", "europe", "union europeenne", "european union",
}
_SPLIT_RE = re.compile(r"[,;/|]|\s+-\s+|\(|\)")


def city_of(value: str | None) -> str:
    """Ville principale d'une localisation : « Paris, A8, France » et « Paris, Île-de-France,
    France » donnent toutes deux « paris ». Vide si seule une région/un pays est indiqué."""
    if not value:
        return ""
    for part in _SPLIT_RE.split(value):
        segment = normalize_text(part)
        segment = re.sub(r"\b\d{2,5}\b", " ", segment)  # code postal ou département
        segment = re.sub(r"\b\d{1,2}\s*(?:e|er|eme|eme arrondissement|arr)\b", " ", segment)
        segment = re.sub(r"\s+", " ", segment).strip()
        if not segment or segment in _NON_CITY:
            continue
        if re.fullmatch(r"[a-z]{1,2}\d{1,3}", segment):  # nom d'autoroute (A8, N118…)
            continue
        return segment
    return ""


def normalize_location(value: str | None) -> str:
    return city_of(value)


def job_fingerprint(company: str, title: str, location: str | None) -> str:
    """Identité métier indépendante de la plateforme source."""
    # Les intitulés H/F, (m/f/d), etc. ne doivent pas créer de doublons. On retire
    # les marqueurs avant la normalisation, car « / » devient un espace ensuite.
    cleaned_title = re.sub(
        r"[\(\[]?\b(?:h\s*[/|]\s*f|f\s*[/|]\s*h|m\s*[/|]\s*[fw]\s*[/|]\s*d|h\s*[/|]\s*f\s*[/|]\s*x)\b[\)\]]?",
        " ",
        title,
        flags=re.IGNORECASE,
    )
    canonical_title = normalize_text(cleaned_title)
    canonical_title = re.sub(r"\b(?:h f|f h|m f d|m w d|h f x)\b", " ", canonical_title)
    canonical_title = re.sub(r"\s+", " ", canonical_title).strip()
    payload = "|".join(
        [normalize_company(company), canonical_title.strip(), normalize_location(location)]
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def canonical_url(url: str) -> str:
    if url.startswith("demo://"):
        return url.rstrip("/").lower()
    parsed = urlparse(url)
    if not parsed.scheme:
        return url.strip().lower()
    host = (parsed.hostname or "").lower().removeprefix("www.")
    path = re.sub(r"/+$", "", parsed.path) or "/"
    kept_params = [
        (key, value)
        for key, value in parse_qsl(parsed.query, keep_blank_values=False)
        if key.lower() in _ID_PARAMS
    ]
    query = urlencode(sorted(kept_params))
    return urlunparse((parsed.scheme.lower(), host, path, "", query, ""))


def url_key(url: str) -> str:
    return hashlib.sha256(canonical_url(url).encode("utf-8")).hexdigest()


# --- Comparaison approchée (même entreprise et même ville, titres/descriptions proches) ---

_LEVEL_WORDS = {"junior", "senior", "lead", "principal", "staff", "stage", "stagiaire",
                "alternance", "alternant", "intern", "internship", "graduate", "confirme",
                "expert", "head", "manager", "debutant"}
_TITLE_NOISE = re.compile(r"\b(?:h f|f h|m f d|m w d|h f x|cdi|cdd|stage|alternance)\b")


def canonical_title(title: str) -> str:
    cleaned = normalize_text(re.sub(r"[/|]", " ", title))
    return re.sub(r"\s+", " ", _TITLE_NOISE.sub(" ", cleaned)).strip()


def _levels(title: str) -> set[str]:
    return set(normalize_text(title).split()) & _LEVEL_WORDS


def _shingles(text: str, size: int = 5) -> set[str]:
    words = normalize_text(text).split()[:400]
    return {" ".join(words[i : i + size]) for i in range(max(1, len(words) - size + 1))}


def description_similarity(left: str, right: str) -> float:
    """Jaccard sur des séquences de 5 mots (0 si une description est trop courte)."""
    a, b = _shingles(left), _shingles(right)
    if len(a) < 10 or len(b) < 10:
        return 0.0
    return len(a & b) / len(a | b)


def title_similarity(left: str, right: str) -> float:
    return SequenceMatcher(None, canonical_title(left), canonical_title(right)).ratio()


def is_probable_duplicate(
    *, company_a: str, title_a: str, location_a: str | None, description_a: str,
    company_b: str, title_b: str, location_b: str | None, description_b: str,
) -> bool:
    """Même entreprise et même ville, niveaux compatibles, puis titre ou description très proches."""
    if normalize_company(company_a) != normalize_company(company_b):
        return False
    city_a, city_b = city_of(location_a), city_of(location_b)
    if city_a and city_b and city_a != city_b:
        return False
    if _levels(title_a) != _levels(title_b):
        return False  # « junior » n'est pas « senior » : deux postes distincts
    similarity = title_similarity(title_a, title_b)
    if similarity >= 0.92:
        return True
    return similarity >= 0.6 and description_similarity(description_a, description_b) >= 0.85
