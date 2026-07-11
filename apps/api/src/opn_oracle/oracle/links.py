"""Explicit tenant-safe many-to-many relationships for Oracle evidence and actors."""

from __future__ import annotations

import uuid

from sqlalchemy import ForeignKey, ForeignKeyConstraint, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from opn_oracle.extensions import Base


class DossierCollaborator(Base):
    __tablename__ = "dossier_collaborators"
    __table_args__ = (
        ForeignKeyConstraint(
            ("dossier_id", "tenant_id"),
            ("strategic_dossiers.id", "strategic_dossiers.tenant_id"),
            ondelete="CASCADE",
            name="fk_dossier_collaborator_dossier_tenant",
        ),
        ForeignKeyConstraint(
            ("tenant_id", "user_id"),
            ("tenant_memberships.tenant_id", "tenant_memberships.user_id"),
            ondelete="CASCADE",
            name="fk_dossier_collaborator_membership",
        ),
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    dossier_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    role: Mapped[str] = mapped_column(String(40), nullable=False, default="collaborator")


class EvidenceDossier(Base):
    __tablename__ = "evidence_dossiers"
    __table_args__ = (
        ForeignKeyConstraint(
            ("evidence_id", "tenant_id"),
            ("evidence.id", "evidence.tenant_id"),
            ondelete="CASCADE",
            name="fk_evidence_dossier_evidence_tenant",
        ),
        ForeignKeyConstraint(
            ("dossier_id", "tenant_id"),
            ("strategic_dossiers.id", "strategic_dossiers.tenant_id"),
            ondelete="CASCADE",
            name="fk_evidence_dossier_dossier_tenant",
        ),
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    evidence_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    dossier_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)


class HypothesisEvidence(Base):
    __tablename__ = "hypothesis_evidence"
    __table_args__ = (
        ForeignKeyConstraint(
            ("hypothesis_id", "tenant_id"),
            ("hypotheses.id", "hypotheses.tenant_id"),
            ondelete="CASCADE",
            name="fk_hypothesis_evidence_hypothesis_tenant",
        ),
        ForeignKeyConstraint(
            ("evidence_id", "tenant_id"),
            ("evidence.id", "evidence.tenant_id"),
            ondelete="CASCADE",
            name="fk_hypothesis_evidence_evidence_tenant",
        ),
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    hypothesis_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    evidence_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    stance: Mapped[str] = mapped_column(String(20), nullable=False, default="supports")


class OpportunitySignal(Base):
    __tablename__ = "opportunity_signals"
    __table_args__ = (
        ForeignKeyConstraint(
            ("opportunity_id", "tenant_id"),
            ("opportunities.id", "opportunities.tenant_id"),
            ondelete="CASCADE",
            name="fk_opportunity_signal_opportunity_tenant",
        ),
        ForeignKeyConstraint(
            ("signal_id", "tenant_id"),
            ("signals.id", "signals.tenant_id"),
            ondelete="CASCADE",
            name="fk_opportunity_signal_signal_tenant",
        ),
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    opportunity_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    signal_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)


class OpportunityEvidence(Base):
    __tablename__ = "opportunity_evidence"
    __table_args__ = (
        ForeignKeyConstraint(
            ("opportunity_id", "tenant_id"),
            ("opportunities.id", "opportunities.tenant_id"),
            ondelete="CASCADE",
            name="fk_opportunity_evidence_opportunity_tenant",
        ),
        ForeignKeyConstraint(
            ("evidence_id", "tenant_id"),
            ("evidence.id", "evidence.tenant_id"),
            ondelete="CASCADE",
            name="fk_opportunity_evidence_evidence_tenant",
        ),
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    opportunity_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    evidence_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)


class OpportunityActor(Base):
    __tablename__ = "opportunity_actors"
    __table_args__ = (
        ForeignKeyConstraint(
            ("opportunity_id", "tenant_id"),
            ("opportunities.id", "opportunities.tenant_id"),
            ondelete="CASCADE",
            name="fk_opportunity_actor_opportunity_tenant",
        ),
        ForeignKeyConstraint(
            ("actor_id", "tenant_id"),
            ("actors.id", "actors.tenant_id"),
            ondelete="CASCADE",
            name="fk_opportunity_actor_actor_tenant",
        ),
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    opportunity_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    actor_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)


class RiskSignal(Base):
    __tablename__ = "risk_signals"
    __table_args__ = (
        ForeignKeyConstraint(
            ("risk_id", "tenant_id"),
            ("risk_items.id", "risk_items.tenant_id"),
            ondelete="CASCADE",
            name="fk_risk_signal_risk_tenant",
        ),
        ForeignKeyConstraint(
            ("signal_id", "tenant_id"),
            ("signals.id", "signals.tenant_id"),
            ondelete="CASCADE",
            name="fk_risk_signal_signal_tenant",
        ),
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    risk_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    signal_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)


class RiskEvidence(Base):
    __tablename__ = "risk_evidence"
    __table_args__ = (
        ForeignKeyConstraint(
            ("risk_id", "tenant_id"),
            ("risk_items.id", "risk_items.tenant_id"),
            ondelete="CASCADE",
            name="fk_risk_evidence_risk_tenant",
        ),
        ForeignKeyConstraint(
            ("evidence_id", "tenant_id"),
            ("evidence.id", "evidence.tenant_id"),
            ondelete="CASCADE",
            name="fk_risk_evidence_evidence_tenant",
        ),
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    risk_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    evidence_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)


class RiskActor(Base):
    __tablename__ = "risk_actors"
    __table_args__ = (
        ForeignKeyConstraint(
            ("risk_id", "tenant_id"),
            ("risk_items.id", "risk_items.tenant_id"),
            ondelete="CASCADE",
            name="fk_risk_actor_risk_tenant",
        ),
        ForeignKeyConstraint(
            ("actor_id", "tenant_id"),
            ("actors.id", "actors.tenant_id"),
            ondelete="CASCADE",
            name="fk_risk_actor_actor_tenant",
        ),
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    risk_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    actor_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)


class DossierActorEvidence(Base):
    __tablename__ = "dossier_actor_evidence"
    __table_args__ = (
        ForeignKeyConstraint(
            ("dossier_actor_id", "tenant_id"),
            ("dossier_actors.id", "dossier_actors.tenant_id"),
            ondelete="CASCADE",
            name="fk_dossier_actor_evidence_actor_tenant",
        ),
        ForeignKeyConstraint(
            ("evidence_id", "tenant_id"),
            ("evidence.id", "evidence.tenant_id"),
            ondelete="CASCADE",
            name="fk_dossier_actor_evidence_evidence_tenant",
        ),
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    dossier_actor_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    evidence_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)


class RelationshipEvidence(Base):
    __tablename__ = "relationship_evidence"
    __table_args__ = (
        ForeignKeyConstraint(
            ("relationship_id", "tenant_id"),
            ("relationships.id", "relationships.tenant_id"),
            ondelete="CASCADE",
            name="fk_relationship_evidence_relationship_tenant",
        ),
        ForeignKeyConstraint(
            ("evidence_id", "tenant_id"),
            ("evidence.id", "evidence.tenant_id"),
            ondelete="CASCADE",
            name="fk_relationship_evidence_evidence_tenant",
        ),
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    relationship_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    evidence_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)


class MeetingActor(Base):
    __tablename__ = "meeting_actors"
    __table_args__ = (
        ForeignKeyConstraint(
            ("meeting_id", "tenant_id"),
            ("meetings.id", "meetings.tenant_id"),
            ondelete="CASCADE",
            name="fk_meeting_actor_meeting_tenant",
        ),
        ForeignKeyConstraint(
            ("actor_id", "tenant_id"),
            ("actors.id", "actors.tenant_id"),
            ondelete="CASCADE",
            name="fk_meeting_actor_actor_tenant",
        ),
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    meeting_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    actor_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)


def _evidence_link_args(
    resource: str, table: str
) -> tuple[ForeignKeyConstraint, ForeignKeyConstraint]:
    return (
        ForeignKeyConstraint(
            (f"{resource}_id", "tenant_id"),
            (f"{table}.id", f"{table}.tenant_id"),
            ondelete="CASCADE",
            name=f"fk_{resource}_evidence_resource_tenant",
        ),
        ForeignKeyConstraint(
            ("evidence_id", "tenant_id"),
            ("evidence.id", "evidence.tenant_id"),
            ondelete="CASCADE",
            name=f"fk_{resource}_evidence_evidence_tenant",
        ),
    )


class MeetingEvidence(Base):
    __tablename__ = "meeting_evidence"
    __table_args__ = _evidence_link_args("meeting", "meetings")
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    meeting_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    evidence_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)


class DecisionEvidence(Base):
    __tablename__ = "decision_evidence"
    __table_args__ = _evidence_link_args("decision", "decisions")
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    decision_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    evidence_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)


class InsightEvidence(Base):
    __tablename__ = "insight_evidence"
    __table_args__ = _evidence_link_args("insight", "insights")
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    insight_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    evidence_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)


class ReportEvidence(Base):
    __tablename__ = "report_evidence"
    __table_args__ = _evidence_link_args("report", "reports")
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    report_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    evidence_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)


LINK_MODELS = (
    DossierCollaborator,
    EvidenceDossier,
    HypothesisEvidence,
    OpportunitySignal,
    OpportunityEvidence,
    OpportunityActor,
    RiskSignal,
    RiskEvidence,
    RiskActor,
    DossierActorEvidence,
    RelationshipEvidence,
    MeetingActor,
    MeetingEvidence,
    DecisionEvidence,
    InsightEvidence,
    ReportEvidence,
)
