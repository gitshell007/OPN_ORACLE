"""add signal dedupe keys

Revision ID: 20260713_0016
Revises: 20260712_0015
Create Date: 2026-07-13 11:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import sqlalchemy as sa
from alembic import op

revision: str = "20260713_0016"
down_revision: str | None = "20260712_0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TRACKING_QUERY_PREFIXES = ("utm_",)
TRACKING_QUERY_KEYS = frozenset(
    {
        "fbclid",
        "gclid",
        "gbraid",
        "mc_cid",
        "mc_eid",
        "msclkid",
        "wbraid",
    }
)


def _canonical_source_url(value: str | None) -> str | None:
    if not value:
        return None
    parsed = urlsplit(value.strip())
    if not parsed.scheme or not parsed.netloc:
        return None
    scheme = parsed.scheme.lower()
    hostname = (parsed.hostname or "").lower()
    if not hostname:
        return None
    port = parsed.port
    netloc = hostname
    if port is not None and not (
        (scheme == "http" and port == 80) or (scheme == "https" and port == 443)
    ):
        netloc = f"{hostname}:{port}"
    path = parsed.path or ""
    path = path.rstrip("/") if path != "/" else ""
    query_items = [
        (key, item)
        for key, item in parse_qsl(parsed.query, keep_blank_values=True)
        if key.lower() not in TRACKING_QUERY_KEYS
        and not key.lower().startswith(TRACKING_QUERY_PREFIXES)
    ]
    return urlunsplit((scheme, netloc, path, urlencode(query_items, doseq=True), ""))


def _dedupe_key(
    source_url: str | None, source_name: str, title: str
) -> tuple[str | None, str | None]:
    canonical_url = _canonical_source_url(source_url)
    if canonical_url:
        return canonical_url, f"url:{canonical_url}"
    normalized_source = " ".join(source_name.casefold().split())
    normalized_title = " ".join(title.casefold().split())
    if not normalized_source or not normalized_title:
        return None, None
    return None, f"title:{normalized_source}:{normalized_title}"


def upgrade() -> None:
    op.add_column("signals", sa.Column("canonical_source_url", sa.String(length=1500)))
    op.add_column("signals", sa.Column("dedupe_key", sa.String(length=2000)))
    bind = op.get_bind()
    rows = bind.execute(sa.text("SELECT id, source_url, source_name, title FROM signals"))
    for row in rows.mappings():
        canonical_url, dedupe_key = _dedupe_key(
            row["source_url"], row["source_name"] or "", row["title"] or ""
        )
        bind.execute(
            sa.text(
                "UPDATE signals SET canonical_source_url=:canonical_url, dedupe_key=:dedupe_key "
                "WHERE id=:id"
            ),
            {"canonical_url": canonical_url, "dedupe_key": dedupe_key, "id": row["id"]},
        )
    op.create_index(
        "ix_signals_tenant_connection_dedupe",
        "signals",
        ["tenant_id", "provider_connection_id", "dedupe_key"],
        postgresql_where=sa.text("dedupe_key IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_signals_tenant_connection_dedupe", table_name="signals")
    op.drop_column("signals", "dedupe_key")
    op.drop_column("signals", "canonical_source_url")
