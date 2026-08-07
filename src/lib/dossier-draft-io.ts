/**
 * Exportación/importación de borradores del asistente de creación de expedientes.
 * Esquema versionado, validación campo a campo, sin estado de UI ni secretos.
 */

import { isIsoGeographyCode, isIsoLanguageCode } from "@/lib/eu-countries";

export const DOSSIER_DRAFT_SCHEMA = "opn.dossier-draft.v1" as const;

export const DOSSIER_DRAFT_TYPES = [
  "project",
  "market",
  "strategic_account",
  "tender_or_grant",
  "partnership",
  "regulatory_affair",
  "competitive_intelligence",
  "custom",
] as const;

export type DossierDraftType = (typeof DOSSIER_DRAFT_TYPES)[number];

/** Alineado con CompetitorsKnowledge del diálogo de creación. */
export type DraftCompetitorsKnowledge = "known" | "unknown" | "not_seeking" | "";

/** Alineado con DiscoveryActorType del diálogo de creación. */
export type DraftDiscoveryActorType =
  | "company"
  | "research_group"
  | "technology_center"
  | "regulator"
  | "potential_customer"
  | "";

const COMPETITORS_KNOWLEDGE = new Set<string>([
  "",
  "known",
  "unknown",
  "not_seeking",
]);

const DISCOVERY_ACTOR_TYPES = new Set<string>([
  "",
  "company",
  "research_group",
  "technology_center",
  "regulator",
  "potential_customer",
]);

/** Límites alineados con maxLength del formulario o tope prudente. */
export const DRAFT_LIMITS = {
  title: 240,
  goal: 5000,
  description: 10000,
  ownOffer: 2000,
  decisionToMake: 2000,
  discoveryIntent: 2000,
  competitors: 5000,
  discoveryKnownNames: 5000,
  segments: 2000,
  geographies: 2000,
  buyers: 2000,
  horizon: 500,
  keywords: 2000,
  cpv: 2000,
  sources: 2000,
  participation: 5000,
  exclusion: 5000,
  indicators: 2000,
  sectors: 2000,
  channels: 2000,
  partners: 2000,
  regulators: 2000,
  barriers: 2000,
  maxCountries: 100,
  maxLanguages: 50,
  geographyCode: 8,
  languageCode: 8,
} as const;

/** Datos de usuario del asistente (sin readiness/busy/error/sesión). */
export type DossierDraftData = {
  title: string;
  goal: string;
  description: string;
  createStarterProfile: boolean;
  competitors: string;
  competitorsKnowledge: DraftCompetitorsKnowledge;
  discoveryIntent: string;
  discoveryActorType: DraftDiscoveryActorType;
  discoveryKnownNames: string;
  ownOffer: string;
  segments: string;
  geographies: string;
  buyers: string;
  horizon: string;
  keywords: string;
  cpv: string;
  sources: string;
  participation: string;
  exclusion: string;
  indicators: string;
  activeOnCreate: boolean;
  sectors: string;
  channels: string;
  partners: string;
  regulators: string;
  barriers: string;
  decisionToMake: string;
  marketCountries: string[];
  marketLanguages: string[];
  languagesTouched: boolean;
};

export type DossierDraftDocument = {
  schema: typeof DOSSIER_DRAFT_SCHEMA;
  exported_at: string;
  type: DossierDraftType;
  data: DossierDraftData;
};

export class DossierDraftParseError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "DossierDraftParseError";
  }
}

function isPlainObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function asString(value: unknown, max: number, field: string): string {
  if (value === undefined || value === null) return "";
  if (typeof value !== "string") {
    throw new DossierDraftParseError(`El campo «${field}» debe ser texto.`);
  }
  return value.slice(0, max);
}

function asBoolean(value: unknown, fallback: boolean, field: string): boolean {
  if (value === undefined || value === null) return fallback;
  if (typeof value !== "boolean") {
    throw new DossierDraftParseError(`El campo «${field}» debe ser verdadero o falso.`);
  }
  return value;
}

function asStringList(
  value: unknown,
  options: {
    maxItems: number;
    itemMax: number;
    field: string;
    validateItem?: (item: string) => boolean;
  },
): string[] {
  if (value === undefined || value === null) return [];
  if (!Array.isArray(value)) {
    throw new DossierDraftParseError(
      `El campo «${options.field}» debe ser una lista.`,
    );
  }
  if (value.length > options.maxItems) {
    throw new DossierDraftParseError(
      `El campo «${options.field}» admite como máximo ${options.maxItems} elementos.`,
    );
  }
  const out: string[] = [];
  for (const raw of value) {
    if (typeof raw !== "string") {
      throw new DossierDraftParseError(
        `Cada elemento de «${options.field}» debe ser texto.`,
      );
    }
    const item = raw.trim().slice(0, options.itemMax);
    if (!item) continue;
    if (options.validateItem && !options.validateItem(item)) {
      throw new DossierDraftParseError(
        `Valor no válido en «${options.field}»: ${item.slice(0, 32)}.`,
      );
    }
    out.push(item);
  }
  return out;
}

export function isDossierDraftType(value: unknown): value is DossierDraftType {
  return (
    typeof value === "string" &&
    (DOSSIER_DRAFT_TYPES as readonly string[]).includes(value)
  );
}

/** Serializa el estado de usuario a documento versionado. */
export function buildDossierDraftDocument(input: {
  type: string;
  data: DossierDraftData;
  exportedAt?: Date;
}): DossierDraftDocument {
  if (!isDossierDraftType(input.type)) {
    throw new DossierDraftParseError("Tipo de expediente no válido para exportar.");
  }
  return {
    schema: DOSSIER_DRAFT_SCHEMA,
    exported_at: (input.exportedAt ?? new Date()).toISOString(),
    type: input.type,
    data: { ...input.data },
  };
}

/**
 * Parsea y valida un JSON de borrador. Fallo atómico: o devuelve un documento
 * completo o lanza DossierDraftParseError sin efectos laterales.
 */
export function parseDossierDraftDocument(raw: unknown): DossierDraftDocument {
  if (!isPlainObject(raw)) {
    throw new DossierDraftParseError("El fichero no contiene un objeto JSON.");
  }
  if (raw.schema !== DOSSIER_DRAFT_SCHEMA) {
    throw new DossierDraftParseError(
      `Esquema no reconocido${typeof raw.schema === "string" ? ` («${raw.schema}»)` : ""}. Se espera ${DOSSIER_DRAFT_SCHEMA}.`,
    );
  }
  if (!isDossierDraftType(raw.type)) {
    throw new DossierDraftParseError(
      "Tipo de expediente ausente o no admitido en el borrador.",
    );
  }
  if (typeof raw.exported_at !== "string" || !raw.exported_at.trim()) {
    throw new DossierDraftParseError("Falta la fecha de exportación (exported_at).");
  }
  if (!isPlainObject(raw.data)) {
    throw new DossierDraftParseError("El borrador no incluye el bloque «data».");
  }
  const src = raw.data;
  // Claves desconocidas se ignoran a propósito (solo leemos las conocidas).
  const competitorsKnowledgeRaw = asString(
    src.competitorsKnowledge,
    32,
    "competitorsKnowledge",
  );
  if (!COMPETITORS_KNOWLEDGE.has(competitorsKnowledgeRaw)) {
    throw new DossierDraftParseError(
      "Valor no válido en «competitorsKnowledge».",
    );
  }
  const discoveryActorTypeRaw = asString(
    src.discoveryActorType,
    40,
    "discoveryActorType",
  );
  if (!DISCOVERY_ACTOR_TYPES.has(discoveryActorTypeRaw)) {
    throw new DossierDraftParseError("Valor no válido en «discoveryActorType».");
  }

  const data: DossierDraftData = {
    title: asString(src.title, DRAFT_LIMITS.title, "title"),
    goal: asString(src.goal, DRAFT_LIMITS.goal, "goal"),
    description: asString(src.description, DRAFT_LIMITS.description, "description"),
    createStarterProfile: asBoolean(src.createStarterProfile, true, "createStarterProfile"),
    competitors: asString(src.competitors, DRAFT_LIMITS.competitors, "competitors"),
    competitorsKnowledge: competitorsKnowledgeRaw as DraftCompetitorsKnowledge,
    discoveryIntent: asString(
      src.discoveryIntent,
      DRAFT_LIMITS.discoveryIntent,
      "discoveryIntent",
    ),
    discoveryActorType: discoveryActorTypeRaw as DraftDiscoveryActorType,
    discoveryKnownNames: asString(
      src.discoveryKnownNames,
      DRAFT_LIMITS.discoveryKnownNames,
      "discoveryKnownNames",
    ),
    ownOffer: asString(src.ownOffer, DRAFT_LIMITS.ownOffer, "ownOffer"),
    segments: asString(src.segments, DRAFT_LIMITS.segments, "segments"),
    geographies: asString(src.geographies, DRAFT_LIMITS.geographies, "geographies"),
    buyers: asString(src.buyers, DRAFT_LIMITS.buyers, "buyers"),
    horizon: asString(src.horizon, DRAFT_LIMITS.horizon, "horizon"),
    keywords: asString(src.keywords, DRAFT_LIMITS.keywords, "keywords"),
    cpv: asString(src.cpv, DRAFT_LIMITS.cpv, "cpv"),
    sources: asString(src.sources, DRAFT_LIMITS.sources, "sources"),
    participation: asString(
      src.participation,
      DRAFT_LIMITS.participation,
      "participation",
    ),
    exclusion: asString(src.exclusion, DRAFT_LIMITS.exclusion, "exclusion"),
    indicators: asString(src.indicators, DRAFT_LIMITS.indicators, "indicators"),
    activeOnCreate: asBoolean(src.activeOnCreate, true, "activeOnCreate"),
    sectors: asString(src.sectors, DRAFT_LIMITS.sectors, "sectors"),
    channels: asString(src.channels, DRAFT_LIMITS.channels, "channels"),
    partners: asString(src.partners, DRAFT_LIMITS.partners, "partners"),
    regulators: asString(src.regulators, DRAFT_LIMITS.regulators, "regulators"),
    barriers: asString(src.barriers, DRAFT_LIMITS.barriers, "barriers"),
    decisionToMake: asString(
      src.decisionToMake,
      DRAFT_LIMITS.decisionToMake,
      "decisionToMake",
    ),
    marketCountries: asStringList(src.marketCountries, {
      maxItems: DRAFT_LIMITS.maxCountries,
      itemMax: DRAFT_LIMITS.geographyCode,
      field: "marketCountries",
      validateItem: (code) => isIsoGeographyCode(code),
    }).map((code) => code.toUpperCase()),
    marketLanguages: asStringList(src.marketLanguages, {
      maxItems: DRAFT_LIMITS.maxLanguages,
      itemMax: DRAFT_LIMITS.languageCode,
      field: "marketLanguages",
      validateItem: (code) => isIsoLanguageCode(code),
    }).map((code) => code.toLowerCase()),
    languagesTouched: asBoolean(src.languagesTouched, false, "languagesTouched"),
  };

  return {
    schema: DOSSIER_DRAFT_SCHEMA,
    exported_at: raw.exported_at.trim().slice(0, 64),
    type: raw.type,
    data,
  };
}

export function parseDossierDraftJson(text: string): DossierDraftDocument {
  let parsed: unknown;
  try {
    parsed = JSON.parse(text) as unknown;
  } catch {
    throw new DossierDraftParseError("El fichero no es un JSON válido.");
  }
  return parseDossierDraftDocument(parsed);
}

/** Nombre de fichero seguro a partir del título y la fecha. */
export function dossierDraftFilename(title: string, when = new Date()): string {
  const stamp = when.toISOString().slice(0, 10);
  const base = title
    .trim()
    .normalize("NFD")
    .replace(/\p{M}/gu, "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 48);
  return `${base || "borrador-expediente"}-${stamp}.json`;
}

export function downloadJsonFile(filename: string, payload: unknown): void {
  const blob = new Blob([`${JSON.stringify(payload, null, 2)}\n`], {
    type: "application/json;charset=utf-8",
  });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.rel = "noopener";
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}
