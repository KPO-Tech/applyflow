"""Plafond quotidien par site et classement des offres par pays."""

from __future__ import annotations

import inspect
from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from applyflow.config import Settings
from applyflow.db.models import Job
from applyflow.geo import detect_country, normalize_country
from applyflow.jobs.service import (
    backfill_countries,
    count_jobs_by_country,
    ingest_jobs,
    list_jobs,
)
from applyflow.providers import build_provider
from applyflow.providers.base import ProviderError
from applyflow.providers.jobspy_provider import JobSpyProvider
from applyflow.schemas import JobQuery, NormalizedJob
from applyflow.usage import UsageStore

# ---------------------------------------------------------------- plafond quotidien


def frame(site: str, count: int) -> pd.DataFrame:
    rows = [
        {
            "id": f"{site}-{i}", "job_url": f"https://{site}.example/{i}", "title": f"Data {i}",
            "company": "Acme", "location": "Paris, France", "description": "Python SQL. " * 30,
        }
        for i in range(count)
    ]
    result = pd.DataFrame(rows)
    result.attrs = {"errors": {}}
    return result


def strict_scrape(calls: list[dict[str, Any]]) -> Any:
    """Faux JobSpy qui refuse tout argument absent de la vraie signature de `scrape_jobs`."""
    jobspy = pytest.importorskip("jobspy")
    allowed = set(inspect.signature(jobspy.scrape_jobs).parameters)

    def scrape(**kwargs: Any) -> pd.DataFrame:
        unknown = set(kwargs) - allowed
        assert not unknown, f"arguments inconnus de JobSpy : {unknown}"
        calls.append(kwargs)
        return frame(kwargs["site_name"][0], kwargs["results_wanted"])

    return scrape


def test_usage_store_counts_per_day_and_persists(tmp_path: Path) -> None:
    day = {"value": date(2026, 10, 23)}
    path = tmp_path / "usage.json"
    store = UsageStore(path, limits={"linkedin": 10}, today=lambda: day["value"])
    store.consume("linkedin", 4)
    assert UsageStore(path, limits={"linkedin": 10}, today=lambda: day["value"]).remaining(
        "linkedin"
    ) == 6  # mémorisé entre deux lancements
    day["value"] = date(2026, 10, 24)
    assert store.remaining("linkedin") == 10  # nouveau jour, compteur remis à zéro
    assert store.remaining("inconnu") is None
    assert UsageStore(path, limits={"linkedin": 0}).limit("linkedin") is None  # 0 = sans plafond


def test_provider_never_exceeds_daily_limit(tmp_path: Path) -> None:
    calls: list[dict[str, Any]] = []
    budget = UsageStore(tmp_path / "usage.json", limits={"indeed": 15, "linkedin": 5})
    provider = JobSpyProvider(
        sites=["indeed", "linkedin"], scrape=strict_scrape(calls), sleep=lambda _: None,
        budget=budget, max_per_site=100,
    )
    jobs = provider.fetch(JobQuery(keywords=["data"], limit=1000))
    assert len(jobs) == 20  # 15 Indeed + 5 LinkedIn, jamais plus
    assert budget.remaining("indeed") == 0 and budget.remaining("linkedin") == 0
    assert provider.daily_usage["linkedin"] == {"used": 5, "limit": 5, "remaining": 0}

    again = JobSpyProvider(
        sites=["indeed", "linkedin"], scrape=strict_scrape(calls), sleep=lambda _: None,
        budget=budget,
    )
    before = len(calls)
    with pytest.raises(ProviderError, match="plafond quotidien atteint"):
        again.fetch(JobQuery(keywords=["data"]))
    assert len(calls) == before  # aucune requête une fois le plafond atteint


def test_exhausted_site_is_skipped_but_others_continue(tmp_path: Path) -> None:
    calls: list[dict[str, Any]] = []
    budget = UsageStore(tmp_path / "usage.json", limits={"linkedin": 3, "indeed": 50})
    budget.consume("linkedin", 3)
    provider = JobSpyProvider(
        sites=["linkedin", "indeed"], scrape=strict_scrape(calls), sleep=lambda _: None,
        budget=budget, max_per_site=10,
    )
    jobs = provider.fetch(JobQuery(keywords=["data"]))
    assert len(jobs) == 10 and {c["site_name"][0] for c in calls} == {"indeed"}
    assert "plafond quotidien" in provider.last_stats["linkedin"]["errors"][0]


def test_registry_applies_global_limits(settings: Settings) -> None:
    settings.boards.jobspy_enabled = True
    settings.boards.daily_limits = {"linkedin": 12}
    provider = build_provider(
        {"kind": "jobspy", "config": {"budget": None}}, settings=settings
    )
    assert provider.budget is not None  # type: ignore[attr-defined]
    assert provider.budget.limit("linkedin") == 12  # type: ignore[attr-defined]


def test_default_limits_are_conservative(settings: Settings) -> None:
    limits = settings.boards.daily_limits
    assert limits["linkedin"] < limits["indeed"]


# ---------------------------------------------------------------- pays


@pytest.mark.parametrize(
    ("location", "iso"),
    [
        ("Paris, Île-de-France, France", "FR"),
        ("Paris, A8, France", "FR"),
        ("Paris", "FR"),
        ("London, United Kingdom", "GB"),
        ("Berlin", "DE"),
        ("Berlin, Allemagne", "DE"),
        ("Paris, Texas, United States", "US"),
        ("Bruxelles", "BE"),
        ("Genève, Suisse", "CH"),
        ("France, Remote; Spain, Remote", "FR"),
        ("Remote", None),
        ("", None),
        (None, None),
    ],
)
def test_detect_country(location: str | None, iso: str | None) -> None:
    assert detect_country(location) == iso


def test_country_hint_is_only_a_fallback() -> None:
    assert detect_country("Remote", default="france") == "FR"
    assert detect_country("Berlin, Germany", default="france") == "DE"
    assert normalize_country("uk") == "GB" and normalize_country("FR") == "FR"
    assert normalize_country("Atlantide") is None
    assert normalize_country("Paris") is None  # une ville n'est pas un pays
    assert normalize_country("Berlin") is None


def job(url: str, company: str, location: str | None, country: str | None = None) -> NormalizedJob:
    return NormalizedJob(
        source_kind="test", url=url, company=company, title=f"Data Engineer {company}",
        location=location, country=country, description="Python SQL " * 30,
    )


def test_ingest_stores_country_and_filters(session) -> None:
    ingest_jobs(
        session,
        [
            job("https://x/1", "Alpha", "Paris, France"),
            job("https://x/2", "Beta", "Lyon", country="fr"),
            job("https://x/3", "Gamma", "London, United Kingdom"),
            job("https://x/4", "Delta", "Remote"),
        ],
    )
    assert {j.country for j in list_jobs(session, country="FR")} == {"FR"}
    assert len(list_jobs(session, country="FR")) == 2
    assert len(list_jobs(session, country="fr,gb")) == 3
    assert [j.company for j in list_jobs(session, country="unknown")] == ["Delta"]
    counts = {row["country"]: row["count"] for row in count_jobs_by_country(session)}
    assert counts == {"FR": 2, "GB": 1, "unknown": 1}


def test_backfill_fills_missing_country(session) -> None:
    session.add(
        Job(
            source_kind="x", url="https://x/9", url_key="k9", company="Old", title="T",
            description="d", location="Madrid, Spain", fingerprint="fp9", raw={},
        )
    )
    session.flush()
    assert backfill_countries(session) == 1
    assert session.query(Job).one().country == "ES"


def test_api_filters_by_country(api_client) -> None:
    api_client.post(
        "/jobs/import",
        json={"jobs": [
            {"url": "https://x/a", "company": "A", "title": "Data Analyst", "location": "Paris, France",
             "description": "SQL " * 30},
            {"url": "https://x/b", "company": "B", "title": "Data Analyst", "location": "Berlin, Germany",
             "description": "SQL " * 30},
        ]},
    )
    france = api_client.get("/jobs", params={"country": "FR"}).json()
    assert [row["company"] for row in france] == ["A"] and france[0]["country"] == "FR"
    countries = {row["country"] for row in api_client.get("/jobs/countries").json()}
    assert {"FR", "DE"} <= countries
