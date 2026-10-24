"""Le filtre de localisation comprend les pays : « France » retrouve « Paris »."""

from __future__ import annotations

import pytest

from applyflow.providers.base import apply_query_filters, location_matches
from applyflow.schemas import JobQuery, NormalizedJob


@pytest.mark.parametrize(
    ("job_location", "wanted", "expected"),
    [
        ("Paris", ["France"], True),  # le pays est déduit de la ville
        ("Paris, France", ["France"], True),
        ("Lyon", ["Paris"], False),
        ("Paris, Île-de-France", ["Paris"], True),  # correspondance par texte, comme avant
        ("Berlin", ["France"], False),
        ("Berlin", ["France", "Germany"], True),
        ("Paris, Texas, United States", ["France"], False),
        ("Remote", ["France"], False),  # sans indice de pays, on n'invente pas
        (None, ["France"], False),
        ("Anywhere", [], True),
        ("Anywhere", [" "], True),  # lieux vides : pas de filtre
    ],
)
def test_location_matches(job_location: str | None, wanted: list[str], expected: bool) -> None:
    assert location_matches(job_location, wanted) is expected


def test_provided_country_wins_over_text() -> None:
    assert location_matches("Springfield", ["France"], country="FR") is True
    assert location_matches("Paris", ["France"], country="US") is False


def job(location: str | None, url: str) -> NormalizedJob:
    return NormalizedJob(
        source_kind="t", url=url, company="Acme", title="Data Engineer", location=location,
        description="SQL",
    )


def test_apply_query_filters_uses_country() -> None:
    jobs = [job("Paris", "https://x/1"), job("Berlin", "https://x/2"), job("Remote", "https://x/3")]
    kept = apply_query_filters(jobs, JobQuery(locations=["France"]))
    assert [j.location for j in kept] == ["Paris"]
