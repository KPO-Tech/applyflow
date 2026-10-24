"""Liste officielle des pays (ISO 3166-1) et détection du pays d'une localisation.

La liste vient de `pycountry` (norme ISO 3166-1, 249 pays, gratuite) avec les noms français de la
base `iso-codes`. Les noms officiels trop lourds (« Russie, Fédération de ») sont raccourcis pour
l'affichage, mais toutes les écritures restent reconnues.
"""

from __future__ import annotations

import gettext
import re
from dataclasses import dataclass
from functools import lru_cache

import pycountry

from applyflow.text import normalize_text

# Noms d'usage quand le nom officiel est inutilisable tel quel.
EN_NAMES = {
    "KP": "North Korea", "RU": "Russia", "IR": "Iran", "SY": "Syria", "TW": "Taiwan",
    "TZ": "Tanzania", "BO": "Bolivia", "VE": "Venezuela", "MD": "Moldova", "LA": "Laos",
    "FM": "Micronesia", "PS": "Palestine", "VA": "Vatican City", "BN": "Brunei",
    "CD": "DR Congo", "VG": "British Virgin Islands", "VI": "US Virgin Islands",
    "BQ": "Bonaire, Sint Eustatius and Saba", "SX": "Sint Maarten", "MF": "Saint Martin",
}
FR_NAMES = {
    "KR": "Corée du Sud", "KP": "Corée du Nord", "CD": "République démocratique du Congo",
    "VG": "Îles Vierges britanniques", "VI": "Îles Vierges des États-Unis",
    "VA": "Vatican", "BQ": "Bonaire, Saint-Eustache et Saba", "SX": "Saint-Martin (partie néerlandaise)",
    "MF": "Saint-Martin (partie française)", "GB": "Royaume-Uni", "US": "États-Unis",
}

# Écritures courantes qui ne figurent pas dans la norme.
CUSTOM_ALIASES = {
    "uk": "GB", "u.k": "GB", "england": "GB", "scotland": "GB", "wales": "GB",
    "northern ireland": "GB", "great britain": "GB", "royaume uni": "GB", "angleterre": "GB",
    "usa": "US", "u.s.a": "US", "u.s": "US", "etats unis": "US", "etats unis d amerique": "US",
    "holland": "NL", "the netherlands": "NL", "nederland": "NL", "pays bas": "NL",
    "uae": "AE", "emirats arabes unis": "AE", "ivory coast": "CI", "czech republic": "CZ",
    "republique tcheque": "CZ", "tchequie": "CZ", "turkey": "TR", "south korea": "KR",
    "russia": "RU", "republique francaise": "FR", "metropolitan france": "FR",
    "deutschland": "DE", "espana": "ES", "italia": "IT", "schweiz": "CH", "svizzera": "CH",
    "osterreich": "AT", "belgie": "BE", "belgien": "BE", "sverige": "SE", "norge": "NO",
    "danmark": "DK", "suomi": "FI", "polska": "PL", "brasil": "BR",
}

# Noms de pays qui désignent aussi autre chose : résolus selon le contexte (voir detect_country).
AMBIGUOUS = {"georgia": "GE"}

US_STATES = (
    "alabama", "alaska", "arizona", "arkansas", "california", "colorado", "connecticut",
    "delaware", "florida", "hawaii", "idaho", "illinois", "indiana", "iowa", "kansas",
    "kentucky", "louisiana", "maine", "maryland", "massachusetts", "michigan", "minnesota",
    "mississippi", "missouri", "montana", "nebraska", "nevada", "new hampshire", "new jersey",
    "new mexico", "new york", "north carolina", "north dakota", "ohio", "oklahoma", "oregon",
    "pennsylvania", "rhode island", "south carolina", "south dakota", "tennessee", "texas",
    "utah", "vermont", "virginia", "washington", "west virginia", "wisconsin", "wyoming",
    "district of columbia",
)
US_STATE_CODES = frozenset(
    ["AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA", "HI", "ID", "IL", "IN", "IA", "KS", "KY", "LA", "ME", "MD", "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH", "NJ", "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI", "SC", "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV", "WI", "WY", "DC"]
)
CA_PROVINCES = (
    "ontario", "quebec", "british columbia", "alberta", "manitoba", "saskatchewan",
    "nova scotia", "new brunswick", "newfoundland and labrador", "prince edward island",
)

# Grandes villes : utiles quand la localisation ne cite pas le pays (« Paris », « London »).
CITIES: dict[str, tuple[str, ...]] = {
    "FR": ("paris", "lyon", "marseille", "toulouse", "nantes", "bordeaux", "lille", "rennes",
           "strasbourg", "montpellier", "nice", "grenoble", "boulogne-billancourt", "nanterre",
           "puteaux", "la defense", "courbevoie", "issy-les-moulineaux", "saint-denis",
           "ile de france", "sophia antipolis", "rouen", "dijon", "clermont-ferrand"),
    "GB": ("london", "manchester", "edinburgh", "birmingham", "bristol", "cambridge", "leeds"),
    "DE": ("berlin", "munich", "hamburg", "frankfurt", "cologne", "stuttgart", "dusseldorf"),
    "ES": ("madrid", "barcelona", "valencia", "seville", "malaga"),
    "NL": ("amsterdam", "rotterdam", "utrecht", "eindhoven", "the hague"),
    "BE": ("brussels", "bruxelles", "antwerp", "gent", "ghent", "liege"),
    "CH": ("zurich", "geneva", "geneve", "lausanne", "basel"),
    "IE": ("dublin", "cork", "galway"),
    "IT": ("milan", "milano", "rome", "roma", "turin", "torino"),
    "PT": ("lisbon", "lisboa", "porto"),
    "LU": ("luxembourg city",),
    "US": ("new york", "san francisco", "seattle", "austin", "boston", "chicago", "los angeles",
           "washington", "atlanta", "denver", "san jose", "palo alto", "mountain view"),
    "CA": ("toronto", "montreal", "vancouver", "ottawa", "calgary", "quebec"),
    "MA": ("casablanca", "rabat", "marrakech"),
    "IN": ("bangalore", "bengaluru", "mumbai", "hyderabad", "pune", "delhi"),
}

_SEPARATORS = re.compile(r"[,;/|()]|\s+-\s+")
_FR = gettext.translation("iso3166-1", pycountry.LOCALES_DIR, languages=["fr"], fallback=True)


@dataclass(frozen=True)
class Country:
    code: str  # ISO 3166-1 alpha-2
    name: str  # nom d'usage en anglais (celui qui est enregistré dans les recherches)
    name_fr: str  # nom d'affichage en français


def _english_name(country: object) -> str:
    code = country.alpha_2  # type: ignore[attr-defined]
    if code in EN_NAMES:
        return EN_NAMES[code]
    common = getattr(country, "common_name", None)
    return common or country.name.split(",")[0].strip()  # type: ignore[attr-defined]


def _french_name(country: object) -> str:
    code = country.alpha_2  # type: ignore[attr-defined]
    if code in FR_NAMES:
        return FR_NAMES[code]
    return _FR.gettext(country.name).split(",")[0].strip()  # type: ignore[attr-defined]


@lru_cache(maxsize=1)
def all_countries() -> tuple[Country, ...]:
    """Les 249 pays officiels, triés par nom français."""
    countries = [
        Country(code=c.alpha_2, name=_english_name(c), name_fr=_french_name(c))
        for c in pycountry.countries
    ]
    return tuple(sorted(countries, key=lambda c: normalize_text(c.name_fr)))


@lru_cache(maxsize=1)
def _alias_table() -> dict[str, str]:
    """Écriture normalisée -> code ISO. Les noms d'usage priment sur les noms officiels."""
    table: dict[str, str] = {}
    for country in all_countries():
        table.setdefault(normalize_text(country.name), country.code)
        table.setdefault(normalize_text(country.name_fr), country.code)
    for official in pycountry.countries:
        for raw in (official.name, getattr(official, "official_name", None),
                    getattr(official, "common_name", None), _FR.gettext(official.name)):
            if raw:
                table.setdefault(normalize_text(raw), official.alpha_2)
                table.setdefault(normalize_text(raw.split(",")[0]), official.alpha_2)
    for alias, code in CUSTOM_ALIASES.items():
        table[normalize_text(alias)] = code
    return table


@lru_cache(maxsize=1)
def _by_code() -> dict[str, Country]:
    return {country.code: country for country in all_countries()}


@lru_cache(maxsize=1)
def _cities() -> dict[str, str]:
    return {normalize_text(city): iso for iso, names in CITIES.items() for city in names}


@lru_cache(maxsize=1)
def _region_names() -> dict[str, str]:
    names = {normalize_text(state): "US" for state in US_STATES}
    names.update({normalize_text(province): "CA" for province in CA_PROVINCES})
    return names


def country_catalog() -> list[dict[str, object]]:
    """Liste pour l'autocomplétion : code, noms, et écritures alternatives acceptées."""
    table = _alias_table()
    extra: dict[str, list[str]] = {}
    for alias, code in table.items():
        country = _by_code()[code]
        if alias not in {normalize_text(country.name), normalize_text(country.name_fr)}:
            extra.setdefault(code, []).append(alias)
    return [
        {"code": c.code, "name": c.name, "name_fr": c.name_fr, "aliases": sorted(extra.get(c.code, []))}
        for c in all_countries()
    ]


def normalize_country(value: str | None) -> str | None:
    """Accepte `FR`, `fr`, `france`, `Allemagne`, `United Kingdom`… et retourne le code ISO.

    Les noms de ville sont refusés : voir `detect_country` pour déduire un pays d'une ville.
    """
    if not value:
        return None
    text = normalize_text(value)
    if not text:
        return None
    if len(text) == 2 and text.upper() in _by_code():
        return text.upper()
    return _alias_table().get(text)


def get_country(iso: str | None) -> Country | None:
    return _by_code().get(iso.upper()) if iso else None


def is_official_country(value: str | None) -> bool:
    return normalize_country(value) is not None


def detect_country(location: str | None, default: str | None = None) -> str | None:
    """Pays d'une localisation. Un nom de pays écrit l'emporte sur une ville ; sinon, `default`.

    Plusieurs lieux (« France, Remote; Spain, Remote ») : le premier pays cité est retenu.
    Un code à deux lettres n'est lu que s'il est écrit en majuscules (« Paris, FR »), et un code
    d'État américain (« Boston, MA ») vaut États-Unis plutôt que Maroc.
    """
    if location:
        raw_segments = [part.strip() for part in _SEPARATORS.split(location)]
        segments = [normalize_text(part) for part in raw_segments]
        segments = [segment for segment in segments if segment]
        table, cities, regions = _alias_table(), _cities(), _region_names()

        if "georgia" in segments:  # État américain ou pays : le contexte tranche
            us_context = any(
                segment in cities and cities[segment] == "US" or segment in {"usa", "united states"}
                for segment in segments
            ) or any(part in US_STATE_CODES for part in raw_segments)
            if not us_context:
                return AMBIGUOUS["georgia"]
            return "US"

        for segment in segments:  # 1. nom de pays, d'État américain ou de province canadienne
            if segment in regions:
                return regions[segment]
            if segment in table and len(segment) != 2:
                return table[segment]
        for segment in segments:  # 2. grande ville
            if segment in cities:
                return cities[segment]
        for part in raw_segments:  # 3. codes en majuscules : État américain, puis code pays
            if part in US_STATE_CODES:
                return "US"
        for part in raw_segments:
            if len(part) == 2 and part.isupper() and part in _by_code():
                return part
    return normalize_country(default)


def country_label(iso: str | None) -> str:
    if not iso:
        return "Inconnu"
    country = _by_code().get(iso)
    return country.name_fr if country else iso
