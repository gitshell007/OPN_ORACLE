"""Aggregate model registry loaded by Flask-Migrate."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from opn_oracle.ai.models import AI_MODELS
from opn_oracle.documents.models import DOCUMENT_MODELS
from opn_oracle.extensions import Base
from opn_oracle.integrations.models import INTEGRATION_MODELS
from opn_oracle.oracle.jobs import JOB_MODELS
from opn_oracle.oracle.links import LINK_MODELS
from opn_oracle.oracle.models import ORACLE_MODELS
from opn_oracle.oracle.procurement_search_profiles import PROCUREMENT_SEARCH_PROFILE_MODELS
from opn_oracle.platform.backups import BACKUP_MODELS
from opn_oracle.platform.models import (
    ApiCredential,
    AuditEvent,
    IntegrationConnection,
    Invitation,
    MembershipRole,
    PasswordResetToken,
    Permission,
    Role,
    RolePermission,
    Tenant,
    TenantMembership,
    User,
    UserSession,
    UserSettings,
    Workspace,
)
from opn_oracle.reporting.models import REPORTING_MODELS


def utc_now() -> datetime:
    return datetime.now(UTC)


class SystemMetadata(Base):
    """Global operational metadata; it never stores tenant business data."""

    __tablename__ = "system_metadata"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )


MODEL_REGISTRY = (
    SystemMetadata,
    Tenant,
    Workspace,
    User,
    UserSettings,
    TenantMembership,
    Permission,
    Role,
    RolePermission,
    MembershipRole,
    Invitation,
    PasswordResetToken,
    UserSession,
    AuditEvent,
    IntegrationConnection,
    ApiCredential,
    *BACKUP_MODELS,
    *INTEGRATION_MODELS,
    *ORACLE_MODELS,
    *PROCUREMENT_SEARCH_PROFILE_MODELS,
    *LINK_MODELS,
    *JOB_MODELS,
    *AI_MODELS,
    *DOCUMENT_MODELS,
    *REPORTING_MODELS,
)
