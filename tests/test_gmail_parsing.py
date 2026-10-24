"""Parsing IMAP : corps, en-têtes, pièces jointes, erreurs de connexion."""

from __future__ import annotations

import base64
import imaplib
from datetime import UTC
from email import message_from_bytes

import pytest

from applyflow.email import gmail as gmail_module


def _parse(raw: bytes):
    return message_from_bytes(raw)


def test_body_prefers_plain_text_and_keeps_accents() -> None:
    raw = (
        'From: =?iso-8859-1?Q?Camille_Martin?= <Camille@Example.invalid>\n'
        "Subject: =?utf-8?Q?Entretien_d=C3=A9cision?=\n"
        "Date: Thu, 22 Oct 2026 10:00:00 +0000\n"
        "MIME-Version: 1.0\n"
        'Content-Type: multipart/alternative; boundary="B"\n'
        "\n"
        "--B\n"
        'Content-Type: text/plain; charset="iso-8859-1"\n'
        "Content-Transfer-Encoding: quoted-printable\n"
        "\n"
        "Nous =E9tudions votre dossier.\n"
        "--B\n"
        'Content-Type: text/html; charset="utf-8"\n'
        "\n"
        "<p>Version HTML</p>\n"
        "--B--\n"
    )
    message = _parse(raw.encode("ascii"))
    assert gmail_module._body_text(message) == "Nous étudions votre dossier."
    assert gmail_module._decode_header(message["Subject"]) == "Entretien décision"
    assert gmail_module._decode_header(message["From"]).endswith("<Camille@Example.invalid>")


def test_html_only_body_loses_markup_scripts_and_entities() -> None:
    raw = (
        'Content-Type: text/html; charset="utf-8"\n'
        "\n"
        "<html><head><style>.a{color:red}</style>"
        "<script>var secret = 1;</script></head>"
        "<body><p>Bonjour&nbsp;Camille,</p><br>"
        "<div>Entretien&nbsp;: lundi</div></body></html>"
    )
    text = gmail_module._body_text(_parse(raw.encode("utf-8")))
    assert "Bonjour Camille," in text
    assert "Entretien : lundi" in text
    assert "secret" not in text
    assert "<p>" not in text
    assert "&nbsp;" not in text


def test_attachment_is_never_used_as_body() -> None:
    raw = (
        'Content-Type: multipart/mixed; boundary="B"\n'
        "\n"
        "--B\n"
        'Content-Type: text/plain; charset="utf-8"\n'
        'Content-Disposition: attachment; filename="notes.txt"\n'
        "\n"
        "Pièce jointe ignorée.\n"
        "--B\n"
        'Content-Type: text/plain; charset="utf-8"\n'
        "\n"
        "Corps réel.\n"
        "--B--\n"
    )
    assert gmail_module._body_text(_parse(raw.encode("utf-8"))) == "Corps réel."


def test_base64_body_is_decoded() -> None:
    encoded = base64.b64encode("Invitation à l'entretien.".encode()).decode("ascii")
    raw = (
        'Content-Type: text/plain; charset="utf-8"\n'
        "Content-Transfer-Encoding: base64\n"
        "\n"
        f"{encoded}\n"
    )
    assert gmail_module._body_text(_parse(raw.encode("ascii"))) == "Invitation à l'entretien."


def test_unknown_charset_falls_back_to_utf8() -> None:
    raw = b'Content-Type: text/plain; charset="x-inexistant"\n\nOk \xc3\xa9t\xc3\xa9\n'
    assert gmail_module._body_text(_parse(raw)) == "Ok été"


def test_body_is_truncated() -> None:
    raw = b'Content-Type: text/plain; charset="utf-8"\n\n' + b"a" * 2_000
    assert len(gmail_module._body_text(_parse(raw))) == gmail_module.MAX_BODY_CHARS


def test_exotic_header_never_raises() -> None:
    assert gmail_module._decode_header(None) == ""
    assert gmail_module._decode_header("=?utf-8?B?!!pas-du-base64?=") != ""


def test_received_at_falls_back_and_attaches_utc() -> None:
    invalid = gmail_module._received_at(_parse(b"Date: pas une date\n\ncorps"))
    assert invalid.tzinfo is not None

    naive = gmail_module._received_at(_parse(b"Date: Thu, 22 Oct 2026 10:00:00\n\ncorps"))
    assert naive.tzinfo == UTC
    assert naive.year == 2026

    missing = gmail_module._received_at(_parse(b"Subject: sans date\n\ncorps"))
    assert missing.tzinfo is not None


def test_fetch_bytes_handles_literal_and_errors() -> None:
    class _Client:
        def __init__(self, response):
            self.response = response

        def uid(self, command, *args):
            return self.response

    assert gmail_module._fetch_bytes(
        _Client(("OK", [(b"1 (BODY[] {5}", b"hello"), b")"])), 1, "BODY[]"
    ) == b"hello"
    assert gmail_module._fetch_bytes(_Client(("OK", [b"raw"])), 1, "BODY[]") == b"raw"
    assert gmail_module._fetch_bytes(_Client(("NO", [])), 1, "BODY[]") is None


def test_login_failure_is_explained_without_leaking_password(monkeypatch) -> None:
    class _Rejecting:
        def __init__(self, *args, **kwargs):
            pass

        def login(self, address, password):
            raise imaplib.IMAP4.error("Invalid credentials")

        def shutdown(self):
            pass

    monkeypatch.setattr(gmail_module.imaplib, "IMAP4_SSL", _Rejecting)
    with pytest.raises(gmail_module.MailboxError) as excinfo:
        gmail_module._connect("camille@gmail.com", "abcd efgh ijkl mnop", "imap.gmail.com", 993)
    assert "mot de passe d'application" in str(excinfo.value)
    assert "abcd" not in str(excinfo.value)


class _FakeIMAP:
    """Serveur IMAP minimal : deux messages sans Message-ID."""

    def __init__(self, headers: list[bytes], bodies: list[bytes]) -> None:
        self.headers = headers
        self.bodies = bodies
        self.searches: list[str] = []

    def select(self, folder: str, readonly: bool = True):
        return "OK", [b"2"]

    def uid(self, command: str, *args):
        if command == "search":
            self.searches.append(args[-1])
            return "OK", [b"2 1"]
        uid = int(args[0])
        payload = self.headers[uid - 1] if "HEADER" in args[1] else self.bodies[uid - 1]
        return "OK", [(f"1 (BODY[] {{{len(payload)}}}".encode(), payload), b")"]

    def logout(self) -> None:
        return None


def test_fetch_messages_synthesizes_ids_and_honours_limit(settings, monkeypatch) -> None:
    headers = [
        (
            "From: Acme <rh@acme.example>\n"
            f"Subject: Entretien {index}\n"
            "Date: Thu, 22 Oct 2026 10:00:00 +0000\n\n"
        ).encode()
        for index in (1, 2)
    ]
    bodies = [header + b"Bonjour, quelles sont vos disponibilites ?" for header in headers]
    client = _FakeIMAP(headers, bodies)
    monkeypatch.setattr(gmail_module, "_connect", lambda *args, **kwargs: client)

    messages = gmail_module.fetch_messages(
        address="camille@gmail.com",
        password="abcd efgh ijkl mnop",
        settings=settings,
        known_ids=set(),
    )
    assert {message.remote_id for message in messages} == {
        "imap:camille@gmail.com:INBOX:1",
        "imap:camille@gmail.com:INBOX:2",
    }
    assert all("disponibilites" in message.body for message in messages)
    assert client.searches and client.searches[0].startswith('(SINCE "')

    limited = gmail_module.fetch_messages(
        address="camille@gmail.com",
        password="abcd efgh ijkl mnop",
        settings=settings,
        known_ids=set(),
        limit=1,
    )
    assert [message.remote_id for message in limited] == ["imap:camille@gmail.com:INBOX:2"]

    skipped = gmail_module.fetch_messages(
        address="camille@gmail.com",
        password="abcd efgh ijkl mnop",
        settings=settings,
        known_ids={"imap:camille@gmail.com:INBOX:2"},
    )
    assert [message.remote_id for message in skipped] == ["imap:camille@gmail.com:INBOX:1"]
