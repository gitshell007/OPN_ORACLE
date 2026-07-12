import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  connections: vi.fn(),
  create: vi.fn(),
  rotate: vi.fn(),
  test: vi.fn(),
  monitors: vi.fn(),
  createMonitor: vi.fn(),
  action: vi.fn(),
  reconcile: vi.fn(),
  getJob: vi.fn(),
  retryJob: vi.fn(),
  recentRun: vi.fn((action: () => Promise<unknown>) => action()),
}));

vi.mock("@oracle/api-client", () => {
  class ApiError extends Error {}
  return {
    ApiError,
    api: {
      signalAvanza: {
        connections: mocks.connections,
        create: mocks.create,
        rotate: mocks.rotate,
        test: mocks.test,
        monitors: mocks.monitors,
        createMonitor: mocks.createMonitor,
        action: mocks.action,
        reconcile: mocks.reconcile,
      },
      jobs: { get: mocks.getJob, retry: mocks.retryJob },
    },
  };
});
vi.mock("@/components/auth/recent-auth", () => ({
  useRecentAuth: () => ({ run: mocks.recentRun }),
}));
vi.mock("@/components/admin/tenant-admin", () => ({
  AdminNav: () => <nav aria-label="Administración de organización" />,
}));
vi.mock("sonner", () => ({
  toast: { success: vi.fn(), warning: vi.fn() },
}));

import { SignalAdmin } from "./signal-admin";

const connection = {
  id: "connection-1",
  provider: "signal-avanza",
  name: "Principal",
  status: "active",
  adapter_mode: "http",
  api_version: "v1",
  base_url: "https://signal.example.test",
  circuit_state: "closed",
  last_health_at: "2026-07-10T10:00:00Z",
  last_success_at: "2026-07-10T10:00:00Z",
  last_error: null,
  version: 1,
};

describe("SignalAdmin", () => {
  afterEach(cleanup);
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.connections.mockResolvedValue({ items: [connection] });
    mocks.rotate.mockResolvedValue({ status: "rotated" });
    mocks.test.mockResolvedValue({ outbox_event_id: "event-1", status: "pending" });
    mocks.reconcile.mockResolvedValue({ requeued: 2 });
    mocks.monitors.mockResolvedValue({ data: [] });
  });

  it("muestra salud y rota credenciales sin volver a exponer el secreto", async () => {
    render(<SignalAdmin />);
    expect(await screen.findByText("Saludable")).toHaveAttribute(
      "data-status",
      "healthy",
    );
    fireEvent.click(screen.getByRole("button", { name: /Rotar credencial/i }));
    const secret = screen.getByLabelText("Nuevo secreto");
    expect(secret).toHaveAttribute("type", "password");
    fireEvent.change(secret, { target: { value: "credencial-segura-123" } });
    fireEvent.click(screen.getByRole("button", { name: /^Rotar$/i }));
    await waitFor(() =>
      expect(mocks.rotate).toHaveBeenCalledWith("connection-1", {
        kind: "api_token",
        secret: "credencial-segura-123",
      }),
    );
    expect(screen.queryByDisplayValue("credencial-segura-123")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: /Probar conexión/i }));
    await waitFor(() => expect(mocks.test).toHaveBeenCalledWith("connection-1"));
  });

  it("sincroniza un monitor con errores y estados accesibles", async () => {
    mocks.monitors.mockResolvedValue({
      data: [
        {
          id: "monitor-1",
          tenant_id: "tenant-1",
          watchlist_id: "watchlist-1",
          connection_id: "connection-1",
          provider: "signal-avanza",
          external_id: "radar-europa",
          status: "error",
          desired_status: "active",
          observed_status: "paused",
          cursor: null,
          last_synced_at: null,
          last_error: "Timeout saneado",
          next_sync_at: null,
          last_sync_attempt_at: null,
          version: 2,
        },
      ],
    });
    mocks.action.mockResolvedValue({ job_id: "job-1", status: "queued" });
    render(<SignalAdmin />);
    await screen.findByText("Saludable");
    fireEvent.change(screen.getByLabelText("Identificador del expediente"), {
      target: { value: "dossier-1" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Cargar vigilancias" }));
    expect(await screen.findByText("Timeout saneado")).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Sincronizar radar-europa" }));
    await waitFor(() =>
      expect(mocks.action).toHaveBeenCalledWith("monitor-1", "sync"),
    );
    expect(await screen.findByText("Proceso: En cola")).toHaveAttribute("role", "status");
  });

  it("ofrece reconciliación real cuando la conexión está degradada", async () => {
    mocks.connections.mockResolvedValue({
      items: [
        {
          ...connection,
          circuit_state: "half_open",
          last_error: "Proveedor intermitente",
        },
      ],
    });
    render(<SignalAdmin />);
    expect(await screen.findByText("Degradada")).toHaveAttribute(
      "data-status",
      "degraded",
    );
    fireEvent.click(screen.getByRole("button", { name: "Reconciliar" }));
    await waitFor(() =>
      expect(mocks.reconcile).toHaveBeenCalledWith("connection-1"),
    );
  });
});
