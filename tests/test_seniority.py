from __future__ import annotations

from applyflow.matching.seniority import assess_seniority, extract_years


def test_title_level_wins_over_description_context() -> None:
    assessment = assess_seniority(
        "Senior Data Engineer",
        "Vous collaborerez avec des équipes senior et des stakeholders senior.",
    )
    assert assessment.level == "senior"
    assert assessment.title_level == "senior"


def test_senior_in_description_is_not_a_level() -> None:
    assessment = assess_seniority(
        "Data Analyst",
        "Vous travaillerez avec des stakeholders senior et la direction. "
        "Aucune expérience préalable exigée.",
    )
    assert assessment.level == "unknown"


def test_explicit_senior_level_in_description() -> None:
    assert assess_seniority("Data Engineer", "This is a senior-level role.").level == "senior"


def test_entry_and_graduate_titles() -> None:
    assert assess_seniority("Graduate Data Engineer").level == "entry"
    assert assess_seniority("Data Analyst — Entry Level").level == "entry"
    assert assess_seniority("Junior Data Engineer").level == "junior"
    assert assess_seniority("Stage — Data Analyst").level == "intern"


def test_lead_and_principal_are_excluded_levels() -> None:
    assert assess_seniority("Lead Data Analyst").level == "lead"
    assert assess_seniority("Staff Data Scientist").level == "principal"
    assert assess_seniority("Head of Data").level == "director"


def test_hard_versus_preferred_years() -> None:
    required, preferred = extract_years("3+ years of experience required. SQL and Python.")
    assert required is not None
    assert required.years == 3
    assert required.hard is True
    assert preferred is None

    required, preferred = extract_years(
        "Three years of experience preferred, but juniors are welcome."
    )
    assert required is None
    assert preferred is None  # « Three » en lettres n'est pas interprété comme une exigence

    required, preferred = extract_years("3 years of experience preferred.")
    assert required is None
    assert preferred is not None
    assert preferred.years == 3
    assert preferred.hard is False


def test_years_range_uses_lower_bound() -> None:
    required, _ = extract_years("3-5 years of experience required.")
    assert required is not None
    assert required.years == 3


def test_zero_to_two_years_is_not_a_hard_requirement() -> None:
    required, preferred = extract_years("0-2 years of experience.")
    assert required is None
    assert preferred is not None
    assert preferred.years == 2


def test_contract_internship_implies_intern() -> None:
    assert assess_seniority("Data Analyst", "Analyse de données.", "internship").level == "intern"
