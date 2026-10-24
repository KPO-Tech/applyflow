from __future__ import annotations

from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from applyflow.api.main import create_app
from applyflow.config import ApplicationConfig, DiscoveryConfig, Settings
from applyflow.db import Database
from applyflow.db.models import Profile
from applyflow.profiles.schemas import ProfileInput
from applyflow.profiles.service import create_profile, upload_resume
from applyflow.seed import SAMPLE_CV
from applyflow.services import ensure_local_user


@pytest.fixture(autouse=True)
def _no_system_keyring(monkeypatch: pytest.MonkeyPatch) -> None:
    """Les tests n'écrivent jamais dans le vrai trousseau de l'utilisateur."""
    monkeypatch.setenv("APPLYFLOW_NO_KEYRING", "1")


@pytest.fixture()
def settings(tmp_path: Path) -> Settings:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    return Settings(
        app={
            "data_dir": data_dir,
            "db_url": f"sqlite:///{(tmp_path / 'applyflow-test.db').as_posix()}",
            "demo_forms": True,
            "log_level": "WARNING",
        },
        discovery=DiscoveryConfig(rate_limit_seconds=0),
        application=ApplicationConfig(dry_run=True),
    )


@pytest.fixture()
def database(settings: Settings) -> Iterator[Database]:
    db = Database(settings.database_url)
    db.init_schema()
    yield db
    db.dispose()


@pytest.fixture()
def session(database: Database) -> Iterator:
    with database.session() as db_session:
        yield db_session


@pytest.fixture()
def make_profile(session) -> Callable[..., Profile]:
    ensure_local_user(session)

    def _make(**overrides) -> Profile:
        data = {
            "name": "Data Engineer",
            "full_name": "Camille Martin",
            "email": "camille.martin@example.invalid",
            "phone": "+33 6 00 00 00 00",
            "city": "Paris",
            "target_titles": ["Data Engineer", "Analytics Engineer"],
            "technical_skills": [
                "Python",
                "SQL",
                "Airflow",
                "dbt",
                "Snowflake",
                "Docker",
            ],
            "domain_skills": ["retail"],
            "experience_level": "junior",
            "years_experience": 2,
            "locations": ["France", "Paris", "Remote"],
            "contract_types": ["CDI"],
            "remote_preferences": ["hybrid", "remote"],
            "salary_min": 40000,
            "salary_max": 48000,
            "salary_currency": "EUR",
            "work_authorization": "France / Union européenne",
        }
        data.update(overrides)
        return create_profile(session, ProfileInput(**data))

    return _make


@pytest.fixture()
def profile(make_profile) -> Profile:
    return make_profile()


@pytest.fixture()
def resume(session, settings, profile):
    content = SAMPLE_CV.read_bytes()
    return upload_resume(
        session, settings, profile.id, filename="cv.pdf", content=content
    )


@pytest.fixture()
def api_client(settings: Settings) -> Iterator[TestClient]:
    settings.config_path = settings.data_dir.parent / "applyflow-test.toml"
    app = create_app(settings)
    with TestClient(app, base_url="http://127.0.0.1:8000") as client:
        yield client
