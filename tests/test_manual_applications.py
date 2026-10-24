"""Candidature à la main : formulaires illisibles (connexion, JavaScript), dossier à copier."""

from __future__ import annotations

import pytest

from applyflow.applications.fetcher import FetchedForm, FormFetchError
from applyflow.applications.forms import NoFormFields, analyze_html, manual_kit
from applyflow.applications.preparer import (
    SubmissionNotAllowed,
    approve_attempt,
    list_attempts,
    prepare_attempt,
    record_submission,
)
from applyflow.db.models import Job

# Ce que HelloWork renvoie réellement : des formulaires de connexion, d'alerte, de favori.
LOGIN_ONLY_PAGE = """<html><body>
<form action="/candidat/onetapturbocustom"><input type="hidden" name="auto-submit"></form>
<form action="/candidat/onetapturbo"><input type="hidden" name="clientId"><input type="hidden" name="credential"></form>
<a href="#postuler">Postuler</a></body></html>"""

SEARCH_FIRST_PAGE = """<html><body>
<form action="/search"><input name="q" type="search"></form>
<form action="/apply">
  <label for="n">Full name</label><input id="n" name="name" required>
  <label for="e">Email</label><input id="e" name="email" type="email" required>
  <label for="r">Resume</label><input id="r" name="resume" type="file">
</form></body></html>"""

# Formulaire lisible mais avec une question obligatoire sans réponse validée.
OPEN_QUESTION_PAGE = """<html><body>
<form action="/apply">
  <label for="n">Full name</label><input id="n" name="name" required>
  <label for="e">Email</label><input id="e" name="email" type="email" required>
  <label for="r">Resume</label><input id="r" name="resume" type="file">
  <label for="d">Numéro de permis de conduire</label><input id="d" name="permis" required>
</form></body></html>"""


class FakeFetcher:
    def __init__(self, html: str | None = None, error: str | None = None) -> None:
        self.html, self.error = html, error

    def fetch(self, url: str) -> FetchedForm:
        if self.error:
            raise FormFetchError(self.error)
        return FetchedForm(url=url, html=self.html or "")


class RenderedFetcher(FakeFetcher):
    """Page statique vide, formulaire présent seulement une fois la page rendue."""

    def __init__(self, shell: str, rendered: str) -> None:
        super().__init__(shell)
        self.rendered = rendered

    def render(self, url: str) -> FetchedForm:
        return FetchedForm(url=url, html=self.rendered)


@pytest.fixture()
def job(session) -> Job:
    row = Job(
        source_kind="test", url="https://www.hellowork.com/fr-fr/emplois/1.html", url_key="k1",
        company="Acme", title="AI Engineer", description="Python " * 40, location="Paris",
        fingerprint="fp-manual", raw={},
    )
    session.add(row)
    session.flush()
    return row


def test_page_without_readable_form_is_manual_not_blocked(session, settings, profile, resume, job) -> None:
    attempt = prepare_attempt(session, settings, job, profile, fetcher=FakeFetcher(LOGIN_ONLY_PAGE))
    assert attempt.status == "manual"
    assert attempt.error is None  # ce n'est pas une erreur : la page est lisible, sans formulaire
    assert attempt.plan["blocked_reason"] is None
    assert any("à la main" in warning for warning in attempt.plan["warnings"])
    kit = {item["key"]: item["value"] for item in attempt.plan["manual_kit"]}
    assert kit["email"] == profile.email and kit["full_name"] == profile.full_name


def test_network_failure_stays_blocked_but_keeps_the_kit(session, settings, profile, resume, job) -> None:
    attempt = prepare_attempt(
        session, settings, job, profile, fetcher=FakeFetcher(error="formulaire inaccessible (HTTP 403)")
    )
    assert attempt.status == "blocked" and "403" in attempt.error
    assert attempt.plan["manual_kit"]  # même bloqué, on peut postuler à la main


def test_kit_contains_only_filled_values(profile) -> None:
    profile.phone = None
    profile.github_url = None
    profile.website = "https://portfolio.example"
    profile.other_links = []
    profile.salary_min = 33700
    profile.salary_currency = "EUR"
    profile.work_authorization = "APS : autorisé à travailler en France"
    items = {item.key: item.value for item in manual_kit(profile)}
    assert "phone" not in items and "github" not in items and "other_link" not in items
    assert items["website"] == "https://portfolio.example"
    assert items["salary"] == "33700 EUR brut par an (minimum)"
    assert items["work_authorization"].startswith("APS")


def test_manual_attempt_is_recorded_only_with_explicit_confirmation(
    session, settings, profile, resume, job
) -> None:
    attempt = prepare_attempt(session, settings, job, profile, fetcher=FakeFetcher(LOGIN_ONLY_PAGE))
    with pytest.raises(SubmissionNotAllowed, match="confirmation"):
        record_submission(session, attempt, confirmed=False)
    with pytest.raises(SubmissionNotAllowed):
        approve_attempt(session, attempt)  # la validation ne concerne que les formulaires lus
    application = record_submission(session, attempt, confirmed=True, reference="HW-123")
    assert application.status == "submitted" and application.external_reference == "HW-123"
    assert attempt.status == "submitted"


def test_prepared_attempt_still_needs_approval_before_recording(
    session, settings, profile, resume, job
) -> None:
    attempt = prepare_attempt(session, settings, job, profile, fetcher=FakeFetcher(SEARCH_FIRST_PAGE))
    assert attempt.status == "prepared"
    with pytest.raises(SubmissionNotAllowed, match="validée"):
        record_submission(session, attempt, confirmed=True)  # le parcours de relecture reste la règle


def test_submission_sent_by_hand_is_recorded_even_with_an_open_question(
    session, settings, profile, resume, job
) -> None:
    """Vous avez postulé vous-même malgré une question restée ouverte : le suivi doit démarrer."""
    attempt = prepare_attempt(
        session, settings, job, profile, fetcher=FakeFetcher(OPEN_QUESTION_PAGE)
    )
    assert attempt.status == "needs_review"
    with pytest.raises(SubmissionNotAllowed, match="préparée"):
        approve_attempt(session, attempt)  # la validation reste impossible sans réponse
    application = record_submission(session, attempt, confirmed=True)
    assert application.status == "submitted" and attempt.status == "submitted"


def test_page_rendered_by_a_browser_is_read_instead_of_going_manual(
    session, settings, profile, resume, job
) -> None:
    """Sans le rendu, cette page serait « à postuler à la main » : le formulaire est en JS."""
    shell = '<html><body><div id="app"></div><script src="/app.js"></script></body></html>'
    attempt = prepare_attempt(
        session,
        settings,
        job,
        profile,
        fetcher=RenderedFetcher(shell, SEARCH_FIRST_PAGE),
    )
    assert attempt.status == "prepared"
    assert attempt.error is None
    assert any("navigateur" in warning for warning in attempt.plan["warnings"])
    assert {fill["key"] for fill in attempt.plan["fills"]} >= {"full_name", "email", "resume"}


def test_manual_attempts_appear_in_the_queue(session, settings, profile, resume, job) -> None:
    prepare_attempt(session, settings, job, profile, fetcher=FakeFetcher(LOGIN_ONLY_PAGE))
    assert [a.status for a in list_attempts(session)] == ["manual"]


def test_analysis_raises_a_specific_error_for_pages_without_fields() -> None:
    with pytest.raises(NoFormFields, match="aucun champ"):
        analyze_html(LOGIN_ONLY_PAGE, "https://x.example")


def test_application_form_is_chosen_among_several_forms() -> None:
    """Un formulaire de recherche placé avant celui de candidature ne doit pas le masquer."""
    analysis = analyze_html(SEARCH_FIRST_PAGE, "https://x.example")
    names = {field.name for field in analysis.fields}
    assert {"name", "email", "resume"} <= names and "q" not in names


def test_api_manual_flow_end_to_end(api_client, monkeypatch) -> None:
    """Campagne -> offre sans formulaire lisible -> dossier -> « j'ai postulé » enregistré."""
    from applyflow.applications import preparer
    from applyflow.seed import SAMPLE_CV

    monkeypatch.setattr(preparer, "DemoAndHttpFetcher", lambda settings: FakeFetcher(LOGIN_ONLY_PAGE))
    profile = api_client.post(
        "/profiles",
        json={"name": "Data Engineer", "full_name": "Camille Martin", "email": "camille@example.invalid",
              "phone": "+33 6 00 00 00 00", "city": "Paris", "target_titles": ["Data Engineer"],
              "technical_skills": ["Python", "SQL", "Airflow", "dbt"], "experience_level": "junior",
              "years_experience": 1, "locations": ["France"], "contract_types": ["CDI"],
              "work_authorization": "APS : autorisé à travailler en France"},
    ).json()
    api_client.post(
        f"/profiles/{profile['id']}/resumes",
        files={"file": ("cv.pdf", SAMPLE_CV.read_bytes(), "application/pdf")},
    )
    api_client.post("/jobs/import", json={"jobs": [
        {"url": "https://www.hellowork.com/fr-fr/emplois/9.html", "company": "Acme",
         "title": "Data Engineer junior", "location": "Paris, France", "description": "Python SQL Airflow dbt " * 12}
    ]})
    campaign = api_client.post(
        "/campaigns",
        json={"name": "Manuel", "sources": [{"kind": "library"}], "profile_ids": [profile["id"]], "min_score": 0},
    ).json()
    summary = api_client.post(f"/campaigns/{campaign['id']}/run", json={}).json()["steps"]["prepare"]
    assert summary["manual"] == 1 and summary["blocked"] == 0 and summary["remaining"] == 0

    queue = api_client.get("/queue").json()
    assert [item["status"] for item in queue] == ["manual"]
    kit = {item["key"]: item["value"] for item in queue[0]["plan"]["manual_kit"]}
    assert kit["email"] == "camille@example.invalid"
    assert kit["work_authorization"] == "APS : autorisé à travailler en France"

    refused = api_client.post(f"/queue/{queue[0]['id']}/submit", json={"confirmed": False})
    assert refused.status_code == 409
    done = api_client.post(f"/queue/{queue[0]['id']}/submit", json={"confirmed": True, "reference": "HW-9"})
    assert done.status_code == 200 and done.json()["status"] == "submitted"
    results = api_client.get(f"/campaigns/{campaign['id']}/results").json()
    assert results[0]["stage"] == "submitted"  # la campagne suit l'état de la candidature


def test_campaign_summaries_report_what_the_limit_left_aside(api_client) -> None:
    profile = api_client.post(
        "/profiles",
        json={"name": "Profil test", "target_titles": ["Data Engineer"], "technical_skills": ["Python"],
              "locations": ["France"]},
    ).json()
    api_client.post("/jobs/import", json={"jobs": [
        {"url": f"https://exemple.test/{i}", "company": f"Co{i}", "title": "Data Engineer",
         "location": "Paris", "description": "Python " * 40} for i in range(5)
    ]})
    cid = api_client.post(
        "/campaigns", json={"name": "Limite", "sources": [{"kind": "library"}], "profile_ids": [profile["id"]]}
    ).json()["id"]
    api_client.post(f"/campaigns/{cid}/run", json={"steps": ["discover"]})
    first = api_client.post(f"/campaigns/{cid}/run", json={"steps": ["analyze"], "max_items": 2}).json()
    assert first["steps"]["analyze"]["remaining"] == 3  # trois offres attendent encore
    rest = api_client.post(f"/campaigns/{cid}/run", json={"steps": ["analyze"]}).json()
    assert rest["steps"]["analyze"]["remaining"] == 0


def test_lowering_the_minimum_score_recovers_the_offers_it_had_discarded(api_client, monkeypatch) -> None:
    """Le seuil n'est pas figé : abaissé, il récupère les offres écartées pour cette seule raison."""
    from applyflow.applications import preparer
    from applyflow.seed import SAMPLE_CV

    monkeypatch.setattr(preparer, "DemoAndHttpFetcher", lambda settings: FakeFetcher(LOGIN_ONLY_PAGE))
    profile = api_client.post(
        "/profiles",
        json={"name": "Profil seuil", "target_titles": ["Data Engineer"], "technical_skills": ["Python", "SQL"],
              "experience_level": "junior", "years_experience": 1, "locations": ["France"]},
    ).json()
    api_client.post(
        f"/profiles/{profile['id']}/resumes",
        files={"file": ("cv.pdf", SAMPLE_CV.read_bytes(), "application/pdf")},
    )
    api_client.post("/jobs/import", json={"jobs": [
        {"url": f"https://exemple.test/s{i}", "company": f"Seuil{i}", "title": "Data Engineer junior",
         "location": "Paris", "description": "Python SQL " * 30} for i in range(3)
    ]})
    cid = api_client.post(
        "/campaigns",
        json={"name": "Seuil", "sources": [{"kind": "library"}], "profile_ids": [profile["id"]], "min_score": 100},
    ).json()["id"]
    api_client.post(f"/campaigns/{cid}/run", json={"steps": ["discover", "analyze"]})

    strict = api_client.post(f"/campaigns/{cid}/run", json={"steps": ["prepare"]}).json()["steps"]["prepare"]
    assert strict["skipped"] == 3 and strict["manual"] == 0  # tout est sous 100
    stages = {r["stage"] for r in api_client.get(f"/campaigns/{cid}/results").json()}
    assert stages == {"rejected"}

    again = api_client.post(f"/campaigns/{cid}/run", json={"steps": ["prepare"]}).json()["steps"]["prepare"]
    assert again["skipped"] == 0  # les offres déjà écartées ne sont pas recomptées à chaque essai

    relaxed = api_client.post(
        f"/campaigns/{cid}/run", json={"steps": ["prepare"], "min_score": 0}
    ).json()["steps"]["prepare"]
    assert relaxed["manual"] == 3 and relaxed["skipped"] == 0  # récupérées, sans ré-analyse
    rows = api_client.get(f"/campaigns/{cid}/results").json()
    assert {r["stage"] for r in rows} == {"manual"}
    assert all(not any(x.get("code") == "min_score" for x in (r["reasons"] or [])) for r in rows)
    assert api_client.get(f"/campaigns/{cid}").json()["min_score"] == 0


def test_offers_rejected_by_a_criterion_do_not_come_back_with_the_threshold(api_client) -> None:
    profile = api_client.post(
        "/profiles",
        json={"name": "Profil stage", "target_titles": ["Data Engineer"], "technical_skills": ["Python"],
              "locations": ["France"], "contract_types": ["CDI"]},
    ).json()
    api_client.post("/jobs/import", json={"jobs": [
        {"url": "https://exemple.test/stage", "company": "Stagiaire", "title": "Stage Data Engineer",
         "location": "Paris", "contract_type": "Stage", "description": "Python " * 40}
    ]})
    cid = api_client.post(
        "/campaigns",
        json={"name": "Critere", "sources": [{"kind": "library"}], "profile_ids": [profile["id"]], "min_score": 0},
    ).json()["id"]
    api_client.post(f"/campaigns/{cid}/run", json={"steps": ["discover", "analyze"]})
    rows = api_client.get(f"/campaigns/{cid}/results").json()
    assert rows[0]["stage"] == "rejected" and rows[0]["eligible"] is False
    done = api_client.post(f"/campaigns/{cid}/run", json={"steps": ["prepare"], "min_score": 0}).json()
    assert done["steps"]["prepare"]["manual"] == 0 and done["steps"]["prepare"]["prepared"] == 0
    assert api_client.get(f"/campaigns/{cid}/results").json()[0]["stage"] == "rejected"


# Structure réelle de la page d'une offre HelloWork : connexion, favori et création d'alerte e-mail.
HELLOWORK_PAGE = """<html><body>
<form action="/fr-fr/candidat/onetapturbocustom"><input type="hidden" name="auto-submit"></form>
<form action="/fr-fr/candidat/onetapturbo">
  <input type="hidden" name="clientId"><input type="hidden" name="credential"><input type="hidden" name="selectBy">
</form>
<form action="/fr-fr/candidat/tooglebookmark"><input type="hidden" name="idOffre"></form>
<form action="/fr-fr/alerte/create">
  <input name="Job.DisplayLabel" placeholder="Métier, mot-clé"><input name="Location.Uri" placeholder="Ville">
  <input name="OtpData.Email" type="email" placeholder="Votre e-mail">
  <input type="checkbox" name="Contracts" value="CDI"><input type="checkbox" name="Contracts" value="CDD">
</form></body></html>"""


@pytest.mark.parametrize(
    "html",
    [
        HELLOWORK_PAGE,  # l'alerte e-mail n'est pas la candidature, même avec un champ e-mail
        "<form action='/login'><input name='email' type='email'><input name='pwd' type='password'></form>",
        "<form action='/newsletter'><input name='email' type='email' placeholder='Votre e-mail'></form>",
        "<form action='/search'><input name='q' type='search'><input name='where'></form>",
        "<form><input name='email' type='email'></form>",  # un e-mail seul : ni nom, ni CV
        "<html><body><p>Aucun formulaire ici</p></body></html>",
    ],
)
def test_forms_that_are_not_an_application_are_never_filled(html: str) -> None:
    with pytest.raises(NoFormFields):
        analyze_html(html, "https://x.example")


@pytest.mark.parametrize(
    "html",
    [
        # Champ CV : suffit à reconnaître une candidature.
        "<form><input name='q1' placeholder='Votre nom'><input type='file' name='cv'></form>",
        # Prénom, nom, e-mail : un formulaire de candidature sans champ fichier.
        "<form action='/postuler'><label for='a'>Prénom</label><input id='a' name='f1'>"
        "<label for='b'>Nom</label><input id='b' name='f2'>"
        "<label for='c'>E-mail</label><input id='c' name='f3' type='email'></form>",
        # Champs désignés seulement par leur étiquette (noms techniques opaques).
        "<form><label for='x'>Email</label><input id='x' name='field_88' type='email'>"
        "<label for='y'>Full name</label><input id='y' name='field_89'></form>",
    ],
)
def test_real_application_forms_are_still_recognised(html: str) -> None:
    assert analyze_html(html, "https://x.example").fields


def test_hellowork_style_page_becomes_a_manual_application(session, settings, profile, resume, job) -> None:
    attempt = prepare_attempt(session, settings, job, profile, fetcher=FakeFetcher(HELLOWORK_PAGE))
    assert attempt.status == "manual"  # et non « à compléter » avec les champs d'une alerte
    assert not attempt.plan["fills"]
    assert attempt.plan["manual_kit"]


def test_reprepare_from_the_queue_updates_the_campaign_row(api_client, monkeypatch) -> None:
    """Re-préparer depuis la file doit aussi corriger l'état affiché dans la campagne."""
    from applyflow.applications import preparer
    from applyflow.seed import SAMPLE_CV

    profile = api_client.post(
        "/profiles",
        json={"name": "Profil sync", "target_titles": ["Data Engineer"], "technical_skills": ["Python", "SQL"],
              "experience_level": "junior", "years_experience": 1, "locations": ["France"]},
    ).json()
    api_client.post(
        f"/profiles/{profile['id']}/resumes",
        files={"file": ("cv.pdf", SAMPLE_CV.read_bytes(), "application/pdf")},
    )
    api_client.post("/jobs/import", json={"jobs": [
        {"url": "https://exemple.test/sync", "company": "Sync", "title": "Data Engineer junior",
         "location": "Paris", "description": "Python SQL " * 30}
    ]})
    cid = api_client.post(
        "/campaigns",
        json={"name": "Sync", "sources": [{"kind": "library"}], "profile_ids": [profile["id"]], "min_score": 0},
    ).json()["id"]
    monkeypatch.setattr(preparer, "DemoAndHttpFetcher", lambda settings: FakeFetcher(error="HTTP 403"))
    api_client.post(f"/campaigns/{cid}/run", json={})
    assert api_client.get(f"/campaigns/{cid}/results").json()[0]["stage"] == "blocked"

    monkeypatch.setattr(preparer, "DemoAndHttpFetcher", lambda settings: FakeFetcher(LOGIN_ONLY_PAGE))
    attempt = api_client.get("/queue").json()[0]
    assert api_client.post(f"/queue/{attempt['id']}/prepare").json()["status"] == "manual"
    assert api_client.get(f"/campaigns/{cid}/results").json()[0]["stage"] == "manual"
