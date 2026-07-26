import { describe, expect, it } from "vitest";
import {
  edgeMatchesRoleCategories,
  edgeRoleCategories,
  graphRoleCategoryOptions,
  primaryRoleCategory,
} from "./entity-graph-roles";

describe("entity-graph-roles", () => {
  it("clasifica roles por alias cuando no hay role_categories del proveedor", () => {
    expect(edgeRoleCategories({ source: "a", target: "b", role: "ADMINISTRADOR UNICO" })).toEqual([
      "governance",
    ]);
    expect(edgeRoleCategories({ source: "a", target: "b", role: "APODERADO" })).toEqual([
      "representation",
    ]);
    expect(edgeRoleCategories({ source: "a", target: "b", role: "SOCIO" })).toEqual(["ownership"]);
    expect(primaryRoleCategory({ source: "a", target: "b", role: "AUDITOR" })).toBe("audit");
  });

  it("respeta el contrato role_categories del backend", () => {
    expect(
      edgeRoleCategories({
        source: "a",
        target: "b",
        role: "Etiqueta rara",
        role_categories: ["ownership"],
      }),
    ).toEqual(["ownership"]);
  });

  it("filtra por familias activas", () => {
    const edge = { source: "a", target: "b", role: "APODERADO" };
    expect(edgeMatchesRoleCategories(edge, new Set(["representation"]))).toBe(true);
    expect(edgeMatchesRoleCategories(edge, new Set(["governance"]))).toBe(false);
    expect(edgeMatchesRoleCategories(edge, new Set())).toBe(false);
  });

  it("agrega recuentos por familia en el grafo", () => {
    const options = graphRoleCategoryOptions({
      nodes: [],
      edges: [
        { source: "c", target: "a", role: "ADMINISTRADOR" },
        { source: "c", target: "b", role: "APODERADO" },
        { source: "c", target: "d", role: "APODERADO" },
      ],
      truncated: false,
      cached_seconds: 0,
      cache_hit: false,
    });
    const byKey = Object.fromEntries(options.map((o) => [o.key, o.count]));
    expect(byKey.governance).toBe(1);
    expect(byKey.representation).toBe(2);
  });
});
