"""Safe bootstrap commands for local platform data."""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime

import click
from flask import Flask, current_app
from sqlalchemy import select

from opn_oracle.auth.passwords import PasswordHasher, PasswordPolicy, PasswordPolicyError
from opn_oracle.extensions import db
from opn_oracle.platform.audit import append_global_audit_event
from opn_oracle.platform.models import (
    MembershipRole,
    Tenant,
    TenantMembership,
    User,
    Workspace,
)
from opn_oracle.platform.rbac import seed_system_roles
from opn_oracle.tenants.context import TenantContext, tenant_context


def register_platform_cli(app: Flask) -> None:
    @app.cli.group("admin")
    def admin() -> None:
        """Administración segura de plataforma."""

    @admin.command("bootstrap-superadmin")
    @click.option("--email", required=True)
    @click.option("--name", required=True)
    @click.option(
        "--rotate-password", is_flag=True, help="Rota la contraseña de una cuenta existente."
    )
    @click.option(
        "--confirm-production",
        is_flag=True,
        help="Confirma conscientemente la operación en producción.",
    )
    def bootstrap_superadmin(
        email: str, name: str, rotate_password: bool, confirm_production: bool
    ) -> None:
        """Crea el primer superadmin; el secreto se solicita sin eco."""

        if current_app.config["APP_ENV"] == "production" and not confirm_production:
            raise click.ClickException(
                "Producción exige --confirm-production y confirmación interactiva."
            )
        if current_app.config["APP_ENV"] == "production" and not click.confirm(
            "¿Confirmas el bootstrap/rotación en producción?"
        ):
            raise click.Abort()
        email, name = email.strip().casefold(), name.strip()
        if "@" not in email or not name:
            raise click.ClickException("Email y nombre deben ser válidos.")
        existing = db.session.scalar(select(User).where(User.email == email))
        if existing is not None and not rotate_password:
            raise click.ClickException(
                "El usuario ya existe; no se ha modificado. Usa --rotate-password conscientemente."
            )
        password = click.prompt("Contraseña", hide_input=True, confirmation_prompt=True)
        try:
            encoded = PasswordHasher(
                PasswordPolicy(
                    current_app.config["PASSWORD_MIN_LENGTH"],
                    current_app.config["PASSWORD_MAX_BYTES"],
                )
            ).hash(password)
        except PasswordPolicyError as error:
            raise click.ClickException(str(error)) from error
        now = datetime.now(UTC)
        if existing is None:
            existing = User(
                id=uuid.uuid4(),
                email=email,
                display_name=name,
                password_hash=encoded,
                status="active",
                platform_role="super_admin",
                email_verified_at=now,
                password_changed_at=now,
            )
            db.session.add(existing)
        else:
            existing.password_hash = encoded
            existing.display_name = name
            existing.status = "active"
            existing.platform_role = "super_admin"
            existing.password_changed_at = now
        append_global_audit_event(
            db.session,
            action="platform.bootstrap.superadmin",
            resource_type="user",
            resource_id=existing.id,
            actor_id=None,
            result="success",
            metadata={"operation": "rotate" if rotate_password else "create"},
        )
        db.session.commit()
        click.echo(
            f"Superadmin preparado: {existing.id}. Rota la contraseña tras el primer acceso."
        )

    @app.cli.command("seed-rbac")
    @click.option("--tenant-id", type=click.UUID, required=True)
    def seed_rbac(tenant_id: uuid.UUID) -> None:
        """Idempotently create the six system roles for one tenant."""

        with tenant_context(TenantContext(tenant_id=tenant_id, actor_id=None)):
            if db.session.get(Tenant, tenant_id) is None:
                raise click.ClickException("El tenant indicado no existe.")
            roles = seed_system_roles(db.session(), tenant_id)
            db.session.commit()
        click.echo(f"Roles actualizados: {', '.join(sorted(roles))}")

    @app.cli.command("create-dev-tenant")
    @click.option("--slug", required=True)
    @click.option("--name", required=True)
    @click.option("--email", required=True)
    @click.option("--display-name", required=True)
    def create_dev_tenant(slug: str, name: str, email: str, display_name: str) -> None:
        """Create local tenant and invited owner without a fixed password."""

        if current_app.config["APP_ENV"] == "production":
            raise click.ClickException("Este comando está deshabilitado en producción.")
        slug = slug.strip().lower()
        email = email.strip().lower()
        name = name.strip()
        display_name = display_name.strip()
        if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", slug):
            raise click.ClickException("El slug no tiene un formato válido.")
        if "@" not in email or not name or not display_name:
            raise click.ClickException("Nombre, display name y email deben ser válidos.")
        tenant_id = uuid.uuid4()
        user_id = uuid.uuid4()
        membership_id = uuid.uuid4()
        with tenant_context(TenantContext(tenant_id=tenant_id, actor_id=user_id)):
            if db.session.scalar(select(Tenant.id).where(Tenant.slug == slug)) is not None:
                raise click.ClickException("Ya existe un tenant con ese slug.")
            if db.session.scalar(select(User.id).where(User.email == email)) is not None:
                raise click.ClickException("Ya existe un usuario con ese email.")
            tenant = Tenant(id=tenant_id, slug=slug, name=name, status="active")
            user = User(
                id=user_id,
                email=email,
                display_name=display_name,
                password_hash=None,
                status="invited",
            )
            membership = TenantMembership(
                id=membership_id,
                tenant_id=tenant_id,
                user_id=user_id,
                status="invited",
                invited_at=datetime.now(UTC),
            )
            db.session.add_all([tenant, user])
            db.session.flush()
            db.session.add_all(
                [
                    membership,
                    Workspace(
                        tenant_id=tenant_id,
                        slug="principal",
                        name="Principal",
                        status="active",
                        is_default=True,
                    ),
                ]
            )
            db.session.flush()
            roles = seed_system_roles(db.session(), tenant_id)
            db.session.add(
                MembershipRole(
                    tenant_id=tenant_id,
                    membership_id=membership_id,
                    role_id=roles["owner"].id,
                )
            )
            db.session.commit()
        click.echo(f"Tenant de desarrollo creado: {tenant_id}")
        click.echo(f"Usuario invitado sin contraseña: {user_id}")
