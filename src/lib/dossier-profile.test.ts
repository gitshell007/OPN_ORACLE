import { describe, expect, it } from "vitest";
import {
  ANNUAL_TURNOVER_INVALID_MSG,
  PAST_SERVICES_MAX_LEN,
  draftFromProfileConfig,
  emptyCompetitiveDraft,
  emptyCustomDraft,
  emptyMarketDraft,
  listField,
  parseAnnualTurnover,
  profileConfigFromDraft,
  profileHasContent,
  profileKindFor,
  solvencyPayloadFromDraft,
  validateSolvencyDraft,
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

  it("parseAnnualTurnover distingue vacío, válido e inválido (tipado, no undefined)", () => {
    expect(parseAnnualTurnover("")).toEqual({ status: "empty" });
    expect(parseAnnualTurnover("  ")).toEqual({ status: "empty" });
    expect(parseAnnualTurnover("0")).toEqual({ status: "valid", value: 0 });
    expect(parseAnnualTurnover("2000000")).toEqual({ status: "valid", value: 2_000_000 });
    expect(parseAnnualTurnover("2000000.50")).toEqual({ status: "valid", value: 2000000.5 });
    expect(parseAnnualTurnover("1500,25")).toEqual({ status: "valid", value: 1500.25 });
    // Exterior-only whitespace is trimmed; value remains valid.
    expect(parseAnnualTurnover("  1000000  ")).toEqual({ status: "valid", value: 1_000_000 });

    for (const bad of [
      "1.000.000 EUR",
      "-5",
      "NaN",
      "Infinity",
      "abc",
      "1e6",
      "1.000.000",
      "€2000000",
      "2000000 EUR",
      // Internal whitespace = thousand separator (or garbage) → invalid, never stripped
      "1 000 000",
      "1\t000",
      "1\u00a0000",
      "1\u202f000",
    ]) {
      const parsed = parseAnnualTurnover(bad);
      expect(parsed.status).toBe("invalid");
      if (parsed.status === "invalid") {
        expect(parsed.message).toBe(ANNUAL_TURNOVER_INVALID_MSG);
      }
      // Invalid never serializes to payload nor clean absence
      expect(() =>
        solvencyPayloadFromDraft({ annual_turnover: bad, past_services: "" }),
      ).toThrow(/número|volumen|Introduce/i);
      const emptyPayload = solvencyPayloadFromDraft({
        annual_turnover: "",
        past_services: "",
      });
      expect(emptyPayload).not.toHaveProperty("annual_turnover");
    }
  });

  it("whitespace interno (espacio, tab, NBSP, narrow NBSP) es invalid y no produce número ni ausencia", () => {
    const spaced = [
      "1 000 000",
      "1\t000",
      "1\u00a0000",
      "1\u202f000",
    ] as const;
    for (const bad of spaced) {
      expect(parseAnnualTurnover(bad)).toEqual({
        status: "invalid",
        message: ANNUAL_TURNOVER_INVALID_MSG,
      });
      expect(validateSolvencyDraft({ annual_turnover: bad, past_services: "" })).toEqual({
        annual_turnover: ANNUAL_TURNOVER_INVALID_MSG,
      });
      expect(() =>
        solvencyPayloadFromDraft({ annual_turnover: bad, past_services: "ok" }),
      ).toThrow(/Introduce un número/);
      // Must not coerce to number or omit silently
      expect(() => profileConfigFromDraft({ ...emptyMarketDraft(), annual_turnover: bad })).toThrow();
    }
  });

  it("solvencyPayloadFromDraft: vacío omite; 0 y decimal emiten; no trunca servicios", () => {
    expect(solvencyPayloadFromDraft({ annual_turnover: "", past_services: "" })).toEqual({});
    expect(solvencyPayloadFromDraft({ annual_turnover: "0", past_services: "" })).toEqual({
      annual_turnover: 0,
    });
    expect(
      solvencyPayloadFromDraft({ annual_turnover: "2000000.5", past_services: "EPC" }),
    ).toEqual({ annual_turnover: 2_000_000.5, past_services: "EPC" });

    const maxOk = "x".repeat(PAST_SERVICES_MAX_LEN);
    expect(
      solvencyPayloadFromDraft({ annual_turnover: "", past_services: maxOk }).past_services,
    ).toBe(maxOk);

    const over = "y".repeat(PAST_SERVICES_MAX_LEN + 1);
    expect(() =>
      solvencyPayloadFromDraft({ annual_turnover: "100", past_services: over }),
    ).toThrow(/4000|caracteres/i);
    // Must not silently truncate into a valid payload
    expect(() => profileConfigFromDraft({ ...emptyMarketDraft(), past_services: over })).toThrow();
  });

  it("validateSolvencyDraft no confunde vacío con inválido", () => {
    expect(validateSolvencyDraft({ annual_turnover: "", past_services: "" })).toEqual({});
    expect(validateSolvencyDraft({ annual_turnover: "1.000.000 EUR", past_services: "" })).toEqual({
      annual_turnover: ANNUAL_TURNOVER_INVALID_MSG,
    });
    const over = "z".repeat(PAST_SERVICES_MAX_LEN + 1);
    const errs = validateSolvencyDraft({ annual_turnover: "100", past_services: over });
    expect(errs.past_services).toMatch(/4000/);
    expect(errs.annual_turnover).toBeUndefined();
  });
});
