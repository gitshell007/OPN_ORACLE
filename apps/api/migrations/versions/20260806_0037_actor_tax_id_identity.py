"""G-16 · Actor durable tax_id column, partial uniqueness, conflict ledger

Revision ID: 20260806_0037
Revises: 20260806_0036
Create Date: 2026-08-06 15:10:00.000000

Structural phase:
- nullable tax_id / tax_id_scheme / tax_id_country on actors
- partial unique index tenant-scoped (active = tax_id IS NOT NULL)
- actor_tax_id_conflicts for resolvable backfill collisions (Capgemini case)
- idempotent backfill from identifiers.tax_id; never deletes/merges actors
"""

from __future__ import annotations

import re
import uuid
from collections import defaultdict
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260806_0037"
down_revision: str | None = "20260806_0036"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CONFLICTS = "actor_tax_id_conflicts"
_SPANISH_COMPANY_CIF = re.compile(r"^[ABCDEFGHJNPQRSUVW]\d{7}[0-9A-J]$")
_MASK_CHARS = re.compile(r"[*•xX…]")


def _enable_rls(table: str) -> None:
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY tenant_isolation ON {table} "
        "USING (tenant_id=oracle_current_tenant()) "
        "WITH CHECK (tenant_id=oracle_current_tenant())"
    )
    op.execute(
        f"""
        DO $$ BEGIN IF EXISTS(SELECT 1 FROM pg_roles WHERE rolname='oracle_app') THEN
          GRANT SELECT,INSERT,UPDATE,DELETE ON {table} TO oracle_app;
        END IF; END $$
        """
    )


def _normalize_company_tax_id(value: Any) -> str | None:
    """Mirror of normalize_spanish_company_tax_id + usable_company_tax_id (no app import)."""

    if value is None:
        return None
    text = str(value).strip()
    if not text or _MASK_CHARS.search(text) or ";" in text:
        return None
    raw = re.sub(r"[\s.\-_/]", "", text).upper()
    if not raw or not _SPANISH_COMPANY_CIF.fullmatch(raw):
        return None
    return raw


def _tax_canonical_key(tax_id: str) -> str:
    return f"tax:es:{tax_id}"[:320]


def _backfill_from_identifiers() -> dict[str, int]:
    """Materialize column tax_id; record collisions without merging/deleting actors."""

    bind = op.get_bind()
    rows = (
        bind.execute(
            sa.text(
                """
            SELECT id, tenant_id, canonical_name, canonical_key, identifiers, provenance,
                   created_at, version
            FROM actors
            ORDER BY tenant_id, created_at ASC, id ASC
            """
            )
        )
        .mappings()
        .all()
    )

    groups: dict[tuple[uuid.UUID, str], list[dict[str, Any]]] = defaultdict(list)
    invalid = 0
    for row in rows:
        identifiers = row["identifiers"] if isinstance(row["identifiers"], dict) else {}
        declared = identifiers.get("tax_id")
        if declared in (None, ""):
            continue
        normalized = _normalize_company_tax_id(declared)
        if normalized is None:
            invalid += 1
            continue
        groups[(row["tenant_id"], normalized)].append(
            {
                "id": row["id"],
                "tenant_id": row["tenant_id"],
                "canonical_name": row["canonical_name"],
                "canonical_key": row["canonical_key"],
                "identifiers": identifiers,
                "provenance": row["provenance"] if isinstance(row["provenance"], dict) else {},
                "created_at": row["created_at"],
                "version": int(row["version"] or 1),
                "declared": str(declared),
            }
        )

    applied = 0
    collisions = 0
    skipped_already = 0
    now = datetime.now(UTC)

    for (tenant_id, tax_id), members in groups.items():
        # Deterministic winner: earliest created_at, then smallest UUID.
        members_sorted = sorted(
            members,
            key=lambda item: (
                item["created_at"] or now,
                str(item["id"]),
            ),
        )
        winner = members_sorted[0]
        losers = members_sorted[1:]

        # Apply winner column + tax-based canonical_key when free.
        tax_key = _tax_canonical_key(tax_id)
        key_taken = bind.execute(
            sa.text(
                """
                SELECT id FROM actors
                WHERE tenant_id = :tenant_id AND canonical_key = :ck AND id <> :winner_id
                LIMIT 1
                """
            ),
            {"tenant_id": tenant_id, "ck": tax_key, "winner_id": winner["id"]},
        ).first()
        new_key = winner["canonical_key"] if key_taken else tax_key

        result = bind.execute(
            sa.text(
                """
                UPDATE actors
                SET tax_id = :tax_id,
                    tax_id_scheme = 'ES_CIF',
                    tax_id_country = 'ES',
                    canonical_key = :ck,
                    identifiers = CAST(:identifiers AS jsonb),
                    provenance = CAST(:provenance AS jsonb),
                    version = :version,
                    updated_at = :now
                WHERE id = :id
                  AND (tax_id IS NULL OR tax_id = :tax_id)
                """
            ),
            {
                "tax_id": tax_id,
                "ck": new_key,
                "identifiers": _json_dump(
                    _sync_identifiers(
                        winner["identifiers"], tax_id=tax_id, declared=winner["declared"]
                    )
                ),
                "provenance": _json_dump(
                    {
                        **winner["provenance"],
                        "tax_id_column_backfill": {
                            "source": "identifiers.tax_id",
                            "tax_id": tax_id,
                            "declared_tax_id": winner["declared"],
                            "role": "winner",
                            "backfilled_at": now.isoformat(),
                        },
                    }
                ),
                "version": winner["version"] + 1,
                "now": now,
                "id": winner["id"],
            },
        )
        if result.rowcount:
            applied += 1
        else:
            skipped_already += 1

        for loser in losers:
            collisions += 1
            conflict_id = uuid.uuid5(
                uuid.NAMESPACE_URL,
                f"opn-oracle:actor-tax-id-conflict:{tenant_id}:{tax_id}:{loser['id']}",
            )
            bind.execute(
                sa.text(
                    """
                    INSERT INTO actor_tax_id_conflicts (
                        id, tenant_id, tax_id, winner_actor_id, loser_actor_id,
                        declared_tax_id, declared_identifiers, status, resolution_note,
                        version, created_at, updated_at
                    ) VALUES (
                        :id, :tenant_id, :tax_id, :winner_id, :loser_id,
                        :declared, CAST(:declared_ids AS jsonb), 'open', NULL,
                        1, :now, :now
                    )
                    ON CONFLICT (tenant_id, tax_id, loser_actor_id) DO NOTHING
                    """
                ),
                {
                    "id": conflict_id,
                    "tenant_id": tenant_id,
                    "tax_id": tax_id,
                    "winner_id": winner["id"],
                    "loser_id": loser["id"],
                    "declared": str(loser["declared"])[:80],
                    "declared_ids": _json_dump(dict(loser["identifiers"] or {})),
                    "now": now,
                },
            )
            # Preserve declared JSONB tax_id; leave column NULL (not the unique holder).
            bind.execute(
                sa.text(
                    """
                    UPDATE actors
                    SET provenance = CAST(:provenance AS jsonb),
                        version = version + 1,
                        updated_at = :now
                    WHERE id = :id
                    """
                ),
                {
                    "id": loser["id"],
                    "now": now,
                    "provenance": _json_dump(
                        {
                            **loser["provenance"],
                            "tax_id_column_backfill": {
                                "source": "identifiers.tax_id",
                                "tax_id": tax_id,
                                "declared_tax_id": loser["declared"],
                                "role": "loser",
                                "winner_actor_id": str(winner["id"]),
                                "backfilled_at": now.isoformat(),
                            },
                        }
                    ),
                },
            )

    return {
        "applied": applied,
        "collisions": collisions,
        "invalid": invalid,
        "skipped_already": skipped_already,
        "groups": len(groups),
    }


def _sync_identifiers(identifiers: dict[str, Any], *, tax_id: str, declared: str) -> dict[str, Any]:
    out = dict(identifiers or {})
    out["tax_id"] = tax_id
    out["tax_id_scheme"] = "ES_CIF"
    out.setdefault("tax_id_declared", declared)
    return out


def _json_dump(value: Any) -> str:
    import json

    return json.dumps(value, ensure_ascii=False, default=str)


def upgrade() -> None:
    op.add_column("actors", sa.Column("tax_id", sa.String(length=20), nullable=True))
    op.add_column("actors", sa.Column("tax_id_scheme", sa.String(length=20), nullable=True))
    op.add_column("actors", sa.Column("tax_id_country", sa.String(length=2), nullable=True))

    op.create_table(
        CONFLICTS,
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tax_id", sa.String(length=20), nullable=False),
        sa.Column("winner_actor_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("loser_actor_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("declared_tax_id", sa.String(length=80), nullable=False),
        sa.Column(
            "declared_identifiers",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="open"),
        sa.Column("resolution_note", sa.Text(), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], ondelete="CASCADE", name="fk_atic_tenant"
        ),
        sa.ForeignKeyConstraint(
            ["winner_actor_id", "tenant_id"],
            ["actors.id", "actors.tenant_id"],
            ondelete="CASCADE",
            name="fk_atic_winner_actor_tenant",
        ),
        sa.ForeignKeyConstraint(
            ["loser_actor_id", "tenant_id"],
            ["actors.id", "actors.tenant_id"],
            ondelete="CASCADE",
            name="fk_atic_loser_actor_tenant",
        ),
        sa.CheckConstraint(
            "status IN ('open','resolved','dismissed')",
            name="ck_atic_status",
        ),
        sa.CheckConstraint("version >= 1", name="ck_atic_version_positive"),
        sa.CheckConstraint("winner_actor_id <> loser_actor_id", name="ck_atic_distinct_actors"),
        sa.UniqueConstraint(
            "tenant_id",
            "tax_id",
            "loser_actor_id",
            name="uq_atic_tenant_tax_loser",
        ),
    )
    op.create_index(
        "ix_atic_tenant_status_tax",
        CONFLICTS,
        ["tenant_id", "status", "tax_id"],
    )
    _enable_rls(CONFLICTS)

    # Backfill before enforcing uniqueness so Capgemini collisions become conflicts,
    # not a failed migration.
    counts = _backfill_from_identifiers()
    # Visible in alembic logs for audit (Capgemini collisions must not be hidden).
    notice = (
        f"g16_tax_id_backfill applied={counts['applied']} "
        f"collisions={counts['collisions']} invalid={counts['invalid']} "
        f"groups={counts['groups']} skipped={counts['skipped_already']}"
    )
    op.execute(sa.text(f"DO $$ BEGIN RAISE NOTICE '{notice}'; END $$"))

    op.create_index(
        "uq_actors_tenant_tax_id_active",
        "actors",
        ["tenant_id", "tax_id"],
        unique=True,
        postgresql_where=sa.text("tax_id IS NOT NULL"),
    )
    op.create_index(
        "ix_actors_tenant_tax_id",
        "actors",
        ["tenant_id", "tax_id"],
        unique=False,
        postgresql_where=sa.text("tax_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_actors_tenant_tax_id", table_name="actors")
    op.drop_index("uq_actors_tenant_tax_id_active", table_name="actors")
    op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {CONFLICTS}")
    op.drop_index("ix_atic_tenant_status_tax", table_name=CONFLICTS)
    op.drop_table(CONFLICTS)
    op.drop_column("actors", "tax_id_country")
    op.drop_column("actors", "tax_id_scheme")
    op.drop_column("actors", "tax_id")
