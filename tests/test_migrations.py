from __future__ import annotations

from sqlalchemy import inspect

EXPECTED_TABLES = {
    "users",
    "profiles",
    "resumes",
    "jobs",
    "job_sources",
    "campaigns",
    "campaign_jobs",
    "routing_decisions",
    "application_attempts",
    "applications",
    "application_answers",
    "audit_events",
    "email_messages",
    "alembic_version",
}


def test_migrations_create_all_tables(database) -> None:
    tables = set(inspect(database.engine).get_table_names())
    assert tables >= EXPECTED_TABLES
    database.init_schema()  # idempotent
    assert set(inspect(database.engine).get_table_names()) >= EXPECTED_TABLES


def test_unique_constraints_exist(database) -> None:
    inspector = inspect(database.engine)
    job_uniques = inspector.get_unique_constraints("jobs")
    assert any("fingerprint" in constraint["column_names"] for constraint in job_uniques)
    application_uniques = inspector.get_unique_constraints("applications")
    assert any("job_id" in constraint["column_names"] for constraint in application_uniques)
