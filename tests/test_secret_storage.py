"""Le mot de passe Gmail va dans le trousseau du système, pas dans un fichier en clair."""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import UTC, datetime

import keyring
import pytest
from keyring.backend import KeyringBackend

from applyflow.config import Settings
from applyflow.email.account import (
    credentials_path,
    delete_credentials,
    load_credentials,
    mark_synced,
    save_credentials,
    secret_storage,
)

PASSWORD = "abcd efgh ijkl mnop"
CLEAN = "abcdefghijklmnop"


class InMemoryKeyring(KeyringBackend):
    priority = 1

    def __init__(self) -> None:
        super().__init__()
        self.items: dict[tuple[str, str], str] = {}

    def set_password(self, service: str, username: str, password: str) -> None:
        self.items[(service, username)] = password

    def get_password(self, service: str, username: str) -> str | None:
        return self.items.get((service, username))

    def delete_password(self, service: str, username: str) -> None:
        self.items.pop((service, username), None)


@pytest.fixture()
def vault(monkeypatch: pytest.MonkeyPatch) -> Iterator[InMemoryKeyring]:
    previous = keyring.get_keyring()
    backend = InMemoryKeyring()
    keyring.set_keyring(backend)
    monkeypatch.delenv("APPLYFLOW_NO_KEYRING", raising=False)
    yield backend
    keyring.set_keyring(previous)


def test_password_is_stored_in_keyring_not_in_the_file(settings: Settings, vault) -> None:
    save_credentials(settings, address="camille@gmail.com", password=PASSWORD)
    raw = credentials_path(settings).read_text(encoding="utf-8")
    assert CLEAN not in raw and "password" not in json.loads(raw)
    assert vault.items[("ApplyFlow", "camille@gmail.com")] == CLEAN
    assert secret_storage(settings) == "keyring"
    credentials = load_credentials(settings)
    assert credentials is not None and credentials["password"] == CLEAN


def test_sync_bookkeeping_never_writes_the_secret_back(settings: Settings, vault) -> None:
    save_credentials(settings, address="camille@gmail.com", password=PASSWORD)
    mark_synced(settings, at=datetime(2026, 10, 23, tzinfo=UTC), summary={"created": 2})
    raw = credentials_path(settings).read_text(encoding="utf-8")
    assert CLEAN not in raw
    assert json.loads(raw)["last_sync"] == {"created": 2}
    assert load_credentials(settings)["password"] == CLEAN  # type: ignore[index]


def test_legacy_plaintext_file_is_migrated(settings: Settings, vault) -> None:
    path = credentials_path(settings)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"provider": "gmail", "address": "camille@gmail.com", "password": CLEAN}),
        encoding="utf-8",
    )
    credentials = load_credentials(settings)
    assert credentials is not None and credentials["password"] == CLEAN
    assert CLEAN not in path.read_text(encoding="utf-8")  # le fichier n'a plus le secret
    assert vault.items[("ApplyFlow", "camille@gmail.com")] == CLEAN
    assert secret_storage(settings) == "keyring"


def test_entry_removed_from_keyring_means_reconnect(settings: Settings, vault) -> None:
    save_credentials(settings, address="camille@gmail.com", password=PASSWORD)
    vault.items.clear()
    assert load_credentials(settings) is None


def test_delete_removes_secret_everywhere(settings: Settings, vault) -> None:
    save_credentials(settings, address="camille@gmail.com", password=PASSWORD)
    assert delete_credentials(settings) is True
    assert not credentials_path(settings).exists() and vault.items == {}


def test_falls_back_to_file_when_keyring_is_disabled(settings: Settings) -> None:
    # `APPLYFLOW_NO_KEYRING=1` est posé par la fixture automatique des tests.
    save_credentials(settings, address="camille@gmail.com", password=PASSWORD)
    assert secret_storage(settings) == "file"
    assert json.loads(credentials_path(settings).read_text(encoding="utf-8"))["password"] == CLEAN
    assert load_credentials(settings)["password"] == CLEAN  # type: ignore[index]


def test_locked_keyring_falls_back_instead_of_failing(settings: Settings, vault) -> None:
    def locked(*_args: object) -> None:
        raise RuntimeError("trousseau verrouillé")

    vault.set_password = locked  # type: ignore[method-assign]
    save_credentials(settings, address="camille@gmail.com", password=PASSWORD)
    assert secret_storage(settings) == "file"
    assert load_credentials(settings)["password"] == CLEAN  # type: ignore[index]


def test_email_status_reports_where_the_secret_lives(api_client, settings: Settings, vault) -> None:
    save_credentials(settings, address="camille@gmail.com", password=PASSWORD)
    status = api_client.get("/email/status").json()
    assert status["connected"] is True and status["secret_storage"] == "keyring"
    assert CLEAN not in json.dumps(status)
