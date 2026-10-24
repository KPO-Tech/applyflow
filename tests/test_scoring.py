from __future__ import annotations

from applyflow.config import ScoringConfig
from applyflow.matching.scoring import JobSignals, score_job
from applyflow.matching.types import ProfileSnapshot


def _profile(**overrides) -> ProfileSnapshot:
    data = {
        "id": "profile-1",
        "name": "Data Engineer",
        "target_titles": ["Data Engineer", "Analytics Engineer"],
        "technical_skills": ["Python", "SQL", "Airflow", "dbt", "Snowflake", "Docker"],
        "domain_skills": ["retail"],
        "experience_level": "junior",
        "years_experience": 2,
        "locations": ["France", "Paris", "Remote"],
        "contract_types": ["CDI"],
        "remote_preferences": ["hybrid", "remote"],
        "work_authorization": "France / Union européenne",
        "resume_id": "resume-1",
    }
    data.update(overrides)
    return ProfileSnapshot(**data)


def _job(**overrides) -> JobSignals:
    data = {
        "title": "Junior Data Engineer",
        "description": "Python, SQL, Airflow et dbt sur Snowflake. Paris, hybride. CDI.",
        "location": "Paris, France",
        "remote": "hybrid",
        "contract_type": "CDI",
        "skills": ["Python", "SQL", "Airflow", "dbt", "Snowflake"],
    }
    data.update(overrides)
    return JobSignals(**data)


def test_entry_level_job_scores_high_and_explains() -> None:
    result = score_job(_job(), _profile(), ScoringConfig())
    assert result.eligible is True
    assert result.score >= 80
    assert result.priority == "high"
    assert result.matched_skills
    assert result.components["skills"] > 0.8
    assert any(reason.code == "skills" for reason in result.reasons)
    assert any(reason.code == "seniority" for reason in result.reasons)


def test_senior_role_is_gated_or_heavily_penalized() -> None:
    result = score_job(
        _job(
            title="Senior Data Engineer",
            description="Au moins 6 ans d'expérience exigés. Spark, Kafka. Paris, CDI.",
            skills=["Spark", "Kafka"],
        ),
        _profile(),
        ScoringConfig(),
    )
    assert result.eligible is False
    assert result.priority == "rejected"
    assert any(reason.impact == "gate" for reason in result.reasons)


def test_location_gate() -> None:
    result = score_job(
        _job(location="Berlin, Germany", remote="onsite"),
        _profile(),
        ScoringConfig(),
    )
    assert result.eligible is False
    assert any(reason.code == "location" and reason.impact == "gate" for reason in result.reasons)


def test_remote_job_accepts_remote_preference() -> None:
    result = score_job(
        _job(location="Remote (France)", remote="remote"),
        _profile(),
        ScoringConfig(),
    )
    assert result.eligible is True


def test_contract_gate() -> None:
    result = score_job(
        _job(contract_type="freelance"),
        _profile(),
        ScoringConfig(),
    )
    assert result.eligible is False
    assert any(reason.code == "contract" for reason in result.reasons)


def test_work_authorization_gate() -> None:
    result = score_job(
        _job(
            location="Remote (United States)",
            remote="remote",
            contract_type="permanent",
            description="Fully remote. You must be authorized to work in the United States. SQL.",
            skills=["SQL"],
        ),
        _profile(),
        ScoringConfig(),
    )
    assert result.eligible is False
    assert any(reason.code == "authorization" for reason in result.reasons)


def test_profile_exclusion_criterion_gate() -> None:
    result = score_job(
        _job(description="Poste en consulting chez un client bancaire. SQL."),
        _profile(exclusion_criteria=["consulting"]),
        ScoringConfig(),
    )
    assert result.eligible is False
    assert any(reason.code == "exclusion" for reason in result.reasons)


def test_three_years_required_penalizes_but_does_not_gate() -> None:
    result = score_job(
        _job(
            title="Data Analyst",
            description="SQL. 3+ years of experience required.",
            location="Lyon, France",
            skills=["SQL"],
        ),
        _profile(),
        ScoringConfig(),
    )
    assert result.eligible is True
    assert result.score < 80
    assert any(
        reason.code == "years_required" and reason.impact == "negative"
        for reason in result.reasons
    )


def test_score_is_bounded_and_priority_band_follows_thresholds() -> None:
    config = ScoringConfig()
    result = score_job(_job(), _profile(), config)
    assert 0 <= result.score <= 100
    assert result.band == config.thresholds.band(result.score)


def test_low_relevance_job_scores_low() -> None:
    result = score_job(
        _job(
            title="Registered Nurse",
            description="Soins infirmiers, garde de nuit. Paris, CDI.",
            skills=["Soins"],
        ),
        _profile(),
        ScoringConfig(),
    )
    assert result.score < 50


def test_accepted_country_covers_its_cities() -> None:
    """Un profil qui accepte « France » ne doit pas écarter une offre à Lyon ou à Nantes."""
    from applyflow.matching.scoring import _location_match

    assert _location_match("Lyon", ["France"])
    assert _location_match("Nantes", ["France", "Paris"])
    assert _location_match("Paris, A8, France", ["France"])
    assert not _location_match("Berlin", ["France"])
    assert not _location_match("Paris, Texas, United States", ["France"])
    assert not _location_match("Lyon", ["Germany"])
    assert _location_match("Berlin", ["France", "Germany"])
    assert not _location_match("Remote", ["France"])  # sans indice de lieu, on n'invente pas
