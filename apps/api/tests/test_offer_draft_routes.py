"""Route-level contract for opportunity offer draft CAS helpers (unit)."""

from __future__ import annotations

import inspect
import uuid
from datetime import UTC, datetime

import pytest

from opn_oracle.ai.offer_draft import cas_update_offer_draft_sql, make_etag
from opn_oracle.ai.routes import (
    get_opportunity_offer_draft,
    patch_opportunity_offer_draft,
    prepare_opportunity_offer_draft,
)


@pytest.mark.unit
def test_export_route_uses_persisted_draft_and_version_gate() -> None:
    from opn_oracle.ai.routes import export_opportunity_offer_draft_docx

    source = inspect.getsource(export_opportunity_offer_draft_docx)
    assert "build_offer_draft_docx" in source
    assert "opportunity.offer_draft.export" in source
    assert "parse_expected_version" in source
    assert "OfferDraftVersionConflict" in source
    assert "offer_draft_not_found" in source
    # Must not re-materialize from calculated artifact during export.
    assert "materialize_content_from_calculated" not in source


@pytest.mark.unit
def test_prepare_route_docs_materialize_not_silent_overwrite() -> None:
    doc = inspect.getdoc(prepare_opportunity_offer_draft) or ""
    assert "materializa" in doc.casefold() or "Materializa" in doc
    assert "sobrescribir" in doc.casefold() or "Idempotente" in doc
    prep = inspect.getsource(prepare_opportunity_offer_draft)
    assert "IntegrityError" in prep


@pytest.mark.unit
def test_patch_uses_atomic_cas_update() -> None:
    assert callable(get_opportunity_offer_draft)
    assert callable(patch_opportunity_offer_draft)
    source = inspect.getsource(patch_opportunity_offer_draft)
    assert "cas_update_offer_draft_sql" in source
    assert "rowcount" in source
    assert "append_audit_event" in source
    assert "version_conflict" in source
    assert "precondition_required" in source

    stmt = cas_update_offer_draft_sql(
        tenant_id=uuid.uuid4(),
        dossier_id=uuid.uuid4(),
        expected_version=1,
        next_content={"statement": "x", "sections": []},
        actor_id=uuid.uuid4(),
        new_version=2,
        new_etag=make_etag(2),
        updated_at=datetime.now(UTC),
    )
    compiled = str(stmt.compile(compile_kwargs={"literal_binds": False}))
    # Predicates must include tenant, dossier and expected version.
    assert "opportunity_offer_drafts" in compiled.casefold() or "OpportunityOfferDraft" in repr(
        stmt
    )
    where = str(stmt.whereclause)
    assert "tenant_id" in where
    assert "dossier_id" in where
    assert "version" in where
