import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ProcurementSearchWizard } from "./procurement-search-wizard";

const mocks = vi.hoisted(() => ({
  latest: vi.fn(),
  run: vi.fn(),
  suggest: vi.fn(),
  suggestCpvs: vi.fn(),
  comparableProfile: vi.fn(),
  previewSearchPlan: vi.fn(),
  createProfile: vi.fn(),
  acceptProfile: vi.fn(),
  saveSearch: vi.fn(),
  getProfile: vi.fn(),
  replan: vi.fn(),
}));

vi.mock("@oracle/api-client", () => {
  class ApiError extends Error {
    constructor(
      public status: number,
      public problem: {
        detail: string;
        errors?: unknown;
      },
      public retryAfter?: number,
    ) {
      super(problem.detail);
    }
  }
  return {
    ApiError,
    api: {
      procurement: {
        suggest: mocks.suggest,
        suggestCpvs: mocks.suggestCpvs,
        comparableProfile: mocks.comparableProfile,
        previewSearchPlan: mocks.previewSearchPlan,
      },
      tenderSearchWizard: {
        latest: mocks.latest,
        run: mocks.run,
      },
      procurementSearchProfiles: {
        create: mocks.createProfile,
        accept: mocks.acceptProfile,
        saveSearch: mocks.saveSearch,
        get: mocks.getProfile,
        replan: mocks.replan,
      },
    },
  };
});

vi.mock("@/components/auth/auth-boundary", () => ({
  PermissionGate: ({ children }: { children: React.ReactNode }) => children,
}));

vi.mock("@/components/reporting/job-progress", () => ({
  JobProgress: () => <div>Trabajo en curso</div>,
}));

const basePlan = {
  intent_summary: "Equipamiento para emergencias públicas",
  include_terms: ["equipos de extinción"],
  synonyms: ["material contra incendios"],
  exclude_terms: ["formación"],
  candidate_cpv: [{ code: "35110000", label: "Equipo de extinción" }],
  buyers: ["Ayuntamiento de Sevilla"],
  geographies: [],
  scope: "active" as const,
  min_amount: null,
  max_amount: null,
  assumptions: ["Se buscan suministros y mantenimiento"],
  questions: ["¿Debe incluirse vestuario técnico?"],
  confidence: 72,
  discarded_count: 2,
  discarded_reasons: { invalid_cpv: 2 },
};

function artifact(id = "artifact-1", output: typeof basePlan = basePlan) {
  return {
    id,
    dossier_id: null,
    agent: "tender_search_wizard",
    schema_name: "tender_search_wizard",
    schema_version: "1",
    status: "valid",
    output,
    created_at: "2026-07-23T10:00:00Z",
    updated_at: "2026-07-23T10:00:00Z",
    version: 1,
  };
}

function comparable() {
  return {
    schema: "comparable-profile/v1",
    company_requested: "ITURRI",
    company_normalized_by_signal: "ITURRI S.A.",
    identity_basis: {
      legal_identity_verified: false,
      oracle_company_core: "iturri",
      oracle_normalized_name: "iturri",
    },
    measurement_contract: {
      dates_repaired: false,
      fields_used: ["winner"],
      llm_calls: 0,
      regions_inferred: false,
      source: "cached_awards",
      unit: "award",
    },
    corpus: {
      aggregated_contracts: 1251,
      analyzed_rows: 1251,
      ignored_rows_without_folder_id: 0,
      provider_total_rows: 1251,
      row_cap: 5000,
      truncated: false,
    },
    award_date_window: {
      invalid_date_examples: [],
      method: "observed",
      raw_observed_start: "2018-01-01",
      raw_observed_end: "2026-07-20",
      rows_with_invalid_date: 0,
      rows_with_valid_date: 1251,
      rows_without_date: 0,
    },
    frequent_cpvs: {
      contracts_with_normalized_cpv: 1251,
      contracts_with_taxonomy_label: 1251,
      contracts_without_normalized_cpv: 0,
      denominator_contracts: 1251,
      invalid_or_unrecognized: [],
      items: [
        {
          code: "35113400",
          contracts: 91,
          denominator_contracts: 1251,
          label: "Ropa de protección",
          raw_examples: ["35113400"],
          share_percent: "7.27",
          taxonomy_match: true,
        },
      ],
      method: "frequency",
      signal_format_observed: "list",
      taxonomy: {
        code_count: 9400,
        downloaded_at: "2026-07-01",
        language: "es",
        source_uri: "europa.eu",
        version: "2008",
      },
    },
    buyers: [
      {
        buyer: "UME",
        contract_share_percent: "5.0",
        contracts: 63,
        contracts_with_amount: 60,
        denominator_contracts: 1251,
        median_awarded_eur: "40000",
        total_awarded_eur: "2500000",
      },
    ],
    amount_distribution: {
      buckets: [],
      contracts_with_amount: 1000,
      contracts_without_amount: 251,
      denominator_contracts: 1251,
      maximum_awarded_eur: "900000",
      mean_awarded_eur: "50000",
      median_awarded_eur: "30000",
      minimum_awarded_eur: "1000",
      total_awarded_eur: "50000000",
    },
    title_terms: {
      contracts_with_terms: 1251,
      contracts_without_terms: 0,
      denominator_contracts: 1251,
      items: [
        {
          contracts: 120,
          denominator_contracts: 1251,
          share_percent: "9.59",
          term: "vehículo autobomba",
        },
      ],
      method: "frequency",
      method_version: "1",
    },
    ute_participation: {
      confidence: "high",
      denominator_contracts: 1251,
      method: "deterministic",
      parsed_ute_contracts: 0,
      status: 200,
      title: "UTE",
      type: "about:blank",
      partners: [],
    },
    cached_seconds: 0,
    cache_hit: false,
    measured_at: "2026-07-23T10:00:00Z",
  };
}

function profile(version = 1) {
  return {
    id: "profile-1",
    schema: "procurement-search-profile/v1",
    original_description: "Equipamiento de emergencias",
    comparables: ["ITURRI"],
    accepted_plan: basePlan,
    accepted_plan_hash: "hash",
    version,
    ai_artifact_id: "artifact-1",
    tender_search_id: null,
    accepted_by_user_id: "user-1",
    created_at: "2026-07-23T10:00:00Z",
    updated_at: "2026-07-23T10:00:00Z",
    last_accepted_at: "2026-07-23T10:00:00Z",
  };
}

function problem(status: number, detail: string, errors?: unknown) {
  return {
    code: status === 429 ? "rate_limit_exceeded" : "validation_error",
    detail,
    errors,
    instance: "/api/v1/procurement",
    request_id: "req-wizard-test",
    status,
    title: detail,
    type: "about:blank",
  };
}

async function openWizard() {
  render(<ProcurementSearchWizard />);
  fireEvent.click(screen.getByRole("button", { name: "Buscar con Oracle" }));
  await screen.findByRole("heading", {
    name: "Describe qué quieres encontrar",
  });
}

async function generatePlan() {
  fireEvent.change(
    screen.getByPlaceholderText(
      /Equipamiento y mantenimiento para emergencias/,
    ),
    { target: { value: "Equipamiento integral para emergencias públicas" } },
  );
  fireEvent.click(screen.getByRole("button", { name: "Generar propuesta" }));
  await screen.findByRole("heading", {
    name: "Revisa el plan antes de usarlo",
  });
}

describe("ProcurementSearchWizard", () => {
  beforeEach(() => {
    window.sessionStorage.clear();
    Object.values(mocks).forEach((mock) => mock.mockReset());
    mocks.latest.mockResolvedValue({
      artifact: null,
      input: null,
      job: null,
    });
    mocks.suggest.mockResolvedValue({ suggestions: [] });
    mocks.suggestCpvs.mockResolvedValue({
      query: "",
      limit: 8,
      cached_seconds: 0,
      items: [],
    });
    mocks.run.mockResolvedValue({
      artifact: artifact(),
      job: { id: "job-1" },
    });
    mocks.replan.mockResolvedValue({
      artifact: artifact("artifact-replan", {
        ...basePlan,
        exclude_terms: ["limpieza"],
      }),
      job: { id: "job-replan" },
    });
  });

  afterEach(() => cleanup());

  it("no genera al abrir y solo ilumina las acciones que invocan IA", async () => {
    await openWizard();

    expect(mocks.run).not.toHaveBeenCalled();
    expect(
      screen.getByRole("button", { name: "Generar propuesta" }),
    ).toHaveClass("vector-ai");
    expect(screen.getByRole("button", { name: "Cancelar" })).not.toHaveClass(
      "vector-ai",
    );

    await generatePlan();
    expect(mocks.run).toHaveBeenCalledTimes(1);
    expect(
      screen.getByRole("button", { name: "Aceptar plan" }),
    ).not.toHaveClass("vector-ai");
  });

  it("hace explícita la base medida omitida y conserva su procedencia", async () => {
    mocks.comparableProfile.mockResolvedValue(comparable());
    await openWizard();
    const comparableInput = screen.getByLabelText(
      "Empresa comparable (opcional)",
    );
    fireEvent.change(comparableInput, { target: { value: "ITURRI" } });
    fireEvent.keyDown(comparableInput, { key: "Enter" });
    await screen.findByText("1251 adjudicaciones");
    expect(screen.getByText(/^Perfil medido hace /)).toBeInTheDocument();

    await generatePlan();
    const measuredGap = screen.getByRole("region", {
      name: "Candidatos medidos omitidos",
    });
    expect(
      within(measuredGap).getByText(/1 términos y 1 CPV/),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Aceptar plan" })).toBeDisabled();

    fireEvent.click(
      within(measuredGap).getByRole("button", {
        name: "Incorporar base medida",
      }),
    );
    expect(screen.getByText("vehículo autobomba")).toBeInTheDocument();
    expect(
      screen.getByText("35113400 · Ropa de protección"),
    ).toBeInTheDocument();
    expect(screen.getAllByText("Medido").length).toBeGreaterThanOrEqual(2);
    expect(screen.getByRole("button", { name: "Aceptar plan" })).toBeEnabled();
  });

  it("usa la copia de sesión del comparable ante 429 sin reintentar", async () => {
    const { ApiError } = await import("@oracle/api-client");
    window.sessionStorage.setItem(
      "oracle:procurement-comparable:iturri",
      JSON.stringify({ profile: comparable(), savedAt: Date.now() }),
    );
    mocks.comparableProfile.mockRejectedValue(
      new ApiError(429, problem(429, "Límite horario"), 120),
    );
    await openWizard();
    const comparableInput = screen.getByLabelText(
      "Empresa comparable (opcional)",
    );
    fireEvent.change(comparableInput, { target: { value: "ITURRI" } });
    fireEvent.keyDown(comparableInput, { key: "Enter" });

    await screen.findByText(/copia conservada en esta sesión/);
    expect(mocks.comparableProfile).toHaveBeenCalledTimes(1);
    expect(screen.getByText("1251 adjudicaciones")).toBeInTheDocument();
  });

  it("regenera sin perder chips del usuario ni propuestas confirmadas", async () => {
    await openWizard();
    await generatePlan();

    fireEvent.click(
      screen.getByRole("button", {
        name: "Confirmar equipos de extinción",
      }),
    );
    fireEvent.change(screen.getByLabelText("Añadir término"), {
      target: { value: "rescate vertical" },
    });
    fireEvent.click(
      screen.getByRole("button", {
        name: "Añadir término al plan",
      }),
    );
    mocks.run.mockResolvedValueOnce({
      artifact: artifact("artifact-2", {
        ...basePlan,
        include_terms: ["nuevo término"],
      }),
      job: { id: "job-2" },
    });

    fireEvent.click(
      screen.getByRole("button", { name: "Regenerar propuesta" }),
    );
    await waitFor(() => expect(mocks.run).toHaveBeenCalledTimes(2));
    expect(screen.getByText("nuevo término")).toBeInTheDocument();
    expect(screen.getByText("equipos de extinción")).toBeInTheDocument();
    expect(screen.getByText("rescate vertical")).toBeInTheDocument();
    expect(screen.getByText("Usuario")).toBeInTheDocument();
    expect(screen.getByText("IA · confirmado")).toBeInTheDocument();
  });

  it("autocompleta CPV, etiqueta códigos válidos y descarta los inválidos", async () => {
    mocks.suggestCpvs.mockImplementation(async (query: string) => ({
      query,
      limit: 8,
      cached_seconds: 0,
      items:
        query === "35113400" || query === "ropa"
          ? [{ code: "35113400", label: "Ropa de protección" }]
          : [],
    }));
    await openWizard();
    await generatePlan();

    const cpvInput = screen.getByRole("combobox", {
      name: "Añadir CPV por código o descripción",
    });
    fireEvent.change(cpvInput, { target: { value: "ropa" } });
    fireEvent.click(
      await screen.findByRole("option", {
        name: "35113400 · Ropa de protección",
      }),
    );
    await screen.findByText("35113400 · Ropa de protección");
    expect(screen.getByText("Usuario")).toBeInTheDocument();

    fireEvent.change(cpvInput, { target: { value: "99999999" } });
    fireEvent.keyDown(cpvInput, { key: "Enter" });
    await screen.findByText(
      "CPV 99999999 descartado: no existe en la taxonomía CPV vigente.",
    );
  });

  it("previsualiza solo bajo petición y respeta el 429 sin reintentos", async () => {
    const { ApiError } = await import("@oracle/api-client");
    mocks.previewSearchPlan.mockRejectedValue(
      new ApiError(429, problem(429, "Demasiadas previsualizaciones"), 27),
    );
    await openWizard();
    await generatePlan();

    expect(mocks.previewSearchPlan).not.toHaveBeenCalled();
    fireEvent.click(
      screen.getByRole("button", { name: "Previsualizar ahora" }),
    );
    await screen.findByText(
      "Límite de previsualización alcanzado. No se reintentará automáticamente.",
    );
    expect(mocks.previewSearchPlan).toHaveBeenCalledTimes(1);
    expect(
      screen.getByRole("button", { name: "Disponible en 27s" }),
    ).toBeDisabled();
  });

  it("separa aceptar una versión de guardar la vigilancia activa", async () => {
    const onWatchSaved = vi.fn();
    mocks.createProfile.mockResolvedValue(profile());
    mocks.saveSearch.mockResolvedValue({
      profile: { ...profile(), tender_search_id: "search-1" },
      saved_search: { id: "search-1" },
    });
    render(<ProcurementSearchWizard onWatchSaved={onWatchSaved} />);
    fireEvent.click(screen.getByRole("button", { name: "Buscar con Oracle" }));
    await generatePlan();

    expect(mocks.createProfile).not.toHaveBeenCalled();
    expect(mocks.saveSearch).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Aceptar plan" }));
    await screen.findByText(/Plan aceptado · v1 ·/);
    expect(mocks.createProfile).toHaveBeenCalledTimes(1);
    expect(mocks.saveSearch).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "Guardar vigilancia" }));
    await screen.findByRole("button", { name: "Vigilancia guardada" });
    expect(mocks.saveSearch).toHaveBeenCalledTimes(1);
    expect(onWatchSaved).toHaveBeenCalledTimes(1);
  });

  it("declara el histórico no disponible y no ofrece vigilancia para todo el índice", async () => {
    mocks.createProfile.mockResolvedValue({
      ...profile(),
      accepted_plan: { ...basePlan, scope: "all" },
    });
    await openWizard();
    await generatePlan();

    expect(
      screen.getByRole("radio", { name: "Solo histórico (no disponible)" }),
    ).toBeDisabled();
    fireEvent.click(
      screen.getByRole("radio", { name: "Todo el índice disponible" }),
    );
    fireEvent.click(screen.getByRole("button", { name: "Aceptar plan" }));
    await screen.findByText(/Plan aceptado · v1 ·/);
    expect(
      screen.queryByRole("button", { name: "Guardar vigilancia" }),
    ).not.toBeInTheDocument();
    expect(
      screen.getByText(/solo puede guardarse para licitaciones activas/),
    ).toBeInTheDocument();
  });

  it("elimina chips por teclado y muestra 422 estructurado junto al plan", async () => {
    const { ApiError } = await import("@oracle/api-client");
    mocks.createProfile.mockRejectedValue(
      new ApiError(
        422,
        problem(422, "ESTE DETAIL NO DEBE MOSTRARSE", [
          {
            loc: ["accepted_plan", "candidate_cpv", 0, "code"],
            msg: "El CPV no existe en la taxonomía vigente",
            type: "value_error",
          },
        ]),
      ),
    );
    await openWizard();
    await generatePlan();

    fireEvent.keyDown(
      screen.getByRole("button", { name: "Eliminar formación" }),
      { key: "Delete" },
    );
    expect(screen.queryByText("formación")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Aceptar plan" }));
    await screen.findByText("Revisa los campos indicados por el servidor");
    expect(
      screen.getByText(/accepted_plan.candidate_cpv.0.code:/),
    ).toBeInTheDocument();
    expect(
      screen.getAllByText("El CPV no existe en la taxonomía vigente").length,
    ).toBeGreaterThanOrEqual(1);
    expect(
      screen.queryByText("ESTE DETAIL NO DEBE MOSTRARSE"),
    ).not.toBeInTheDocument();
    expect(
      screen.getByRole("combobox", {
        name: "Añadir CPV por código o descripción",
      }),
    ).toHaveAttribute("aria-invalid", "true");
  });

  it("reabre la última aceptación con versión, fecha y elección explícita", async () => {
    mocks.latest.mockResolvedValue({
      artifact: artifact(),
      input: {
        description: "Equipamiento integral para emergencias públicas",
        comparable: "ITURRI",
      },
      job: null,
      acceptance: {
        profile_id: "profile-1",
        version: 2,
        accepted_at: "2026-07-22T09:30:00Z",
      },
    });
    mocks.getProfile.mockResolvedValue(profile(2));
    await openWizard();

    expect(
      await screen.findByText("Aceptado como v2 el 22/07/2026"),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Revisar plan aceptado" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Regenerar propuesta" }),
    ).toHaveClass("vector-ai");
    expect(mocks.run).not.toHaveBeenCalled();

    fireEvent.click(
      screen.getByRole("button", { name: "Revisar plan aceptado" }),
    );
    await screen.findByText(/Plan aceptado · v2 · 23\/07\/2026/);
    expect(mocks.getProfile).toHaveBeenCalledWith("profile-1");
    expect(mocks.run).not.toHaveBeenCalled();
  });

  it("replanifica una vez, muestra el diff triple y acepta sobre el perfil exacto", async () => {
    mocks.getProfile.mockResolvedValue(profile(2));
    mocks.acceptProfile.mockResolvedValue(profile(3));
    render(
      <ProcurementSearchWizard
        replanRequest={{
          profileId: "profile-1",
          digestHash: "digest-1",
          requestKey: 1,
        }}
      />,
    );

    await screen.findByRole("heading", {
      name: "Revisa el plan antes de usarlo",
    });
    expect(mocks.replan).toHaveBeenCalledTimes(1);
    expect(mocks.replan).toHaveBeenCalledWith(
      "profile-1",
      {
        expected_version: 2,
        digest_hash: "digest-1",
      },
      "procurement-replan:profile-1:2:digest-1",
    );
    expect(mocks.run).not.toHaveBeenCalled();
    const diff = screen.getByRole("region", {
      name: "Cambios respecto a v2",
    });
    expect(within(diff).getByText("Añadido · 1")).toBeInTheDocument();
    expect(within(diff).getByText("Retirado · 1")).toBeInTheDocument();
    expect(within(diff).getByText(/Conservado ·/)).toBeInTheDocument();
    expect(within(diff).getByText("limpieza")).toBeInTheDocument();
    expect(within(diff).getByText("formación")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Aceptar como v3" }));
    await waitFor(() =>
      expect(mocks.acceptProfile).toHaveBeenCalledWith(
        "profile-1",
        expect.objectContaining({ expected_version: 2 }),
      ),
    );
  });
});
