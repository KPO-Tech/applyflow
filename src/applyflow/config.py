"""Configuration typée d'ApplyFlow (fichier TOML + variables d'environnement)."""

from __future__ import annotations

import os
import re
import tomllib
from pathlib import Path
from typing import Any, Literal

import tomli_w
from pydantic import BaseModel, Field, field_validator, model_validator

DEFAULT_CONFIG_FILENAME = "applyflow.toml"
PROJECT_ROOT = Path(__file__).resolve().parents[2]


class AppConfig(BaseModel):
    data_dir: Path = Path("data")
    db_url: str | None = None
    log_level: str = "INFO"
    log_json: bool = False
    demo_forms: bool = True


class ScoringWeights(BaseModel):
    skills: float = 30
    titles: float = 20
    seniority: float = 20
    experience: float = 15
    location: float = 5
    contract: float = 5
    obligations: float = 5

    @model_validator(mode="after")
    def _positive(self) -> ScoringWeights:
        if any(value <= 0 for value in self.model_dump().values()):
            raise ValueError("les poids de scoring doivent être strictement positifs")
        return self

    def normalized(self) -> dict[str, float]:
        total = sum(self.model_dump().values())
        return {key: value / total for key, value in self.model_dump().items()}


class Thresholds(BaseModel):
    high: int = Field(default=80, ge=0, le=100)
    medium: int = Field(default=65, ge=0, le=100)
    min_apply: int = Field(default=65, ge=0, le=100)

    @model_validator(mode="after")
    def _ordered(self) -> Thresholds:
        if not (self.high > self.medium >= self.min_apply):
            raise ValueError("seuils attendus : high > medium >= min_apply")
        return self

    def band(self, score: int | float) -> str:
        if score >= self.high:
            return "high"
        if score >= self.medium:
            return "medium"
        return "low"


class ScoringConfig(BaseModel):
    weights: ScoringWeights = Field(default_factory=ScoringWeights)
    thresholds: Thresholds = Field(default_factory=Thresholds)
    excluded_seniority: list[str] = Field(
        default_factory=lambda: ["lead", "principal", "staff", "head", "director"]
    )
    penalized_seniority: list[str] = Field(default_factory=lambda: ["senior"])
    max_required_years: float = 5.0


class RouterConfig(BaseModel):
    provider: Literal["deterministic", "laya", "remote"] = "deterministic"
    fallback_to_deterministic: bool = True
    laya_base_url: str = "http://127.0.0.1:8420"
    laya_token: str = ""
    remote_route_url: str = ""
    timeout_seconds: float = 10.0
    uncertainty_margin: float = 0.08


class DiscoveryConfig(BaseModel):
    user_agent: str = "ApplyFlow/0.1 (local job application assistant)"
    timeout_seconds: float = 20.0
    rate_limit_seconds: float = 1.0
    max_jobs_default: int = 1000
    # Une erreur passagère (timeout, 429, 5xx) est retentée avec un repli exponentiel ;
    # l'en-tête Retry-After est respecté. Une erreur définitive (403, 404) n'est pas retentée.
    retry_attempts: int = Field(default=3, ge=1, le=10)
    retry_base_seconds: float = Field(default=1.0, ge=0, le=60)
    retry_max_seconds: float = Field(default=20.0, ge=0, le=300)

    @model_validator(mode="after")
    def _retry_window(self) -> DiscoveryConfig:
        if self.retry_max_seconds < self.retry_base_seconds:
            raise ValueError("retry_max_seconds doit être supérieur ou égal à retry_base_seconds")
        return self


class AdzunaConfig(BaseModel):
    """Clé gratuite de l'API officielle Adzuna (agrégateur d'offres)."""

    app_id: str = ""
    app_key: str = ""
    country: str = "fr"
    max_pages: int = Field(default=5, ge=1, le=20)


class BoardsConfig(BaseModel):
    """Collecte étendue via JobSpy (job boards). Désactivée par défaut : usage à vos risques."""

    jobspy_enabled: bool = False
    # LinkedIn n'est pas coché par défaut : c'est le site qui détecte le plus vite les rafales.
    sites: list[str] = Field(default_factory=lambda: ["indeed", "hellowork"])
    country: str = "france"
    max_per_site: int = Field(default=100, ge=1, le=1000)
    pause_seconds: float = Field(default=5.0, ge=0, le=120)
    proxies: list[str] = Field(default_factory=list)
    # Plafond d'offres collectées par jour et par site (0 = pas de plafond pour ce site).
    daily_limits: dict[str, int] = Field(
        default_factory=lambda: {
            "linkedin": 75, "indeed": 200, "glassdoor": 150, "hellowork": 150, "google": 100,
        }
    )

    @field_validator("daily_limits")
    @classmethod
    def _limits(cls, value: dict[str, int]) -> dict[str, int]:
        cleaned: dict[str, int] = {}
        for site, limit in value.items():
            if limit < 0 or limit > 5000:
                raise ValueError(f"plafond invalide pour {site} : entre 0 et 5000 attendu")
            cleaned[str(site).strip().lower()] = int(limit)
        return cleaned


ATS_FORMAT = re.compile(r"^[a-z]+:\S+$")


class SearchDefaultsConfig(BaseModel):
    """Recherche préremplie dans l'écran Découverte (modifiable dans Réglages → Collecte)."""

    keywords: list[str] = Field(
        default_factory=lambda: [
            "Data Engineer junior",
            "Data Analyst junior",
            "AI Engineer junior",
            "Data Scientist junior",
            "Graduate Data Engineer",
        ]
    )
    locations: list[str] = Field(default_factory=lambda: ["France"])
    limit: int = Field(default=100, ge=1, le=5000)
    # Entreprises dont l'API carrières publique a répondu avec des offres en France le
    # 2026-10-23. Les identifiants changent parfois : vérifiez-les avec une collecte.
    ats_companies: list[str] = Field(
        default_factory=lambda: [
            "greenhouse:datadog",
            "greenhouse:doctolib",
            "greenhouse:algolia",
            "greenhouse:mirakl",
            "greenhouse:dataiku",
            "lever:qonto",
            "lever:contentsquare",
            "lever:blablacar",
            "ashby:alan",
            "ashby:backmarket",
        ]
    )

    @field_validator("keywords", "locations", "ats_companies")
    @classmethod
    def _clean_list(cls, value: list[str]) -> list[str]:
        return list(dict.fromkeys(item.strip() for item in value if item and item.strip()))

    @field_validator("ats_companies")
    @classmethod
    def _ats_format(cls, value: list[str]) -> list[str]:
        for entry in value:
            if not ATS_FORMAT.match(entry.lower()):
                raise ValueError(f"format attendu ats:identifiant (ex. lever:qonto), reçu : {entry}")
        # Seul le nom de l'ATS est normalisé : l'identifiant d'entreprise peut être sensible à la casse.
        return [f"{entry.partition(':')[0].lower()}:{entry.partition(':')[2]}" for entry in value]


class EmailConfig(BaseModel):
    """Boîte mail personnelle : lecture seule, aucun envoi automatique."""

    provider: str = "gmail"
    address: str = ""
    imap_host: str = "imap.gmail.com"
    imap_port: int = 993
    folder: str = "INBOX"
    lookback_days: int = Field(default=45, ge=1, le=365)
    max_messages: int = Field(default=80, ge=5, le=300)
    relance_days: int = Field(default=10, ge=1, le=90)


class ApplicationConfig(BaseModel):
    dry_run: bool = True
    allow_submit: bool = False
    headless: bool = True
    # Les ATS construisent leur formulaire en JavaScript : quand le HTML statique n'a aucun
    # champ, la page est relue dans un navigateur avant de conclure « à postuler à la main ».
    render_forms: bool = True
    max_resume_mb: int = 5
    max_form_bytes: int = 2_000_000


class ApiConfig(BaseModel):
    host: str = "127.0.0.1"
    port: int = 8000
    # Noms d'hôte acceptés dans l'en-tête Host (protection contre le « DNS rebinding »).
    # À compléter seulement si vous exposez l'application volontairement sous un autre nom.
    allowed_hosts: list[str] = Field(default_factory=lambda: ["127.0.0.1", "localhost", "::1"])


class UiConfig(BaseModel):
    port: int = 8501


class Settings(BaseModel):
    app: AppConfig = Field(default_factory=AppConfig)
    router: RouterConfig = Field(default_factory=RouterConfig)
    discovery: DiscoveryConfig = Field(default_factory=DiscoveryConfig)
    scoring: ScoringConfig = Field(default_factory=ScoringConfig)
    application: ApplicationConfig = Field(default_factory=ApplicationConfig)
    adzuna: AdzunaConfig = Field(default_factory=AdzunaConfig)
    boards: BoardsConfig = Field(default_factory=BoardsConfig)
    search: SearchDefaultsConfig = Field(default_factory=SearchDefaultsConfig)
    email: EmailConfig = Field(default_factory=EmailConfig)
    api: ApiConfig = Field(default_factory=ApiConfig)
    ui: UiConfig = Field(default_factory=UiConfig)
    config_path: Path | None = Field(default=None, exclude=True)

    @property
    def data_dir(self) -> Path:
        return self.app.data_dir

    @property
    def database_url(self) -> str:
        if self.app.db_url:
            return self.app.db_url
        return f"sqlite:///{(self.data_dir / 'applyflow.db').as_posix()}"

    def ensure_directories(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        (self.data_dir / "resumes").mkdir(parents=True, exist_ok=True)
        (self.data_dir / "exports").mkdir(parents=True, exist_ok=True)


_ENV_APP_OVERRIDES = {
    "APPLYFLOW_DATA_DIR": "data_dir",
    "APPLYFLOW_DB_URL": "db_url",
    "APPLYFLOW_LOG_LEVEL": "log_level",
}


def _resolve_config_path(explicit: Path | str | None) -> Path | None:
    if explicit:
        path = Path(explicit).expanduser()
        if not path.is_file():
            raise FileNotFoundError(f"fichier de configuration introuvable : {path}")
        return path
    env_path = os.environ.get("APPLYFLOW_CONFIG")
    if env_path:
        path = Path(env_path).expanduser()
        if not path.is_file():
            raise FileNotFoundError(f"APPLYFLOW_CONFIG pointe vers un fichier absent : {path}")
        return path
    candidate = Path.cwd() / DEFAULT_CONFIG_FILENAME
    return candidate if candidate.is_file() else None


def load_settings(config_path: Path | str | None = None) -> Settings:
    """Charge la configuration TOML, puis applique quelques surcharges d'environnement."""
    path = _resolve_config_path(config_path)
    raw: dict[str, Any] = {}
    if path is not None:
        with path.open("rb") as handle:
            raw = tomllib.load(handle)

    app_raw = raw.setdefault("app", {})
    for env_key, field in _ENV_APP_OVERRIDES.items():
        if env_key in os.environ:
            app_raw[field] = os.environ[env_key]
    if "APPLYFLOW_DRY_RUN" in os.environ:
        raw.setdefault("application", {})["dry_run"] = os.environ[
            "APPLYFLOW_DRY_RUN"
        ].strip().lower() in {"1", "true", "yes", "on"}
    # Secrets locaux : préférer l'environnement au fichier TOML.
    if os.environ.get("APPLYFLOW_LAYA_TOKEN"):
        raw.setdefault("router", {})["laya_token"] = os.environ["APPLYFLOW_LAYA_TOKEN"]
    if os.environ.get("APPLYFLOW_ADZUNA_APP_ID"):
        raw.setdefault("adzuna", {})["app_id"] = os.environ["APPLYFLOW_ADZUNA_APP_ID"]
    if os.environ.get("APPLYFLOW_ADZUNA_APP_KEY"):
        raw.setdefault("adzuna", {})["app_key"] = os.environ["APPLYFLOW_ADZUNA_APP_KEY"]

    settings = Settings(**raw)
    base_dir = path.parent if path is not None else Path.cwd()
    data_dir = Path(settings.app.data_dir).expanduser()
    if not data_dir.is_absolute():
        data_dir = (base_dir / data_dir).resolve()
    settings.app.data_dir = data_dir
    settings.config_path = path.resolve() if path is not None else None
    if settings.app.log_json:
        settings.app.log_level = settings.app.log_level.upper()
    return settings


def save_settings(settings: Settings, path: Path | str | None = None) -> Path:
    """Écrit la configuration complète (sans secret ajouté) dans un fichier TOML."""
    target = Path(path) if path else (settings.config_path or Path.cwd() / DEFAULT_CONFIG_FILENAME)
    payload = settings.model_dump(mode="json", exclude={"config_path"})
    # Les chemins absolus ne doivent pas rendre le projet non portable.
    data_dir = Path(settings.app.data_dir)
    try:
        payload["app"]["data_dir"] = str(data_dir.relative_to(target.parent.resolve()))
    except ValueError:
        payload["app"]["data_dir"] = str(data_dir)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("wb") as handle:
        tomli_w.dump(_without_none(payload), handle)
    return target


def _without_none(value: Any) -> Any:
    """TOML ne connaît pas null : les options absentes sont simplement omises."""
    if isinstance(value, dict):
        return {
            key: _without_none(item)
            for key, item in value.items()
            if item is not None
        }
    if isinstance(value, list):
        return [_without_none(item) for item in value]
    return value
