import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  formatAuditCost,
  formatAuditLatency,
  formatAuditTokens,
} from "./ai-audit-panel";

const mocks = vi.hoisted(() => ({
  list: vi.fn(),
  get: vi.fn(),
  searchParams: new URLSearchParams(),
}));

vi.mock("@oracle/api-client", () => {
  class ApiError extends Error {
    status: number;
    problem: { detail: string };
    constructor(status: number, problem: { detail: string }) {
      super(problem.detail);
      this.status = status;
      this.problem = problem;
      this.name = "ApiError";
    }
  }
  return {
    ApiError,
    api: {
      aiAudit: {
        list: mocks.list,
        get: mocks.get,
      },
    },
  };
});

vi.mock("next/navigation", () => ({
  useSearchParams: () => mocks.searchParams,
}));

vi.mock("next/link", () => ({
  default: ({
    children,
    href,
  }: {
    children: React.ReactNode;
    href: string;
  }) => <a href={href}>{children}</a>,
}));

import { AiAuditPanel } from "./ai-audit-panel";

const sampleItem = {
  id: "audit-1",
  dossier_id: "dossier-abc-12345678",
  background_job_id: "job-99",
  agent: "dossier_completion_wizard",
  action: "generate",
  status: "succeeded",
  error_code: null,
  provider: "signal-avanza",
  model: "mock-model",
  input_tokens: 120,
  output_tokens: 40,
  cost_micros: 1_250_000,
  currency: "EUR",
  latency_ms: 842,
  attempt_count: 1,
  source_ids: ["ev-1", "ev-2"],
  data_classification: "internal",
  human_review_state: "not_required",
  created_at: "2026-08-03T10:00:00+00:00",
};

const failedItem = {
  ...sampleItem,
  id: "audit-2",
  status: "failed",
  error_code: "provider_timeout",
  cost_micros: 0,
  latency_ms: null as number | null,
  source_ids: [] as string[],
  created_at: "2026-08-03T11:00:00+00:00",
};

describe("format helpers", () => {
  it("formatea coste con 6 decimales y no inventa nulos", () => {
    expect(formatAuditCost(1_250_000, "EUR")).toBe("1.250000 EUR");
    expect(formatAuditCost(0, "EUR")).toBe("0.000000 EUR");
    expect(formatAuditCost(null)).toBe("—");
    expect(formatAuditCost(undefined)).toBe("—");
  });

  it("formatea tokens y latencia sin rellenar", () => {
    expect(formatAuditTokens(10, 5)).toBe("10 / 5");
    expect(formatAuditTokens(null, null)).toBe("—");
    expect(formatAuditLatency(842)).toBe("842 ms");
    expect(formatAuditLatency(null)).toBe("—");
  });
});

describe("AiAuditPanel", () => {
  afterEach(() => {
    cleanup();
  });

  beforeEach(() => {
    vi.clearAllMocks();
    mocks.searchParams = new URLSearchParams();
    mocks.list.mockResolvedValue({ items: [failedItem, sampleItem] });
    mocks.get.mockResolvedValue({
      ...sampleItem,
      prompt: { name: "wizard", version: "v1", hash: "abc" },
      schema: { name: "wizard", version: "v1" },
      usage: {
        input_tokens: 120,
        output_tokens: 40,
        cost_micros: 1_250_000,
        currency: "EUR",
      },
      review_state: "not_required",
      attempts: [
        {
          number: 1,
          kind: "generate",
          status: "succeeded",
          input_tokens: 120,
          output_tokens: 40,
          cost_micros: 1_250_000,
          latency_ms: 842,
          error_code: null,
        },
      ],
    });
  });

  it("lista ejecuciones con números alineados y coste fijo", async () => {
    render(<AiAuditPanel />);
    expect(await screen.findByTestId("ai-audit-table")).toBeInTheDocument();
    expect(screen.getByText("1.250000 EUR")).toBeInTheDocument();
    expect(screen.getAllByText("120 / 40").length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText("842 ms")).toBeInTheDocument();
    // latencia nula → guion; coste 0 con 6 decimales
    expect(screen.getByText("0.000000 EUR")).toBeInTheDocument();
    expect(screen.getAllByText("—").length).toBeGreaterThan(0);
    expect(mocks.list).toHaveBeenCalled();
  });

  it("abre detalle con evidencias y trabajo de origen", async () => {
    render(<AiAuditPanel />);
    await screen.findByTestId("ai-audit-table");
    fireEvent.click(screen.getByTestId("ai-audit-open-audit-1"));
    expect(await screen.findByTestId("ai-audit-detail-body")).toBeInTheDocument();
    expect(screen.getByTestId("ai-audit-source-ids")).toHaveTextContent("ev-1");
    expect(screen.getByText("job-99")).toBeInTheDocument();
    expect(mocks.get).toHaveBeenCalledWith("audit-1");
  });

  it("filtra por estado fallidas al cambiar el select", async () => {
    render(<AiAuditPanel />);
    await screen.findByTestId("ai-audit-table");
    fireEvent.change(screen.getByTestId("ai-audit-filter-status"), {
      target: { value: "failed" },
    });
    await waitFor(() => {
      expect(mocks.list).toHaveBeenLastCalledWith(
        expect.objectContaining({ status: "failed" }),
      );
    });
  });

  it("muestra acceso denegado cuando la API responde 403", async () => {
    // El mock de ApiError usa `instanceof` en runtime del módulo mockeado.
    const { ApiError } = await import("@oracle/api-client");
    mocks.list.mockRejectedValue(
      new ApiError(403, { detail: "No tienes permiso para esta acción." } as never),
    );
    render(<AiAuditPanel />);
    expect(await screen.findByTestId("ai-audit-denied")).toBeInTheDocument();
    expect(screen.getByText("Acceso restringido")).toBeInTheDocument();
    expect(
      screen.getByText("No tienes permiso para consultar la auditoría de IA."),
    ).toBeInTheDocument();
  });
});
