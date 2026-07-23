from __future__ import annotations

import hashlib
import json
import os
import uuid
from pathlib import Path
from typing import Any

import pytest
from flask_migrate import downgrade, upgrade
from sqlalchemy import create_engine, text

from opn_oracle import create_app

pytestmark = pytest.mark.integration


def _env() -> tuple[str, str, str]:
    migration_url = os.environ.get("TEST_DATABASE_URL")
    runtime_url = os.environ.get("TEST_RUNTIME_DATABASE_URL")
    redis_url = os.environ.get("TEST_REDIS_URL")
    if not migration_url or not runtime_url or not redis_url:
        pytest.skip("define TEST_DATABASE_URL, TEST_RUNTIME_DATABASE_URL y TEST_REDIS_URL")
    if "test" not in migration_url.lower() or "test" not in runtime_url.lower():
        pytest.fail("Las URLs de integración deben apuntar a una base desechable con 'test'")
    return migration_url, runtime_url, redis_url


def _plan() -> dict[str, Any]:
    return {
        "intent_summary": "Equipamiento de emergencia",
        "include_terms": ["proteccion"],
        "synonyms": [],
        "exclude_terms": [],
        "candidate_cpv": [
            {
                "code": "18100000",
                "label": "Prendas de vestir, calzado, artículos de viaje y accesorios",
            }
        ],
        "buyers": ["Servicios de emergencias"],
        "geographies": ["España"],
        "scope": "active",
        "min_amount": None,
        "max_amount": None,
        "assumptions": [],
        "questions": [],
        "confidence": 80,
        "discarded_count": 0,
        "discarded_reasons": {},
    }


def _seed_profile_with_feedback(
    connection: Any,
    *,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    slug: str,
) -> tuple[uuid.UUID, uuid.UUID]:
    membership_id = uuid.uuid4()
    audit_id = uuid.uuid4()
    artifact_id = uuid.uuid4()
    profile_id = uuid.uuid4()
    feedback_id = uuid.uuid4()
    plan = _plan()
    plan_hash = hashlib.sha256(
        json.dumps(plan, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).digest()
    output_hash = hashlib.sha256(b"artifact-output").digest()
    connection.execute(
        text(
            "INSERT INTO tenants("
            "id,slug,name,status,locale,timezone,settings,created_at,updated_at"
            ") "
            "VALUES (:tenant,:slug,:name,'active','es-ES','UTC','{}',now(),now())"
        ),
        {"tenant": tenant_id, "slug": slug, "name": slug.upper()},
    )
    connection.execute(
        text(
            "INSERT INTO tenant_memberships("
            "id,tenant_id,user_id,status,settings,created_at,updated_at"
            ") "
            "VALUES (:membership,:tenant,:user,'active','{}',now(),now())"
        ),
        {"membership": membership_id, "tenant": tenant_id, "user": user_id},
    )
    connection.execute(
        text(
            "INSERT INTO ai_audit_logs("
            "id,tenant_id,requested_by_user_id,use_case,agent,action,provider,model,"
            "prompt_name,prompt_version,prompt_hash,schema_name,schema_version,input_hash,"
            "output_hash,source_ids,status,data_classification,redaction_applied,"
            "redaction_summary,input_tokens,output_tokens,actual_cost_micros,currency,"
            "attempt_count,human_review_state,created_at,updated_at"
            ") VALUES ("
            ":audit,:tenant,:user,'tender_search_wizard','tender_search_wizard','generate',"
            "'mock','mock-oracle-v1','tender_search_wizard','v2',:hash,'TenderSearchWizardOutput',"
            "'v1',:hash,:output_hash,'[]','succeeded','internal',false,'{}',0,0,0,"
            "'EUR',1,'not_required',now(),now())"
        ),
        {
            "audit": audit_id,
            "tenant": tenant_id,
            "user": user_id,
            "hash": b"p" * 32,
            "output_hash": output_hash,
        },
    )
    connection.execute(
        text(
            "INSERT INTO ai_artifacts("
            "id,tenant_id,audit_log_id,dossier_id,target_type,target_id,agent,schema_name,"
            "schema_version,output,output_hash,status,version,created_at,updated_at"
            ") VALUES ("
            ":artifact,:tenant,:audit,NULL,'tenant_search_profile',:tenant,"
            "'tender_search_wizard','TenderSearchWizardOutput','v1',:plan,:output_hash,"
            "'valid',1,now(),now())"
        ),
        {
            "artifact": artifact_id,
            "tenant": tenant_id,
            "audit": audit_id,
            "plan": json.dumps(plan),
            "output_hash": output_hash,
        },
    )
    connection.execute(
        text(
            "INSERT INTO procurement_search_profiles("
            "id,tenant_id,original_description,comparables,accepted_plan,accepted_plan_hash,"
            "version,ai_artifact_id,accepted_by_user_id,created_at,updated_at,last_accepted_at"
            ") VALUES ("
            ":profile,:tenant,'Equipamiento de emergencia','[]',:plan,:plan_hash,1,"
            ":artifact,:user,now(),now(),now())"
        ),
        {
            "profile": profile_id,
            "tenant": tenant_id,
            "plan": json.dumps(plan),
            "plan_hash": plan_hash,
            "artifact": artifact_id,
            "user": user_id,
        },
    )
    connection.execute(
        text(
            "INSERT INTO procurement_search_feedback("
            "id,tenant_id,profile_id,plan_version,folder_id,verdict,reason,note,"
            "actor_user_id,tender_title,tender_cpvs,created_at,updated_at"
            ") VALUES ("
            ":feedback,:tenant,:profile,1,:folder,'not_relevant','region','',:user,"
            "'Licitacion fuera de region','[]',now(),now())"
        ),
        {
            "feedback": feedback_id,
            "tenant": tenant_id,
            "profile": profile_id,
            "folder": f"EXP-{slug}",
            "user": user_id,
        },
    )
    return profile_id, feedback_id


def _set_tenant(connection: Any, tenant_id: uuid.UUID) -> None:
    connection.execute(
        text("SELECT set_config('app.tenant_id', :tenant, false)"),
        {"tenant": str(tenant_id)},
    )


def test_procurement_search_feedback_0023_up_down_up_and_rls() -> None:
    migration_url, runtime_url, redis_url = _env()
    app = create_app(
        {
            "APP_ENV": "test",
            "SECRET_KEY": "procurement-feedback-migration",
            "DATABASE_URL": runtime_url,
            "DATABASE_MIGRATION_URL": migration_url,
            "REDIS_URL": redis_url,
        }
    )
    migrations = str(Path(__file__).resolve().parents[1] / "migrations")
    with app.app_context():
        downgrade(directory=migrations, revision="base")
        upgrade(directory=migrations, revision="20260723_0022")
        upgrade(directory=migrations, revision="20260723_0023")

    migrator = create_engine(migration_url)
    runtime = create_engine(runtime_url)
    tenant_a, tenant_b, user_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    with migrator.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO users(id,email,display_name,status,created_at,updated_at) "
                "VALUES ("
                ":user,'feedback-migration@example.test','Feedback migration',"
                "'active',now(),now())"
            ),
            {"user": user_id},
        )
        profile_a, feedback_a = _seed_profile_with_feedback(
            connection,
            tenant_id=tenant_a,
            user_id=user_id,
            slug="tenant-a",
        )
        profile_b, feedback_b = _seed_profile_with_feedback(
            connection,
            tenant_id=tenant_b,
            user_id=user_id,
            slug="tenant-b",
        )

    with runtime.begin() as connection:
        _set_tenant(connection, tenant_a)
        assert connection.scalar(text("SELECT count(*) FROM procurement_search_feedback")) == 1
        assert (
            connection.scalar(
                text(
                    "SELECT count(*) FROM procurement_search_feedback "
                    "WHERE id=:feedback AND profile_id=:profile"
                ),
                {"feedback": feedback_a, "profile": profile_a},
            )
            == 1
        )
        assert (
            connection.scalar(
                text("SELECT count(*) FROM procurement_search_feedback WHERE id=:feedback"),
                {"feedback": feedback_b},
            )
            == 0
        )
    with runtime.begin() as connection:
        _set_tenant(connection, tenant_b)
        assert connection.scalar(text("SELECT count(*) FROM procurement_search_feedback")) == 1
        assert (
            connection.scalar(
                text("SELECT count(*) FROM procurement_search_feedback WHERE id=:feedback"),
                {"feedback": feedback_a},
            )
            == 0
        )
        assert (
            connection.scalar(
                text(
                    "SELECT count(*) FROM procurement_search_feedback "
                    "WHERE id=:feedback AND profile_id=:profile"
                ),
                {"feedback": feedback_b, "profile": profile_b},
            )
            == 1
        )

    with app.app_context():
        downgrade(directory=migrations, revision="20260723_0022")
    with migrator.connect() as connection:
        assert connection.scalar(text("SELECT to_regclass('procurement_search_feedback')")) is None
    with app.app_context():
        upgrade(directory=migrations, revision="20260723_0023")
    with migrator.connect() as connection:
        assert (
            connection.scalar(
                text("SELECT relrowsecurity FROM pg_class WHERE relname=:table"),
                {"table": "procurement_search_feedback"},
            )
            is True
        )

    with migrator.begin() as connection:
        connection.execute(text("DELETE FROM procurement_search_feedback"))
        connection.execute(text("DELETE FROM procurement_search_profiles"))
        connection.execute(text("DELETE FROM ai_artifacts WHERE dossier_id IS NULL"))
        connection.execute(text("DELETE FROM ai_audit_logs WHERE dossier_id IS NULL"))
        connection.execute(text("DELETE FROM tenant_memberships"))
        connection.execute(text("DELETE FROM tenants"))
        connection.execute(text("DELETE FROM users WHERE email='feedback-migration@example.test'"))
    runtime.dispose()
    migrator.dispose()
    with app.app_context():
        downgrade(directory=migrations, revision="base")
