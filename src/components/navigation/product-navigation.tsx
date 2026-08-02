"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useAuth } from "@/components/auth/auth-provider";
import {
  ADMIN_ROUTES,
  canAccessRoute,
  dossierTabHref,
  DOSSIER_GROUPS,
  DOSSIER_SECTION_GROUP,
  DOSSIER_TABS,
} from "@/lib/app-routes";

export function DossierNavigation({ dossierId }: { dossierId: string }) {
  const pathname = usePathname();
  const auth = useAuth();
  const permissions = auth.identity?.permissions ?? [];
  const allowed = new Set(
    DOSSIER_TABS.filter((tab) => permissions.includes(tab.permission)).map(
      (tab) => tab.segment,
    ),
  );
  const current = DOSSIER_TABS.find(
    (tab) => pathname === dossierTabHref(dossierId, tab.segment),
  );
  const activeGroup = current ? DOSSIER_SECTION_GROUP[current.segment] : "summary";

  return (
    <nav className="dossier-nav" aria-label="Secciones del expediente">
      {DOSSIER_GROUPS.map((group) => {
        const sections = group.sections.filter((segment) => allowed.has(segment));
        if (sections.length === 0) return null;
        // Destino estático: el primer hijo permitido del grupo. Sin memoria de
        // última visita, para que el enlace sea determinista en hidratación.
        const href = dossierTabHref(dossierId, sections[0]);
        // Solo el destino de hoja lleva aria-current="page". Si el grupo tiene
        // subnavegación, el ítem de primer nivel usa data-active y el subnav
        // marca la página actual (evita el doble aria-current del antiguo
        // <details>Más</details> y del default del grupo).
        const isLeafGroup = sections.length < 2;
        return (
          <Link
            key={group.id}
            href={href}
            className="dossier-nav__item"
            data-testid={`dossier-nav-${group.id}`}
            data-active={activeGroup === group.id ? "true" : undefined}
            aria-current={
              isLeafGroup && pathname === href ? "page" : undefined
            }
          >
            {group.label}
          </Link>
        );
      })}
    </nav>
  );
}

export function DossierSubnav({ dossierId }: { dossierId: string }) {
  const pathname = usePathname();
  const auth = useAuth();
  const permissions = auth.identity?.permissions ?? [];
  const current = DOSSIER_TABS.find(
    (tab) => pathname === dossierTabHref(dossierId, tab.segment),
  );
  const groupId = current ? DOSSIER_SECTION_GROUP[current.segment] : "summary";
  const group = DOSSIER_GROUPS.find((item) => item.id === groupId);
  // Resumen y Actividad no tienen hermanos: no se pinta un nivel 2 de un ítem.
  if (!group || group.sections.length < 2) return null;

  const tabs = group.sections
    .map((segment) => DOSSIER_TABS.find((tab) => tab.segment === segment))
    .filter(
      (tab): tab is (typeof DOSSIER_TABS)[number] =>
        Boolean(tab) && permissions.includes(tab!.permission),
    );
  if (tabs.length < 2) return null;

  return (
    <nav className="dossier-subnav" aria-label={`Subsecciones de ${group.label}`}>
      {tabs.map((tab) => {
        const href = dossierTabHref(dossierId, tab.segment);
        return (
          <Link
            key={tab.id}
            href={href}
            data-testid={`dossier-subnav-${tab.id}`}
            aria-current={pathname === href ? "page" : undefined}
          >
            {tab.label}
          </Link>
        );
      })}
    </nav>
  );
}

export function AdminNavigation() {
  const pathname = usePathname();
  const auth = useAuth();
  const permissions = auth.identity?.permissions ?? [];
  const routes = ADMIN_ROUTES.filter((route) =>
    canAccessRoute(route, permissions),
  );
  const activeRoute = [...routes]
    .sort((a, b) => b.href.length - a.href.length)
    .find(
      (route) =>
        pathname === route.href || pathname.startsWith(`${route.href}/`),
    );
  return (
    <nav className="account-tabs admin-tabs" aria-label="Administración de la organización">
      {routes.map((route) => (
        <Link
          key={route.id}
          href={route.href}
          aria-current={activeRoute?.id === route.id ? "page" : undefined}
        >
          {route.label}
        </Link>
      ))}
    </nav>
  );
}
