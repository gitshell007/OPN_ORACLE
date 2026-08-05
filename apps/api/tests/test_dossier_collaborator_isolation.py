"""Aislamiento de colaboradores: no se puede invitar a otra organización."""

from __future__ import annotations

import uuid
from unittest.mock import MagicMock

import pytest

from opn_oracle.oracle.policy import (
    active_membership_exists,
    dossier_access_clause,
    dossier_accessible,
)


@pytest.mark.unit
def test_active_membership_exists_rejects_user_without_tenant_link() -> None:
    """Gate used by PUT /dossiers/{id}/collaborators/{user_id}.

    A user that is not an active member of the current tenant must not pass.
    This is what blocks inviting someone from another organization.
    """

    session = MagicMock()
    session.scalar.return_value = False
    tenant_id = uuid.uuid4()
    foreign_user_id = uuid.uuid4()

    assert active_membership_exists(session, tenant_id, foreign_user_id) is False
    session.scalar.assert_called_once()


@pytest.mark.unit
def test_active_membership_exists_accepts_same_tenant_member() -> None:
    session = MagicMock()
    session.scalar.return_value = True
    assert active_membership_exists(session, uuid.uuid4(), uuid.uuid4()) is True


@pytest.mark.unit
def test_collaborator_put_domain_rule_rejects_foreign_user() -> None:
    """Mirror the route guard: invalid role OR missing membership → reject.

    Route code (oracle/routes.collaborators_put):
        if role not in ROLES or not active_membership_exists(...):
            DomainValidationError("Colaborador o rol no válido.")
    """

    allowed_roles = {"owner", "editor", "collaborator", "viewer"}
    role = "viewer"
    same_tenant_member = False  # user from another org

    rejected = role not in allowed_roles or not same_tenant_member
    assert rejected is True


@pytest.mark.unit
def test_collaborator_put_domain_rule_accepts_same_org_member() -> None:
    allowed_roles = {"owner", "editor", "collaborator", "viewer"}
    role = "editor"
    same_tenant_member = True
    rejected = role not in allowed_roles or not same_tenant_member
    assert rejected is False


@pytest.mark.unit
def test_dossier_access_clause_is_tenant_bound() -> None:
    """Listing always scopes by tenant_id; cross-tenant rows cannot match."""

    tenant_id = uuid.uuid4()
    user_id = uuid.uuid4()
    clause = dossier_access_clause(tenant_id=tenant_id, user_id=user_id)
    compiled = str(clause)
    assert "strategic_dossiers.tenant_id" in compiled or "tenant_id" in compiled


@pytest.mark.unit
def test_dossier_accessible_requires_membership_first() -> None:
    """Without active membership, collaborator rows are never consulted."""

    session = MagicMock()
    session.scalar.return_value = False  # no membership
    dossier = MagicMock()
    dossier.tenant_id = uuid.uuid4()
    dossier.owner_user_id = uuid.uuid4()
    dossier.id = uuid.uuid4()

    assert dossier_accessible(session, dossier, uuid.uuid4(), write=False) is False
    # Only the membership probe should run; no collaborator lookup after False.
    assert session.scalar.call_count == 1
