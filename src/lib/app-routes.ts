import type { LucideIcon } from "lucide-react";
import {
  Activity,
  Bell,
  BriefcaseBusiness,
  Building2,
  DatabaseBackup,
  CalendarDays,
  CircleGauge,
  FileChartColumn,
  FileSearch,
  History,
  House,
  KeyRound,
  ListChecks,
  ListTodo,
  MonitorSmartphone,
  Network,
  Newspaper,
  PlugZap,
  BarChart3,
  RadioTower,
  SearchCheck,
  Settings,
  ShieldAlert,
  ShieldCheck,
  SlidersHorizontal,
  Sparkles,
  ScrollText,
  UserRound,
  Users,
  Workflow,
} from "lucide-react";

export const PERMISSIONS = [
  "dossier.read",
  "dossier.write",
  "dossier.delete",
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
  "report.publish",
  "task.read",
  "task.write",
  "tenant.users.manage",
  "tenant.settings.manage",
  "tenant.integrations.manage",
  "audit.read",
  "documents.read",
  "documents.manage",
  "notifications.read",
  "notifications.manage",
  "export.create",
  "audit.export",
  "ai.execute",
  "ai.review",
] as const;

export type Permission = (typeof PERMISSIONS)[number];
export type RouteGroup =
  | "work"
  | "intelligence"
  | "execution"
  | "admin"
  | "account"
  | "platform";

export interface AppRouteDefinition {
  id: string;
  label: string;
  href: string;
  group: RouteGroup;
  icon: LucideIcon;
  permission?: Permission;
  anyPermissions?: readonly Permission[];
  nav?: boolean;
  platformOnly?: boolean;
  badgeSource?: "signals_unread" | "changes_unread" | "notifications_unread";
}

export const GLOBAL_ROUTES = [
  {
    id: "home",
    label: "Inicio",
    href: "/app",
    group: "work",
    icon: House,
    permission: "dossier.read",
    nav: true,
  },
  {
    id: "dossiers",
    label: "Expedientes",
    href: "/app/dossiers",
    group: "work",
    icon: BriefcaseBusiness,
    permission: "dossier.read",
    nav: true,
  },
  {
    id: "changes",
    label: "Qué ha cambiado",
    href: "/app/changes",
    group: "work",
    icon: History,
    permission: "dossier.read",
    nav: true,
    badgeSource: "changes_unread",
  },
  {
    id: "signals",
    label: "Señales",
    href: "/app/signals",
    group: "intelligence",
    icon: RadioTower,
    permission: "signal.read",
    nav: true,
    badgeSource: "signals_unread",
  },
  {
    id: "opportunities",
    label: "Oportunidades",
    href: "/app/opportunities",
    group: "intelligence",
    icon: Sparkles,
    permission: "opportunity.read",
    nav: true,
  },
  {
    id: "procurement",
    label: "Licitaciones",
    href: "/app/procurement",
    group: "intelligence",
    icon: FileSearch,
    permission: "opportunity.read",
    nav: true,
  },
  {
    id: "procurement-stats",
    label: "Estadísticas mercado",
    href: "/app/procurement/stats",
    group: "intelligence",
    icon: BarChart3,
    permission: "opportunity.read",
    nav: true,
  },
  {
    id: "risks",
    label: "Riesgos",
    href: "/app/risks",
    group: "intelligence",
    icon: ShieldAlert,
    permission: "risk.read",
    nav: true,
  },
  {
    id: "actors",
    label: "Actores",
    href: "/app/actors",
    group: "intelligence",
    icon: Network,
    permission: "actor.read",
    nav: true,
  },
  {
    id: "meetings",
    label: "Reuniones",
    href: "/app/meetings",
    group: "execution",
    icon: CalendarDays,
    permission: "meeting.read",
    nav: true,
  },
  {
    id: "tasks",
    label: "Tareas",
    href: "/app/tasks",
    group: "execution",
    icon: ListTodo,
    permission: "task.read",
    nav: true,
  },
  {
    id: "reports",
    label: "Informes",
    href: "/app/reports",
    group: "execution",
    icon: FileChartColumn,
    permission: "report.read",
    nav: true,
  },
  {
    id: "admin",
    label: "Administración",
    href: "/app/admin",
    group: "admin",
    icon: Settings,
    anyPermissions: [
      "tenant.users.manage",
      "tenant.settings.manage",
      "tenant.integrations.manage",
      "audit.read",
    ],
    nav: true,
  },
] as const satisfies readonly AppRouteDefinition[];

export const ACCOUNT_ROUTES = [
  { id: "account", label: "Mi cuenta", href: "/app/account", group: "account", icon: UserRound },
  { id: "account-profile", label: "Perfil", href: "/app/account/profile", group: "account", icon: UserRound },
  { id: "account-security", label: "Seguridad", href: "/app/account/security", group: "account", icon: KeyRound },
  { id: "account-sessions", label: "Sesiones activas", href: "/app/account/sessions", group: "account", icon: MonitorSmartphone },
  { id: "account-preferences", label: "Preferencias", href: "/app/account/preferences", group: "account", icon: SlidersHorizontal },
  { id: "account-notifications", label: "Notificaciones", href: "/app/account/notifications", group: "account", icon: Bell, permission: "notifications.manage" },
] as const satisfies readonly AppRouteDefinition[];

export const AUXILIARY_ROUTES = [
  { id: "notifications", label: "Notificaciones", href: "/app/notifications", group: "account", icon: Bell, permission: "notifications.read" },
  { id: "exports", label: "Exportaciones", href: "/app/exports", group: "execution", icon: FileSearch, permission: "export.create" },
] as const satisfies readonly AppRouteDefinition[];

export const ADMIN_ROUTES = [
  { id: "admin-organization", label: "Organización", href: "/app/admin/organization", group: "admin", icon: Building2, permission: "tenant.settings.manage" },
  { id: "admin-members", label: "Miembros", href: "/app/admin/members", group: "admin", icon: Users, permission: "tenant.users.manage" },
  { id: "admin-roles", label: "Roles y permisos", href: "/app/admin/roles", group: "admin", icon: ShieldCheck, permission: "tenant.users.manage" },
  { id: "admin-workspaces", label: "Espacios de trabajo", href: "/app/admin/workspaces", group: "admin", icon: Workflow, permission: "tenant.settings.manage" },
  { id: "admin-ai", label: "Inteligencia artificial", href: "/app/admin/ai", group: "admin", icon: Sparkles, permission: "tenant.settings.manage" },
  { id: "admin-integrations", label: "Integraciones", href: "/app/admin/integrations", group: "admin", icon: PlugZap, permission: "tenant.integrations.manage" },
  { id: "admin-signal", label: "Signal Avanza", href: "/app/admin/integrations/signal-avanza", group: "admin", icon: RadioTower, permission: "tenant.integrations.manage" },
  { id: "admin-audit", label: "Auditoría", href: "/app/admin/audit", group: "admin", icon: SearchCheck, permission: "audit.read" },
  { id: "admin-ai-audit", label: "Auditoría de IA", href: "/app/admin/ai-audit", group: "admin", icon: ScrollText, permission: "audit.read" },
] as const satisfies readonly AppRouteDefinition[];

export const PLATFORM_ROUTES = [
  { id: "platform", label: "Estado general", href: "/platform", group: "platform", icon: CircleGauge, platformOnly: true, nav: true },
  { id: "platform-tenants", label: "Organizaciones", href: "/platform/tenants", group: "platform", icon: Building2, platformOnly: true, nav: true },
  { id: "platform-users", label: "Usuarios", href: "/platform/users", group: "platform", icon: Users, platformOnly: true, nav: true },
  { id: "platform-jobs", label: "Trabajos y colas", href: "/platform/jobs", group: "platform", icon: ListChecks, platformOnly: true, nav: true },
  { id: "platform-integrations", label: "Integraciones", href: "/platform/integrations", group: "platform", icon: PlugZap, platformOnly: true, nav: true },
  { id: "platform-audit", label: "Auditoría global", href: "/platform/audit", group: "platform", icon: FileSearch, platformOnly: true, nav: true },
  { id: "platform-source-activity", label: "Fuentes oficiales", href: "/platform/source-activity", group: "platform", icon: Newspaper, platformOnly: true, nav: true },
  { id: "platform-procurement-stats", label: "Estadísticas licitaciones", href: "/platform/procurement-stats", group: "platform", icon: BarChart3, platformOnly: true, nav: true },
  { id: "platform-system", label: "Salud técnica", href: "/platform/system", group: "platform", icon: Activity, platformOnly: true, nav: true },
  { id: "platform-backups", label: "Copias de seguridad", href: "/platform/backups", group: "platform", icon: DatabaseBackup, platformOnly: true, nav: true },
] as const satisfies readonly AppRouteDefinition[];

export const DOSSIER_TABS = [
  { id: "summary", label: "Resumen", segment: "", permission: "dossier.read" },
  { id: "activity", label: "Actividad", segment: "activity", permission: "dossier.read" },
  { id: "ask", label: "Preguntar", segment: "ask", permission: "ai.execute" },
  { id: "signals", label: "Señales", segment: "signals", permission: "signal.read" },
  { id: "opportunities", label: "Oportunidades", segment: "opportunities", permission: "opportunity.read" },
  { id: "procurement", label: "Licitaciones", segment: "procurement", permission: "opportunity.read" },
  { id: "risks", label: "Riesgos", segment: "risks", permission: "risk.read" },
  { id: "actors", label: "Actores", segment: "actors", permission: "actor.read" },
  { id: "investigations", label: "Investigación", segment: "investigations", permission: "dossier.read" },
  { id: "meetings", label: "Reuniones", segment: "meetings", permission: "meeting.read" },
  { id: "tasks", label: "Tareas", segment: "tasks", permission: "task.read" },
  { id: "documents", label: "Documentos", segment: "documents", permission: "documents.read" },
  { id: "reports", label: "Informes", segment: "reports", permission: "report.read" },
  { id: "custom-brief", label: "Informe libre", segment: "custom-brief", permission: "report.generate" },
  { id: "decisions", label: "Decisiones", segment: "decisions", permission: "task.read" },
  { id: "settings", label: "Configuración", segment: "settings", permission: "dossier.read" },
] as const;

export type DossierSection = (typeof DOSSIER_TABS)[number]["segment"];

/**
 * Agrupación de las secciones del expediente en seis destinos de primer nivel.
 * Dieciséis pestañas planas no son una arquitectura: son una lista. Ninguna URL
 * cambia; sólo cambia cómo se presentan. El primer elemento de `sections` es el
 * destino por defecto del grupo (estático: sin memoria de última visita, para
 * que el destino sea determinista en hidratación y en los e2e).
 */
export const DOSSIER_GROUPS = [
  { id: "summary", label: "Resumen", sections: [""] },
  {
    id: "surveillance",
    label: "Vigilancia",
    sections: ["signals", "opportunities", "procurement", "risks"],
  },
  { id: "analysis", label: "Análisis", sections: ["actors", "investigations", "ask"] },
  { id: "decision", label: "Decisión", sections: ["decisions", "meetings", "tasks"] },
  {
    id: "deliverables",
    label: "Entregables",
    sections: ["reports", "custom-brief", "documents"],
  },
  { id: "activity", label: "Actividad", sections: ["activity"] },
] as const satisfies readonly {
  id: string;
  label: string;
  sections: readonly DossierSection[];
}[];

export type DossierGroupId = (typeof DOSSIER_GROUPS)[number]["id"] | "settings";

/** Reverso exhaustivo: un segmento nuevo sin entrada aquí no compila. */
export const DOSSIER_SECTION_GROUP = {
  "": "summary",
  signals: "surveillance",
  opportunities: "surveillance",
  procurement: "surveillance",
  risks: "surveillance",
  actors: "analysis",
  investigations: "analysis",
  ask: "analysis",
  decisions: "decision",
  meetings: "decision",
  tasks: "decision",
  reports: "deliverables",
  "custom-brief": "deliverables",
  documents: "deliverables",
  activity: "activity",
  settings: "settings",
} satisfies Record<DossierSection, DossierGroupId>;

export const GROUP_LABELS: Record<Exclude<RouteGroup, "account" | "platform">, string> = {
  work: "Trabajo estratégico",
  intelligence: "Inteligencia",
  execution: "Ejecución",
  admin: "Administración",
};

export function canAccessRoute(
  route: AppRouteDefinition,
  permissions: readonly string[],
  platformSuperadmin = false,
): boolean {
  if (route.platformOnly) return platformSuperadmin;
  if (route.permission && !permissions.includes(route.permission)) return false;
  if (route.anyPermissions && !route.anyPermissions.some((item) => permissions.includes(item))) {
    return false;
  }
  return true;
}

export function visibleGlobalRoutes(permissions: readonly string[]): AppRouteDefinition[] {
  return GLOBAL_ROUTES.filter(
    (route) => route.nav && canAccessRoute(route, permissions),
  );
}

export function dossierTabHref(dossierId: string, segment: DossierSection): string {
  const root = `/app/dossiers/${encodeURIComponent(dossierId)}`;
  return segment ? `${root}/${segment}` : root;
}

export interface BreadcrumbItem {
  label: string;
  href?: string;
}

const ALL_ROUTES: readonly AppRouteDefinition[] = [
  ...GLOBAL_ROUTES,
  ...AUXILIARY_ROUTES,
  ...ACCOUNT_ROUTES,
  ...ADMIN_ROUTES,
  ...PLATFORM_ROUTES,
];

export function breadcrumbsForPath(pathname: string): BreadcrumbItem[] {
  const entityMatch = pathname.match(/^\/app\/actors\/entity\/([^/]+)\/(.+)$/);
  if (entityMatch) {
    const [, , encodedName] = entityMatch;
    return [
      { label: "Actores", href: "/app/actors" },
      { label: decodeURIComponent(encodedName) },
    ];
  }
  const dossierMatch = pathname.match(/^\/app\/dossiers\/([^/]+)(?:\/([^/]+))?$/);
  if (dossierMatch) {
    const [, dossierId, section = ""] = dossierMatch;
    const tab = DOSSIER_TABS.find((item) => item.segment === section);
    return [
      { label: "Expedientes", href: "/app/dossiers" },
      { label: "Expediente", href: dossierTabHref(dossierId, "") },
      ...(tab && tab.segment ? [{ label: tab.label }] : []),
    ];
  }
  const route = [...ALL_ROUTES]
    .sort((a, b) => b.href.length - a.href.length)
    .find((item) => pathname === item.href || pathname.startsWith(`${item.href}/`));
  if (!route) return [{ label: "Oracle" }];
  if (route.group === "admin" && route.href !== "/app/admin") {
    return [{ label: "Administración", href: "/app/admin" }, { label: route.label }];
  }
  if (route.group === "account" && route.href !== "/app/account") {
    return [{ label: "Mi cuenta", href: "/app/account" }, { label: route.label }];
  }
  if (route.group === "platform" && route.href !== "/platform") {
    return [{ label: "Plataforma", href: "/platform" }, { label: route.label }];
  }
  return [{ label: route.label }];
}
