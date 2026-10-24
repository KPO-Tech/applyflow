"""Lecture IMAP d'une boîte Gmail, en lecture seule."""

from __future__ import annotations

import contextlib
import email
import imaplib
import re
import socket
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from email.header import decode_header, make_header
from email.message import Message
from email.utils import parseaddr, parsedate_to_datetime
from html import unescape

from applyflow.config import Settings
from applyflow.email.account import normalize_password

MAX_BODY_CHARS = 1600


class MailboxError(RuntimeError):
    """Erreur lisible par l'utilisateur, sans jamais contenir le secret."""


@dataclass(frozen=True)
class InboundEmail:
    remote_id: str
    subject: str
    sender_name: str
    sender_email: str
    body: str
    received_at: datetime


def _connect(address: str, password: str, host: str, port: int) -> imaplib.IMAP4_SSL:
    try:
        client = imaplib.IMAP4_SSL(host, port, timeout=25)
    except (OSError, socket.gaierror) as exc:
        raise MailboxError(
            f"Connexion IMAP impossible à {host}:{port}. Vérifiez votre connexion réseau ({exc})."
        ) from exc
    try:
        client.login(address, normalize_password(password))
    except imaplib.IMAP4.error as exc:
        with contextlib.suppress(Exception):
            client.shutdown()
        message = str(exc).lower()
        if "authentication" in message or "invalid credentials" in message or "login" in message:
            raise MailboxError(
                "Gmail a refusé la connexion. Utilisez un mot de passe d'application "
                "(16 caractères, pas votre mot de passe habituel) et vérifiez que la "
                "validation en deux étapes est active sur le compte."
            ) from exc
        raise MailboxError(f"La connexion IMAP a échoué : {exc}") from exc
    return client


def _logout(client: imaplib.IMAP4_SSL) -> None:
    with contextlib.suppress(Exception):
        client.logout()


def test_connection(
    address: str, password: str, *, host: str = "imap.gmail.com", port: int = 993
) -> dict[str, object]:
    client = _connect(address, password, host, port)
    try:
        status, data = client.select("INBOX", readonly=True)
        if status != "OK":
            raise MailboxError("La boîte de réception n'est pas accessible en lecture.")
        total = 0
        if data and isinstance(data[0], bytes) and data[0].isdigit():
            total = int(data[0])
        return {"address": address, "messages": total}
    finally:
        _logout(client)


def _fetch_bytes(client: imaplib.IMAP4_SSL, uid: int, section: str) -> bytes | None:
    status, data = client.uid("fetch", str(uid), f"({section})")
    if status != "OK" or not data:
        return None
    for item in data:
        if isinstance(item, tuple):
            # Un littéral IMAP arrive sous la forme (métadonnées, contenu).
            parts = [part for part in item if isinstance(part, bytes)]
            if parts:
                return parts[-1]
        elif isinstance(item, bytes):
            return item
    return None


def _decode_header(value: str | None) -> str:
    if not value:
        return ""
    try:
        return str(make_header(decode_header(value))).strip()
    except Exception:  # en-tête exotique : on garde la valeur brute
        return str(value).strip()


def _part_text(part: Message) -> str:
    payload = part.get_payload(decode=True)
    if payload is None:
        raw = part.get_payload()
        return raw if isinstance(raw, str) else ""
    charset = part.get_content_charset() or "utf-8"
    try:
        return payload.decode(charset, errors="replace")
    except LookupError:
        return payload.decode("utf-8", errors="replace")


def _html_to_text(value: str) -> str:
    text = re.sub(r"(?is)<(script|style).*?</\1>", " ", value)
    text = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</li>", "\n", text)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    return unescape(text)


def _body_text(message: Message) -> str:
    plain: str | None = None
    html: str | None = None
    for part in message.walk():
        disposition = str(part.get("Content-Disposition") or "").lower()
        if "attachment" in disposition:
            continue
        content_type = part.get_content_type()
        if content_type == "text/plain" and plain is None:
            plain = _part_text(part)
        elif content_type == "text/html" and html is None:
            html = _part_text(part)
    text = plain or _html_to_text(html or "")
    text = re.sub(r"[ \t\u00a0]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return text[:MAX_BODY_CHARS]


def _received_at(message: Message) -> datetime:
    raw = message.get("Date")
    if raw:
        try:
            parsed = parsedate_to_datetime(str(raw))
            if parsed is not None:
                return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
        except (TypeError, ValueError):
            pass
    return datetime.now(UTC)


def fetch_messages(
    *,
    address: str,
    password: str,
    settings: Settings,
    known_ids: set[str],
    now: datetime | None = None,
    limit: int | None = None,
) -> list[InboundEmail]:
    """Récupère les messages récents de la boîte, sans jamais marquer comme lu."""
    config = settings.email
    since = (now or datetime.now(UTC)) - timedelta(days=config.lookback_days)
    client = _connect(address, password, config.imap_host, config.imap_port)
    try:
        status, _ = client.select(config.folder, readonly=True)
        if status != "OK":
            raise MailboxError(f"Le dossier « {config.folder} » n'est pas accessible.")
        try:
            status, data = client.uid(
                "search", None, f'(SINCE "{since.strftime("%d-%b-%Y")}")'
            )
        except imaplib.IMAP4.error as exc:
            raise MailboxError(f"La recherche IMAP a échoué : {exc}") from exc
        if status != "OK" or not data:
            raise MailboxError("La recherche IMAP n'a renvoyé aucun résultat exploitable.")
        uids = sorted({int(uid) for uid in (data[0] or b"").split()}, reverse=True)
        uids = uids[: limit or config.max_messages]

        messages: list[InboundEmail] = []
        for uid in uids:
            header_raw = _fetch_bytes(client, uid, "BODY.PEEK[HEADER]")
            if header_raw is None:
                continue
            header = email.message_from_bytes(header_raw)
            remote_id = (
                str(header.get("Message-ID") or f"imap:{address}:{config.folder}:{uid}")
            ).strip()
            if remote_id in known_ids:
                continue
            raw = _fetch_bytes(client, uid, "BODY.PEEK[]") or header_raw
            message = email.message_from_bytes(raw)
            sender_name, sender_email = parseaddr(_decode_header(message.get("From")))
            messages.append(
                InboundEmail(
                    remote_id=remote_id,
                    subject=_decode_header(message.get("Subject"))[:480],
                    sender_name=(sender_name or "").strip()[:240],
                    sender_email=(sender_email or "").strip().lower(),
                    body=_body_text(message),
                    received_at=_received_at(message),
                )
            )
        messages.sort(key=lambda item: item.received_at, reverse=True)
        return messages
    except imaplib.IMAP4.error as exc:
        raise MailboxError(f"La synchronisation IMAP a échoué : {exc}") from exc
    finally:
        _logout(client)
