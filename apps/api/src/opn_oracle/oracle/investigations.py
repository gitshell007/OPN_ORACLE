"""Durable, tenant-scoped workbench for traceable company investigations.

The workbench deliberately keeps discovered identities and relationships outside the
canonical Actor graph until a person verifies and promotes them.  Signal remains the
producer of registry/procurement data; Oracle stores only bounded source snapshots,
claims, decisions and references needed to reproduce a run.
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
import uuid
from collections.abc import Mapping
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    select,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, Session, mapped_column

from opn_oracle.extensions import Base
from opn_oracle.integrations.entity_intel import (
    cached_graph,
    resolve_signal_external_tenant_id_for_tenant,
)
from opn_oracle.integrations.procurement import cached_awards
from opn_oracle.oracle.models import Actor, StrategicDossier, TenantDomainMixin
from opn_oracle.platform.audit import append_audit_event
from opn_oracle.tenants.context import require_tenant_id

INVESTIGATION_PROTOCOL_VERSION = "investigation-protocol-v1"
INVESTIGATION_SOURCE_POLICY_VERSION = "signal-reference-snapshots-v1"
MACRO_STAGES = ("P0", "P1", "P2", "P3", "P4", "P5")
LEGAL_SUFFIXES = frozenset(
    {
        "SA",
        "SL",
        "SLU",
        "SLL",
        "SLC",
        "SCOOP",
        "SOCIEDAD",
        "ANONIMA",
        "LIMITADA",
        "UNIPERSONAL",
        "INC",
        "LTD",
        "LIMITED",
        "GMBH",
        "PLC",
    }
)

# Tokenized legal forms produced by re.findall(r"[A-Z0-9]+", …) on "S.L.", "S.A.",
# "S.L.U.", etc. Longer suffixes first so SLU collapses before SL.
_MULTI_TOKEN_LEGAL_SUFFIXES: tuple[tuple[str, ...], ...] = (
    ("S", "L", "U"),
    ("S", "A", "U"),
    ("S", "L", "L"),
    ("S", "L", "C"),
    ("S", "COOP"),
    ("S", "L"),
    ("S", "A"),
)


class InvestigationRun(TenantDomainMixin, Base):
    __tablename__ = "investigation_runs"
    __table_args__ = (
        UniqueConstraint("id", "tenant_id", name="uq_investigation_runs_id_tenant"),
        UniqueConstraint("tenant_id", "idempotency_key", name="uq_investigation_runs_idempotency"),
        ForeignKeyConstraint(
            ("dossier_id", "tenant_id"),
            ("strategic_dossiers.id", "strategic_dossiers.tenant_id"),
            ondelete="CASCADE",
            name="fk_investigation_runs_dossier_tenant",
        ),
        ForeignKeyConstraint(
            ("tenant_id", "requested_by_user_id"),
            ("tenant_memberships.tenant_id", "tenant_memberships.user_id"),
            ondelete="RESTRICT",
            name="fk_investigation_runs_requester_membership",
        ),
        CheckConstraint(
            "status IN "
            "('awaiting_review','ready','running','paused','completed','failed','cancelled')",
            name="investigation_run_status",
        ),
        CheckConstraint("stage IN ('P0','P1','P2','P3','P4','P5')", name="investigation_run_stage"),
        CheckConstraint("progress BETWEEN 0 AND 100", name="investigation_run_progress"),
        CheckConstraint("version >= 1", name="investigation_run_version"),
        CheckConstraint("jsonb_typeof(seed_identifiers)='object'", name="investigation_seed_ids"),
        CheckConstraint("jsonb_typeof(limits)='object'", name="investigation_limits"),
        CheckConstraint("jsonb_typeof(source_policy)='object'", name="investigation_source_policy"),
        Index("ix_investigation_runs_dossier_updated", "tenant_id", "dossier_id", "updated_at"),
    )

    dossier_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    seed_name: Mapped[str] = mapped_column(String(300), nullable=False)
    seed_kind: Mapped[str] = mapped_column(String(20), nullable=False)
    seed_identifiers: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    cutoff_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    period_start: Mapped[date | None] = mapped_column(Date)
    period_end: Mapped[date | None] = mapped_column(Date)
    protocol_version: Mapped[str] = mapped_column(
        String(80), nullable=False, default=INVESTIGATION_PROTOCOL_VERSION
    )
    source_policy_version: Mapped[str] = mapped_column(
        String(80), nullable=False, default=INVESTIGATION_SOURCE_POLICY_VERSION
    )
    limits: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    source_policy: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="awaiting_review")
    stage: Mapped[str] = mapped_column(String(3), nullable=False, default="P0")
    progress: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    stop_reason: Mapped[str | None] = mapped_column(String(500))
    corpus_hash: Mapped[bytes | None] = mapped_column(LargeBinary(32))
    idempotency_key: Mapped[str] = mapped_column(String(200), nullable=False)
    requested_by_user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)


class InvestigationStep(TenantDomainMixin, Base):
    __tablename__ = "investigation_steps"
    __table_args__ = (
        UniqueConstraint("id", "tenant_id", name="uq_investigation_steps_id_tenant"),
        UniqueConstraint(
            "tenant_id",
            "run_id",
            "stage",
            "subject_key",
            name="uq_investigation_steps_subject",
        ),
        ForeignKeyConstraint(
            ("run_id", "tenant_id"),
            ("investigation_runs.id", "investigation_runs.tenant_id"),
            ondelete="CASCADE",
            name="fk_investigation_steps_run_tenant",
        ),
        ForeignKeyConstraint(
            ("background_job_id", "tenant_id"),
            ("background_jobs.id", "background_jobs.tenant_id"),
            ondelete="SET NULL",
            name="fk_investigation_steps_job_tenant",
        ),
        CheckConstraint(
            "stage IN ('P0','P1','P2','P3','P4','P5')", name="investigation_step_stage"
        ),
        CheckConstraint(
            "status IN "
            "('pending','ready','running','blocked','completed','failed','skipped','cancelled')",
            name="investigation_step_status",
        ),
        CheckConstraint(
            "jsonb_typeof(dependencies)='array'", name="investigation_step_dependencies"
        ),
        CheckConstraint("jsonb_typeof(result)='object'", name="investigation_step_result"),
        Index("ix_investigation_steps_run_status", "tenant_id", "run_id", "status"),
    )

    run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    stage: Mapped[str] = mapped_column(String(3), nullable=False)
    step_type: Mapped[str] = mapped_column(String(80), nullable=False)
    subject_key: Mapped[str] = mapped_column(String(320), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    dependencies: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    result: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    background_job_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ResearchEntity(TenantDomainMixin, Base):
    __tablename__ = "research_entities"
    __table_args__ = (
        UniqueConstraint("id", "tenant_id", name="uq_research_entities_id_tenant"),
        UniqueConstraint(
            "tenant_id",
            "run_id",
            "entity_kind",
            "normalized_name",
            name="uq_research_entities_identity",
        ),
        ForeignKeyConstraint(
            ("run_id", "tenant_id"),
            ("investigation_runs.id", "investigation_runs.tenant_id"),
            ondelete="CASCADE",
            name="fk_research_entities_run_tenant",
        ),
        ForeignKeyConstraint(
            ("canonical_actor_id", "tenant_id"),
            ("actors.id", "actors.tenant_id"),
            ondelete="SET NULL",
            name="fk_research_entities_actor_tenant",
        ),
        ForeignKeyConstraint(
            ("tenant_id", "reviewed_by_user_id"),
            ("tenant_memberships.tenant_id", "tenant_memberships.user_id"),
            ondelete="SET NULL",
            name="fk_research_entities_reviewer_membership",
        ),
        CheckConstraint(
            "entity_kind IN ('company','person','unknown')", name="research_entity_kind"
        ),
        CheckConstraint(
            "resolution_status IN ('candidate','verified','ambiguous','rejected')",
            name="research_entity_resolution",
        ),
        CheckConstraint("identity_confidence BETWEEN 0 AND 100", name="research_entity_confidence"),
        CheckConstraint("depth >= 0", name="research_entity_depth"),
        CheckConstraint("jsonb_typeof(identifiers)='object'", name="research_entity_identifiers"),
        CheckConstraint("jsonb_typeof(discovery_path)='array'", name="research_entity_path"),
        Index("ix_research_entities_run_status", "tenant_id", "run_id", "resolution_status"),
    )

    run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    exact_name: Mapped[str] = mapped_column(String(300), nullable=False)
    normalized_name: Mapped[str] = mapped_column(String(320), nullable=False)
    entity_kind: Mapped[str] = mapped_column(String(20), nullable=False, default="unknown")
    identifiers: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    depth: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    discovery_path: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    resolution_status: Mapped[str] = mapped_column(String(20), nullable=False, default="candidate")
    identity_confidence: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    gate_reason: Mapped[str | None] = mapped_column(String(500))
    canonical_actor_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    reviewed_by_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ResearchAlias(TenantDomainMixin, Base):
    __tablename__ = "research_aliases"
    __table_args__ = (
        UniqueConstraint("id", "tenant_id", name="uq_research_aliases_id_tenant"),
        UniqueConstraint(
            "tenant_id",
            "run_id",
            "entity_id",
            "normalized_alias",
            name="uq_research_aliases_entity",
        ),
        ForeignKeyConstraint(
            ("run_id", "tenant_id"),
            ("investigation_runs.id", "investigation_runs.tenant_id"),
            ondelete="CASCADE",
            name="fk_research_aliases_run_tenant",
        ),
        ForeignKeyConstraint(
            ("entity_id", "tenant_id"),
            ("research_entities.id", "research_entities.tenant_id"),
            ondelete="CASCADE",
            name="fk_research_aliases_entity_tenant",
        ),
        ForeignKeyConstraint(
            ("tenant_id", "reviewed_by_user_id"),
            ("tenant_memberships.tenant_id", "tenant_memberships.user_id"),
            ondelete="SET NULL",
            name="fk_research_aliases_reviewer_membership",
        ),
        CheckConstraint(
            "status IN ('candidate','verified','rejected')", name="research_alias_status"
        ),
        CheckConstraint("jsonb_typeof(evidence)='object'", name="research_alias_evidence"),
    )

    run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    entity_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    exact_alias: Mapped[str] = mapped_column(String(300), nullable=False)
    normalized_alias: Mapped[str] = mapped_column(String(320), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="candidate")
    evidence: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    reviewed_by_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ResearchRelation(TenantDomainMixin, Base):
    __tablename__ = "research_relations"
    __table_args__ = (
        UniqueConstraint("id", "tenant_id", name="uq_research_relations_id_tenant"),
        UniqueConstraint(
            "tenant_id",
            "run_id",
            "from_entity_id",
            "to_entity_id",
            "relation_type",
            name="uq_research_relations_edge",
        ),
        ForeignKeyConstraint(
            ("run_id", "tenant_id"),
            ("investigation_runs.id", "investigation_runs.tenant_id"),
            ondelete="CASCADE",
            name="fk_research_relations_run_tenant",
        ),
        ForeignKeyConstraint(
            ("from_entity_id", "tenant_id"),
            ("research_entities.id", "research_entities.tenant_id"),
            ondelete="CASCADE",
            name="fk_research_relations_from_tenant",
        ),
        ForeignKeyConstraint(
            ("to_entity_id", "tenant_id"),
            ("research_entities.id", "research_entities.tenant_id"),
            ondelete="CASCADE",
            name="fk_research_relations_to_tenant",
        ),
        CheckConstraint("from_entity_id <> to_entity_id", name="research_relation_distinct"),
        CheckConstraint(
            "status IN ('candidate','verified','disputed','rejected')",
            name="research_relation_status",
        ),
        CheckConstraint(
            "identity_confidence BETWEEN 0 AND 100 AND relation_confidence BETWEEN 0 AND 100",
            name="research_relation_confidence",
        ),
        CheckConstraint("jsonb_typeof(source_ref)='object'", name="research_relation_source"),
    )

    run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    from_entity_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    to_entity_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    relation_type: Mapped[str] = mapped_column(String(80), nullable=False)
    original_label: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    valid_from: Mapped[date | None] = mapped_column(Date)
    valid_to: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="candidate")
    identity_confidence: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    relation_confidence: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    source_ref: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)


class ResearchSourceSnapshot(TenantDomainMixin, Base):
    __tablename__ = "research_source_snapshots"
    __table_args__ = (
        UniqueConstraint("id", "tenant_id", name="uq_research_sources_id_tenant"),
        UniqueConstraint("tenant_id", "run_id", "content_hash", name="uq_research_sources_content"),
        ForeignKeyConstraint(
            ("run_id", "tenant_id"),
            ("investigation_runs.id", "investigation_runs.tenant_id"),
            ondelete="CASCADE",
            name="fk_research_sources_run_tenant",
        ),
        CheckConstraint("octet_length(content_hash)=32", name="research_source_hash"),
        CheckConstraint("jsonb_typeof(payload)='object'", name="research_source_payload"),
        CheckConstraint("jsonb_typeof(coverage)='object'", name="research_source_coverage"),
        Index("ix_research_sources_run_kind", "tenant_id", "run_id", "source_kind"),
    )

    run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    provider: Mapped[str] = mapped_column(String(80), nullable=False)
    source_kind: Mapped[str] = mapped_column(String(80), nullable=False)
    external_id: Mapped[str | None] = mapped_column(String(500))
    source_url: Mapped[str | None] = mapped_column(String(1500))
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    content_hash: Mapped[bytes] = mapped_column(LargeBinary(32), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    coverage: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    parser_version: Mapped[str] = mapped_column(String(80), nullable=False, default="oracle-v1")


class ProcurementParticipation(TenantDomainMixin, Base):
    __tablename__ = "procurement_participations"
    __table_args__ = (
        UniqueConstraint("id", "tenant_id", name="uq_procurement_participations_id_tenant"),
        UniqueConstraint(
            "tenant_id",
            "run_id",
            "entity_id",
            "folder_id",
            "lot_id",
            "role",
            name="uq_procurement_participations_role",
        ),
        ForeignKeyConstraint(
            ("run_id", "tenant_id"),
            ("investigation_runs.id", "investigation_runs.tenant_id"),
            ondelete="CASCADE",
            name="fk_procurement_participations_run_tenant",
        ),
        ForeignKeyConstraint(
            ("entity_id", "tenant_id"),
            ("research_entities.id", "research_entities.tenant_id"),
            ondelete="CASCADE",
            name="fk_procurement_participations_entity_tenant",
        ),
        CheckConstraint(
            "role IN "
            "('awardee','bidder_confirmed','lost','excluded','withdrawn','mentioned_unknown','unknown')",
            name="procurement_participation_role",
        ),
        CheckConstraint(
            "evidence_kind IN ('structured','documentary')",
            name="procurement_participation_evidence_kind",
        ),
        CheckConstraint(
            "confidence BETWEEN 0 AND 100", name="procurement_participation_confidence"
        ),
        CheckConstraint(
            "jsonb_typeof(source_ref)='object'", name="procurement_participation_source"
        ),
        Index("ix_procurement_participations_run_role", "tenant_id", "run_id", "role"),
    )

    run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    entity_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    folder_id: Mapped[str] = mapped_column(String(500), nullable=False)
    lot_id: Mapped[str] = mapped_column(String(300), nullable=False, default="")
    role: Mapped[str] = mapped_column(String(30), nullable=False)
    evidence_kind: Mapped[str] = mapped_column(String(20), nullable=False)
    exact_name: Mapped[str] = mapped_column(String(300), nullable=False)
    exact_identifier: Mapped[str | None] = mapped_column(String(100))
    received_tender_quantity: Mapped[int | None] = mapped_column(Integer)
    confidence: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    source_ref: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)


class ResearchClaim(TenantDomainMixin, Base):
    __tablename__ = "research_claims"
    __table_args__ = (
        UniqueConstraint("id", "tenant_id", name="uq_research_claims_id_tenant"),
        UniqueConstraint("tenant_id", "run_id", "claim_hash", name="uq_research_claims_hash"),
        ForeignKeyConstraint(
            ("run_id", "tenant_id"),
            ("investigation_runs.id", "investigation_runs.tenant_id"),
            ondelete="CASCADE",
            name="fk_research_claims_run_tenant",
        ),
        CheckConstraint("octet_length(claim_hash)=32", name="research_claim_hash"),
        CheckConstraint(
            "claim_kind IN ('fact','inference','opinion','recommendation','limitation')",
            name="research_claim_kind",
        ),
        CheckConstraint(
            "status IN ('candidate','verified','disputed','rejected','superseded')",
            name="research_claim_status",
        ),
        CheckConstraint("confidence BETWEEN 0 AND 100", name="research_claim_confidence"),
        CheckConstraint("jsonb_typeof(evidence_refs)='array'", name="research_claim_evidence"),
        Index("ix_research_claims_run_status", "tenant_id", "run_id", "status"),
    )

    run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    claim_kind: Mapped[str] = mapped_column(String(30), nullable=False)
    subject: Mapped[str] = mapped_column(String(500), nullable=False)
    predicate: Mapped[str] = mapped_column(String(120), nullable=False)
    object_value: Mapped[str] = mapped_column(Text, nullable=False)
    period_label: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="candidate")
    confidence: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    evidence_refs: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    claim_hash: Mapped[bytes] = mapped_column(LargeBinary(32), nullable=False)


class InvestigationError(ValueError):
    pass


class InvestigationNotFound(LookupError):
    pass


class InvestigationConflict(RuntimeError):
    pass


def normalize_identity_name(value: str, *, drop_legal_suffix: bool = False) -> str:
    """Normalize a legal/trade name for identity matching.

    When ``drop_legal_suffix=True``, trailing legal forms are removed, including
    punctuated Spanish forms such as ``S.L.`` / ``S.A.`` / ``S.L.U.`` (tokenized as
    ``S`` + ``L`` etc.) and compact forms already in :data:`LEGAL_SUFFIXES`.
    """

    normalized = unicodedata.normalize("NFKD", value)
    without_marks = "".join(
        character for character in normalized if unicodedata.category(character) != "Mn"
    )
    tokens = re.findall(r"[A-Z0-9]+", without_marks.upper())
    if drop_legal_suffix:
        while tokens:
            dropped = False
            for suffix in _MULTI_TOKEN_LEGAL_SUFFIXES:
                width = len(suffix)
                if len(tokens) >= width and tuple(tokens[-width:]) == suffix:
                    tokens = tokens[:-width]
                    dropped = True
                    break
            if not dropped and tokens[-1] in LEGAL_SUFFIXES:
                tokens.pop()
                dropped = True
            if not dropped:
                break
    return " ".join(tokens)[:320]


# CIF de sociedad española. Nunca se usa para personas físicas: el BORME no publica
# NIF personal y emparejar por nombre sin identificador sigue prohibido.
_SPANISH_COMPANY_CIF = re.compile(r"^[ABCDEFGHJNPQRSUVW]\d{7}[0-9A-J]$")


def normalize_spanish_company_tax_id(value: Any) -> str | None:
    """Normaliza CIF de sociedad. Rechaza NIF de persona (8 dígitos + letra)."""
    raw = re.sub(r"[\s.\-_/]", "", str(value or "")).upper()
    if not raw or not _SPANISH_COMPANY_CIF.fullmatch(raw):
        return None
    return raw


def extract_company_tax_id(*sources: Any) -> str | None:
    """Busca un CIF de sociedad en dicts de identificadores, nodos Signal o strings."""
    keys = (
        "tax_id",
        "cif",
        "vat",
        "vat_id",
        "nif",
        "company_tax_id",
        "winner_identifier",
        "identifier",
    )
    for source in sources:
        if source is None:
            continue
        if isinstance(source, str):
            tax_id = normalize_spanish_company_tax_id(source)
            if tax_id:
                return tax_id
            continue
        if not isinstance(source, Mapping):
            continue
        nested = source.get("identifiers")
        if isinstance(nested, Mapping):
            for key in keys:
                tax_id = normalize_spanish_company_tax_id(nested.get(key))
                if tax_id:
                    return tax_id
        for key in keys:
            tax_id = normalize_spanish_company_tax_id(source.get(key))
            if tax_id:
                return tax_id
        profile = source.get("profile")
        if isinstance(profile, Mapping):
            tax_id = normalize_spanish_company_tax_id(profile.get("tax_id") or profile.get("cif"))
            if tax_id:
                return tax_id
    return None


def _actor_tax_id_provenance_summary(actor: Actor) -> dict[str, Any]:
    """Honest provenance labels for durable/declared tax identity (never 'verified')."""

    identifiers = dict(actor.identifiers or {}) if isinstance(actor.identifiers, dict) else {}
    provenance = dict(actor.provenance or {}) if isinstance(actor.provenance, dict) else {}
    source = identifiers.get("tax_id_source")
    if not isinstance(source, dict):
        source = provenance.get("tax_id_assignment")
    if not isinstance(source, dict):
        source = provenance.get("tax_id_hydration")
    if not isinstance(source, dict):
        source = provenance.get("tax_id_column_backfill")
    if not isinstance(source, dict):
        source = {}

    declared = identifiers.get("tax_id_declared") or identifiers.get("tax_id")
    column_tax = getattr(actor, "tax_id", None)
    has_column = bool(column_tax)

    origin_kind = str(
        source.get("kind")
        or source.get("source")
        or source.get("origin")
        or ("column_durable" if has_column else "declared" if declared else "none")
    )
    # Map internal kinds to honest Spanish labels; never claim official verification.
    label_map = {
        "award_hydration": "hidratado desde adjudicación",
        "tax_id_hydration": "hidratado desde adjudicación",
        "identifiers.tax_id": "declarado en identificadores",
        "column_durable": "columna fiscal durable",
        "declared": "declarado",
        "manual": "declarado manualmente",
        "backfill": "backfill desde identificadores",
        "tax_id_column_backfill": "backfill desde identificadores",
    }
    origin_label = label_map.get(
        origin_kind, origin_kind.replace("_", " ") if origin_kind else "sin procedencia"
    )
    if has_column and origin_kind in {"none", "declared", "column_durable"}:
        origin_label = "columna fiscal durable (declarado; no verificación oficial)"
    elif not has_column and declared:
        origin_label = "declarado (sin columna durable; no verificación oficial)"

    return {
        "origin_kind": origin_kind or None,
        "origin_label": origin_label,
        "declared_tax_id": str(declared)[:80] if declared else None,
        "folder_id": str(source.get("folder_id") or "")[:240] or None,
        "winner_name": str(source.get("winner_name") or "")[:300] or None,
        "verified": False,  # never present declared NIF as officially verified
    }


def _serialize_alias_candidate_actor(actor: Actor) -> dict[str, Any]:
    from opn_oracle.oracle.actor_tax_id import actor_durable_tax_id, usable_company_tax_id

    column_tax = usable_company_tax_id(getattr(actor, "tax_id", None))
    durable = actor_durable_tax_id(actor)
    identifiers = dict(actor.identifiers or {}) if isinstance(actor.identifiers, dict) else {}
    return {
        "id": str(actor.id),
        "name": actor.canonical_name,
        "aliases": list(actor.aliases or []),
        "identifiers": identifiers,
        "tax_id": durable,
        "tax_id_scheme": actor.tax_id_scheme or identifiers.get("tax_id_scheme"),
        "tax_id_country": actor.tax_id_country or ("ES" if durable else None),
        "has_durable_tax_id_column": column_tax is not None,
        "tax_id_provenance": _actor_tax_id_provenance_summary(actor),
        "version": int(actor.version or 1),
    }


def _suggest_tax_winner(actors: list[Actor]) -> Actor:
    """Prefer the actor that already holds the durable tax_id column."""

    from opn_oracle.oracle.actor_tax_id import usable_company_tax_id

    with_column = [
        actor for actor in actors if usable_company_tax_id(getattr(actor, "tax_id", None))
    ]
    pool = with_column or list(actors)
    pool.sort(
        key=lambda actor: (
            getattr(actor, "created_at", None) or datetime.min.replace(tzinfo=UTC),
            str(actor.id),
        )
    )
    return pool[0]


def actor_alias_candidates(session: Session) -> dict[str, Any]:
    """Detect organization duplicates tax-first; never merge or mutate actors.

    Returns ``{"items": [...], "meta": {...}}`` with honest coverage metrics.
    Persons and other tenants are never mixed. Same-name pairs with distinct
    durable tax_ids are reported as blocked, not as mergeable candidates.
    """

    from opn_oracle.oracle.actor_tax_id import actor_durable_tax_id, usable_company_tax_id

    tenant_id = require_tenant_id()
    actors = list(
        session.scalars(
            select(Actor)
            .where(Actor.tenant_id == tenant_id, Actor.actor_type == "organization")
            .order_by(Actor.canonical_name, Actor.id)
        )
    )
    total_orgs = len(actors)
    with_tax = 0
    for actor in actors:
        if actor_durable_tax_id(actor):
            with_tax += 1

    # --- 1) Tax-id buckets (primary) ---
    tax_buckets: dict[str, list[Actor]] = {}
    for actor in actors:
        tax = actor_durable_tax_id(actor)
        if tax:
            tax_buckets.setdefault(tax, []).append(actor)

    covered_ids: set[uuid.UUID] = set()
    candidates: list[dict[str, Any]] = []
    count_tax_id = 0
    count_name = 0
    count_blocked = 0

    for tax_id, group in sorted(tax_buckets.items(), key=lambda item: item[0]):
        if len(group) < 2:
            continue
        winner = _suggest_tax_winner(group)
        for actor in group:
            covered_ids.add(actor.id)
        count_tax_id += 1
        candidates.append(
            {
                "identity_key": f"tax:es:{tax_id}",
                "match_reason": "tax_id",
                "status": "candidate",
                "priority": 100,
                "confidence": "high",
                "reason": (
                    f"Coincidencia fiscal por NIF/CIF durable {tax_id}. "
                    "Prioridad alta; el destino sugerido ya posee (o declara) esa identidad fiscal."
                ),
                "suggested_target_id": str(winner.id),
                "tax_id": tax_id,
                "actors": [_serialize_alias_candidate_actor(actor) for actor in group],
            }
        )

    # --- 2) Name buckets (fallback only for actors not already tax-matched) ---
    name_buckets: dict[str, list[Actor]] = {}
    for actor in actors:
        if actor.id in covered_ids:
            continue
        key = normalize_identity_name(actor.canonical_name, drop_legal_suffix=True)
        if key:
            name_buckets.setdefault(key, []).append(actor)

    for key, group in sorted(name_buckets.items(), key=lambda item: item[0]):
        if len(group) < 2:
            continue
        durable_taxes = {
            tax for actor in group if (tax := usable_company_tax_id(getattr(actor, "tax_id", None)))
        }
        # Distinct durable columns → blocked fiscal conflict (never name-merge).
        if len(durable_taxes) >= 2:
            count_blocked += 1
            candidates.append(
                {
                    "identity_key": f"name-blocked:{key}",
                    "match_reason": "tax_id_conflict",
                    "status": "blocked",
                    "priority": 50,
                    "confidence": "blocked",
                    "reason": (
                        "Misma denominación normalizada pero NIF/CIF durables distintos. "
                        "Fusión bloqueada; no se infiere identidad fiscal por nombre."
                    ),
                    "suggested_target_id": None,
                    "tax_id": None,
                    "blocking_tax_ids": sorted(durable_taxes),
                    "actors": [_serialize_alias_candidate_actor(actor) for actor in group],
                }
            )
            continue

        # Prefer the one that holds a durable column as suggested target when present.
        with_column = [
            actor for actor in group if usable_company_tax_id(getattr(actor, "tax_id", None))
        ]
        suggested = with_column[0] if with_column else group[0]
        count_name += 1
        candidates.append(
            {
                "identity_key": key,
                "match_reason": "normalized_name",
                "status": "candidate",
                "priority": 10,
                "confidence": "low",
                "reason": (
                    "Coincidencia de denominación sin forma jurídica (p. ej. SL / S.L. / SA). "
                    "No se infiere NIF por nombre; requiere revisión humana cautelosa."
                ),
                "suggested_target_id": str(suggested.id),
                "tax_id": usable_company_tax_id(getattr(suggested, "tax_id", None)),
                "actors": [_serialize_alias_candidate_actor(actor) for actor in group],
            }
        )

    # tax_id matches first, then blocked, then name; stable within each band.
    candidates.sort(
        key=lambda item: (
            0 if item["match_reason"] == "tax_id" else 1 if item["status"] == "blocked" else 2,
            -int(item.get("priority") or 0),
            str(item.get("identity_key") or ""),
        )
    )

    coverage_pct = round((with_tax / total_orgs) * 100.0, 2) if total_orgs else 0.0
    meta = {
        "organizations_evaluated": total_orgs,
        "organizations_with_tax_id": with_tax,
        "tax_id_coverage_pct": coverage_pct,
        "criteria_evaluated": ["tax_id", "normalized_name"],
        "counts": {
            "tax_id": count_tax_id,
            "normalized_name": count_name,
            "tax_id_conflict_blocked": count_blocked,
            "candidates_mergeable": count_tax_id + count_name,
            "candidates_blocked": count_blocked,
            "total_items": len(candidates),
        },
        "limitations": (
            f"{with_tax}/{total_orgs} organizaciones con NIF/CIF durable evaluable. "
            "Solo se proponen coincidencias bajo los criterios tax_id y nombre normalizado "
            "sin forma jurídica; no hay verificación oficial del NIF."
        ),
        "empty_state_message": (
            "No hay candidatos bajo los criterios evaluados "
            f"(tax_id y denominación normalizada). Cobertura NIF: {with_tax}/{total_orgs} "
            f"({coverage_pct}%). Esto no implica ausencia de duplicados: la detección está "
            "limitada por la cobertura fiscal y por el criterio nominal cauteloso."
        ),
    }
    return {"items": candidates, "meta": meta}


def _canonical_payload(value: Mapping[str, Any]) -> tuple[bytes, dict[str, Any]]:
    payload = json.loads(json.dumps(dict(value), ensure_ascii=False, sort_keys=True, default=str))
    encoded = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode()
    return hashlib.sha256(encoded).digest(), payload


def _bounded_limits(value: Mapping[str, Any] | None) -> dict[str, int]:
    raw = dict(value or {})
    defaults = {
        "max_depth": 2,
        "max_entities": 150,
        "max_documents": 2000,
        "max_ai_calls": 250,
        "max_runtime_minutes": 360,
    }
    limits: dict[str, int] = {}
    ranges = {
        "max_depth": (1, 3),
        "max_entities": (1, 500),
        "max_documents": (0, 5000),
        "max_ai_calls": (0, 1000),
        "max_runtime_minutes": (10, 1440),
    }
    for key, default in defaults.items():
        try:
            selected = int(raw.get(key, default))
        except (TypeError, ValueError) as error:
            raise InvestigationError(f"{key} debe ser entero.") from error
        minimum, maximum = ranges[key]
        if not minimum <= selected <= maximum:
            raise InvestigationError(f"{key} debe estar entre {minimum} y {maximum}.")
        limits[key] = selected
    return limits


def create_investigation(
    session: Session,
    *,
    dossier_id: uuid.UUID,
    payload: Mapping[str, Any],
    idempotency_key: str,
    requested_by_user_id: uuid.UUID,
    request_id: str | None,
) -> InvestigationRun:
    tenant_id = require_tenant_id()
    if not 8 <= len(idempotency_key) <= 200:
        raise InvestigationError("Idempotency-Key debe tener entre 8 y 200 caracteres.")
    existing = session.scalar(
        select(InvestigationRun).where(
            InvestigationRun.tenant_id == tenant_id,
            InvestigationRun.idempotency_key == idempotency_key,
        )
    )
    if existing is not None:
        return existing
    dossier = session.scalar(
        select(StrategicDossier).where(
            StrategicDossier.id == dossier_id,
            StrategicDossier.tenant_id == tenant_id,
            StrategicDossier.status != "archived",
        )
    )
    if dossier is None:
        raise InvestigationNotFound("Expediente no encontrado.")
    question = " ".join(str(payload.get("question") or "").strip().split())
    seed_name = " ".join(str(payload.get("seed_name") or "").strip().split())
    seed_kind = str(payload.get("seed_kind") or "unknown").strip().casefold()
    if not 10 <= len(question) <= 5000:
        raise InvestigationError("La pregunta debe contener entre 10 y 5000 caracteres.")
    if not 2 <= len(seed_name) <= 300:
        raise InvestigationError("La entidad semilla debe contener entre 2 y 300 caracteres.")
    if seed_kind not in {"company", "person", "unknown"}:
        raise InvestigationError("seed_kind no es válido.")
    raw_identifiers = payload.get("seed_identifiers") or {}
    if not isinstance(raw_identifiers, Mapping):
        raise InvestigationError("seed_identifiers debe ser un objeto.")
    identifiers = dict(raw_identifiers)
    if seed_kind == "company":
        seed_tax = extract_company_tax_id(identifiers)
        if seed_tax:
            identifiers["tax_id"] = seed_tax
            identifiers.setdefault("tax_id_scheme", "ES_CIF")
    limits_value = payload.get("limits")
    if limits_value is not None and not isinstance(limits_value, Mapping):
        raise InvestigationError("limits debe ser un objeto.")
    now = datetime.now(UTC)
    run = InvestigationRun(
        tenant_id=tenant_id,
        dossier_id=dossier.id,
        question=question,
        seed_name=seed_name,
        seed_kind=seed_kind,
        seed_identifiers=dict(identifiers),
        cutoff_at=now,
        period_start=_date_or_none(payload.get("period_start")),
        period_end=_date_or_none(payload.get("period_end")),
        limits=_bounded_limits(limits_value),
        source_policy={
            "allowed": ["signal_borme", "signal_placsp", "placsp_documents"],
            "raw_corpus_retained": False,
            "absence_semantics": "not_located_in_consulted_corpus",
        },
        idempotency_key=idempotency_key,
        requested_by_user_id=requested_by_user_id,
    )
    if run.period_start and run.period_end and run.period_start > run.period_end:
        raise InvestigationError("period_start no puede ser posterior a period_end.")
    session.add(run)
    session.flush()
    seed = ResearchEntity(
        tenant_id=tenant_id,
        run_id=run.id,
        exact_name=seed_name,
        normalized_name=normalize_identity_name(seed_name),
        entity_kind=seed_kind,
        identifiers=dict(identifiers),
        depth=0,
        discovery_path=[],
        resolution_status="candidate",
        identity_confidence=100 if identifiers else 0,
        gate_reason=(
            "CIF de sociedad en semilla; confirma la entidad antes de expandir."
            if seed_kind == "company" and extract_company_tax_id(identifiers)
            else "Confirma la identidad raíz antes de consultar o expandir fuentes."
        ),
    )
    session.add(seed)
    for index, stage in enumerate(MACRO_STAGES):
        session.add(
            InvestigationStep(
                tenant_id=tenant_id,
                run_id=run.id,
                stage=stage,
                step_type={
                    "P0": "seed_identity",
                    "P1": "registry_core",
                    "P2": "identity_frontier",
                    "P3": "procurement",
                    "P4": "claims_metrics",
                    "P5": "report",
                }[stage],
                subject_key="run",
                status="blocked" if stage == "P0" else "pending",
                dependencies=[] if index == 0 else [MACRO_STAGES[index - 1]],
            )
        )
    append_audit_event(
        session,
        action="investigation.created",
        resource_type="investigation_run",
        resource_id=run.id,
        dossier_id=dossier.id,
        result="success",
        request_id=request_id,
        metadata={"protocol_version": run.protocol_version},
    )
    session.commit()
    return run


def _date_or_none(value: Any) -> date | None:
    if value in (None, ""):
        return None
    try:
        return date.fromisoformat(str(value))
    except ValueError as error:
        raise InvestigationError("Las fechas deben usar YYYY-MM-DD.") from error


def get_investigation(session: Session, run_id: uuid.UUID) -> InvestigationRun:
    tenant_id = require_tenant_id()
    run = session.scalar(
        select(InvestigationRun).where(
            InvestigationRun.id == run_id,
            InvestigationRun.tenant_id == tenant_id,
        )
    )
    if run is None:
        raise InvestigationNotFound("Investigación no encontrada.")
    return run


def review_research_entity(
    session: Session,
    *,
    run_id: uuid.UUID,
    entity_id: uuid.UUID,
    decision: str,
    actor_id: uuid.UUID,
    alias: str | None = None,
) -> ResearchEntity:
    run = get_investigation(session, run_id)
    entity = session.scalar(
        select(ResearchEntity)
        .where(
            ResearchEntity.id == entity_id,
            ResearchEntity.run_id == run.id,
            ResearchEntity.tenant_id == run.tenant_id,
        )
        .with_for_update()
    )
    if entity is None:
        raise InvestigationNotFound("Entidad candidata no encontrada.")
    now = datetime.now(UTC)
    if decision == "verify":
        entity.resolution_status = "verified"
        entity.identity_confidence = max(entity.identity_confidence, 80)
        entity.gate_reason = None
    elif decision == "reject":
        entity.resolution_status = "rejected"
        entity.gate_reason = "Rechazada por revisión humana."
    elif decision == "add_alias":
        exact_alias = " ".join(str(alias or "").strip().split())
        if not 2 <= len(exact_alias) <= 300:
            raise InvestigationError("El alias debe contener entre 2 y 300 caracteres.")
        normalized = normalize_identity_name(exact_alias)
        existing = session.scalar(
            select(ResearchAlias).where(
                ResearchAlias.run_id == run.id,
                ResearchAlias.entity_id == entity.id,
                ResearchAlias.normalized_alias == normalized,
            )
        )
        if existing is None:
            session.add(
                ResearchAlias(
                    tenant_id=run.tenant_id,
                    run_id=run.id,
                    entity_id=entity.id,
                    exact_alias=exact_alias,
                    normalized_alias=normalized,
                    status="verified",
                    evidence={"decision": "human_review"},
                    reviewed_by_user_id=actor_id,
                    reviewed_at=now,
                )
            )
    else:
        raise InvestigationError("Decisión de identidad no válida.")
    entity.reviewed_by_user_id = actor_id
    entity.reviewed_at = now
    if entity.depth == 0 and decision == "verify":
        step = session.scalar(
            select(InvestigationStep).where(
                InvestigationStep.run_id == run.id,
                InvestigationStep.stage == "P0",
                InvestigationStep.subject_key == "run",
            )
        )
        assert step is not None
        step.status = "completed"
        step.result = {"seed_entity_id": str(entity.id), "reviewed_by_user_id": str(actor_id)}
        step.finished_at = now
        run.status = "ready"
        run.progress = 10
        run.version += 1
    append_audit_event(
        session,
        action=f"investigation.entity.{decision}",
        resource_type="research_entity",
        resource_id=entity.id,
        dossier_id=run.dossier_id,
        result="success",
        metadata={"run_id": str(run.id)},
    )
    session.commit()
    return entity


def set_investigation_state(
    session: Session,
    *,
    run_id: uuid.UUID,
    action: str,
) -> InvestigationRun:
    run = get_investigation(session, run_id)
    if action == "pause" and run.status in {"ready", "running"}:
        run.status = "paused"
    elif action == "resume" and run.status in {"awaiting_review", "ready", "paused", "failed"}:
        seed = session.scalar(
            select(ResearchEntity).where(
                ResearchEntity.run_id == run.id,
                ResearchEntity.depth == 0,
                ResearchEntity.resolution_status == "verified",
            )
        )
        if seed is None:
            raise InvestigationConflict("Confirma la identidad raíz antes de reanudar.")
        run.status = "running"
    elif action == "cancel" and run.status not in {"completed", "cancelled"}:
        run.status = "cancelled"
        run.stop_reason = "Cancelación solicitada por una persona."
    else:
        raise InvestigationConflict("La transición solicitada no es válida.")
    run.version += 1
    session.commit()
    return run


def _source_snapshot(
    session: Session,
    *,
    run: InvestigationRun,
    source_kind: str,
    external_id: str,
    payload: Mapping[str, Any],
    coverage: Mapping[str, Any],
) -> ResearchSourceSnapshot:
    digest, canonical = _canonical_payload(payload)
    existing = session.scalar(
        select(ResearchSourceSnapshot).where(
            ResearchSourceSnapshot.run_id == run.id,
            ResearchSourceSnapshot.content_hash == digest,
        )
    )
    if existing is not None:
        return existing
    source = ResearchSourceSnapshot(
        tenant_id=run.tenant_id,
        run_id=run.id,
        provider="signal-avanza",
        source_kind=source_kind,
        external_id=external_id[:500],
        captured_at=datetime.now(UTC),
        content_hash=digest,
        payload=canonical,
        coverage=dict(coverage),
    )
    session.add(source)
    session.flush()
    return source


def _node_name(node: Mapping[str, Any]) -> str:
    return " ".join(
        str(node.get("name") or node.get("label") or node.get("title") or "").strip().split()
    )[:300]


def _node_kind(node: Mapping[str, Any]) -> str:
    value = str(node.get("type") or node.get("kind") or "").casefold()
    if value in {"company", "organization", "organisation", "empresa"}:
        return "company"
    if value in {"person", "persona"}:
        return "person"
    return "unknown"


def _merge_entity_identifiers(
    entity: ResearchEntity,
    identifiers: Mapping[str, Any] | None,
) -> None:
    if not identifiers:
        return
    merged = dict(entity.identifiers or {})
    for key, value in identifiers.items():
        if value is None or value == "":
            continue
        # Solo persistir tax_id/cif/nif si es un CIF de sociedad válido.
        if key in {"tax_id", "cif", "nif", "vat", "vat_id", "company_tax_id"}:
            tax_id = normalize_spanish_company_tax_id(value)
            if tax_id and entity.entity_kind == "company":
                merged["tax_id"] = tax_id
                merged["tax_id_scheme"] = "ES_CIF"
            continue
        if key not in merged or not merged.get(key):
            merged[key] = value
    tax_id = extract_company_tax_id(merged)
    entity.identifiers = merged
    if tax_id and entity.entity_kind == "company" and entity.identity_confidence < 90:
        entity.identity_confidence = 90
        entity.gate_reason = (
            "CIF de sociedad capturado; la identidad societaria es estable. "
            "Las personas vinculadas siguen requiriendo revisión humana."
        )


def _upsert_entity(
    session: Session,
    *,
    run: InvestigationRun,
    name: str,
    kind: str,
    depth: int,
    discovery_path: list[Any],
    identifiers: Mapping[str, Any] | None = None,
) -> ResearchEntity:
    normalized = normalize_identity_name(name)
    tax_id = extract_company_tax_id(identifiers) if kind == "company" else None
    entity: ResearchEntity | None = None
    # Sociedades: desduplicar por CIF cuando existe. Nunca emparejar personas por
    # parecido de nombre ni por NIF inventado.
    if tax_id:
        for candidate in session.scalars(
            select(ResearchEntity).where(
                ResearchEntity.run_id == run.id,
                ResearchEntity.entity_kind == "company",
            )
        ):
            if extract_company_tax_id(candidate.identifiers) == tax_id:
                entity = candidate
                break
    if entity is None:
        entity = session.scalar(
            select(ResearchEntity).where(
                ResearchEntity.run_id == run.id,
                ResearchEntity.entity_kind == kind,
                ResearchEntity.normalized_name == normalized,
            )
        )
    if entity is None:
        entity = ResearchEntity(
            tenant_id=run.tenant_id,
            run_id=run.id,
            exact_name=name,
            normalized_name=normalized,
            entity_kind=kind,
            depth=depth,
            discovery_path=discovery_path,
            resolution_status="candidate",
            identity_confidence=0,
            gate_reason=(
                "Las personas y entidades sin identificador requieren revisión antes de expandirse."
            ),
            identifiers=dict(identifiers or {}),
        )
        session.add(entity)
        session.flush()
    else:
        if depth < entity.depth:
            entity.depth = depth
    _merge_entity_identifiers(entity, identifiers)
    return entity


def process_investigation_run(
    session: Session,
    *,
    run_id: uuid.UUID,
) -> dict[str, Any]:
    """Execute the deterministic MVP passes against bounded Signal reads.

    P2 intentionally remains a human checkpoint for newly discovered identities.  P3
    queries only verified companies, so a person can safely resume the same run after
    reviewing more candidates without duplicating rows or claims.
    """

    run = get_investigation(session, run_id)
    if run.status == "cancelled":
        return {"status": "cancelled", "run_id": str(run.id)}
    if run.status not in {"awaiting_review", "ready", "running", "paused", "failed"}:
        raise InvestigationConflict("La investigación no está lista para ejecutarse.")
    seed = session.scalar(
        select(ResearchEntity).where(
            ResearchEntity.run_id == run.id,
            ResearchEntity.depth == 0,
            ResearchEntity.resolution_status == "verified",
        )
    )
    if seed is None:
        raise InvestigationConflict("La identidad raíz no está verificada.")
    run.status = "running"
    run.stage = "P1"
    run.progress = 15
    _mark_step(session, run.id, "P1", "running")
    external_tenant_id = resolve_signal_external_tenant_id_for_tenant(run.tenant_id)
    graph = cached_graph(
        tenant_id=str(run.tenant_id),
        name=seed.exact_name,
        kind="person" if seed.entity_kind == "person" else "company",
        depth=int(run.limits["max_depth"]),
        active_only=False,
        external_tenant_id=external_tenant_id,
    )
    graph_source = _source_snapshot(
        session,
        run=run,
        source_kind="entity_graph",
        external_id=f"{seed.entity_kind}:{seed.normalized_name}",
        payload=graph,
        coverage={
            "depth": run.limits["max_depth"],
            "truncated": bool(graph.get("truncated")),
            "absence_semantics": "not_located_in_consulted_corpus",
        },
    )
    nodes = [item for item in graph.get("nodes", []) if isinstance(item, Mapping)]
    node_entities: dict[str, ResearchEntity] = {}
    for node in nodes[: int(run.limits["max_entities"])]:
        name = _node_name(node)
        if not name:
            continue
        kind = _node_kind(node)
        node_identifiers: dict[str, Any] = {}
        tax_id = extract_company_tax_id(node) if kind == "company" else None
        if tax_id:
            node_identifiers = {
                "tax_id": tax_id,
                "tax_id_scheme": "ES_CIF",
                "tax_id_source": "signal_graph",
            }
        entity = _upsert_entity(
            session,
            run=run,
            name=name,
            kind=kind,
            depth=max(1, int(node.get("depth") or 1)),
            discovery_path=[{"source_id": str(graph_source.id), "via": "entity_graph"}],
            identifiers=node_identifiers or None,
        )
        for key in ("id", "key", "node_id"):
            value = node.get(key)
            if value is not None:
                node_entities[str(value)] = entity
        node_entities[normalize_identity_name(name)] = entity
        if tax_id:
            node_entities[f"tax_id:{tax_id}"] = entity
    node_entities.setdefault(seed.normalized_name, seed)
    if seed.entity_kind == "company":
        seed_tax = extract_company_tax_id(seed.identifiers, run.seed_identifiers)
        if seed_tax:
            node_entities[f"tax_id:{seed_tax}"] = seed
    relations_created = 0
    for edge in [item for item in graph.get("edges", []) if isinstance(item, Mapping)]:
        source_value = edge.get("source") or edge.get("from") or edge.get("source_name")
        target_value = edge.get("target") or edge.get("to") or edge.get("target_name")
        from_entity = node_entities.get(str(source_value)) or node_entities.get(
            normalize_identity_name(str(source_value or ""))
        )
        to_entity = node_entities.get(str(target_value)) or node_entities.get(
            normalize_identity_name(str(target_value or ""))
        )
        if from_entity is None or to_entity is None or from_entity.id == to_entity.id:
            continue
        relation_type = str(
            edge.get("role_keys", [None])[0]
            if isinstance(edge.get("role_keys"), list) and edge.get("role_keys")
            else edge.get("role") or edge.get("type") or "registry_relation"
        )[:80]
        existing = session.scalar(
            select(ResearchRelation).where(
                ResearchRelation.run_id == run.id,
                ResearchRelation.from_entity_id == from_entity.id,
                ResearchRelation.to_entity_id == to_entity.id,
                ResearchRelation.relation_type == relation_type,
            )
        )
        if existing is None:
            session.add(
                ResearchRelation(
                    tenant_id=run.tenant_id,
                    run_id=run.id,
                    from_entity_id=from_entity.id,
                    to_entity_id=to_entity.id,
                    relation_type=relation_type,
                    original_label=str(edge.get("role") or edge.get("type") or "")[:200],
                    status="candidate",
                    identity_confidence=0,
                    relation_confidence=60,
                    source_ref={"source_id": str(graph_source.id)},
                )
            )
            relations_created += 1
    _mark_step(
        session,
        run.id,
        "P1",
        "completed",
        {"nodes": len(node_entities), "relations_created": relations_created},
    )
    _mark_step(
        session,
        run.id,
        "P2",
        "blocked",
        {"reason": "identity_review", "candidate_count": len(node_entities) - 1},
    )
    run.stage = "P3"
    run.progress = 45
    _mark_step(session, run.id, "P3", "running")
    participations_created = 0
    verified_companies = list(
        session.scalars(
            select(ResearchEntity).where(
                ResearchEntity.run_id == run.id,
                ResearchEntity.entity_kind == "company",
                ResearchEntity.resolution_status == "verified",
            )
        )
    )
    for entity in verified_companies[: int(run.limits["max_entities"])]:
        awards = cached_awards(
            tenant_id=str(run.tenant_id),
            company=entity.exact_name,
            buyer=None,
            limit=200,
            offset=0,
        )
        source = _source_snapshot(
            session,
            run=run,
            source_kind="procurement_awards",
            external_id=entity.normalized_name,
            payload=awards,
            coverage={
                "role": "awardee",
                "nominal_non_awardees_available": False,
                "absence_semantics": "not_located_in_consulted_corpus",
            },
        )
        items = awards.get("items")
        if not isinstance(items, list):
            items = awards.get("results", [])
        for item in [row for row in items if isinstance(row, Mapping)]:
            folder_id = str(
                item.get("folder_id") or item.get("contract_folder_id") or item.get("id") or ""
            )[:500]
            if not folder_id:
                continue
            lot_id = str(item.get("lot_id") or item.get("lot") or "")[:300]
            existing_participation = session.scalar(
                select(ProcurementParticipation).where(
                    ProcurementParticipation.run_id == run.id,
                    ProcurementParticipation.entity_id == entity.id,
                    ProcurementParticipation.folder_id == folder_id,
                    ProcurementParticipation.lot_id == lot_id,
                    ProcurementParticipation.role == "awardee",
                )
            )
            if existing_participation is not None:
                continue
            received = item.get("received_tender_quantity")
            if isinstance(received, bool) or not isinstance(received, int) or received < 0:
                received = None
            award_tax_id = extract_company_tax_id(item)
            if award_tax_id:
                _merge_entity_identifiers(
                    entity,
                    {
                        "tax_id": award_tax_id,
                        "tax_id_scheme": "ES_CIF",
                        "tax_id_source": "procurement_award",
                    },
                )
            session.add(
                ProcurementParticipation(
                    tenant_id=run.tenant_id,
                    run_id=run.id,
                    entity_id=entity.id,
                    folder_id=folder_id,
                    lot_id=lot_id,
                    role="awardee",
                    evidence_kind="structured",
                    exact_name=entity.exact_name,
                    exact_identifier=(
                        award_tax_id
                        or (
                            str(item.get("winner_identifier"))[:100]
                            if item.get("winner_identifier")
                            else None
                        )
                    ),
                    received_tender_quantity=received,
                    confidence=100,
                    source_ref={"source_id": str(source.id), "folder_id": folder_id},
                )
            )
            participations_created += 1
    session.flush()
    _mark_step(
        session,
        run.id,
        "P3",
        "completed",
        {
            "verified_companies": len(verified_companies),
            "participations_created": participations_created,
            "non_awardee_identity_coverage": "unavailable",
        },
    )
    run.stage = "P4"
    run.progress = 75
    _mark_step(session, run.id, "P4", "running")
    claims_created = _materialize_claims(session, run)
    _mark_step(
        session,
        run.id,
        "P4",
        "completed",
        {"claims_created": claims_created},
    )
    run.stage = "P5"
    run.progress = 90
    run.status = "awaiting_review"
    _mark_step(
        session,
        run.id,
        "P5",
        "blocked",
        {
            "reason": "human_publication_review",
            "report_contract": "deterministic_factual_mvp",
            "report_preview_available": True,
        },
    )
    source_hashes = list(
        session.scalars(
            select(ResearchSourceSnapshot.content_hash)
            .where(ResearchSourceSnapshot.run_id == run.id)
            .order_by(ResearchSourceSnapshot.content_hash)
        )
    )
    run.corpus_hash = hashlib.sha256(b"".join(source_hashes)).digest()
    run.version += 1
    session.commit()
    return investigation_summary(session, run)


def _mark_step(
    session: Session,
    run_id: uuid.UUID,
    stage: str,
    status: str,
    result: Mapping[str, Any] | None = None,
) -> None:
    step = session.scalar(
        select(InvestigationStep).where(
            InvestigationStep.run_id == run_id,
            InvestigationStep.stage == stage,
            InvestigationStep.subject_key == "run",
        )
    )
    if step is None:
        raise InvestigationConflict(f"Falta el paso durable {stage}.")
    now = datetime.now(UTC)
    if status == "running" and step.started_at is None:
        step.started_at = now
    if status in {"completed", "failed", "skipped", "cancelled"}:
        step.finished_at = now
    step.status = status
    if result is not None:
        step.result = dict(result)


def _materialize_claims(session: Session, run: InvestigationRun) -> int:
    created = 0
    rows = session.execute(
        select(ProcurementParticipation, ResearchEntity)
        .join(
            ResearchEntity,
            (ResearchEntity.id == ProcurementParticipation.entity_id)
            & (ResearchEntity.tenant_id == ProcurementParticipation.tenant_id),
        )
        .where(ProcurementParticipation.run_id == run.id)
    ).all()
    for participation, entity in rows:
        value = {
            "subject": entity.exact_name,
            "predicate": "adjudicatario_en",
            "object": participation.folder_id,
            "lot": participation.lot_id,
            "role": participation.role,
        }
        digest, _ = _canonical_payload(value)
        existing = session.scalar(
            select(ResearchClaim).where(
                ResearchClaim.run_id == run.id,
                ResearchClaim.claim_hash == digest,
            )
        )
        if existing is not None:
            continue
        session.add(
            ResearchClaim(
                tenant_id=run.tenant_id,
                run_id=run.id,
                claim_kind="fact",
                subject=entity.exact_name,
                predicate="adjudicatario_en",
                object_value=participation.folder_id,
                period_label="",
                status="verified",
                confidence=100,
                evidence_refs=[participation.source_ref],
                claim_hash=digest,
            )
        )
        created += 1
    limitation = {
        "subject": run.seed_name,
        "predicate": "coverage_limitation",
        "object": "La identidad nominal de no adjudicatarios no está disponible estructuradamente.",
    }
    digest, _ = _canonical_payload(limitation)
    if (
        session.scalar(
            select(ResearchClaim).where(
                ResearchClaim.run_id == run.id,
                ResearchClaim.claim_hash == digest,
            )
        )
        is None
    ):
        session.add(
            ResearchClaim(
                tenant_id=run.tenant_id,
                run_id=run.id,
                claim_kind="limitation",
                subject=run.seed_name,
                predicate="coverage_limitation",
                object_value=limitation["object"],
                status="verified",
                confidence=100,
                evidence_refs=[],
                claim_hash=digest,
            )
        )
        created += 1
    return created


def investigation_summary(session: Session, run: InvestigationRun) -> dict[str, Any]:
    entities = list(
        session.scalars(
            select(ResearchEntity)
            .where(ResearchEntity.run_id == run.id)
            .order_by(ResearchEntity.depth, ResearchEntity.exact_name)
        )
    )
    steps = list(
        session.scalars(
            select(InvestigationStep)
            .where(InvestigationStep.run_id == run.id)
            .order_by(InvestigationStep.stage)
        )
    )
    aliases = list(
        session.scalars(
            select(ResearchAlias)
            .where(ResearchAlias.run_id == run.id)
            .order_by(ResearchAlias.exact_alias)
        )
    )
    relations = list(
        session.scalars(
            select(ResearchRelation)
            .where(ResearchRelation.run_id == run.id)
            .order_by(ResearchRelation.relation_type, ResearchRelation.created_at)
        )
    )
    participations = list(
        session.scalars(
            select(ProcurementParticipation)
            .where(ProcurementParticipation.run_id == run.id)
            .order_by(ProcurementParticipation.folder_id, ProcurementParticipation.lot_id)
        )
    )
    claims = list(
        session.scalars(
            select(ResearchClaim)
            .where(ResearchClaim.run_id == run.id)
            .order_by(ResearchClaim.claim_kind, ResearchClaim.subject)
        )
    )
    completed_stages = {step.stage for step in steps if step.status == "completed"}
    blocked_stages = {step.stage for step in steps if step.status == "blocked"}
    pending_stages = {
        step.stage for step in steps if step.status in {"pending", "ready", "running"}
    }
    # MVP only completes P1/P3/P4; P2 (identity frontier expansion) and P5 (report)
    # stay blocked pending human review. Never present that as a full network map.
    incomplete_reasons: list[str] = []
    if "P2" in blocked_stages:
        incomplete_reasons.append(
            "P2_identity_frontier_blocked_pending_human_review_no_level_expansion"
        )
    if "P5" in blocked_stages:
        incomplete_reasons.append("P5_report_blocked_pending_human_publication_review")
    if pending_stages:
        incomplete_reasons.append("stages_pending:" + ",".join(sorted(pending_stages)))
    if completed_stages != set(MACRO_STAGES):
        missing = [stage for stage in MACRO_STAGES if stage not in completed_stages]
        incomplete_reasons.append("stages_not_completed:" + ",".join(missing))
    # Dedupe while preserving order.
    seen_reasons: set[str] = set()
    ordered_reasons: list[str] = []
    for reason in incomplete_reasons:
        if reason not in seen_reasons:
            seen_reasons.add(reason)
            ordered_reasons.append(reason)
    completeness = "complete" if not ordered_reasons else "incomplete"
    return {
        "id": str(run.id),
        "dossier_id": str(run.dossier_id),
        "question": run.question,
        "seed": {
            "name": run.seed_name,
            "kind": run.seed_kind,
            "identifiers": dict(run.seed_identifiers or {}),
        },
        "status": run.status,
        "stage": run.stage,
        "completeness": completeness,
        "incompleteness_reasons": ordered_reasons,
        "progress": run.progress,
        "cutoff_at": run.cutoff_at.isoformat(),
        "period_start": run.period_start.isoformat() if run.period_start else None,
        "period_end": run.period_end.isoformat() if run.period_end else None,
        "protocol_version": run.protocol_version,
        "source_policy_version": run.source_policy_version,
        "limits": dict(run.limits or {}),
        "source_policy": dict(run.source_policy or {}),
        "corpus_hash": run.corpus_hash.hex() if run.corpus_hash else None,
        "stop_reason": run.stop_reason,
        "version": run.version,
        "created_at": run.created_at.isoformat(),
        "updated_at": run.updated_at.isoformat(),
        "steps": [
            {
                "id": str(step.id),
                "stage": step.stage,
                "step_type": step.step_type,
                "status": step.status,
                "result": dict(step.result or {}),
            }
            for step in steps
        ],
        "counts": {
            "entities": len(entities),
            "verified_entities": sum(
                1 for entity in entities if entity.resolution_status == "verified"
            ),
            "candidate_entities": sum(
                1 for entity in entities if entity.resolution_status == "candidate"
            ),
            "relations": len(relations),
            "procurement_participations": len(participations),
            "claims": len(claims),
        },
        "entities": [
            {
                "id": str(entity.id),
                "name": entity.exact_name,
                "normalized_name": entity.normalized_name,
                "kind": entity.entity_kind,
                "identifiers": dict(entity.identifiers or {}),
                "depth": entity.depth,
                "resolution_status": entity.resolution_status,
                "identity_confidence": entity.identity_confidence,
                "gate_reason": entity.gate_reason,
                "canonical_actor_id": (
                    str(entity.canonical_actor_id) if entity.canonical_actor_id else None
                ),
                "aliases": [
                    {
                        "id": str(item.id),
                        "value": item.exact_alias,
                        "status": item.status,
                    }
                    for item in aliases
                    if item.entity_id == entity.id
                ],
            }
            for entity in entities
        ],
        "relations": [
            {
                "id": str(relation.id),
                "from_entity_id": str(relation.from_entity_id),
                "to_entity_id": str(relation.to_entity_id),
                "relation_type": relation.relation_type,
                "status": relation.status,
                "identity_confidence": relation.identity_confidence,
                "relation_confidence": relation.relation_confidence,
                "source_ref": dict(relation.source_ref or {}),
            }
            for relation in relations[:200]
        ],
        "procurement_participations": [
            {
                "id": str(participation.id),
                "entity_id": str(participation.entity_id),
                "folder_id": participation.folder_id,
                "lot_id": participation.lot_id,
                "role": participation.role,
                "evidence_kind": participation.evidence_kind,
                "exact_name": participation.exact_name,
                "received_tender_quantity": participation.received_tender_quantity,
                "confidence": participation.confidence,
                "source_ref": dict(participation.source_ref or {}),
            }
            for participation in participations[:500]
        ],
        "claims": [
            {
                "id": str(claim.id),
                "claim_kind": claim.claim_kind,
                "subject": claim.subject,
                "predicate": claim.predicate,
                "object_value": claim.object_value,
                "status": claim.status,
                "confidence": claim.confidence,
                "evidence_refs": list(claim.evidence_refs or []),
            }
            for claim in claims[:500]
        ],
    }


def investigation_report_preview(session: Session, run_id: uuid.UUID) -> dict[str, Any]:
    run = get_investigation(session, run_id)
    summary = investigation_summary(session, run)
    entity_by_id = {entity["id"]: entity for entity in summary["entities"]}
    awarded = [item for item in summary["procurement_participations"] if item["role"] == "awardee"]
    candidates = [
        entity for entity in summary["entities"] if entity["resolution_status"] == "candidate"
    ]
    verified = [
        entity for entity in summary["entities"] if entity["resolution_status"] == "verified"
    ]
    lines: list[str] = [
        f"Investigacion: {summary['question']}",
        f"Entidad semilla: {summary['seed']['name']} ({summary['seed']['kind']})",
        "",
        "Resumen ejecutivo",
        (
            f"La pasada deterministicamente trazable localizo {summary['counts']['entities']} "
            f"entidades, de las que {summary['counts']['verified_entities']} estan verificadas "
            f"y {summary['counts']['candidate_entities']} quedan pendientes de revision humana."
        ),
        (
            f"En PLACSP estructurado se han registrado {len(awarded)} participaciones como "
            "adjudicatario. La identidad de licitadores no adjudicatarios no se infiere si no "
            "consta en evidencia documental o estructurada."
        ),
        "",
        "Lectura analitica",
        (
            "La red debe interpretarse como mapa de indicios verificables: los nodos candidatos "
            "sirven para orientar la siguiente pasada, pero no amplian busquedas ni sostienen "
            "conclusiones hasta ser confirmados."
        ),
    ]
    if awarded:
        lines.append("")
        lines.append("Licitaciones estructuradas relevantes")
        for participation in awarded[:20]:
            entity = entity_by_id.get(participation["entity_id"], {})
            received = participation["received_tender_quantity"]
            received_label = (
                "sin contador de ofertas" if received is None else f"{received} ofertas"
            )
            lines.append(
                f"- {entity.get('name', participation['exact_name'])}: expediente "
                f"{participation['folder_id']} ({received_label})."
            )
    if candidates:
        lines.append("")
        lines.append("Pendiente de revision")
        for entity in candidates[:20]:
            lines.append(f"- {entity['name']} ({entity['kind']}), profundidad {entity['depth']}.")
    return {
        "investigation": summary,
        "report": {
            "title": f"Informe de investigacion: {summary['seed']['name']}",
            "protocol_version": summary["protocol_version"],
            "source_policy_version": summary["source_policy_version"],
            "corpus_hash": summary["corpus_hash"],
            "generated_at": datetime.now(UTC).isoformat(),
            "sections": {
                "executive_summary": lines[4],
                "procurement_scope": lines[5],
                "analysis": lines[8],
            },
            "markdown": "\n".join(lines),
            "limitations": [
                "No identifica licitadores perdedores salvo evidencia documental procesada.",
                "No expande nodos candidatos sin revision humana de identidad.",
                "La opinion se limita a sociedades, estructura de red y hechos fechados.",
            ],
            "completeness": summary.get("completeness", "incomplete"),
            "incompleteness_reasons": list(summary.get("incompleteness_reasons") or []),
        },
        "verified_entities": verified,
        "candidate_entities": candidates,
    }


INVESTIGATION_MODELS = (
    InvestigationRun,
    InvestigationStep,
    ResearchEntity,
    ResearchAlias,
    ResearchRelation,
    ResearchSourceSnapshot,
    ProcurementParticipation,
    ResearchClaim,
)
