"""API locale FastAPI — même logique métier que le site local et la CLI."""

from __future__ import annotations

import importlib.util
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from fastapi import Body, Depends, FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from applyflow import __version__
from applyflow.api.serializers import (
    application_dict,
    attempt_dict,
    campaign_dict,
    campaign_job_dict,
    job_dict,
    profile_dict,
    resume_dict,
)
from applyflow.applications.answers import list_answers, upsert_answer
from applyflow.applications.preparer import (
    DuplicateApplication,
    PreparationError,
    SubmissionNotAllowed,
    approve_attempt,
    get_attempt,
    list_applications,
    list_attempts,
    prepare_attempt,
    record_submission,
    update_application_status,
)
from applyflow.campaign_tasks import CampaignBusy, CampaignManager
from applyflow.campaigns.schemas import CampaignInput
from applyflow.campaigns.service import (
    STEPS,
    CampaignError,
    cancel_campaign,
    create_campaign,
    get_campaign,
    list_campaigns,
    pause_campaign,
    resume_campaign,
    run_campaign,
)
from applyflow.collection_tasks import CollectionBusy, CollectionManager
from applyflow.config import Settings, load_settings, save_settings
from applyflow.contracts import contract_catalog
from applyflow.dashboard import campaign_stage_counts, dashboard_metrics
from applyflow.db import Database
from applyflow.db.models import CampaignJob, Job, Resume
from applyflow.email import (
    MailboxError,
    MailboxNotConnected,
    delete_credentials,
    email_status,
    followup_candidates,
    list_messages,
    load_credentials,
    mark_followed_up,
    save_credentials,
    serialize_messages,
    sync_mailbox,
    test_connection,
    update_message,
)
from applyflow.export import export_campaign
from applyflow.geo import country_catalog
from applyflow.jobs.service import (
    collect_jobs,
    count_jobs,
    count_jobs_by_country,
    ensure_source,
    get_job,
    ingest_jobs,
    list_jobs,
)
from applyflow.profiles.schemas import ProfileInput
from applyflow.profiles.service import (
    ResumeValidationError,
    create_profile,
    get_profile,
    list_profiles,
    set_active,
    update_profile,
    upload_resume,
)
from applyflow.providers import provider_catalog
from applyflow.providers.adzuna import AdzunaProvider
from applyflow.providers.base import ProviderError
from applyflow.providers.json_import import normalized_from_mapping
from applyflow.schemas import JobQuery
from applyflow.usage import UsageStore, usage_path

WEB_DIR = Path(__file__).resolve().parents[1] / "web"


def get_session(request: Request) -> Iterator[Session]:
    database: Database = request.app.state.database
    with database.session() as session:
        yield session


def _sync_campaign_stage(session: Session, attempt: Any) -> None:
    """La ligne de campagne suit l'état de la candidature (re-préparation, validation, soumission)."""
    if not attempt.campaign_id:
        return
    row = session.scalar(
        select(CampaignJob).where(
            CampaignJob.campaign_id == attempt.campaign_id, CampaignJob.job_id == attempt.job_id
        )
    )
    if row is not None:
        row.stage = attempt.status
        row.error = attempt.error


def _usage_store(settings: Settings) -> UsageStore:
    return UsageStore(usage_path(settings.app.data_dir), limits=settings.boards.daily_limits)


NO_CACHE = {"Cache-Control": "no-cache"}


def _assets_version() -> str:
    """Identifie la version des fichiers de l'interface (date de la dernière modification)."""
    newest = max((p.stat().st_mtime_ns for p in (WEB_DIR / "assets").rglob("*") if p.is_file()), default=0)
    return format(newest, "x")


class RevalidatedStaticFiles(StaticFiles):
    """Fichiers de l'interface : le navigateur les revérifie à chaque chargement (ETag, réponse
    304 sans retéléchargement). Sans cela, il garde d'anciens CSS/JS après une mise à jour."""

    async def get_response(self, path: str, scope: Any) -> Any:
        response = await super().get_response(path, scope)
        response.headers["Cache-Control"] = "no-cache"
        return response


class DiscoveryRequest(BaseModel):
    source: dict[str, Any] = Field(default_factory=lambda: {"kind": "fixture"})
    keywords: list[str] = Field(default_factory=list)
    locations: list[str] = Field(default_factory=list)
    limit: int = Field(default=200, ge=1, le=5000)


class RunCampaignRequest(BaseModel):
    steps: list[str] = Field(default_factory=lambda: list(STEPS))
    max_items: int | None = Field(default=None, ge=1)
    redo: bool = False  # réanalyse aussi les offres déjà notées (étape « analyze »)
    min_score: int | None = Field(default=None, ge=0, le=100)  # change le seuil de la campagne


class SubmitRequest(BaseModel):
    confirmed: bool = False
    reference: str | None = None


class AnswerInput(BaseModel):
    question_text: str = Field(min_length=1)
    answer: str = Field(min_length=1)
    approved: bool = True
    kind: str = "text"


class StatusInput(BaseModel):
    status: str


class EmailConnectInput(BaseModel):
    address: str = Field(min_length=3, max_length=255)
    password: str = Field(min_length=8, max_length=64)


class EmailMessageUpdate(BaseModel):
    application_id: str | None = None
    classification: str | None = None
    ignored: bool | None = None
    apply_status: bool = False


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or load_settings()
    settings.ensure_directories()
    database = Database(settings.database_url)
    database.init_schema()

    app = FastAPI(
        title="ApplyFlow",
        version=__version__,
        description="Gestion locale et explicable des candidatures.",
    )
    app.state.settings = settings
    app.state.database = database
    app.state.collections = CollectionManager()
    app.state.campaign_tasks = CampaignManager()

    if WEB_DIR.is_dir():
        app.mount("/assets", RevalidatedStaticFiles(directory=WEB_DIR / "assets"), name="assets")

        @app.get("/", include_in_schema=False)
        def ui_index() -> HTMLResponse:
            # Un numéro de version dans l'adresse des fichiers : après une mise à jour, le
            # navigateur ne peut plus réutiliser une ancienne copie en cache.
            version = _assets_version()
            html = (WEB_DIR / "index.html").read_text(encoding="utf-8")
            for name in ("styles.css", "app.js"):
                html = html.replace(f"/assets/{name}", f"/assets/{name}?v={version}")
            return HTMLResponse(html, headers=NO_CACHE)

    @app.middleware("http")
    async def _local_only_guard(request: Request, call_next: Any) -> Any:
        """Refuse les requêtes venues d'une autre page web ou d'un autre nom d'hôte.

        Une page quelconque ouverte dans votre navigateur peut envoyer des requêtes à
        127.0.0.1 : sans ce contrôle, elle pourrait lire vos CV ou lancer des collectes.
        """
        allowed = {host.lower() for host in request.app.state.settings.api.allowed_hosts}
        host_header = request.headers.get("host", "")
        if (urlsplit(f"//{host_header}").hostname or "").lower() not in allowed:
            return JSONResponse(
                status_code=403,
                content={"detail": "Hôte non autorisé (voir api.allowed_hosts dans la configuration)."},
            )
        origin = request.headers.get("origin")
        if origin is not None and urlsplit(origin).netloc.lower() != host_header.lower():
            return JSONResponse(
                status_code=403,
                content={"detail": "Requête refusée : elle ne vient pas de l'interface ApplyFlow."},
            )
        return await call_next(request)

    @app.exception_handler(CollectionBusy)
    async def _collection_busy(_request: Request, exc: CollectionBusy) -> JSONResponse:
        return JSONResponse(status_code=409, content={"detail": str(exc)})

    @app.exception_handler(CampaignBusy)
    async def _campaign_busy(_request: Request, exc: CampaignBusy) -> JSONResponse:
        return JSONResponse(status_code=409, content={"detail": str(exc)})

    @app.exception_handler(LookupError)
    async def _not_found(_request: Request, exc: LookupError) -> JSONResponse:
        return JSONResponse(status_code=404, content={"detail": str(exc)})

    @app.exception_handler(DuplicateApplication)
    async def _duplicate(_request: Request, exc: DuplicateApplication) -> JSONResponse:
        return JSONResponse(status_code=409, content={"detail": str(exc)})

    @app.exception_handler(SubmissionNotAllowed)
    async def _not_allowed(_request: Request, exc: SubmissionNotAllowed) -> JSONResponse:
        return JSONResponse(status_code=409, content={"detail": str(exc)})

    @app.exception_handler(PreparationError)
    async def _prep_error(_request: Request, exc: PreparationError) -> JSONResponse:
        return JSONResponse(status_code=409, content={"detail": str(exc)})

    @app.exception_handler(CampaignError)
    async def _campaign_error(_request: Request, exc: CampaignError) -> JSONResponse:
        return JSONResponse(status_code=409, content={"detail": str(exc)})

    @app.exception_handler(ResumeValidationError)
    async def _resume_error(_request: Request, exc: ResumeValidationError) -> JSONResponse:
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    @app.exception_handler(ValueError)
    async def _value_error(_request: Request, exc: ValueError) -> JSONResponse:
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    @app.exception_handler(MailboxError)
    async def _mailbox_error(_request: Request, exc: MailboxError) -> JSONResponse:
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    @app.exception_handler(MailboxNotConnected)
    async def _mailbox_missing(_request: Request, exc: MailboxNotConnected) -> JSONResponse:
        return JSONResponse(status_code=409, content={"detail": str(exc)})

    @app.get("/health")
    def health(request: Request) -> dict[str, Any]:
        with request.app.state.database.session() as session:
            jobs = count_jobs(session)
        return {"status": "ok", "version": __version__, "mode": "dry-run" if settings.application.dry_run else "live", "jobs": jobs}

    @app.get("/dashboard")
    def dashboard(session: Session = Depends(get_session)) -> dict[str, Any]:
        return dashboard_metrics(session)

    # --- Profils et CV ---
    @app.get("/profiles")
    def profiles(session: Session = Depends(get_session)) -> list[dict[str, Any]]:
        return [profile_dict(profile) for profile in list_profiles(session, active_only=False)]

    @app.post("/profiles", status_code=201)
    def profiles_create(
        payload: ProfileInput, session: Session = Depends(get_session)
    ) -> dict[str, Any]:
        profile = create_profile(session, payload)
        session.flush()
        return profile_dict(profile)

    @app.put("/profiles/{profile_id}")
    def profiles_update(
        profile_id: str, payload: ProfileInput, session: Session = Depends(get_session)
    ) -> dict[str, Any]:
        profile = update_profile(session, profile_id, payload)
        session.flush()
        return profile_dict(profile)

    @app.post("/profiles/{profile_id}/deactivate")
    def profiles_deactivate(
        profile_id: str, session: Session = Depends(get_session)
    ) -> dict[str, Any]:
        profile = set_active(session, profile_id, False)
        return profile_dict(profile)

    @app.post("/profiles/{profile_id}/activate")
    def profiles_activate(
        profile_id: str, session: Session = Depends(get_session)
    ) -> dict[str, Any]:
        profile = set_active(session, profile_id, True)
        return profile_dict(profile)

    @app.post("/profiles/{profile_id}/resumes", status_code=201)
    async def profiles_upload_resume(
        profile_id: str,
        file: UploadFile = File(...),
        session: Session = Depends(get_session),
    ) -> dict[str, Any]:
        content = await file.read()
        resume = upload_resume(
            session,
            settings,
            profile_id,
            filename=file.filename or "cv.pdf",
            content=content,
        )
        return resume_dict(resume)

    @app.get("/profiles/{profile_id}/resumes/{resume_id}/file", include_in_schema=False)
    def profiles_resume_file(
        profile_id: str, resume_id: str, session: Session = Depends(get_session)
    ) -> FileResponse:
        """Sert le PDF du CV pour la prévisualisation, sans jamais sortir du dossier des CV."""
        resume = session.get(Resume, resume_id)
        if resume is None or resume.profile_id != profile_id:
            raise HTTPException(status_code=404, detail="CV introuvable")
        root = (settings.data_dir / "resumes").resolve()
        path = (settings.data_dir / resume.stored_path).resolve()
        if root not in path.parents or not path.is_file():
            raise HTTPException(status_code=404, detail="fichier du CV introuvable")
        return FileResponse(
            path,
            media_type="application/pdf",
            headers={"Content-Disposition": "inline", **NO_CACHE},
        )

    # --- Offres ---
    @app.get("/jobs")
    def jobs(
        keyword: str | None = None,
        source: str | None = None,
        country: str | None = None,
        limit: int = 100,
        offset: int = 0,
        session: Session = Depends(get_session),
    ) -> list[dict[str, Any]]:
        rows = list_jobs(
            session, keyword=keyword, source=source, country=country,
            limit=min(limit, 500), offset=offset,
        )
        return [job_dict(job) for job in rows]

    @app.get("/jobs/countries")
    def jobs_by_country(session: Session = Depends(get_session)) -> list[dict[str, Any]]:
        return count_jobs_by_country(session)

    @app.get("/jobs/{job_id}")
    def job_detail(job_id: str, session: Session = Depends(get_session)) -> dict[str, Any]:
        return job_dict(get_job(session, job_id), include_description=True)

    @app.post("/jobs/import")
    def jobs_import(
        payload: dict[str, Any] = Body(...), session: Session = Depends(get_session)
    ) -> dict[str, Any]:
        items = payload.get("jobs") if isinstance(payload, dict) else payload
        if not isinstance(items, list):
            raise ValueError("payload attendu : {\"jobs\": [...]}")
        normalized = []
        errors: list[str] = []
        for item in items:
            try:
                normalized.append(
                    normalized_from_mapping(item, source_kind="json_import", source_name="api")
                )
            except Exception as exc:
                errors.append(str(exc))
        source = ensure_source(session, "json_file", "Import API")
        result = ingest_jobs(session, normalized, source_id=source.id)
        return {**result.model_dump(), "errors": [*result.errors, *errors]}

    @app.post("/discovery")
    def discovery(
        request: Request,
        payload: DiscoveryRequest,
        session: Session = Depends(get_session),
    ) -> dict[str, Any]:
        result, errors = collect_jobs(
            session,
            [payload.source],
            JobQuery(
                keywords=payload.keywords,
                locations=payload.locations,
                limit=payload.limit,
            ),
            # Les réglages peuvent être modifiés à chaud (clé Adzuna) : relire l'état courant.
            request.app.state.settings,
        )
        return {**result.model_dump(), "source_errors": errors}

    @app.post("/discovery/start", status_code=202)
    def discovery_start(request: Request, payload: DiscoveryRequest) -> dict[str, Any]:
        """Lance une collecte en arrière-plan (suivi : GET /discovery/tasks/{id})."""
        manager: CollectionManager = request.app.state.collections
        task = manager.start(
            request.app.state.database,
            request.app.state.settings,
            [payload.source],
            JobQuery(
                keywords=payload.keywords, locations=payload.locations, limit=payload.limit
            ),
        )
        return task.as_dict()

    @app.get("/discovery/tasks/active")
    def discovery_active(request: Request) -> dict[str, Any] | None:
        task = request.app.state.collections.active()
        return task.as_dict() if task else None

    @app.get("/discovery/tasks/{task_id}")
    def discovery_task(request: Request, task_id: str) -> dict[str, Any]:
        return request.app.state.collections.get(task_id).as_dict()

    @app.post("/discovery/tasks/{task_id}/cancel")
    def discovery_cancel(request: Request, task_id: str) -> dict[str, Any]:
        return request.app.state.collections.cancel(task_id).as_dict()

    @app.get("/sources")
    def sources(request: Request) -> list[dict[str, Any]]:
        current: Settings = request.app.state.settings
        # La source fictive reste un outil de test interne : jamais proposée à l'utilisateur.
        catalog = [entry for entry in provider_catalog() if entry["kind"] != "fixture"]
        for entry in catalog:
            if entry["kind"] == "adzuna":
                entry["configured"] = bool(current.adzuna.app_id and current.adzuna.app_key)
            elif entry["kind"] == "jobspy":
                entry["installed"] = importlib.util.find_spec("jobspy") is not None
                entry["enabled"] = current.boards.jobspy_enabled
                entry["sites"] = current.boards.sites
                entry["daily_usage"] = _usage_store(current).snapshot()
            elif entry["kind"] == "ats":
                entry["installed"] = importlib.util.find_spec("ats_scrapers") is not None
        return catalog

    @app.get("/countries")
    def countries() -> list[dict[str, Any]]:
        """Liste officielle des pays (ISO 3166-1) pour l'autocomplétion."""
        return country_catalog()

    @app.get("/contracts")
    def contracts() -> list[dict[str, str]]:
        return contract_catalog()

    @app.get("/collection/usage")
    def collection_usage(request: Request) -> dict[str, Any]:
        """Offres collectées aujourd'hui par site, avec le plafond et le reste."""
        return {"sites": _usage_store(request.app.state.settings).snapshot()}

    @app.post("/sources/adzuna/test")
    def sources_adzuna_test(
        request: Request, payload: dict[str, Any] | None = Body(default=None)
    ) -> dict[str, Any]:
        """Teste la clé Adzuna ; accepte les valeurs du formulaire non encore enregistrées."""
        current: Settings = request.app.state.settings
        values = payload or {}
        incoming_key = str(values.get("app_key") or "").strip()
        app_key = current.adzuna.app_key if incoming_key in {"", "***"} else incoming_key
        app_id = str(values.get("app_id") or "").strip() or current.adzuna.app_id
        country = str(values.get("country") or "").strip() or current.adzuna.country
        keywords = [
            str(item).strip() for item in (values.get("keywords") or []) if str(item).strip()
        ]
        try:
            provider = AdzunaProvider(
                app_id=app_id,
                app_key=app_key,
                country=country,
                max_pages=1,
            )
            jobs = provider.fetch(JobQuery(keywords=keywords or ["data"], limit=3))
        except ProviderError as exc:
            raise ValueError(str(exc)) from exc
        return {
            "ok": True,
            "total": provider.last_count,
            "sample": [
                {
                    "title": job.title,
                    "company": job.company,
                    "location": job.location,
                    "url": job.url,
                }
                for job in jobs[:3]
            ],
        }

    # --- Campagnes ---
    @app.get("/campaigns")
    def campaigns(session: Session = Depends(get_session)) -> list[dict[str, Any]]:
        return [
            {**campaign_dict(campaign), "stages": campaign_stage_counts(session, campaign.id)}
            for campaign in list_campaigns(session)
        ]

    @app.post("/campaigns", status_code=201)
    def campaigns_create(
        payload: CampaignInput, session: Session = Depends(get_session)
    ) -> dict[str, Any]:
        return campaign_dict(create_campaign(session, payload))

    # Suivi des exécutions en arrière-plan. Déclarés avant `/campaigns/{campaign_id}` :
    # sinon « tasks » serait pris pour un identifiant de campagne.
    @app.get("/campaigns/tasks/active")
    def campaigns_task_active(request: Request) -> dict[str, Any] | None:
        task = request.app.state.campaign_tasks.active()
        return task.as_dict() if task else None

    @app.get("/campaigns/tasks/{task_id}")
    def campaigns_task(request: Request, task_id: str) -> dict[str, Any]:
        return request.app.state.campaign_tasks.get(task_id).as_dict()

    @app.post("/campaigns/tasks/{task_id}/cancel")
    def campaigns_task_cancel(request: Request, task_id: str) -> dict[str, Any]:
        """Arrête l'exécution en cours ; la campagne reste reprenable."""
        return request.app.state.campaign_tasks.cancel(task_id).as_dict()

    @app.get("/campaigns/{campaign_id}")
    def campaigns_get(campaign_id: str, session: Session = Depends(get_session)) -> dict[str, Any]:
        campaign = get_campaign(session, campaign_id)
        return {**campaign_dict(campaign), "stages": campaign_stage_counts(session, campaign.id)}

    @app.post("/campaigns/{campaign_id}/pause")
    def campaigns_pause(campaign_id: str, session: Session = Depends(get_session)) -> dict[str, Any]:
        return campaign_dict(pause_campaign(session, campaign_id))

    @app.post("/campaigns/{campaign_id}/cancel")
    def campaigns_cancel(campaign_id: str, session: Session = Depends(get_session)) -> dict[str, Any]:
        return campaign_dict(cancel_campaign(session, campaign_id))

    @app.post("/campaigns/{campaign_id}/resume")
    def campaigns_resume(campaign_id: str, session: Session = Depends(get_session)) -> dict[str, Any]:
        return campaign_dict(resume_campaign(session, campaign_id))

    @app.post("/campaigns/{campaign_id}/run")
    def campaigns_run(
        campaign_id: str,
        payload: RunCampaignRequest,
        request: Request,
        session: Session = Depends(get_session),
    ) -> dict[str, Any]:
        return run_campaign(
            session,
            campaign_id,
            request.app.state.settings,
            steps=payload.steps,
            max_items=payload.max_items,
            redo=payload.redo,
            min_score=payload.min_score,
        )

    @app.post("/campaigns/{campaign_id}/run/start", status_code=202)
    def campaigns_run_start(
        campaign_id: str,
        payload: RunCampaignRequest,
        request: Request,
        session: Session = Depends(get_session),
    ) -> dict[str, Any]:
        """Lance une campagne en arrière-plan (suivi : GET /campaigns/tasks/{id})."""
        get_campaign(session, campaign_id)  # 404 avant de démarrer un thread
        manager: CampaignManager = request.app.state.campaign_tasks
        task = manager.start(
            request.app.state.database,
            request.app.state.settings,
            campaign_id,
            steps=payload.steps,
            max_items=payload.max_items,
            redo=payload.redo,
            min_score=payload.min_score,
        )
        return task.as_dict()

    @app.get("/campaigns/{campaign_id}/results")
    def campaigns_results(
        campaign_id: str,
        limit: int = 300,
        session: Session = Depends(get_session),
    ) -> list[dict[str, Any]]:
        rows = session.query(CampaignJob).filter(CampaignJob.campaign_id == campaign_id).limit(
            min(limit, 1000)
        )
        return [campaign_job_dict(row) for row in rows]

    @app.get("/campaigns/{campaign_id}/export")
    def campaigns_export(
        campaign_id: str,
        fmt: str = "csv",
        session: Session = Depends(get_session),
    ) -> FileResponse:
        get_campaign(session, campaign_id)
        target = settings.data_dir / "exports" / f"campaign_{campaign_id}.{fmt}"
        export_campaign(session, campaign_id, target, fmt=fmt)
        return FileResponse(target, filename=target.name)

    # --- File de validation et candidatures ---
    @app.get("/queue")
    def queue(session: Session = Depends(get_session)) -> list[dict[str, Any]]:
        return [attempt_dict(session, attempt) for attempt in list_attempts(session)]

    @app.post("/queue/{attempt_id}/prepare")
    def queue_prepare(attempt_id: str, session: Session = Depends(get_session)) -> dict[str, Any]:
        attempt = get_attempt(session, attempt_id)
        job = session.get(Job, attempt.job_id)
        profile = get_profile(session, attempt.profile_id)
        attempt = prepare_attempt(session, settings, job, profile, campaign_id=attempt.campaign_id)
        _sync_campaign_stage(session, attempt)
        return attempt_dict(session, attempt)

    @app.post("/queue/{attempt_id}/approve")
    def queue_approve(attempt_id: str, session: Session = Depends(get_session)) -> dict[str, Any]:
        attempt = get_attempt(session, attempt_id)
        application = approve_attempt(session, attempt)
        _sync_campaign_stage(session, attempt)
        return application_dict(session, application)

    @app.post("/queue/{attempt_id}/submit")
    def queue_submit(
        attempt_id: str,
        payload: SubmitRequest,
        session: Session = Depends(get_session),
    ) -> dict[str, Any]:
        attempt = get_attempt(session, attempt_id)
        application = record_submission(
            session, attempt, confirmed=payload.confirmed, reference=payload.reference
        )
        _sync_campaign_stage(session, attempt)
        return application_dict(session, application)

    @app.get("/answers")
    def answers(session: Session = Depends(get_session)) -> list[dict[str, Any]]:
        return [
            {
                "id": answer.id,
                "question_text": answer.question_text,
                "answer": answer.answer,
                "approved": answer.approved,
                "kind": answer.kind,
                "times_used": answer.times_used,
            }
            for answer in list_answers(session)
        ]

    @app.post("/answers", status_code=201)
    def answers_upsert(
        payload: AnswerInput, session: Session = Depends(get_session)
    ) -> dict[str, Any]:
        answer = upsert_answer(
            session,
            question_text=payload.question_text,
            answer=payload.answer,
            approved=payload.approved,
            kind=payload.kind,
        )
        return {"id": answer.id, "question_text": answer.question_text, "answer": answer.answer}

    @app.get("/applications")
    def applications(session: Session = Depends(get_session)) -> list[dict[str, Any]]:
        return [application_dict(session, app) for app in list_applications(session)]

    @app.patch("/applications/{application_id}")
    def applications_status(
        application_id: str,
        payload: StatusInput,
        session: Session = Depends(get_session),
    ) -> dict[str, Any]:
        from applyflow.db.models import Application

        if session.get(Application, application_id) is None:
            raise LookupError(f"candidature introuvable : {application_id}")
        return application_dict(
            session, update_application_status(session, application_id, payload.status)
        )

    # --- Boîte mail ---
    @app.get("/email/status")
    def email_status_route(
        request: Request, session: Session = Depends(get_session)
    ) -> dict[str, Any]:
        return email_status(session, request.app.state.settings)

    @app.post("/email/connect")
    def email_connect(
        request: Request,
        payload: EmailConnectInput,
        session: Session = Depends(get_session),
    ) -> dict[str, Any]:
        current: Settings = request.app.state.settings
        address = payload.address.strip().lower()
        if "@" not in address or address.startswith("@") or address.endswith("@"):
            raise ValueError("Adresse e-mail invalide.")
        test_connection(
            address,
            payload.password,
            host=current.email.imap_host,
            port=current.email.imap_port,
        )
        save_credentials(current, address=address, password=payload.password)
        return email_status(session, current)

    @app.post("/email/test")
    def email_test(request: Request) -> dict[str, Any]:
        current: Settings = request.app.state.settings
        credentials = load_credentials(current)
        if credentials is None:
            raise MailboxNotConnected("Aucune boîte n'est connectée.")
        return test_connection(
            credentials["address"],
            credentials["password"],
            host=current.email.imap_host,
            port=current.email.imap_port,
        )

    @app.post("/email/disconnect")
    def email_disconnect(
        request: Request, session: Session = Depends(get_session)
    ) -> dict[str, Any]:
        delete_credentials(request.app.state.settings)
        return email_status(session, request.app.state.settings)

    @app.post("/email/sync")
    def email_sync(
        request: Request, session: Session = Depends(get_session)
    ) -> dict[str, Any]:
        current: Settings = request.app.state.settings
        summary = sync_mailbox(session, current)
        session.flush()
        return {**summary, **email_status(session, current)}

    @app.get("/email/messages")
    def email_messages(
        scope: str = "all", session: Session = Depends(get_session)
    ) -> list[dict[str, Any]]:
        return serialize_messages(session, list_messages(session, scope=scope))

    @app.patch("/email/messages/{message_id}")
    def email_message_update(
        message_id: str,
        payload: EmailMessageUpdate,
        session: Session = Depends(get_session),
    ) -> dict[str, Any]:
        fields = payload.model_fields_set
        kwargs: dict[str, Any] = {"apply_status": payload.apply_status}
        if "application_id" in fields:
            kwargs["application_id"] = payload.application_id
        if "classification" in fields:
            kwargs["classification"] = payload.classification
        if "ignored" in fields:
            kwargs["ignored"] = payload.ignored
        message = update_message(session, message_id, **kwargs)
        return serialize_messages(session, [message])[0]

    @app.get("/email/followups")
    def email_followups(
        request: Request, session: Session = Depends(get_session)
    ) -> dict[str, Any]:
        items = followup_candidates(session, request.app.state.settings)
        return {"items": items, "total": len(items)}

    @app.post("/email/followups/{application_id}/mark")
    def email_followup_mark(
        application_id: str, session: Session = Depends(get_session)
    ) -> dict[str, Any]:
        return mark_followed_up(session, application_id)

    # --- Réglages ---
    @app.get("/settings")
    def settings_get(request: Request) -> dict[str, Any]:
        current: Settings = request.app.state.settings
        payload = current.model_dump(mode="json")
        # Ne jamais renvoyer un secret local via l'API.
        if payload.get("router", {}).get("laya_token"):
            payload["router"]["laya_token"] = "***"
        if payload.get("adzuna", {}).get("app_key"):
            payload["adzuna"]["app_key"] = "***"
        return {
            **payload,
            "config_path": str(current.config_path) if current.config_path else None,
        }

    @app.put("/settings")
    def settings_update(
        request: Request, payload: dict[str, Any] = Body(...)
    ) -> dict[str, Any]:
        current: Settings = request.app.state.settings
        merged = current.model_dump()
        for section, values in payload.items():
            if section == "config_path":
                continue
            if isinstance(values, dict) and isinstance(merged.get(section), dict):
                merged[section].update(values)
            else:
                merged[section] = values
        # Un client qui renvoie la configuration lue (jeton masqué) ne doit pas
        # écraser le secret stocké localement.
        incoming_router = payload.get("router") if isinstance(payload.get("router"), dict) else {}
        if incoming_router.get("laya_token") in {None, "***"}:
            merged["router"]["laya_token"] = current.router.laya_token
        incoming_adzuna = payload.get("adzuna") if isinstance(payload.get("adzuna"), dict) else {}
        if incoming_adzuna.get("app_key") in {None, "***"}:
            merged["adzuna"]["app_key"] = current.adzuna.app_key
        updated = Settings(**merged)
        updated.config_path = current.config_path
        target = save_settings(updated)
        request.app.state.settings = updated
        restart_required = any(section in payload for section in ("router", "api", "ui"))
        return {"saved_to": str(target), "restart_required": restart_required}

    return app
