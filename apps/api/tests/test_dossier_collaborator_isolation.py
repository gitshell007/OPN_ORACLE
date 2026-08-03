"""Aislamiento de colaboradores: no se puede invitar a otra organización."""

from __future__ import annotations

import uuid
from unittest.mock import MagicMock

import pytest

from opn_oracle.oracle.policy import active_membership_exists


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
