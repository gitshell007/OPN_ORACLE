import { describe, expect, it } from "vitest";
import {
  breadcrumbsForPath,
  canAccessRoute,
  dossierTabHref,
  GLOBAL_ROUTES,
  visibleGlobalRoutes,
} from "./app-routes";

describe("registro de rutas", () => {
  it("mantiene los destinos de trabajo productivos en orden estable", () => {
    // Primer bloque de GLOBAL_ROUTES: nav de producto (12) antes de admin.
    expect(GLOBAL_ROUTES.slice(0, 12).map((route) => route.id)).toEqual([
      "home",
      "dossiers",
      "changes",
      "signals",
      "opportunities",
      "procurement",
      "procurement-stats",
      "risks",
      "actors",
      "meetings",
      "tasks",
      "reports",
    ]);
    expect(GLOBAL_ROUTES.slice(0, 3).map((route) => route.href)).toEqual([
      "/app",
      "/app/dossiers",
      "/app/changes",
    ]);
    expect(GLOBAL_ROUTES.map((route) => route.id)).toContain("procurement");
    expect(GLOBAL_ROUTES.map((route) => route.id)).toContain("procurement-stats");
  });

  it("deriva navegación por permiso sin conceder administración", () => {
    const routes = visibleGlobalRoutes(["dossier.read", "signal.read"]);
    expect(routes.map((route) => route.id)).toEqual([
      "home",
      "dossiers",
      "changes",
      "signals",
    ]);
    expect(routes.some((route) => route.id === "admin")).toBe(false);
  });

  it("admite administración por cualquiera de sus permisos", () => {
    const admin = GLOBAL_ROUTES.find((route) => route.id === "admin")!;
    expect(canAccessRoute(admin, ["audit.read"])).toBe(true);
    expect(canAccessRoute(admin, ["dossier.read"])).toBe(false);
  });

  it("genera enlaces y breadcrumbs contextuales de expediente", () => {
    expect(dossierTabHref("abc 123", "signals")).toBe(
      "/app/dossiers/abc%20123/signals",
    );
    expect(breadcrumbsForPath("/app/dossiers/abc/signals")).toEqual([
      { label: "Expedientes", href: "/app/dossiers" },
      { label: "Expediente", href: "/app/dossiers/abc" },
      { label: "Señales" },
    ]);
  });
});
