import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  tenders: vi.fn(),
  summarizeTender: vi.fn(),
  awards: vi.fn(),
  searches: vi.fn(),
  createSearch: vi.fn(),
  patchSearch: vi.fn(),
  deleteSearch: vi.fn(),
  runSearch: vi.fn(),
  dossiersList: vi.fn(),
  pin: vi.fn(),
  listPinned: vi.fn(),
  removePinned: vi.fn(),
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
        awards: mocks.awards,
        searches: mocks.searches,
        createSearch: mocks.createSearch,
        patchSearch: mocks.patchSearch,
        deleteSearch: mocks.deleteSearch,
        runSearch: mocks.runSearch,
      },
      dossiers: { list: mocks.dossiersList },
      dossierProcurement: {
        pin: mocks.pin,
        list: mocks.listPinned,
        remove: mocks.removePinned,
      },
    },
  };
});

vi.mock("@/components/auth/auth-boundary", () => ({
  PermissionGate: ({ children }: { children: React.ReactNode }) => children,
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
    mocks.dossiersList.mockResolvedValue({ data: [dossier], meta: { total: 1 } });
    mocks.pin.mockResolvedValue({ id: "pin-1", folder_id: tender.folder_id });
    mocks.awards.mockResolvedValue({
      buyer_norm: "",
      cache_hit: false,
      cached_seconds: 0,
      company_norm: "iturri",
      total: 1,
      items: [
        {
          folder_id: "award/1",
          lot_id: "1",
          title: "Servicio de emergencias",
          buyer: "Ayuntamiento de Zaragoza",
          winner: "Iturri",
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
  });

  afterEach(() => {
    cleanup();
  });

  it("muestra resultados de licitaciones, filtros y resumen LLM cacheado sin POST", async () => {
    render(<ProcurementWorkspace />);

    expect(await screen.findByText("Suministro de baterías")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /mostrar filtros/i }));
    fireEvent.change(screen.getByLabelText("Keywords CSV"), {
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
          active: true,
        }),
      ),
    );

    fireEvent.click(screen.getByRole("button", { name: /resumen/i }));
    expect(await screen.findByText("Resumen ya calculado.")).toBeInTheDocument();
    expect(mocks.summarizeTender).not.toHaveBeenCalled();
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
    await waitFor(() => expect(mocks.runSearch).toHaveBeenCalledWith("search-1", {
      limit: 25,
      offset: 0,
    }));
  });

  it("permite buscar adjudicaciones de actor y fijarlas a expediente", async () => {
    render(<ProcurementAwardsPanel />);

    fireEvent.change(screen.getByLabelText("Empresa"), {
      target: { value: "Iturri" },
    });
    fireEvent.click(screen.getByRole("button", { name: /buscar adjudicaciones/i }));

    expect(await screen.findByText("Servicio de emergencias")).toBeInTheDocument();
    expect(mocks.awards).toHaveBeenCalledWith(
      expect.objectContaining({ company: "Iturri", limit: 25, offset: 0 }),
    );

    fireEvent.click(await screen.findByRole("button", { name: /^Fijar$/ }));
    await waitFor(() =>
      expect(mocks.pin).toHaveBeenCalledWith("dossier-1", {
        kind: "award",
        folder_id: "award/1",
      }),
    );
  });

  it("lista y desfija referencias PLACSP desde el expediente", async () => {
    render(<DossierProcurementSection dossierId="dossier-1" />);

    expect(await screen.findByText("Suministro de baterías")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /desfijar/i }));

    await waitFor(() =>
      expect(mocks.removePinned).toHaveBeenCalledWith("dossier-1", "pin-1"),
    );
  });
});
