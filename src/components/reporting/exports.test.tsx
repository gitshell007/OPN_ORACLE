import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  list: vi.fn(),
  create: vi.fn(),
  get: vi.fn(),
  downloadLink: vi.fn(),
  dossiers: vi.fn(),
  job: vi.fn(),
}));

vi.mock("@oracle/api-client", () => ({
  api: {
    exports: {
      list: mocks.list,
      create: mocks.create,
      get: mocks.get,
      downloadLink: mocks.downloadLink,
    },
    dossiers: { list: mocks.dossiers },
    jobs: { get: mocks.job },
  },
}));
vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

import { ExportCenter } from "./exports";

const queued = {
  id: "export-1",
  dataset: "reports",
  format: "csv" as const,
  status: "queued" as const,
  dossier_id: null,
  job_id: "job-1",
  filters: {},
  columns: ["id", "title", "status"],
  watermark: "",
  byte_size: null,
  checksum: null,
  expires_at: null,
  error_code: null,
  version: 1,
  created_at: "2026-07-11T01:00:00Z",
  updated_at: "2026-07-11T01:00:00Z",
};

describe("secure exports Vector", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.list.mockResolvedValue({ data: [], meta: { page: 1, size: 100, total: 0 } });
    mocks.dossiers.mockResolvedValue({ data: [], meta: { total: 0 } });
    mocks.create.mockResolvedValue({ export: queued, job_id: "job-1", replayed: false });
    mocks.job.mockResolvedValue({
      id: "job-1",
      tenant_id: "tenant-1",
      job_type: "oracle.export.generate",
      queue: "default",
      status: "running",
      stage: "Renderizando CSV",
      progress: 47,
      version: 1,
    });
    mocks.downloadLink.mockResolvedValue({
      url: "/api/v1/export-artifacts/export-1/download?signed=1",
      expires_at: "2026-07-11T02:00:00Z",
    });
  });
  afterEach(cleanup);

  it("crea una exportación con columnas explícitas y muestra progreso durable", async () => {
    render(<ExportCenter initialDataset="reports" />);
    expect(await screen.findByText("Aún no hay exportaciones")).toBeVisible();
    fireEvent.change(screen.getByLabelText("Buscar (opcional)"), {
      target: { value: "ejecutivo" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Generar CSV" }));
    await waitFor(() =>
      expect(mocks.create).toHaveBeenCalledWith(
        expect.objectContaining({
          dataset: "reports",
          filters: { search: "ejecutivo" },
          columns: expect.arrayContaining(["id", "title", "status"]),
        }),
        expect.stringContaining("export-reports-"),
      ),
    );
    const progress = await screen.findByRole("progressbar", {
      name: "Generando exportación",
    });
    await waitFor(() => expect(progress).toHaveAttribute("aria-valuenow", "47"));
  });

  it("solicita enlace temporal antes de descargar un CSV disponible", async () => {
    const ready = { ...queued, status: "ready" as const, job_id: null, byte_size: 2048 };
    mocks.list.mockResolvedValueOnce({ data: [ready], meta: { page: 1, size: 100, total: 1 } });
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => undefined);
    render(<ExportCenter />);
    fireEvent.click(await screen.findByRole("button", { name: "Descargar exportación de reports" }));
    await waitFor(() => expect(mocks.downloadLink).toHaveBeenCalledWith("export-1"));
    expect(click).toHaveBeenCalled();
  });
});
