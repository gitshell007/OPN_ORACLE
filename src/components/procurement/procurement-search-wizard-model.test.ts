import type {
  ComparableProcurementProfile,
  TenderSearchPlan,
} from "@oracle/api-client";
import { describe, expect, it } from "vitest";

import {
  addMissingMeasuredCandidates,
  createUserTenderSearchChip,
  diffTenderSearchChips,
  findMissingMeasuredBuyers,
  findMissingMeasuredCandidates,
  mergeRegeneratedTenderSearchPlan,
  tenderSearchChipKey,
  tenderSearchPlanToChips,
} from "./procurement-search-wizard-model";

function plan(overrides: Partial<TenderSearchPlan> = {}): TenderSearchPlan {
  return {
    assumptions: [],
    buyers: [],
    candidate_cpv: [],
    confidence: 0.7,
    discarded_count: 0,
    discarded_reasons: {},
    exclude_terms: [],
    geographies: [],
    include_terms: [],
    intent_summary: "Equipamiento de emergencias",
    max_amount: null,
    min_amount: null,
    questions: [],
    scope: "active",
    synonyms: [],
    ...overrides,
  };
}

function profile(): ComparableProcurementProfile {
  return {
    measured_at: "2026-07-23T10:00:00Z",
    amount_distribution: {
      buckets: [],
      contracts_with_amount: 0,
      contracts_without_amount: 2,
      denominator_contracts: 2,
      maximum_awarded_eur: null,
      mean_awarded_eur: null,
      median_awarded_eur: null,
      minimum_awarded_eur: null,
      total_awarded_eur: null,
    },
    award_date_window: {
      invalid_date_examples: [],
      method: "raw",
      raw_observed_end: "2026-06-01",
      raw_observed_start: "2024-01-01",
      rows_with_invalid_date: 0,
      rows_with_valid_date: 2,
      rows_without_date: 0,
    },
    buyers: [
      {
        buyer: "Ayuntamiento de Sevilla",
        contract_share_percent: "50.0",
        contracts: 1,
        contracts_with_amount: 0,
        denominator_contracts: 2,
        median_awarded_eur: null,
        total_awarded_eur: null,
      },
    ],
    cache_hit: true,
    cached_seconds: 60,
    company_normalized_by_signal: "ITURRI",
    company_requested: "Iturri",
    corpus: {
      aggregated_contracts: 2,
      analyzed_rows: 2,
      ignored_rows_without_folder_id: 0,
      provider_total_rows: 2,
      row_cap: 2_000,
      truncated: false,
    },
    frequent_cpvs: {
      contracts_with_normalized_cpv: 2,
      contracts_with_taxonomy_label: 2,
      contracts_without_normalized_cpv: 0,
      denominator_contracts: 2,
      invalid_or_unrecognized: [],
      items: [
        {
          code: "35110000",
          contracts: 2,
          denominator_contracts: 2,
          label: "Equipo de extinción de incendios",
          raw_examples: ["35110000-8"],
          share_percent: "100.0",
          taxonomy_match: true,
        },
        {
          code: "34144210",
          contracts: 1,
          denominator_contracts: 2,
          label: "Vehículos de extinción de incendios",
          raw_examples: ["34144210"],
          share_percent: "50.0",
          taxonomy_match: true,
        },
      ],
      method: "primary_cpv",
      signal_format_observed: "XXXXXXXX",
      taxonomy: {
        code_count: 9_400,
        downloaded_at: "2026-07-01",
        language: "es",
        source_uri: "https://example.test/cpv",
        version: "2008",
      },
    },
    identity_basis: {
      legal_identity_verified: false,
      oracle_company_core: "ITURRI",
      oracle_normalized_name: "ITURRI",
    },
    measurement_contract: {
      dates_repaired: false,
      fields_used: ["title", "cpv", "buyer"],
      llm_calls: 0,
      regions_inferred: false,
      source: "Signal",
      unit: "expediente",
    },
    schema: "comparable-procurement-profile/v1",
    title_terms: {
      contracts_with_terms: 2,
      contracts_without_terms: 0,
      denominator_contracts: 2,
      items: [
        {
          contracts: 2,
          denominator_contracts: 2,
          share_percent: "100.0",
          term: "extinción",
        },
        {
          contracts: 1,
          denominator_contracts: 2,
          share_percent: "50.0",
          term: "vehículos",
        },
      ],
      method: "token_frequency",
      method_version: "v1",
    },
    ute_participation: {
      confidence: "high",
      denominator_contracts: 2,
      method: "winner_parser",
      parsed_ute_contracts: 0,
      partners: [],
      unparsed_ute_contracts: 0,
      ute_contracts: 0,
      ute_share_percent: "0.0",
      verified: true,
      warning: "",
    },
  };
}

describe("modelo del wizard de contratación", () => {
  it("calcula la procedencia con claves normalizadas sin confundir categorías", () => {
    const current = plan({
      buyers: ["AYUNTAMIENTO DE SEVILLA"],
      candidate_cpv: [
        { code: "35110000", label: "Equipo de extinción de incendios" },
      ],
      exclude_terms: ["extinción"],
      include_terms: ["Extincion", "respiración"],
    });
    const userKey = tenderSearchChipKey("include_terms", "respiración");

    const chips = tenderSearchPlanToChips(current, profile(), {
      userKeys: [userKey],
    });

    expect(
      chips.map(({ category, provenance, value }) => ({
        category,
        provenance,
        value,
      })),
    ).toEqual([
      {
        category: "include_terms",
        provenance: "measured",
        value: "Extincion",
      },
      {
        category: "include_terms",
        provenance: "user",
        value: "respiración",
      },
      {
        category: "exclude_terms",
        provenance: "ai",
        value: "extinción",
      },
      {
        category: "buyers",
        provenance: "measured",
        value: "AYUNTAMIENTO DE SEVILLA",
      },
      {
        category: "candidate_cpv",
        provenance: "measured",
        value: "35110000",
      },
    ]);
  });

  it("detecta top medidos ausentes y los une una sola vez respetando tombstones", () => {
    const current = plan({
      candidate_cpv: [{ code: "35110000", label: "Equipo de extinción" }],
      synonyms: ["EXTINCION"],
    });
    const removedCpv = tenderSearchChipKey("candidate_cpv", "34144210");

    const missing = findMissingMeasuredCandidates(current, profile(), [
      removedCpv,
    ]);
    const union = addMissingMeasuredCandidates(current, profile(), [
      removedCpv,
    ]);

    expect(missing.terms.map(({ value }) => value)).toEqual(["vehículos"]);
    expect(missing.cpvs).toEqual([]);
    expect(union.plan.include_terms).toEqual(["vehículos"]);
    expect(union.plan.synonyms).toEqual(["EXTINCION"]);
    expect(union.plan.candidate_cpv).toHaveLength(1);
    expect(findMissingMeasuredBuyers(current, profile())).toMatchObject([
      {
        category: "buyers",
        provenance: "measured",
        value: "Ayuntamiento de Sevilla",
      },
    ]);
  });

  it("al regenerar conserva chips del usuario y confirmados sin revivir eliminados", () => {
    const oldPlan = plan({
      include_terms: ["espuma", "rescate", "sirenas"],
    });
    const userKey = tenderSearchChipKey("include_terms", "espuma");
    const confirmedKey = tenderSearchChipKey("include_terms", "rescate");
    const removedKey = tenderSearchChipKey("include_terms", "sirenas");
    const currentChips = tenderSearchPlanToChips(oldPlan, profile(), {
      confirmedKeys: [confirmedKey],
      userKeys: [userKey],
    });
    currentChips.push(
      createUserTenderSearchChip("geographies", "Castilla y León"),
    );
    const regenerated = plan({
      include_terms: ["sirenas", "vehículos"],
      synonyms: ["vehiculos"],
    });

    const merged = mergeRegeneratedTenderSearchPlan(
      regenerated,
      currentChips,
      profile(),
      [removedKey],
    );

    expect(merged.plan.include_terms).toEqual([
      "vehículos",
      "espuma",
      "rescate",
    ]);
    expect(merged.plan.synonyms).toEqual([]);
    expect(merged.plan.geographies).toEqual(["Castilla y León"]);
    expect(merged.chips.find(({ value }) => value === "espuma")).toMatchObject({
      confirmed: true,
      provenance: "user",
    });
    expect(merged.chips.some(({ value }) => value === "sirenas")).toBe(false);
  });

  it("clasifica el diff normalizado como añadido, retirado y conservado", () => {
    const accepted = [
      createUserTenderSearchChip("include_terms", "Rescate aéreo"),
      createUserTenderSearchChip(
        "candidate_cpv",
        "35113400",
        "Ropa de protección",
      ),
      createUserTenderSearchChip("buyers", "UME"),
    ];
    const proposed = [
      createUserTenderSearchChip("include_terms", "rescate aéreo"),
      createUserTenderSearchChip("exclude_terms", "limpieza"),
      createUserTenderSearchChip("buyers", "Ayuntamiento de Sevilla"),
    ];

    const diff = diffTenderSearchChips(accepted, proposed);

    expect(diff.map(({ change, chip }) => `${change}:${chip.key}`)).toEqual([
      "added:exclude_terms:limpieza",
      "added:buyers:ayuntamiento de sevilla",
      "removed:candidate_cpv:35113400",
      "removed:buyers:ume",
      "retained:include_terms:rescate aereo",
    ]);
    expect(
      diff.find(({ change }) => change === "retained")?.chip.provenance,
    ).toBe("user");
  });
});
