import { describe, expect, it } from "vitest";
import {
  DOSSIER_DRAFT_SCHEMA,
  DRAFT_LIMITS,
  buildDossierDraftDocument,
  dossierDraftFilename,
  parseDossierDraftDocument,
  parseDossierDraftJson,
  DossierDraftParseError,
  type DossierDraftData,
} from "./dossier-draft-io";

function sampleData(overrides: Partial<DossierDraftData> = {}): DossierDraftData {
  return {
    title: "Mercado de almacenamiento",
    goal: "Decidir si entramos",
    description: "Notas",
    createStarterProfile: true,
    competitors: "Alpha, Beta",
    competitorsKnowledge: "known",
    discoveryIntent: "",
    discoveryActorType: "",
    discoveryKnownNames: "",
    ownOffer: "Integración de baterías",
    segments: "utility",
    geographies: "ES, DE",
    buyers: "operadores",
    horizon: "12 meses",
    keywords: "batería",
    cpv: "",
    sources: "PLACSP",
    participation: "",
    exclusion: "",
    indicators: "ROI",
    activeOnCreate: true,
    sectors: "energía",
    channels: "licitación",
    partners: "Partner",
    regulators: "CNMC",
    barriers: "certificación",
    decisionToMake: "Entrar con partner",
    marketCountries: ["ES", "DE"],
    marketLanguages: ["es", "de"],
    languagesTouched: true,
    ...overrides,
  };
}

describe("dossier-draft-io", () => {
  it("ida y vuelta: exportar y parsear conserva el estado de usuario", () => {
    const original = buildDossierDraftDocument({
      type: "market",
      data: sampleData(),
      exportedAt: new Date("2026-08-07T12:00:00.000Z"),
    });
    const again = parseDossierDraftJson(JSON.stringify(original));
    expect(again.schema).toBe(DOSSIER_DRAFT_SCHEMA);
    expect(again.type).toBe("market");
    expect(again.exported_at).toBe("2026-08-07T12:00:00.000Z");
    expect(again.data).toEqual(sampleData());
  });

  it("rechaza schema desconocido", () => {
    expect(() =>
      parseDossierDraftDocument({
        schema: "opn.dossier-draft.v0",
        exported_at: "2026-08-07T12:00:00.000Z",
        type: "market",
        data: sampleData(),
      }),
    ).toThrow(DossierDraftParseError);
    expect(() =>
      parseDossierDraftDocument({
        schema: "opn.dossier-draft.v0",
        exported_at: "2026-08-07T12:00:00.000Z",
        type: "market",
        data: sampleData(),
      }),
    ).toThrow(/Esquema no reconocido/);
  });

  it("ignora claves desconocidas en data sin fallar", () => {
    const parsed = parseDossierDraftDocument({
      schema: DOSSIER_DRAFT_SCHEMA,
      exported_at: "2026-08-07T12:00:00.000Z",
      type: "project",
      data: {
        ...sampleData({ title: "Libre", goal: "Meta" }),
        readiness: { secret: true },
        tenant_id: "should-ignore",
        busy: true,
        __proto__: { polluted: true },
      },
      extra_root: 1,
    });
    expect(parsed.data.title).toBe("Libre");
    expect(parsed.data).not.toHaveProperty("readiness");
    expect(parsed.data).not.toHaveProperty("tenant_id");
  });

  it("recorta longitudes al límite del formulario", () => {
    const longTitle = "T".repeat(DRAFT_LIMITS.title + 40);
    const parsed = parseDossierDraftDocument({
      schema: DOSSIER_DRAFT_SCHEMA,
      exported_at: "2026-08-07T12:00:00.000Z",
      type: "project",
      data: sampleData({ title: longTitle }),
    });
    expect(parsed.data.title).toHaveLength(DRAFT_LIMITS.title);
  });

  it("rechaza tipos de campo incorrectos sin aplicar parcial", () => {
    expect(() =>
      parseDossierDraftDocument({
        schema: DOSSIER_DRAFT_SCHEMA,
        exported_at: "2026-08-07T12:00:00.000Z",
        type: "market",
        data: { ...sampleData(), activeOnCreate: "yes" },
      }),
    ).toThrow(/activeOnCreate/);
  });

  it("genera nombre de fichero a partir del título", () => {
    expect(dossierDraftFilename("Mercado de Almacenamiento", new Date("2026-08-07T00:00:00Z"))).toBe(
      "mercado-de-almacenamiento-2026-08-07.json",
    );
  });
});
