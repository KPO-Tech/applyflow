"""Adaptateur Laya / HTTP pour le routage des CV.

Constat vérifié le 2026-10-23 sur https://github.com/aayushch/laya : Laya est un
« centre de notifications IA local » (Slack, Gmail, GitHub, Jira...) qui expose un
moteur local FastAPI (`/health`, `/events`, cartes d'action). Ce n'est pas un routeur
de CV et aucune API de sélection de CV n'est documentée. ApplyFlow ne prétend donc
pas appeler une API inexistante :

* `LayaRouter` vérifie d'abord le moteur Laya via `GET /health` (endpoint documenté) ;
* puis délègue le routage à un **adaptateur local** optionnel (`router.remote_route_url`)
  qui implémente le contrat ApplyFlow décrit dans docs/laya.md.
* Sans adaptateur configuré, le routeur lève `RouterUnavailable` et ApplyFlow bascule
  sur le routeur déterministe, sans interrompre la campagne.
"""

from __future__ import annotations

from typing import Any

import httpx
from pydantic import BaseModel, Field, ValidationError

from applyflow.config import RouterConfig
from applyflow.matching.router import RouterUnavailable
from applyflow.matching.types import ProfileSnapshot, RouteCandidate, RouterDecision

ROUTE_CONTRACT_VERSION = "applyflow.route.v1"


class RemoteRouteResponse(BaseModel):
    profile_id: str
    resume_id: str | None = None
    confidence: float = Field(default=0.5, ge=0, le=1)
    reasons: list[str] = Field(default_factory=list)
    uncertain: bool = False


class RemoteRouter:
    """Appelle un endpoint local qui respecte le contrat `applyflow.route.v1`."""

    name = "remote"

    def __init__(
        self,
        config: RouterConfig,
        *,
        name: str | None = None,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.config = config
        self.name = name or self.name
        self._transport = transport

    def _client(self) -> httpx.Client:
        return httpx.Client(
            timeout=self.config.timeout_seconds,
            transport=self._transport,
            headers={"User-Agent": "ApplyFlow/0.1"},
        )

    def _check_engine(self) -> None:
        """Aucune vérification pour le routeur HTTP générique."""

    def _endpoint(self) -> str:
        endpoint = (self.config.remote_route_url or "").strip()
        if not endpoint:
            raise RouterUnavailable(
                "aucun endpoint de routage configuré (router.remote_route_url)"
            )
        return endpoint

    def route(self, job: Any, profiles: list[ProfileSnapshot]) -> RouterDecision:
        if not profiles:
            raise RouterUnavailable("aucun profil actif disponible pour le routage")
        self._check_engine()
        endpoint = self._endpoint()
        payload = {
            "contract": ROUTE_CONTRACT_VERSION,
            "job": {
                "title": getattr(job, "title", ""),
                "description": getattr(job, "description", "") or "",
                "company": getattr(job, "company", "") or "",
                "location": getattr(job, "location", None),
                "remote": getattr(job, "remote", None),
                "contract_type": getattr(job, "contract_type", None),
                "skills": list(
                    getattr(job, "skills", None) or getattr(job, "required_skills", None) or []
                ),
            },
            "profiles": [profile.model_dump() for profile in profiles],
        }
        headers = {"X-ApplyFlow-Contract": ROUTE_CONTRACT_VERSION}
        try:
            with self._client() as client:
                response = client.post(endpoint, json=payload, headers=headers)
                response.raise_for_status()
                data = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise RouterUnavailable(f"routeur {self.name} injoignable : {exc}") from exc

        try:
            parsed = RemoteRouteResponse.model_validate(data)
        except ValidationError as exc:
            raise RouterUnavailable(f"réponse de routage invalide : {exc}") from exc

        profile_by_id = {profile.id: profile for profile in profiles}
        if parsed.profile_id not in profile_by_id:
            raise RouterUnavailable(
                f"profil inconnu renvoyé par le routeur : {parsed.profile_id}"
            )
        chosen = profile_by_id[parsed.profile_id]
        candidates = [
            RouteCandidate(
                profile_id=profile.id,
                profile_name=profile.name,
                resume_id=profile.resume_id,
                resume_filename=profile.resume_filename,
                score=1.0 if profile.id == parsed.profile_id else 0.0,
                reasons=["choix du routeur distant"],
            )
            for profile in profiles
        ]
        reasons = [
            f"routage {self.name} via adaptateur local (contrat {ROUTE_CONTRACT_VERSION})",
            *parsed.reasons,
        ]
        if chosen.resume_id is None:
            reasons.append("aucun CV actif associé au profil choisi")
        return RouterDecision(
            profile_id=chosen.id,
            resume_id=chosen.resume_id,
            router=self.name,
            confidence=parsed.confidence,
            reasons=reasons,
            uncertain=parsed.uncertain,
            candidates=candidates,
        )


class LayaRouter(RemoteRouter):
    """Santé du moteur Laya + délégation à un adaptateur de routage local."""

    name = "laya"

    def _check_engine(self) -> None:
        base = (self.config.laya_base_url or "").rstrip("/")
        if not base:
            raise RouterUnavailable("router.laya_base_url non configuré")
        headers = {"User-Agent": "ApplyFlow/0.1"}
        if self.config.laya_token:
            headers["Authorization"] = f"Bearer {self.config.laya_token}"
        try:
            with self._client() as client:
                response = client.get(f"{base}/health", headers=headers)
                response.raise_for_status()
        except httpx.HTTPError as exc:
            raise RouterUnavailable(f"moteur Laya injoignable ({base}/health) : {exc}") from exc

        if not (self.config.remote_route_url or "").strip():
            raise RouterUnavailable(
                "le moteur Laya ne fournit pas d'API de routage de CV ; "
                "configurez router.remote_route_url avec un adaptateur local "
                "(voir docs/laya.md)"
            )
