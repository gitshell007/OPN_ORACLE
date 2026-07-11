"""Deterministic identities for the disposable frontend E2E database."""

from datetime import UTC, datetime

from opn_oracle import create_app
from opn_oracle.auth.passwords import PasswordHasher, PasswordPolicy
from opn_oracle.extensions import db
from opn_oracle.platform.models import MembershipRole, Tenant, TenantMembership, User, Workspace
from opn_oracle.platform.rbac import seed_system_roles
from opn_oracle.tenants.context import TenantContext, tenant_context

PASSWORD = "Oracle E2E segura 2026"


def seed() -> None:
    app = create_app()
    with app.app_context():
        hasher = PasswordHasher(PasswordPolicy(12, 1024))
        tenant = Tenant(slug="asterion-e2e", name="Asterion E2E", status="active")
        second_tenant = Tenant(slug="boreal-e2e", name="Boreal E2E", status="active")
        owner = User(
            email="owner@oracle-e2e.test",
            display_name="Olivia Owner",
            status="active",
            password_hash=hasher.hash(PASSWORD),
            email_verified_at=datetime.now(UTC),
        )
        viewer = User(
            email="viewer@oracle-e2e.test",
            display_name="Víctor Viewer",
            status="active",
            password_hash=hasher.hash(PASSWORD),
            email_verified_at=datetime.now(UTC),
        )
        platform = User(
            email="platform@oracle-e2e.test",
            display_name="Paula Plataforma",
            status="active",
            platform_role="super_admin",
            password_hash=hasher.hash(PASSWORD),
            email_verified_at=datetime.now(UTC),
        )
        db.session.add_all([tenant, second_tenant, owner, viewer, platform])
        db.session.flush()
        db.session.add(
            Workspace(
                tenant_id=tenant.id,
                slug="principal",
                name="Principal",
                status="active",
                is_default=True,
            )
        )
        db.session.add(
            Workspace(
                tenant_id=second_tenant.id,
                slug="principal",
                name="Principal",
                status="active",
                is_default=True,
            )
        )
        membership = TenantMembership(
            tenant_id=tenant.id, user_id=owner.id, status="active", accepted_at=datetime.now(UTC)
        )
        second_membership = TenantMembership(
            tenant_id=second_tenant.id,
            user_id=owner.id,
            status="active",
            accepted_at=datetime.now(UTC),
        )
        viewer_membership = TenantMembership(
            tenant_id=tenant.id, user_id=viewer.id, status="active", accepted_at=datetime.now(UTC)
        )
        db.session.add_all([membership, second_membership, viewer_membership])
        db.session.flush()
        tenant_id, second_tenant_id, owner_id = tenant.id, second_tenant.id, owner.id
        membership_id, second_membership_id, viewer_membership_id = (
            membership.id,
            second_membership.id,
            viewer_membership.id,
        )
        db.session.commit()
        with tenant_context(TenantContext(tenant_id=tenant_id, actor_id=owner_id)):
            roles = seed_system_roles(db.session, tenant_id)
            db.session.add(
                MembershipRole(
                    tenant_id=tenant_id, membership_id=membership_id, role_id=roles["owner"].id
                )
            )
            db.session.add(
                MembershipRole(
                    tenant_id=tenant_id,
                    membership_id=viewer_membership_id,
                    role_id=roles["viewer"].id,
                )
            )
            db.session.commit()
        with tenant_context(TenantContext(tenant_id=second_tenant_id, actor_id=owner_id)):
            roles = seed_system_roles(db.session, second_tenant_id)
            db.session.add(
                MembershipRole(
                    tenant_id=second_tenant_id,
                    membership_id=second_membership_id,
                    role_id=roles["owner"].id,
                )
            )
            db.session.commit()


if __name__ == "__main__":
    seed()
