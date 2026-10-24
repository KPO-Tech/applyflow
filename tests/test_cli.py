"""Tests de la CLI : chaque commande documentée est exercée sur une base temporaire."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from applyflow.campaigns.schemas import CampaignInput
from applyflow.campaigns.service import create_campaign
from applyflow.cli import build_parser, main
from applyflow.config import Settings
from applyflow.db.models import ApplicationAttempt, Job


def _config_file(tmp_path: Path, settings: Settings) -> Path:
    config = tmp_path / "applyflow-cli.toml"
    config.write_text(
        "[app]\n"
        f'data_dir = "{settings.data_dir.as_posix()}"\n'
        f'db_url = "{settings.database_url}"\n'
        'log_level = "WARNING"\n'
        "\n[discovery]\n"
        "rate_limit_seconds = 0.0\n",
        encoding="utf-8",
    )
    return config


def _run(capsys, *args: str) -> tuple[int, object]:
    code = main(list(args))
    out = capsys.readouterr().out
    return code, json.loads(out) if out.strip() else None


def _job(session, **overrides) -> Job:
    data = {
        "source_kind": "manual_url",
        "url": "https://acme.example/jobs/1",
        "url_key": "https://acme.example/jobs/1",
        "company": "Acme",
        "title": "Data Engineer",
        "description": "Python, SQL.",
        "fingerprint": "a" * 64,
    }
    data.update(overrides)
    job = Job(**data)
    session.add(job)
    session.flush()
    return job


def _attempt(session, profile, job, *, status: str) -> ApplicationAttempt:
    attempt = ApplicationAttempt(
        job_id=job.id,
        profile_id=profile.id,
        status=status,
        idempotency_key=f"{job.id}:{profile.id}:{status}",
    )
    session.add(attempt)
    session.flush()
    return attempt


def test_parser_defaults_and_required_arguments() -> None:
    parser = build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args([])
    with pytest.raises(SystemExit):
        parser.parse_args(["fill"])  # --attempt obligatoire
    args = parser.parse_args(["export", "--campaign", "abc"])
    assert args.format == "csv"
    assert parser.parse_args(["run-campaign"]).steps == "discover,analyze,prepare"


def test_init_db_is_idempotent(settings, tmp_path, capsys) -> None:
    config = _config_file(tmp_path, settings)
    code, payload = _run(capsys, "--config", str(config), "init-db")
    assert code == 0
    assert payload["status"] == "ok"
    assert (tmp_path / "applyflow-test.db").exists()

    code, _ = _run(capsys, "--config", str(config), "init-db")
    assert code == 0


def test_status_and_providers_render_json(settings, tmp_path, capsys) -> None:
    config = _config_file(tmp_path, settings)
    assert _run(capsys, "--config", str(config), "init-db")[0] == 0

    code, status = _run(capsys, "--config", str(config), "status")
    assert code == 0
    assert status["profiles"] == 0
    assert status["applications_queue"] == 0
    assert status["applications_total"] == 0

    code, catalog = _run(capsys, "--config", str(config), "providers")
    assert code == 0
    kinds = {entry["kind"] for entry in catalog}
    assert {"adzuna", "jobspy", "rss", "greenhouse", "lever"} <= kinds


def test_import_json_then_rebuild_dedupe(settings, tmp_path, capsys) -> None:
    payload_file = tmp_path / "offres.json"
    payload_file.write_text(
        json.dumps(
            {
                "jobs": [
                    {
                        "url": "https://acme.example/jobs/1",
                        "company": "Acme",
                        "title": "Data Engineer Junior",
                        "location": "Paris, France",
                        "description": "Python, SQL.",
                    },
                    {
                        # Même entreprise/intitulé/ville : doublon métier volontaire.
                        "url": "https://acme.example/jobs/1-bis",
                        "company": "Acme SAS",
                        "title": "Data Engineer Junior",
                        "location": "Paris",
                        "description": "Python, SQL, dbt.",
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
    config = _config_file(tmp_path, settings)

    code, first = _run(
        capsys, "--config", str(config), "import-json", "--file", str(payload_file)
    )
    assert code == 0
    assert first["created"] == 1
    assert first["duplicates"] == 1

    code, second = _run(
        capsys, "--config", str(config), "import-json", "--file", str(payload_file)
    )
    assert code == 0
    assert second["created"] == 0
    assert second["duplicates"] == 2

    code, rebuilt = _run(capsys, "--config", str(config), "rebuild-dedupe")
    assert code == 0
    assert isinstance(rebuilt, dict)


def test_run_campaign_requires_an_existing_campaign(settings, tmp_path, capsys) -> None:
    config = _config_file(tmp_path, settings)
    with pytest.raises(SystemExit) as missing:
        main(["--config", str(config), "run-campaign"])
    assert "aucune campagne" in str(missing.value)

    with pytest.raises(SystemExit) as unknown:
        main(["--config", str(config), "run-campaign", "--name", "Inconnue"])
    assert "campagne introuvable" in str(unknown.value)


def test_run_campaign_analyze_on_empty_campaign(settings, session, profile, tmp_path, capsys) -> None:
    campaign = create_campaign(
        session,
        CampaignInput(
            name="CLI analyze",
            sources=[{"kind": "json_file", "config": {"path": "offres.json"}}],
        ),
    )
    session.commit()
    config = _config_file(tmp_path, settings)

    code, summary = _run(
        capsys, "--config", str(config), "run-campaign", "--id", campaign.id, "--steps", "analyze"
    )
    assert code == 0
    assert summary["campaign_id"] == campaign.id
    assert summary["steps"]["analyze"]["analyzed"] == 0
    assert summary["status"] == "paused"


def test_fill_refuses_unapproved_attempt(settings, session, profile, tmp_path) -> None:
    job = _job(session)
    attempt = _attempt(session, profile, job, status="needs_review")
    session.commit()
    config = _config_file(tmp_path, settings)

    with pytest.raises(SystemExit) as refused:
        main(["--config", str(config), "fill", "--attempt", attempt.id])
    assert "validée" in str(refused.value)


def test_record_submission_creates_application(
    settings, session, profile, tmp_path, capsys
) -> None:
    job = _job(session, fingerprint="b" * 64, url_key="https://acme.example/jobs/2")
    attempt = _attempt(session, profile, job, status="approved")
    session.commit()
    config = _config_file(tmp_path, settings)

    code, payload = _run(
        capsys,
        "--config",
        str(config),
        "record-submission",
        "--attempt",
        attempt.id,
        "--reference",
        "ACME-42",
    )
    assert code == 0
    assert payload["status"] == "submitted"
