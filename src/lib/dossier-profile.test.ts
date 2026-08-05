import { describe, expect, it } from "vitest";
import {
  annualTurnoverFromField,
  draftFromProfileConfig,
  emptyCompetitiveDraft,
  emptyCustomDraft,
  emptyMarketDraft,
  listField,
  profileConfigFromDraft,
  profileHasContent,
  profileKindFor,
} from "./dossier-profile";

describe("dossier-profile helpers", () => {
  it("clasifica tipos de perfil", () => {
    expect(profileKindFor("market")).toBe("market");
    expect(profileKindFor("competitive_intelligence")).toBe("competitive_intelligence");
    expect(profileKindFor("custom")).toBe("custom");
    expect(profileKindFor("project")).toBe("custom");
    expect(profileKindFor("unknown_type")).toBe("empty");
    expect(profileKindFor("unknown_type", { mystery: true })).toBe("custom");
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

  it("serializa el perfil custom del expediente demo (oferta, CPV, competidores, decisión)", () => {
    const draft = draftFromProfileConfig("custom", {
      version: "v1",
      own_offer: "Software e IA para sector público",
      decision_to_make: "Priorizar cuentas PLACSP software",
      competitors: [
        { name: "Capgemini", aliases: [] },
        { name: "NTT DATA", aliases: [] },
        { name: "Inetum", aliases: [] },
      ],
      cpv: ["72000000", "72200000", "72212000"],
      barriers: ["Homologación sector público"],
      keywords: ["software", "IA"],
    });
    expect(draft?.kind).toBe("custom");
    expect(draft && draft.kind === "custom" && draft.competitors).toBe(
      "Capgemini, NTT DATA, Inetum",
    );
    expect(draft && draft.kind === "custom" && draft.cpv).toBe(
      "72000000, 72200000, 72212000",
    );
    const payload = profileConfigFromDraft(draft!);
    expect(payload.version).toBe("custom.v1");
    expect(payload.own_offer).toBe("Software e IA para sector público");
    expect(payload.decision_to_make).toBe("Priorizar cuentas PLACSP software");
    expect(payload.competitors).toEqual([
      { name: "Capgemini", aliases: [] },
      { name: "NTT DATA", aliases: [] },
      { name: "Inetum", aliases: [] },
    ]);
    expect(payload.cpv).toEqual(["72000000", "72200000", "72212000"]);
    expect(payload.barriers).toEqual(["Homologación sector público"]);
  });

  it("parsea listas por comas y saltos de línea", () => {
    expect(listField("a, b\nc")).toEqual(["a", "b", "c"]);
  });

  it("detecta contenido útil ignorando solo version", () => {
    expect(profileHasContent({ version: "market.v1" })).toBe(false);
    expect(profileHasContent({ version: "market.v1", own_offer: "x" })).toBe(true);
  });

  it("round-trip vacío de solvencia no emite 0 ni cadenas fantasma (tres kinds)", () => {
    for (const draft of [emptyMarketDraft(), emptyCompetitiveDraft(), emptyCustomDraft()]) {
      const payload = profileConfigFromDraft(draft);
      expect(payload).not.toHaveProperty("annual_turnover");
      expect(payload).not.toHaveProperty("past_services");
    }
  });

  it("round-trip de annual_turnover decimal y past_services en market", () => {
    const draft = draftFromProfileConfig("market", {
      version: "market.v1",
      own_offer: "Baterías",
      decision_to_make: "Entrar",
      annual_turnover: 2_000_000.5,
      past_services: "EPC 2023-2025 con certificados",
    });
    expect(draft && draft.kind === "market" && draft.annual_turnover).toBe("2000000.5");
    expect(draft && draft.kind === "market" && draft.past_services).toBe(
      "EPC 2023-2025 con certificados",
    );
    const payload = profileConfigFromDraft(draft!);
    expect(payload.annual_turnover).toBe(2_000_000.5);
    expect(payload.past_services).toBe("EPC 2023-2025 con certificados");
  });

  it("round-trip de solvencia en competitive_intelligence y custom", () => {
    const ci = draftFromProfileConfig("competitive_intelligence", {
      own_offer: "Oferta",
      business_objective: "Ganar",
      competitors: [{ name: "Rival" }],
      annual_turnover: 1_500_000,
      past_services: "Limpieza 2024",
    });
    expect(profileConfigFromDraft(ci!).annual_turnover).toBe(1_500_000);
    expect(profileConfigFromDraft(ci!).past_services).toBe("Limpieza 2024");

    const custom = draftFromProfileConfig("custom", {
      version: "custom.v1",
      own_offer: "Software",
      competitors: [{ name: "Capgemini" }],
      annual_turnover: 2_000_000,
      past_services: "IA pública con certificados",
    });
    const customPayload = profileConfigFromDraft(custom!);
    expect(customPayload.annual_turnover).toBe(2_000_000);
    expect(customPayload.past_services).toBe("IA pública con certificados");
  });

  it("annualTurnoverFromField normaliza y rechaza vacío/ambiguo", () => {
    expect(annualTurnoverFromField("")).toBeUndefined();
    expect(annualTurnoverFromField("  ")).toBeUndefined();
    expect(annualTurnoverFromField("2000000")).toBe(2_000_000);
    expect(annualTurnoverFromField("2000000.50")).toBe(2000000.5);
    expect(annualTurnoverFromField("1.000.000 EUR")).toBeUndefined();
    expect(annualTurnoverFromField("NaN")).toBeUndefined();
  });
});
