import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  get: vi.fn(),
  retry: vi.fn(),
  cancel: vi.fn(),
  success: vi.fn(),
  error: vi.fn(),
}));

vi.mock("@oracle/api-client", () => ({
  ApiError: class ApiError extends Error {},
  api: { jobs: { get: mocks.get, retry: mocks.retry, cancel: mocks.cancel } },
}));
vi.mock("sonner", () => ({
  toast: { success: mocks.success, error: mocks.error, dismiss: vi.fn() },
}));

import { JobProgress } from "./job-progress";

const job = {
  id: "job-1",
  job_type: "document.process",
  progress: 70,
  queue: "default",
  stage: "Extrayendo texto",
  status: "failed" as const,
  tenant_id: "tenant-1",
  version: 3,
  retryable: true,
  error_message: "El documento necesita revisión.",
};

describe("JobProgress", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.get.mockResolvedValue(job);
    mocks.retry.mockResolvedValue({
      ...job,
      status: "queued",
      progress: 0,
      version: 4,
    });
    mocks.cancel.mockResolvedValue({
      ...job,
      status: "running",
      cancel_requested: true,
      version: 4,
    });
  });
  afterEach(cleanup);

  it("expone un reintento versionado para fallos recuperables", async () => {
    render(<JobProgress jobId="job-1" allowActions />);
    expect(await screen.findByText("El documento necesita revisión.")).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Reintentar" }));
    await waitFor(() => expect(mocks.retry).toHaveBeenCalledWith("job-1", 3));
    expect(mocks.success).toHaveBeenCalledWith("Reintento encolado", {
      id: "job-progress:job-1",
      duration: 4000,
    });
  });

  it("permite solicitar la cancelación de un proceso activo", async () => {
    mocks.get.mockResolvedValue({ ...job, status: "running", retryable: false });
    render(<JobProgress jobId="job-1" allowActions />);
    fireEvent.click(await screen.findByRole("button", { name: "Cancelar" }));
    await waitFor(() => expect(mocks.cancel).toHaveBeenCalledWith("job-1", 3));
  });
});
