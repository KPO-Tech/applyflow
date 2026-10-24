"""Connexion SQLite, sessions et exécution des migrations Alembic."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from applyflow.logging_setup import get_logger

MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"
logger = get_logger("db")


class Database:
    """Petit conteneur de connexion, sans état global."""

    def __init__(self, url: str, *, echo: bool = False) -> None:
        self.url = url
        connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
        self.engine = create_engine(url, echo=echo, future=True, connect_args=connect_args)
        if url.startswith("sqlite"):

            @event.listens_for(self.engine, "connect")
            def _fk_pragma(dbapi_connection, _record):  # pragma: no cover - trivial
                cursor = dbapi_connection.cursor()
                cursor.execute("PRAGMA foreign_keys=ON")
                cursor.close()

        self._session_factory = sessionmaker(bind=self.engine, expire_on_commit=False)

    @contextmanager
    def session(self) -> Iterator[Session]:
        session = self._session_factory()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def init_schema(self) -> None:
        """Applique toutes les migrations Alembic (idempotent)."""
        config = Config()
        config.set_main_option("script_location", str(MIGRATIONS_DIR))
        config.set_main_option("sqlalchemy.url", self.url)
        command.upgrade(config, "head")
        logger.info("schéma à jour", extra={"data": {"url": self.url}})

    def dispose(self) -> None:
        self.engine.dispose()
