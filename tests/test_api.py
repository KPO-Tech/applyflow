from __future__ import annotations

from applyflow.schemas import NormalizedJob
from applyflow.seed import SAMPLE_CV


def _profile_payload() -> dict:
    return {
        "name": "Data Engineer",
        "full_name": "Camille Martin",
        "email": "camille.martin@example.invalid",
        "phone": "+33 6 00 00 00 00",
        "city": "Paris",
        "target_titles": ["Data Engineer"],
        "technical_skills": ["Python", "SQL", "Airflow", "dbt", "Snowflake"],
        "experience_level": "junior",
        "years_experience": 2,
        "locations": ["France", "Paris", "Remote"],
        "contract_types": ["CDI"],
        "remote_preferences": ["hybrid", "remote"],
        "salary_min": 40000,
        "work_authorization": "France / Union européenne",
    }


def test_health_and_settings(api_client) -> None:
    health = api_client.get("/health")
    assert health.status_code == 200
    assert health.json()["status"] == "ok"
    settings = api_client.get("/settings")
    assert settings.status_code == 200
    assert settings.json()["application"]["dry_run"] is True
    updated = api_client.put(
        "/settings", json={"scoring": {"thresholds": {"high": 85, "medium": 70, "min_apply": 60}}}
    )
    assert updated.status_code == 200
    assert "saved_to" in updated.json()


def test_discovery_retry_settings_are_persisted(api_client) -> None:
    response = api_client.put("/settings", json={"discovery": {"retry_attempts": 4}})
    assert response.status_code == 200
    payload = api_client.get("/settings").json()
    assert payload["discovery"]["retry_attempts"] == 4
    # Les autres clés de la section survivent à une mise à jour partielle.
    assert payload["discovery"]["rate_limit_seconds"] == 0


def test_adzuna_settings_test_and_discovery(api_client, monkeypatch) -> None:
    def catalog() -> dict:
        return {item["kind"]: item for item in api_client.get("/sources").json()}

    assert catalog()["adzuna"]["available"] is True
    assert catalog()["adzuna"]["configured"] is False

    saved = api_client.put(
        "/settings",
        json={
            "adzuna": {
                "app_id": "my-id",
                "app_key": "secret-key",
                "country": "fr",
                "max_pages": 2,
            }
        },
    )
    assert saved.status_code == 200
    payload = api_client.get("/settings").json()
    assert payload["adzuna"]["app_id"] == "my-id"
    assert payload["adzuna"]["app_key"] == "***"
    assert catalog()["adzuna"]["configured"] is True

    # Un client qui renvoie la valeur masquée ne doit pas écraser la clé stockée.
    api_client.put("/settings", json={"adzuna": {"app_id": "my-id", "app_key": "***"}})
    assert api_client.app.state.settings.adzuna.app_key == "secret-key"

    sample = NormalizedJob(
        source_kind="adzuna",
        url="https://www.adzuna.fr/details/1",
        company="Nova Retail",
        title="Data Engineer",
        location="Paris",
    )
    received: dict = {}

    class FakeAdzuna:
        kind = "adzuna"
        capabilities = None
        last_count = 57

        def __init__(self, **kwargs) -> None:
            received.update(kwargs)

        def fetch(self, query):
            assert query.keywords == ["data engineer"]
            return [sample]

    monkeypatch.setattr("applyflow.api.main.AdzunaProvider", FakeAdzuna)
    result = api_client.post("/sources/adzuna/test", json={"keywords": ["data engineer"]})
    assert result.status_code == 200
    assert result.json()["total"] == 57
    assert result.json()["sample"][0]["company"] == "Nova Retail"

    def fake_build_provider(spec, settings=None):
        received.update(
            spec=spec,
            app_id=settings.adzuna.app_id if settings else None,
            app_key=settings.adzuna.app_key if settings else None,
        )
        return FakeAdzuna()

    monkeypatch.setattr("applyflow.jobs.service.build_provider", fake_build_provider)
    discovery = api_client.post(
        "/discovery",
        json={"source": {"kind": "adzuna"}, "keywords": ["data engineer"], "limit": 5},
    )
    assert discovery.status_code == 200
    assert discovery.json()["created"] == 1, discovery.json()
    # Les réglages enregistrés à chaud sont bien ceux utilisés par la collecte.
    assert received["app_id"] == "my-id"
    assert received["app_key"] == "secret-key"


def test_profile_creation_and_resume_upload(api_client) -> None:
    created = api_client.post("/profiles", json=_profile_payload())
    assert created.status_code == 201
    profile = created.json()
    assert profile["name"] == "Data Engineer"
    uploaded = api_client.post(
        f"/profiles/{profile['id']}/resumes",
        files={"file": ("cv.pdf", SAMPLE_CV.read_bytes(), "application/pdf")},
    )
    assert uploaded.status_code == 201
    assert uploaded.json()["is_active"] is True
    invalid = api_client.post(
        f"/profiles/{profile['id']}/resumes",
        files={"file": ("cv.txt", b"nope", "text/plain")},
    )
    assert invalid.status_code == 400


def test_resume_preview_serves_the_stored_pdf(api_client) -> None:
    profile = api_client.post("/profiles", json=_profile_payload()).json()
    uploaded = api_client.post(
        f"/profiles/{profile['id']}/resumes",
        files={"file": ("cv.pdf", SAMPLE_CV.read_bytes(), "application/pdf")},
    ).json()

    preview = api_client.get(f"/profiles/{profile['id']}/resumes/{uploaded['id']}/file")
    assert preview.status_code == 200
    # Affiché dans le navigateur plutôt que téléchargé : c'est une prévisualisation.
    assert preview.headers["content-type"] == "application/pdf"
    assert preview.headers["content-disposition"] == "inline"
    assert preview.content == SAMPLE_CV.read_bytes()

    # Un CV n'est jamais servi à travers le profil d'un autre, ni pour un identifiant inconnu.
    other = api_client.post(
        "/profiles", json={**_profile_payload(), "name": "Autre profil"}
    ).json()
    assert api_client.get(f"/profiles/{other['id']}/resumes/{uploaded['id']}/file").status_code == 404
    assert api_client.get(f"/profiles/{profile['id']}/resumes/inconnu/file").status_code == 404


def test_discovery_and_campaign_run_over_api(api_client) -> None:
    profile = api_client.post("/profiles", json=_profile_payload()).json()
    api_client.post(
        f"/profiles/{profile['id']}/resumes",
        files={"file": ("cv.pdf", SAMPLE_CV.read_bytes(), "application/pdf")},
    )
    sources = api_client.get("/sources").json()
    assert any(item["kind"] == "greenhouse" and item["available"] for item in sources)
    assert any(item["kind"] == "linkedin" and not item["available"] for item in sources)

    discovery = api_client.post(
        "/discovery", json={"source": {"kind": "fixture"}, "limit": 10}
    )
    assert discovery.status_code == 200
    assert discovery.json()["created"] >= 8  # le jeu de données contient un doublon volontaire

    campaign = api_client.post(
        "/campaigns",
        json={
            "name": "Campagne API",
            "sources": [{"kind": "fixture"}],
            "profile_ids": [profile["id"]],
            "max_jobs": 4,
            "min_score": 0,
        },
    )
    assert campaign.status_code == 201
    campaign_id = campaign.json()["id"]
    run = api_client.post(
        f"/campaigns/{campaign_id}/run",
        json={"steps": ["discover", "analyze"], "max_items": 3},
    )
    assert run.status_code == 200
    assert run.json()["status"] == "paused"
    results = api_client.get(f"/campaigns/{campaign_id}/results").json()
    assert len(results) == 4
    assert all("score" in item for item in results)
    dashboard = api_client.get("/dashboard").json()
    assert dashboard["jobs_collected"] >= 10
    assert api_client.get("/queue").status_code == 200


def test_web_ui_and_profile_activation(api_client) -> None:
    root = api_client.get("/")
    assert root.status_code == 200
    assert root.headers["content-type"].startswith("text/html")
    assert "/assets/app.js" in root.text
    assert "ApplyFlow" in root.text

    assets = [
        "/assets/styles.css",
        "/assets/app.js",
        "/assets/api.js",
        "/assets/ui.js",
        "/assets/icons.js",
        "/assets/store.js",
        "/assets/pages/dashboard.js",
        "/assets/pages/campaigns.js",
        "/assets/pages/queue.js",
        "/assets/pages/applications.js",
        "/assets/pages/emails.js",
        "/assets/pages/profiles.js",
        "/assets/pages/discovery.js",
        "/assets/pages/settings.js",
    ]
    for asset in assets:
        response = api_client.get(asset)
        assert response.status_code == 200, asset
    assert api_client.get("/assets/styles.css").headers["content-type"].startswith("text/css")
    assert api_client.get("/assets/app.js").headers["content-type"].startswith("text/javascript")

    profile = api_client.post("/profiles", json=_profile_payload()).json()
    deactivated = api_client.post(f"/profiles/{profile['id']}/deactivate")
    assert deactivated.status_code == 200
    assert deactivated.json()["active"] is False
    activated = api_client.post(f"/profiles/{profile['id']}/activate")
    assert activated.status_code == 200
    assert activated.json()["active"] is True


def test_jobs_import_and_answers(api_client) -> None:
    response = api_client.post(
        "/jobs/import",
        json={
            "jobs": [
                {
                    "url": "https://example.invalid/job/42",
                    "company": "Acme",
                    "title": "Data Analyst",
                    "description": "SQL et Python. Paris.",
                    "location": "Paris",
                }
            ]
        },
    )
    assert response.status_code == 200
    assert response.json()["created"] == 1
    jobs = api_client.get("/jobs").json()
    assert any(job["company"] == "Acme" for job in jobs)

    answer = api_client.post(
        "/answers", json={"question_text": "What is your notice period?", "answer": "1 month"}
    )
    assert answer.status_code == 201
    answers = api_client.get("/answers").json()
    assert answers[0]["question_text"] == "What is your notice period?"
