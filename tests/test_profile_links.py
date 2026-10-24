"""Portfolio et liens supplémentaires du profil (« + Ajouter un site »)."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from pydantic import ValidationError

from applyflow.applications.forms import analyze_html, build_plan
from applyflow.profiles.schemas import MAX_OTHER_LINKS, ProfileInput, normalize_url

BASE = {"name": "Data Engineer", "target_titles": ["Data Engineer"]}


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("kpoviessi-stephane.vercel.app", "https://kpoviessi-stephane.vercel.app"),
        ("  seshat-ai.com  ", "https://seshat-ai.com"),
        ("https://seshat-ai.com/", "https://seshat-ai.com/"),
        ("http://exemple.fr/portfolio?x=1", "http://exemple.fr/portfolio?x=1"),
        ("monsite.fr:8080", "https://monsite.fr:8080"),
        ("", None),
        ("   ", None),
        (None, None),
    ],
)
def test_urls_are_completed_and_cleaned(raw: str | None, expected: str | None) -> None:
    assert normalize_url(raw) == expected


@pytest.mark.parametrize(
    "dangerous",
    ["javascript:alert(1)", "data:text/html,<script>1</script>", "file:///c:/secret",
     "mailto:a@b.fr", "ftp://exemple.fr", "pas un site", "localhost"],
)
def test_dangerous_or_invalid_links_are_refused(dangerous: str) -> None:
    """Ces adresses sont écrites dans des formulaires et affichées dans l'interface."""
    with pytest.raises(ValueError):
        normalize_url(dangerous)
    with pytest.raises(ValidationError):
        ProfileInput(**BASE, website=dangerous)
    with pytest.raises(ValidationError):
        ProfileInput(**BASE, other_links=[{"label": "x", "url": dangerous}])


def test_profile_accepts_portfolio_and_extra_links() -> None:
    profile = ProfileInput(
        **BASE,
        website="kpoviessi-stephane.vercel.app",
        linkedin_url="linkedin.com/in/exemple",
        other_links=[
            {"label": " Seshat AI ", "url": "seshat-ai.com"},
            {"label": "doublon", "url": "https://seshat-ai.com/"},  # même site : un seul conservé
            {"label": "", "url": "https://exemple.fr/projet"},
        ],
    )
    assert profile.website == "https://kpoviessi-stephane.vercel.app"
    assert profile.linkedin_url == "https://linkedin.com/in/exemple"
    assert [(link.label, link.url) for link in profile.other_links] == [
        ("Seshat AI", "https://seshat-ai.com"),
        ("", "https://exemple.fr/projet"),
    ]


def test_link_count_is_limited() -> None:
    links = [{"label": str(i), "url": f"https://site{i}.example"} for i in range(MAX_OTHER_LINKS + 1)]
    with pytest.raises(ValidationError):
        ProfileInput(**BASE, other_links=links)


def test_links_round_trip_through_the_api(api_client) -> None:
    payload = {**BASE, "website": "kpoviessi-stephane.vercel.app",
               "other_links": [{"label": "Seshat AI", "url": "seshat-ai.com"}]}
    created = api_client.post("/profiles", json=payload)
    assert created.status_code in (200, 201), created.text
    body = created.json()
    assert body["website"] == "https://kpoviessi-stephane.vercel.app"
    assert body["other_links"] == [{"label": "Seshat AI", "url": "https://seshat-ai.com"}]

    payload["other_links"] = []  # retirer tous les liens
    updated = api_client.put(f"/profiles/{body['id']}", json=payload).json()
    assert updated["other_links"] == [] and updated["website"] == body["website"]

    refused = api_client.post("/profiles", json={**BASE, "other_links": [{"url": "javascript:alert(1)"}]})
    assert refused.status_code in (400, 422)


def _legacy_row(connection: sqlite3.Connection, table: str, **values: object) -> None:
    """Insère une ligne dans l'ancien schéma en remplissant les colonnes obligatoires."""
    row: dict[str, object] = dict(values)
    for _, name, kind, notnull, default, _pk in connection.execute(f"pragma table_info({table})"):
        if name in row or not notnull or default is not None:
            continue
        kind = kind.upper()
        row[name] = (
            0 if ("INT" in kind or "BOOL" in kind or "FLOAT" in kind)
            else "[]" if "JSON" in kind
            else "2026-01-01 00:00:00" if "DATE" in kind
            else "x"
        )
    columns = ", ".join(row)
    marks = ", ".join("?" for _ in row)
    connection.execute(f"INSERT INTO {table} ({columns}) VALUES ({marks})", list(row.values()))


def test_existing_database_keeps_its_profiles_and_gets_the_new_column(tmp_path: Path) -> None:
    """Une base créée avant cette fonction est migrée sans perdre ses profils."""
    from alembic import command
    from alembic.config import Config

    from applyflow.db.base import MIGRATIONS_DIR

    path = tmp_path / "old.db"
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS_DIR))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{path}")

    command.upgrade(config, "b7d41e5c9a20")  # schéma d'avant les liens supplémentaires
    connection = sqlite3.connect(path)
    assert "other_links" not in {row[1] for row in connection.execute("pragma table_info(profiles)")}
    _legacy_row(connection, "users", id="u1")
    _legacy_row(connection, "profiles", id="p1", user_id="u1", name="Profil existant",
                website="https://ancien-site.fr")
    connection.commit()
    connection.close()

    command.upgrade(config, "head")
    connection = sqlite3.connect(path)
    assert "other_links" in {row[1] for row in connection.execute("pragma table_info(profiles)")}
    name, website, links = connection.execute(
        "SELECT name, website, other_links FROM profiles WHERE id = 'p1'"
    ).fetchone()
    assert (name, website, links) == ("Profil existant", "https://ancien-site.fr", "[]")
    connection.close()


FORM = """<form>
  <label for="a">Full name</label><input id="a" name="full_name" type="text" required>
  <label for="b">Email</label><input id="b" name="email" type="email" required>
  <label for="c">Portfolio</label><input id="c" name="portfolio" type="url">
  <label for="d">%s</label><input id="d" name="extra" type="url">
</form>"""


@pytest.mark.parametrize("label", ["Other website", "Autre lien", "Additional link"])
def test_forms_are_prefilled_with_portfolio_and_extra_link(profile, session, label: str) -> None:
    profile.website = "https://kpoviessi-stephane.vercel.app"
    profile.other_links = [{"label": "Seshat AI", "url": "https://seshat-ai.com"},
                           {"label": "Autre", "url": "https://exemple.fr"}]
    plan = build_plan(
        analyze_html(FORM % label, "demo://liens"), profile=profile, resume=None, answers={}
    )
    values = {fill.key: fill.value for fill in plan.fills}
    assert values["website"] == "https://kpoviessi-stephane.vercel.app"  # champ « Portfolio »
    assert values["other_link"] == "https://seshat-ai.com"  # le premier lien supplémentaire
    assert "https://exemple.fr" not in values.values()


def test_missing_links_are_not_invented(profile, session) -> None:
    profile.website = None
    profile.other_links = []
    plan = build_plan(
        analyze_html(FORM % "Other website", "demo://liens"), profile=profile, resume=None, answers={}
    )
    filled = {fill.value for fill in plan.fills}
    assert not any(value and "http" in str(value) for value in filled)
