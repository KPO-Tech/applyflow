"""Mesure locale : collecte et analyse de 1 000 offres synthétiques.

Usage : uv run python scripts/benchmark_1000.py
Aucune donnée réelle, aucun réseau, base temporaire.
"""

from __future__ import annotations

import json
import tempfile
import time
from pathlib import Path

from sqlalchemy import func, select

from applyflow.campaigns.schemas import CampaignInput
from applyflow.campaigns.service import create_campaign, run_campaign
from applyflow.config import Settings
from applyflow.db import Database
from applyflow.db.models import CampaignJob, Job, Profile
from applyflow.profiles.service import seed_default_profiles

TITLES = [
    "Data Engineer",
    "Data Analyst",
    "AI Engineer",
    "Data Scientist",
    "Python Developer",
    "BI Analyst",
]
LOCATIONS = ["Paris, France", "Lyon, France", "Remote (France)", "Berlin, Germany"]
SKILLS = [
    ["Python", "SQL", "Airflow", "dbt"],
    ["SQL", "Power BI", "Excel"],
    ["Python", "PyTorch", "LLM"],
    ["Python", "Statistics", "scikit-learn"],
    ["Python", "FastAPI", "PostgreSQL"],
]


def build_jobs(count: int = 1000) -> list[dict]:
    jobs = []
    for index in range(count):
        title = TITLES[index % len(TITLES)]
        skills = SKILLS[index % len(SKILLS)]
        jobs.append(
            {
                "external_id": f"bench-{index}",
                "url": f"https://bench.example.invalid/jobs/{index}",
                "apply_url": "demo://simple",
                "company": f"Benchmark Company {index:04d}",
                "title": f"{title} #{index:04d}",
                "description": (
                    f"{title} junior. Compétences : {', '.join(skills)}. "
                    f"{LOCATIONS[index % len(LOCATIONS)]}. CDI."
                ),
                "location": LOCATIONS[index % len(LOCATIONS)],
                "contract_type": "CDI",
                "skills": skills,
                "published_at": "2026-10-01T09:00:00+00:00",
            }
        )
    return jobs


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="applyflow-bench-") as tmp:
        root = Path(tmp)
        data_dir = root / "data"
        data_dir.mkdir()
        settings = Settings(
            app={
                "data_dir": data_dir,
                "db_url": f"sqlite:///{(root / 'bench.db').as_posix()}",
                "log_level": "ERROR",
            },
            discovery={"rate_limit_seconds": 0},
        )
        jobs_path = root / "jobs.json"
        jobs_path.write_text(json.dumps(build_jobs(1000), ensure_ascii=False), encoding="utf-8")

        database = Database(settings.database_url)
        database.init_schema()
        with database.session() as session:
            seed_default_profiles(session)
            session.commit()
            profile_ids = list(session.scalars(select(Profile.id)))
            campaign = create_campaign(
                session,
                CampaignInput(
                    name="Benchmark 1000",
                    sources=[
                        {"kind": "json_file", "config": {"path": str(jobs_path)}}
                    ],
                    profile_ids=profile_ids,
                    max_jobs=1000,
                    min_score=0,
                ),
            )
            campaign_id = campaign.id
            session.commit()

        started = time.perf_counter()
        with database.session() as session:
            result = run_campaign(session, campaign_id, settings, steps=("discover", "analyze"))
        elapsed = time.perf_counter() - started

        with database.session() as session:
            jobs = session.scalar(select(func.count()).select_from(Job))
            rows = session.scalar(select(func.count()).select_from(CampaignJob))
        print(
            json.dumps(
                {
                    "jobs_ingested": jobs,
                    "campaign_jobs": rows,
                    "discover": result["steps"].get("discover"),
                    "analyze": result["steps"].get("analyze"),
                    "seconds": round(elapsed, 2),
                    "jobs_per_second": round(1000 / elapsed, 1),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        database.dispose()


if __name__ == "__main__":
    main()
