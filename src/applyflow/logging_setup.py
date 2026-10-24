"""Journalisation structurée (JSON ou texte) pour toutes les opérations."""

from __future__ import annotations

import json
import logging
import sys
from datetime import UTC, datetime
from typing import Any

_CONFIGURED = False


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.now(UTC).isoformat(timespec="seconds"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        data = getattr(record, "data", None)
        if isinstance(data, dict) and data:
            payload["data"] = data
        if record.exc_info:
            payload["error"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, default=str)


class TextFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        base = super().format(record)
        data = getattr(record, "data", None)
        if isinstance(data, dict) and data:
            extras = " ".join(f"{key}={value}" for key, value in data.items())
            return f"{base} | {extras}"
        return base


def configure_logging(level: str = "INFO", json_output: bool = False) -> None:
    global _CONFIGURED
    root = logging.getLogger("applyflow")
    root.setLevel(level.upper())
    root.handlers.clear()
    root.propagate = False
    handler = logging.StreamHandler(sys.stderr)
    if json_output:
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(TextFormatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s"))
    root.addHandler(handler)
    _CONFIGURED = True


def get_logger(name: str) -> logging.Logger:
    if not _CONFIGURED:
        configure_logging()
    return logging.getLogger(f"applyflow.{name}")


def log_event(logger: logging.Logger, message: str, **data: Any) -> None:
    logger.info(message, extra={"data": data})


def audit_event(logger: logging.Logger, action: str, **data: Any) -> None:
    logger.info(f"audit:{action}", extra={"data": {"action": action, **data}})
