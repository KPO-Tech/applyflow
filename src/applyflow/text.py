"""Normalisation de texte (accents, casse, tokens) partagée par le scoring et le dédoublonnage."""

from __future__ import annotations

import re
import unicodedata

_WORD_RE = re.compile(r"[a-z0-9][a-z0-9+#.\-]*")

STOPWORDS = frozenset(
    ["a", "an", "and", "are", "as", "at", "be", "been", "being", "but", "by", "can", "could", "do", "does", "for", "from", "had", "has", "have", "how", "i", "if", "in", "into", "is", "it", "its", "may", "might", "more", "most", "must", "my", "no", "not", "of", "on", "or", "our", "over", "same", "should", "so", "some", "such", "than", "that", "the", "their", "them", "then", "there", "these", "they", "this", "those", "to", "too", "under", "up", "us", "use", "using", "very", "was", "we", "were", "what", "when", "where", "which", "while", "who", "will", "with", "within", "without", "would", "you", "your", "au", "aux", "avec", "ce", "ces", "cet", "cette", "dans", "de", "des", "du", "elle", "elles", "en", "est", "et", "eux", "il", "ils", "je", "la", "le", "les", "leur", "leurs", "lui", "ma", "mais", "mes", "moi", "mon", "ne", "nos", "notre", "nous", "on", "ou", "par", "pas", "pour", "qu", "que", "qui", "sa", "se", "ses", "son", "sur", "ta", "te", "tes", "toi", "ton", "tu", "un", "une", "vos", "votre", "vous", "y", "plus", "tres"]
)


def strip_accents(value: str) -> str:
    if value.isascii():  # voie rapide : rien à décomposer
        return value
    decomposed = unicodedata.normalize("NFKD", value)
    return "".join(char for char in decomposed if not unicodedata.combining(char))


def normalize_text(value: str) -> str:
    value = strip_accents(value or "").lower()
    value = value.replace("’", "'").replace("–", "-").replace("—", "-")
    value = re.sub(r"[^a-z0-9+#.\-\s]", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def tokens(value: str) -> list[str]:
    return [
        token
        for token in _WORD_RE.findall(normalize_text(value))
        if len(token) > 1 and token not in STOPWORDS
    ]


def token_set(value: str) -> set[str]:
    return set(tokens(value))


def slugify(value: str, *, max_length: int = 300) -> str:
    normalized = normalize_text(value)
    slug = re.sub(r"[^a-z0-9]+", "-", normalized).strip("-")
    return slug[:max_length]


def contains_phrase(haystack: str, needle: str) -> bool:
    """Recherche bornée par des frontières de mots, insensible aux accents."""
    haystack_norm = normalize_text(haystack)
    needle_norm = normalize_text(needle)
    if not needle_norm:
        return False
    return re.search(rf"(?<![a-z0-9]){re.escape(needle_norm)}(?![a-z0-9])", haystack_norm) is not None


def split_sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+|\n+|\u2022", text or "")
    return [part.strip() for part in parts if part.strip()]


def truncate(value: str, limit: int) -> str:
    value = (value or "").strip()
    return value if len(value) <= limit else value[: limit - 1].rstrip() + "…"
