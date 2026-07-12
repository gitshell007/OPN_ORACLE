import { describe, expect, it } from "vitest";
import { authenticatedLanding, safeNext } from "./safe-next";

describe("safeNext", () => {
  it("conserva destinos internos", () => {
    expect(safeNext("/concept-a/settings/sessions?tab=active")).toBe("/concept-a/settings/sessions?tab=active");
    expect(safeNext("/app/reports?status=ready")).toBe("/app/reports?status=ready");
  });

  it.each(["https://evil.example", "//evil.example", "/\\evil.example", "%2F%2Fevil.example", null])("rechaza redirecciones externas: %s", value => {
    expect(safeNext(value)).toBe("/app");
  });
});

describe("authenticatedLanding", () => {
  it("envía al superadmin sin tenant al alta de organizaciones", () => {
    expect(
      authenticatedLanding(null, {
        active_tenant_id: null,
        user: { platform_role: "super_admin" },
      }),
    ).toBe("/platform/tenants");
  });

  it("mantiene el inicio del producto para una identidad con tenant", () => {
    expect(
      authenticatedLanding(null, {
        active_tenant_id: "tenant-1",
        user: { platform_role: null },
      }),
    ).toBe("/app");
  });

  it("respeta una ruta interna solicitada explícitamente", () => {
    expect(
      authenticatedLanding("/platform/backups", {
        active_tenant_id: null,
        user: { platform_role: "super_admin" },
      }),
    ).toBe("/platform/backups");
  });
});
