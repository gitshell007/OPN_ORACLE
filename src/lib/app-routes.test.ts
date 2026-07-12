import { describe, expect, it } from "vitest";
import {
  breadcrumbsForPath,
  canAccessRoute,
  dossierTabHref,
  GLOBAL_ROUTES,
  visibleGlobalRoutes,
} from "./app-routes";

describe("registro de rutas", () => {
  it("mantiene los diez destinos de trabajo en orden estable", () => {
    expect(GLOBAL_ROUTES.filter((route) => route.group !== "admin")).toHaveLength(10);
    expect(GLOBAL_ROUTES.slice(0, 3).map((route) => route.href)).toEqual([
      "/app",
      "/app/dossiers",
      "/app/changes",
    ]);
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
