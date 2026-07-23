from __future__ import annotations

import pytest

from tests.test_integration_oracle_domain import (
    _assert_procurement_search_profile_acceptance_is_explicit_and_versioned,
    _assert_procurement_search_profiles_hide_cross_tenant_rows,
    _assert_tender_search_wizard_http_reuses_same_input_artifact,
)
from tests.test_integration_oracle_domain import (
    oracle_stack as _oracle_stack_fixture,  # noqa: F401
)


@pytest.mark.integration
def test_tender_search_wizard_http_reuses_same_input_artifact(
    request: pytest.FixtureRequest,
) -> None:
    oracle_stack = request.getfixturevalue("_oracle_stack_fixture")
    _assert_tender_search_wizard_http_reuses_same_input_artifact(oracle_stack)


@pytest.mark.integration
def test_procurement_search_profile_acceptance_is_explicit_and_versioned(
    request: pytest.FixtureRequest,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    oracle_stack = request.getfixturevalue("_oracle_stack_fixture")
    _assert_procurement_search_profile_acceptance_is_explicit_and_versioned(
        oracle_stack,
        monkeypatch,
    )


@pytest.mark.integration
def test_procurement_search_profiles_hide_cross_tenant_rows(
    request: pytest.FixtureRequest,
) -> None:
    oracle_stack = request.getfixturevalue("_oracle_stack_fixture")
    _assert_procurement_search_profiles_hide_cross_tenant_rows(oracle_stack)
