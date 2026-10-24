"""Modèles SQLAlchemy — schéma local, explicite et migrable."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def new_id() -> str:
    return uuid4().hex


def utcnow() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    email: Mapped[str] = mapped_column(String(255), unique=True)
    name: Mapped[str] = mapped_column(String(120))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    profiles: Mapped[list[Profile]] = relationship(back_populates="user")
    answers: Mapped[list[ApplicationAnswer]] = relationship(back_populates="user")


class Profile(Base):
    __tablename__ = "profiles"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    # Identité candidat : uniquement des valeurs saisies par l'utilisateur.
    full_name: Mapped[str | None] = mapped_column(String(160), nullable=True)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    linkedin_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    github_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    website: Mapped[str | None] = mapped_column(String(500), nullable=True)
    other_links: Mapped[list[dict[str, str]]] = mapped_column(JSON, default=list)
    city: Mapped[str | None] = mapped_column(String(120), nullable=True)
    target_titles: Mapped[list[str]] = mapped_column(JSON, default=list)
    technical_skills: Mapped[list[str]] = mapped_column(JSON, default=list)
    domain_skills: Mapped[list[str]] = mapped_column(JSON, default=list)
    experience_level: Mapped[str] = mapped_column(String(32), default="junior")
    years_experience: Mapped[float] = mapped_column(Float, default=0.0)
    locations: Mapped[list[str]] = mapped_column(JSON, default=list)
    contract_types: Mapped[list[str]] = mapped_column(JSON, default=list)
    remote_preferences: Mapped[list[str]] = mapped_column(JSON, default=list)
    salary_min: Mapped[int | None] = mapped_column(Integer, nullable=True)
    salary_max: Mapped[int | None] = mapped_column(Integer, nullable=True)
    salary_currency: Mapped[str] = mapped_column(String(8), default="EUR")
    exclusion_criteria: Mapped[list[str]] = mapped_column(JSON, default=list)
    work_authorization: Mapped[str | None] = mapped_column(String(120), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    user: Mapped[User] = relationship(back_populates="profiles")
    resumes: Mapped[list[Resume]] = relationship(
        back_populates="profile", cascade="all, delete-orphan"
    )


class Resume(Base):
    __tablename__ = "resumes"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    profile_id: Mapped[str] = mapped_column(
        ForeignKey("profiles.id", ondelete="CASCADE"), index=True
    )
    filename: Mapped[str] = mapped_column(String(255))
    stored_path: Mapped[str] = mapped_column(String(500))
    sha256: Mapped[str] = mapped_column(String(64))
    size_bytes: Mapped[int] = mapped_column(Integer)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    profile: Mapped[Profile] = relationship(back_populates="resumes")


class JobSource(Base):
    __tablename__ = "job_sources"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(120))
    kind: Mapped[str] = mapped_column(String(40))
    config: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Job(Base):
    __tablename__ = "jobs"
    __table_args__ = (UniqueConstraint("fingerprint", name="uq_jobs_fingerprint"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    source_id: Mapped[str | None] = mapped_column(
        ForeignKey("job_sources.id", ondelete="SET NULL"), nullable=True, index=True
    )
    source_kind: Mapped[str] = mapped_column(String(40), default="fixture")
    external_id: Mapped[str] = mapped_column(String(255), default="")
    url: Mapped[str] = mapped_column(String(1000))
    url_key: Mapped[str] = mapped_column(String(1000), index=True)
    apply_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    company: Mapped[str] = mapped_column(String(255))
    title: Mapped[str] = mapped_column(String(300))
    description: Mapped[str] = mapped_column(Text)
    location: Mapped[str | None] = mapped_column(String(255), nullable=True)
    country: Mapped[str | None] = mapped_column(String(2), nullable=True, index=True)
    remote: Mapped[str | None] = mapped_column(String(32), nullable=True)
    salary_min: Mapped[int | None] = mapped_column(Integer, nullable=True)
    salary_max: Mapped[int | None] = mapped_column(Integer, nullable=True)
    salary_currency: Mapped[str | None] = mapped_column(String(8), nullable=True)
    contract_type: Mapped[str | None] = mapped_column(String(40), nullable=True)
    seniority: Mapped[str | None] = mapped_column(String(32), nullable=True)
    required_skills: Mapped[list[str]] = mapped_column(JSON, default=list)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    collected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    fingerprint: Mapped[str] = mapped_column(String(64))
    raw: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    campaign_jobs: Mapped[list[CampaignJob]] = relationship(back_populates="job")


class Campaign(Base):
    __tablename__ = "campaigns"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(160))
    status: Mapped[str] = mapped_column(String(20), default="draft", index=True)
    sources: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    profile_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    locations: Mapped[list[str]] = mapped_column(JSON, default=list)
    keywords: Mapped[list[str]] = mapped_column(JSON, default=list)
    experience_levels: Mapped[list[str]] = mapped_column(JSON, default=list)
    max_jobs: Mapped[int] = mapped_column(Integer, default=1000)
    min_score: Mapped[int] = mapped_column(Integer, default=65)
    exclusions: Mapped[list[str]] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    campaign_jobs: Mapped[list[CampaignJob]] = relationship(
        back_populates="campaign", cascade="all, delete-orphan"
    )


class CampaignJob(Base):
    __tablename__ = "campaign_jobs"
    __table_args__ = (
        UniqueConstraint("campaign_id", "job_id", name="uq_campaign_jobs"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    campaign_id: Mapped[str] = mapped_column(
        ForeignKey("campaigns.id", ondelete="CASCADE"), index=True
    )
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), index=True)
    stage: Mapped[str] = mapped_column(String(20), default="discovered")
    score: Mapped[float | None] = mapped_column(Float, nullable=True)
    priority: Mapped[str | None] = mapped_column(String(16), nullable=True)
    eligible: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    reasons: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    decision: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    campaign: Mapped[Campaign] = relationship(back_populates="campaign_jobs")
    job: Mapped[Job] = relationship(back_populates="campaign_jobs")


class RoutingDecision(Base):
    __tablename__ = "routing_decisions"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), index=True)
    profile_id: Mapped[str] = mapped_column(ForeignKey("profiles.id", ondelete="CASCADE"))
    resume_id: Mapped[str | None] = mapped_column(
        ForeignKey("resumes.id", ondelete="SET NULL"), nullable=True
    )
    router: Mapped[str] = mapped_column(String(40))
    confidence: Mapped[float] = mapped_column(Float)
    reasons: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    uncertain: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ApplicationAttempt(Base):
    __tablename__ = "application_attempts"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_attempt_idempotency"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    campaign_id: Mapped[str | None] = mapped_column(
        ForeignKey("campaigns.id", ondelete="SET NULL"), nullable=True
    )
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), index=True)
    profile_id: Mapped[str] = mapped_column(ForeignKey("profiles.id", ondelete="CASCADE"))
    resume_id: Mapped[str | None] = mapped_column(
        ForeignKey("resumes.id", ondelete="SET NULL"), nullable=True
    )
    mode: Mapped[str] = mapped_column(String(12), default="dry_run")
    status: Mapped[str] = mapped_column(String(20), default="prepared", index=True)
    form_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    plan: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    unknown_questions: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    idempotency_key: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class Application(Base):
    __tablename__ = "applications"
    __table_args__ = (UniqueConstraint("job_id", name="uq_applications_job"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), index=True)
    profile_id: Mapped[str] = mapped_column(ForeignKey("profiles.id", ondelete="CASCADE"))
    resume_id: Mapped[str | None] = mapped_column(
        ForeignKey("resumes.id", ondelete="SET NULL"), nullable=True
    )
    campaign_id: Mapped[str | None] = mapped_column(
        ForeignKey("campaigns.id", ondelete="SET NULL"), nullable=True
    )
    attempt_id: Mapped[str | None] = mapped_column(
        ForeignKey("application_attempts.id", ondelete="SET NULL"), nullable=True
    )
    status: Mapped[str] = mapped_column(String(24), default="submitted")
    submitted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    followed_up_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    external_reference: Mapped[str | None] = mapped_column(String(255), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class EmailMessage(Base):
    """Message reçu, réduit à un extrait : le corps complet n'est pas conservé."""

    __tablename__ = "email_messages"
    __table_args__ = (UniqueConstraint("remote_id", name="uq_email_messages_remote"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    remote_id: Mapped[str] = mapped_column(String(500))
    account: Mapped[str] = mapped_column(String(255))
    folder: Mapped[str] = mapped_column(String(64), default="INBOX")
    subject: Mapped[str] = mapped_column(String(500), default="")
    sender_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    sender_email: Mapped[str] = mapped_column(String(255), default="", index=True)
    excerpt: Mapped[str] = mapped_column(Text, default="")
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, index=True
    )
    classification: Mapped[str] = mapped_column(String(24), default="other", index=True)
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    reason: Mapped[str] = mapped_column(String(400), default="")
    application_id: Mapped[str | None] = mapped_column(
        ForeignKey("applications.id", ondelete="SET NULL"), nullable=True, index=True
    )
    match_reason: Mapped[str | None] = mapped_column(String(400), nullable=True)
    reviewed: Mapped[bool] = mapped_column(Boolean, default=False)
    ignored: Mapped[bool] = mapped_column(Boolean, default=False)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ApplicationAnswer(Base):
    __tablename__ = "application_answers"
    __table_args__ = (UniqueConstraint("user_id", "question_key", name="uq_answers_user_key"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    question_key: Mapped[str] = mapped_column(String(300))
    question_text: Mapped[str] = mapped_column(Text)
    answer: Mapped[str] = mapped_column(Text)
    kind: Mapped[str] = mapped_column(String(32), default="text")
    approved: Mapped[bool] = mapped_column(Boolean, default=False)
    times_used: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    user: Mapped[User] = relationship(back_populates="answers")


class AuditEvent(Base):
    __tablename__ = "audit_events"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    entity_type: Mapped[str] = mapped_column(String(40), index=True)
    entity_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    action: Mapped[str] = mapped_column(String(80), index=True)
    data: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    actor: Mapped[str] = mapped_column(String(80), default="local")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
