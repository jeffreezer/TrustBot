"""SQLAlchemy models for the TrustBot MVP.

Design invariants (see 01_TrustBot_MVP_Portfolio_Plan.md §10 and the build guide):

- Every table has a UUID primary key and ``created_at`` / ``updated_at``.
- Every tenant-owned table carries ``org_id`` from day one, so the single-tenant
  MVP becomes multi-tenant by adding a filter rather than a migration. The
  ``organization`` table is the only exception (it *is* the tenant).
- ``evidence`` and ``knowledge_chunks`` carry confidentiality / customer-shareable
  metadata. Retrieval (Phase 3) filters on it and answer validation (Phase 4)
  refuses to put internal-only material in a customer-facing answer.
- Integrity hashes (``file_hash`` / ``source_hash``) back the audit trail: we can
  prove which exact bytes produced a given answer.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

# BGE-M3 embedding width. The vector column is fixed-size, so this is pinned here
# and referenced by the migration. Changing models/embedders means a new migration.
EMBEDDING_DIM = 1024


class Base(DeclarativeBase):
    pass


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class UUIDPrimaryKeyMixin:
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )


def _org_fk() -> Mapped[uuid.UUID]:
    """org_id column + FK + index, used by every tenant-owned table."""
    return mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organization.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )


class Organization(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "organization"

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)


class CompanyProfile(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "company_profile"

    org_id: Mapped[uuid.UUID] = _org_fk()
    # The source markdown is kept verbatim (the document of record); key_facts is a
    # structured projection of the canonical facts for fast querying / filtering.
    raw_markdown: Mapped[str] = mapped_column(Text, nullable=False)
    key_facts: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    source_hash: Mapped[str] = mapped_column(String(64), nullable=False)


class Control(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "controls"
    __table_args__ = (UniqueConstraint("org_id", "control_code", name="uq_control_org_code"),)

    org_id: Mapped[uuid.UUID] = _org_fk()
    control_code: Mapped[str] = mapped_column(String(64), nullable=False)
    domain: Mapped[str | None] = mapped_column(String(128))
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    implementation_statement: Mapped[str | None] = mapped_column(Text)
    owner: Mapped[str | None] = mapped_column(String(128))
    status: Mapped[str | None] = mapped_column(String(64))
    framework_mappings: Mapped[str | None] = mapped_column(Text)
    last_reviewed: Mapped[date | None] = mapped_column(Date)
    next_review: Mapped[date | None] = mapped_column(Date)
    confidence: Mapped[str | None] = mapped_column(String(32))
    notes: Mapped[str | None] = mapped_column(Text)

    links: Mapped[list[EvidenceControlLink]] = relationship(
        back_populates="control", cascade="all, delete-orphan"
    )


class Evidence(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "evidence"

    org_id: Mapped[uuid.UUID] = _org_fk()
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    evidence_type: Mapped[str | None] = mapped_column(String(64))
    original_filename: Mapped[str] = mapped_column(String(512), nullable=False)
    # Opaque key/URL returned by the storage adapter (local path or s3://...).
    storage_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    content_type: Mapped[str | None] = mapped_column(String(128))
    file_hash: Mapped[str] = mapped_column(String(64), nullable=False)  # sha256 hex
    file_size: Mapped[int | None] = mapped_column(Integer)
    owner: Mapped[str | None] = mapped_column(String(128))
    # confidentiality + customer_shareable gate what may appear in external answers.
    confidentiality: Mapped[str] = mapped_column(String(32), nullable=False, default="internal")
    customer_shareable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    version: Mapped[str | None] = mapped_column(String(64))
    valid_from: Mapped[date | None] = mapped_column(Date)
    valid_until: Mapped[date | None] = mapped_column(Date)

    links: Mapped[list[EvidenceControlLink]] = relationship(
        back_populates="evidence", cascade="all, delete-orphan"
    )


class EvidenceControlLink(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "evidence_control_links"
    __table_args__ = (
        UniqueConstraint("evidence_id", "control_id", name="uq_evidence_control"),
    )

    org_id: Mapped[uuid.UUID] = _org_fk()
    evidence_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("evidence.id", ondelete="CASCADE"), nullable=False
    )
    control_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("controls.id", ondelete="CASCADE"), nullable=False
    )

    evidence: Mapped[Evidence] = relationship(back_populates="links")
    control: Mapped[Control] = relationship(back_populates="links")


class KnowledgeChunk(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A retrievable chunk. Populated in Phase 2 (parse → chunk → embed); empty now."""

    __tablename__ = "knowledge_chunks"

    org_id: Mapped[uuid.UUID] = _org_fk()
    source_type: Mapped[str] = mapped_column(String(64), nullable=False)
    source_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), index=True)
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    chunk_text: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIM))
    # Python attr `meta`; DB column `metadata` (the bare name is reserved by Declarative).
    meta: Mapped[dict] = mapped_column("metadata", JSONB, nullable=False, default=dict)


class ApprovedAnswer(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Reusable approved Q&A. Seeded from Northwind's completed questionnaires."""

    __tablename__ = "approved_answer_library"
    __table_args__ = (
        UniqueConstraint(
            "org_id", "source", "question_external_id", name="uq_approved_answer_src_qid"
        ),
    )

    org_id: Mapped[uuid.UUID] = _org_fk()
    source: Mapped[str] = mapped_column(String(128), nullable=False)
    question_external_id: Mapped[str | None] = mapped_column(String(64))
    domain: Mapped[str | None] = mapped_column(String(128))
    question_text: Mapped[str] = mapped_column(Text, nullable=False)
    answer_text: Mapped[str | None] = mapped_column(Text)
    answer_detail: Mapped[str | None] = mapped_column(Text)
    extra: Mapped[dict | None] = mapped_column(JSONB)


class Questionnaire(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "questionnaires"

    org_id: Mapped[uuid.UUID] = _org_fk()
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    original_filename: Mapped[str | None] = mapped_column(String(512))
    storage_path: Mapped[str | None] = mapped_column(String(1024))
    file_hash: Mapped[str | None] = mapped_column(String(64))
    source_format: Mapped[str | None] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="uploaded")

    questions: Mapped[list[Question]] = relationship(
        back_populates="questionnaire", cascade="all, delete-orphan"
    )


class Question(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "questions"

    org_id: Mapped[uuid.UUID] = _org_fk()
    questionnaire_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("questionnaires.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    external_id: Mapped[str | None] = mapped_column(String(64))
    domain: Mapped[str | None] = mapped_column(String(128))
    text: Mapped[str] = mapped_column(Text, nullable=False)
    row_index: Mapped[int | None] = mapped_column(Integer)

    questionnaire: Mapped[Questionnaire] = relationship(back_populates="questions")
    answers: Mapped[list[Answer]] = relationship(
        back_populates="question", cascade="all, delete-orphan"
    )


class Answer(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "answers"

    org_id: Mapped[uuid.UUID] = _org_fk()
    question_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("questions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    short_answer: Mapped[str | None] = mapped_column(String(512))
    answer_text: Mapped[str | None] = mapped_column(Text)
    claim: Mapped[str | None] = mapped_column(Text)
    scope: Mapped[str | None] = mapped_column(Text)
    evidence_refs: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    exceptions: Mapped[str | None] = mapped_column(Text)
    confidence: Mapped[str | None] = mapped_column(String(32))
    # supported_yes | supported_no | has_exception | unknown
    outcome: Mapped[str | None] = mapped_column(String(32))
    # Defaults to True: nothing is externally usable until a human signs off.
    needs_human_review: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    review_reason: Mapped[str | None] = mapped_column(Text)
    freshness_status: Mapped[str | None] = mapped_column(String(32))
    generated_by: Mapped[str | None] = mapped_column(String(128))
    # Human-review decision (Phase 5): pending | approved | edited | rejected |
    # needs_evidence. The audit trail of every action lives in answer_reviews + audit_log.
    review_status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    # Soft-supersede: regenerate marks a prior *draft* (never an approved/edited answer)
    # with a timestamp instead of deleting it, so history survives. NULL = the live row;
    # exactly one non-superseded answer per question.
    superseded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    question: Mapped[Question] = relationship(back_populates="answers")
    reviews: Mapped[list[AnswerReview]] = relationship(
        back_populates="answer", cascade="all, delete-orphan"
    )


class AnswerReview(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "answer_reviews"

    org_id: Mapped[uuid.UUID] = _org_fk()
    answer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("answers.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    reviewer: Mapped[str | None] = mapped_column(String(255))
    # approve | edit | reject | request_evidence | save_to_library
    action: Mapped[str] = mapped_column(String(32), nullable=False)
    edited_text: Mapped[str | None] = mapped_column(Text)
    comment: Mapped[str | None] = mapped_column(Text)

    answer: Mapped[Answer] = relationship(back_populates="reviews")


class AuditLog(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Append-only record of state changes. payload must never contain secrets."""

    __tablename__ = "audit_log"

    org_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organization.id", ondelete="CASCADE"), index=True
    )
    actor: Mapped[str] = mapped_column(String(255), nullable=False)
    action: Mapped[str] = mapped_column(String(128), nullable=False)
    target_type: Mapped[str | None] = mapped_column(String(64))
    target_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    payload: Mapped[dict | None] = mapped_column(JSONB)


class GenerationJob(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A background draft-generation run for one questionnaire (Phase 6 async jobs).

    The UUID primary key is random (non-guessable), so a job id is itself a capability;
    every read is still org-scoped on top of that. ``error`` holds a **generic** message
    only — never a stack trace, provider response, or any secret/PII.
    """

    __tablename__ = "generation_jobs"

    org_id: Mapped[uuid.UUID] = _org_fk()
    questionnaire_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("questionnaires.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # pending | running | done | failed
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    total: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    completed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error: Mapped[str | None] = mapped_column(Text)
