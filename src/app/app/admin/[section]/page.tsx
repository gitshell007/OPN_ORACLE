import { notFound } from "next/navigation";
import { AuthBoundary } from "@/components/auth/auth-boundary";
import { TenantJobs, TenantOrganization, TenantRoles, TenantWorkspaces } from "@/components/admin/tenant-operations";

const sections = {
  organization: { title: "Organización", permission: "tenant.settings.manage", description: "Nombre, zona horaria, idioma y estado de la organización.", api: "GET/PATCH /api/v1/tenant" },
  roles: { title: "Roles y permisos", permission: "tenant.users.manage", description: "Matriz legible de roles y permisos de la organización.", api: "GET /api/v1/tenant/roles" },
  workspaces: { title: "Espacios de trabajo", permission: "tenant.settings.manage", description: "Espacios de trabajo y asignaciones autorizadas.", api: "Dominio de espacios de trabajo; cambios pendientes de contrato" },
  jobs: { title: "Trabajos en segundo plano", permission: "tenant.settings.manage", description: "Estado, cola, progreso, reintentos y errores saneados.", api: "GET /api/v1/jobs" },
} as const;

export default async function Page({ params }: { params: Promise<{ section: string }> }) {
  const { section } = await params;
  const config = sections[section as keyof typeof sections];
  if (!config) notFound();
  if (section === "roles") {
    return <AuthBoundary permission="tenant.users.manage"><TenantRoles /></AuthBoundary>;
  }
  if (section === "organization") {
    return <AuthBoundary permission="tenant.settings.manage"><TenantOrganization /></AuthBoundary>;
  }
  if (section === "workspaces") {
    return <AuthBoundary permission="tenant.settings.manage"><TenantWorkspaces /></AuthBoundary>;
  }
  if (section === "jobs") {
    return <AuthBoundary permission="tenant.settings.manage"><TenantJobs /></AuthBoundary>;
  }
  notFound();
}
