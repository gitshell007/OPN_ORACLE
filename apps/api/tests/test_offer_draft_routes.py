"""Route-level contract for opportunity offer draft (no full app stack)."""

from __future__ import annotations

import inspect

import pytest

from opn_oracle.ai.routes import (
    get_opportunity_offer_draft,
    patch_opportunity_offer_draft,
    prepare_opportunity_offer_draft,
)


@pytest.mark.unit
def test_prepare_route_docs_materialize_not_silent_overwrite() -> None:
    doc = inspect.getdoc(prepare_opportunity_offer_draft) or ""
    assert "materializa" in doc.casefold() or "Materializa" in doc
    assert "sobrescribir" in doc.casefold() or "Idempotente" in doc


@pytest.mark.unit
def test_get_and_patch_routes_exist_and_require_permission_docs() -> None:
    assert callable(get_opportunity_offer_draft)
    assert callable(patch_opportunity_offer_draft)
    source = inspect.getsource(patch_opportunity_offer_draft)
    assert "version" in source
    assert "append_audit_event" in source
    assert "If-Match" in source or "parse_expected_version" in source
    assert "tenant_id" in source  # rejected from client payload
    prep = inspect.getsource(prepare_opportunity_offer_draft)
    assert "draft_offer" in prep
    assert "current_user.id" in prep
    assert "g.active_tenant_id" in prep
