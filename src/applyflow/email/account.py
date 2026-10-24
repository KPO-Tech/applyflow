"""Identifiants de la boîte mail, jamais exposés par l'API.

Le mot de passe d'application est rangé dans le trousseau du système (Gestionnaire d'identifiants
Windows, Trousseau macOS, Secret Service sous Linux). Le fichier `data/secrets/gmail.json` ne
contient alors que l'adresse et l'état de synchronisation. Sans trousseau utilisable (serveur sans
interface, par exemple) ou si `APPLYFLOW_NO_KEYRING=1`, le mot de passe reste dans ce fichier,
avec les permissions les plus restrictives possibles : `secret_storage` l'indique.
"""

from __future__ import annotations

import contextlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from applyflow.config import Settings
from applyflow.logging_setup import get_logger

CREDENTIALS_FILENAME = "gmail.json"
KEYRING_SERVICE = "ApplyFlow"
logger = get_logger("email.account")


def credentials_path(settings: Settings) -> Path:
    return Path(settings.app.data_dir) / "secrets" / CREDENTIALS_FILENAME


def normalize_password(raw: str) -> str:
    """Les mots de passe d'application Google sont affichés par groupes de quatre."""
    return "".join(str(raw or "").split())


def _keyring() -> Any | None:
    """Le module `keyring` si un trousseau réel est disponible, sinon None."""
    if os.environ.get("APPLYFLOW_NO_KEYRING", "").strip().lower() in {"1", "true", "yes"}:
        return None
    try:
        import keyring
        from keyring.backends import fail
    except ImportError:
        return None
    return None if isinstance(keyring.get_keyring(), fail.Keyring) else keyring


def _store_secret(address: str, password: str) -> bool:
    keyring = _keyring()
    if keyring is None:
        return False
    try:
        keyring.set_password(KEYRING_SERVICE, address, password)
    except Exception:  # trousseau verrouillé ou indisponible : repli sur le fichier
        logger.warning("trousseau indisponible, mot de passe conservé dans le fichier local")
        return False
    return True


def _read_secret(address: str) -> str | None:
    keyring = _keyring()
    if keyring is None:
        return None
    try:
        return keyring.get_password(KEYRING_SERVICE, address)
    except Exception:
        return None


def load_credentials(settings: Settings) -> dict[str, Any] | None:
    """Identifiants avec le mot de passe en mémoire. Migre un ancien fichier en clair."""
    path = credentials_path(settings)
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(payload, dict) or not payload.get("address"):
        return None
    address = str(payload["address"])
    if payload.get("secret_storage") == "keyring":
        password = _read_secret(address)
        if not password:
            return None  # entrée supprimée du trousseau : il faut se reconnecter
        return {**payload, "password": password}
    if not payload.get("password"):
        return None
    if _store_secret(address, str(payload["password"])):  # migration silencieuse du fichier ancien
        _write(path, {**payload, "secret_storage": "keyring"})
        logger.info("mot de passe Gmail déplacé vers le trousseau du système")
        payload["secret_storage"] = "keyring"
    else:
        payload.setdefault("secret_storage", "file")
    return payload


def secret_storage(settings: Settings) -> str | None:
    """`keyring`, `file` ou None (aucun compte)."""
    path = credentials_path(settings)
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(payload, dict):
        return None
    return "keyring" if payload.get("secret_storage") == "keyring" else "file"


def _write(path: Path, payload: dict[str, Any]) -> None:
    payload = dict(payload)
    if payload.get("secret_storage") == "keyring":
        payload.pop("password", None)  # ne jamais écrire le secret quand il est dans le trousseau
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    # Windows ne gère pas les permissions POSIX : sans trousseau, le fichier reste dans data/.
    with contextlib.suppress(OSError):
        os.chmod(temporary, 0o600)
    temporary.replace(path)


def save_credentials(settings: Settings, *, address: str, password: str) -> Path:
    path = credentials_path(settings)
    address = address.strip()
    password = normalize_password(password)
    in_keyring = _store_secret(address, password)
    payload: dict[str, Any] = {
        "provider": "gmail",
        "address": address,
        "secret_storage": "keyring" if in_keyring else "file",
        "saved_at": datetime.now(UTC).isoformat(),
        "last_sync_at": None,
        "last_sync": {},
    }
    if not in_keyring:
        payload["password"] = password
    _write(path, payload)
    return path


def mark_synced(settings: Settings, *, at: datetime, summary: dict[str, Any]) -> None:
    credentials = load_credentials(settings)
    if credentials is None:
        return
    credentials["last_sync_at"] = at.isoformat()
    credentials["last_sync"] = summary
    _write(credentials_path(settings), credentials)


def delete_credentials(settings: Settings) -> bool:
    path = credentials_path(settings)
    if not path.is_file():
        return False
    keyring = _keyring()
    if keyring is not None:
        with contextlib.suppress(Exception):
            payload = json.loads(path.read_text(encoding="utf-8"))
            keyring.delete_password(KEYRING_SERVICE, str(payload.get("address") or ""))
    try:
        path.unlink()
    except OSError:
        return False
    return True
