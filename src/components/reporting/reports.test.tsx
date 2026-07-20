import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  list: vi.fn(),
  listDossier: vi.fn(),
  templates: vi.fn(),
  generate: vi.fn(),
  get: vi.fn(),
  retry: vi.fn(),
  review: vi.fn(),
  publish: vi.fn(),
  downloadLink: vi.fn(),
  dossiers: vi.fn(),
  job: vi.fn(),
  exportCreate: vi.fn(),
  exportGet: vi.fn(),
  push: vi.fn(),
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
      reports: {
        list: mocks.list,
        listDossier: mocks.listDossier,
        templates: mocks.templates,
        generate: mocks.generate,
        get: mocks.get,
        retry: mocks.retry,
        review: mocks.review,
        publish: mocks.publish,
        downloadLink: mocks.downloadLink,
      },
      dossiers: { list: mocks.dossiers },
      jobs: { get: mocks.job },
      exports: { create: mocks.exportCreate, get: mocks.exportGet },
    },
  };
});
vi.mock("@/components/auth/auth-boundary", () => ({
  PermissionGate: ({ children }: { children: React.ReactNode }) => children,
}));
vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams(),
  useParams: () => ({ id: "report-1" }),
  useRouter: () => ({ push: mocks.push }),
}));
vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

import { ReportLibrary } from "./report-library";
import { ReportViewer } from "./report-viewer";

const template = {
  key: "executive_dossier",
  version: "v1",
  label: "Informe ejecutivo de expediente",
  report_type: "executive",
  input_contract: {
    required: ["dossier_id"],
    properties: { audience: "string?" },
  },
  sections: ["Estado actual"],
  evidence_policy: "Cada hecho material debe citar evidencia.",
  output_schema: "ReportOutput/v1",
  permissions: {},
  formats: ["html", "pdf", "json"],
  sha256: "abc",
};

const baseReport = {
  id: "report-1",
  dossier_id: "11111111-1111-4111-8111-111111111111",
  title: "Informe ejecutivo",
  status: "ready" as const,
  report_type: "executive",
  template_key: "executive_dossier",
  template_version: "v1",
  generation_version: 1,
  classification: "internal" as const,
  confidentiality_label: "Uso interno",
  job_id: null,
  parent_report_id: null,
  ready_at: "2026-07-11T01:00:00Z",
  reviewed_at: null,
  published_at: null,
  error_code: null,
  version: 2,
  revision: {
    id: "revision-1",
    content: {
      title: "Informe ejecutivo",
      executive_summary: "El expediente conserva impulso.",
      confidence: 82,
      sections: [
        {
          heading: "Estado actual",
          paragraphs: [
            {
              text: "Existe una señal material confirmada.",
              kind: "fact",
              confidence: 91,
              evidence_ids: ["evidence-1"],
            },
          ],
        },
      ],
      open_questions: ["¿Qué cambia la próxima semana?"],
      warnings: [],
    },
  },
  artifacts: [
    {
      id: "artifact-1",
      format: "html",
      status: "available",
      byte_size: 1200,
      checksum: "checksum",
      media_type: "text/html",
    },
  ],
  reviews: [],
  evidence: [
    {
      id: "evidence-1",
      extract: "Extracto original trazable.",
      locator: {
        title: "CATL defiende su planta de baterías en Zaragoza",
        source_type: "news",
        published_at: "2026-07-11T00:00:00Z",
        source_url: "https://www.elespanol.com/economia/",
        external_id: "sig_ext_sVHBO_pUd4",
      },
      source_label: "https://www.elespanol.com/economia/",
      classification: "public",
    },
  ],
  created_at: "2026-07-11T00:00:00Z",
  updated_at: "2026-07-11T01:00:00Z",
};

describe("reports Vector", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.list.mockResolvedValue({ data: [], meta: { page: 1, size: 100, total: 0 } });
    mocks.listDossier.mockResolvedValue({ data: [], meta: { page: 1, size: 100, total: 0 } });
    mocks.templates.mockResolvedValue({ items: [template], capabilities: { pdf: false } });
    mocks.dossiers.mockResolvedValue({
      data: [
        {
          id: baseReport.dossier_id,
          title: "Expediente Delta",
          description: "",
          dossier_type: "project",
          status: "active",
          strategic_goal: "",
          health_score: 70,
          opportunity_score: 80,
          risk_score: 20,
          updated_at: "2026-07-11T00:00:00Z",
        },
      ],
      meta: { total: 1 },
    });
    mocks.generate.mockResolvedValue({
      report: { ...baseReport, status: "generating", job_id: null, revision: null, artifacts: [], evidence: [] },
      job_id: "job-1",
      replayed: false,
    });
    mocks.get.mockResolvedValue(baseReport);
    mocks.review.mockResolvedValue({
      review_id: "review-1",
      report: { ...baseReport, status: "reviewed", version: 3 },
    });
    mocks.publish.mockResolvedValue({ ...baseReport, status: "published", version: 4 });
    mocks.downloadLink.mockResolvedValue({ url: "/api/v1/download?signed=1", expires_at: "2026-07-11T02:00:00Z" });
  });
  afterEach(cleanup);

  it("muestra vacío y genera desde el contrato de plantilla sin ofrecer PDF deshabilitado", async () => {
    render(<ReportLibrary routeBase="/app" />);
    expect(await screen.findByText("Aún no hay informes")).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Generar primer informe" }));
    expect(screen.getByRole("dialog", { name: "Crear informe" })).toBeVisible();
    expect(screen.getByLabelText(/PDF/i)).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Expediente"), {
      target: { value: baseReport.dossier_id },
    });
    fireEvent.change(screen.getByLabelText("Audiencia"), {
      target: { value: "Comité de dirección" },
    });
    fireEvent.change(screen.getByLabelText("Clasificación"), {
      target: { value: "public" },
    });
    expect(screen.getByLabelText("Etiqueta de confidencialidad")).toHaveValue(
      "Público",
    );
    fireEvent.click(screen.getByRole("button", { name: "Generar informe" }));
    await waitFor(() =>
      expect(mocks.generate).toHaveBeenCalledWith(
        baseReport.dossier_id,
        expect.objectContaining({
          template_key: "executive_dossier",
          options: expect.objectContaining({
            audience: "Comité de dirección",
            classification: "public",
            confidentiality_label: "Público",
            formats: ["html", "json"],
          }),
        }),
        expect.stringContaining("report-"),
      ),
    );
  });

  it("abre el informe desde la fila con teclado", async () => {
    mocks.list.mockResolvedValue({ data: [baseReport], meta: { page: 1, size: 100, total: 1 } });
    render(<ReportLibrary routeBase="/app" />);

    const row = await screen.findByRole("button", {
      name: "Abrir detalle de Informe ejecutivo",
    });
    expect(row).toHaveClass("interactive-row");
    fireEvent.keyDown(row, { key: "Enter" });

    expect(await screen.findByText("El expediente conserva impulso.")).toBeVisible();
  });

  it("abre citas, registra revisión, publica y solicita descarga firmada", async () => {
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => undefined);
    render(<ReportViewer reportId="report-1" routeBase="/app" />);
    expect(await screen.findByText("El expediente conserva impulso.")).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Abrir evidencia 1" }));
    expect(screen.getByText("Extracto original trazable.")).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Cerrar evidencia" }));
    fireEvent.click(screen.getByRole("button", { name: "Registrar revisión" }));
    await waitFor(() => expect(mocks.review).toHaveBeenCalledWith("report-1", expect.objectContaining({ decision: "approved", revision_id: "revision-1", version: 2 })));
    fireEvent.click(await screen.findByRole("button", { name: "Publicar" }));
    await waitFor(() => expect(mocks.publish).toHaveBeenCalledWith("report-1", 3));
    fireEvent.click(screen.getByRole("button", { name: "Descargar artefacto html" }));
    await waitFor(() => expect(mocks.downloadLink).toHaveBeenCalledWith("report-1", "artifact-1"));
    expect(click).toHaveBeenCalled();
  });

  it("presenta fragmentos cortos de una sección como un resumen narrativo único", async () => {
    mocks.get.mockResolvedValueOnce({
      ...baseReport,
      revision: {
        ...baseReport.revision,
        content: {
          ...baseReport.revision.content,
          sections: [
            {
              heading: "Cobertura y límites",
              paragraphs: [
                {
                  text: "El informe se basa en un subconjunto de actos registrales.",
                  kind: "inference",
                  confidence: 70,
                  evidence_ids: [],
                },
                {
                  text: "Las fechas del BORME son fechas de publicación.",
                  kind: "inference",
                  confidence: 70,
                  evidence_ids: [],
                },
                {
                  text: "La información relacionada no está desambiguada para homónimos.",
                  kind: "inference",
                  confidence: 70,
                  evidence_ids: [],
                },
              ],
            },
          ],
        },
      },
    });

    const { container } = render(<ReportViewer reportId="report-1" routeBase="/app" />);

    expect(
      await screen.findByText(
        "El informe se basa en un subconjunto de actos registrales. Las fechas del BORME son fechas de publicación. La información relacionada no está desambiguada para homónimos.",
      ),
    ).toBeVisible();
    expect(container.querySelectorAll(".report-claim")).toHaveLength(0);
    expect(screen.getAllByText("Inferencia")).toHaveLength(1);
  });

  it("mantiene distinguibles hecho e inferencia dentro de una misma sección", async () => {
    // 4 de las 7 secciones del informe real de producción mezclan hecho e inferencia.
    // Si la fusión narrativa deja el tipo solo en un pie de sección, el lector no puede
    // saber qué frase está respaldada por evidencia y cuál es conjetura del modelo:
    // se pierde justo la distinción que sostiene la confianza en el informe.
    mocks.get.mockResolvedValueOnce({
      ...baseReport,
      revision: {
        ...baseReport.revision,
        content: {
          ...baseReport.revision.content,
          sections: [
            {
              heading: "Gobierno y personas clave",
              paragraphs: [
                {
                  text: "El 6 de abril de 2026 se publicó el cese de cinco apoderados.",
                  kind: "fact",
                  confidence: 100,
                  evidence_ids: [],
                },
                {
                  text: "El movimiento sugiere una reorganización del órgano de apoderamiento.",
                  kind: "inference",
                  confidence: 70,
                  evidence_ids: [],
                },
              ],
            },
          ],
        },
      },
    });

    const { container } = render(<ReportViewer reportId="report-1" routeBase="/app" />);

    const hecho = await screen.findByText(/se publicó el cese de cinco apoderados/);
    const inferencia = screen.getByText(/sugiere una reorganización/);
    const bloqueHecho = hecho.closest("[data-claim-kind]");
    const bloqueInferencia = inferencia.closest("[data-claim-kind]");

    // No pueden acabar en el mismo bloque: son de tipos distintos.
    expect(bloqueHecho).not.toBe(bloqueInferencia);
    expect(bloqueHecho).toHaveAttribute("data-claim-kind", "fact");
    expect(bloqueInferencia).toHaveAttribute("data-claim-kind", "inference");
    // Y el tipo es legible, no solo color: el color no vale como señal única.
    expect(container.querySelectorAll("[data-claim-kind]")).toHaveLength(2);
    expect(screen.getByText("Hecho")).toBeVisible();
    expect(screen.getByText("Inferencia")).toBeVisible();
  });

  it("presenta las fuentes como citas legibles sin exponer el locator técnico", async () => {
    render(<ReportViewer reportId="report-1" routeBase="/app" />);
    expect(await screen.findByText("elespanol.com")).toBeVisible();
    expect(screen.getByText("CATL defiende su planta de baterías en Zaragoza")).toBeVisible();
    expect(screen.getByText(/Señal de prensa no verificada/)).toBeVisible();
    expect(screen.getByRole("link", { name: "Abrir fuente elespanol.com" })).toHaveAttribute(
      "href",
      "https://www.elespanol.com/economia/",
    );
    expect(screen.queryByText(/sig_ext_sVHBO_pUd4/)).not.toBeInTheDocument();
  });
});
