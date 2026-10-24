"""Collecte, persistance et consultation des annonces."""

from __future__ import annotations

import threading
import time
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from applyflow.config import Settings
from applyflow.db.models import Job, JobSource
from applyflow.geo import country_label, detect_country, normalize_country
from applyflow.jobs.dedupe import (
    is_probable_duplicate,
    job_fingerprint,
    normalize_company,
    url_key,
)
from applyflow.logging_setup import get_logger
from applyflow.providers import build_provider
from applyflow.providers.base import (
    Controllable,
    ProgressCallback,
    ProviderDisabled,
    ProviderError,
)
from applyflow.schemas import ImportResult, JobQuery, NormalizedJob
from applyflow.services import record_audit

logger = get_logger("jobs")


def ensure_source(
    session: Session, kind: str, name: str = "", config: dict[str, Any] | None = None
) -> JobSource:
    name = name or kind
    source = session.scalar(
        select(JobSource).where(JobSource.kind == kind, JobSource.name == name)
    )
    if source is None:
        source = JobSource(kind=kind, name=name, config=config or {})
        session.add(source)
        session.flush()
    return source


def ingest_jobs(
    session: Session,
    jobs: list[NormalizedJob],
    *,
    source_id: str | None = None,
) -> ImportResult:
    result = ImportResult()
    seen: dict[str, str] = {}
    for normalized in jobs:
        try:
            fingerprint = job_fingerprint(
                normalized.company, normalized.title, normalized.location
            )
            key = url_key(normalized.url)
            existing = session.scalar(
                select(Job).where(or_(Job.fingerprint == fingerprint, Job.url_key == key))
            )
            if existing is None and fingerprint in seen:
                existing = session.get(Job, seen[fingerprint])
            if existing is None:
                existing = _find_near_duplicate(session, normalized)
            if existing is not None:
                result.duplicates += 1
                result.job_ids.append(existing.id)
                _enrich(existing, normalized)
                _record_source(existing, normalized)
                continue

            job = Job(
                source_id=source_id,
                source_kind=normalized.source_kind,
                external_id=normalized.external_id,
                url=normalized.url,
                url_key=key,
                apply_url=normalized.apply_url,
                company=normalized.company,
                title=normalized.title,
                description=normalized.description,
                location=normalized.location,
                country=normalized.country or detect_country(normalized.location),
                remote=normalized.remote,
                salary_min=normalized.salary_min,
                salary_max=normalized.salary_max,
                salary_currency=normalized.salary_currency,
                contract_type=normalized.contract_type,
                seniority=normalized.seniority,
                required_skills=normalized.skills,
                published_at=normalized.published_at,
                fingerprint=fingerprint,
                raw=dict(normalized.raw),
            )
            _record_source(job, normalized)
            session.add(job)
            session.flush()
            seen[fingerprint] = job.id
            result.created += 1
            result.job_ids.append(job.id)
        except Exception as exc:  # une annonce cassée ne bloque pas l'import
            logger.warning(
                "annonce ignorée", extra={"data": {"url": normalized.url, "error": str(exc)}}
            )
            result.skipped += 1
            result.errors.append(f"{normalized.url}: {exc}")
    if result.created or result.duplicates:
        record_audit(
            session,
            entity_type="job",
            entity_id=source_id,
            action="jobs.ingested",
            data={
                "created": result.created,
                "duplicates": result.duplicates,
                "skipped": result.skipped,
            },
        )
    return result


def _find_near_duplicate(session: Session, normalized: NormalizedJob) -> Job | None:
    """Même annonce publiée sur une autre plateforme avec des libellés légèrement différents."""
    company_key = normalize_company(normalized.company)
    if not company_key:
        return None
    first_word = company_key.split()[0]
    candidates = session.scalars(
        select(Job).where(func.lower(Job.company).like(f"{first_word}%"))
    ).all()
    for candidate in candidates:
        if is_probable_duplicate(
            company_a=candidate.company, title_a=candidate.title,
            location_a=candidate.location, description_a=candidate.description,
            company_b=normalized.company, title_b=normalized.title,
            location_b=normalized.location, description_b=normalized.description,
        ):
            return candidate
    return None


def _record_source(job: Job, normalized: NormalizedJob) -> None:
    """Conserve chaque plateforme où l'annonce a été vue (sans multiplier les candidatures)."""
    sources = list((job.raw or {}).get("sources") or [])
    key = url_key(normalized.url)
    if not any(entry.get("url_key") == key for entry in sources):
        sources.append(
            {
                "source": normalized.source_name or normalized.source_kind,
                "url": normalized.url,
                "url_key": key,
                "apply_url": normalized.apply_url,
                "external_id": normalized.external_id,
            }
        )
    job.raw = {**(job.raw or {}), "sources": sources}


def rebuild_fingerprints(session: Session) -> dict[str, int]:
    """Recalcule les empreintes après un changement de règle ; fusionne les doublons exacts."""
    updated = merged = 0
    seen: dict[str, str] = {}
    for job in session.scalars(select(Job).order_by(Job.created_at)).all():
        fingerprint = job_fingerprint(job.company, job.title, job.location)
        if fingerprint in seen:
            keeper = session.get(Job, seen[fingerprint])
            if keeper is not None and not job.campaign_jobs:
                keeper.raw = {**(keeper.raw or {}), "sources": _merge_sources(keeper, job)}
                session.delete(job)
                merged += 1
                continue
            continue  # lié à une campagne : on le garde tel quel plutôt que de casser l'historique
        seen[fingerprint] = job.id
        if job.fingerprint != fingerprint:
            job.fingerprint = fingerprint
            updated += 1
    session.flush()
    return {"updated": updated, "merged": merged, "countries": backfill_countries(session)}


def _merge_sources(keeper: Job, other: Job) -> list[dict[str, Any]]:
    def own(job: Job) -> dict[str, Any]:
        return {"source": job.source_kind, "url": job.url, "url_key": job.url_key,
                "apply_url": job.apply_url, "external_id": job.external_id}

    merged: list[dict[str, Any]] = []
    known: set[Any] = set()
    for entry in [
        *((keeper.raw or {}).get("sources") or [own(keeper)]),
        *((other.raw or {}).get("sources") or []),
        own(other),
    ]:
        if entry.get("url_key") not in known:
            merged.append(entry)
            known.add(entry.get("url_key"))
    return merged


def _enrich(job: Job, normalized: NormalizedJob) -> None:
    """Complète les champs manquants sans écraser une donnée existante."""
    if not job.country:
        job.country = normalized.country or detect_country(normalized.location)
    if not job.apply_url and normalized.apply_url:
        job.apply_url = normalized.apply_url
    if not job.required_skills and normalized.skills:
        job.required_skills = normalized.skills
    if not job.salary_min and normalized.salary_min:
        job.salary_min = normalized.salary_min
        job.salary_max = normalized.salary_max
        job.salary_currency = normalized.salary_currency


def collect_jobs(
    session: Session,
    source_specs: list[dict[str, Any]],
    query: JobQuery,
    settings: Settings,
    *,
    on_progress: ProgressCallback | None = None,
    cancel_event: threading.Event | None = None,
) -> tuple[ImportResult, list[str]]:
    """Exécute les connecteurs configurés, séquentiellement (pas de contournement de limites).

    `on_progress` reçoit (étapes faites, étapes totales, libellé, offres collectées) ; si
    `cancel_event` est levé, la collecte s'arrête entre deux requêtes et les offres déjà
    récupérées sont enregistrées.
    """
    combined = ImportResult()
    errors: list[str] = []
    for index, spec in enumerate(source_specs):
        if cancel_event is not None and cancel_event.is_set():
            break
        if index > 0 and settings.discovery.rate_limit_seconds > 0:
            # Collecte strictement séquentielle : une pause entre connecteurs évite
            # de marteler une plateforme. Aucune concurrence n'est utilisée.
            time.sleep(settings.discovery.rate_limit_seconds)
        kind = str(spec.get("kind") or "")
        label = spec.get("name") or kind
        try:
            provider = build_provider(spec, settings=settings)
            source = ensure_source(session, provider.kind, str(label), spec.get("config") or {})
            if isinstance(provider, Controllable):
                provider.bind_control(on_progress, cancel_event)
            jobs = provider.fetch(query)
            if on_progress is not None:
                on_progress(1, 1, "Enregistrement des offres", len(jobs))
            result = ingest_jobs(session, jobs, source_id=source.id)
            combined.created += result.created
            combined.duplicates += result.duplicates
            combined.skipped += result.skipped
            combined.errors.extend(result.errors)
            combined.job_ids.extend(result.job_ids)
            provider_stats = getattr(provider, "last_stats", None)
            if provider_stats:
                combined.stats[str(label)] = {
                    "kind": provider.kind,
                    "details": provider_stats,
                    "daily_usage": getattr(provider, "daily_usage", {}) or {},
                }
            logger.info(
                "collecte terminée",
                extra={
                    "data": {
                        "source": kind,
                        "fetched": len(jobs),
                        "created": result.created,
                        "duplicates": result.duplicates,
                    }
                },
            )
        except ProviderDisabled as exc:
            errors.append(f"{label} : {exc}")
        except (ProviderError, ValueError, OSError) as exc:
            errors.append(f"{label} : {exc}")
        except Exception as exc:  # connecteur tiers : ne pas interrompre les autres sources
            errors.append(f"{label} : erreur inattendue ({exc})")
            logger.exception("échec du connecteur", extra={"data": {"source": kind}})
    combined.errors.extend(errors)
    return combined, errors


def list_jobs(
    session: Session,
    *,
    keyword: str | None = None,
    source: str | None = None,
    country: str | None = None,
    limit: int = 200,
    offset: int = 0,
) -> list[Job]:
    query = select(Job).order_by(Job.collected_at.desc())
    if keyword:
        pattern = f"%{keyword.strip()}%"
        query = query.where(
            or_(Job.title.ilike(pattern), Job.company.ilike(pattern), Job.description.ilike(pattern))
        )
    if source:
        query = query.where(Job.source_kind == source)
    if country:
        codes = [normalize_country(part) or part.strip().upper() for part in country.split(',')]
        wanted = [code for code in codes if code and code != 'UNKNOWN']
        clauses = []
        if wanted:
            clauses.append(Job.country.in_(wanted))
        if len(wanted) < len(codes):  # unknown : pays non déterminé
            clauses.append(Job.country.is_(None))
        query = query.where(or_(*clauses))
    return list(session.scalars(query.offset(offset).limit(limit)))


def count_jobs_by_country(session: Session) -> list[dict[str, Any]]:
    """Nombre d'offres par pays (sans pays connu : `unknown`)."""
    rows = session.execute(
        select(Job.country, func.count()).group_by(Job.country).order_by(func.count().desc())
    ).all()
    return [
        {"country": code or "unknown", "label": country_label(code), "count": int(count)}
        for code, count in rows
    ]


def backfill_countries(session: Session) -> int:
    """Renseigne le pays des offres existantes à partir de leur localisation."""
    updated = 0
    for job in session.scalars(select(Job).where(Job.country.is_(None))).all():
        code = detect_country(job.location)
        if code:
            job.country = code
            updated += 1
    session.flush()
    return updated


def count_jobs(session: Session) -> int:
    return int(session.scalar(select(func.count()).select_from(Job)) or 0)


def get_job(session: Session, job_id: str) -> Job:
    job = session.get(Job, job_id)
    if job is None:
        raise LookupError(f"offre introuvable : {job_id}")
    return job
