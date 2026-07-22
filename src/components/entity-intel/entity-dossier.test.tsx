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

const currentRegistryResponse = {
  query: "IBERDROLA",
  view: "current",
  total: 1,
  source_total: 3,
  profile: dossierResponse.sections.registry.data.profile,
  available_provinces: ["BIZKAIA", "MADRID"],
  summary: {
    history_events: 3,
    received_events: 3,
    history_complete: true,
    current_relationships: 1,
    ended_relationships: 1,
    company_acts: 3,
  },
  items: [
    {
      person: "BURGOS CANTO MIGUEL",
      counterpart: "BURGOS CANTO MIGUEL",
      counterpart_kind: null,
      counterpart_kind_verified: false,
      role: "Administrador",
      action: "nombramiento",
      relationship_status: "active",
      date: "2026-07-01",
      province: "BIZKAIA",
      source_url: "https://boe.test/1",
    },
  ],
  cached_seconds: 600,
  cache_hit: false,
};

const historyRegistryResponse = {
  ...currentRegistryResponse,
  view: "history",
  total: 3,
  items: dossierResponse.sections.registry.data.items.map((item) => ({
    ...item,
    counterpart: item.person,
    counterpart_kind: null,
    counterpart_kind_verified: false,
  })),
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
    mocks.registry.mockResolvedValue(currentRegistryResponse);
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
    expect(screen.getByText((_, element) => element?.textContent === "3 eventos de cargos")).toBeInTheDocument();
    expect(screen.getByText((_, element) => element?.textContent === "3 actos societarios")).toBeInTheDocument();
    expect(screen.getByText("Actos societarios publicados")).toBeInTheDocument();
    expect(screen.getByText("Eventos de cargos y órganos")).toBeInTheDocument();
    expect(screen.getByText(/Las fechas son de publicación en BORME/i)).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Noticias" })).toBeInTheDocument();
  });

  it("muestra degradación de grafo sin tumbar el resto", async () => {
    render(<EntityDossier name="IBERDROLA" type="company" />);

    fireEvent.click(await screen.findByRole("tab", { name: "Grafo" }));

    expect(screen.getByText("Grafo deshabilitado en Signal.")).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Perfil" })).toBeInTheDocument();
  });

  it("declara cuando EPO entrega una muestra recortada de patentes", async () => {
    mocks.dossier.mockResolvedValue({
      ...dossierResponse,
      sections: {
        ...dossierResponse.sections,
        patents: {
          ok: true,
          data: {
            total: 569,
            items: Array.from({ length: 25 }, (_, index) => ({
              pub_number: `EP-${index + 1}`,
              title: `Patente ${index + 1}`,
              applicants: ["TELEFONICA SA"],
              url: `https://example.test/patent/${index + 1}`,
            })),
          },
        },
      },
    });

    render(<EntityDossier name="TELEFONICA SA" type="company" />);

    fireEvent.click(await screen.findByRole("tab", { name: "Patentes" }));
    expect(
      screen.getByText(/se muestran 25 de 569 publicaciones de patente/i),
    ).toBeInTheDocument();
    expect(screen.getByText(/la muestra no es exhaustiva/i)).toBeInTheDocument();
  });

  it("muestra el fallo de búsqueda EPO sin convertirlo en ausencia de patentes", async () => {
    mocks.dossier.mockResolvedValue({
      ...dossierResponse,
      entity: { name: "ITURRI SA", type: "company" },
      sections: {
        ...dossierResponse.sections,
        patents: { ok: false, error: "epo_search_404" },
      },
    });

    render(<EntityDossier name="ITURRI SA" type="company" />);

    fireEvent.click(await screen.findByRole("tab", { name: "Patentes" }));
    expect(screen.getByRole("alert")).toHaveTextContent(
      /puede estar registrado con otra grafía o mediante una filial/i,
    );
    expect(screen.getByRole("alert")).toHaveTextContent(
      /no permite concluir que la entidad carezca de patentes/i,
    );
    expect(screen.getByText(/código de la fuente: epo_search_404/i)).toBeInTheDocument();
  });

  it("no muestra aviso de recorte cuando EPO entrega todas las patentes", async () => {
    mocks.dossier.mockResolvedValue({
      ...dossierResponse,
      entity: { name: "INDRA SISTEMAS SA", type: "company" },
      sections: {
        ...dossierResponse.sections,
        patents: {
          ok: true,
          data: {
            total: 3,
            items: Array.from({ length: 3 }, (_, index) => ({
              pub_number: `EP-INDRA-${index + 1}`,
              title: `Patente INDRA ${index + 1}`,
              applicants: ["INDRA SISTEMAS SA"],
              url: `https://example.test/indra/${index + 1}`,
            })),
          },
        },
      },
    });

    render(<EntityDossier name="INDRA SISTEMAS SA" type="company" />);

    fireEvent.click(await screen.findByRole("tab", { name: "Patentes" }));
    expect(screen.getByText("3 de 3 filas")).toBeInTheDocument();
    expect(screen.queryByText(/la muestra no es exhaustiva/i)).not.toBeInTheDocument();
  });

  it("separa cargos actuales del histórico sin atribuir estado actual a cada evento", async () => {
    mocks.registry
      .mockResolvedValueOnce(currentRegistryResponse)
      .mockResolvedValueOnce(historyRegistryResponse);
    render(<EntityDossier name="IBERDROLA" type="company" />);

    fireEvent.click(await screen.findByRole("tab", { name: "Órganos y cargos" }));

    expect(screen.getByText("BURGOS CANTO MIGUEL")).toBeInTheDocument();
    expect(screen.queryByText("PEREZ LOPEZ ANA")).not.toBeInTheDocument();
    expect(screen.getByText("Actual")).toBeInTheDocument();
    expect(screen.getByText(/Una fila por contraparte y cargo/i)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("tab", { name: /Histórico BORME/i }));

    expect(await screen.findAllByText("PEREZ LOPEZ ANA")).toHaveLength(2);
    expect(screen.getAllByText("cese")).toHaveLength(1);
    expect(screen.queryByText("Cesado")).not.toBeInTheDocument();
    expect(screen.getByText(/no el estado actual de todas las filas anteriores/i)).toBeInTheDocument();
  });

  it("envía búsqueda, provincia y orden al backend para aplicarlos a todo el corpus", async () => {
    render(<EntityDossier name="IBERDROLA" type="company" />);

    fireEvent.click(await screen.findByRole("tab", { name: "Órganos y cargos" }));
    await screen.findByText("BURGOS CANTO MIGUEL");

    fireEvent.change(screen.getByLabelText("Buscar en todo el histórico"), {
      target: { value: "auditor" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Aplicar filtros" }));
    await waitFor(() => expect(mocks.registry).toHaveBeenLastCalledWith(expect.objectContaining({
      q: "auditor",
      view: "current",
      offset: 0,
    })));

    fireEvent.change(screen.getByLabelText("Provincia"), { target: { value: "MADRID" } });
    await waitFor(() => expect(mocks.registry).toHaveBeenLastCalledWith(expect.objectContaining({
      q: "auditor",
      province: "MADRID",
      offset: 0,
    })));

    fireEvent.click(screen.getByRole("button", { name: /Cargo, sin ordenar/i }));
    await waitFor(() => expect(mocks.registry).toHaveBeenLastCalledWith(expect.objectContaining({
      sort: "role",
      offset: 0,
    })));
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
    mocks.registry
      .mockResolvedValueOnce({ ...currentRegistryResponse, total: 75 })
      .mockResolvedValueOnce({
        ...currentRegistryResponse,
        items: [{
          person: "SEGUNDA PAGINA",
          counterpart: "SEGUNDA PAGINA",
          counterpart_kind: null,
          counterpart_kind_verified: false,
          role: "Administrador",
          action: "nombramiento",
          date: "2026-01-01",
        }],
        total: 75,
      });
    render(<EntityDossier name="IBERDROLA" type="company" />);

    fireEvent.click(await screen.findByRole("tab", { name: "Órganos y cargos" }));
    fireEvent.click(screen.getByRole("button", { name: "Siguiente" }));

    await waitFor(() => expect(mocks.registry).toHaveBeenCalledWith({
      name: "IBERDROLA",
      type: "company",
      limit: 50,
      offset: 50,
      view: "current",
      q: "",
      province: "",
      sort: "-date",
    }));
    expect(await screen.findByText("SEGUNDA PAGINA")).toBeInTheDocument();
  });
});
