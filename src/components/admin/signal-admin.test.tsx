import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  connections: vi.fn(),
  create: vi.fn(),
  rotate: vi.fn(),
  test: vi.fn(),
  activate: vi.fn(),
  disable: vi.fn(),
  update: vi.fn(),
  monitors: vi.fn(),
  createMonitor: vi.fn(),
  action: vi.fn(),
  reconcile: vi.fn(),
  getJob: vi.fn(),
  retryJob: vi.fn(),
  /** Real recent.run: intercepts recent_auth_required and retries after reauth. */
  recentRun: vi.fn(async (action: () => Promise<unknown>) => {
    try {
      return await action();
    } catch (reason) {
      if (
        reason instanceof Error &&
        "problem" in reason &&
        (reason as { problem?: { code?: string } }).problem?.code === "recent_auth_required"
      ) {
        // Simulate successful reauthenticate then retry once.
        return await action();
      }
      throw reason;
    }
  }),
}));

vi.mock("@oracle/api-client", () => {
  class ApiError extends Error {
    status: number;
    problem: { code: string; detail: string; title?: string };
    constructor(status: number, problem: { code: string; detail: string }) {
      super(problem.detail);
      this.name = "ApiError";
      this.status = status;
      this.problem = problem;
    }
  }
  return {
    ApiError,
    api: {
      signalAvanza: {
        connections: mocks.connections,
        create: mocks.create,
        rotate: mocks.rotate,
        test: mocks.test,
        activate: mocks.activate,
        disable: mocks.disable,
        update: mocks.update,
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
vi.mock("@/components/auth/auth-provider", () => ({
  useAuth: () => ({
    identity: { user: { platform_role: null } },
  }),
}));
vi.mock("@/components/admin/tenant-admin", () => ({
  AdminNav: () => <nav aria-label="Administración de organización" />,
}));
vi.mock("sonner", () => ({
  toast: { success: vi.fn(), warning: vi.fn() },
}));

import { ApiError } from "@oracle/api-client";
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
    mocks.activate.mockResolvedValue({ ...connection, status: "active" });
    mocks.disable.mockResolvedValue({ ...connection, status: "disabled" });
    mocks.update.mockResolvedValue({
      ...connection,
      base_url: "https://signal.updated.test",
      api_version: "2026-08-01",
    });
    mocks.reconcile.mockResolvedValue({ requeued: 2 });
    mocks.monitors.mockResolvedValue({ data: [] });
    mocks.create.mockResolvedValue({ ...connection, id: "connection-new" });
    // Default: pass-through (reauth already fresh)
    mocks.recentRun.mockImplementation(async (action: () => Promise<unknown>) => action());
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

  it("permite reactivar una conexión desactivada y editar el destino", async () => {
    mocks.connections.mockResolvedValue({
      items: [{ ...connection, status: "disabled" }],
    });
    render(<SignalAdmin />);
    expect(await screen.findByTestId("connection-status-connection-1")).toHaveTextContent(
      /desactivad/i,
    );
    fireEvent.click(screen.getByRole("button", { name: /^Activar$/i }));
    await waitFor(() => expect(mocks.activate).toHaveBeenCalledWith("connection-1"));
    fireEvent.click(screen.getByRole("button", { name: /Editar destino/i }));
    fireEvent.change(screen.getByLabelText("Dirección base (URL)"), {
      target: { value: "https://signal.updated.test" },
    });
    fireEvent.change(screen.getByLabelText("Versión de API"), {
      target: { value: "2026-08-01" },
    });
    expect(
      screen.queryByLabelText(/Confirmo el uso de esta URL/i),
    ).toBeNull();
    expect(
      screen.getByTestId("signal-edit-cross-env-platform-note"),
    ).toHaveTextContent(/superadministración de plataforma/i);
    fireEvent.click(screen.getByRole("button", { name: /Guardar destino/i }));
    await waitFor(() =>
      expect(mocks.update).toHaveBeenCalledWith("connection-1", {
        name: "Principal",
        adapter_mode: "http",
        base_url: "https://signal.updated.test",
        api_version: "2026-08-01",
        confirm_cross_environment: undefined,
      }),
    );
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

  it("crear conexión pasa por useRecentAuth y reintenta tras reautenticación", async () => {
    mocks.create
      .mockRejectedValueOnce(
        new ApiError(401, {
          code: "recent_auth_required",
          detail: "Vuelve a introducir tu contraseña para continuar.",
        }),
      )
      .mockResolvedValueOnce({ ...connection, id: "connection-new" });
    mocks.recentRun.mockImplementation(async (action: () => Promise<unknown>) => {
      try {
        return await action();
      } catch (reason) {
        if (
          reason instanceof ApiError &&
          reason.problem.code === "recent_auth_required"
        ) {
          return await action();
        }
        throw reason;
      }
    });
    render(<SignalAdmin />);
    await screen.findByText("Saludable");
    fireEvent.click(screen.getByRole("button", { name: /Nueva conexión|Configurar/i }));
    // Form may already be open or need click
    const nameField =
      screen.queryByLabelText(/^Nombre$/i) ??
      (await screen.findByDisplayValue("Principal"));
    fireEvent.change(nameField, { target: { value: "Secundaria" } });
    fireEvent.click(screen.getByRole("button", { name: /Guardar conexión/i }));
    await waitFor(() => expect(mocks.recentRun).toHaveBeenCalled());
    await waitFor(() => expect(mocks.create).toHaveBeenCalledTimes(2));
    expect(mocks.create.mock.calls[0][0]).toMatchObject({ name: "Secundaria" });
  });

  it("un 401 de reauth se muestra como confirmación de contraseña, no genérico", async () => {
    mocks.activate.mockRejectedValue(
      new ApiError(401, {
        code: "recent_auth_required",
        detail: "Vuelve a introducir tu contraseña para continuar.",
      }),
    );
    // recent.run rethrows if not handling — surface to UI
    mocks.recentRun.mockImplementation(async (action: () => Promise<unknown>) => {
      try {
        return await action();
      } catch (reason) {
        throw reason;
      }
    });
    mocks.connections.mockResolvedValue({
      items: [{ ...connection, status: "disabled" }],
    });
    render(<SignalAdmin />);
    await screen.findByTestId("connection-status-connection-1");
    fireEvent.click(screen.getByRole("button", { name: /^Activar$/i }));
    expect(
      await screen.findByText(/Confirma tu contraseña para continuar/i),
    ).toBeVisible();
    expect(screen.queryByText(/No se pudo activar la conexión/i)).toBeNull();
    expect(screen.queryByText(/No se pudo configurar la conexión/i)).toBeNull();
  });

  it("un 403 de plataforma muestra su mensaje propio", async () => {
    mocks.create.mockRejectedValue(
      new ApiError(403, {
        code: "signal_cross_environment_platform_required",
        detail:
          "Apuntar a una instancia de Signal distinta de este despliegue requiere superadministración de plataforma.",
      }),
    );
    render(<SignalAdmin />);
    await screen.findByText("Saludable");
    fireEvent.click(screen.getByRole("button", { name: /Nueva conexión/i }));
    fireEvent.click(screen.getByRole("button", { name: /Guardar conexión/i }));
    expect(
      await screen.findByText(/superadministración de plataforma/i),
    ).toBeVisible();
    expect(screen.queryByText(/No se pudo configurar la conexión/i)).toBeNull();
  });

  it("create, activate, disable, update y rotate pasan por useRecentAuth", async () => {
    // Active connection → Desactivar visible; then flip list to disabled for Activar.
    mocks.connections.mockResolvedValue({ items: [connection] });
    render(<SignalAdmin />);
    await screen.findByText("Saludable");

    fireEvent.click(screen.getByRole("button", { name: /Desactivar/i }));
    await waitFor(() => expect(mocks.disable).toHaveBeenCalledWith("connection-1"));
    expect(mocks.recentRun).toHaveBeenCalled();
    const callsAfterDisable = mocks.recentRun.mock.calls.length;

    mocks.connections.mockResolvedValue({
      items: [{ ...connection, status: "disabled" }],
    });
    fireEvent.click(screen.getByRole("button", { name: /Actualizar/i }));
    await screen.findByTestId("connection-status-connection-1");
    fireEvent.click(screen.getByRole("button", { name: /^Activar$/i }));
    await waitFor(() =>
      expect(mocks.recentRun.mock.calls.length).toBeGreaterThan(callsAfterDisable),
    );
    await waitFor(() => expect(mocks.activate).toHaveBeenCalledWith("connection-1"));

    // Restore active list for edit/rotate UI (reload after activate may still be disabled mock).
    mocks.connections.mockResolvedValue({ items: [connection] });
    fireEvent.click(screen.getByRole("button", { name: /Actualizar/i }));
    await screen.findByText("Saludable");

    fireEvent.click(screen.getByRole("button", { name: /Editar destino/i }));
    fireEvent.click(screen.getByRole("button", { name: /Guardar destino/i }));
    await waitFor(() => expect(mocks.update).toHaveBeenCalled());

    fireEvent.click(screen.getByRole("button", { name: /Rotar credencial/i }));
    fireEvent.change(screen.getByLabelText("Nuevo secreto"), {
      target: { value: "otra-clave-segura-xyz" },
    });
    fireEvent.click(screen.getByRole("button", { name: /^Rotar$/i }));
    await waitFor(() => expect(mocks.rotate).toHaveBeenCalled());

    // Create via open form
    fireEvent.click(screen.getByRole("button", { name: /Nueva conexión/i }));
    fireEvent.click(screen.getByRole("button", { name: /Guardar conexión/i }));
    await waitFor(() => expect(mocks.create).toHaveBeenCalled());

    expect(mocks.recentRun.mock.calls.length).toBeGreaterThanOrEqual(5);
    expect(mocks.disable).toHaveBeenCalled();
    expect(mocks.activate).toHaveBeenCalled();
    expect(mocks.update).toHaveBeenCalled();
    expect(mocks.rotate).toHaveBeenCalled();
    expect(mocks.create).toHaveBeenCalled();
  });
});

describe("SignalAdmin · invariante recent_auth", () => {
  it("toda mutación protegida en backend se invoca vía recent.run en el fuente", () => {
    const here = dirname(fileURLToPath(import.meta.url));
    const src = readFileSync(join(here, "signal-admin.tsx"), "utf8");
    // Backend: create, activate, disable, patch(update), rotate → @recent_auth_required
    const protectedMethods = ["create", "activate", "disable", "update", "rotate"] as const;
    for (const method of protectedMethods) {
      const wrapped = new RegExp(
        `recent\\.run\\([\\s\\S]{0,120}?api\\.signalAvanza\\.${method}\\b`,
      );
      expect(src, `api.signalAvanza.${method} must be inside recent.run`).toMatch(
        wrapped,
      );
      // Must not call the protected API with bare await outside recent.run
      // (allow test/monitors/etc.). Strip recent.run blocks and ensure method gone.
      const withoutRecentBlocks = src.replace(
        /recent\.run\(\(\)\s*=>[\s\S]*?\),?\n/g,
        "/* recent.run stripped */\n",
      );
      expect(
        withoutRecentBlocks,
        `api.signalAvanza.${method} must not appear outside recent.run`,
      ).not.toMatch(new RegExp(`api\\.signalAvanza\\.${method}\\s*\\(`));
    }
  });
});
