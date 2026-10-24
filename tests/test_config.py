from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from applyflow.config import Settings, Thresholds, load_settings, save_settings


def test_load_defaults_without_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("APPLYFLOW_CONFIG", raising=False)
    settings = load_settings()
    assert settings.app.data_dir == (tmp_path / "data").resolve()
    assert settings.router.provider == "deterministic"
    assert settings.application.dry_run is True
    assert settings.config_path is None


def test_load_toml_and_relative_data_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = tmp_path / "applyflow.toml"
    config.write_text(
        """
[app]
data_dir = "local-data"
log_level = "DEBUG"

[router]
provider = "remote"
remote_route_url = "http://127.0.0.1:9999/route"

[scoring.thresholds]
high = 85
medium = 70
min_apply = 60
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("APPLYFLOW_DATA_DIR", "overridden")
    settings = load_settings(config)
    assert settings.app.log_level == "DEBUG"
    assert settings.router.provider == "remote"
    assert settings.app.data_dir == (tmp_path / "overridden").resolve()
    assert settings.scoring.thresholds.high == 85


def test_thresholds_must_be_ordered() -> None:
    with pytest.raises(ValidationError):
        Thresholds(high=50, medium=70, min_apply=65)


def test_band() -> None:
    thresholds = Thresholds(high=80, medium=65, min_apply=65)
    assert thresholds.band(90) == "high"
    assert thresholds.band(70) == "medium"
    assert thresholds.band(20) == "low"


def test_save_settings_roundtrip(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    settings = Settings(app={"data_dir": data_dir})
    target = save_settings(settings, tmp_path / "saved.toml")
    assert target.is_file()
    reloaded = load_settings(target)
    assert reloaded.data_dir == data_dir.resolve()
    assert reloaded.scoring.weights.skills == settings.scoring.weights.skills
