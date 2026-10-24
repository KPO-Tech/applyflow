"""Une campagne sur les offres déjà en bibliothèque, étape par étape."""

from __future__ import annotations

from typing import Any

from applyflow.seed import SAMPLE_CV

DESCRIPTION = "Python, SQL, Airflow et dbt pour des pipelines de données en production. " * 6


def profile_payload() -> dict[str, Any]:
    return {
        "name": "Data Engineer", "full_name": "Camille Martin", "email": "camille@example.invalid",
        "phone": "+33 6 00 00 00 00", "city": "Paris", "target_titles": ["Data Engineer"],
        "technical_skills": ["Python", "SQL", "Airflow", "dbt"], "experience_level": "junior",
        "years_experience": 1, "locations": ["France", "Paris"], "contract_types": ["CDI"],
        "remote_preferences": ["hybrid"], "salary_min": 35000,
        "work_authorization": "France / Union européenne",
    }


def job(i: int, title: str, location: str, company: str = "Acme") -> dict[str, Any]:
    return {"url": f"https://exemple.test/{i}", "company": f"{company}{i}", "title": title,
            "location": location, "description": DESCRIPTION}


def setup(api_client, campaign_extra: dict[str, Any] | None = None) -> str:
    profile = api_client.post("/profiles", json=profile_payload()).json()
    api_client.post(
        f"/profiles/{profile['id']}/resumes",
        files={"file": ("cv.pdf", SAMPLE_CV.read_bytes(), "application/pdf")},
    )
    api_client.post("/jobs/import", json={"jobs": [
        job(1, "Data Engineer junior", "Paris, France"),
        job(2, "Data Engineer", "Lyon"),
        job(3, "Data Analyst junior", "Berlin, Germany"),
        job(4, "Chef de cuisine", "Paris"),
    ]})
    body = {"name": "Atelier", "sources": [{"kind": "library"}], "profile_ids": [profile["id"]],
            "min_score": 0, **(campaign_extra or {})}
    response = api_client.post("/campaigns", json=body)
    assert response.status_code == 201, response.text
    return response.json()["id"]


def run(api_client, campaign_id: str, steps: list[str], **extra: Any) -> dict[str, Any]:
    response = api_client.post(f"/campaigns/{campaign_id}/run", json={"steps": steps, **extra})
    assert response.status_code == 200, response.text
    return response.json()


def stages(api_client, campaign_id: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in api_client.get(f"/campaigns/{campaign_id}/results").json():
        counts[row["stage"]] = counts.get(row["stage"], 0) + 1
    return counts


def test_library_source_reuses_collected_offers_without_collecting(api_client) -> None:
    campaign_id = setup(api_client)
    summary = run(api_client, campaign_id, ["discover"])["steps"]["discover"]
    assert summary["linked"] == 4 and summary["from_library"] == 4
    assert summary["created"] == 0 and summary["errors"] == []  # aucune collecte, aucun réseau
    assert stages(api_client, campaign_id) == {"discovered": 4}
    # Relancer ne rajoute rien : une offre n'est suivie qu'une fois par campagne.
    again = run(api_client, campaign_id, ["discover"])["steps"]["discover"]
    assert again["linked"] == 0


def test_library_respects_keywords_locations_and_country(api_client) -> None:
    campaign_id = setup(
        api_client, {"keywords": ["data"], "locations": ["France"]}
    )
    assert run(api_client, campaign_id, ["discover"])["steps"]["discover"]["linked"] == 2  # Paris + Lyon
    titles = {row["job"]["title"] for row in api_client.get(f"/campaigns/{campaign_id}/results").json()}
    assert titles == {"Data Engineer junior", "Data Engineer"}

    only_germany = setup(
        api_client, {"name": "Allemagne", "sources": [{"kind": "library", "config": {"country": "DE"}}]}
    )
    assert run(api_client, only_germany, ["discover"])["steps"]["discover"]["linked"] == 1


def test_steps_run_one_at_a_time_and_can_be_inspected(api_client) -> None:
    campaign_id = setup(api_client)
    run(api_client, campaign_id, ["discover"])
    assert stages(api_client, campaign_id) == {"discovered": 4}

    analyze = run(api_client, campaign_id, ["analyze"])
    assert analyze["status"] == "paused"  # en attente de l'étape suivante
    assert set(analyze["steps"]) == {"analyze"}
    counts = stages(api_client, campaign_id)
    assert "discovered" not in counts and sum(counts.values()) == 4
    rows = api_client.get(f"/campaigns/{campaign_id}/results").json()
    assert all(row["score"] is not None and row["reasons"] for row in rows)  # score + raisons

    prepare = run(api_client, campaign_id, ["prepare"])
    assert set(prepare["steps"]) == {"prepare"}
    assert set(prepare["steps"]["prepare"]) >= {"prepared", "needs_review", "blocked", "skipped"}


def test_redo_reanalyzes_already_scored_offers(api_client) -> None:
    campaign_id = setup(api_client)
    run(api_client, campaign_id, ["discover", "analyze"])
    before = stages(api_client, campaign_id)
    assert run(api_client, campaign_id, ["analyze"])["steps"]["analyze"] == {
        "analyzed": 0, "rejected": 0, "errors": 0, "remaining": 0  # rien à faire : tout est déjà noté
    }
    redone = run(api_client, campaign_id, ["analyze"], redo=True)["steps"]["analyze"]
    assert redone["analyzed"] + redone["rejected"] == sum(before.values())
    assert stages(api_client, campaign_id) == before  # mêmes critères : même résultat


def test_analyze_without_profile_explains_what_to_do(api_client) -> None:
    api_client.post("/jobs/import", json={"jobs": [job(1, "Data Engineer", "Paris")]})
    response = api_client.post(
        "/campaigns", json={"name": "Sans profil", "sources": [{"kind": "library"}]}
    )
    campaign_id = response.json()["id"]
    run(api_client, campaign_id, ["discover"])
    failed = api_client.post(f"/campaigns/{campaign_id}/run", json={"steps": ["analyze"]})
    assert failed.status_code == 409 and "profil" in failed.json()["detail"]
