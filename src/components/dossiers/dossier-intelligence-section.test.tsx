import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  signalList: vi.fn(),
  signalReview: vi.fn(),
  signalPromote: vi.fn(),
  opportunityList: vi.fn(),
  opportunityEvidence: vi.fn(),
  opportunityUpdate: vi.fn(),
  riskList: vi.fn(),
  riskEvidence: vi.fn(),
  riskUpdate: vi.fn(),
  success: vi.fn(),
  replace: vi.fn(),
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
      dossierSignals: {
        list: mocks.signalList,
        review: mocks.signalReview,
        promote: mocks.signalPromote,
      },
      opportunities: {
        list: mocks.opportunityList,
        evidence: mocks.opportunityEvidence,
        update: mocks.opportunityUpdate,
      },
      risks: {
        list: mocks.riskList,
        evidence: mocks.riskEvidence,
        update: mocks.riskUpdate,
      },
    },
  };
});

vi.mock("sonner", () => ({ toast: { success: mocks.success } }));
vi.mock("next/navigation", () => ({
  usePathname: () => "/app/dossiers/dossier-1/signals",
  useRouter: () => ({ replace: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
}));
vi.mock("@/components/auth/auth-boundary", () => ({
  PermissionGate: ({ children }: { children: React.ReactNode }) => children,
}));
vi.mock("next/navigation", () => ({
  usePathname: () => "/app/dossiers/dossier-1/signals",
  useRouter: () => ({ replace: mocks.replace }),
  useSearchParams: () => new URLSearchParams(),
}));

import { DossierIntelligenceSection } from "./dossier-intelligence-section";

const signal = {
  link: {
    id: "link-1",
    tenant_id: "tenant-1",
    dossier_id: "dossier-1",
    signal_id: "signal-1",
    status: "new",
    relevance: 82,
    novelty: 70,
    confidence: 76,
    strategic_impact: 88,
    overall_score: 81,
    triage_version: 2,
    updated_at: "2026-07-11T09:00:00Z",
    why_it_matters: "Puede adelantar el siguiente hito.",
  },
  signal: {
    id: "signal-1",
    tenant_id: "tenant-1",
    title: "Publicada una nueva convocatoria",
    summary: "La fuente oficial abre un plazo de presentación.",
    source_name: "Boletín de Arcadia",
    source_type: "official_publication",
    source_url: "https://example.test/fuente",
    published_at: "2026-07-11T08:00:00Z",
  },
};

const opportunity = {
  id: "op-1",
  tenant_id: "tenant-1",
  dossier_id: "dossier-1",
  title: "Alianza de distribución",
  status: "identified",
  overall_score: 84,
  score_details: { confidence: 72, strategic_fit: 90 },
  version: 4,
  updated_at: "2026-07-11T09:00:00Z",
};

describe("DossierIntelligenceSection", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.signalList.mockResolvedValue({
      data: [signal],
      meta: { page: 1, size: 25, total: 1 },
    });
    mocks.signalReview.mockResolvedValue({ ...signal.link, status: "reviewed" });
    mocks.opportunityList.mockResolvedValue({
      data: [opportunity],
      meta: { page: 1, size: 25, total: 1 },
    });
    mocks.opportunityEvidence.mockResolvedValue({
      data: [
        {
          id: "evidence-1",
          tenant_id: "tenant-1",
          extract: "La entidad busca socios regionales.",
          classification: "public",
        },
      ],
      meta: { page: 1, size: 25, total: 1 },
    });
    mocks.opportunityUpdate.mockResolvedValue({
      ...opportunity,
      status: "qualified",
      version: 5,
    });
    mocks.riskList.mockResolvedValue({ data: [], meta: { page: 1, size: 25, total: 0 } });
    mocks.riskEvidence.mockResolvedValue({ data: [] });
    mocks.riskUpdate.mockResolvedValue({});
  });

  afterEach(cleanup);

  it("muestra fuente, confianza y revisa una señal con versión de triage", async () => {
    render(<DossierIntelligenceSection dossierId="dossier-1" kind="signals" />);

    expect((await screen.findAllByText("Publicada una nueva convocatoria"))[0]).toBeVisible();
    fireEvent.click(
      screen.getAllByRole("button", {
        name: "Inspeccionar Publicada una nueva convocatoria",
      })[0],
    );
    const detail = await screen.findByRole("dialog", {
      name: "Publicada una nueva convocatoria",
    });
    expect(within(detail).getByText("Boletín de Arcadia")).toBeVisible();
    expect(within(detail).getByText("76 %")).toBeVisible();
    fireEvent.click(within(detail).getByRole("button", { name: "Marcar revisada" }));
    fireEvent.click(screen.getByRole("button", { name: "Confirmar" }));

    await waitFor(() =>
      expect(mocks.signalReview).toHaveBeenCalledWith(
        "link-1",
        expect.objectContaining({
          status: "reviewed",
          version: 2,
          relevance: 82,
          confidence: 76,
        }),
      ),
    );
  });

  it("carga evidencia y aplica una transición permitida con versión", async () => {
    render(
      <DossierIntelligenceSection dossierId="dossier-1" kind="opportunities" />,
    );

    expect((await screen.findAllByText("Alianza de distribución"))[0]).toBeVisible();
    fireEvent.click(
      screen.getAllByRole("button", {
        name: "Inspeccionar Alianza de distribución",
      })[0],
    );
    expect(await screen.findByText("La entidad busca socios regionales.")).toBeVisible();
    fireEvent.change(screen.getByLabelText("Siguiente estado permitido"), {
      target: { value: "qualified" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Actualizar estado" }));
    fireEvent.click(screen.getByRole("button", { name: "Confirmar" }));

    await waitFor(() =>
      expect(mocks.opportunityUpdate).toHaveBeenCalledWith(
        "op-1",
        { status: "qualified", version: 4 },
        4,
      ),
    );
  });

  it("aplica búsqueda, estado y score como filtros server-side", async () => {
    render(<DossierIntelligenceSection dossierId="dossier-1" kind="signals" />);
    await screen.findAllByText("Publicada una nueva convocatoria");

    fireEvent.change(screen.getByPlaceholderText("Buscar señales…"), {
      target: { value: "  convocatoria " },
    });
    fireEvent.change(screen.getByLabelText("Estado"), {
      target: { value: "reviewed" },
    });
    fireEvent.change(screen.getByLabelText("Puntuación mínima"), {
      target: { value: "70" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Aplicar" }));

    await waitFor(() =>
      expect(mocks.signalList).toHaveBeenLastCalledWith("dossier-1", {
        page: 1,
        size: 25,
        status: "reviewed",
        search: "convocatoria",
        scoreMin: 70,
      }),
    );
  });
});
