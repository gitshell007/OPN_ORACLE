/** Helpers for strategic_dossiers.profile_config.
 *
 * Mapa real (no unificar a lo bravo):
 * - market → market.v1 (intake mercado)
 * - competitive_intelligence → competitive-intelligence.v1
 * - custom/project/opportunity/… → free-form JSONB (API passthrough); UI modela
 *   un subconjunto estratégico (oferta, competidores, CPV, barreras, decisión)
 *   con version "custom.v1" al guardar desde esta pantalla.
 * - dossier memory profile (API aparte) y procurement search profiles son otros
 *   objetos; no se mezclan aquí.
 */

export type ProfileKind = "market" | "competitive_intelligence" | "custom" | "empty";

export type CompetitorDraft = {
  name: string;
  aliases: string[];
  website?: string;
  tax_id?: string;
  country?: string;
};

export type MarketProfileDraft = {
  kind: "market";
  own_offer: string;
  decision_to_make: string;
  horizon: string;
  segments: string;
  channels: string;
  target_buyers: string;
  competitors: string;
  partners: string;
  regulators: string;
  barriers: string;
  success_indicators: string;
  keywords: string;
};

export type CompetitiveProfileDraft = {
  kind: "competitive_intelligence";
  own_offer: string;
  business_objective: string;
  competitors: string;
  segments: string;
  geographies: string;
  target_buyers: string;
  horizon: string;
  keywords: string;
  cpv: string;
  sources: string;
  participation_criteria: string;
  exclusion_criteria: string;
  success_indicators: string;
};

/** Free-form strategic intake for custom/project and other non-typed dossier types. */
export type CustomProfileDraft = {
  kind: "custom";
  own_offer: string;
  decision_to_make: string;
  competitors: string;
  barriers: string;
  cpv: string;
  keywords: string;
  geographies: string;
  target_buyers: string;
  segments: string;
  business_objective: string;
  success_indicators: string;
  sources: string;
};

export type ProfileDraft = MarketProfileDraft | CompetitiveProfileDraft | CustomProfileDraft;

export function profileKindFor(
  dossierType: string,
  profileConfig?: Record<string, unknown> | null,
): ProfileKind {
  if (dossierType === "market") return "market";
  if (dossierType === "competitive_intelligence") return "competitive_intelligence";
  // Custom and siblings always expose the strategic form (even empty) so the
  // intake loop can be closed for demo/project dossiers without changing type.
  if (
    dossierType === "custom" ||
    dossierType === "project" ||
    dossierType === "opportunity" ||
    dossierType === "risk" ||
    dossierType === "account" ||
    (profileConfig && Object.keys(profileConfig).length > 0)
  ) {
    return "custom";
  }
  return "empty";
}

export function listField(value: string): string[] {
  return [...new Set(value.split(/[\n,]/).map((item) => item.trim()).filter(Boolean))];
}

export function competitorsFromField(value: string): CompetitorDraft[] {
  return listField(value).map((name) => ({ name, aliases: [] }));
}

export function competitorsToField(value: unknown): string {
  if (!Array.isArray(value)) return "";
  return value
    .map((item) => {
      if (typeof item === "string") return item.trim();
      if (item && typeof item === "object" && "name" in item) {
        return String((item as { name?: unknown }).name ?? "").trim();
      }
      return "";
    })
    .filter(Boolean)
    .join(", ");
}

export function stringsToField(value: unknown): string {
  if (!Array.isArray(value)) return "";
  return value.map(String).map((item) => item.trim()).filter(Boolean).join(", ");
}

export function emptyMarketDraft(): MarketProfileDraft {
  return {
    kind: "market",
    own_offer: "",
    decision_to_make: "",
    horizon: "",
    segments: "",
    channels: "",
    target_buyers: "",
    competitors: "",
    partners: "",
    regulators: "",
    barriers: "",
    success_indicators: "",
    keywords: "",
  };
}

export function emptyCompetitiveDraft(): CompetitiveProfileDraft {
  return {
    kind: "competitive_intelligence",
    own_offer: "",
    business_objective: "",
    competitors: "",
    segments: "",
    geographies: "",
    target_buyers: "",
    horizon: "",
    keywords: "",
    cpv: "",
    sources: "",
    participation_criteria: "",
    exclusion_criteria: "",
    success_indicators: "",
  };
}

export function emptyCustomDraft(): CustomProfileDraft {
  return {
    kind: "custom",
    own_offer: "",
    decision_to_make: "",
    competitors: "",
    barriers: "",
    cpv: "",
    keywords: "",
    geographies: "",
    target_buyers: "",
    segments: "",
    business_objective: "",
    success_indicators: "",
    sources: "",
  };
}

function customDraftFromProfile(profile: Record<string, unknown>): CustomProfileDraft {
  return {
    kind: "custom",
    own_offer: String(profile.own_offer ?? ""),
    decision_to_make: String(profile.decision_to_make ?? ""),
    competitors: competitorsToField(profile.competitors),
    barriers: stringsToField(profile.barriers),
    cpv: stringsToField(profile.cpv),
    keywords: stringsToField(profile.keywords),
    geographies: stringsToField(profile.geographies),
    target_buyers: stringsToField(profile.target_buyers),
    segments: stringsToField(profile.segments),
    business_objective: String(profile.business_objective ?? ""),
    success_indicators: stringsToField(profile.success_indicators),
    sources: stringsToField(profile.sources),
  };
}

export function draftFromProfileConfig(
  dossierType: string,
  profileConfig?: Record<string, unknown> | null,
): ProfileDraft | null {
  const profile = profileConfig ?? {};
  if (dossierType === "market") {
    return {
      kind: "market",
      own_offer: String(profile.own_offer ?? ""),
      decision_to_make: String(profile.decision_to_make ?? ""),
      horizon: String(profile.horizon ?? ""),
      segments: stringsToField(profile.segments),
      channels: stringsToField(profile.channels),
      target_buyers: stringsToField(profile.target_buyers),
      competitors: competitorsToField(profile.competitors),
      partners: stringsToField(profile.partners),
      regulators: stringsToField(profile.regulators),
      barriers: stringsToField(profile.barriers),
      success_indicators: stringsToField(profile.success_indicators),
      keywords: stringsToField(profile.keywords),
    };
  }
  if (dossierType === "competitive_intelligence") {
    return {
      kind: "competitive_intelligence",
      own_offer: String(profile.own_offer ?? ""),
      business_objective: String(profile.business_objective ?? ""),
      competitors: competitorsToField(profile.competitors),
      segments: stringsToField(profile.segments),
      geographies: stringsToField(profile.geographies),
      target_buyers: stringsToField(profile.target_buyers),
      horizon: String(profile.horizon ?? ""),
      keywords: stringsToField(profile.keywords),
      cpv: stringsToField(profile.cpv),
      sources: stringsToField(profile.sources),
      participation_criteria: String(profile.participation_criteria ?? ""),
      exclusion_criteria: String(profile.exclusion_criteria ?? ""),
      success_indicators: stringsToField(profile.success_indicators),
    };
  }
  if (profileKindFor(dossierType, profileConfig) === "custom") {
    return customDraftFromProfile(profile);
  }
  return null;
}

export function profileConfigFromDraft(draft: ProfileDraft): Record<string, unknown> {
  if (draft.kind === "market") {
    return {
      own_offer: draft.own_offer.trim(),
      decision_to_make: draft.decision_to_make.trim(),
      horizon: draft.horizon.trim(),
      segments: listField(draft.segments),
      channels: listField(draft.channels),
      target_buyers: listField(draft.target_buyers),
      competitors: competitorsFromField(draft.competitors),
      partners: listField(draft.partners),
      regulators: listField(draft.regulators),
      barriers: listField(draft.barriers),
      success_indicators: listField(draft.success_indicators),
      keywords: listField(draft.keywords),
    };
  }
  if (draft.kind === "competitive_intelligence") {
    return {
      own_offer: draft.own_offer.trim(),
      business_objective: draft.business_objective.trim(),
      competitors: competitorsFromField(draft.competitors),
      segments: listField(draft.segments),
      geographies: listField(draft.geographies),
      target_buyers: listField(draft.target_buyers),
      horizon: draft.horizon.trim(),
      keywords: listField(draft.keywords),
      cpv: listField(draft.cpv),
      sources: listField(draft.sources),
      participation_criteria: draft.participation_criteria.trim(),
      exclusion_criteria: draft.exclusion_criteria.trim(),
      success_indicators: listField(draft.success_indicators),
    };
  }
  // custom.v1: free-form strategic intake. Kept separate from market/CI schemas
  // so agents/context do not treat it as typed evidence until a later turn.
  return {
    version: "custom.v1",
    own_offer: draft.own_offer.trim(),
    decision_to_make: draft.decision_to_make.trim(),
    competitors: competitorsFromField(draft.competitors),
    barriers: listField(draft.barriers),
    cpv: listField(draft.cpv),
    keywords: listField(draft.keywords),
    geographies: listField(draft.geographies),
    target_buyers: listField(draft.target_buyers),
    segments: listField(draft.segments),
    business_objective: draft.business_objective.trim(),
    success_indicators: listField(draft.success_indicators),
    sources: listField(draft.sources),
  };
}

export function profileHasContent(profileConfig?: Record<string, unknown> | null): boolean {
  if (!profileConfig) return false;
  return Object.keys(profileConfig).some((key) => {
    if (key === "version") return false;
    const value = profileConfig[key];
    if (Array.isArray(value)) return value.length > 0;
    if (typeof value === "string") return value.trim().length > 0;
    return value != null;
  });
}
