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
  toast: {
    success: mocks.success,
    error: mocks.error,
    message: vi.fn(),
    dismiss: vi.fn(),
  },
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

  it("reanuda el poll tras reintento no terminal hasta éxito", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    mocks.get
      .mockResolvedValueOnce({ ...job, status: "failed", retryable: true, version: 3 })
      .mockResolvedValueOnce({
        ...job,
        status: "queued",
        stage: "manual_retry",
        progress: 0,
        version: 4,
        retryable: true,
      })
      .mockResolvedValue({
        ...job,
        status: "succeeded",
        progress: 100,
        version: 5,
        retryable: false,
      });
    mocks.retry.mockResolvedValue({
      ...job,
      status: "queued",
      stage: "manual_retry",
      progress: 0,
      version: 4,
    });
    const onTerminal = vi.fn();
    render(<JobProgress jobId="job-1" allowActions onTerminal={onTerminal} />);
    fireEvent.click(await screen.findByRole("button", { name: "Reintentar" }));
    await waitFor(() => expect(mocks.retry).toHaveBeenCalledWith("job-1", 3));
    // Poll loop restarted: GET after mutate
    await vi.advanceTimersByTimeAsync(3000);
    await waitFor(() => expect(mocks.get.mock.calls.length).toBeGreaterThanOrEqual(2));
    await vi.advanceTimersByTimeAsync(3000);
    await waitFor(() => expect(onTerminal).toHaveBeenCalled());
    expect(onTerminal.mock.calls.at(-1)?.[0]?.status).toBe("succeeded");
    vi.useRealTimers();
  });

  it("oculta Cancelar si ya hay cancel_requested y muestra Cancelando", async () => {
    mocks.get.mockResolvedValue({
      ...job,
      status: "running",
      cancel_requested: true,
      retryable: false,
    });
    render(<JobProgress jobId="job-1" allowActions />);
    expect(await screen.findByText("Cancelando…")).toBeVisible();
    expect(screen.queryByRole("button", { name: "Cancelar" })).toBeNull();
  });

  it("no muestra Reintentar si failed no es retryable", async () => {
    mocks.get.mockResolvedValue({ ...job, status: "failed", retryable: false });
    render(<JobProgress jobId="job-1" allowActions />);
    await screen.findByText("El documento necesita revisión.");
    expect(screen.queryByRole("button", { name: "Reintentar" })).toBeNull();
  });
});