import { describe, expect, it } from "vitest";
import { buildRuntimeLabel, formatBuiltAt } from "./runtime-meta";

describe("buildRuntimeLabel", () => {
  it("parsea release nativo con stamp UTC y SHA", () => {
    const label = buildRuntimeLabel({
      release: "20260807T143022Z-native-a1b2c3d",
      environment: "development",
      version: "0.1.0",
    });
    expect(label.shortSha).toBe("a1b2c3d");
    expect(label.builtAt?.toISOString()).toBe("2026-08-07T14:30:22.000Z");
    expect(label.primary).toContain("2026");
    // 14:30 UTC en agosto = 16:30 en península (UTC+2 / CEST)
    expect(label.primary).toMatch(/16:30/);
    expect(label.primary).toContain("España");
    expect(label.secondary).toBe("a1b2c3d · development");
  });

  it("etiqueta desarrollo local sin release nativo", () => {
    const label = buildRuntimeLabel({
      release: "development",
      environment: "development",
      version: "0.1.0",
    });
    expect(label.primary).toBe("Entorno de desarrollo");
    expect(label.shortSha).toBeNull();
    expect(label.builtAt).toBeNull();
    expect(label.secondary).toContain("0.1.0");
  });

  it("conserva release opaco como primario", () => {
    const label = buildRuntimeLabel({
      release: "v0.2.0-rc.1",
      environment: "production",
      version: "0.2.0",
    });
    expect(label.primary).toBe("v0.2.0-rc.1");
    expect(label.secondary).toBe("v0.2.0 · production");
  });
});

describe("formatBuiltAt", () => {
  it("formatea en hora peninsular (Europe/Madrid)", () => {
    // Agosto: CEST = UTC+2 → 14:30Z se muestra como 16:30
    const summer = formatBuiltAt(new Date("2026-08-07T14:30:22Z"));
    expect(summer).toMatch(/2026/);
    expect(summer).toMatch(/16:30/);
    expect(summer).toContain("España");

    // Enero: CET = UTC+1 → 14:30Z se muestra como 15:30
    const winter = formatBuiltAt(new Date("2026-01-15T14:30:00Z"));
    expect(winter).toMatch(/15:30/);
    expect(winter).toContain("España");
  });
});
