"""CLI ApplyFlow : initialisation, campagne, export, API, interface et préremplissage."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from applyflow.applications.preparer import (
    get_attempt,
    list_applications,
    list_attempts,
    record_submission,
)
from applyflow.campaigns.service import (
    STEPS,
    get_campaign,
    list_campaigns,
    run_campaign,
)
from applyflow.config import Settings, load_settings
from applyflow.dashboard import dashboard_metrics
from applyflow.db import Database
from applyflow.db.models import Campaign
from applyflow.export import export_campaign
from applyflow.logging_setup import configure_logging
from applyflow.profiles.service import list_profiles
from applyflow.providers import provider_catalog

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _database(settings: Settings) -> Database:
    settings.ensure_directories()
    database = Database(settings.database_url)
    database.init_schema()
    return database


def _resolve_campaign(session, campaign_id: str | None, name: str | None) -> Campaign:
    if campaign_id:
        return get_campaign(session, campaign_id)
    campaigns = list_campaigns(session)
    if name:
        for campaign in campaigns:
            if campaign.name == name:
                return campaign
        raise SystemExit(f"campagne introuvable : {name}")
    if not campaigns:
        raise SystemExit("aucune campagne : créez-en une dans l'interface (Campagnes)")
    return campaigns[0]


def _print(payload: Any) -> None:
    print(json.dumps(payload, indent=2, ensure_ascii=False, default=str))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="applyflow", description="ApplyFlow")
    parser.add_argument("--config", help="chemin du fichier applyflow.toml")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("init-db", help="crée ou met à jour la base SQLite")
    sub.add_parser(
        "rebuild-dedupe", help="recalcule les empreintes de dédoublonnage des annonces existantes"
    )
    sub.add_parser("status", help="affiche les métriques du tableau de bord")
    sub.add_parser("providers", help="liste les connecteurs et leurs limites")

    run = sub.add_parser("run-campaign", help="exécute ou reprend une campagne")
    run.add_argument("--id", dest="campaign_id")
    run.add_argument("--name")
    run.add_argument("--steps", default=",".join(STEPS))
    run.add_argument("--max-items", type=int)

    export = sub.add_parser("export", help="exporte les résultats d'une campagne")
    export.add_argument("--campaign", required=True)
    export.add_argument("--output")
    export.add_argument("--format", default="csv", choices=["csv", "json"])

    discover = sub.add_parser("import-json", help="importe des annonces depuis un fichier JSON")
    discover.add_argument("--file", required=True)
    discover.add_argument("--limit", type=int, default=1000)

    api = sub.add_parser("serve-api", help="lance l'API FastAPI locale")
    api.add_argument("--host")
    api.add_argument("--port", type=int)

    ui = sub.add_parser("serve-ui", help="lance l'interface web locale")
    ui.add_argument("--port", type=int)

    fill = sub.add_parser(
        "fill", help="préremplit une candidature validée avec Playwright (sans soumettre)"
    )
    fill.add_argument("--attempt", required=True)
    fill.add_argument("--headful", action="store_true")

    submit = sub.add_parser(
        "record-submission", help="enregistre une soumission effectuée manuellement"
    )
    submit.add_argument("--attempt", required=True)
    submit.add_argument("--reference")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    settings = load_settings(args.config)
    configure_logging(settings.app.log_level, settings.app.log_json)

    if args.command == "init-db":
        database = _database(settings)
        with database.session() as session:
            from applyflow.services import ensure_local_user

            ensure_local_user(session)
        _print({"database": settings.database_url, "status": "ok"})
        return 0

    if args.command == "rebuild-dedupe":
        from applyflow.jobs.service import rebuild_fingerprints

        database = _database(settings)
        with database.session() as session:
            _print(rebuild_fingerprints(session))
        return 0

    if args.command == "status":
        database = _database(settings)
        with database.session() as session:
            metrics = dashboard_metrics(session)
            metrics["profiles"] = len(list_profiles(session, active_only=False))
            metrics["applications_queue"] = len(list_attempts(session))
            metrics["applications_total"] = len(list_applications(session))
        _print(metrics)
        return 0

    if args.command == "providers":
        _print(provider_catalog())
        return 0

    if args.command == "run-campaign":
        database = _database(settings)
        steps = [step.strip() for step in args.steps.split(",") if step.strip()]
        with database.session() as session:
            campaign = _resolve_campaign(session, args.campaign_id, args.name)
            _print(
                run_campaign(
                    session,
                    campaign.id,
                    settings,
                    steps=steps,
                    max_items=args.max_items,
                )
            )
        return 0

    if args.command == "export":
        database = _database(settings)
        with database.session() as session:
            campaign = get_campaign(session, args.campaign)
            destination = (
                Path(args.output)
                if args.output
                else settings.data_dir / "exports" / f"{campaign.id}.{args.format}"
            )
            path = export_campaign(session, campaign.id, destination, fmt=args.format)
        _print({"export": str(path)})
        return 0

    if args.command == "import-json":
        database = _database(settings)
        from applyflow.jobs.service import collect_jobs
        from applyflow.schemas import JobQuery

        with database.session() as session:
            result, errors = collect_jobs(
                session,
                [{"kind": "json_file", "config": {"path": args.file}}],
                JobQuery(limit=args.limit),
                settings,
            )
            _print({**result.model_dump(), "errors": errors})
        return 0

    if args.command == "serve-api":
        import uvicorn

        from applyflow.api.main import create_app

        app = create_app(settings)
        uvicorn.run(
            app,
            host=args.host or settings.api.host,
            port=args.port or settings.api.port,
            log_level=settings.app.log_level.lower(),
        )
        return 0

    if args.command == "serve-ui":
        import uvicorn

        from applyflow.api.main import create_app

        app = create_app(settings)
        uvicorn.run(
            app,
            host="127.0.0.1",
            port=args.port or settings.ui.port,
            log_level=settings.app.log_level.lower(),
        )
        return 0

    if args.command == "fill":
        from applyflow.applications.forms import ApplicationPlan
        from applyflow.applications.playwright_filler import fill_with_playwright
        from applyflow.db.models import Job

        database = _database(settings)
        with database.session() as session:
            attempt = get_attempt(session, args.attempt)
            if attempt.status != "approved":
                raise SystemExit(
                    "seule une candidature validée peut être préremplie "
                    f"(statut actuel : {attempt.status})"
                )
            job = session.get(Job, attempt.job_id)
            plan = ApplicationPlan.model_validate(attempt.plan)
            report = fill_with_playwright(
                job.apply_url or job.url,
                plan,
                headless=not args.headful,
            )
        _print(report.model_dump())
        return 0 if not report.errors else 1

    if args.command == "record-submission":
        database = _database(settings)
        with database.session() as session:
            attempt = get_attempt(session, args.attempt)
            application = record_submission(
                session, attempt, confirmed=True, reference=args.reference
            )
            _print({"application_id": application.id, "status": application.status})
        return 0

    parser.error(f"commande inconnue : {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
