from __future__ import annotations

from sqlalchemy import func, select

from applyflow.campaigns.service import (
    STEPS,
    CampaignError,
    cancel_campaign,
    get_campaign,
    pause_campaign,
    resume_campaign,
    run_campaign,
)
from applyflow.db.models import (
    Application,
    ApplicationAttempt,
    Campaign,
    CampaignJob,
    RoutingDecision,
)
from applyflow.export import export_campaign
from applyflow.seed import seed_demo


def _seed_campaign(database, settings, max_jobs: int = 6) -> str:
    with database.session() as session:
        summary = seed_demo(session, settings)
        campaign = session.get(Campaign, summary["campaign_id"])
        campaign.max_jobs = max_jobs
        session.commit()
        return campaign.id


def test_seed_demo_creates_profiles_resumes_jobs_and_campaign(database, settings) -> None:
    with database.session() as session:
        summary = seed_demo(session, settings)
    assert summary["profiles_total"] == 5
    assert summary["resumes_created"] == 5
    assert summary["jobs_total"] == 33
    assert summary["campaign_id"]


def test_campaign_can_resume_after_partial_run(database, settings) -> None:
    campaign_id = _seed_campaign(database, settings, max_jobs=6)
    with database.session() as session:
        first = run_campaign(
            session,
            campaign_id,
            settings,
            steps=("discover", "analyze"),
            max_items=2,
        )
        assert first["status"] == "paused"
        campaign = get_campaign(session, campaign_id)
        assert session.scalar(
            select(func.count()).select_from(CampaignJob).where(CampaignJob.campaign_id == campaign.id)
        ) == 6
        analyzed = session.scalar(
            select(func.count())
            .select_from(CampaignJob)
            .where(CampaignJob.campaign_id == campaign.id, CampaignJob.stage.in_(("analyzed", "rejected")))
        )
        assert analyzed == 2

        second = run_campaign(
            session, campaign_id, settings, steps=("analyze", "prepare"), max_items=10
        )
        assert second["status"] == "paused"
        pending_analysis = session.scalar(
            select(func.count())
            .select_from(CampaignJob)
            .where(CampaignJob.campaign_id == campaign.id, CampaignJob.stage == "discovered")
        )
        assert pending_analysis == 0
        assert session.scalar(select(func.count()).select_from(ApplicationAttempt)) > 0

        third = run_campaign(session, campaign_id, settings, steps=STEPS)
        assert third["status"] in {"completed", "paused"}
        campaign = get_campaign(session, campaign_id)
        assert campaign.status in {"completed", "paused"}
        assert session.scalar(
            select(func.count()).select_from(Application)
        ) == 0  # aucune soumission sans validation


def test_preparation_is_idempotent(database, settings) -> None:
    campaign_id = _seed_campaign(database, settings, max_jobs=5)
    with database.session() as session:
        run_campaign(session, campaign_id, settings, steps=("discover", "analyze"))
        first = run_campaign(session, campaign_id, settings, steps=("prepare",))
        attempts_after_first = session.scalar(
            select(func.count()).select_from(ApplicationAttempt)
        )
        second = run_campaign(session, campaign_id, settings, steps=("prepare",))
        attempts_after_second = session.scalar(
            select(func.count()).select_from(ApplicationAttempt)
        )
    assert first["steps"]["prepare"]["prepared"] + first["steps"]["prepare"]["needs_review"] + first["steps"]["prepare"]["blocked"] >= 1
    assert second["steps"]["prepare"]["prepared"] == 0
    assert attempts_after_first == attempts_after_second


def test_min_score_prevents_preparation(database, settings) -> None:
    campaign_id = _seed_campaign(database, settings, max_jobs=4)
    with database.session() as session:
        campaign = get_campaign(session, campaign_id)
        campaign.min_score = 100
        run_campaign(session, campaign_id, settings, steps=("discover", "analyze"))
        result = run_campaign(session, campaign_id, settings, steps=("prepare",))
        attempts = session.scalar(select(func.count()).select_from(ApplicationAttempt))
    assert result["steps"]["prepare"]["skipped"] > 0
    assert attempts == 0


def test_campaign_max_jobs_is_enforced(database, settings) -> None:
    with database.session() as session:
        summary = seed_demo(session, settings)
        campaign = session.get(Campaign, summary["campaign_id"])
        campaign.max_jobs = 3
        run_campaign(session, campaign.id, settings, steps=("discover",))
        linked = session.scalar(
            select(func.count()).select_from(CampaignJob).where(CampaignJob.campaign_id == campaign.id)
        )
    assert linked == 3


def test_pause_resume_cancel(database, settings) -> None:
    campaign_id = _seed_campaign(database, settings, max_jobs=2)
    with database.session() as session:
        paused = pause_campaign(session, campaign_id)
        assert paused.status == "paused"
        resumed = resume_campaign(session, campaign_id)
        assert resumed.status == "running"
        cancelled = cancel_campaign(session, campaign_id)
        assert cancelled.status == "cancelled"
        import pytest

        with pytest.raises(CampaignError):
            resume_campaign(session, campaign_id)
        with pytest.raises(CampaignError):
            run_campaign(session, campaign_id, settings)


def test_routing_decision_and_explanations_are_persisted(database, settings) -> None:
    campaign_id = _seed_campaign(database, settings, max_jobs=5)
    with database.session() as session:
        run_campaign(session, campaign_id, settings, steps=("discover", "analyze"))
        decision = session.scalar(select(RoutingDecision))
        assert decision is not None
        assert 0 <= decision.confidence <= 1
        rows = list(
            session.scalars(select(CampaignJob).where(CampaignJob.campaign_id == campaign_id))
        )
        assert all(row.reasons for row in rows)
        assert any(row.priority == "rejected" for row in rows) or any(
            row.priority == "high" for row in rows
        )


def test_export_campaign_csv_and_json(database, settings, tmp_path) -> None:
    campaign_id = _seed_campaign(database, settings, max_jobs=4)
    with database.session() as session:
        run_campaign(session, campaign_id, settings, steps=("discover", "analyze"))
        csv_path = export_campaign(session, campaign_id, tmp_path / "resultats.csv")
        json_path = export_campaign(session, campaign_id, tmp_path / "resultats.json", fmt="json")
    assert csv_path.is_file()
    assert json_path.is_file()
    lines = csv_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 5  # en-tête + 4 offres
    assert "score" in lines[0]
    assert json_path.read_text(encoding="utf-8").startswith("[")


def test_campaign_without_source_is_refused_instead_of_using_fake_data() -> None:
    import pytest
    from pydantic import ValidationError

    from applyflow.campaigns.schemas import CampaignInput

    with pytest.raises(ValidationError, match="au moins une source"):
        CampaignInput(name="Sans source")
    with pytest.raises(ValidationError, match="au moins une source"):
        CampaignInput(name="Sans source", sources=[])
