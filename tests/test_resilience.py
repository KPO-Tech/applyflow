from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx
import pytest

from applyflow.config import DiscoveryConfig, Settings
from applyflow.providers import build_provider
from applyflow.providers.base import ProviderError
from applyflow.providers.http_providers import GreenhouseProvider, RssProvider
from applyflow.providers.resilience import Pacer, RetryPolicy, retry_after_seconds
from applyflow.schemas import JobQuery

FEED = """<?xml version="1.0"?>
<rss version="2.0"><channel><title>Flux</title>
<item><title>Data Engineer</title><link>https://example.invalid/job/1</link>
<description>Python, SQL, télétravail</description></item>
</channel></rss>"""


def _greenhouse_body() -> dict:
    return {
        "jobs": [
            {
                "id": 7,
                "title": "Junior Data Engineer",
                "absolute_url": "https://boards.greenhouse.io/acme/jobs/7",
                "location": {"name": "Paris, France"},
                "content": "Python, SQL",
            }
        ]
    }


class _Counter:
    def __init__(self, statuses: list[int]) -> None:
        self.statuses = statuses
        self.calls = 0

    def __call__(self, request: httpx.Request) -> httpx.Response:
        status = self.statuses[min(self.calls, len(self.statuses) - 1)]
        self.calls += 1
        if status == 200:
            return httpx.Response(200, json=_greenhouse_body())
        return httpx.Response(status)


def test_transient_failure_is_retried_and_recovers() -> None:
    calls = _Counter([503, 200])
    naps: list[float] = []
    provider = GreenhouseProvider(
        "acme",
        transport=httpx.MockTransport(calls),
        retry_attempts=3,
        retry_base_seconds=1.0,
        sleep=naps.append,
    )
    jobs = provider.fetch(JobQuery(limit=5))
    assert len(jobs) == 1
    assert calls.calls == 2
    assert len(naps) == 1
    assert 0.7 <= naps[0] <= 1.3  # 1 s, plus ou moins l'aléa


def test_transient_failure_gives_up_after_configured_attempts() -> None:
    calls = _Counter([502])
    naps: list[float] = []
    provider = GreenhouseProvider(
        "acme",
        transport=httpx.MockTransport(calls),
        retry_attempts=3,
        retry_base_seconds=2.0,
        sleep=naps.append,
    )
    with pytest.raises(ProviderError, match="Greenhouse indisponible"):
        provider.fetch(JobQuery(limit=5))
    assert calls.calls == 3
    assert len(naps) == 2  # pas d'attente après le dernier essai


def test_permanent_error_is_not_retried() -> None:
    calls = _Counter([404])
    naps: list[float] = []
    provider = GreenhouseProvider(
        "acme", transport=httpx.MockTransport(calls), retry_attempts=4, sleep=naps.append
    )
    with pytest.raises(ProviderError):
        provider.fetch(JobQuery(limit=5))
    assert calls.calls == 1
    assert naps == []


def test_rate_limited_status_is_retried() -> None:
    calls = _Counter([429, 200])
    naps: list[float] = []
    provider = GreenhouseProvider(
        "acme", transport=httpx.MockTransport(calls), sleep=naps.append
    )
    assert provider.fetch(JobQuery(limit=5))
    assert calls.calls == 2
    assert len(naps) == 1


def test_backoff_doubles_and_stops_at_the_cap() -> None:
    policy = RetryPolicy(attempts=8, base_seconds=1.0, max_seconds=20.0, jitter=0.0)
    delays = [policy.wait_seconds(attempt) for attempt in range(1, 7)]
    assert delays == [1.0, 2.0, 4.0, 8.0, 16.0, 20.0]


def test_retry_after_header_wins_over_the_backoff() -> None:
    policy = RetryPolicy(base_seconds=1.0, max_seconds=20.0)
    response = httpx.Response(429, headers={"retry-after": "7"})
    assert policy.wait_seconds(1, response) == 7.0
    capped = httpx.Response(429, headers={"retry-after": "900"})
    assert policy.wait_seconds(1, capped) == 20.0


def test_retry_after_accepts_an_http_date() -> None:
    moment = datetime.now(UTC) + timedelta(seconds=30)
    response = httpx.Response(503, headers={"retry-after": moment.strftime("%a, %d %b %Y %H:%M:%S GMT")})
    value = retry_after_seconds(response)
    assert value is not None
    assert 25 <= value <= 35
    assert retry_after_seconds(httpx.Response(503)) is None
    assert retry_after_seconds(httpx.Response(503, headers={"retry-after": "soon"})) is None


def test_pacer_spaces_requests_per_host() -> None:
    now = {"t": 100.0}
    naps: list[float] = []

    def clock() -> float:
        return now["t"]

    def sleep(seconds: float) -> None:
        naps.append(seconds)
        now["t"] += seconds

    pacer = Pacer(2.0, sleep=sleep, clock=clock)
    assert pacer.wait("example.invalid") == 0.0
    assert pacer.wait("example.invalid") == 2.0
    assert pacer.wait("autre.invalid") == 0.0  # un autre hôte n'attend pas
    assert naps == [2.0]


def test_rss_feeds_on_the_same_host_are_paced() -> None:
    naps: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=FEED, headers={"content-type": "application/rss+xml"})

    provider = RssProvider(
        ["https://example.invalid/a.xml", "https://example.invalid/b.xml"],
        delay_seconds=2.0,
        transport=httpx.MockTransport(handler),
        sleep=naps.append,
    )
    jobs = provider.fetch(JobQuery(limit=10))
    assert len(jobs) == 2
    assert len(naps) == 1
    assert 1.5 <= naps[0] <= 2.01  # l'intervalle est mesuré sur l'horloge réelle


def test_registry_passes_retry_settings_to_connectors() -> None:
    settings = Settings(discovery=DiscoveryConfig(retry_attempts=5, retry_base_seconds=0.5))
    provider = build_provider(
        {"kind": "greenhouse", "config": {"board_token": "acme"}}, settings=settings
    )
    assert isinstance(provider, GreenhouseProvider)
    assert provider.retry.attempts == 5
    assert provider.retry.base_seconds == 0.5
    # La configuration de la source garde la priorité sur le réglage global.
    override = build_provider(
        {"kind": "greenhouse", "config": {"board_token": "acme", "retry_attempts": 2}},
        settings=settings,
    )
    assert override.retry.attempts == 2


@pytest.mark.parametrize(
    "overrides",
    [
        {"retry_attempts": 0},
        {"retry_attempts": 11},
        {"retry_base_seconds": -1},
        {"retry_base_seconds": 5.0, "retry_max_seconds": 2.0},
    ],
)
def test_invalid_retry_settings_are_rejected(overrides: dict) -> None:
    with pytest.raises(ValueError):
        DiscoveryConfig(**overrides)
