"""Mesure du classement sur un jeu d'offres étiquetées.

Sert à comparer des approches de matching (score déterministe, embeddings, modèle de
décision) sur les mêmes offres, avec une étiquette humaine en référence. Le jeu de
données vit hors du paquet (`data/etiquetage/`) : ce module ne fait que lire et calculer.

Convention d'étiquette : `ok` (offre à traiter), `maybe` (à arbitrer à la main),
`no` (à écarter). L'AUC est calculée sur `ok` contre `no` ; `maybe` est ignoré pour
l'AUC et compté à part dans le top-k, parce que ces offres ne sont ni des succès ni
des erreurs du classement.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

LABELS = ("ok", "maybe", "no")


@dataclass(frozen=True)
class LabeledOffer:
    """Une offre du jeu de mesure, avec son étiquette et sa note d'étiquetage."""

    id: str
    title: str
    label: str
    company: str = ""
    location: str | None = None
    contract: str | None = None
    description: str = ""
    best_profile: str | None = None
    note: str = ""
    extra: dict[str, Any] = field(default_factory=dict)


class DatasetError(ValueError):
    """Les fichiers du jeu de mesure sont absents, incohérents ou incomplets."""


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise DatasetError(f"fichier absent : {path}") from exc
    except json.JSONDecodeError as exc:
        raise DatasetError(f"JSON invalide dans {path} : {exc}") from exc


def _resolve_labels_file(data_dir: Path, labels_filename: str | None) -> Path:
    if labels_filename:
        return data_dir / labels_filename
    preferred = data_dir / "etiquettes.json"
    if preferred.exists():
        return preferred
    # Un jeu étiqueté à plusieurs reprises garde le nom de son auteur : etiquettes-<nom>.json.
    candidates = sorted(data_dir.glob("etiquettes-*.json"))
    if not candidates:
        raise DatasetError(
            f"aucun fichier d'étiquettes dans {data_dir} "
            "(attendu : etiquettes.json ou etiquettes-<nom>.json)"
        )
    return candidates[0]


def load_dataset(
    data_dir: Path | str,
    *,
    offers_filename: str = "selection.json",
    labels_filename: str | None = None,
) -> list[LabeledOffer]:
    """Charge les offres et leurs étiquettes, dans l'ordre du fichier d'offres.

    Chaque offre doit avoir une étiquette connue ; une offre non étiquetée est une
    erreur, pas une offre implicitement « no ».
    """
    root = Path(data_dir)
    offers_raw = _read_json(root / offers_filename)
    labels_raw = _read_json(_resolve_labels_file(root, labels_filename))
    labels_list = labels_raw.get("labels", []) if isinstance(labels_raw, dict) else labels_raw
    if not isinstance(offers_raw, list) or not offers_raw:
        raise DatasetError(f"{root / offers_filename} doit contenir une liste d'offres")
    if not isinstance(labels_list, list) or not labels_list:
        raise DatasetError("le fichier d'étiquettes doit contenir une liste `labels`")

    by_id: dict[str, dict[str, Any]] = {}
    for entry in labels_list:
        offer_id = str(entry.get("id", "")).strip()
        if not offer_id:
            raise DatasetError("une étiquette n'a pas d'identifiant d'offre")
        label = str(entry.get("label", "")).strip().lower()
        if label not in LABELS:
            raise DatasetError(f"étiquette inconnue pour {offer_id} : {label!r}")
        by_id[offer_id] = entry

    offers: list[LabeledOffer] = []
    missing: list[str] = []
    for raw in offers_raw:
        offer_id = str(raw.get("id", "")).strip()
        entry = by_id.get(offer_id)
        if entry is None:
            missing.append(offer_id or "(sans id)")
            continue
        offers.append(
            LabeledOffer(
                id=offer_id,
                title=str(raw.get("title", "")),
                label=str(entry["label"]).strip().lower(),
                company=str(raw.get("company") or ""),
                location=raw.get("location"),
                contract=raw.get("contract"),
                description=str(raw.get("description") or ""),
                best_profile=entry.get("best_profile"),
                note=str(entry.get("note") or ""),
                extra={
                    key: value
                    for key, value in raw.items()
                    if key not in {"id", "title", "company", "location", "contract", "description"}
                },
            )
        )
    if missing:
        raise DatasetError(
            "offres sans étiquette (ajoutez-les au fichier d'étiquettes) : "
            + ", ".join(missing[:5])
            + ("…" if len(missing) > 5 else "")
        )
    return offers


def label_counts(labels: Sequence[str]) -> dict[str, int]:
    """Nombre d'offres par étiquette, dans l'ordre canonique."""
    return {label: sum(1 for value in labels if value == label) for label in LABELS}


def auc(scores: Sequence[float], labels: Sequence[str]) -> float | None:
    """Aire sous la courbe ROC pour `ok` contre `no` (les égalités comptent 0,5).

    Renvoie `None` si l'une des deux classes est absente : l'AUC n'est alors pas définie.
    """
    if len(scores) != len(labels):
        raise ValueError("scores et labels n'ont pas la même longueur")
    positive = [score for score, label in zip(scores, labels, strict=True) if label == "ok"]
    negative = [score for score, label in zip(scores, labels, strict=True) if label == "no"]
    if not positive or not negative:
        return None
    wins = 0.0
    for good in positive:
        for bad in negative:
            if good > bad:
                wins += 1.0
            elif good == bad:
                wins += 0.5
    return wins / (len(positive) * len(negative))


def top_k_counts(
    scores: Sequence[float], labels: Sequence[str], k: int
) -> dict[str, int]:
    """Étiquettes des `k` meilleures offres (tri stable, départage par l'ordre d'entrée)."""
    if len(scores) != len(labels):
        raise ValueError("scores et labels n'ont pas la même longueur")
    order = sorted(range(len(scores)), key=lambda index: -float(scores[index]))
    counts = {label: 0 for label in LABELS}
    for index in order[: max(0, k)]:
        counts[labels[index]] += 1
    return counts


def mean_rank_of(labels: Sequence[str], target: str = "ok") -> float | None:
    """Rang moyen (1 = meilleur) des offres d'une étiquette, `None` si aucune."""
    ranks = [index + 1 for index, label in enumerate(labels) if label == target]
    return sum(ranks) / len(ranks) if ranks else None


def summarize(scores: Sequence[float], labels: Sequence[str], k: int = 10) -> dict[str, Any]:
    """Toutes les métriques d'une approche, prêtes à afficher."""
    if len(scores) != len(labels):
        raise ValueError("scores et labels n'ont pas la même longueur")
    ordered = [
        label
        for _, label in sorted(
            zip(scores, labels, strict=True), key=lambda pair: -float(pair[0])
        )
    ]
    return {
        "auc": auc(scores, labels),
        "top_k": k,
        "top_k_counts": top_k_counts(scores, labels, k),
        "mean_rank_ok": mean_rank_of(ordered, "ok"),
        "count": len(labels),
        "labels": label_counts(labels),
    }


def format_auc(value: float | None) -> str:
    return "n/d" if value is None else f"{value:.3f}"


def format_rank(value: float | None) -> str:
    return "n/d" if value is None else f"{value:.1f}"


def markdown_table(results: Sequence[tuple[str, dict[str, Any]]]) -> str:
    """Tableau Markdown : une ligne par approche, dans l'ordre fourni."""
    headers = ["Approche", "AUC (ok/no)", "top-k (ok / maybe / no)", "rang moyen des ok", "offres"]
    lines = ["| " + " | ".join(headers) + " |", "|" + "---|" * len(headers)]
    for name, summary in results:
        counts = summary["top_k_counts"]
        lines.append(
            "| {name} | {auc} | top {k} : {ok} / {maybe} / {no} | {rank} | {count} |".format(
                name=name,
                auc=format_auc(summary["auc"]),
                k=summary["top_k"],
                ok=counts["ok"],
                maybe=counts["maybe"],
                no=counts["no"],
                rank=format_rank(summary["mean_rank_ok"]),
                count=summary["count"],
            )
        )
    return "\n".join(lines)
