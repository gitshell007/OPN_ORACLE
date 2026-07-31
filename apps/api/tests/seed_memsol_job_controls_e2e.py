"""Seed durable MEMSOL jobs that are never published (stay queued/failed for E2E).

Invoked by scripts/run-auth-e2e-api.sh after seed-oracle-demo.
Writes /tmp/memsol_e2e_job_controls.json for Playwright discovery.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime
from pathlib import Path

from opn_oracle import create_app
from opn_oracle.extensions import db
from opn_oracle.oracle.conversations import DossierConversation, DossierMessage
from opn_oracle.oracle.jobs import BackgroundJob
from opn_oracle.oracle.models import StrategicDossier
from opn_oracle.platform.models import Tenant, TenantMembership, User
from opn_oracle.tenants.context import TenantContext, tenant_context
from sqlalchemy import select

FIXTURE_PATH = Path("/tmp/memsol_e2e_job_controls.json")

# Deterministic UUIDs for stable Playwright selectors across e2e boots
QUEUED_JOB_ID = uuid.UUID("b1000000-0000-4000-8000-000000000001")
FAILED_JOB_ID = uuid.UUID("b1000000-0000-4000-8000-000000000002")
CONVERSATION_ID = uuid.UUID("b1000000-0000-4000-8000-000000000003")
MESSAGE_QUEUED_ID = uuid.UUID("b1000000-0000-4000-8000-000000000004")
MESSAGE_FAILED_ID = uuid.UUID("b1000000-0000-4000-8000-000000000005")
BRIEF_REPORT_ID = uuid.UUID("b1000000-0000-4000-8000-000000000006")


def _digest(payload: dict) -> bytes:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).digest()


def seed() -> dict:
    app = create_app()
    with app.app_context():
        # Resolve identities without tenant context, then commit so the next
        # tenant_context starts a clean transaction (RLS guard).
        tenant = db.session.scalar(select(Tenant).where(Tenant.slug == "asterion-e2e"))
        if tenant is None:
            raise RuntimeError("asterion-e2e tenant missing; run seed_frontend_e2e first")
        tenant_id = tenant.id
        dossier = db.session.scalar(
            select(StrategicDossier)
            .where(StrategicDossier.tenant_id == tenant_id)
            .order_by(StrategicDossier.created_at.asc())
            .limit(1)
        )
        if dossier is None:
            raise RuntimeError("no dossier for asterion-e2e; run seed-oracle-demo first")
        dossier_id = dossier.id
        owner = db.session.scalar(
            select(User)
            .join(TenantMembership, TenantMembership.user_id == User.id)
            .where(
                TenantMembership.tenant_id == tenant_id,
                TenantMembership.status == "active",
                User.email == "owner@oracle-e2e.test",
            )
        )
        if owner is None:
            raise RuntimeError("owner@oracle-e2e.test membership missing")
        owner_id = owner.id
        if dossier.owner_user_id is None:
            dossier.owner_user_id = owner_id
        db.session.commit()

        queued_question = "Pregunta E2E en cola para cancelar (nunca publicada al broker)."
        failed_question = "Pregunta E2E fallida para reintentar."

        with tenant_context(
            TenantContext(
                tenant_id=tenant_id,
                actor_id=owner_id,
                platform_access=True,
                access_reason="MEMSOL e2e control fixtures",
            )
        ):
            for mid in (MESSAGE_QUEUED_ID, MESSAGE_FAILED_ID):
                existing = db.session.get(DossierMessage, mid)
                if existing is not None:
                    db.session.delete(existing)
            for jid in (QUEUED_JOB_ID, FAILED_JOB_ID):
                existing_job = db.session.get(BackgroundJob, jid)
                if existing_job is not None:
                    db.session.delete(existing_job)
            existing_conv = db.session.get(DossierConversation, CONVERSATION_ID)
            if existing_conv is not None:
                db.session.delete(existing_conv)
            db.session.flush()

            conversation = DossierConversation(
                id=CONVERSATION_ID,
                tenant_id=tenant_id,
                dossier_id=dossier_id,
                status="open",
                title="MEMSOL E2E controls",
                created_by_user_id=owner_id,
            )
            db.session.add(conversation)
            db.session.flush()

            q_payload = {
                "message_id": str(MESSAGE_QUEUED_ID),
                "conversation_id": str(CONVERSATION_ID),
                "dossier_id": str(dossier_id),
            }
            queued_job = BackgroundJob(
                id=QUEUED_JOB_ID,
                tenant_id=tenant_id,
                dossier_id=dossier_id,
                job_type="oracle.dossier_question.answer",
                status="queued",
                stage="queued",
                queue="ai",
                progress=0,
                idempotency_key="memsol-e2e-queued-control",
                payload_hash=_digest(q_payload),
                input_payload=q_payload,
                resource_type="dossier_message",
                resource_id=MESSAGE_QUEUED_ID,
                requested_by_user_id=owner_id,
                retryable=True,
                cancel_requested=False,
                attempts=0,
                max_attempts=3,
                version=1,
                celery_task_id=str(uuid.uuid4()),
            )
            db.session.add(queued_job)
            db.session.flush()

            db.session.add(
                DossierMessage(
                    id=MESSAGE_QUEUED_ID,
                    tenant_id=tenant_id,
                    dossier_id=dossier_id,
                    conversation_id=CONVERSATION_ID,
                    role="user",
                    status="queued",
                    sequence=1,
                    content_text=queued_question,
                    background_job_id=QUEUED_JOB_ID,
                    created_by_user_id=owner_id,
                    answer_payload={},
                    coverage_manifest={},
                )
            )

            f_payload = {
                "message_id": str(MESSAGE_FAILED_ID),
                "conversation_id": str(CONVERSATION_ID),
                "dossier_id": str(dossier_id),
            }
            failed_job = BackgroundJob(
                id=FAILED_JOB_ID,
                tenant_id=tenant_id,
                dossier_id=dossier_id,
                job_type="oracle.dossier_question.answer",
                status="failed",
                stage="failed",
                queue="ai",
                progress=0,
                idempotency_key="memsol-e2e-failed-control",
                payload_hash=_digest(f_payload),
                input_payload=f_payload,
                resource_type="dossier_message",
                resource_id=MESSAGE_FAILED_ID,
                requested_by_user_id=owner_id,
                retryable=True,
                cancel_requested=False,
                attempts=1,
                max_attempts=3,
                version=1,
                error_code="permanent_failure",
                error_message="fallo controlado E2E para reintentar",
                celery_task_id=str(uuid.uuid4()),
            )
            db.session.add(failed_job)
            db.session.flush()

            db.session.add(
                DossierMessage(
                    id=MESSAGE_FAILED_ID,
                    tenant_id=tenant_id,
                    dossier_id=dossier_id,
                    conversation_id=CONVERSATION_ID,
                    role="user",
                    status="failed",
                    sequence=2,
                    content_text=failed_question,
                    background_job_id=FAILED_JOB_ID,
                    error_code="permanent_failure",
                    error_message="fallo controlado E2E para reintentar",
                    created_by_user_id=owner_id,
                    answer_payload={},
                    coverage_manifest={},
                )
            )
            db.session.commit()

        fixture = {
            "dossier_id": str(dossier_id),
            "conversation_id": str(CONVERSATION_ID),
            "queued_job_id": str(QUEUED_JOB_ID),
            "failed_job_id": str(FAILED_JOB_ID),
            "queued_message_id": str(MESSAGE_QUEUED_ID),
            "failed_message_id": str(MESSAGE_FAILED_ID),
            "queued_question": queued_question,
            "failed_question": failed_question,
            "seeded_at": datetime.now(UTC).isoformat(),
        }
        FIXTURE_PATH.write_text(json.dumps(fixture, indent=2))
        return fixture

if __name__ == "__main__":
    print(json.dumps(seed(), indent=2))
