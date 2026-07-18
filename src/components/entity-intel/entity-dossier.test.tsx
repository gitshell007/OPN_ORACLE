import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  push: vi.fn(),
  dossier: vi.fn(),
  registry: vi.fn(),
  suggest: vi.fn(),
  graph: vi.fn(),
  reports: vi.fn(),
  startReport: vi.fn(),
  incorporateReport: vi.fn(),
  dossiersList: vi.fn(),
  attachActor: vi.fn(),
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: mocks.push }),
}));

vi.mock("@oracle/api-client", () => {
  class ApiError extends Error {
    constructor(public problem: { detail: string }) {
      super(problem.detail);
    }
  }
  return {
    ApiError,
    api: {
      actors: {
        attach: mocks.attachActor,
      },
      dossiers: {
        list: mocks.dossiersList,
      },
      entityIntel: {
        dossier: mocks.dossier,
        registry: mocks.registry,
        suggest: mocks.suggest,
        graph: mocks.graph,
        reports: mocks.reports,
        startReport: mocks.startReport,
        incorporateReport: mocks.incorporateReport,
      },
    },
  };
});

vi.mock("@/components/auth/auth-boundary", () => ({
  PermissionGate: ({ children }: { children: ReactNode }) => <>{children}</>,
}));

vi.mock("@/components/reporting/job-progress", () => ({
  JobProgress: ({ label, onTerminal }: { label?: string; onTerminal?: (job: unknown) => void }) => (
    <button type="button" onClick={() => onTerminal?.({ status: "succeeded" })}>
      {label || "Proceso"}
    </button>
  ),
}));

vi.mock("cytoscape", () => ({ default: Object.assign(vi.fn(() => ({
  destroy: vi.fn(),
  elements: vi.fn(() => ({ removeClass: vi.fn(), not: vi.fn(() => ({ addClass: vi.fn() })) })),
  on: vi.fn(),
  removeListener: vi.fn(),
})), { use: vi.fn() }) }));
vi.mock("cytoscape-fcose", () => ({ default: vi.fn() }));

import { EntityDossier } from "./entity-dossier";

const dossierResponse = {
  entity: { name: "IBERDROLA CLIENTES ESPAÑA SOCIEDAD ANONIMA", type: "company" },
  sections: {
    registry: {
      ok: true,
      data: {
        query: "IBERDROLA",
        total: 3,
        profile: {
          status: "activa",
          constitution_date: "2001-02-03",
          provinces: ["BIZKAIA", "MADRID"],
          total_acts: 3,
          first_act_date: "2001-02-10",
          last_act_date: "2026-07-01",
        },
        items: [
          {
            person: "BURGOS CANTO MIGUEL",
            role: "Administrador",
            action: "nombramiento",
            date: "2026-07-01",
            province: "BIZKAIA",
            source_url: "https://boe.test/1",
          },
          {
            person: "PEREZ LOPEZ ANA",
            role: "Consejera",
            action: "cese",
            date: "2025-01-01",
            province: "MADRID",
            source_url: "https://boe.test/2",
          },
          {
            person: "PEREZ LOPEZ ANA",
            role: "Consejera",
            action: "nombramiento",
            date: "2019-01-01",
            province: "MADRID",
            source_url: "https://boe.test/3",
          },
        ],
        cached_seconds: 600,
        cache_hit: false,
      },
    },
    graph: {
      ok: false,
      error: "Grafo deshabilitado en Signal.",
    },
    news: {
      ok: true,
      data: {
        items: [{ title: "Noticia relevante", source: "Medio", url: "https://news.test" }],
      },
    },
  },
  cached_seconds: 600,
  cache_hit: false,
};

const waitingReportOutput = {
  title: "Informe de entidad en espera",
  executive_summary: "La entidad presenta actividad registral reciente y fuentes citables.",
  confidence: 82,
  facts: [],
  inferences: [],
  recommendations: [],
  open_questions: ["Confirmar homónimos antes de decidir."],
  warnings: ["Las fechas BORME son fechas de publicación."],
  sections: [
    {
      heading: "Perfil registral",
      paragraphs: [
        {
          text: "Consta un nombramiento publicado en BORME.",
          kind: "fact",
          confidence: 86,
          evidence_ids: ["evidence-1"],
        },
      ],
    },
  ],
  source_index: [{ evidence_id: "evidence-1", label: "BORME", locator: "boe" }],
};

const pendingEvidenceSources = [
  {
    id: "evidence-1",
    label: "BORME · 2026-07-01 · nombramiento",
    source_kind: "registry_act",
    source_url: "https://www.boe.es/borme/dias/2026/07/01/",
    extract: "Acto BORME: nombramiento. Fecha de publicación: 2026-07-01.",
  },
];

describe("EntityDossier", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.dossier.mockResolvedValue(dossierResponse);
    mocks.suggest.mockResolvedValue({ suggestions: [], kind: "company", cached_seconds: 600, cache_hit: false });
    mocks.registry.mockResolvedValue({ items: [], total: 0, cached_seconds: 600, cache_hit: false });
    mocks.graph.mockResolvedValue({ nodes: [], edges: [], truncated: false, cached_seconds: 600, cache_hit: false });
    mocks.reports.mockResolvedValue({ data: [] });
    mocks.startReport.mockResolvedValue({
      job_id: "job-1",
      job: { id: "job-1", status: "queued", result: {}, version: 1 },
    });
    mocks.incorporateReport.mockResolvedValue({
      report: { id: "report-1", title: "Informe de entidad" },
      job: { id: "job-1", status: "succeeded", result: { incorporated_report_id: "report-1" }, version: 2 },
    });
    mocks.dossiersList.mockResolvedValue({
      data: [{ id: "dossier-1", title: "Expediente ITURRI", updated_at: "2026-07-17" }],
    });
    mocks.attachActor.mockResolvedValue({ id: "link-1" });
  });

  afterEach(cleanup);

  it("muestra cabecera de perfil y límites de fuente", async () => {
    render(<EntityDossier name="IBERDROLA" type="company" />);

    expect(await screen.findByText("IBERDROLA CLIENTES ESPAÑA SOCIEDAD ANONIMA")).toBeInTheDocument();
    expect(screen.getByText("activa")).toBeInTheDocument();
    expect(screen.getByText(/Constitución:/)).toBeInTheDocument();
    expect(screen.getByText(/Las fechas son de publicación en BORME/i)).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Noticias" })).toBeInTheDocument();
  });

  it("muestra degradación de grafo sin tumbar el resto", async () => {
    render(<EntityDossier name="IBERDROLA" type="company" />);

    fireEvent.click(await screen.findByRole("tab", { name: "Grafo" }));

    expect(screen.getByText("Grafo deshabilitado en Signal.")).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Perfil" })).toBeInTheDocument();
  });

  it("diferencia activos y cesados y filtra por activos", async () => {
    render(<EntityDossier name="IBERDROLA" type="company" />);

    fireEvent.click(await screen.findByRole("tab", { name: "Órganos y cargos" }));

    expect(screen.getByText("BURGOS CANTO MIGUEL")).toBeInTheDocument();
    expect(screen.getAllByText("PEREZ LOPEZ ANA")).toHaveLength(2);
    expect(screen.getAllByText("Cesado")).toHaveLength(2);

    fireEvent.click(screen.getByLabelText("Solo activos"));

    expect(screen.getByText("BURGOS CANTO MIGUEL")).toBeInTheDocument();
    expect(screen.queryByText("PEREZ LOPEZ ANA")).not.toBeInTheDocument();
  });

  it("ordena cronológicamente por defecto y permite filtrar la tabla de cargos", async () => {
    render(<EntityDossier name="IBERDROLA" type="company" />);

    fireEvent.click(await screen.findByRole("tab", { name: "Órganos y cargos" }));

    const rows = await screen.findAllByRole("row");
    expect(rows[1]).toHaveTextContent("BURGOS CANTO MIGUEL");

    fireEvent.click(screen.getByRole("button", { name: /Publicación BORME, orden descendente/i }));
    await waitFor(() => {
      const sortedRows = screen.getAllByRole("row");
      expect(sortedRows[1]).toHaveTextContent("PEREZ LOPEZ ANA");
      expect(sortedRows[1]).toHaveTextContent("2019");
    });

    fireEvent.change(screen.getByLabelText("Filtrar tabla de actos"), { target: { value: "BIZKAIA" } });

    expect(screen.getByText("BURGOS CANTO MIGUEL")).toBeInTheDocument();
    expect(screen.queryByText("PEREZ LOPEZ ANA")).not.toBeInTheDocument();
  });

  it("materializa la entidad de Signal como actor interno al vincularla a un expediente", async () => {
    render(<EntityDossier name="IBERDROLA" type="company" />);

    expect(await screen.findByText("Expediente ITURRI")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /Añadir actor/i }));

    await waitFor(() => expect(mocks.attachActor).toHaveBeenCalledWith(
      "dossier-1",
      expect.objectContaining({
        actor_type: "organization",
        canonical_name: "IBERDROLA CLIENTES ESPAÑA SOCIEDAD ANONIMA",
        roles: ["Entidad Signal"],
        tags: ["signal", "entity-intel"],
        provenance: expect.objectContaining({
          source: "signal_entity_intel",
          entity_kind: "company",
          source_name: "IBERDROLA CLIENTES ESPAÑA SOCIEDAD ANONIMA",
        }),
      }),
    ));
    expect(await screen.findByText(/Entidad vinculada al expediente/i)).toBeInTheDocument();
  });

  it("lanza el informe IA de entidad con idempotency-key de intento", async () => {
    render(<EntityDossier name="IBERDROLA" type="company" />);

    fireEvent.click(await screen.findByRole("button", { name: /^Informe de la entidad$/i }));

    await waitFor(() => expect(mocks.startReport).toHaveBeenCalledWith(
      { name: "IBERDROLA CLIENTES ESPAÑA SOCIEDAD ANONIMA", type: "company" },
      expect.stringMatching(/^entity-report:company:/),
    ));
    expect(await screen.findByText(/Informe encolado/i)).toBeInTheDocument();
  });

  it("previsualiza un informe en espera sin incorporarlo", async () => {
    mocks.reports.mockResolvedValue({
      data: [
        {
          id: "job-new",
          status: "succeeded",
          result: {
            output: waitingReportOutput,
            pending_evidence_sources: pendingEvidenceSources,
          },
          version: 1,
        },
        {
          id: "job-old",
          status: "succeeded",
          result: { incorporated_report_id: "report-old", output: { title: "Informe viejo" } },
          version: 1,
        },
      ],
    });
    render(<EntityDossier name="IBERDROLA" type="company" />);

    expect(await screen.findByText(/Informe en espera, todavía no incorporado/i)).toBeInTheDocument();
    expect(screen.queryByText(/biblioteca de informes/i)).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Ver informe en espera" }));

    expect(await screen.findByRole("heading", { name: "Informe de entidad en espera" })).toBeInTheDocument();
    expect(screen.getByText(/actividad registral reciente/i)).toBeInTheDocument();
    expect(screen.getByText("Consta un nombramiento publicado en BORME.")).toBeInTheDocument();
    expect(screen.getByText("BORME · 2026-07-01 · nombramiento")).toBeInTheDocument();
    expect(screen.getByText(/todavía no son registros Evidence/i)).toBeInTheDocument();
    expect(mocks.incorporateReport).not.toHaveBeenCalled();
  });

  it("si el informe actual ya está incorporado enlaza al informe concreto", async () => {
    mocks.reports.mockResolvedValue({
      data: [
        {
          id: "job-current",
          status: "succeeded",
          result: {
            incorporated_report_id: "report-current",
            output: waitingReportOutput,
            pending_evidence_sources: pendingEvidenceSources,
          },
          version: 2,
        },
      ],
    });
    render(<EntityDossier name="IBERDROLA" type="company" />);

    const link = await screen.findByRole("link", { name: /Abrir informe incorporado/i });
    expect(link).toHaveAttribute("href", "/app/reports/report-current");
    expect(screen.queryByText(/biblioteca de informes/i)).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Ver informe en espera" })).not.toBeInTheDocument();
  });

  it("explica el estado vacío cuando la entidad no tiene informes", async () => {
    render(<EntityDossier name="IBERDROLA" type="company" />);

    expect(await screen.findByText(/Aún no hay informes generados para esta entidad/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^Informe de la entidad$/i })).toBeInTheDocument();
  });

  it("incorpora un informe de entidad terminado a un expediente", async () => {
    mocks.reports.mockResolvedValue({
      data: [
        {
          id: "job-1",
          status: "succeeded",
          result: { output: { title: "Informe de entidad" } },
          version: 1,
        },
      ],
    });
    render(<EntityDossier name="IBERDROLA" type="company" />);

    fireEvent.click(await screen.findByRole("button", { name: /Incorporar a expediente/i }));

    await waitFor(() => expect(mocks.incorporateReport).toHaveBeenCalledWith(
      "job-1",
      { dossier_id: "dossier-1" },
    ));
    expect(await screen.findByText(/Informe incorporado/i)).toBeInTheDocument();
  });

  it("carga una página adicional del histórico si hay paginación", async () => {
    mocks.dossier.mockResolvedValueOnce({
      ...dossierResponse,
      sections: {
        ...dossierResponse.sections,
        registry: {
          ok: true,
          data: {
            ...dossierResponse.sections.registry.data,
            total: 75,
          },
        },
      },
    });
    mocks.registry.mockResolvedValueOnce({
      items: [{ person: "SEGUNDA PAGINA", role: "Administrador", action: "nombramiento", date: "2026-01-01" }],
      total: 75,
      cached_seconds: 600,
      cache_hit: false,
    });
    render(<EntityDossier name="IBERDROLA" type="company" />);

    fireEvent.click(await screen.findByRole("tab", { name: "Órganos y cargos" }));
    fireEvent.click(screen.getByRole("button", { name: "Siguiente" }));

    await waitFor(() => expect(mocks.registry).toHaveBeenCalledWith({
      name: "IBERDROLA",
      type: "company",
      limit: 50,
      offset: 50,
    }));
    expect(await screen.findByText("SEGUNDA PAGINA")).toBeInTheDocument();
  });
});
