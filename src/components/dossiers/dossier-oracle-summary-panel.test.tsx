import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  get: vi.fn(),
  refresh: vi.fn(),
  versions: vi.fn(),
  feedback: vi.fn(),
  createTask: vi.fn(),
  createDecision: vi.fn(),
  createOpportunity: vi.fn(),
  createRisk: vi.fn(),
  attachActor: vi.fn(),
  createHypothesis: vi.fn(),
  success: vi.fn(),
  error: vi.fn(),
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
    oracleSummary: {
      get: mocks.get,
      refresh: mocks.refresh,
      versions: mocks.versions,
      feedback: mocks.feedback,
    },
    tasks: { create: mocks.createTask },
    decisions: { create: mocks.createDecision },
    opportunities: { create: mocks.createOpportunity },
    risks: { create: mocks.createRisk },
    actors: { attach: mocks.attachActor },
    hypotheses: { create: mocks.createHypothesis },
  },
}));

vi.mock("sonner", () => ({ toast: { success: mocks.success, error: mocks.error } }));
vi.mock("@/components/auth/auth-boundary", () => ({
  PermissionGate: ({ children }: { children: React.ReactNode }) => children,
}));

import { DossierOracleSummaryPanel } from "./dossier-oracle-summary-panel";

const version = {
  id: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
  tenant_id: "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
  dossier_id: "dossier-1",
  version: 2,
  status: "valid",
  created_at: "2026-07-11T10:00:00Z",
  updated_at: "2026-07-11T10:05:00Z",
  output: {
    headline: "Avance con una decisión pendiente",
    executive_summary: "El expediente avanza con evidencia suficiente.",
    situation_status: "advancing",
    facts: [{ text: "La convocatoria está abierta.", evidence_ids: ["eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee"] }],
    material_changes: [{ change: "Se ha publicado la convocatoria.", importance: "high", evidence_ids: [] }],
    opportunities: [{ title: "Preparar propuesta", rationale: "Encaja con el objetivo.", urgency: "high" }],
    risks: [],
    decisions_required: [{ decision: "Aprobar presentación", reason: "Hay plazo próximo.", urgency: "high" }],
    recommended_actions: [{ action: "Asignar responsable", rationale: "Reduce bloqueo.", priority: "high" }],
    confidence: 78,
    evidence_coverage: { cited_items: 1, available_items: 3, limitations: [] },
    warnings: [],
  },
  citations: [
    {
      id: "eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee",
      tenant_id: "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
      created_at: "2026-07-11T09:00:00Z",
      updated_at: "2026-07-11T09:00:00Z",
      source_kind: "signal",
      source_url: "https://example.com/fuente",
      locator: {},
      extract: "La convocatoria está abierta.",
      classification: "public",
    },
  ],
  audit: {
    id: "cccccccc-cccc-4ccc-8ccc-cccccccccccc",
    tenant_id: "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
    provider: "ollama",
    model: "qwen3.5:9b",
    prompt_name: "dossier_situation_summary",
    prompt_version: "v1",
    prompt_hash: "hash",
    context_hash: "ctx",
    input_tokens: 10,
    output_tokens: 20,
    cost_micros: 0,
    latency_ms: 100,
    status: "succeeded",
  },
};

describe("DossierOracleSummaryPanel", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.get.mockResolvedValue({
      state: "ready",
      summary: version,
      living_summary_version: 3,
      last_refreshed_at: "2026-07-11T10:05:00Z",
      generation_trigger: "nightly",
      job: null,
    });
    mocks.versions.mockResolvedValue({ data: [version] });
    mocks.refresh.mockResolvedValue({ job_id: "job-1", status: "queued" });
    mocks.feedback.mockResolvedValue({ feedback_id: "feedback-1" });
    mocks.createTask.mockResolvedValue({ id: "task-1" });
    mocks.createDecision.mockResolvedValue({ id: "decision-1" });
  });

  afterEach(cleanup);

  it("muestra resumen, cobertura, citas y bloques ejecutivos", async () => {
    render(<DossierOracleSummaryPanel dossierId="dossier-1" />);

    expect(await screen.findByRole("heading", { name: "Oráculo del expediente" })).toBeVisible();
    expect(await screen.findByText("Avance con una decisión pendiente")).toBeVisible();
    expect(screen.getByText("78%")).toBeVisible();
    expect(screen.getByText("1/3")).toBeVisible();
    expect(screen.getByText("La convocatoria está abierta.")).toBeVisible();
    expect(screen.getByText("Alta")).toBeVisible();
    expect(screen.getByText("Generación nocturna")).toBeVisible();
    expect(screen.queryByText(/Revisión de evidencia:/)).not.toBeInTheDocument();
    expect(mocks.refresh).not.toHaveBeenCalled();
    expect(screen.queryByText("high")).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Fuente #eeeeeeee" })).toHaveAttribute(
      "href",
      "https://example.com/fuente",
    );
  });

  it("hace visible el recorte del revisor sin presentar el claim como hecho", async () => {
    const reviewedVersion = {
      ...version,
      output: {
        ...version.output,
        facts: [],
        warnings: [
          "Revisión de evidencia: se retiraron 1 afirmación objetada antes de publicar.",
          "Afirmación retirada: La convocatoria cubre toda Europa. Motivo: La fuente solo acredita España.",
        ],
      },
    };
    mocks.get.mockResolvedValueOnce({
      state: "ready",
      summary: reviewedVersion,
      living_summary_version: 4,
      last_refreshed_at: "2026-07-22T08:05:00Z",
      generation_trigger: "nightly",
      job: null,
    });

    render(<DossierOracleSummaryPanel dossierId="dossier-1" />);

    expect(await screen.findByText(/se retiraron 1 afirmación objetada/)).toBeVisible();
    expect(screen.getByText(/Afirmación retirada: La convocatoria cubre toda Europa/)).toBeVisible();
    expect(screen.queryByText("La convocatoria está abierta.")).not.toBeInTheDocument();
  });

  it("conserva la versión publicada mientras una regeneración está en curso", async () => {
    mocks.get.mockResolvedValueOnce({
      state: "ready",
      summary: version,
      living_summary_version: 3,
      last_refreshed_at: "2026-07-11T10:05:00Z",
      generation_trigger: "manual",
      job: { id: "job-1", status: "running" },
    });
    render(<DossierOracleSummaryPanel dossierId="dossier-1" />);

    expect(await screen.findByText("Avance con una decisión pendiente")).toBeVisible();
    expect(screen.getByText(/Actualización en curso/)).toBeVisible();
    expect(screen.getByRole("button", { name: "Actualizando" })).toBeDisabled();
  });

  it("encola refresh durable y registra feedback", async () => {
    render(<DossierOracleSummaryPanel dossierId="dossier-1" />);
    await screen.findByText("Avance con una decisión pendiente");

    fireEvent.click(screen.getByRole("button", { name: /Actualizar análisis/i }));
    await waitFor(() => expect(mocks.refresh).toHaveBeenCalledWith("dossier-1", expect.stringMatching(/^oracle-summary-/)));

    fireEvent.change(screen.getByLabelText("Comentario sobre el análisis"), {
      target: { value: "La oportunidad necesita más contexto documental." },
    });
    fireEvent.click(screen.getByRole("button", { name: /Enviar comentario/i }));
    await waitFor(() =>
      expect(mocks.feedback).toHaveBeenCalledWith(
        "dossier-1",
        version.id,
        expect.objectContaining({ comment: "La oportunidad necesita más contexto documental." }),
      ),
    );
  });

  it("materializa tarea y decisión solo después de confirmación humana", async () => {
    render(<DossierOracleSummaryPanel dossierId="dossier-1" />);
    await screen.findByText("Avance con una decisión pendiente");

    const action = screen.getByText("Asignar responsable").closest("li");
    expect(action).not.toBeNull();
    fireEvent.click(within(action!).getByRole("button", { name: "Crear borrador" }));
    expect(mocks.createTask).not.toHaveBeenCalled();
    expect(screen.getByRole("dialog", { name: "Crear borrador de tarea" })).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Confirmar borrador" }));
    await waitFor(() => expect(mocks.createTask).toHaveBeenCalledWith(
      "dossier-1",
      expect.objectContaining({
        title: "Asignar responsable",
        status: "open",
        content: expect.objectContaining({ oracle_summary_id: version.id, requires_human_review: true }),
      }),
    ));

    const decision = screen.getByText("Aprobar presentación").closest("li");
    expect(decision).not.toBeNull();
    fireEvent.click(within(decision!).getByRole("button", { name: "Crear borrador de decisión" }));
    expect(mocks.createDecision).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Confirmar borrador" }));
    await waitFor(() => expect(mocks.createDecision).toHaveBeenCalledWith(
      "dossier-1",
      expect.objectContaining({ title: "Aprobar presentación", status: "proposed" }),
    ));
  });
});
