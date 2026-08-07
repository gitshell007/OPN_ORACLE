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
    # Enumerating tenants starts an unscoped transaction. Close that transaction
    # before entering the first TenantContext; reusing it would make the
    # transaction-context guard reject the tenant change.
    db.session.remove()
    for tenant_id in tenant_ids:
        with tenant_context(TenantContext(tenant_id=tenant_id, actor_id=None)):
            try:
                total += purge_due_documents(tenant_id)
                total += reconcile_storage_orphans(tenant_id)
                total += recover_expired_document_attempts(tenant_id)
            finally:
                # Never let one tenant's transaction leak into the next tenant,
                # including when a storage/database operation raises.
                db.session.remove()
    return total
