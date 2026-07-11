"""Global backup catalogue and host-agent operation queue."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from opn_oracle.extensions import Base
from opn_oracle.platform.models import TimestampMixin, UUIDPrimaryKeyMixin


class PlatformBackupArtifact(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Non-secret metadata for one backup stored outside the application container."""

    __tablename__ = "platform_backup_artifacts"
    __table_args__ = (
        CheckConstraint("status IN ('available','expired','missing')", name="backup_status"),
        CheckConstraint("origin IN ('manual','scheduled','imported')", name="backup_origin"),
        CheckConstraint("size_bytes >= 0", name="backup_size"),
        CheckConstraint("sha256 ~ '^[0-9a-f]{64}$'", name="backup_sha256"),
        CheckConstraint("relative_path !~ '(^/|(^|/)[.][.](/|$))'", name="backup_relative_path"),
        UniqueConstraint("backup_name", name="uq_platform_backup_name"),
        UniqueConstraint("relative_path", name="uq_platform_backup_relative_path"),
        Index("ix_platform_backup_created", "backup_created_at"),
    )

    backup_name: Mapped[str] = mapped_column(String(200), nullable=False)
    relative_path: Mapped[str] = mapped_column(String(500), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="available")
    origin: Mapped[str] = mapped_column(String(20), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    backup_created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class PlatformBackupOperation(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Durable request consumed exclusively by the privileged host backup agent."""

    __tablename__ = "platform_backup_operations"
    __table_args__ = (
        CheckConstraint(
            "operation_type IN ('manual_backup','scheduled_backup','restore')",
            name="backup_operation_type",
        ),
        CheckConstraint(
            "status IN ('queued','awaiting_approval','running','succeeded','failed','cancelled')",
            name="backup_operation_status",
        ),
        CheckConstraint("attempts >= 0 AND attempts <= 20", name="backup_operation_attempts"),
        CheckConstraint("jsonb_typeof(result_metadata)='object'", name="backup_result_object"),
        CheckConstraint(
            "(status='running') = (worker_id IS NOT NULL AND lease_expires_at IS NOT NULL)",
            name="backup_operation_lease",
        ),
        UniqueConstraint("idempotency_key", name="uq_platform_backup_operation_idempotency"),
        Index("ix_platform_backup_operation_queue", "status", "created_at"),
    )

    operation_type: Mapped[str] = mapped_column(String(30), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="queued")
    requested_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT", name="fk_backup_ops_requested_user"),
    )
    artifact_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "platform_backup_artifacts.id",
            ondelete="RESTRICT",
            name="fk_backup_ops_artifact",
        ),
    )
    idempotency_key: Mapped[str] = mapped_column(String(200), nullable=False)
    request_id: Mapped[str | None] = mapped_column(String(100))
    correlation_id: Mapped[str | None] = mapped_column(String(100))
    worker_id: Mapped[str | None] = mapped_column(String(100))
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    error_code: Mapped[str | None] = mapped_column(String(100))
    error_message: Mapped[str | None] = mapped_column(Text)
    result_metadata: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )


BACKUP_MODELS = (PlatformBackupArtifact, PlatformBackupOperation)
