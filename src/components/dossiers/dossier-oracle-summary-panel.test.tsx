import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  get: vi.fn(),
  refresh: vi.fn(),
  versions: vi.fn(),
  feedback: vi.fn(),
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
  },
}));

vi.mock("sonner", () => ({ toast: { success: mocks.success, error: mocks.error } }));

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
      job: null,
    });
    mocks.versions.mockResolvedValue({ data: [version] });
    mocks.refresh.mockResolvedValue({ job_id: "job-1", status: "queued" });
    mocks.feedback.mockResolvedValue({ feedback_id: "feedback-1" });
  });

  afterEach(cleanup);

  it("muestra resumen, cobertura, citas y bloques ejecutivos", async () => {
    render(<DossierOracleSummaryPanel dossierId="dossier-1" />);

    expect(await screen.findByRole("heading", { name: "Oráculo del expediente" })).toBeVisible();
    expect(screen.getByText("Avance con una decisión pendiente")).toBeVisible();
    expect(screen.getByText("78%")).toBeVisible();
    expect(screen.getByText("1/3")).toBeVisible();
    expect(screen.getByText("La convocatoria está abierta.")).toBeVisible();
    expect(screen.getByText("Alta")).toBeVisible();
    expect(screen.queryByText("high")).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Fuente #eeeeeeee" })).toHaveAttribute(
      "href",
      "https://example.com/fuente",
    );
  });

  it("encola refresh durable y registra feedback", async () => {
    render(<DossierOracleSummaryPanel dossierId="dossier-1" />);
    await screen.findByText("Avance con una decisión pendiente");

    fireEvent.click(screen.getByRole("button", { name: /Actualizar análisis/i }));
    await waitFor(() => expect(mocks.refresh).toHaveBeenCalledWith("dossier-1", expect.stringMatching(/^oracle-summary-/)));

    fireEvent.change(screen.getByLabelText("Feedback sobre el análisis"), {
      target: { value: "La oportunidad necesita más contexto documental." },
    });
    fireEvent.click(screen.getByRole("button", { name: /Enviar feedback/i }));
    await waitFor(() =>
      expect(mocks.feedback).toHaveBeenCalledWith(
        "dossier-1",
        version.id,
        expect.objectContaining({ comment: "La oportunidad necesita más contexto documental." }),
      ),
    );
  });
});
