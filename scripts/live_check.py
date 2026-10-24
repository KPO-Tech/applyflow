"""Tests réels de collecte, dans une base et des plafonds TEMPORAIRES (jamais votre configuration).

    uv run python scripts/live_check.py ats
    uv run python scripts/live_check.py boards --confirm

`boards` interroge LinkedIn, Indeed, Glassdoor et HelloWork (usage personnel, volume très faible,
à vos risques) : il exige --confirm. Les plafonds utilisés ici sont bas et n'affectent pas votre
compteur quotidien réel.
"""

from __future__ import annotations

import argparse
import collections
import pathlib
import sys
import tempfile
import time
import warnings

warnings.filterwarnings("ignore")

from sqlalchemy import select  # noqa: E402

from applyflow.config import Settings  # noqa: E402
from applyflow.db.base import Database  # noqa: E402
from applyflow.db.models import Job  # noqa: E402
from applyflow.jobs.service import count_jobs_by_country, ingest_jobs  # noqa: E402
from applyflow.providers import build_provider  # noqa: E402
from applyflow.schemas import JobQuery  # noqa: E402

ATS_DEFAULT = [
    "greenhouse:datadog", "greenhouse:doctolib", "greenhouse:algolia",
    "lever:qonto", "ashby:alan", "ashby:backmarket",
]


def report(provider, jobs, db, seconds: float) -> None:
    long_desc = sum(len(j.description) > 200 for j in jobs)
    print(f"\n{len(jobs)} offres collectées en {seconds:.1f} s "
          f"({long_desc} avec description complète, soit "
          f"{round(100 * long_desc / len(jobs)) if jobs else 0} %)")
    for name, detail in provider.last_stats.items():
        total = f" sur {detail['total']}" if "total" in detail else ""
        errors = f"  ERREUR: {detail['errors'][0]}" if detail["errors"] else ""
        print(f"  {name:<22} {detail['jobs']:>4}{total}  ({detail['seconds']} s){errors}")
    with db.session() as session:
        result = ingest_jobs(session, jobs)
        print(f"\nEnregistrement : {result.created} uniques, {result.duplicates} fusionnées")
        multi = [
            j for j in session.scalars(select(Job)) if len((j.raw or {}).get("sources", [])) > 1
        ]
        print(f"Offres vues sur plusieurs plateformes : {len(multi)}")
        for job in multi[:5]:
            names = [s["source"].split(":")[-1] for s in job.raw["sources"]]
            print(f"  - {job.company} | {job.title[:50]} | {names}")
        print("Par pays :", {r["country"]: r["count"] for r in count_jobs_by_country(session)})
        seniority = collections.Counter(j.seniority for j in session.scalars(select(Job)))
        print("Séniorité :", dict(seniority))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument("mode", choices=["ats", "boards"])
    parser.add_argument("--keywords", default="", help="séparés par des virgules")
    parser.add_argument("--locations", default="France")
    parser.add_argument("--confirm", action="store_true", help="requis pour `boards`")
    args = parser.parse_args()

    tmp = pathlib.Path(tempfile.mkdtemp(prefix="applyflow-live-"))
    settings = Settings()
    settings.app.data_dir = tmp
    db = Database(f"sqlite:///{tmp}/live.db")
    db.init_schema()
    locations = [part.strip() for part in args.locations.split(",") if part.strip()]
    started = time.monotonic()

    if args.mode == "ats":
        keywords = [k.strip() for k in (args.keywords or "data,machine learning").split(",")]
        provider = build_provider(
            {"kind": "ats", "config": {"companies": ATS_DEFAULT, "concurrency": 4}}, settings=settings
        )
        print("ATS publics :", ", ".join(ATS_DEFAULT))
        jobs = provider.fetch(JobQuery(keywords=keywords, locations=locations, limit=500))
    else:
        if not args.confirm:
            print("Refusé : `boards` interroge LinkedIn, Indeed, Glassdoor et HelloWork.\n"
                  "Ces sites encadrent l'automatisation (usage personnel, à vos risques).\n"
                  "Relancez avec --confirm (ou : make live-boards CONFIRM=yes).")
            return 2
        keywords = [k.strip() for k in (args.keywords or "Data Engineer junior").split(",")]
        settings.boards.jobspy_enabled = True
        settings.boards.sites = ["indeed", "hellowork", "linkedin", "glassdoor"]
        settings.boards.max_per_site = 10
        settings.boards.pause_seconds = 4
        settings.boards.daily_limits = {"linkedin": 5, "indeed": 10, "glassdoor": 10, "hellowork": 10}
        provider = build_provider({"kind": "jobspy"}, settings=settings)
        print("Job boards (plafonds de ce test : LinkedIn 5, autres 10) …")
        jobs = provider.fetch(JobQuery(keywords=keywords, locations=locations, limit=100))
    report(provider, jobs, db, time.monotonic() - started)
    return 0


if __name__ == "__main__":
    sys.exit(main())
