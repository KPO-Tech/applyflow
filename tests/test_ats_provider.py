from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest

from applyflow.providers import build_provider
from applyflow.providers.ats_provider import AtsProvider, parse_company
from applyflow.providers.base import ProviderError
from applyflow.schemas import JobQuery


def _job(i: int, title: str, location: str, **extra: Any) -> SimpleNamespace:
    base = {
        "ats_id": str(i), "global_id": f"g{i}", "url": f"https://boards.example/{i}",
        "apply_url": None, "company": "Acme", "title": title, "description": "Python SQL. " * 30,
        "location": location, "employment_type": "FULL_TIME", "salary_min": 45000.0,
        "salary_max": None, "salary_currency": "EUR", "posted_at": datetime(2026, 10, 1, tzinfo=UTC),
        "department": "Data", "language": "fr", "is_remote": False,
    }
    return SimpleNamespace(**(base | extra))


def factory(data: dict[str, Any]) -> Any:
    def make(ats: str, slug: str, timeout: float) -> Any:
        payload = data[f"{ats}:{slug}"]

        class Scraper:
            async def afetch(self) -> list[Any]:
                if isinstance(payload, Exception):
                    raise payload
                return payload

        return Scraper()

    return make


def test_parse_company_formats_and_whitelist() -> None:
    assert parse_company("Greenhouse:datadog") == ("greenhouse", "datadog")
    assert parse_company({"ats": "lever", "slug": "qonto"}) == ("lever", "qonto")
    with pytest.raises(ProviderError, match="non pris en charge"):
        parse_company("tesla:tesla")  # scraper à navigateur furtif : refusé
    with pytest.raises(ProviderError, match="manquant"):
        parse_company("greenhouse:")


def test_filters_by_query_and_keeps_stats_per_company() -> None:
    data = {
        "greenhouse:acme": [
            _job(1, "Data Engineer Junior", "Paris, France"),
            _job(2, "Account Executive", "Paris, France"),
            _job(3, "Data Engineer", "New York"),
        ],
        "lever:beta": [_job(4, "Data Analyst", "Lyon, France", company="Beta")],
    }
    provider = AtsProvider(
        companies=["greenhouse:acme", "lever:beta"], make_scraper=factory(data), concurrency=2
    )
    jobs = provider.fetch(JobQuery(keywords=["data"], locations=["France"], limit=100))
    assert sorted(j.title for j in jobs) == ["Data Analyst", "Data Engineer Junior"]
    assert provider.last_stats["greenhouse:acme"]["total"] == 3
    assert provider.last_stats["greenhouse:acme"]["jobs"] == 1
    first = next(j for j in jobs if j.title == "Data Engineer Junior")
    assert first.contract_type == "CDI" and first.salary_min == 45000 and first.salary_max is None
    assert first.source_name == "ATS:greenhouse" and first.apply_url == first.url


def test_one_failing_company_does_not_stop_others() -> None:
    data = {"greenhouse:ok": [_job(1, "Data Engineer", "Paris")], "lever:down": RuntimeError("500")}
    provider = AtsProvider(companies=["greenhouse:ok", "lever:down"], make_scraper=factory(data))
    jobs = provider.fetch(JobQuery(keywords=["data"]))
    assert len(jobs) == 1
    assert provider.last_stats["lever:down"]["errors"] == ["500"]


def test_all_failing_raises_and_empty_config_raises() -> None:
    provider = AtsProvider(
        companies=["lever:down"], make_scraper=factory({"lever:down": RuntimeError("boom")})
    )
    with pytest.raises(ProviderError, match="aucune entreprise ATS"):
        provider.fetch(JobQuery(keywords=["x"]))
    with pytest.raises(ProviderError, match="aucune entreprise configurée"):
        AtsProvider().fetch(JobQuery())


def test_registry_builds_ats_provider() -> None:
    provider = build_provider({"kind": "ats", "config": {"companies": ["greenhouse:datadog"]}})
    assert provider.kind == "ats"
