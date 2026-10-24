from __future__ import annotations

from applyflow.applications.answers import (
    approved_answers,
    find_answer,
    list_answers,
    normalize_question,
    upsert_answer,
)


def test_normalize_question() -> None:
    assert normalize_question("What is your notice period?") == "what-is-your-notice-period"
    assert normalize_question("Earliest start date") == "earliest-start-date"


def test_answers_are_upserted_and_approved(session) -> None:
    answer = upsert_answer(
        session, question_text="What is your notice period?", answer="1 month", approved=True
    )
    updated = upsert_answer(
        session, question_text="what is your notice period", answer="2 months", approved=True
    )
    assert answer.id == updated.id
    assert updated.answer == "2 months"
    assert len(list_answers(session)) == 1


def test_only_approved_answers_are_available(session) -> None:
    upsert_answer(session, question_text="Question A", answer="Oui", approved=False)
    upsert_answer(session, question_text="Question B", answer="Non", approved=True)
    approved = approved_answers(session)
    assert "question-a" not in approved
    assert "question-b" in approved


def test_find_answer_exact_and_fuzzy(session) -> None:
    upsert_answer(session, question_text="What is your notice period?", answer="1 month")
    answers = approved_answers(session)
    assert find_answer(answers, "What is your notice period?") is not None
    assert find_answer(answers, "notice period") is not None
    assert find_answer(answers, "Do you require a visa?") is None


def test_empty_answer_rejected(session) -> None:
    import pytest

    with pytest.raises(ValueError):
        upsert_answer(session, question_text="Question", answer="   ")
