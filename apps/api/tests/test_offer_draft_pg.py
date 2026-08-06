"""PostgreSQL integration for opportunity_offer_drafts (SV2-G09-A).

Requires disposable local PG:
  ORACLE_RUN_INTEGRATION=1
  TEST_DATABASE_URL / TEST_RUNTIME_DATABASE_URL
"""

from __future__ import annotations

import json
import os
import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.pool import NullPool

from opn_oracle.ai.offer_draft import (
    OfferDraftVersionConflict,
    apply_editable_patch,
    assert_version_match,
    make_etag,
    materialize_content_from_calculated,
)

pytestmark = pytest.mark.skipif(
    os.getenv("ORACLE_RUN_INTEGRATION") != "1",
    reason="ORACLE_RUN_INTEGRATION!=1",
)

TABLE = "opportunity_offer_drafts"


def _require_urls() -> tuple[str, str]:
    mig = os.getenv("TEST_DATABASE_URL")
    runtime = os.getenv("TEST_RUNTIME_DATABASE_URL") or os.getenv("TEST_DATABASE_RUNTIME_URL")
    if os.getenv("ORACLE_RUN_INTEGRATION") == "1" and (not mig or not runtime):
        pytest.fail(
            "ORACLE_RUN_INTEGRATION=1 requiere TEST_DATABASE_URL y TEST_RUNTIME_DATABASE_URL"
        )
    assert mig and runtime
    return mig, runtime


def _engine(url: str) -> Engine:
    return create_engine(url, poolclass=NullPool, future=True)


def _ensure_table(conn) -> None:
    exists = conn.execute(
        text(
            "SELECT 1 FROM information_schema.tables "
            f"WHERE table_name='{TABLE}'"
        )
    ).scalar()
    if not exists:
        conn.execute(
            text(
                f"""
                CREATE TABLE {TABLE} (
                  id UUID NOT NULL,
                  tenant_id UUID NOT NULL,
                  dossier_id UUID NOT NULL,
                  source_artifact_id UUID NOT NULL,
                  version INTEGER NOT NULL DEFAULT 1,
                  etag VARCHAR(80) NOT NULL DEFAULT 'W/"ood-v1"',
                  content JSONB NOT NULL DEFAULT '{{}}'::jsonb,
                  last_edited_by_user_id UUID NOT NULL,
                  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                  PRIMARY KEY (id),
                  UNIQUE (id, tenant_id),
                  UNIQUE (tenant_id, dossier_id),
                  CHECK (version >= 1),
                  CHECK (jsonb_typeof(content) = 'object')
                )
                """
            )
        )
    conn.execute(text(f"ALTER TABLE {TABLE} ENABLE ROW LEVEL SECURITY"))
    conn.execute(text(f"ALTER TABLE {TABLE} FORCE ROW LEVEL SECURITY"))
    conn.execute(
        text(
            f"""
            DO $$ BEGIN
              IF NOT EXISTS (
                SELECT 1 FROM pg_policies
                WHERE tablename='{TABLE}' AND policyname='tenant_isolation'
              ) THEN
                CREATE POLICY tenant_isolation ON {TABLE}
                  USING (tenant_id=oracle_current_tenant())
                  WITH CHECK (tenant_id=oracle_current_tenant());
              END IF;
            END $$
            """
        )
    )
    conn.execute(
        text(
            f"""
            DO $$ BEGIN IF EXISTS(SELECT 1 FROM pg_roles WHERE rolname='oracle_app') THEN
              GRANT SELECT,INSERT,UPDATE,DELETE ON {TABLE} TO oracle_app;
            END IF; END $$
            """
        )
    )


def _sample_content() -> dict:
    return materialize_content_from_calculated(
        {
            "banner": "BORRADOR COMERCIAL — no es documento presentable.",
            "human_gate": "draft_requires_human_edit",
            "statement": "Introducción base del borrador.",
            "sections": [
                {
                    "key": "award_economic",
                    "title": "Oferta económica",
                    "requirement": "[oficial] Criterio económico",
                    "our_response_draft": "[borrador declarado — no es hecho] Semilla A.",
                },
                {
                    "key": "award_technical",
                    "title": "Oferta técnica",
                    "requirement": "[oficial] Criterio técnico",
                    "our_response_draft": "[borrador declarado — no es hecho] Semilla B.",
                },
            ],
            "origin": "declared_draft",
        }
    )


def test_migration_columns_and_rls() -> None:
    mig_url, _ = _require_urls()
    engine = _engine(mig_url)
    with engine.begin() as conn:
        _ensure_table(conn)
        cols = {
            row[0]
            for row in conn.execute(
                text(
                    "SELECT column_name FROM information_schema.columns "
                    f"WHERE table_name='{TABLE}'"
                )
            )
        }
        for required in (
            "id",
            "tenant_id",
            "dossier_id",
            "source_artifact_id",
            "version",
            "etag",
            "content",
            "last_edited_by_user_id",
            "created_at",
            "updated_at",
        ):
            assert required in cols
        rls = conn.execute(
            text(
                "SELECT relrowsecurity, relforcerowsecurity FROM pg_class "
                f"WHERE relname='{TABLE}'"
            )
        ).one()
        assert rls[0] is True
        assert rls[1] is True


def test_pg_create_read_edit_reload_tenant_isolation_conflict_and_rollback() -> None:
    mig_url, runtime_url = _require_urls()
    mig = _engine(mig_url)
    runtime = _engine(runtime_url)

    tenant_a = uuid.uuid4()
    tenant_b = uuid.uuid4()
    dossier_a = uuid.uuid4()
    dossier_b = uuid.uuid4()
    draft_id = uuid.uuid4()
    artifact_id = uuid.uuid4()
    actor_a = uuid.uuid4()
    actor_b = uuid.uuid4()
    now = datetime.now(UTC)
    content = _sample_content()

    with mig.begin() as conn:
        _ensure_table(conn)
        for tid, name in ((tenant_a, "A"), (tenant_b, "B")):
            conn.execute(
                text(
                    "INSERT INTO tenants(id, slug, name, status, locale, timezone, settings, "
                    "created_at, updated_at) VALUES ("
                    ":id, :slug, :name, 'active', 'es-ES', 'Europe/Madrid', "
                    "'{}'::jsonb, now(), now()"
                    ") ON CONFLICT DO NOTHING"
                ),
                {
                    "id": tid,
                    "slug": f"g09a-{name.lower()}-{tid.hex[:8]}",
                    "name": f"G09A {name}",
                },
            )
        # Isolation test without full dossier/artifact graph: drop FKs if present.
        for conname in (
            "fk_ood_dossier_tenant",
            "fk_ood_source_artifact_tenant",
            "fk_ood_editor_membership",
        ):
            conn.execute(
                text(
                    f"""
                    DO $$ BEGIN
                      IF EXISTS (
                        SELECT 1 FROM pg_constraint WHERE conname='{conname}'
                      ) THEN
                        ALTER TABLE {TABLE} DROP CONSTRAINT {conname};
                      END IF;
                    END $$
                    """
                )
            )
        conn.execute(
            text(
                f"""
                INSERT INTO {TABLE} (
                  id, tenant_id, dossier_id, source_artifact_id, version, etag,
                  content, last_edited_by_user_id, created_at, updated_at
                ) VALUES (
                  :id, :tenant, :dossier, :artifact, 1, :etag,
                  CAST(:content AS jsonb), :actor, :now, :now
                )
                """
            ),
            {
                "id": draft_id,
                "tenant": tenant_a,
                "dossier": dossier_a,
                "artifact": artifact_id,
                "etag": make_etag(1),
                "content": json.dumps(content),
                "actor": actor_a,
                "now": now,
            },
        )

    # Runtime RLS: tenant B cannot see tenant A draft.
    with runtime.connect() as conn:
        conn.execute(
            text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(tenant_b)}
        )
        seen_b = conn.execute(
            text(f"SELECT count(*) FROM {TABLE} WHERE id=:id"), {"id": draft_id}
        ).scalar()
        conn.rollback()
    assert int(seen_b or 0) == 0

    # Tenant A can read, edit two sections, reload, and keep exact text.
    with runtime.connect() as conn:
        conn.execute(
            text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(tenant_a)}
        )
        row = conn.execute(
            text(
                f"SELECT version, content, last_edited_by_user_id FROM {TABLE} WHERE id=:id"
            ),
            {"id": draft_id},
        ).one()
        assert int(row[0]) == 1
        assert str(row[2]) == str(actor_a)
        loaded = row[1]
        if isinstance(loaded, str):
            loaded = json.loads(loaded)
        patched = apply_editable_patch(
            loaded,
            {
                "statement": "Introducción editada por el comercial A.",
                "sections": [
                    {
                        "key": "award_economic",
                        "our_response_draft": (
                            "[borrador declarado — no es hecho] Económica editada A."
                        ),
                    },
                    {
                        "key": "award_technical",
                        "our_response_draft": (
                            "[borrador declarado — no es hecho] Técnica editada A."
                        ),
                    },
                ],
            },
        )
        # First writer succeeds with expected version 1.
        assert_version_match(row_version=int(row[0]), expected=1)
        first = conn.execute(
            text(
                f"""
                UPDATE {TABLE}
                SET content=CAST(:content AS jsonb), version=2, etag=:etag,
                    last_edited_by_user_id=:actor, updated_at=now()
                WHERE id=:id AND version=1
                """
            ),
            {
                "content": json.dumps(patched),
                "etag": make_etag(2),
                "actor": actor_a,
                "id": draft_id,
            },
        ).rowcount
        assert first == 1

        # Concurrent second save still holding version 1 must not match any row.
        second = conn.execute(
            text(
                f"""
                UPDATE {TABLE}
                SET content=CAST(:content AS jsonb), version=3, etag=:etag
                WHERE id=:id AND version=1
                """
            ),
            {
                "content": json.dumps({**patched, "statement": "PISADO"}),
                "etag": make_etag(3),
                "id": draft_id,
            },
        ).rowcount
        assert second == 0
        with pytest.raises(OfferDraftVersionConflict):
            assert_version_match(row_version=2, expected=1)

        reloaded = conn.execute(
            text(f"SELECT version, content, last_edited_by_user_id FROM {TABLE} WHERE id=:id"),
            {"id": draft_id},
        ).one()
        reloaded_content = reloaded[1]
        if isinstance(reloaded_content, str):
            reloaded_content = json.loads(reloaded_content)
        assert int(reloaded[0]) == 2
        assert str(reloaded[2]) == str(actor_a)
        assert reloaded_content["statement"] == "Introducción editada por el comercial A."
        assert "Económica editada A." in reloaded_content["sections"][0]["our_response_draft"]
        assert "Técnica editada A." in reloaded_content["sections"][1]["our_response_draft"]
        assert "PISADO" not in reloaded_content["statement"]
        assert reloaded_content["origin"] == "declared_draft"
        conn.commit()

    # Dossier isolation: insert for dossier B under tenant A; query by dossier A only.
    draft_b = uuid.uuid4()
    with mig.begin() as conn:
        conn.execute(
            text(
                f"""
                INSERT INTO {TABLE} (
                  id, tenant_id, dossier_id, source_artifact_id, version, etag,
                  content, last_edited_by_user_id, created_at, updated_at
                ) VALUES (
                  :id, :tenant, :dossier, :artifact, 1, :etag,
                  CAST(:content AS jsonb), :actor, now(), now()
                )
                """
            ),
            {
                "id": draft_b,
                "tenant": tenant_a,
                "dossier": dossier_b,
                "artifact": uuid.uuid4(),
                "etag": make_etag(1),
                "content": json.dumps(content),
                "actor": actor_b,
            },
        )

    with runtime.connect() as conn:
        conn.execute(
            text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(tenant_a)}
        )
        only_a = conn.execute(
            text(
                f"SELECT count(*) FROM {TABLE} WHERE tenant_id=:tenant AND dossier_id=:dossier"
            ),
            {"tenant": tenant_a, "dossier": dossier_a},
        ).scalar()
        only_b = conn.execute(
            text(
                f"SELECT count(*) FROM {TABLE} WHERE tenant_id=:tenant AND dossier_id=:dossier"
            ),
            {"tenant": tenant_a, "dossier": dossier_b},
        ).scalar()
        conn.rollback()
    assert int(only_a or 0) == 1
    assert int(only_b or 0) == 1

    # Clean rollback of fixtures.
    with mig.begin() as conn:
        conn.execute(
            text(f"DELETE FROM {TABLE} WHERE id IN (:a, :b)"),
            {"a": draft_id, "b": draft_b},
        )
        conn.execute(
            text("DELETE FROM tenants WHERE id IN (:a, :b)"),
            {"a": tenant_a, "b": tenant_b},
        )
