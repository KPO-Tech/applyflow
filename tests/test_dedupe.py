from __future__ import annotations

from sqlalchemy import func, select

from applyflow.db.models import Job
from applyflow.jobs.dedupe import (
    canonical_url,
    job_fingerprint,
    normalize_company,
    url_key,
)
from applyflow.jobs.service import ingest_jobs
from applyflow.providers.fixture import FixtureProvider
from applyflow.schemas import JobQuery


def test_company_and_title_fingerprint_normalization() -> None:
    assert normalize_company("Nova Retail SAS") == normalize_company("Nova Retail")
    left = job_fingerprint("Nova Retail", "Junior Data Engineer", "Paris, France")
    right = job_fingerprint(
        "Nova Retail SAS", "Junior Data Engineer (H/F)", "Paris, France"
    )
    assert left == right


def test_fingerprint_differs_on_location() -> None:
    assert job_fingerprint("Acme", "Data Analyst", "Paris") != job_fingerprint(
        "Acme", "Data Analyst", "Lyon"
    )


def test_canonical_url_drops_tracking_but_keeps_job_id() -> None:
    url = "https://www.Example.com/jobs/42?utm_source=x&gh_jid=99&ref=abc"
    canonical = canonical_url(url)
    assert canonical.startswith("https://example.com/jobs/42")
    assert "utm_source" not in canonical
    assert "gh_jid=99" in canonical
    assert url_key(url) == url_key(url + "&utm_campaign=other")


def test_ingest_is_idempotent_and_links_existing_job(session) -> None:
    provider = FixtureProvider()
    jobs = provider.fetch(JobQuery(limit=1000))
    assert len(jobs) == 34
    first = ingest_jobs(session, jobs)
    assert first.created == 33
    assert first.duplicates == 1
    job_ids = set(first.job_ids)
    assert len(job_ids) == 33

    second = ingest_jobs(session, jobs)
    assert second.created == 0
    assert second.duplicates == 34
    total = session.scalar(select(func.count()).select_from(Job))
    assert total == 33


def test_ingest_duplicate_in_same_batch(session) -> None:
    provider = FixtureProvider()
    jobs = provider.fetch(JobQuery(limit=1000))
    duplicate = jobs[0].model_copy(
        update={"url": "https://another-board.example/job/1", "source_kind": "other"}
    )
    result = ingest_jobs(session, [jobs[0], duplicate])
    assert result.created == 1
    assert result.duplicates == 1
    assert len(result.job_ids) == 2
