import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  get: vi.fn(),
  retry: vi.fn(),
  cancel: vi.fn(),
  success: vi.fn(),
  error: vi.fn(),
  message: vi.fn(),
  dismiss: vi.fn(),
}));

vi.mock("@oracle/api-client", () => ({
  ApiError: class ApiError extends Error {},
  api: { jobs: { get: mocks.get, retry: mocks.retry, cancel: mocks.cancel } },
}));
vi.mock("sonner", () => ({
  toast: {
    success: mocks.success,
    error: mocks.error,
    message: mocks.message,
    dismiss: mocks.dismiss,
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

const queuedJob = {
  ...job,
  status: "queued" as const,
  stage: "manual_retry",
  progress: 0,
  version: 4,
  error_message: null,
};

const runningJob = {
  ...queuedJob,
  status: "running" as const,
  stage: "Generando informe",
  progress: 45,
};

const succeededJob = {
  ...runningJob,
  status: "succeeded" as const,
  stage: "Completado",
  progress: 100,
  version: 5,
  retryable: false,
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
  afterEach(() => {
    cleanup();
    vi.useRealTimers();
  });

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

  it("reanuda un único poll tras retry queued → running → succeeded", async () => {
    vi.useFakeTimers();
    mocks.get
      .mockResolvedValueOnce(job)
      .mockResolvedValueOnce(queuedJob)
      .mockResolvedValueOnce(runningJob)
      .mockResolvedValueOnce(succeededJob);
    mocks.retry.mockResolvedValue(queuedJob);
    const onTerminal = vi.fn();

    render(<JobProgress jobId="job-1" allowActions onTerminal={onTerminal} />);
    await act(async () => {
      await Promise.resolve();
    });
    expect(screen.getByText("El documento necesita revisión.")).toBeVisible();

    // El primer GET comunica el failed inicial; medimos solo el intento nuevo.
    onTerminal.mockClear();
    mocks.success.mockClear();
    mocks.error.mockClear();

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Reintentar" }));
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(mocks.retry).toHaveBeenCalledTimes(1);
    expect(mocks.retry).toHaveBeenCalledWith("job-1", 3);
    expect(mocks.get).toHaveBeenCalledTimes(2);
    expect(onTerminal).not.toHaveBeenCalled();

    await act(async () => {
      await vi.advanceTimersByTimeAsync(2499);
    });
    expect(mocks.get).toHaveBeenCalledTimes(2);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(1);
    });
    expect(mocks.get).toHaveBeenCalledTimes(3);
    expect(onTerminal).not.toHaveBeenCalled();

    await act(async () => {
      await vi.advanceTimersByTimeAsync(1799);
    });
    expect(mocks.get).toHaveBeenCalledTimes(3);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(1);
    });
    expect(mocks.get).toHaveBeenCalledTimes(4);
    expect(onTerminal).toHaveBeenCalledTimes(1);
    expect(onTerminal).toHaveBeenCalledWith(succeededJob);
    expect(
      mocks.success.mock.calls.filter(([message]) => message === "Proceso completado"),
    ).toHaveLength(1);

    // Un terminal no deja otro timer vivo ni duplica callback/toast.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(20_000);
    });
    expect(mocks.get).toHaveBeenCalledTimes(4);
    expect(onTerminal).toHaveBeenCalledTimes(1);
    expect(
      mocks.success.mock.calls.filter(([message]) => message === "Proceso completado"),
    ).toHaveLength(1);
  });

  it("notifica una sola vez si retry ya devuelve terminal", async () => {
    vi.useFakeTimers();
    mocks.get.mockResolvedValue(job);
    mocks.retry.mockResolvedValue(succeededJob);
    const onTerminal = vi.fn();

    render(<JobProgress jobId="job-1" allowActions onTerminal={onTerminal} />);
    await act(async () => {
      await Promise.resolve();
    });
    onTerminal.mockClear();
    mocks.success.mockClear();
    mocks.error.mockClear();

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Reintentar" }));
      await Promise.resolve();
    });

    expect(mocks.retry).toHaveBeenCalledWith("job-1", 3);
    expect(onTerminal).toHaveBeenCalledTimes(1);
    expect(onTerminal).toHaveBeenCalledWith(succeededJob);
    expect(
      mocks.success.mock.calls.filter(([message]) => message === "Proceso completado"),
    ).toHaveLength(1);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(20_000);
    });
    expect(mocks.get).toHaveBeenCalledTimes(1);
    expect(onTerminal).toHaveBeenCalledTimes(1);
    expect(
      mocks.success.mock.calls.filter(([message]) => message === "Proceso completado"),
    ).toHaveLength(1);
  });

  it("invalida el GET en vuelo y no agenda timers después de desmontar", async () => {
    vi.useFakeTimers();
    let resolveGet: ((value: typeof runningJob) => void) | undefined;
    mocks.get.mockImplementationOnce(
      () =>
        new Promise<typeof runningJob>((resolve) => {
          resolveGet = resolve;
        }),
    );
    const onTerminal = vi.fn();

    const view = render(<JobProgress jobId="job-1" allowActions onTerminal={onTerminal} />);
    expect(mocks.get).toHaveBeenCalledTimes(1);
    view.unmount();

    await act(async () => {
      resolveGet?.(runningJob);
      await Promise.resolve();
      await vi.advanceTimersByTimeAsync(20_000);
    });

    expect(mocks.get).toHaveBeenCalledTimes(1);
    expect(onTerminal).not.toHaveBeenCalled();
    expect(mocks.success).not.toHaveBeenCalled();
    expect(mocks.error).not.toHaveBeenCalled();
    expect(mocks.message).not.toHaveBeenCalled();
  });
});
