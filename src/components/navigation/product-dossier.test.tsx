import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  get: vi.fn(),
  opportunities: vi.fn(),
  risks: vi.fn(),
  tasks: vi.fn(),
  decisions: vi.fn(),
}));

vi.mock("@oracle/api-client", () => ({
  ApiError: class ApiError extends Error {
    constructor(
      public status: number,
      public problem: { detail: string },
    ) {
      super(problem.detail);
    }
  },
  api: {
    dossiers: { get: mocks.get },
    opportunities: { list: mocks.opportunities },
    risks: { list: mocks.risks },
    tasks: { list: mocks.tasks },
    decisions: { list: mocks.decisions },
  },
}));

vi.mock("next/navigation", () => ({
  useParams: () => ({ id: "dossier-demo" }),
}));

vi.mock("@/components/dossiers/dossier-oracle-summary-panel", () => ({
  DossierOracleSummaryPanel: () => <div data-testid="oracle-summary" />,
}));

vi.mock("@/components/dossiers/dossier-context-panel", () => ({
  DossierContextPanel: () => <div data-testid="context-panel" />,
}));

vi.mock("@/components/ui/page-header", () => ({
  PageHeader: ({ title, description }: { title: string; description?: string }) => (
    <header>
      <h1>{title}</h1>
      {description ? <p>{description}</p> : null}
    </header>
  ),
}));

import { ProductDossier, SummaryList } from "./product-dossier";

const dossier = {
  id: "dossier-demo",
  title: "SV2 Demo · Nexus Ibérica Sistemas",
  status: "active",
  dossier_type: "market",
  strategic_goal: "Vigilar mercado energético",
  description: "Expediente demo",
  health_score: 50,
  opportunity_score: 0,
  risk_score: 0,
  updated_at: "2026-08-03T08:00:00Z",
};

describe("SummaryList", () => {
  afterEach(cleanup);

  it("muestra un vacío digno con invitación a crear, no un mensaje de permisos", () => {
    render(
      <SummaryList
        title="Oportunidades principales"
        href="/app/dossiers/d1/opportunities"
        items={[]}
        emptyTitle="Aún no hay oportunidades registradas"
        emptyDescription="Registra oportunidades o promueve una recomendación del Oráculo."
        ctaLabel="Abrir oportunidades"
      />,
    );
    expect(screen.getByRole("heading", { name: "Oportunidades principales" })).toBeVisible();
    expect(screen.getByText("Aún no hay oportunidades registradas")).toBeVisible();
    expect(screen.getByText(/promueve una recomendación del Oráculo/i)).toBeVisible();
    expect(screen.getByRole("link", { name: "Abrir oportunidades" })).toHaveAttribute(
      "href",
      "/app/dossiers/d1/opportunities",
    );
    expect(screen.queryByText("No hay elementos accesibles.")).not.toBeInTheDocument();
  });

  it("distingue error de carga de vacío real", () => {
    render(
      <SummaryList
        title="Riesgos principales"
        href="/app/dossiers/d1/risks"
        items={[]}
        state="error"
        errorMessage="403 Forbidden"
        emptyTitle="Aún no hay riesgos registrados"
        emptyDescription="Añade riesgos."
        ctaLabel="Abrir riesgos"
      />,
    );
    expect(screen.getByRole("alert")).toHaveTextContent("No se pudo cargar este panel");
    expect(screen.getByText("403 Forbidden")).toBeVisible();
    expect(screen.queryByText("Aún no hay riesgos registrados")).not.toBeInTheDocument();
  });

  it("lista elementos cuando hay datos de negocio", () => {
    render(
      <SummaryList
        title="Siguientes acciones"
        href="/app/dossiers/d1/tasks"
        items={[{ id: "t1", title: "Evaluar licitación", meta: "Alta · sin fecha" }]}
        emptyTitle="No hay siguientes acciones pendientes"
        emptyDescription="Crea tareas."
        ctaLabel="Abrir tareas"
      />,
    );
    expect(screen.getByText("Evaluar licitación")).toBeVisible();
    expect(screen.getByText("Alta · sin fecha")).toBeVisible();
    expect(screen.queryByText("No hay siguientes acciones pendientes")).not.toBeInTheDocument();
  });
});

describe("ProductDossier paneles de portada", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.get.mockResolvedValue(dossier);
    mocks.opportunities.mockResolvedValue({ data: [] });
    mocks.risks.mockResolvedValue({ data: [] });
    mocks.tasks.mockResolvedValue({ data: [] });
    mocks.decisions.mockResolvedValue({ data: [] });
  });

  afterEach(cleanup);

  it("carga entidades de negocio y muestra vacíos dignos cuando no hay filas", async () => {
    render(<ProductDossier />);

    expect(await screen.findByRole("heading", { name: dossier.title })).toBeVisible();
    await waitFor(() => {
      expect(mocks.opportunities).toHaveBeenCalledWith("dossier-demo", {
        page: 1,
        size: 10,
        sort: "-overall_score",
      });
      expect(mocks.risks).toHaveBeenCalled();
      expect(mocks.tasks).toHaveBeenCalled();
      expect(mocks.decisions).toHaveBeenCalled();
    });

    expect(screen.getByText("Aún no hay oportunidades registradas")).toBeVisible();
    expect(screen.getByText("Aún no hay riesgos registrados")).toBeVisible();
    expect(screen.getByText("No hay siguientes acciones pendientes")).toBeVisible();
    expect(screen.getByText("No hay decisiones registradas")).toBeVisible();
    expect(screen.queryByText("No hay elementos accesibles.")).not.toBeInTheDocument();
  });

  it("puebla paneles solo con entidades de negocio, no con el análisis", async () => {
    mocks.opportunities.mockResolvedValue({
      data: [
        {
          id: "opp-1",
          title: "Oportunidad formal de negocio",
          status: "identified",
          overall_score: 72,
        },
      ],
    });
    mocks.tasks.mockResolvedValue({
      data: [
        {
          id: "task-1",
          title: "Tarea formal",
          status: "open",
          priority: "high",
          due_date: null,
        },
        {
          id: "task-done",
          title: "Hecha",
          status: "done",
          priority: "low",
          due_date: null,
        },
      ],
    });

    render(<ProductDossier />);

    const opportunitiesPanel = await screen.findByRole("heading", {
      name: "Oportunidades principales",
    });
    const panel = opportunitiesPanel.closest("article");
    expect(panel).toBeTruthy();
    expect(within(panel as HTMLElement).getByText("Oportunidad formal de negocio")).toBeVisible();
    expect(within(panel as HTMLElement).getByText(/Puntuación 72/)).toBeVisible();

    expect(await screen.findByText("Tarea formal")).toBeVisible();
    expect(screen.queryByText("Hecha")).not.toBeInTheDocument();
  });

  it("muestra error de panel si la lista de negocio falla, sin fingir vacío de permisos", async () => {
    const { ApiError } = await import("@oracle/api-client");
    mocks.opportunities.mockRejectedValue(
      new ApiError(403, { detail: "Sin permiso de lectura" } as never),
    );

    render(<ProductDossier />);

    expect(await screen.findByText("No se pudo cargar este panel")).toBeVisible();
    expect(screen.getByText("Sin permiso de lectura")).toBeVisible();
    expect(screen.queryByText("No hay elementos accesibles.")).not.toBeInTheDocument();
    // Other panels still render their empty state
    expect(await screen.findByText("Aún no hay riesgos registrados")).toBeVisible();
  });
});
