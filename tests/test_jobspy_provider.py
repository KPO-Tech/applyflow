from __future__ import annotations

from typing import Any

import pandas as pd
import pytest

from applyflow.config import Settings
from applyflow.providers import build_provider
from applyflow.providers.base import ProviderError
from applyflow.providers.jobspy_provider import JobSpyProvider
from applyflow.schemas import JobQuery


def _frame(site: str, n: int, *, error: str | None = None) -> pd.DataFrame:
    rows = [
        {
            "id": f"{site}-{i}",
            "job_url": f"https://{site}.example/jobs/{i}",
            "job_url_direct": None,
            "title": f"Data Engineer junior {i}",
            "company": "Acme" if i else None,
            "location": "Paris, France",
            "date_posted": pd.Timestamp("2026-10-20").date(),
            "job_type": "fulltime",
            "interval": "yearly",
            "min_amount": 40000.0,
            "max_amount": float("nan"),
            "currency": "EUR",
            "is_remote": False,
            "description": "Python et SQL, débutant accepté. " * 5,
            "skills": None,
        }
        for i in range(n)
    ]
    frame = pd.DataFrame(rows)
    frame.attrs = {"errors": {site: error} if error else {}}
    return frame


def fake_scrape(counts: dict[str, int], errors: dict[str, str] | None = None) -> Any:
    calls: list[dict[str, Any]] = []

    def scrape(**kwargs: Any) -> pd.DataFrame:
        calls.append(kwargs)
        site = kwargs["site_name"][0]
        return _frame(site, counts.get(site, 0), error=(errors or {}).get(site))

    scrape.calls = calls  # type: ignore[attr-defined]
    return scrape


def test_disabled_by_default_in_settings() -> None:
    provider = build_provider({"kind": "jobspy"}, settings=Settings())
    with pytest.raises(ProviderError, match="désactivé"):
        provider.fetch(JobQuery(keywords=["data engineer"]))


def test_campaign_cannot_override_global_switch() -> None:
    provider = build_provider({"kind": "jobspy", "config": {"enabled": True}}, settings=Settings())
    assert provider.enabled is False  # type: ignore[attr-defined]


def test_collects_normalizes_and_counts_per_site() -> None:
    sleeps: list[float] = []
    scrape = fake_scrape({"indeed": 3, "hellowork": 2})
    provider = JobSpyProvider(
        sites=["indeed", "hellowork"], scrape=scrape, sleep=sleeps.append, pause_seconds=4
    )
    jobs = provider.fetch(JobQuery(keywords=["data engineer"], locations=["Paris"], limit=50))
    assert len(jobs) == 5
    assert provider.last_stats["indeed"]["jobs"] == 3
    assert provider.last_stats["hellowork"]["jobs"] == 2
    assert sleeps == [4.0]  # une pause entre deux requêtes, jamais avant la première
    job = jobs[0]
    assert job.source_name == "JobSpy:indeed"
    assert job.contract_type == "CDI"
    assert job.salary_min == 40000 and job.salary_max is None
    assert job.description  # description complète conservée
    assert any(j.company == "Entreprise non communiquée" for j in jobs)  # pas d'invention


def test_blocked_site_is_dropped_but_others_continue() -> None:
    scrape = fake_scrape(
        {"linkedin": 0, "indeed": 2},
        errors={"linkedin": "response status code 429 (blocked: use a proxy)"},
    )
    provider = JobSpyProvider(
        sites=["linkedin", "indeed"], scrape=scrape, sleep=lambda _: None
    )
    jobs = provider.fetch(JobQuery(keywords=["a", "b"], locations=["France"]))
    linkedin_calls = [c for c in scrape.calls if c["site_name"] == ["linkedin"]]
    assert len(linkedin_calls) == 1  # pas d'insistance après un 429
    assert len(jobs) == 4
    assert provider.last_stats["linkedin"]["errors"]


def test_all_sites_blocked_raises() -> None:
    scrape = fake_scrape({}, errors={"indeed": "status code 403 (blocked)"})
    provider = JobSpyProvider(sites=["indeed"], scrape=scrape, sleep=lambda _: None)
    with pytest.raises(ProviderError, match="bloqué"):
        provider.fetch(JobQuery(keywords=["x"]))


def test_limit_caps_volume_and_unknown_site_rejected() -> None:
    scrape = fake_scrape({"indeed": 50})
    provider = JobSpyProvider(sites=["indeed"], scrape=scrape, max_per_site=10)
    provider.fetch(JobQuery(keywords=["x"], limit=1000))
    assert scrape.calls[0]["results_wanted"] == 10
    with pytest.raises(ProviderError, match="non supporté"):
        JobSpyProvider(sites=["monster"])
