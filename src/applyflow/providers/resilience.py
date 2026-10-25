"""Nouvelles tentatives et débit par source pour les connecteurs HTTP.

Deux garde-fous, appliqués aux seules requêtes de lecture :

* `RetryPolicy` : une erreur passagère (timeout, connexion coupée, 429, 5xx) est retentée
  avec un repli exponentiel et un peu d'aléa ; l'en-tête `Retry-After` est respecté. Une
  erreur définitive (404, 403…) n'est jamais retentée.
* `Pacer` : intervalle minimal entre deux requêtes vers un même hôte, pour ne pas envoyer
  de rafale quand un connecteur lit plusieurs pages ou plusieurs flux.
"""

from __future__ import annotations

import random
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any

import httpx

from applyflow.logging_setup import get_logger

logger = get_logger("providers")

#: Statuts propres à un incident passager. Les autres 4xx sont définitifs.
TRANSIENT_STATUSES = frozenset({408, 425, 429, 500, 502, 503, 504})


@dataclass(frozen=True)
class RetryPolicy:
    """Combien de fois insister, et avec quel délai entre deux essais."""

    attempts: int = 3
    base_seconds: float = 1.0
    max_seconds: float = 20.0
    jitter: float = 0.25

    def __post_init__(self) -> None:
        if self.attempts < 1:
            raise ValueError("au moins une tentative est nécessaire")
        if self.base_seconds < 0 or self.max_seconds < 0:
            raise ValueError("les délais de repli ne peuvent pas être négatifs")

    def wait_seconds(
        self,
        attempt: int,
        response: httpx.Response | None = None,
        *,
        rng: random.Random | None = None,
    ) -> float:
        """Délai avant le prochain essai, après `attempt` échecs (1 = premier échec)."""
        hinted = retry_after_seconds(response)
        if hinted is not None:
            return min(self.max_seconds, hinted)
        delay = min(self.max_seconds, self.base_seconds * 2 ** max(0, attempt - 1))
        if self.jitter and delay:
            generator = rng or random
            spread = delay * self.jitter
            delay = max(0.0, delay + generator.uniform(-spread, spread))
        return delay


def retry_after_seconds(response: httpx.Response | None) -> float | None:
    """`Retry-After` en secondes (nombre ou date HTTP), ou None s'il est absent."""
    if response is None:
        return None
    raw = (response.headers.get("retry-after") or "").strip()
    if not raw:
        return None
    try:
        return max(0.0, float(raw))
    except ValueError:
        pass
    try:
        moment = parsedate_to_datetime(raw)
    except (TypeError, ValueError):
        return None
    if moment is None:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    return max(0.0, (moment - datetime.now(UTC)).total_seconds())


class Pacer:
    """Intervalle minimal entre deux requêtes vers un même hôte (thread-safe)."""

    def __init__(
        self,
        min_seconds: float = 0.0,
        *,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.min_seconds = max(0.0, float(min_seconds))
        self._sleep = sleep
        self._clock = clock
        self._last: dict[str, float] = {}
        self._lock = threading.Lock()

    def wait(self, key: str = "") -> float:
        """Attend si besoin, puis enregistre l'heure de la requête ; rend l'attente réelle."""
        if self.min_seconds <= 0:
            return 0.0
        with self._lock:
            last = self._last.get(key)
            delay = 0.0 if last is None else max(0.0, self.min_seconds - (self._clock() - last))
            if delay > 0:
                self._sleep(delay)
            self._last[key] = self._clock()
            return delay


def request_with_retry(
    client: httpx.Client,
    method: str,
    url: str,
    *,
    policy: RetryPolicy | None = None,
    pacer: Pacer | None = None,
    sleep: Callable[[float], None] = time.sleep,
    rng: random.Random | None = None,
    **kwargs: Any,
) -> httpx.Response:
    """Requête idempotente (GET) avec repli exponentiel ; relance l'erreur finale.

    À l'épuisement des tentatives, l'exception `httpx` d'origine remonte : l'appelant la
    traduit en `ProviderError` avec le contexte de sa source.
    """
    policy = policy or RetryPolicy()
    error: httpx.HTTPError | None = None
    for attempt in range(1, policy.attempts + 1):
        if pacer is not None:
            pacer.wait(httpx.URL(url).host)
        response: httpx.Response | None = None
        try:
            response = client.request(method, url, **kwargs)
            response.raise_for_status()
            return response
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code not in TRANSIENT_STATUSES:
                raise
            error, response = exc, exc.response
        except httpx.TransportError as exc:  # timeout, connexion coupée, DNS
            error = exc
        if attempt < policy.attempts:
            delay = policy.wait_seconds(attempt, response, rng=rng)
            logger.warning(
                "erreur passagère, nouvelle tentative",
                extra={
                    "data": {
                        "url": url,
                        "attempt": attempt,
                        "status": response.status_code if response is not None else None,
                        "delay_seconds": round(delay, 2),
                    }
                },
            )
            sleep(delay)
    if error is None:  # pragma: no cover - attempts >= 1 garantit une sortie par le haut
        raise RuntimeError("requête sans tentative")
    raise error
