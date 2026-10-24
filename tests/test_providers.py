from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from applyflow.providers import build_provider, provider_catalog
from applyflow.providers.adzuna import AdzunaProvider
from applyflow.providers.base import ProviderDisabled, ProviderError
from applyflow.providers.fixture import FixtureProvider
from applyflow.providers.http_providers import (
    GreenhouseProvider,
    LeverProvider,
    RssProvider,
    SingleUrlProvider,
)
from applyflow.providers.json_import import JsonFileProvider
from applyflow.schemas import JobQuery


def test_fixture_provider_filters_and_limits() -> None:
    provider = FixtureProvider()
    jobs = provider.fetch(JobQuery(limit=5))
    assert len(jobs) == 5
    analyst_jobs = provider.fetch(JobQuery(keywords=["data analyst"], limit=100))
    assert analyst_jobs
    assert all("analyst" in job.title.lower() for job in analyst_jobs)
    remote_jobs = provider.fetch(JobQuery(remote_only=True, limit=100))
    assert remote_jobs
    assert all(job.remote in {"remote", "hybrid"} for job in remote_jobs)


def test_json_file_provider(tmp_path: Path) -> None:
    path = tmp_path / "jobs.json"
    path.write_text(
        json.dumps(
            [
                {
                    "url": "https://example.invalid/job/1",
                    "company": "Acme",
                    "title": "Data Analyst",
                    "description": "SQL et Python.",
                    "location": "Paris",
                }
            ]
        ),
        encoding="utf-8",
    )
    jobs = JsonFileProvider(str(path)).fetch(JobQuery(limit=10))
    assert len(jobs) == 1
    assert jobs[0].company == "Acme"
    assert "sql" in [skill.lower() for skill in jobs[0].skills]


def test_greenhouse_provider_reads_public_board() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/acme/jobs")
        return httpx.Response(
            200,
            json={
                "jobs": [
                    {
                        "id": 12,
                        "title": "Junior Data Engineer",
                        "absolute_url": "https://boards.greenhouse.io/acme/jobs/12",
                        "location": {"name": "Paris, France"},
                        "content": "&lt;p&gt;Python, SQL, Airflow&lt;/p&gt;",
                        "updated_at": "2026-10-01T10:00:00Z",
                    }
                ]
            },
        )

    provider = GreenhouseProvider("acme", transport=httpx.MockTransport(handler))
    jobs = provider.fetch(JobQuery(limit=10))
    assert len(jobs) == 1
    assert jobs[0].title == "Junior Data Engineer"
    assert "python" in jobs[0].skills
    assert jobs[0].url.startswith("https://boards.greenhouse.io/")


def test_lever_provider_reads_public_postings() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=[
                {
                    "id": "abc",
                    "text": "Data Analyst",
                    "hostedUrl": "https://jobs.lever.co/acme/abc",
                    "applyUrl": "https://jobs.lever.co/acme/abc/apply",
                    "categories": {"location": "Lyon", "commitment": "Full-time"},
                    "descriptionPlain": "SQL, Power BI. Junior accepted.",
                    "createdAt": 1760000000000,
                }
            ],
        )

    provider = LeverProvider("acme", transport=httpx.MockTransport(handler))
    jobs = provider.fetch(JobQuery(limit=10))
    assert len(jobs) == 1
    assert jobs[0].apply_url.endswith("/apply")
    assert jobs[0].contract_type == "full-time"
    assert jobs[0].location == "Lyon"


def test_rss_provider() -> None:
    feed = """<?xml version="1.0"?>
    <rss version="2.0"><channel><title>Jobs Feed</title>
      <item>
        <title>Python Developer</title>
        <link>https://example.invalid/rss/1</link>
        <description>Python, FastAPI and SQL. Remote.</description>
        <pubDate>Mon, 01 Sep 2026 10:00:00 GMT</pubDate>
        <guid>rss-1</guid>
      </item>
    </channel></rss>"""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=feed, headers={"content-type": "application/rss+xml"})

    provider = RssProvider(
        ["https://example.invalid/feed.xml"], transport=httpx.MockTransport(handler)
    )
    jobs = provider.fetch(JobQuery(limit=10))
    assert len(jobs) == 1
    assert jobs[0].title == "Python Developer"
    assert jobs[0].remote == "remote"


def test_single_url_provider_extracts_json_ld() -> None:
    html = """
    <html><head><script type="application/ld+json">
    {"@context":"https://schema.org","@type":"JobPosting",
     "title":"Data Scientist",
     "description":"<p>Python et machine learning.</p>",
     "datePosted":"2026-09-01",
     "hiringOrganization":{"@type":"Organization","name":"Acme"},
     "jobLocation":{"@type":"Place","address":{"addressLocality":"Paris","addressCountry":"France"}},
     "baseSalary":{"@type":"MonetaryAmount","currency":"EUR","value":{"type":"QuantitativeValue","minValue":40000,"maxValue":50000}},
     "employmentType":"FULL_TIME"}
    </script></head><body></body></html>
    """

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=html, headers={"content-type": "text/html"})

    provider = SingleUrlProvider(
        "https://careers.example.invalid/jobs/1", transport=httpx.MockTransport(handler)
    )
    jobs = provider.fetch(JobQuery(limit=10))
    assert len(jobs) == 1
    assert jobs[0].company == "Acme"
    assert jobs[0].salary_min == 40000
    assert jobs[0].location.startswith("Paris")


def test_single_url_provider_requires_title() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html><body>Rien ici</body></html>")

    provider = SingleUrlProvider(
        "https://careers.example.invalid/empty", transport=httpx.MockTransport(handler)
    )
    with pytest.raises(ProviderError):
        provider.fetch(JobQuery(limit=10))


def test_adzuna_provider_normalizes_official_api_results() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(
            200,
            json={
                "count": 132,
                "results": [
                    {
                        "id": "4012345",
                        "title": "Data Engineer Junior",
                        "company": {"display_name": "Nova Retail"},
                        "location": {"display_name": "Paris, Île-de-France"},
                        "description": "Python, SQL, Airflow. CDI, télétravail partiel.",
                        "redirect_url": "https://www.adzuna.fr/details/4012345",
                        "created": "2026-10-20T08:30:00Z",
                        "contract_type": "permanent",
                        "salary_min": 42000.0,
                        "salary_max": 48000.0,
                    }
                ],
            },
        )

    provider = AdzunaProvider(
        app_id="demo-id",
        app_key="demo-key",
        transport=httpx.MockTransport(handler),
    )
    jobs = provider.fetch(JobQuery(keywords=["data engineer"], locations=["Paris"], limit=5))
    assert provider.last_count == 132
    assert len(jobs) == 1
    job = jobs[0]
    assert job.source_kind == "adzuna"
    assert job.company == "Nova Retail"
    assert job.location.startswith("Paris")
    assert job.salary_min == 42000
    assert job.salary_currency == "EUR"
    assert job.contract_type == "permanent"
    assert job.published_at is not None
    url = seen[0].url
    assert url.path.endswith("/fr/search/1")
    assert url.params["app_id"] == "demo-id"
    assert url.params["app_key"] == "demo-key"
    assert url.params["what"] == "data engineer"
    assert url.params["where"] == "Paris"


def test_adzuna_provider_requires_credentials_and_query() -> None:
    with pytest.raises(ProviderError, match="app_id"):
        AdzunaProvider().fetch(JobQuery(keywords=["data"]))
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json={"results": []}))
    with pytest.raises(ProviderError, match="mot-clé"):
        AdzunaProvider(app_id="id", app_key="key", transport=transport).fetch(JobQuery())


def test_adzuna_provider_reports_rejected_key() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": "unauthorized"})

    provider = AdzunaProvider(
        app_id="wrong", app_key="wrong", transport=httpx.MockTransport(handler)
    )
    with pytest.raises(ProviderError, match="refusé la clé"):
        provider.fetch(JobQuery(keywords=["data"], limit=1))


def test_platforms_prohibiting_automation_are_disabled() -> None:
    for kind in ("linkedin", "indeed", "welcome_to_the_jungle", "workday"):
        with pytest.raises(ProviderDisabled):
            build_provider({"kind": kind})
    catalog = {item["kind"]: item for item in provider_catalog()}
    assert catalog["linkedin"]["available"] is False
    assert "interdit" in catalog["linkedin"]["notes"].lower()


def test_single_url_forbidden_suggests_job_boards() -> None:
    """Indeed, LinkedIn… répondent 403 à une requête simple : le message doit orienter l'utilisateur."""
    transport = httpx.MockTransport(lambda request: httpx.Response(403, text="forbidden"))
    provider = SingleUrlProvider(url="https://fr.indeed.com/", transport=transport)
    with pytest.raises(ProviderError) as error:
        provider.fetch(JobQuery())
    message = str(error.value)
    assert "HTTP 403" in message and "Job boards" in message
    assert "Client error" not in message  # plus de message technique brut

    transport = httpx.MockTransport(lambda request: httpx.Response(404, text="absent"))
    other = SingleUrlProvider(url="https://exemple.fr/x", transport=transport)
    with pytest.raises(ProviderError) as error:
        other.fetch(JobQuery())
    assert "HTTP 404" in str(error.value) and "Job boards" not in str(error.value)
