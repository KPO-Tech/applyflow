"""Déduplication interplateformes, sur des cas observés lors de collectes réelles."""

from __future__ import annotations

import pytest
from sqlalchemy import func, select

from applyflow.db.models import Job
from applyflow.jobs.dedupe import city_of, is_probable_duplicate, job_fingerprint
from applyflow.jobs.service import ingest_jobs, rebuild_fingerprints
from applyflow.schemas import NormalizedJob

DESCRIPTION = (
    "Rejoignez notre équipe data pour construire et maintenir les pipelines de données, "
    "orchestrer les flux avec Airflow, modéliser les données avec dbt et assurer la qualité "
    "des livrables en production avec Python et SQL sur une plateforme cloud moderne. "
) * 2


def job(source: str, title: str, location: str, *, company: str = "GitGuardian", url: str = "",
        description: str = DESCRIPTION) -> NormalizedJob:
    return NormalizedJob(
        source_kind="jobspy", source_name=f"JobSpy:{source}", external_id=f"{source}-1",
        url=url or f"https://{source}.example/job/{title.replace(' ', '-')}",
        company=company, title=title, location=location, description=description,
    )


@pytest.mark.parametrize(
    ("raw", "city"),
    [
        ("Paris, A8, France", "paris"),
        ("Paris, Île-de-France, France", "paris"),
        ("Paris, France", "paris"),
        ("France - Paris", "paris"),
        ("75008 Paris", "paris"),
        ("Paris 15e", "paris"),
        ("Saint-Denis, 93, France", "saint-denis"),
        ("France", ""),
        ("Remote", ""),
        (None, ""),
    ],
)
def test_city_of(raw: str | None, city: str) -> None:
    assert city_of(raw) == city


def test_same_job_on_three_platforms_is_one_job() -> None:
    fingerprints = {
        job_fingerprint("GitGuardian", "Junior Data Engineer", location)
        for location in ("Paris, A8, France", "Paris, Île-de-France, France", "Paris, France")
    }
    assert len(fingerprints) == 1


def test_ingest_merges_platforms_and_keeps_every_source(session) -> None:
    batch = [
        job("indeed", "Junior Data Engineer", "Paris, A8, France"),
        job("linkedin", "Junior Data Engineer", "Paris, Île-de-France, France"),
        job("glassdoor", "Junior Data Engineer", "Paris, France"),
    ]
    result = ingest_jobs(session, batch)
    assert (result.created, result.duplicates) == (1, 2)
    stored = session.scalars(select(Job)).one()
    sources = {entry["source"] for entry in stored.raw["sources"]}
    assert sources == {"JobSpy:indeed", "JobSpy:linkedin", "JobSpy:glassdoor"}
    again = ingest_jobs(session, batch)  # relancer ne duplique ni l'offre ni les sources
    assert again.created == 0
    assert len(session.scalars(select(Job)).one().raw["sources"]) == 3


def test_near_duplicate_title_with_same_description_is_merged(session) -> None:
    ingest_jobs(session, [job("indeed", "Data Engineer Junior", "Paris, France")])
    result = ingest_jobs(
        session, [job("hellowork", "Data Engineer Junior - Boulogne CDI", "Paris, 75, France")]
    )
    assert result.duplicates == 1


def test_junior_and_senior_are_different_jobs() -> None:
    assert not is_probable_duplicate(
        company_a="Converteo", title_a="Consultant Data Engineer Junior H/F",
        location_a="Paris, France", description_a=DESCRIPTION,
        company_b="Converteo", title_b="Consultant Data Engineer Senior H/F",
        location_b="Paris, France", description_b=DESCRIPTION,
    )


def test_different_city_or_company_never_merge(session) -> None:
    ingest_jobs(session, [job("indeed", "Data Engineer", "Paris, France")])
    result = ingest_jobs(
        session,
        [
            job("indeed", "Data Engineer", "Lyon, France", url="https://indeed.example/lyon"),
            job(
                "indeed", "Data Engineer", "Paris, France", company="Autre Société",
                url="https://indeed.example/autre",
            ),
        ],
    )
    assert result.created == 2
    assert session.scalar(select(func.count()).select_from(Job)) == 3


def test_same_title_different_content_in_same_city_stay_apart(session) -> None:
    other = "Poste très différent : maintenance de réseaux électriques haute tension. " * 6
    ingest_jobs(session, [job("indeed", "Ingénieur Data Projet Alpha", "Paris")])
    result = ingest_jobs(
        session, [job("linkedin", "Ingénieur Data Projet Omega", "Paris", description=other)]
    )
    assert result.created == 1


def test_rebuild_fingerprints_merges_legacy_duplicates(session) -> None:
    for source, location in (("indeed", "Paris, A8, France"), ("glassdoor", "Paris, France")):
        session.add(
            Job(
                source_kind="jobspy", external_id=source, url=f"https://{source}.example/1",
                url_key=source, company="Pigment", title="Junior Backend Engineer",
                description=DESCRIPTION, location=location, fingerprint=f"old-{source}", raw={},
            )
        )
    session.flush()
    report = rebuild_fingerprints(session)
    assert report["merged"] == 1
    kept = session.scalars(select(Job)).one()
    assert len(kept.raw["sources"]) == 2


def test_job_board_urls_keep_their_identifier() -> None:
    """Indeed (?jk=) et Glassdoor (?jl=) n'ont pas d'identifiant dans le chemin."""
    from applyflow.jobs.dedupe import url_key

    assert url_key("https://fr.indeed.com/viewjob?jk=aaa&from=serp") != url_key(
        "https://fr.indeed.com/viewjob?jk=bbb"
    )
    assert url_key("https://www.glassdoor.fr/job-listing/j?jl=1&src=x") != url_key(
        "https://www.glassdoor.fr/job-listing/j?jl=2"
    )
    assert url_key("https://fr.indeed.com/viewjob?jk=aaa&utm_source=x") == url_key(
        "https://fr.indeed.com/viewjob?jk=aaa"
    )
