"""Platform identity, tenancy, RBAC, audit and integration persistence."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    LargeBinary,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import CITEXT, INET, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from opn_oracle.extensions import Base


def utc_now() -> datetime:
    return datetime.now(UTC)


class UUIDPrimaryKeyMixin:
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        onupdate=utc_now,
        server_default=text("now()"),
    )


class Tenant(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "tenants"
    __table_args__ = (
        CheckConstraint(
            "slug = lower(slug) AND slug ~ '^[a-z0-9]+(-[a-z0-9]+)*$'",
            name="tenant_slug_format",
        ),
        CheckConstraint("status IN ('active', 'suspended', 'archived')", name="tenant_status"),
        CheckConstraint("jsonb_typeof(settings) = 'object'", name="tenant_settings_object"),
    )

    slug: Mapped[str] = mapped_column(String(63), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    plan: Mapped[str | None] = mapped_column(String(50))
    locale: Mapped[str] = mapped_column(String(20), nullable=False, default="es-ES")
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, default="Europe/Madrid")
    settings: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )


class Workspace(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "workspaces"
    __table_args__ = (
        UniqueConstraint("tenant_id", "slug", name="uq_workspaces_tenant_slug"),
        UniqueConstraint("id", "tenant_id", name="uq_workspaces_id_tenant"),
        CheckConstraint(
            "slug = lower(slug) AND slug ~ '^[a-z0-9]+(-[a-z0-9]+)*$'",
            name="workspace_slug_format",
        ),
        CheckConstraint("status IN ('active', 'archived')", name="workspace_status"),
        CheckConstraint("jsonb_typeof(settings) = 'object'", name="workspace_settings_object"),
        Index(
            "uq_workspaces_one_default_per_tenant",
            "tenant_id",
            unique=True,
            postgresql_where=text("is_default"),
        ),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    slug: Mapped[str] = mapped_column(String(63), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    settings: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )


class User(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint(
            "status IN ('invited', 'active', 'locked', 'disabled')", name="user_status"
        ),
        CheckConstraint(
            "platform_role IS NULL OR platform_role = 'super_admin'",
            name="user_platform_role",
        ),
    )

    email: Mapped[str] = mapped_column(CITEXT(), nullable=False, unique=True)
    display_name: Mapped[str] = mapped_column(String(200), nullable=False)
    password_hash: Mapped[str | None] = mapped_column(String(512))
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="invited")
    platform_role: Mapped[str | None] = mapped_column(String(30))
    email_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    password_changed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    def __repr__(self) -> str:
        return f"User(id={self.id!s}, status={self.status!r})"

    @property
    def is_active(self) -> bool:
        return self.status == "active"

    @property
    def is_authenticated(self) -> bool:
        return True

    @property
    def is_anonymous(self) -> bool:
        return False

    def get_id(self) -> str:
        return str(self.id)


class UserSettings(TimestampMixin, Base):
    __tablename__ = "user_settings"
    __table_args__ = (
        CheckConstraint("schema_version >= 1", name="user_settings_schema_version"),
        CheckConstraint(
            "jsonb_typeof(preferences) = 'object'", name="user_settings_preferences_object"
        ),
        CheckConstraint(
            "jsonb_typeof(digest_preferences) = 'object'",
            name="user_settings_digest_object",
        ),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    locale: Mapped[str] = mapped_column(String(20), nullable=False, default="es-ES")
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, default="Europe/Madrid")
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    preferences: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    digest_preferences: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )


class TenantMembership(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "tenant_memberships"
    __table_args__ = (
        UniqueConstraint("tenant_id", "user_id", name="uq_membership_tenant_user"),
        UniqueConstraint("id", "tenant_id", name="uq_membership_id_tenant"),
        CheckConstraint(
            "status IN ('invited', 'active', 'suspended', 'revoked')",
            name="membership_status",
        ),
        CheckConstraint("jsonb_typeof(settings) = 'object'", name="membership_settings_object"),
        Index("ix_tenant_memberships_user_id", "user_id"),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="invited")
    invited_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    settings: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )


class Permission(Base):
    __tablename__ = "permissions"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    description: Mapped[str] = mapped_column(String(300), nullable=False)


class Role(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "roles"
    __table_args__ = (
        UniqueConstraint("tenant_id", "key", name="uq_roles_tenant_key"),
        UniqueConstraint("id", "tenant_id", name="uq_roles_id_tenant"),
        CheckConstraint("key = lower(key) AND key ~ '^[a-z][a-z0-9_]*$'", name="role_key_format"),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    key: Mapped[str] = mapped_column(String(50), nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str] = mapped_column(String(300), nullable=False, default="")
    is_system: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class RolePermission(Base):
    __tablename__ = "role_permissions"
    __table_args__ = (
        ForeignKeyConstraint(
            ("role_id", "tenant_id"),
            ("roles.id", "roles.tenant_id"),
            ondelete="CASCADE",
            name="fk_role_permissions_role_tenant",
        ),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    role_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    permission_key: Mapped[str] = mapped_column(
        String(100), ForeignKey("permissions.key", ondelete="CASCADE"), primary_key=True
    )


class MembershipRole(Base):
    __tablename__ = "membership_roles"
    __table_args__ = (
        ForeignKeyConstraint(
            ("membership_id", "tenant_id"),
            ("tenant_memberships.id", "tenant_memberships.tenant_id"),
            ondelete="CASCADE",
            name="fk_membership_roles_membership_tenant",
        ),
        ForeignKeyConstraint(
            ("role_id", "tenant_id"),
            ("roles.id", "roles.tenant_id"),
            ondelete="CASCADE",
            name="fk_membership_roles_role_tenant",
        ),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    membership_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    role_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)


class Invitation(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "invitations"
    __table_args__ = (
        ForeignKeyConstraint(
            ("membership_id", "tenant_id"),
            ("tenant_memberships.id", "tenant_memberships.tenant_id"),
            ondelete="CASCADE",
            name="fk_invitations_membership_tenant",
        ),
        CheckConstraint("octet_length(token_hash) = 32", name="invitation_token_hash_size"),
        Index("ix_invitations_membership_id", "membership_id"),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    membership_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    token_hash: Mapped[bytes] = mapped_column(LargeBinary(32), nullable=False, unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    invited_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )


class PasswordResetToken(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "password_reset_tokens"
    __table_args__ = (
        CheckConstraint("octet_length(token_hash) = 32", name="reset_token_hash_size"),
        Index("ix_password_reset_tokens_user_id", "user_id"),
        UniqueConstraint("delivery_key", name="uq_password_reset_tokens_delivery_key"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="SET NULL")
    )
    token_hash: Mapped[bytes] = mapped_column(LargeBinary(32), nullable=False, unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    delivery_key: Mapped[str | None] = mapped_column(String(200))
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    delivery_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class UserSession(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "user_sessions"
    __table_args__ = (
        CheckConstraint("octet_length(session_hash) = 32", name="session_hash_size"),
        Index("ix_user_sessions_user_id", "user_id"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    active_tenant_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="SET NULL")
    )
    session_hash: Mapped[bytes] = mapped_column(LargeBinary(32), nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, server_default=text("now()")
    )
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    idle_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    absolute_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    user_agent_summary: Mapped[str | None] = mapped_column(String(255))
    ip_address: Mapped[str | None] = mapped_column(INET())


class AuditEvent(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "audit_events"
    __table_args__ = (
        CheckConstraint("actor_type IN ('user', 'service')", name="audit_actor_type"),
        CheckConstraint("result IN ('success', 'denied', 'failure')", name="audit_result"),
        CheckConstraint("jsonb_typeof(metadata) = 'object'", name="audit_metadata_object"),
        Index("ix_audit_events_tenant_created", "tenant_id", "created_at"),
        Index("ix_audit_events_tenant_dossier_created", "tenant_id", "dossier_id", "created_at"),
        ForeignKeyConstraint(
            ("dossier_id", "tenant_id"),
            ("strategic_dossiers.id", "strategic_dossiers.tenant_id"),
            ondelete="RESTRICT",
            name="fk_audit_events_dossier_tenant",
        ),
    )

    tenant_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="SET NULL")
    )
    actor_type: Mapped[str] = mapped_column(String(20), nullable=False)
    actor_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    dossier_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    action: Mapped[str] = mapped_column(String(150), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(100), nullable=False)
    resource_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    result: Mapped[str] = mapped_column(String(20), nullable=False)
    request_id: Mapped[str | None] = mapped_column(String(100))
    correlation_id: Mapped[str | None] = mapped_column(String(100))
    event_metadata: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, server_default=text("now()")
    )


class IntegrationConnection(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "integration_connections"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "provider", "name", name="uq_integration_tenant_provider_name"
        ),
        UniqueConstraint("id", "tenant_id", name="uq_integration_id_tenant"),
        CheckConstraint(
            "status IN ('pending', 'active', 'error', 'disabled')",
            name="integration_status",
        ),
        CheckConstraint("adapter_mode IN ('mock','http')", name="integration_adapter_mode"),
        CheckConstraint(
            "circuit_state IN ('closed','open','half_open')", name="integration_circuit_state"
        ),
        CheckConstraint("version >= 1", name="integration_version_positive"),
        CheckConstraint("jsonb_typeof(metadata) = 'object'", name="integration_metadata_object"),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    provider: Mapped[str] = mapped_column(String(100), nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False, default="default")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    base_url: Mapped[str | None] = mapped_column(String(1000))
    api_version: Mapped[str] = mapped_column(String(30), nullable=False, default="v1")
    subscription_key: Mapped[str | None] = mapped_column(String(100), unique=True)
    adapter_mode: Mapped[str] = mapped_column(String(20), nullable=False, default="mock")
    circuit_state: Mapped[str] = mapped_column(String(20), nullable=False, default="closed")
    circuit_opened_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_health_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(String(500))
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    connection_metadata: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )


class ApiCredential(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "api_credentials"
    __table_args__ = (
        ForeignKeyConstraint(
            ("connection_id", "tenant_id"),
            ("integration_connections.id", "integration_connections.tenant_id"),
            ondelete="CASCADE",
            name="fk_api_credentials_connection_tenant",
        ),
        UniqueConstraint(
            "connection_id",
            "credential_kind",
            "credential_version",
            name="uq_credential_connection_kind_version",
        ),
        CheckConstraint("credential_version >= 1", name="credential_version_positive"),
        CheckConstraint("key_version >= 1", name="credential_key_version_positive"),
        CheckConstraint(
            "credential_kind IN ('api_token','webhook_secret')", name="credential_kind"
        ),
        CheckConstraint("algorithm = 'AES-256-GCM'", name="credential_algorithm"),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    connection_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    credential_kind: Mapped[str] = mapped_column(String(30), nullable=False, default="api_token")
    algorithm: Mapped[str] = mapped_column(String(30), nullable=False, default="AES-256-GCM")
    ciphertext: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    nonce: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    key_version: Mapped[int] = mapped_column(Integer, nullable=False)
    credential_version: Mapped[int] = mapped_column(Integer, nullable=False)
    fingerprint: Mapped[str] = mapped_column(String(128), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    rotated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    valid_from: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    valid_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    retired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
