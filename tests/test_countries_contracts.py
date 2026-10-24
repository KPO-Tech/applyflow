"""Liste officielle des pays, types de contrat multiples, recherche dans plusieurs pays."""

from __future__ import annotations

from typing import Any

import httpx
import pandas as pd
import pytest

from applyflow.contracts import CONTRACT_TYPES, contract_matches, normalize_contract
from applyflow.geo import all_countries, country_catalog, detect_country, normalize_country
from applyflow.providers.adzuna import AdzunaProvider
from applyflow.providers.jobspy_provider import JobSpyProvider, jobspy_country, site_covers
from applyflow.schemas import JobQuery
from applyflow.text import normalize_text

# ---------------------------------------------------------------- liste officielle


def test_official_list_has_every_iso_country() -> None:
    countries = all_countries()
    assert len(countries) == 249  # ISO 3166-1
    assert len({c.code for c in countries}) == 249
    assert all(c.name and c.name_fr for c in countries)
    keys = [normalize_text(c.name_fr) for c in countries]
    assert keys == sorted(keys)  # triée par nom français, sans tenir compte des accents


@pytest.mark.parametrize(
    ("typed", "code"),
    [
        ("Allemagne", "DE"), ("germany", "DE"), ("Deutschland", "DE"), ("de", "DE"),
        ("États-Unis", "US"), ("etats-unis", "US"), ("USA", "US"), ("United States", "US"),
        ("Royaume-Uni", "GB"), ("UK", "GB"), ("Corée du Sud", "KR"), ("South Korea", "KR"),
        ("Russie", "RU"), ("Côte d'Ivoire", "CI"), ("cote d ivoire", "CI"), ("Tchéquie", "CZ"),
        ("Japon", "JP"), ("Brésil", "BR"), ("Sénégal", "SN"), ("Maroc", "MA"), ("Canada", "CA"),
    ],
)
def test_any_official_spelling_is_recognised(typed: str, code: str) -> None:
    assert normalize_country(typed) == code


@pytest.mark.parametrize("not_a_country", ["Atlantide", "Paris", "Berlin", "Remote", "", "xx", "Europe"])
def test_unknown_names_and_cities_are_not_countries(not_a_country: str) -> None:
    assert normalize_country(not_a_country) is None


@pytest.mark.parametrize(
    ("location", "code"),
    [
        ("Boston, MA", "US"),  # Massachusetts, pas le Maroc
        ("Atlanta, Georgia", "US"),
        ("Tbilisi, Georgia", "GE"),
        ("Paris, Texas", "US"),
        ("Paris, FR", "FR"),
        ("Berlin, DE", "DE"),  # DE = Delaware ou Allemagne : la ville tranche
        ("Toronto, Ontario", "CA"),
        ("Tokyo, Japon", "JP"),
        ("Nairobi, Kenya", "KE"),
        ("Lagos, Nigeria", "NG"),
        ("Moscou, Russie", "RU"),
        ("Remote", None),
    ],
)
def test_location_country_detection_with_the_full_list(location: str, code: str | None) -> None:
    assert detect_country(location) == code


def test_catalog_serves_autocomplete_data(api_client) -> None:
    response = api_client.get("/countries")
    assert response.status_code == 200
    catalog = response.json()
    assert len(catalog) == 249 and catalog == country_catalog()
    france = next(entry for entry in catalog if entry["code"] == "FR")
    assert france["name"] == "France" and france["name_fr"] == "France"
    germany = next(entry for entry in catalog if entry["code"] == "DE")
    assert (germany["name"], germany["name_fr"]) == ("Germany", "Allemagne")
    assert "deutschland" in germany["aliases"]  # écriture locale acceptée à la saisie


# ---------------------------------------------------------------- contrats


def test_every_contract_type_has_a_label_and_matches_itself() -> None:
    assert len(CONTRACT_TYPES) == 8
    for key, label in CONTRACT_TYPES:
        assert normalize_contract(label) == key, label


@pytest.mark.parametrize(
    ("job_label", "accepted", "expected"),
    [
        ("CDI", ["CDI", "CDD"], True),
        ("CDD", ["CDI", "CDD"], True),
        ("Stage", ["CDI", "CDD"], False),
        ("Stage", ["Stage", "Alternance"], True),
        ("Alternance", ["Stage", "Alternance"], True),
        ("Temps partiel", ["CDI"], False),  # libellé produit par les connecteurs
        ("Temps partiel", ["CDI", "Temps partiel"], True),
        ("Intérim", ["Intérim"], True),
        ("CDD / contrat", ["CDD"], True),  # libellé générique des connecteurs
        ("CDD / contrat", ["Freelance"], True),
        ("CDD / contrat", ["CDI"], False),
        ("full-time", ["CDI"], True),
        ("VIE", ["VIE"], True),
    ],
)
def test_contract_matching_with_several_accepted_types(
    job_label: str, accepted: list[str], expected: bool
) -> None:
    result = contract_matches(
        normalize_contract(job_label), {normalize_contract(item) for item in accepted}
    )
    assert result is expected


def test_contracts_endpoint(api_client) -> None:
    contracts = api_client.get("/contracts").json()
    assert [item["label"] for item in contracts][:3] == ["CDI", "CDD", "Stage"]
    assert all(item["key"] for item in contracts)


def test_profile_keeps_several_contract_types(api_client) -> None:
    created = api_client.post(
        "/profiles",
        json={"name": "Multi", "target_titles": ["Data"], "contract_types": ["CDI", "CDD", "Stage"],
              "locations": ["France", "Germany", "Lyon"]},
    ).json()
    assert created["contract_types"] == ["CDI", "CDD", "Stage"]
    assert created["locations"] == ["France", "Germany", "Lyon"]


# ---------------------------------------------------------------- JobSpy : un pays par lieu


def frame(site: str) -> pd.DataFrame:
    result = pd.DataFrame([{
        "id": f"{site}-1", "job_url": f"https://{site}.example/1", "title": "Data", "company": "Acme",
        "location": "Somewhere", "description": "SQL " * 40,
    }])
    result.attrs = {"errors": {}}
    return result


def test_jobspy_country_mapping() -> None:
    pytest.importorskip("jobspy")
    assert jobspy_country("DE") == "germany"
    assert jobspy_country("FR") == "france"
    assert jobspy_country("GB") == "uk"
    assert jobspy_country("US") == "usa"
    assert jobspy_country("KE") is None  # non géré par JobSpy
    assert site_covers("hellowork", "FR") and not site_covers("hellowork", "DE")
    assert site_covers("indeed", "DE") and site_covers("linkedin", "DE")


def test_jobspy_searches_each_country_with_its_own_domain() -> None:
    pytest.importorskip("jobspy")
    calls: list[dict[str, Any]] = []

    def scrape(**kwargs: Any) -> pd.DataFrame:
        calls.append(kwargs)
        return frame(kwargs["site_name"][0])

    provider = JobSpyProvider(
        sites=["indeed", "hellowork", "linkedin"], scrape=scrape, sleep=lambda _: None,
        country="france", max_per_site=30,
    )
    provider.fetch(JobQuery(keywords=["data"], locations=["France", "Germany", "Canada"], limit=90))
    by_call = {(c["site_name"][0], c["location"]): c["country_indeed"] for c in calls}
    assert by_call[("indeed", "France")] == "france"
    assert by_call[("indeed", "Germany")] == "germany"
    assert by_call[("indeed", "Canada")] == "canada"
    assert ("hellowork", "France") in by_call  # HelloWork : France seulement
    assert ("hellowork", "Germany") not in by_call and ("hellowork", "Canada") not in by_call
    assert ("linkedin", "Germany") in by_call
    assert any("ne couvre pas" in error for error in provider.last_stats["hellowork"]["errors"])


# ---------------------------------------------------------------- Adzuna : un pays par recherche


def adzuna_item(i: int, country: str) -> dict[str, Any]:
    return {"id": f"{country}{i}", "redirect_url": f"https://adzuna.example/{country}/{i}",
            "title": "Data Engineer", "company": {"display_name": f"Acme{i}"},
            "location": {"display_name": "Ville"}, "description": "SQL " * 30, "created": "2026-10-20T10:00:00Z"}


def test_adzuna_searches_every_covered_country() -> None:
    seen: list[tuple[str, dict[str, str]]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        country = request.url.path.split("/")[-3]
        seen.append((country, dict(request.url.params)))
        return httpx.Response(200, json={"count": 1, "results": [adzuna_item(len(seen), country)]})

    provider = AdzunaProvider(
        app_id="id", app_key="key", transport=httpx.MockTransport(handler), max_pages=1
    )
    jobs = provider.fetch(
        JobQuery(keywords=["data"], locations=["France", "Germany", "Japan", "Lyon"], limit=40)
    )
    countries = [country for country, _ in seen]
    assert sorted(countries) == ["de", "fr", "fr"]  # France, Allemagne, et Lyon (en France)
    assert "where" not in dict(seen[0][1]) and dict(seen[2][1]).get("where") == "Lyon"
    assert len(jobs) == 3 and {job.country for job in jobs} == {"FR", "DE"}
    assert {job.salary_currency for job in jobs} == {"EUR"}
    assert set(provider.last_stats) == {"FR", "DE", "FR · Lyon"}  # le Japon n'est pas couvert


def test_adzuna_refuses_when_no_requested_country_is_covered() -> None:
    from applyflow.providers.base import ProviderError

    provider = AdzunaProvider(app_id="id", app_key="key", transport=httpx.MockTransport(
        lambda request: httpx.Response(200, json={"results": []})))
    with pytest.raises(ProviderError, match="ne couvre aucun"):
        provider.fetch(JobQuery(keywords=["data"], locations=["Japan"]))
