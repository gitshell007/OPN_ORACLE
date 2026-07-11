"""Idempotent platform permission and per-tenant system-role seeds."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import delete, select

from opn_oracle.platform.models import Permission, Role, RolePermission
from opn_oracle.tenants.context import require_tenant_id

PERMISSIONS: dict[str, str] = {
    "dossier.read": "Consultar expedientes y sus recursos.",
    "dossier.write": "Crear y modificar expedientes.",
    "dossier.delete": "Archivar o eliminar expedientes según política.",
    "dossier.archive": "Archivar expedientes sin borrado físico.",
    "signal.read": "Consultar señales vinculadas al tenant.",
    "signal.review": "Revisar y clasificar señales.",
    "signal.promote": "Promover señales revisadas a oportunidad o riesgo.",
    "opportunity.read": "Consultar oportunidades.",
    "opportunity.write": "Crear y modificar oportunidades.",
    "risk.read": "Consultar riesgos.",
    "risk.write": "Crear y modificar riesgos.",
    "actor.read": "Consultar actores y relaciones.",
    "actor.write": "Gestionar actores y relaciones.",
    "meeting.read": "Consultar reuniones y briefings.",
    "meeting.write": "Gestionar reuniones y briefings.",
    "report.read": "Consultar informes.",
    "report.generate": "Solicitar informes y briefings.",
    "report.review": "Revisar y comentar informes.",
    "report.publish": "Publicar y sustituir informes.",
    "task.read": "Consultar tareas y decisiones.",
    "task.write": "Gestionar tareas y decisiones.",
    "tenant.users.manage": "Gestionar usuarios, memberships y roles.",
    "tenant.settings.manage": "Gestionar configuración del tenant.",
    "tenant.integrations.manage": "Gestionar integraciones y credenciales.",
    "audit.read": "Consultar la auditoría autorizada.",
    "ai.execute": "Ejecutar análisis IA sobre expedientes autorizados.",
    "ai.review": "Revisar y validar resultados IA.",
    "documents.read": "Consultar documentos, búsqueda y evidencias.",
    "documents.manage": "Subir, reprocesar y retirar documentos.",
    "notifications.read": "Consultar notificaciones propias.",
    "notifications.manage": "Gestionar preferencias de notificación propias.",
    "export.create": "Solicitar exportaciones de datos autorizados.",
    "audit.export": "Exportar auditoría con marca de agua.",
}

ROLE_PERMISSIONS: dict[str, frozenset[str]] = {
    "owner": frozenset(PERMISSIONS),
    "admin": frozenset(PERMISSIONS),
    "editor": frozenset(
        {
            "dossier.read",
            "dossier.write",
            "dossier.archive",
            "signal.read",
            "signal.review",
            "signal.promote",
            "opportunity.read",
            "opportunity.write",
            "risk.read",
            "risk.write",
            "actor.read",
            "actor.write",
            "meeting.read",
            "meeting.write",
            "report.read",
            "report.generate",
            "report.review",
            "task.read",
            "task.write",
            "ai.execute",
            "ai.review",
            "documents.read",
            "documents.manage",
            "notifications.read",
            "notifications.manage",
            "export.create",
        }
    ),
    "analyst": frozenset(
        {
            "dossier.read",
            "signal.read",
            "signal.review",
            "signal.promote",
            "opportunity.read",
            "opportunity.write",
            "risk.read",
            "risk.write",
            "actor.read",
            "meeting.read",
            "report.read",
            "report.generate",
            "report.review",
            "task.read",
            "task.write",
            "ai.execute",
            "ai.review",
            "documents.read",
            "documents.manage",
            "notifications.read",
            "notifications.manage",
            "export.create",
        }
    ),
    "viewer": frozenset(
        {
            "dossier.read",
            "signal.read",
            "opportunity.read",
            "risk.read",
            "actor.read",
            "meeting.read",
            "report.read",
            "task.read",
            "documents.read",
            "notifications.read",
            "notifications.manage",
            "export.create",
        }
    ),
    "auditor": frozenset(
        {
            "dossier.read",
            "documents.read",
            "audit.read",
            "audit.export",
            "export.create",
            "notifications.read",
            "notifications.manage",
        }
    ),
}

ROLE_DEFINITIONS: dict[str, tuple[str, str]] = {
    "owner": ("Propietario", "Control completo del tenant y sus permisos."),
    "admin": ("Administrador", "Administra usuarios, configuración y recursos."),
    "editor": ("Editor", "Crea y modifica expedientes y señales."),
    "analyst": ("Analista", "Analiza señales y genera informes."),
    "viewer": ("Lector", "Consulta expedientes sin modificarlos."),
    "auditor": ("Auditor", "Consulta evidencias y auditoría autorizada."),
}


def seed_permission_catalog(session: Any) -> None:
    existing = set(session.scalars(select(Permission.key)))
    for key, description in PERMISSIONS.items():
        if key not in existing:
            session.add(Permission(key=key, description=description))


def seed_system_roles(session: Any, tenant_id: UUID) -> dict[str, Role]:
    if require_tenant_id() != tenant_id:
        raise ValueError("El seed solo puede operar sobre el tenant activo.")
    seed_permission_catalog(session)
    session.flush()
    roles = {
        role.key: role for role in session.scalars(select(Role).where(Role.tenant_id == tenant_id))
    }
    for key, (name, description) in ROLE_DEFINITIONS.items():
        if key not in roles:
            role = Role(
                tenant_id=tenant_id,
                key=key,
                name=name,
                description=description,
                is_system=True,
            )
            session.add(role)
            roles[key] = role
        else:
            roles[key].name = name
            roles[key].description = description
            roles[key].is_system = True
    session.flush()
    for key, permissions in ROLE_PERMISSIONS.items():
        role = roles[key]
        session.execute(delete(RolePermission).where(RolePermission.role_id == role.id))
        session.add_all(
            RolePermission(tenant_id=tenant_id, role_id=role.id, permission_key=permission)
            for permission in sorted(permissions)
        )
    session.flush()
    return roles
