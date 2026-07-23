import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  tenders: vi.fn(),
  summarizeTender: vi.fn(),
  suggest: vi.fn(),
  awards: vi.fn(),
  searches: vi.fn(),
  listSearchProfiles: vi.fn(),
  createSearch: vi.fn(),
  patchSearch: vi.fn(),
  deleteSearch: vi.fn(),
  runSearch: vi.fn(),
  listFeedback: vi.fn(),
  createFeedback: vi.fn(),
  removeFeedback: vi.fn(),
  feedbackDigest: vi.fn(),
  listWatches: vi.fn(),
  updateWatch: vi.fn(),
  watchItems: vi.fn(),
  reviewWatchItems: vi.fn(),
  dossiersList: vi.fn(),
  pin: vi.fn(),
  listPinned: vi.fn(),
  removePinned: vi.fn(),
  listReports: vi.fn(),
  generateReport: vi.fn(),
  getJob: vi.fn(),
}));

vi.mock("@oracle/api-client", () => {
  class ApiError extends Error {
    constructor(
      public status: number,
      public problem: { detail: string },
    ) {
      super(problem.detail);
    }
  }
  return {
    ApiError,
    api: {
      procurement: {
        tenders: mocks.tenders,
        summarizeTender: mocks.summarizeTender,
        suggest: mocks.suggest,
        awards: mocks.awards,
        searches: mocks.searches,
        createSearch: mocks.createSearch,
        patchSearch: mocks.patchSearch,
        deleteSearch: mocks.deleteSearch,
        runSearch: mocks.runSearch,
      },
      procurementSearchProfiles: {
        list: mocks.listSearchProfiles,
        listFeedback: mocks.listFeedback,
        createFeedback: mocks.createFeedback,
        removeFeedback: mocks.removeFeedback,
        feedbackDigest: mocks.feedbackDigest,
      },
      procurementSearchWatches: {
        list: mocks.listWatches,
        update: mocks.updateWatch,
        items: mocks.watchItems,
        reviewItems: mocks.reviewWatchItems,
      },
      dossiers: { list: mocks.dossiersList },
      dossierProcurement: {
        pin: mocks.pin,
        list: mocks.listPinned,
        remove: mocks.removePinned,
      },
      reports: {
        listDossier: mocks.listReports,
        generate: mocks.generateReport,
      },
      jobs: { get: mocks.getJob },
    },
  };
});

vi.mock("@/components/auth/auth-boundary", () => ({
  PermissionGate: ({ children }: { children: React.ReactNode }) => children,
}));
vi.mock("@/components/auth/auth-provider", () => ({
  useAuth: () => ({
    can: () => true,
  }),
}));

import { DossierProcurementSection } from "@/components/dossiers/dossier-procurement-section";
import { ProcurementAwardsPanel } from "./procurement-awards-panel";
import { ProcurementWorkspace } from "./procurement-workspace";

const dossier = {
  id: "dossier-1",
  title: "Expediente CATL",
  status: "active",
  updated_at: "2026-07-16T00:00:00Z",
};

const tender = {
  folder_id: "2026/123/ABC",
  title: "Suministro de baterías",
  summary_feed: "Contrato para suministro estratégico.",
  buyer: "Gobierno de Aragón",
  status: "Activa",
  cpv: ["31400000"],
  amount: 1200000,
  deadline: "2026-08-01",
  feed_updated_at: "2026-07-15T10:30:00Z",
  region: "Aragón",
  source_url: "https://contrataciondelestado.es/tender",
  is_active: true,
  llm_summary: "Resumen ya calculado.",
  llm_summary_model: "qwen3.5",
};

const tendersResponse = {
  cache_hit: false,
  cached_seconds: 0,
  filters: {},
  items: [tender],
  keywords: ["baterías"],
  limit: 25,
  offset: 0,
  total: 1,
};

describe("UI de contratación pública", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.tenders.mockResolvedValue(tendersResponse);
    mocks.searches.mockResolvedValue({ items: [] });
    mocks.listSearchProfiles.mockResolvedValue({ items: [] });
    mocks.listWatches.mockResolvedValue({ items: [] });
    mocks.watchItems.mockResolvedValue({ items: [] });
    mocks.listFeedback.mockResolvedValue({ items: [] });
    mocks.feedbackDigest.mockResolvedValue({
      profile_id: "profile-1",
      plan_version: 4,
      digest_hash: "digest-empty",
      new_feedback_count: 0,
      counts: { relevant: 0, not_relevant: 0 },
      reasons: {
        wrong_sector: 0,
        amount: 0,
        region: 0,
        buyer: 0,
        other: 0,
      },
      exclusion_candidates: { terms: [], cpvs: [] },
      reinforcement_candidates: { terms: [], cpvs: [] },
    });
    mocks.dossiersList.mockResolvedValue({
      data: [dossier],
      meta: { total: 1 },
    });
    mocks.pin.mockResolvedValue({ id: "pin-1", folder_id: tender.folder_id });
    mocks.suggest.mockResolvedValue({
      kind: "winner",
      suggestions: ["ITURRI, S.A."],
      cached_seconds: 300,
      cache_hit: false,
    });
    mocks.awards.mockResolvedValue({
      buyer_norm: "",
      cache_hit: false,
      cached_seconds: 0,
      company_norm: "iturri",
      total: 1,
      items: [
        {
          folder_id: "award/1",
          lot_id: "A41050113",
          title: "Servicio de emergencias",
          buyer: "Ayuntamiento de Zaragoza",
          winner: "Iturri",
          is_ute: true,
          award_amount: 300000,
          cpv: ["35100000"],
          status: "Adjudicada",
          award_date: "2026-05-10",
          source_url: "https://contrataciondelestado.es/award",
        },
      ],
    });
    mocks.listPinned.mockResolvedValue({
      data: [
        {
          id: "pin-1",
          tenant_id: "tenant-1",
          dossier_id: "dossier-1",
          kind: "tender",
          folder_id: tender.folder_id,
          snapshot: tender,
          source_url: tender.source_url,
          evidence_id: "evidence-1",
          pinned_by_user_id: "user-1",
          created_at: "2026-07-16T00:00:00Z",
          updated_at: "2026-07-16T00:00:00Z",
        },
      ],
    });
    mocks.removePinned.mockResolvedValue({ deleted: true, id: "pin-1" });
    mocks.listReports.mockResolvedValue({
      data: [],
      meta: { page: 1, size: 100, total: 0 },
    });
    mocks.getJob.mockResolvedValue({
      id: "job-competitive-1",
      status: "queued",
      stage: "queued",
      progress: 0,
      version: 1,
      retryable: true,
      cancel_requested: false,
    });
  });

  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it("muestra resultados de licitaciones, filtros y resumen LLM cacheado sin POST", async () => {
    render(<ProcurementWorkspace />);

    expect(
      await screen.findByText("Suministro de baterías"),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /mostrar filtros/i }));
    fireEvent.change(screen.getByLabelText("Términos de búsqueda"), {
      target: { value: "baterías, movilidad" },
    });
    fireEvent.change(screen.getByLabelText("CPV"), {
      target: { value: "31400000" },
    });
    fireEvent.change(screen.getByLabelText("Importe mínimo"), {
      target: { value: "100000" },
    });
    fireEvent.change(screen.getByLabelText("Órgano comprador"), {
      target: { value: "Gobierno de Aragón" },
    });
    fireEvent.click(screen.getByRole("button", { name: /^Buscar$/ }));

    await waitFor(() =>
      expect(mocks.tenders).toHaveBeenLastCalledWith(
        expect.objectContaining({
          keywords: "baterías, movilidad",
          cpv: "31400000",
          min_amount: 100000,
          buyer: "Gobierno de Aragón",
          scope: "active",
        }),
      ),
    );

    fireEvent.click(screen.getByRole("button", { name: /resumen/i }));
    expect(
      await screen.findByText("Resumen ya calculado."),
    ).toBeInTheDocument();
    expect(mocks.summarizeTender).not.toHaveBeenCalled();
  });

  it("expone el alcance real de Signal y no promete histórico aislado", async () => {
    render(<ProcurementWorkspace />);

    expect(
      await screen.findByText("Suministro de baterías"),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /mostrar filtros/i }));

    const scope = screen.getByRole("combobox", { name: "Ámbito temporal" });
    expect(
      within(scope).queryByRole("option", { name: "No activas" }),
    ).not.toBeInTheDocument();
    expect(
      within(scope).getByRole("option", { name: "Todo el índice disponible" }),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/no equivale a un archivo histórico completo/i),
    ).toBeInTheDocument();

    fireEvent.change(scope, { target: { value: "all" } });
    fireEvent.click(screen.getByRole("button", { name: /^Buscar$/ }));

    await waitFor(() =>
      expect(mocks.tenders).toHaveBeenLastCalledWith(
        expect.objectContaining({ scope: "all" }),
      ),
    );
    expect(
      screen.getByRole("button", { name: /guardar actual/i }),
    ).toBeDisabled();
    expect(
      screen.getByText(
        /solo conserva búsquedas guardadas de licitaciones activas/i,
      ),
    ).toBeInTheDocument();
  });

  it("muestra estado canónico y hace visible el estado desconocido", async () => {
    mocks.tenders.mockResolvedValue({
      ...tendersResponse,
      items: [
        { ...tender, folder_id: "open", canonical_status: "open" },
        {
          ...tender,
          folder_id: "unknown",
          title: "Estado sin contrato",
          canonical_status: "unknown",
        },
      ],
      total: 2,
    });

    render(<ProcurementWorkspace />);

    expect(await screen.findByText("Abierta")).toBeInTheDocument();
    expect(
      screen.getByText("Estado no confirmado por la fuente"),
    ).toBeInTheDocument();
  });

  it("explica con lenguaje claro los dos modos de búsqueda", async () => {
    vi.stubGlobal(
      "ResizeObserver",
      class ResizeObserverMock {
        observe() {}
        unobserve() {}
        disconnect() {}
      },
    );
    render(<ProcurementWorkspace />);

    expect(
      await screen.findByText("Suministro de baterías"),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("textbox", { name: "Términos de búsqueda" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("textbox", { name: "Descripción del tema" }),
    ).toBeInTheDocument();
    expect(screen.queryByText("Keywords CSV")).not.toBeInTheDocument();
    expect(screen.queryByText("Etiqueta semántica")).not.toBeInTheDocument();

    fireEvent.click(
      screen.getByRole("button", { name: "Ayuda sobre términos de búsqueda" }),
    );
    expect(await screen.findByText(/sepáralas con comas/i)).toBeInTheDocument();

    fireEvent.keyDown(document, { key: "Escape" });
    fireEvent.click(
      screen.getByRole("button", { name: "Ayuda sobre descripción del tema" }),
    );
    expect(
      await screen.findByText(/alternativa a los términos/i),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/se desactiva para no mezclar/i),
    ).toBeInTheDocument();
  });

  it("sugiere órganos compradores con debounce y conserva la escritura libre", async () => {
    mocks.suggest.mockResolvedValue({
      kind: "buyer",
      suggestions: ["Ayuntamiento de Soneja", "Ayuntamiento de Loriguilla"],
      cached_seconds: 300,
      cache_hit: false,
    });

    render(<ProcurementWorkspace />);

    expect(
      await screen.findByText("Suministro de baterías"),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /mostrar filtros/i }));
    const buyer = screen.getByRole("combobox", { name: "Órgano comprador" });
    fireEvent.change(buyer, { target: { value: "ayu" } });
    fireEvent.change(buyer, { target: { value: "ayunt" } });
    fireEvent.change(buyer, { target: { value: "ayunta" } });

    expect(
      await screen.findByRole("option", { name: "Ayuntamiento de Soneja" }),
    ).toBeInTheDocument();
    expect(mocks.suggest).toHaveBeenCalledTimes(1);
    expect(mocks.suggest).toHaveBeenCalledWith({
      q: "ayunta",
      kind: "buyer",
      limit: 8,
    });

    fireEvent.keyDown(buyer, { key: "ArrowDown" });
    fireEvent.keyDown(buyer, { key: "Enter" });
    expect(buyer).toHaveValue("Ayuntamiento de Soneja");

    fireEvent.change(buyer, { target: { value: "Órgano fuera de catálogo" } });
    fireEvent.click(screen.getByRole("button", { name: /^Buscar$/ }));
    await waitFor(() =>
      expect(mocks.tenders).toHaveBeenLastCalledWith(
        expect.objectContaining({ buyer: "Órgano fuera de catálogo" }),
      ),
    );
  });

  it("sugiere regiones observadas sin alterar su literal y mantiene texto libre", async () => {
    mocks.tenders.mockResolvedValue({
      ...tendersResponse,
      items: [{ ...tender, region: "Valencia/València" }],
    });

    render(<ProcurementWorkspace />);

    expect(
      await screen.findByText("Suministro de baterías"),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /mostrar filtros/i }));
    const region = screen.getByRole("combobox", { name: "Región" });
    fireEvent.focus(region);
    fireEvent.click(
      await screen.findByRole("option", { name: "Valencia/València" }),
    );
    expect(region).toHaveValue("Valencia/València");

    fireEvent.change(region, { target: { value: "Ámbito nuevo" } });
    expect(region).toHaveValue("Ámbito nuevo");
  });

  it("ordena por plazo solo la página cargada y declara el límite paginado", async () => {
    mocks.tenders.mockResolvedValue({
      ...tendersResponse,
      total: 80,
      offset: 25,
      items: [
        {
          ...tender,
          folder_id: "late",
          title: "Vence tarde",
          deadline: "2026-09-20",
        },
        { ...tender, folder_id: "unknown", title: "Sin plazo", deadline: null },
        {
          ...tender,
          folder_id: "early",
          title: "Vence pronto",
          deadline: "2026-07-25",
        },
      ],
    });

    render(<ProcurementWorkspace />);

    expect(await screen.findByText("Vence tarde")).toBeInTheDocument();
    fireEvent.change(
      screen.getByRole("combobox", {
        name: "Orden de los resultados cargados",
      }),
      { target: { value: "deadline_asc" } },
    );

    const titles = Array.from(
      document.querySelectorAll<HTMLElement>(
        ".procurement-card > header strong",
      ),
    ).map((node) => node.textContent);
    expect(titles).toEqual(["Vence pronto", "Vence tarde", "Sin plazo"]);
    expect(
      screen.getByText(
        /orden local sobre los 3 resultados cargados en esta página; no reordena los 80 resultados del corpus/i,
      ),
    ).toBeInTheDocument();
  });

  it("agrupa todas las acciones de una licitación en un único control", async () => {
    render(<ProcurementWorkspace />);

    expect(
      await screen.findByText("Suministro de baterías"),
    ).toBeInTheDocument();
    const actions = screen.getByRole("group", {
      name: "Acciones para Suministro de baterías",
    });
    expect(
      within(actions).getByRole("button", { name: "Resumen" }),
    ).toBeInTheDocument();
    expect(
      within(actions).getByRole("link", { name: "Ver fuente oficial" }),
    ).toBeInTheDocument();
    expect(
      within(actions).getByRole("button", { name: "Fijar" }),
    ).toBeInTheDocument();
  });

  it("gestiona estados vacíos y búsquedas guardadas", async () => {
    mocks.tenders.mockResolvedValueOnce({
      ...tendersResponse,
      items: [],
      total: 0,
    });
    mocks.searches.mockResolvedValue({
      items: [
        {
          id: "search-1",
          name: "Movilidad eléctrica",
          keywords: ["baterías"],
          filters: { active: true },
        },
      ],
    });
    mocks.createSearch.mockResolvedValue({ id: "search-2", name: "Actual" });
    mocks.runSearch.mockResolvedValue({
      search: { id: "search-1", name: "Movilidad eléctrica" },
      results: tendersResponse,
    });

    render(<ProcurementWorkspace />);

    expect(
      await screen.findByText("No hay licitaciones para estos criterios"),
    ).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Nombre"), {
      target: { value: "Actual" },
    });
    fireEvent.click(screen.getByRole("button", { name: /guardar actual/i }));
    await waitFor(() => expect(mocks.createSearch).toHaveBeenCalled());

    fireEvent.click(await screen.findByRole("button", { name: /ejecutar/i }));
    await waitFor(() =>
      expect(mocks.runSearch).toHaveBeenCalledWith("search-1", {
        limit: 25,
        offset: 0,
      }),
    );
  });

  it("correlaciona la búsqueda guardada por el wizard con su versión aceptada", async () => {
    mocks.searches.mockResolvedValue({
      items: [
        {
          id: "search-wizard-1",
          name: "Emergencias activas",
          keywords: ["extinción"],
          filters: { scope: "active" },
        },
      ],
    });
    mocks.listSearchProfiles.mockResolvedValue({
      items: [
        {
          id: "profile-1",
          tender_search_id: "search-wizard-1",
          version: 4,
        },
      ],
    });
    mocks.listWatches.mockResolvedValue({
      items: [
        {
          id: "watch-1",
          profile_id: "profile-1",
          tender_search_id: "search-wizard-1",
          name: "Emergencias activas",
          enabled: false,
          notifications_enabled: false,
          cadence_seconds: 900,
          new_count: 2,
          last_success_at: null,
          last_attempt_at: null,
          last_error_code: null,
          last_error_message: null,
          created_at: "2026-07-23T20:00:00Z",
          updated_at: "2026-07-23T20:00:00Z",
        },
      ],
    });

    render(<ProcurementWorkspace />);

    const searchName = await screen.findByText("Emergencias activas");
    const card = searchName.closest("article");
    expect(card).not.toBeNull();
    expect(within(card as HTMLElement).getByText("v4")).toBeInTheDocument();
    expect(
      within(card as HTMLElement).getByRole("button", {
        name: "Activar vigilancia y avisos",
      }),
    ).toBeInTheDocument();
  });

  it("registra feedback neutro sobre resultados correlacionados y permite deshacerlo", async () => {
    const search = {
      id: "search-wizard-1",
      name: "Emergencias activas",
      keywords: ["extinción"],
      filters: { scope: "active" },
    };
    const searchProfile = {
      id: "profile-1",
      tender_search_id: search.id,
      version: 4,
    };
    const feedback = {
      id: "feedback-1",
      profile_id: searchProfile.id,
      plan_version: 4,
      folder_id: tender.folder_id,
      verdict: "not_relevant",
      reason: "wrong_sector",
      note: null,
      tender: {
        title: tender.title,
        cpvs: tender.cpv,
      },
      created_at: "2026-07-23T20:00:00Z",
      updated_at: "2026-07-23T20:00:00Z",
    };
    mocks.searches.mockResolvedValue({ items: [search] });
    mocks.listSearchProfiles.mockResolvedValue({ items: [searchProfile] });
    mocks.runSearch.mockResolvedValue({
      search,
      results: tendersResponse,
    });
    mocks.createFeedback.mockResolvedValue(feedback);
    mocks.removeFeedback.mockResolvedValue({
      deleted: true,
      id: feedback.id,
    });
    mocks.feedbackDigest
      .mockResolvedValueOnce({
        profile_id: "profile-1",
        plan_version: 4,
        digest_hash: "digest-empty",
        new_feedback_count: 0,
        counts: { relevant: 0, not_relevant: 0 },
        reasons: {
          wrong_sector: 0,
          amount: 0,
          region: 0,
          buyer: 0,
          other: 0,
        },
        exclusion_candidates: { terms: [], cpvs: [] },
        reinforcement_candidates: { terms: [], cpvs: [] },
      })
      .mockResolvedValue({
        profile_id: "profile-1",
        plan_version: 4,
        digest_hash: "digest-feedback",
        new_feedback_count: 1,
        counts: { relevant: 0, not_relevant: 1 },
        reasons: {
          wrong_sector: 1,
          amount: 0,
          region: 0,
          buyer: 0,
          other: 0,
        },
        exclusion_candidates: {
          terms: [{ value: "baterías", count: 1 }],
          cpvs: [],
        },
        reinforcement_candidates: { terms: [], cpvs: [] },
      });

    render(<ProcurementWorkspace />);
    fireEvent.click(await screen.findByRole("button", { name: "Ejecutar" }));
    const feedbackGroup = await screen.findByRole("group", {
      name: "Valoración para Suministro de baterías",
    });
    fireEvent.click(
      within(feedbackGroup).getByRole("button", { name: "No relevante" }),
    );
    fireEvent.click(
      await screen.findByRole("button", { name: "Sector incorrecto" }),
    );

    await screen.findByText(
      "Lo tendremos en cuenta cuando pidas revisar el plan.",
    );
    expect(mocks.createFeedback).toHaveBeenCalledWith("profile-1", {
      plan_version: 4,
      folder_id: tender.folder_id,
      verdict: "not_relevant",
      reason: "wrong_sector",
      note: null,
      tender: {
        title: tender.title,
        cpvs: tender.cpv,
      },
    });
    expect(
      screen.getByText("1 feedback nuevos · 1 no relevantes · 0 relevantes"),
    ).toBeInTheDocument();
    expect(
      screen.getByText("Suministro de baterías").closest("article"),
    ).toHaveClass("has-feedback");

    fireEvent.click(screen.getByRole("button", { name: "Deshacer" }));
    await waitFor(() =>
      expect(mocks.removeFeedback).toHaveBeenCalledWith(
        "profile-1",
        "feedback-1",
      ),
    );
    expect(
      await screen.findByRole("group", {
        name: "Valoración para Suministro de baterías",
      }),
    ).toBeInTheDocument();
  });

  it("permite buscar adjudicaciones de actor y fijarlas a expediente", async () => {
    render(<ProcurementAwardsPanel />);

    fireEvent.change(screen.getByLabelText("Adjudicatario registral"), {
      target: { value: "Iturri" },
    });
    fireEvent.click(
      await screen.findByRole("option", { name: "ITURRI, S.A." }),
    );
    fireEvent.click(
      screen.getByRole("button", { name: /buscar adjudicaciones/i }),
    );

    expect(
      await screen.findByText("Servicio de emergencias"),
    ).toBeInTheDocument();
    expect(screen.getByText("Organismo licitador")).toBeInTheDocument();
    expect(screen.getByText("Ayuntamiento de Zaragoza")).toBeInTheDocument();
    expect(screen.getByText("Sin lote")).toBeInTheDocument();
    expect(screen.queryByText("A41050113")).not.toBeInTheDocument();
    expect(screen.getByText("UTE · En consorcio")).toBeInTheDocument();
    expect(mocks.suggest).toHaveBeenCalledWith({
      q: "Iturri",
      kind: "winner",
      limit: 8,
    });
    expect(mocks.awards).toHaveBeenCalledWith(
      expect.objectContaining({
        company: "ITURRI, S.A.",
        limit: 25,
        offset: 0,
      }),
    );

    expect(await screen.findByText("Expediente CATL")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /^Fijar$/ }));
    await waitFor(() =>
      expect(mocks.pin).toHaveBeenCalledWith("dossier-1", {
        kind: "award",
        folder_id: "award/1",
      }),
    );
  });

  it("lista y desfija referencias PLACSP desde el expediente", async () => {
    render(<DossierProcurementSection dossierId="dossier-1" />);

    expect(
      await screen.findByText("Suministro de baterías"),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /desfijar/i }));

    await waitFor(() =>
      expect(mocks.removePinned).toHaveBeenCalledWith("dossier-1", "pin-1"),
    );
  });

  it("muestra el organismo licitador y la UTE en adjudicaciones fijadas", async () => {
    mocks.listPinned.mockResolvedValue({
      data: [
        {
          id: "award-pin-1",
          tenant_id: "tenant-1",
          dossier_id: "dossier-1",
          kind: "award",
          folder_id: "award/ute-1",
          snapshot: {
            title: "Servicio de prevención",
            buyer: "Autoridad Portuaria de Barcelona",
            winner: "UTE PREVIPORT BCN 2026",
            is_ute: true,
            award_amount: 450000,
            award_date: "2026-06-10",
          },
          source_url: "https://contrataciondelestado.es/award/ute-1",
          evidence_id: "evidence-ute-1",
          pinned_by_user_id: "user-1",
          created_at: "2026-07-16T00:00:00Z",
          updated_at: "2026-07-16T00:00:00Z",
        },
      ],
    });

    render(<DossierProcurementSection dossierId="dossier-1" />);

    expect(
      await screen.findByText("Servicio de prevención"),
    ).toBeInTheDocument();
    expect(screen.getByText("Organismo licitador")).toBeInTheDocument();
    expect(
      screen.getAllByText("Autoridad Portuaria de Barcelona"),
    ).not.toHaveLength(0);
    expect(screen.getByText("UTE · En consorcio")).toBeInTheDocument();
  });

  it("encola inteligencia competitiva con la denominación fijada y estado durable", async () => {
    mocks.listPinned.mockResolvedValue({
      data: [
        {
          id: "award-pin-competitive",
          tenant_id: "tenant-1",
          dossier_id: "dossier-1",
          kind: "award",
          folder_id: "EMERGENCIACR2026/671",
          snapshot: {
            title: "Suministro de emergencia",
            buyer: "Consorcio de Emergencias",
            winner: "ITURRI, S.A",
            award_amount: 5000,
            award_date: "2026-07-01",
          },
          source_url: "https://contrataciondelestado.es/award/1",
          evidence_id: "evidence-award-1",
          pinned_by_user_id: "user-1",
          created_at: "2026-07-17T00:00:00Z",
          updated_at: "2026-07-17T00:00:00Z",
        },
      ],
    });
    mocks.generateReport.mockResolvedValue({
      report: {
        id: "report-competitive-1",
        dossier_id: "dossier-1",
        title: "Inteligencia competitiva",
        status: "draft",
        report_type: "competitive_procurement",
        template_key: "competitive_procurement",
        template_version: "v1",
        generation_version: 1,
        classification: "internal",
        confidentiality_label: "Uso interno",
        job_id: "job-competitive-1",
        parent_report_id: null,
        ready_at: null,
        reviewed_at: null,
        published_at: null,
        error_code: null,
        generation: null,
        version: 1,
        revision: null,
        artifacts: [],
        reviews: [],
        evidence: [],
        created_at: "2026-07-17T00:00:00Z",
        updated_at: "2026-07-17T00:00:00Z",
      },
      job_id: "job-competitive-1",
      replayed: false,
    });

    render(<DossierProcurementSection dossierId="dossier-1" />);

    expect(
      await screen.findByRole("combobox", {
        name: /adjudicatario a analizar/i,
      }),
    ).toHaveValue("ITURRI, S.A");
    fireEvent.click(
      screen.getByRole("button", { name: /inteligencia competitiva/i }),
    );

    await waitFor(() =>
      expect(mocks.generateReport).toHaveBeenCalledWith(
        "dossier-1",
        {
          template_key: "competitive_procurement",
          options: expect.objectContaining({
            company_name: "ITURRI, S.A",
            formats: ["html", "json"],
          }),
        },
        expect.stringMatching(/^competitive-procurement-dossier-1-/),
      ),
    );
    expect(
      await screen.findByText("Informe competitivo en segundo plano"),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/puedes salir de esta pantalla/i),
    ).toBeInTheDocument();
  });
});
