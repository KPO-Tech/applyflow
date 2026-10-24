"""Types de contrat : vocabulaire commun au profil, au scoring et aux connecteurs."""

from __future__ import annotations

from collections.abc import Iterable

from applyflow.text import normalize_text

# (clé interne, libellé affiché) : l'ordre est celui de l'interface.
CONTRACT_TYPES: tuple[tuple[str, str], ...] = (
    ("permanent", "CDI"),
    ("fixed-term", "CDD"),
    ("internship", "Stage"),
    ("apprenticeship", "Alternance"),
    ("freelance", "Freelance"),
    ("temporary", "Intérim"),
    ("part-time", "Temps partiel"),
    ("vie", "VIE"),
)

# Écriture normalisée -> clé interne. Couvre aussi les libellés produits par les connecteurs
# (JobSpy, ATS) : sans cela, « CDD / contrat » ou « Temps partiel » ne correspondaient à rien.
CONTRACT_ALIASES = {
    "cdi": "permanent",
    "permanent": "permanent",
    "open-ended": "permanent",
    "full time": "permanent",
    "full-time": "permanent",
    "temps plein": "permanent",
    "cdd": "fixed-term",
    "fixed term": "fixed-term",
    "fixed-term": "fixed-term",
    "temporary": "temporary",
    "temporaire": "temporary",
    "interim": "temporary",
    "contract": "contract",
    "cdd contrat": "contract",  # libellé générique des connecteurs : CDD ou mission
    "freelance": "freelance",
    "independant": "freelance",
    "internship": "internship",
    "stage": "internship",
    "stagiaire": "internship",
    "alternance": "apprenticeship",
    "apprenticeship": "apprenticeship",
    "apprentissage": "apprenticeship",
    "contrat d apprentissage": "apprenticeship",
    "contrat de professionnalisation": "apprenticeship",
    "part time": "part-time",
    "part-time": "part-time",
    "temps partiel": "part-time",
    "vie": "vie",
    "vie via": "vie",
}

# Un libellé générique est compatible avec plusieurs types demandés.
GENERIC_CONTRACTS = {"contract": frozenset({"fixed-term", "freelance"})}


def normalize_contract(value: str | None) -> str | None:
    if not value:
        return None
    normalized = normalize_text(value)
    return CONTRACT_ALIASES.get(normalized, normalized)


def contract_matches(job_contract: str | None, accepted: Iterable[str | None]) -> bool:
    """Le contrat de l'offre figure-t-il parmi ceux que le profil accepte ?"""
    wanted = {item for item in accepted if item}
    if not job_contract or job_contract in wanted:
        return bool(job_contract)
    return bool(GENERIC_CONTRACTS.get(job_contract, frozenset()) & wanted)


def contract_catalog() -> list[dict[str, str]]:
    return [{"key": key, "label": label} for key, label in CONTRACT_TYPES]
