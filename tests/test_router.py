from __future__ import annotations

import httpx
import pytest

from applyflow.config import RouterConfig
from applyflow.matching.laya_router import LayaRouter, RemoteRouter
from applyflow.matching.router import (
    DeterministicRouter,
    FallbackRouter,
    RouterUnavailable,
)
from applyflow.matching.types import ProfileSnapshot
from applyflow.schemas import NormalizedJob


def _profile(profile_id: str, name: str, titles: list[str], skills: list[str]) -> ProfileSnapshot:
    return ProfileSnapshot(
        id=profile_id,
        name=name,
        target_titles=titles,
        technical_skills=skills,
        experience_level="junior",
        years_experience=2,
        locations=["France"],
        contract_types=["CDI"],
        remote_preferences=["hybrid"],
        resume_id=f"resume-{profile_id}",
    )


@pytest.fixture()
def profiles() -> list[ProfileSnapshot]:
    return [
        _profile(
            "ai",
            "AI Engineer",
            ["AI Engineer", "Machine Learning Engineer"],
            ["Python", "PyTorch", "LLM", "NLP", "FastAPI"],
        ),
        _profile(
            "de",
            "Data Engineer",
            ["Data Engineer", "Analytics Engineer"],
            ["Python", "SQL", "Airflow", "dbt", "Snowflake"],
        ),
        _profile(
            "ba",
            "BI Analyst",
            ["Data Analyst", "BI Analyst"],
            ["SQL", "Power BI", "Tableau", "Excel"],
        ),
    ]


@pytest.fixture()
def ai_job() -> NormalizedJob:
    return NormalizedJob(
        source_kind="fixture",
        url="https://example.invalid/ai",
        company="MediMind",
        title="AI Engineer (Junior)",
        description="Python, PyTorch et LLM. Paris, hybride, CDI.",
        location="Paris, France",
        remote="hybrid",
        skills=["Python", "PyTorch", "LLM", "NLP"],
    )


def test_deterministic_router_selects_best_profile(profiles, ai_job) -> None:
    decision = DeterministicRouter().route(ai_job, profiles)
    assert decision.profile_id == "ai"
    assert decision.resume_id == "resume-ai"
    assert 0 <= decision.confidence <= 1
    assert decision.candidates[0].score >= decision.candidates[1].score
    assert any("intitulé" in reason for reason in decision.reasons)


def test_router_confidence_is_not_fit_score(profiles, ai_job) -> None:
    decision = DeterministicRouter().route(ai_job, profiles)
    # La confiance mesure la séparation entre profils, pas la qualité de l'offre.
    assert decision.confidence != decision.candidates[0].score
    assert decision.candidates[0].score <= 1
    assert decision.uncertain is False


def test_router_without_profiles_raises(ai_job) -> None:
    with pytest.raises(RouterUnavailable):
        DeterministicRouter().route(ai_job, [])


def test_fallback_router_uses_deterministic(profiles, ai_job) -> None:
    class Broken:
        name = "broken"

        def route(self, job, candidates):
            raise RouterUnavailable("moteur injoignable")

    decision = FallbackRouter(Broken(), DeterministicRouter()).route(ai_job, profiles)
    assert decision.profile_id == "ai"
    assert "fallback" in decision.router
    assert decision.reasons[0].startswith("Fallback")


def test_remote_router_contract(profiles, ai_job) -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["contract"] = request.headers.get("X-ApplyFlow-Contract")
        seen["payload"] = request.read()
        return httpx.Response(
            200,
            json={
                "profile_id": "ai",
                "resume_id": "resume-ai",
                "confidence": 0.72,
                "reasons": ["adaptateur local"],
            },
        )

    config = RouterConfig(provider="remote", remote_route_url="http://adapter.local/route")
    router = RemoteRouter(config, transport=httpx.MockTransport(handler))
    decision = router.route(ai_job, profiles)
    assert seen["contract"] == "applyflow.route.v1"
    assert decision.profile_id == "ai"
    assert decision.confidence == 0.72


def test_remote_router_rejects_unknown_profile(profiles, ai_job) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"profile_id": "ghost", "confidence": 0.9})

    config = RouterConfig(provider="remote", remote_route_url="http://adapter.local/route")
    router = RemoteRouter(config, transport=httpx.MockTransport(handler))
    with pytest.raises(RouterUnavailable):
        router.route(ai_job, profiles)


def test_remote_router_without_endpoint_raises(profiles, ai_job) -> None:
    router = RemoteRouter(RouterConfig(provider="remote"))
    with pytest.raises(RouterUnavailable):
        router.route(ai_job, profiles)


def test_laya_reports_missing_cv_routing_api(profiles, ai_job) -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(f"{request.method} {request.url.path}")
        if request.url.path == "/health":
            return httpx.Response(200, json={"status": "ok"})
        return httpx.Response(404)

    config = RouterConfig(provider="laya", laya_base_url="http://laya.local")
    router = LayaRouter(config, transport=httpx.MockTransport(handler))
    with pytest.raises(RouterUnavailable, match="routeur|routage"):
        router.route(ai_job, profiles)
    assert calls == ["GET /health"]


def test_laya_adapter_route_when_configured(profiles, ai_job) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/health":
            return httpx.Response(200, json={"status": "ok"})
        return httpx.Response(200, json={"profile_id": "de", "confidence": 0.6})

    config = RouterConfig(
        provider="laya",
        laya_base_url="http://laya.local",
        remote_route_url="http://adapter.local/route",
    )
    router = LayaRouter(config, transport=httpx.MockTransport(handler))
    decision = router.route(ai_job, profiles)
    assert decision.profile_id == "de"
    assert decision.router == "laya"
    assert any("adaptateur" in reason for reason in decision.reasons)
