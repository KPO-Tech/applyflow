from __future__ import annotations

import json
from pathlib import Path

import pytest

from applyflow.matching.evaluation import (
    DatasetError,
    auc,
    label_counts,
    load_dataset,
    markdown_table,
    mean_rank_of,
    summarize,
    top_k_counts,
)

REAL_DATA_DIR = Path(__file__).resolve().parents[1] / "data" / "etiquetage"


def test_auc_perfect_and_inverted() -> None:
    scores = [0.9, 0.8, 0.2, 0.1]
    labels = ["ok", "ok", "no", "no"]
    assert auc(scores, labels) == 1.0
    assert auc(list(reversed(scores)), labels) == 0.0


def test_auc_ties_count_half() -> None:
    assert auc([0.5, 0.5], ["ok", "no"]) == 0.5


def test_auc_ignores_maybe_and_needs_both_classes() -> None:
    # « maybe » est hors du calcul : ni succès ni erreur du classement.
    assert auc([0.9, 0.4, 0.8], ["ok", "maybe", "no"]) == 1.0
    assert auc([0.9, 0.8], ["ok", "maybe"]) is None
    assert auc([0.9, 0.8], ["maybe", "no"]) is None


def test_auc_rejects_mismatched_lengths() -> None:
    with pytest.raises(ValueError):
        auc([0.5], ["ok", "no"])


def test_top_k_counts_puts_best_first() -> None:
    scores = [0.1, 0.9, 0.5, 0.8]
    labels = ["no", "ok", "maybe", "ok"]
    assert top_k_counts(scores, labels, 2) == {"ok": 2, "maybe": 0, "no": 0}
    assert top_k_counts(scores, labels, 4) == {"ok": 2, "maybe": 1, "no": 1}
    assert top_k_counts(scores, labels, 0) == {"ok": 0, "maybe": 0, "no": 0}


def test_mean_rank_of_missing_label_is_none() -> None:
    assert mean_rank_of(["no", "maybe"], "ok") is None
    assert mean_rank_of(["ok", "no", "ok"], "ok") == 2.0


def test_summarize_reports_rank_of_ok_after_sorting() -> None:
    summary = summarize([0.2, 0.9, 0.5], ["no", "ok", "maybe"], k=2)
    assert summary["auc"] == 1.0
    assert summary["top_k_counts"] == {"ok": 1, "maybe": 1, "no": 0}
    assert summary["mean_rank_ok"] == 1.0
    assert summary["count"] == 3


def test_markdown_table_marks_missing_auc() -> None:
    table = markdown_table([("approche", summarize([0.9, 0.8], ["ok", "maybe"]))])
    assert "n/d" in table
    assert "approche" in table


def _write_dataset(root: Path, offers: list[dict], labels: list[dict]) -> None:
    (root / "selection.json").write_text(json.dumps(offers), encoding="utf-8")
    (root / "etiquettes-test.json").write_text(
        json.dumps({"labeled_by": "test", "labels": labels}), encoding="utf-8"
    )


def test_load_dataset_reads_named_labels_file(tmp_path: Path) -> None:
    _write_dataset(
        tmp_path,
        offers=[{"id": "a", "title": "Data Engineer", "description": "Python"}],
        labels=[{"id": "a", "label": "ok", "note": "convient"}],
    )
    offers = load_dataset(tmp_path)
    assert len(offers) == 1
    assert offers[0].title == "Data Engineer"
    assert offers[0].label == "ok"
    assert offers[0].note == "convient"


def test_load_dataset_refuses_unlabelled_offer(tmp_path: Path) -> None:
    _write_dataset(tmp_path, offers=[{"id": "a", "title": "X"}], labels=[])
    with pytest.raises(DatasetError):
        load_dataset(tmp_path)


def test_load_dataset_refuses_unknown_label(tmp_path: Path) -> None:
    _write_dataset(
        tmp_path,
        offers=[{"id": "a", "title": "X"}],
        labels=[{"id": "a", "label": "peut-être"}],
    )
    with pytest.raises(DatasetError):
        load_dataset(tmp_path)


def test_load_dataset_refuses_offer_without_label(tmp_path: Path) -> None:
    _write_dataset(
        tmp_path,
        offers=[{"id": "a", "title": "X"}, {"id": "b", "title": "Y"}],
        labels=[{"id": "a", "label": "no"}],
    )
    with pytest.raises(DatasetError, match="b"):
        load_dataset(tmp_path)


@pytest.mark.skipif(not REAL_DATA_DIR.exists(), reason="jeu d'étiquetage absent")
def test_real_dataset_is_consistent() -> None:
    """Le jeu livré reste étiqueté sans trou ni doublon : une mesure fiable en dépend."""
    offers = load_dataset(REAL_DATA_DIR)
    assert len(offers) == 40
    assert len({offer.id for offer in offers}) == len(offers)
    assert label_counts([offer.label for offer in offers]) == {"ok": 3, "maybe": 12, "no": 25}
    assert all(offer.title for offer in offers)
