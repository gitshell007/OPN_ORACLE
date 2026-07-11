"""Periodic document retention maintenance."""

from __future__ import annotations

from celery import shared_task
from sqlalchemy import select

from opn_oracle.documents.service import (
    purge_due_documents,
    reconcile_storage_orphans,
    recover_expired_document_attempts,
)
from opn_oracle.extensions import db
from opn_oracle.platform.models import Tenant
from opn_oracle.tenants.context import TenantContext, tenant_context


@shared_task(name="maintenance.documents_retention", ignore_result=True)
def documents_retention() -> int:
    total = 0
    tenant_ids = list(db.session.scalars(select(Tenant.id)))
    for tenant_id in tenant_ids:
        with tenant_context(TenantContext(tenant_id=tenant_id, actor_id=None)):
            total += purge_due_documents(tenant_id)
            total += reconcile_storage_orphans(tenant_id)
            total += recover_expired_document_attempts(tenant_id)
            db.session.remove()
    return total
