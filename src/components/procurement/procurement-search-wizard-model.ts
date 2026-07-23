import type {
  ComparableProcurementProfile,
  TenderSearchPlan,
} from "@oracle/api-client";

export const TENDER_SEARCH_CHIP_CATEGORIES = [
  "include_terms",
  "synonyms",
  "exclude_terms",
  "candidate_cpv",
  "buyers",
  "geographies",
] as const;

export type TenderSearchChipCategory =
  (typeof TENDER_SEARCH_CHIP_CATEGORIES)[number];
export type TenderSearchChipProvenance = "measured" | "ai" | "user";

export interface TenderSearchChip {
  category: TenderSearchChipCategory;
  confirmed: boolean;
  key: string;
  label: string | null;
  provenance: TenderSearchChipProvenance;
  value: string;
}

export interface TenderSearchChipAnnotations {
  confirmedKeys?: Iterable<string>;
  userKeys?: Iterable<string>;
}

export interface MissingMeasuredCandidates {
  cpvs: TenderSearchChip[];
  terms: TenderSearchChip[];
}

export interface RegeneratedTenderSearchPlan {
  chips: TenderSearchChip[];
  plan: TenderSearchPlan;
}

const TERM_CATEGORIES: ReadonlySet<TenderSearchChipCategory> = new Set([
  "include_terms",
  "synonyms",
]);

function normalizeText(value: string): string {
  return value
    .normalize("NFKD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLocaleLowerCase("es")
    .replace(/[^\p{L}\p{N}]+/gu, " ")
    .trim()
    .replace(/\s+/g, " ");
}

function normalizeCpv(value: string): string {
  const digits = value.replace(/\D/g, "");
  return digits.length >= 8 ? digits.slice(0, 8) : digits;
}

export function normalizedTenderSearchChipValue(
  category: TenderSearchChipCategory,
  value: string,
): string {
  return category === "candidate_cpv"
    ? normalizeCpv(value)
    : normalizeText(value);
}

export function tenderSearchChipKey(
  category: TenderSearchChipCategory,
  value: string,
): string {
  return `${category}:${normalizedTenderSearchChipValue(category, value)}`;
}

function makeChip(
  category: TenderSearchChipCategory,
  value: string,
  options: {
    confirmed?: boolean;
    label?: string | null;
    provenance: TenderSearchChipProvenance;
  },
): TenderSearchChip {
  const trimmedValue = value.trim();
  return {
    category,
    confirmed: options.confirmed ?? false,
    key: tenderSearchChipKey(category, trimmedValue),
    label: options.label?.trim() || null,
    provenance: options.provenance,
    value: trimmedValue,
  };
}

function semanticChipKey(chip: TenderSearchChip): string {
  return TERM_CATEGORIES.has(chip.category)
    ? `positive_term:${normalizeText(chip.value)}`
    : chip.key;
}

function isTombstoned(
  chip: TenderSearchChip,
  tombstones: ReadonlySet<string>,
): boolean {
  if (tombstones.has(chip.key)) return true;
  if (!TERM_CATEGORIES.has(chip.category)) return false;
  const normalized = normalizeText(chip.value);
  return (
    tombstones.has(tenderSearchChipKey("include_terms", normalized)) ||
    tombstones.has(tenderSearchChipKey("synonyms", normalized))
  );
}

export function createUserTenderSearchChip(
  category: TenderSearchChipCategory,
  value: string,
  label: string | null = null,
): TenderSearchChip {
  return makeChip(category, value, {
    confirmed: true,
    label,
    provenance: "user",
  });
}

function uniqueChips(chips: readonly TenderSearchChip[]): TenderSearchChip[] {
  const unique = new Map<string, TenderSearchChip>();
  for (const chip of chips) {
    if (!normalizedTenderSearchChipValue(chip.category, chip.value)) continue;
    const identity = semanticChipKey(chip);
    const existing = unique.get(identity);
    if (!existing) {
      unique.set(identity, chip);
      continue;
    }
    if (
      chip.provenance === "user" ||
      (chip.confirmed && !existing.confirmed)
    ) {
      unique.set(identity, chip);
    }
  }
  return [...unique.values()];
}

function measuredSets(profile?: ComparableProcurementProfile | null) {
  return {
    buyers: new Set(
      (profile?.buyers ?? []).slice(0, 20).map(({ buyer }) => normalizeText(buyer)),
    ),
    cpvs: new Set(
      (profile?.frequent_cpvs.items ?? [])
        .slice(0, 20)
        .map(({ code }) => normalizeCpv(code)),
    ),
    terms: new Set(
      (profile?.title_terms.items ?? [])
        .slice(0, 20)
        .map(({ term }) => normalizeText(term)),
    ),
  };
}

function isMeasuredChip(
  category: TenderSearchChipCategory,
  value: string,
  profile?: ComparableProcurementProfile | null,
): boolean {
  const measured = measuredSets(profile);
  if (TERM_CATEGORIES.has(category)) {
    return measured.terms.has(normalizeText(value));
  }
  if (category === "candidate_cpv") {
    return measured.cpvs.has(normalizeCpv(value));
  }
  if (category === "buyers") {
    return measured.buyers.has(normalizeText(value));
  }
  return false;
}

export function tenderSearchPlanToChips(
  plan: TenderSearchPlan,
  profile?: ComparableProcurementProfile | null,
  annotations: TenderSearchChipAnnotations = {},
): TenderSearchChip[] {
  const userKeys = new Set(annotations.userKeys ?? []);
  const confirmedKeys = new Set(annotations.confirmedKeys ?? []);
  const textChips = (
    [
      ["include_terms", plan.include_terms],
      ["synonyms", plan.synonyms],
      ["exclude_terms", plan.exclude_terms],
      ["buyers", plan.buyers],
      ["geographies", plan.geographies],
    ] as const
  ).flatMap(([category, values]) =>
    values.map((value) => {
      const key = tenderSearchChipKey(category, value);
      return makeChip(category, value, {
        confirmed: confirmedKeys.has(key) || userKeys.has(key),
        provenance: userKeys.has(key)
          ? "user"
          : isMeasuredChip(category, value, profile)
            ? "measured"
            : "ai",
      });
    }),
  );
  const cpvChips = plan.candidate_cpv.map(({ code, label }) => {
    const key = tenderSearchChipKey("candidate_cpv", code);
    return makeChip("candidate_cpv", code, {
      confirmed: confirmedKeys.has(key) || userKeys.has(key),
      label,
      provenance: userKeys.has(key)
        ? "user"
        : isMeasuredChip("candidate_cpv", code, profile)
          ? "measured"
          : "ai",
    });
  });

  return uniqueChips([...textChips, ...cpvChips]);
}

export function findMissingMeasuredCandidates(
  plan: TenderSearchPlan,
  profile?: ComparableProcurementProfile | null,
  tombstoneKeys: Iterable<string> = [],
): MissingMeasuredCandidates {
  if (!profile) return { cpvs: [], terms: [] };

  const tombstones = new Set(tombstoneKeys);
  const presentTermValues = new Set(
    [...plan.include_terms, ...plan.synonyms].map(normalizeText),
  );
  const presentCpvValues = new Set(
    plan.candidate_cpv.map(({ code }) => normalizeCpv(code)),
  );

  const terms = profile.title_terms.items
    .slice(0, 20)
    .filter(({ term }) => !presentTermValues.has(normalizeText(term)))
    .map(({ term }) =>
      makeChip("include_terms", term, {
        confirmed: true,
        provenance: "measured",
      }),
    )
    .filter((chip) => !isTombstoned(chip, tombstones));

  const cpvs = profile.frequent_cpvs.items
    .slice(0, 20)
    .filter(({ code }) => !presentCpvValues.has(normalizeCpv(code)))
    .map(({ code, label }) =>
      makeChip("candidate_cpv", code, {
        confirmed: true,
        label,
        provenance: "measured",
      }),
    )
    .filter((chip) => !isTombstoned(chip, tombstones));

  return {
    cpvs: uniqueChips(cpvs),
    terms: uniqueChips(terms),
  };
}

export function findMissingMeasuredBuyers(
  plan: TenderSearchPlan,
  profile?: ComparableProcurementProfile | null,
  tombstoneKeys: Iterable<string> = [],
): TenderSearchChip[] {
  if (!profile) return [];
  const present = new Set(plan.buyers.map(normalizeText));
  const tombstones = new Set(tombstoneKeys);
  return uniqueChips(
    profile.buyers
      .slice(0, 20)
      .filter(({ buyer }) => !present.has(normalizeText(buyer)))
      .map(({ buyer }) =>
        makeChip("buyers", buyer, {
          confirmed: true,
          provenance: "measured",
        }),
      )
      .filter((chip) => !isTombstoned(chip, tombstones)),
  );
}

export function applyChipsToTenderSearchPlan(
  plan: TenderSearchPlan,
  chips: readonly TenderSearchChip[],
): TenderSearchPlan {
  const unique = uniqueChips(chips);
  const values = (category: TenderSearchChipCategory) =>
    unique
      .filter((chip) => chip.category === category)
      .map((chip) => chip.value);

  return {
    ...plan,
    buyers: values("buyers"),
    candidate_cpv: unique
      .filter((chip) => chip.category === "candidate_cpv")
      .map((chip) => ({
        code: normalizeCpv(chip.value),
        label: chip.label ?? chip.value,
      })),
    exclude_terms: values("exclude_terms"),
    geographies: values("geographies"),
    include_terms: values("include_terms"),
    synonyms: values("synonyms"),
  };
}

export function addMissingMeasuredCandidates(
  plan: TenderSearchPlan,
  profile?: ComparableProcurementProfile | null,
  tombstoneKeys: Iterable<string> = [],
): RegeneratedTenderSearchPlan {
  const existing = tenderSearchPlanToChips(plan, profile);
  const missing = findMissingMeasuredCandidates(plan, profile, tombstoneKeys);
  const chips = uniqueChips([...existing, ...missing.terms, ...missing.cpvs]);
  return {
    chips,
    plan: applyChipsToTenderSearchPlan(plan, chips),
  };
}

export function mergeRegeneratedTenderSearchPlan(
  regeneratedPlan: TenderSearchPlan,
  currentChips: readonly TenderSearchChip[],
  profile?: ComparableProcurementProfile | null,
  tombstoneKeys: Iterable<string> = [],
): RegeneratedTenderSearchPlan {
  const tombstones = new Set(tombstoneKeys);
  const regenerated = tenderSearchPlanToChips(regeneratedPlan, profile).filter(
    (chip) => !isTombstoned(chip, tombstones),
  );
  const retained = currentChips.filter(
    (chip) =>
      (chip.provenance === "user" || chip.confirmed) &&
      !isTombstoned(chip, tombstones),
  );
  const chips = uniqueChips([...regenerated, ...retained]);
  return {
    chips,
    plan: applyChipsToTenderSearchPlan(regeneratedPlan, chips),
  };
}
