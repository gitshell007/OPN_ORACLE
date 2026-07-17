"""allow entity-intel evidence source kind

Revision ID: 20260717_0020
Revises: 20260714_0019
Create Date: 2026-07-17 12:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "20260717_0020"
down_revision: str | None = "20260714_0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


EVIDENCE_SOURCE_SHAPE_V5 = (
    "(source_kind='signal' AND signal_id IS NOT NULL AND document_id IS NULL "
    "AND document_version_id IS NULL AND document_chunk_id IS NULL) OR "
    "(source_kind='document' AND signal_id IS NULL AND document_id IS NOT NULL "
    "AND document_version_id IS NOT NULL AND document_chunk_id IS NOT NULL) OR "
    "(source_kind='legacy_unresolved' AND signal_id IS NULL AND document_id IS NULL "
    "AND document_version_id IS NULL AND document_chunk_id IS NULL "
    'AND provenance @> \'{"migration_status":"quarantined_missing_source"}\'::jsonb) OR '
    "(source_kind='procurement' AND signal_id IS NULL AND document_id IS NULL "
    'AND provenance @> \'{"source_kind":"procurement"}\'::jsonb) OR '
    "(source_kind='entity_intel' AND signal_id IS NULL AND document_id IS NULL "
    "AND document_version_id IS NULL AND document_chunk_id IS NULL "
    'AND provenance @> \'{"source_kind":"entity_intel"}\'::jsonb)'
)

EVIDENCE_SOURCE_SHAPE_V4 = (
    "(source_kind='signal' AND signal_id IS NOT NULL AND document_id IS NULL "
    "AND document_version_id IS NULL AND document_chunk_id IS NULL) OR "
    "(source_kind='document' AND signal_id IS NULL AND document_id IS NOT NULL "
    "AND document_version_id IS NOT NULL AND document_chunk_id IS NOT NULL) OR "
    "(source_kind='legacy_unresolved' AND signal_id IS NULL AND document_id IS NULL "
    "AND document_version_id IS NULL AND document_chunk_id IS NULL "
    'AND provenance @> \'{"migration_status":"quarantined_missing_source"}\'::jsonb) OR '
    "(source_kind='procurement' AND signal_id IS NULL AND document_id IS NULL "
    'AND provenance @> \'{"source_kind":"procurement"}\'::jsonb)'
)


def upgrade() -> None:
    op.drop_constraint("evidence_source_shape", "evidence", type_="check")
    op.create_check_constraint("evidence_source_shape", "evidence", EVIDENCE_SOURCE_SHAPE_V5)


def downgrade() -> None:
    op.drop_constraint("evidence_source_shape", "evidence", type_="check")
    op.execute(
        """
        UPDATE evidence
        SET source_kind='legacy_unresolved',
            provenance = provenance || '{"migration_status":"quarantined_missing_source"}'::jsonb
        WHERE source_kind='entity_intel'
        """
    )
    op.create_check_constraint("evidence_source_shape", "evidence", EVIDENCE_SOURCE_SHAPE_V4)
