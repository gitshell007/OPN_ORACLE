"use client";

import * as DropdownMenu from "@radix-ui/react-dropdown-menu";
import {
  BookOpenCheck,
  ChevronDown,
  Building2,
  LogOut,
  Menu,
  Plus,
  UserRound,
  X,
} from "lucide-react";
import { api } from "@oracle/api-client";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useMemo, useRef, useState } from "react";
import { toast } from "sonner";
import {
  CommandPalette,
  ProductCommandPalette,
} from "@/components/shared/command-palette";
import { CreateDossierDialog } from "@/components/shared/create-dossier-dialog";
import { CreateProductDossierDialog } from "@/components/navigation/create-product-dossier-dialog";
import { PermissionGate } from "@/components/auth/auth-boundary";
import { useAuth } from "@/components/auth/auth-provider";
import { NotificationBell } from "@/components/reporting/notifications";
import {
  breadcrumbsForPath,
  GLOBAL_ROUTES,
  GROUP_LABELS,
  visibleGlobalRoutes,
  type AppRouteDefinition,
} from "@/lib/app-routes";
import { productRoleLabel } from "@/lib/product-copy";

export function VectorShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const auth = useAuth();
  const productBase: "/app" | "/concept-a" = pathname.startsWith("/app")
    ? "/app"
    : "/concept-a";
  const canonical = productBase === "/app";
  const nav = useMemo<AppRouteDefinition[]>(
    () =>
      canonical
        ? visibleGlobalRoutes(auth.identity?.permissions ?? [])
        : GLOBAL_ROUTES.filter((route) => route.group !== "admin").map(
            (route) => ({
              ...route,
              href:
                route.id === "home"
                  ? "/concept-a/portfolio"
                  : route.id === "reports"
                    ? "/concept-a/reports"
                    : `/concept-a/portfolio#${route.id}`,
            }),
          ),
    [auth.identity?.permissions, canonical],
  );
  const [compact, setCompact] = useState(false);
  const [mobileOpen, setMobileOpen] = useState(false);
  const [createOpen, setCreateOpen] = useState(false);
  const [dossierBreadcrumb, setDossierBreadcrumb] = useState<{
    id: string;
    title: string;
  } | null>(null);
  const mobileTriggerRef = useRef<HTMLButtonElement>(null);
  const mobileCloseRef = useRef<HTMLButtonElement>(null);
  const crumbs = useMemo(() => breadcrumbsForPath(pathname), [pathname]);
  const dossierId = useMemo(() => {
    const match = canonical
      ? pathname.match(/^\/app\/dossiers\/([^/]+)(?:\/[^/]+)?$/)
      : null;
    return match ? decodeURIComponent(match[1]) : null;
  }, [canonical, pathname]);
  const visibleCrumbs = useMemo(
    () =>
      dossierBreadcrumb?.id === dossierId
        ? crumbs.map((crumb) =>
            crumb.label === "Expediente"
              ? { ...crumb, label: dossierBreadcrumb.title }
              : crumb,
          )
        : crumbs,
    [crumbs, dossierBreadcrumb, dossierId],
  );
  const user = auth.identity!.user;
  const activeMembership = auth.identity!.memberships.find(
    (item) => item.tenant_id === auth.identity!.active_tenant_id,
  );
  const initials = user.display_name
    .split(/\s+/)
    .slice(0, 2)
    .map((part) => part[0])
    .join("")
    .toUpperCase();

  useEffect(() => {
    if (!canonical) return;
    const loadPreference = () =>
      setCompact(
        window.localStorage.getItem(`oracle:nav:compact:${user.id}`) === "true",
      );
    const kickoff = window.setTimeout(loadPreference, 0);
    window.addEventListener("oracle:navigation-preference", loadPreference);
    return () => {
      window.clearTimeout(kickoff);
      window.removeEventListener("oracle:navigation-preference", loadPreference);
    };
  }, [canonical, user.id]);

  useEffect(() => {
    let current = true;
    if (!dossierId) return () => {
      current = false;
    };
    void api.dossiers
      .get(dossierId)
      .then((dossier) => {
        if (current) setDossierBreadcrumb({ id: dossierId, title: dossier.title });
      })
      .catch(() => {
        // Keep the neutral label when the dossier no longer exists or is not accessible.
      });
    return () => {
      current = false;
    };
  }, [dossierId]);

  useEffect(
    () => () => {
      document.body.style.overflow = "";
    },
    [],
  );

  const toggleCompact = () => {
    setCompact((current) => {
      const next = !current;
      if (canonical) {
        window.localStorage.setItem(`oracle:nav:compact:${user.id}`, String(next));
      }
      return next;
    });
  };

  const openMobileNav = () => {
    setMobileOpen(true);
    document.body.style.overflow = "hidden";
    window.setTimeout(() => mobileCloseRef.current?.focus(), 0);
  };

  const closeMobileNav = () => {
    setMobileOpen(false);
    document.body.style.overflow = "";
    window.setTimeout(() => mobileTriggerRef.current?.focus(), 0);
  };

  const navigateFromMobile = () => {
    if (!mobileOpen) return;
    setMobileOpen(false);
    document.body.style.overflow = "";
    window.setTimeout(() => document.getElementById("main-content")?.focus(), 0);
  };

  const navGroups = (["work", "intelligence", "execution", "admin"] as const)
    .map((group) => ({ group, routes: nav.filter((route) => route.group === group) }))
    .filter((item) => item.routes.length > 0);

  return (
    <div className={`vector-app ${compact ? "is-compact" : ""}`}>
      <a className="skip-link" href="#main-content">
        Saltar al contenido principal
      </a>
      <aside
        className={`vector-sidebar ${mobileOpen ? "is-open" : ""}`}
        id="primary-navigation"
        onKeyDown={(event) => {
          if (event.key === "Escape" && mobileOpen) {
            event.preventDefault();
            closeMobileNav();
          }
          if (event.key === "Tab" && mobileOpen) {
            const focusable = Array.from(
              event.currentTarget.querySelectorAll<HTMLElement>(
                'a[href], button:not([disabled]), [tabindex]:not([tabindex="-1"])',
              ),
            ).filter((element) => element.offsetParent !== null);
            const first = focusable[0];
            const last = focusable.at(-1);
            if (event.shiftKey && document.activeElement === first) {
              event.preventDefault();
              last?.focus();
            } else if (!event.shiftKey && document.activeElement === last) {
              event.preventDefault();
              first?.focus();
            }
          }
        }}
      >
        <div className="vector-brand">
          <Link
            href={canonical ? "/app" : "/concept-a/portfolio"}
            className="oracle-logo"
            aria-label="OPN Oracle, ir al centro de operaciones"
          >
            <span className="oracle-mark" aria-hidden="true">
              O
            </span>
            <span>
              OPN Oracle{!canonical && <small>Vector</small>}
            </span>
          </Link>
          <button
            ref={mobileCloseRef}
            className="icon-button sidebar-close"
            onClick={closeMobileNav}
            aria-label="Cerrar navegación"
          >
            <X size={19} />
          </button>
        </div>
        <DropdownMenu.Root>
          <DropdownMenu.Trigger
            className="workspace-chip"
            disabled={auth.identity!.memberships.length < 2}
          >
            <span className="workspace-avatar">
              {(activeMembership?.tenant_name ?? "OP")
                .slice(0, 2)
                .toUpperCase()}
            </span>
            <span>
              <strong>
                {activeMembership?.tenant_name ?? "Plataforma Oracle"}
              </strong>
              <small>
                {auth.identity!.memberships.length > 1
                  ? "Cambiar organización"
                  : "Organización activa"}
              </small>
            </span>
            {auth.identity!.memberships.length > 1 && <ChevronDown size={14} />}
          </DropdownMenu.Trigger>
          {auth.identity!.memberships.length > 1 && (
            <DropdownMenu.Portal>
              <DropdownMenu.Content
                className="vector-menu"
                side="right"
                align="start"
                sideOffset={8}
              >
                {auth.identity!.memberships.map((membership) => (
                  <DropdownMenu.Item
                    key={membership.tenant_id}
                    onSelect={() =>
                      void auth
                        .switchTenant(membership.tenant_id)
                        .then(() => {
                          toast.success("Organización actualizada");
                          router.replace(
                            canonical ? "/app" : "/concept-a/portfolio",
                          );
                        })
                        .catch(() =>
                          toast.error("No se pudo cambiar de organización"),
                        )
                    }
                  >
                    <Building2 size={16} />
                    {membership.tenant_name}
                  </DropdownMenu.Item>
                ))}
              </DropdownMenu.Content>
            </DropdownMenu.Portal>
          )}
        </DropdownMenu.Root>
        <nav className="vector-nav" aria-label="Navegación principal">
          {navGroups.map(({ group, routes }) => (
            <div key={group} className="vector-nav-group">
              <p className="nav-label">{GROUP_LABELS[group]}</p>
              {routes.map(({ id, label, href, icon: Icon, badgeSource }) => {
                const active =
                  pathname === href ||
                  (href !== "/app" && pathname.startsWith(`${href}/`));
                return (
                  <Link
                    key={id}
                    href={href}
                    title={compact ? label : undefined}
                    aria-label={label}
                    aria-current={active ? "page" : undefined}
                    className={active ? "active" : ""}
                    onClick={navigateFromMobile}
                  >
                    <Icon size={18} />
                    <span>{label}</span>
                    {!canonical && badgeSource === "signals_unread" && <b>7</b>}
                  </Link>
                );
              })}
            </div>
          ))}
        </nav>
        <button
          className="sidebar-collapse"
          onClick={toggleCompact}
        >
          <Menu size={17} />
          <span>{compact ? "Ampliar navegación" : "Contraer navegación"}</span>
        </button>
        <DropdownMenu.Root>
          <DropdownMenu.Trigger className="vector-user">
            <span className="user-avatar">{initials}</span>
            <span>
              <strong>{user.display_name}</strong>
              <small>
                {auth.identity!.roles[0] ? productRoleLabel(auth.identity!.roles[0]) :
                  (user.platform_role === "super_admin"
                    ? "Superadministración"
                    : "Miembro")}
              </small>
            </span>
            <ChevronDown size={15} />
          </DropdownMenu.Trigger>
          <DropdownMenu.Portal>
            <DropdownMenu.Content
              className="vector-menu"
              side="right"
              align="end"
              sideOffset={10}
            >
              <DropdownMenu.Label>
                {user.display_name}
                <small>{user.email}</small>
                <small>
                  {activeMembership?.tenant_name ?? "Contexto de plataforma"} ·{" "}
                  {auth.identity!.roles.map(productRoleLabel).join(", ") || "Sin rol asignado"}
                </small>
              </DropdownMenu.Label>
              <DropdownMenu.Item
                onSelect={() =>
                  router.push(canonical ? "/app/account" : "/concept-a/settings")
                }
              >
                <UserRound size={16} /> Mi cuenta
              </DropdownMenu.Item>
              {canonical && (
                <DropdownMenu.Item
                  onSelect={() => router.push("/app/account/security")}
                >
                  <BookOpenCheck size={16} /> Seguridad y sesiones
                </DropdownMenu.Item>
              )}
              {canonical && (
                <DropdownMenu.Item
                  onSelect={() => router.push("/app/account/preferences")}
                >
                  <UserRound size={16} /> Preferencias
                </DropdownMenu.Item>
              )}
              {canonical && (
                <DropdownMenu.Item
                  onSelect={() => router.push("/app/account/notifications")}
                >
                  <BookOpenCheck size={16} /> Notificaciones
                </DropdownMenu.Item>
              )}
              {user.platform_role === "super_admin" && (
                <DropdownMenu.Item
                  onSelect={() => router.push("/platform/tenants")}
                >
                  <Building2 size={16} /> Portal de plataforma
                </DropdownMenu.Item>
              )}
              <DropdownMenu.Item
                onSelect={() =>
                  toast.info("Atajos", {
                    description: "⌘K buscar · Esc cerrar · / enfocar filtros",
                  })
                }
              >
                <BookOpenCheck size={16} /> Atajos de teclado
              </DropdownMenu.Item>
              <DropdownMenu.Separator />
              <DropdownMenu.Item
                onSelect={() =>
                  void auth
                    .logout()
                    .then(() => router.replace("/login"))
                    .catch(() =>
                      toast.error("No se pudo cerrar la sesión", {
                        description:
                          "La sesión continúa activa. Inténtalo de nuevo.",
                      }),
                    )
                }
              >
                <LogOut size={16} /> Cerrar sesión
              </DropdownMenu.Item>
            </DropdownMenu.Content>
          </DropdownMenu.Portal>
        </DropdownMenu.Root>
      </aside>
      {mobileOpen && (
        <button
          className="mobile-scrim"
          onClick={closeMobileNav}
          aria-label="Cerrar navegación"
        />
      )}
      <div className="vector-main">
        <header className="vector-topbar">
          <button
            ref={mobileTriggerRef}
            className="icon-button mobile-menu"
            onClick={openMobileNav}
            aria-label="Abrir navegación"
            aria-controls="primary-navigation"
            aria-expanded={mobileOpen}
          >
            <Menu size={20} />
          </button>
          <nav className="breadcrumbs" aria-label="Migas de pan">
            <Link href={canonical ? "/app" : "/concept-a/portfolio"}>Oracle</Link>
            {visibleCrumbs.map((crumb) => (
              <span key={`${crumb.href ?? "current"}-${crumb.label}`} className="breadcrumb-part">
                <i>/</i>
                {crumb.href ? (
                  <Link href={crumb.href}>{crumb.label}</Link>
                ) : (
                  <strong aria-current="page">{crumb.label}</strong>
                )}
              </span>
            ))}
          </nav>
          {canonical ? (
            <ProductCommandPalette onCreate={() => setCreateOpen(true)} />
          ) : (
            <CommandPalette concept="a" onCreate={() => setCreateOpen(true)} />
          )}
          <div className="topbar-actions">
            {!canonical && <span className="synthetic-badge">● Datos sintéticos</span>}
            <PermissionGate permission="notifications.read">
              <NotificationBell routeBase={productBase} />
            </PermissionGate>
            {canonical ? (
              <PermissionGate permission="dossier.write">
                <DropdownMenu.Root>
                  <DropdownMenu.Trigger
                    className="vector-primary compact-action"
                    aria-label="Crear"
                  >
                    <Plus size={17} />
                    <span>Crear</span>
                    <ChevronDown size={14} />
                  </DropdownMenu.Trigger>
                  <DropdownMenu.Portal>
                    <DropdownMenu.Content
                      className="vector-menu"
                      align="end"
                      sideOffset={8}
                    >
                      <DropdownMenu.Item onSelect={() => setCreateOpen(true)}>
                        <Plus size={16} /> Nuevo expediente
                      </DropdownMenu.Item>
                    </DropdownMenu.Content>
                  </DropdownMenu.Portal>
                </DropdownMenu.Root>
              </PermissionGate>
            ) : (
              <button
                className="vector-primary compact-action"
                onClick={() => setCreateOpen(true)}
              >
                <Plus size={17} />
                <span>Crear expediente</span>
              </button>
            )}
          </div>
        </header>
        <main className="vector-content" id="main-content" tabIndex={-1}>
          {children}
        </main>
      </div>
      {canonical ? (
        <CreateProductDossierDialog
          open={createOpen}
          onOpenChange={setCreateOpen}
        />
      ) : (
        <CreateDossierDialog
          open={createOpen}
          onOpenChange={setCreateOpen}
          accent="a"
        />
      )}
    </div>
  );
}
