"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useAuth } from "@/components/auth/auth-provider";
import {
  ADMIN_ROUTES,
  canAccessRoute,
  dossierTabHref,
  DOSSIER_TABS,
} from "@/lib/app-routes";

export function DossierNavigation({ dossierId }: { dossierId: string }) {
  const pathname = usePathname();
  const auth = useAuth();
  const permissions = auth.identity?.permissions ?? [];
  const tabs = DOSSIER_TABS.filter((tab) => permissions.includes(tab.permission));
  const activeSecondary = tabs
    .slice(3)
    .find((tab) => pathname === dossierTabHref(dossierId, tab.segment));
  return (
    <nav className="account-tabs dossier-tabs" aria-label="Secciones del expediente">
      {tabs.map((tab, index) => {
        const href = dossierTabHref(dossierId, tab.segment);
        return (
          <Link
            key={tab.id}
            className={index >= 3 ? "dossier-tab-secondary" : undefined}
            href={href}
            aria-current={pathname === href ? "page" : undefined}
          >
            {tab.label}
          </Link>
        );
      })}
      {tabs.length > 3 && (
        <details className="dossier-more">
          <summary>{activeSecondary ? `Más · ${activeSecondary.label}` : "Más"}</summary>
          <div className="dossier-more-menu">
            {tabs.slice(3).map((tab) => {
              const href = dossierTabHref(dossierId, tab.segment);
              return (
                <Link
                  key={tab.id}
                  href={href}
                  aria-current={pathname === href ? "page" : undefined}
                >
                  {tab.label}
                </Link>
              );
            })}
          </div>
        </details>
      )}
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
