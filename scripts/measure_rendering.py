"""Mesure : combien de formulaires deviennent lisibles quand la page est rendue.

Pour chaque candidature encore en attente, la page est lue deux fois — HTML servi, puis
page rendue par un navigateur — et les champs exploitables sont comparés. Le second passage
ne clique nulle part : il récupère le DOM affiché, comme le ferait un visiteur.

    uv run python scripts/measure_rendering.py
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from urllib.parse import urlsplit

from sqlalchemy import select

from applyflow.applications.fetcher import (
    BrowserFormFetcher,
    FormFetchError,
    HttpFormFetcher,
)
from applyflow.applications.forms import FormAnalysisError, NoFormFields, analyze_html
from applyflow.config import load_settings
from applyflow.db import Database
from applyflow.db.models import ApplicationAttempt, Job

# Statuts qui attendent encore une action et pourraient gagner du rendu.
PENDING = ("manual", "blocked", "needs_review", "prepared")


def read(url: str, fetcher: object) -> tuple[int | None, str | None]:
    """Nombre de champs trouvés, ou None avec la raison de l'échec."""
    try:
        form = fetcher.fetch(url)  # type: ignore[attr-defined]
        analysis = analyze_html(form.html, form.url)
    except NoFormFields:
        return 0, "aucun champ"
    except (FormFetchError, FormAnalysisError) as exc:
        return None, str(exc)[:70]
    return len(analysis.fields), None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, help="ne mesurer que les N premières offres")
    parser.add_argument("--http-only", action="store_true", help="sauter le rendu navigateur")
    parser.add_argument("--json", help="enregistrer le détail dans ce fichier JSON")
    args = parser.parse_args()

    settings = load_settings(None)
    database = Database(settings.database_url)
    with database.session() as session:
        rows = list(
            session.execute(
                select(ApplicationAttempt, Job)
                .join(Job, Job.id == ApplicationAttempt.job_id)
                .where(ApplicationAttempt.status.in_(PENDING))
                .order_by(ApplicationAttempt.created_at)
            ).all()
        )
    if args.limit:
        rows = rows[: args.limit]
    if not rows:
        print("Aucune candidature en attente : rien à mesurer.")
        return 0

    http = HttpFormFetcher(settings=settings)
    browser = None if args.http_only else BrowserFormFetcher(settings)
    pause = settings.discovery.rate_limit_seconds

    print(f"{len(rows)} offres en attente — lecture HTTP puis rendu navigateur\n")
    print(f"{'statut':13} {'domaine':34} {'HTTP':>6} {'RENDU':>7}  verdict")
    print("-" * 92)

    details: list[dict[str, object]] = []
    gained = 0
    readable = 0
    unusable = 0
    for attempt, job in rows:
        url = job.apply_url or job.url
        host = urlsplit(url).hostname or "?"
        http_fields, http_error = read(url, http)
        rendered_fields: int | None = None
        rendered_error = None
        if http_fields == 0 and browser is not None:
            rendered_fields, rendered_error = read(url, browser)

        if http_fields:
            verdict = "lisible sans navigateur"
            readable += 1
        elif rendered_fields:
            verdict = "LISIBLE GRÂCE AU RENDU"
            gained += 1
            readable += 1
        elif http_fields is None and rendered_fields is None:
            verdict = f"inaccessible ({http_error or rendered_error})"
            unusable += 1
        else:
            verdict = "aucun champ même rendu"
            unusable += 1

        shown = "-" if http_fields is None else str(http_fields)
        shown_rendered = "-" if rendered_fields is None else str(rendered_fields)
        print(f"{attempt.status:13} {host[:34]:34} {shown:>6} {shown_rendered:>7}  {verdict}")

        details.append(
            {
                "attempt_id": attempt.id,
                "status": attempt.status,
                "title": job.title,
                "company": job.company,
                "url": url,
                "http_fields": http_fields,
                "http_error": http_error,
                "rendered_fields": rendered_fields,
                "rendered_error": rendered_error,
                "verdict": verdict,
            }
        )
        time.sleep(pause)

    print("-" * 92)
    print(
        f"\n{readable}/{len(rows)} exploitables : "
        f"{readable - gained} déjà lisibles en HTTP, {gained} seulement après rendu, "
        f"{unusable} inutilisables."
    )
    if gained:
        print("Ces offres n'attendaient qu'un navigateur, pas une intelligence : relancer la")
        print("préparation les fera passer de « à postuler à la main » à préparées.")

    if args.json:
        Path(args.json).write_text(
            json.dumps(details, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"\nDétail écrit dans {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
