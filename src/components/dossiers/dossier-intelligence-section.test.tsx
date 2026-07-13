import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  signalList: vi.fn(),
  signalReview: vi.fn(),
  signalPromote: vi.fn(),
  opportunityList: vi.fn(),
  opportunityEvidence: vi.fn(),
  opportunityUpdate: vi.fn(),
  opportunityCreate: vi.fn(),
  riskList: vi.fn(),
  riskEvidence: vi.fn(),
  riskUpdate: vi.fn(),
  riskCreate: vi.fn(),
  success: vi.fn(),
  replace: vi.fn(),
}));

vi.mock("@oracle/api-client", () => {
  class ApiError extends Error {
    constructor(
      public status: number,
      public problem: { detail: string; code?: string },
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
        create: mocks.opportunityCreate,
      },
      risks: {
        list: mocks.riskList,
        evidence: mocks.riskEvidence,
        update: mocks.riskUpdate,
        create: mocks.riskCreate,
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

import { ApiError } from "@oracle/api-client";
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
    mocks.signalPromote.mockResolvedValue({
      kind: "opportunity",
      resource: { id: "op-from-signal" },
    });
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
    mocks.opportunityCreate.mockResolvedValue({ id: "op-2" });
    mocks.riskList.mockResolvedValue({ data: [], meta: { page: 1, size: 25, total: 0 } });
    mocks.riskEvidence.mockResolvedValue({ data: [] });
    mocks.riskUpdate.mockResolvedValue({});
    mocks.riskCreate.mockResolvedValue({ id: "risk-1" });
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

  it("distingue una señal pendiente de triaje de una puntuación real", async () => {
    mocks.signalList.mockResolvedValue({
      data: [{
        ...signal,
        link: {
          ...signal.link,
          overall_score: 0,
          confidence: 0,
          scoring_state: "pending",
          why_it_matters: "",
        },
      }],
      meta: { page: 1, size: 25, total: 1 },
    });
    render(<DossierIntelligenceSection dossierId="dossier-1" kind="signals" />);

    expect((await screen.findAllByText("Sin puntuar"))[0]).toBeVisible();
    expect((await screen.findAllByText("Pendiente de triaje"))[0]).toBeVisible();
    fireEvent.click(
      screen.getAllByRole("button", {
        name: "Inspeccionar Publicada una nueva convocatoria",
      })[0],
    );
    expect(await screen.findByText("Pendiente de triaje automático.")).toBeVisible();
  });

  it("recarga y reintenta una revisión cuando el triaje avanzó", async () => {
    const refreshed = {
      ...signal,
      link: { ...signal.link, triage_version: 3, relevance: 85 },
    };
    mocks.signalList
      .mockResolvedValueOnce({ data: [signal], meta: { page: 1, size: 25, total: 1 } })
      .mockResolvedValueOnce({ data: [refreshed], meta: { page: 1, size: 25, total: 1 } });
    mocks.signalReview
      .mockRejectedValueOnce(
        new ApiError(409, {
          type: "about:blank",
          title: "Conflicto de versión",
          status: 409,
          detail: "La revisión de señal cambió.",
          code: "version_conflict",
          instance: "",
          request_id: "request-1",
        }),
      )
      .mockResolvedValueOnce({ ...refreshed.link, status: "reviewed" });

    render(<DossierIntelligenceSection dossierId="dossier-1" kind="signals" />);
    fireEvent.click(
      (await screen.findAllByRole("button", {
        name: "Inspeccionar Publicada una nueva convocatoria",
      }))[0],
    );
    const detail = await screen.findByRole("dialog", {
      name: "Publicada una nueva convocatoria",
    });
    fireEvent.click(within(detail).getByRole("button", { name: "Marcar revisada" }));
    fireEvent.click(screen.getByRole("button", { name: "Confirmar" }));

    await waitFor(() =>
      expect(mocks.signalReview).toHaveBeenNthCalledWith(
        2,
        "link-1",
        expect.objectContaining({ version: 3, relevance: 85, status: "reviewed" }),
      ),
    );
    expect(mocks.signalReview).toHaveBeenNthCalledWith(
      1,
      "link-1",
      expect.objectContaining({ version: 2, status: "reviewed" }),
    );
  });

  it("revisa y prepara una oportunidad desde una señal nueva", async () => {
    render(<DossierIntelligenceSection dossierId="dossier-1" kind="signals" />);
    fireEvent.click(
      (await screen.findAllByRole("button", {
        name: "Inspeccionar Publicada una nueva convocatoria",
      }))[0],
    );
    const detail = await screen.findByRole("dialog", {
      name: "Publicada una nueva convocatoria",
    });
    expect(within(detail).getByRole("link", { name: "Registrar actor" })).toHaveAttribute(
      "href",
      "/app/dossiers/dossier-1/actors?view=candidates&signal_id=signal-1",
    );
    fireEvent.click(within(detail).getByRole("button", { name: "Promover a oportunidad" }));

    await waitFor(() => expect(mocks.signalReview).toHaveBeenCalledWith(
      "link-1",
      expect.objectContaining({ status: "reviewed", version: 2 }),
    ));
    const promotion = await screen.findByRole("dialog", { name: "Promover a oportunidad" });
    fireEvent.change(within(promotion).getByLabelText("Título"), {
      target: { value: "Alianza industrial CATL-Stellantis" },
    });
    fireEvent.change(within(promotion).getByLabelText("Siguiente acción"), {
      target: { value: "Preparar reunión con compras" },
    });
    fireEvent.change(within(promotion).getByLabelText("Fecha objetivo"), {
      target: { value: "2026-07-20" },
    });
    fireEvent.click(within(promotion).getByRole("button", { name: "Crear recurso" }));

    await waitFor(() => expect(mocks.signalPromote).toHaveBeenCalledWith(
      "link-1",
      expect.objectContaining({
        kind: "opportunity",
        title: "Alianza industrial CATL-Stellantis",
        next_action: "Preparar reunión con compras",
        due_date: "2026-07-20",
        create_task: true,
      }),
      expect.any(String),
    ));
    expect(await screen.findByRole("link", { name: "Ver la oportunidad creada" })).toHaveAttribute(
      "href",
      "/app/dossiers/dossier-1/opportunities?selected=op-from-signal",
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

  it("crea una oportunidad manual con valoración humana inicial", async () => {
    render(<DossierIntelligenceSection dossierId="dossier-1" kind="opportunities" />);
    fireEvent.click(await screen.findByRole("button", { name: "Nueva oportunidad" }));
    fireEvent.change(screen.getByLabelText("Título"), { target: { value: "Acuerdo con fabricante" } });
    fireEvent.change(screen.getByLabelText("Descripción"), { target: { value: "Explorar alianza europea" } });
    fireEvent.change(screen.getByLabelText("Siguiente acción"), { target: { value: "Preparar contacto" } });
    fireEvent.click(screen.getByRole("button", { name: "Crear" }));

    await waitFor(() => expect(mocks.opportunityCreate).toHaveBeenCalledWith(
      "dossier-1",
      expect.objectContaining({
        title: "Acuerdo con fabricante",
        description: "Explorar alianza europea",
        next_action: "Preparar contacto",
        strategic_fit: 50,
        urgency: 50,
      }),
    ));
  });

  it("crea un riesgo manual con mitigación inicial", async () => {
    render(<DossierIntelligenceSection dossierId="dossier-1" kind="risks" />);
    fireEvent.click(await screen.findByRole("button", { name: "Nuevo riesgo" }));
    fireEvent.change(screen.getByLabelText("Título"), { target: { value: "Dependencia tecnológica" } });
    fireEvent.change(screen.getByLabelText("Mitigación inicial"), { target: { value: "Diversificar socios" } });
    fireEvent.click(screen.getByRole("button", { name: "Crear" }));

    await waitFor(() => expect(mocks.riskCreate).toHaveBeenCalledWith(
      "dossier-1",
      expect.objectContaining({
        title: "Dependencia tecnológica",
        mitigation: "Diversificar socios",
        impact: 50,
        likelihood: 50,
      }),
    ));
  });
});
