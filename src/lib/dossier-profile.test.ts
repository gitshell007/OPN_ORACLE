import { describe, expect, it } from "vitest";
import {
  draftFromProfileConfig,
  listField,
  profileConfigFromDraft,
  profileHasContent,
  profileKindFor,
} from "./dossier-profile";

describe("dossier-profile helpers", () => {
  it("clasifica tipos de perfil", () => {
    expect(profileKindFor("market")).toBe("market");
    expect(profileKindFor("competitive_intelligence")).toBe("competitive_intelligence");
    expect(profileKindFor("project")).toBe("empty");
    expect(profileKindFor("project", { mystery: true })).toBe("other");
  });

  it("serializa y deserializa un perfil de mercado", () => {
    const draft = draftFromProfileConfig("market", {
      version: "market.v1",
      own_offer: "Baterías",
      decision_to_make: "Entrar o no",
      competitors: [{ name: "Gamma", aliases: ["G"] }],
      barriers: ["Permisos"],
      keywords: ["almacenamiento"],
    });
    expect(draft?.kind).toBe("market");
    expect(draft && draft.kind === "market" && draft.competitors).toBe("Gamma");
    expect(draft && draft.kind === "market" && draft.barriers).toBe("Permisos");
    const payload = profileConfigFromDraft(draft!);
    expect(payload.own_offer).toBe("Baterías");
    expect(payload.competitors).toEqual([{ name: "Gamma", aliases: [] }]);
    expect(payload.barriers).toEqual(["Permisos"]);
  });

  it("serializa CPV y competidores del perfil competitivo", () => {
    const draft = draftFromProfileConfig("competitive_intelligence", {
      version: "competitive-intelligence.v1",
      own_offer: "Oferta",
      business_objective: "Ganar",
      competitors: [{ name: "Rival A" }, { name: "Rival B" }],
      cpv: ["90910000", "35110000"],
    });
    const payload = profileConfigFromDraft(draft!);
    expect(payload.cpv).toEqual(["90910000", "35110000"]);
    expect(payload.competitors).toEqual([
      { name: "Rival A", aliases: [] },
      { name: "Rival B", aliases: [] },
    ]);
  });

  it("parsea listas por comas y saltos de línea", () => {
    expect(listField("a, b\nc")).toEqual(["a", "b", "c"]);
  });

  it("detecta contenido útil ignorando solo version", () => {
    expect(profileHasContent({ version: "market.v1" })).toBe(false);
    expect(profileHasContent({ version: "market.v1", own_offer: "x" })).toBe(true);
  });
});
