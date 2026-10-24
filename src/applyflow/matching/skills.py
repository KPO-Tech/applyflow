"""Vocabulaire de compétences : alias, extraction et recouvrement."""

from __future__ import annotations

import re

from applyflow.text import normalize_text

# Alias -> libellé canonique. Volontairement explicite et extensible.
SKILL_ALIASES: dict[str, str] = {
    "python": "python",
    "pyspark": "spark",
    "apache spark": "spark",
    "spark": "spark",
    "sql": "sql",
    "postgres": "postgresql",
    "postgresql": "postgresql",
    "mysql": "mysql",
    "sqlite": "sqlite",
    "snowflake": "snowflake",
    "bigquery": "bigquery",
    "big query": "bigquery",
    "redshift": "redshift",
    "databricks": "databricks",
    "kafka": "kafka",
    "apache kafka": "kafka",
    "airflow": "airflow",
    "apache airflow": "airflow",
    "dbt": "dbt",
    "dagster": "dagster",
    "fivetran": "fivetran",
    "etl": "etl",
    "elt": "elt",
    "data warehouse": "data warehouse",
    "data warehousing": "data warehouse",
    "data lake": "data lake",
    "data pipeline": "data pipelines",
    "data pipelines": "data pipelines",
    "aws": "aws",
    "amazon web services": "aws",
    "gcp": "gcp",
    "google cloud": "gcp",
    "azure": "azure",
    "docker": "docker",
    "kubernetes": "kubernetes",
    "k8s": "kubernetes",
    "terraform": "terraform",
    "git": "git",
    "linux": "linux",
    "java": "java",
    "scala": "scala",
    "pandas": "pandas",
    "numpy": "numpy",
    "scikit-learn": "scikit-learn",
    "sklearn": "scikit-learn",
    "tensorflow": "tensorflow",
    "pytorch": "pytorch",
    "torch": "pytorch",
    "mlflow": "mlflow",
    "llm": "llm",
    "llms": "llm",
    "large language models": "llm",
    "nlp": "nlp",
    "natural language processing": "nlp",
    "computer vision": "computer vision",
    "power bi": "power bi",
    "powerbi": "power bi",
    "tableau": "tableau",
    "looker": "looker",
    "excel": "excel",
    "google analytics": "google analytics",
    "a/b testing": "a/b testing",
    "ab testing": "a/b testing",
    "statistics": "statistics",
    "statistiques": "statistics",
    "machine learning": "machine learning",
    "deep learning": "deep learning",
    "data modeling": "data modeling",
    "data modelling": "data modeling",
    "data quality": "data quality",
    "data governance": "data governance",
    "javascript": "javascript",
    "typescript": "typescript",
    "react": "react",
    "fastapi": "fastapi",
    "django": "django",
    "flask": "flask",
    "rest api": "rest api",
    "rest apis": "rest api",
    "graphql": "graphql",
    "ci/cd": "ci/cd",
    "github actions": "github actions",
    "jenkins": "jenkins",
    "microservices": "microservices",
    "unit testing": "unit testing",
    "pytest": "pytest",
    "agile": "agile",
    "scrum": "scrum",
    "jira": "jira",
    "sap": "sap",
    "salesforce": "salesforce",
    "hubspot": "hubspot",
    "finance": "finance",
    "healthcare": "healthcare",
    "retail": "retail",
    "ecommerce": "ecommerce",
    "e-commerce": "ecommerce",
    "marketing": "marketing",
    "fraud": "fraud",
    "supply chain": "supply chain",
    "logistics": "logistics",
    "saas": "saas",
    "b2b": "b2b",
    "consulting": "consulting",
    "reporting": "reporting",
    "dashboards": "dashboards",
    "dashboard": "dashboards",
    "visualization": "visualization",
    "visualisation": "visualization",
    "forecasting": "forecasting",
    "experimentation": "experimentation",
    "product analytics": "product analytics",
    "crm": "crm",
}

_ALIAS_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(rf"(?<![a-z0-9]){re.escape(alias)}(?![a-z0-9])"), canonical)
    for alias, canonical in sorted(SKILL_ALIASES.items(), key=lambda item: len(item[0]), reverse=True)
]


def canonicalize_skill(value: str) -> str:
    normalized = normalize_text(value)
    return SKILL_ALIASES.get(normalized, normalized)


def canonicalize_skills(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        canonical = canonicalize_skill(value)
        if canonical and canonical not in seen:
            seen.add(canonical)
            result.append(canonical)
    return result


def extract_skills(text: str) -> list[str]:
    """Extrait les compétences connues présentes dans un texte."""
    normalized = normalize_text(text)
    found: list[str] = []
    seen: set[str] = set()
    for pattern, canonical in _ALIAS_PATTERNS:
        if canonical in seen:
            continue
        if pattern.search(normalized):
            seen.add(canonical)
            found.append(canonical)
    return found


def skill_overlap(profile_skills: list[str], job_skills: list[str]) -> tuple[float, list[str], list[str]]:
    """Retourne (ratio de couverture des compétences du poste, matches, manquantes)."""
    profile = set(canonicalize_skills(profile_skills))
    job = set(canonicalize_skills(job_skills))
    if not job:
        return 0.0, [], []
    matched = sorted(job & profile)
    missing = sorted(job - profile)
    return len(matched) / len(job), matched, missing
