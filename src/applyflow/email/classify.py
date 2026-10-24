"""Classification prudente des réponses : des indices, jamais une décision."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

LABEL_LABELS = {
    "interview": "Entretien",
    "offer": "Offre",
    "rejected": "Refus",
    "acknowledgement": "Accusé de réception",
    "other": "Autre",
}

_PRIORITY = ("rejected", "offer", "interview", "acknowledgement")

_RULES: dict[str, tuple[tuple[str, int], ...]] = {
    "rejected": (
        ("nous ne donnons pas suite", 4),
        ("ne donnerons pas suite", 4),
        ("n'avons pas retenu", 4),
        ("n'a pas ete retenue", 3),
        ("pas retenu votre candidature", 4),
        ("ne correspond pas a nos besoins", 3),
        ("avons choisi un autre", 3),
        ("avons decide de poursuivre", 3),
        ("poste est deja pourvu", 3),
        ("nous regrettons", 3),
        ("avons le regret", 4),
        ("regret to inform", 4),
        ("ne correspond pas au profil", 3),
        ("sans suite", 3),
        ("not be moving forward", 3),
        ("not moving forward", 3),
        ("not been selected", 3),
        ("malheureusement", 2),
        ("unfortunately", 2),
        ("unsuccessful", 2),
        ("other candidates", 2),
        ("another candidate", 2),
        ("not selected", 2),
    ),
    "offer": (
        ("proposition d'embauche", 4),
        ("offre d'embauche", 4),
        ("offre de contrat", 3),
        ("nous avons le plaisir de vous proposer", 4),
        ("we are pleased to offer", 4),
        ("job offer", 3),
        ("offer letter", 3),
        ("congratulations", 3),
        ("felicitations", 2),
        ("date de demarrage", 2),
        ("remuneration annuelle", 2),
        ("contrat de travail", 2),
    ),
    "interview": (
        ("passer un entretien", 3),
        ("entretien", 2),
        ("interview", 2),
        ("visioconference", 2),
        ("vos disponibilites", 3),
        ("disponibilites", 2),
        ("echanger avec vous", 2),
        ("rencontrer", 2),
        ("phone screen", 3),
        ("technical screen", 3),
        ("schedule a call", 3),
        ("call with you", 2),
        ("visio", 1),
        ("rendez-vous", 1),
    ),
    "acknowledgement": (
        ("avons bien recu votre candidature", 4),
        ("nous avons bien recu", 3),
        ("nous avons recu", 3),
        ("candidature recue", 3),
        ("accuse de reception", 3),
        ("merci pour votre candidature", 3),
        ("we have received your application", 4),
        ("thank you for your application", 3),
        ("application received", 3),
        ("nous reviendrons vers vous", 2),
        ("reponse automatique", 3),
        ("automatic reply", 3),
    ),
}

_ALERT_CUES = (
    "alerte emploi",
    "alertes emploi",
    "job alert",
    "nouvelles offres",
    "offres d'emploi",
    "newsletter",
    "votre profil a ete consulte",
    "postes qui pourraient",
)
_NOT_ALERTS = ("candidature", "entretien", "application", "interview")


@dataclass(frozen=True)
class Classification:
    label: str
    confidence: float
    reason: str


def fold(value: str) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(char for char in text if not unicodedata.combining(char))
    text = text.replace("\u2019", "'").replace("\u2018", "'")
    text = re.sub(r"\s+", " ", text)
    return text.lower().strip()


def classify(subject: str, body: str, sender_email: str = "") -> Classification:
    subject_key = fold(subject)
    text = fold(f"{subject}\n{body}")

    if any(cue in subject_key for cue in _ALERT_CUES) and not any(
        cue in subject_key for cue in _NOT_ALERTS
    ):
        return Classification(
            label="other",
            confidence=0.2,
            reason="Notification automatique (alerte ou newsletter), pas une réponse.",
        )

    scores: dict[str, int] = {}
    hits: dict[str, list[str]] = {}
    for label, rules in _RULES.items():
        matched = [(phrase, weight) for phrase, weight in rules if phrase in text]
        if not matched:
            continue
        scores[label] = sum(weight for _phrase, weight in matched)
        hits[label] = [phrase for phrase, _weight in matched]

    if not scores:
        return Classification(
            label="other",
            confidence=0.2,
            reason="Aucun signal de réponse détecté.",
        )

    best = max(scores.values())
    candidates = [label for label, score in scores.items() if score == best]
    label = next(item for item in _PRIORITY if item in candidates)
    confidence = min(0.96, 0.45 + 0.09 * best)
    phrases = hits[label][:3]
    reason = "Indices : " + " · ".join(phrases)
    if len(candidates) > 1:
        reason += " (signaux partagés avec une autre catégorie)"
    return Classification(label=label, confidence=round(confidence, 2), reason=reason)


def reply_label(label: str) -> str:
    return LABEL_LABELS.get(label, LABEL_LABELS["other"])
