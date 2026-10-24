"""Compare des approches de matching sur les offres étiquetées à la main.

Usage :
    uv run python scripts/eval_matching.py
    uv run python scripts/eval_matching.py --json
    uv run python scripts/eval_matching.py --data-dir data/etiquetage --k 10

Le score ApplyFlow est **recalculé** avec le code courant, les profils actifs de la
base et la configuration locale : le chiffre suit donc les changements du moteur.
Les colonnes externes de `comparaison.csv` (modèle de décision Laya, embeddings) sont
des mesures enregistrées, impossibles à recalculer ici sans leurs dépendances ; elles
sont affichées à côté, marquées comme telles.

Lecture seule : aucune écriture en base, aucun appel réseau.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

from sqlalchemy import select

from applyflow.config import Settings, load_settings
from applyflow.db import Database
from applyflow.db.models import Profile
from applyflow.matching.evaluation import (
    DatasetError,
    LabeledOffer,
    label_counts,
    load_dataset,
    markdown_table,
    summarize,
)
from applyflow.matching.router import build_router
from applyflow.matching.scoring import JobSignals, score_job
from applyflow.matching.types import ProfileSnapshot, snapshot_profile

APPLYFLOW_COLUMN = "ApplyFlow courant"
RECORDED_FILE = "comparaison.csv"


class OfferView:
    """Vue minimale d'une offre, aux attributs attendus par le routeur et le scoring."""

    def __init__(self, offer: LabeledOffer) -> None:
        self.id = offer.id
        self.title = offer.title
        self.description = offer.description
        self.company = offer.company
        self.location = offer.location
        self.contract_type = offer.contract
        self.remote = None
        self.skills: list[str] = []
        self.salary_min = None
        self.salary_max = None


def active_profiles(settings: Settings) -> dict[str, ProfileSnapshot]:
    database = Database(settings.database_url)
    try:
        with database.session() as session:
            profiles = list(session.scalars(select(Profile).where(Profile.active.is_(True))))
            return {profile.id: snapshot_profile(profile) for profile in profiles}
    finally:
        database.dispose()


def score_offers(
    offers: list[LabeledOffer],
    profiles: dict[str, ProfileSnapshot],
    settings: Settings,
) -> list[float]:
    """Score de chaque offre, avec la même chaîne que l'analyse de campagne.

    Routeur puis `score_job` sur le profil retenu. Une offre non éligible (porte de
    salaire, de contrat, de localisation, de niveau) reçoit -1 : elle sort de la file de
    validation, donc elle doit passer derrière toutes les autres au classement.
    """
    router = build_router(settings)
    snapshots = list(profiles.values())
    scores: list[float] = []
    for offer in offers:
        view = OfferView(offer)
        decision = router.route(view, snapshots)
        profile = profiles[decision.profile_id]
        result = score_job(JobSignals.from_any(view), profile, settings.scoring)
        scores.append(float(result.score) if result.eligible else -1.0)
    return scores


def recorded_columns(
    data_dir: Path,
) -> tuple[list[str], list[tuple[str, dict[str, float]]]]:
    """Colonnes externes de `comparaison.csv`, dans l'ordre du fichier.

    Une liste de couples (titre, valeurs) plutôt qu'un dictionnaire : les titres ne sont
    pas uniques dans le jeu d'offres (deux offres peuvent s'appeler « AI Engineer H/F »).
    """
    path = data_dir / RECORDED_FILE
    if not path.exists():
        return [], []
    with path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    if not rows:
        return [], []
    names = [name for name in rows[0] if name not in {"titre", "label"}]
    values: list[tuple[str, dict[str, float]]] = []
    for row in rows:
        title = row.get("titre") or ""
        parsed: dict[str, float] = {}
        for name in names:
            try:
                parsed[name] = float(row[name])
            except (TypeError, ValueError):
                continue
        values.append((title, parsed))
    return names, values


def align_recorded(
    offers: list[LabeledOffer], values: list[tuple[str, dict[str, float]]]
) -> list[dict[str, float] | None]:
    """Associe les lignes enregistrées aux offres, dans le même ordre.

    Le CSV d'origine n'a pas d'identifiant et tronque les titres à 50 caractères : on
    associe d'abord par titre exact, puis par titre tronqué (préfixe unique), et pour les
    titres en double on consomme les lignes dans l'ordre du fichier, qui suit celui des
    offres.
    """
    queues: dict[str, list[dict[str, float]]] = {}
    for title, row in values:
        queues.setdefault(title, []).append(row)

    def take(title: str) -> dict[str, float] | None:
        queue = queues.get(title)
        if not queue:
            return None
        return queue.pop(0)

    aligned: list[dict[str, float] | None] = []
    for offer in offers:
        row = take(offer.title)
        if row is None:
            candidates = [
                title for title, queue in queues.items() if queue and offer.title.startswith(title)
            ]
            if len(candidates) == 1:
                row = take(candidates[0])
        aligned.append(row)
    return aligned


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--data-dir", default="data/etiquetage", help="jeu d'offres étiquetées")
    parser.add_argument("--config", default=None, help="fichier TOML (défaut : découverte habituelle)")
    parser.add_argument("--k", type=int, default=10, help="taille du top à inspecter (défaut : 10)")
    parser.add_argument("--json", action="store_true", help="sortie JSON au lieu du tableau Markdown")
    args = parser.parse_args(argv)

    data_dir = Path(args.data_dir)
    try:
        offers = load_dataset(data_dir)
    except DatasetError as exc:
        print(f"jeu de mesure inutilisable : {exc}", file=sys.stderr)
        return 2

    settings = load_settings(args.config)
    profiles = active_profiles(settings)
    if not profiles:
        print(
            "aucun profil actif dans la base : créez un profil (interface ou `applyflow seed`) "
            "avant de mesurer, sinon le score n'a pas de sens.",
            file=sys.stderr,
        )
        return 2

    labels = [offer.label for offer in offers]
    approaches: list[tuple[str, list[float]]] = [
        (APPLYFLOW_COLUMN, score_offers(offers, profiles, settings))
    ]

    names, recorded = recorded_columns(data_dir)
    aligned = align_recorded(offers, recorded)
    for name in names:
        missing = sum(1 for row in aligned if row is None or name not in row)
        if missing:
            print(
                f"colonne « {name} » incomplète : {missing} offre(s) sans valeur, ignorée",
                file=sys.stderr,
            )
            continue
        approaches.append(
            (f"{name} (enregistré)", [float(row[name]) for row in aligned if row])
        )

    results = [(name, summarize(scores, labels, k=args.k)) for name, scores in approaches]
    counts = label_counts(labels)

    if args.json:
        print(
            json.dumps(
                {
                    "offers": len(offers),
                    "labels": counts,
                    "profiles": [profile.name for profile in profiles.values()],
                    "k": args.k,
                    "approaches": [{"name": name, **summary} for name, summary in results],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    print(markdown_table(results))
    print()
    print(
        f"{len(offers)} offres étiquetées (ok {counts['ok']}, maybe {counts['maybe']}, "
        f"no {counts['no']}) ; top {args.k} ; profils actifs : "
        + ", ".join(profile.name for profile in profiles.values())
    )
    print(
        "« ApplyFlow courant » est recalculé à chaque exécution (offres non éligibles classées "
        f"-1) ; les colonnes « enregistré » viennent de {RECORDED_FILE} et ne sont pas rejouées."
    )
    if counts["ok"] < 10:
        print(
            f"attention : {counts['ok']} offre(s) « ok » seulement — l'AUC est instable, "
            "à lire comme un ordre de grandeur."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
