import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  list: vi.fn(),
  read: vi.fn(),
  readAll: vi.fn(),
  dismiss: vi.fn(),
  preferences: vi.fn(),
  updatePreference: vi.fn(),
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
      notifications: {
        list: mocks.list,
        read: mocks.read,
        readAll: mocks.readAll,
        dismiss: mocks.dismiss,
        preferences: mocks.preferences,
        updatePreference: mocks.updatePreference,
      },
    },
  };
});
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: mocks.push }),
}));
vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

import {
  NotificationBell,
  NotificationCenter,
  NotificationPreferences,
} from "./notifications";

const unread = {
  id: "notification-1",
  type: "report.ready",
  severity: "success" as const,
  title: "Informe disponible",
  body: "La generación terminó y requiere revisión.",
  link: "/app/dossiers/11111111-1111-4111-8111-111111111111/reports?report=report-1",
  read_at: null,
  dismissed_at: null,
  expires_at: null,
  resource_type: "report",
  resource_id: "report-1",
  created_at: "2026-07-11T01:00:00Z",
};

describe("notifications Vector", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.list.mockResolvedValue({
      data: [unread],
      meta: { page: 1, size: 100, total: 1, unread_count: 1 },
    });
    mocks.read.mockResolvedValue({ ...unread, read_at: "2026-07-11T01:05:00Z" });
    mocks.readAll.mockResolvedValue({ updated: 1, unread_count: 0 });
    mocks.dismiss.mockResolvedValue({ ...unread, dismissed_at: "2026-07-11T01:06:00Z" });
    mocks.preferences.mockResolvedValue({ items: [] });
    mocks.updatePreference.mockImplementation(async (input) => ({
      id: "preference-1",
      notification_type: input.notification_type,
      channels: input.channels,
      digest_cadence: input.digest_cadence,
      timezone: input.timezone,
      local_time: input.local_time,
      weekday: input.weekday,
      quiet_hours_start: input.quiet_hours_start,
      quiet_hours_end: input.quiet_hours_end,
      minimum_severity: input.minimum_severity,
      security_locked: false,
      version: 1,
    }));
  });
  afterEach(cleanup);

  it("muestra contador real en la campana y abre el destino tras marcar lectura", async () => {
    render(<NotificationBell routeBase="/app" />);
    const bell = await screen.findByRole("button", {
      name: "Notificaciones, 1 sin leer",
    });
    fireEvent.click(bell);
    fireEvent.click(await screen.findByRole("button", { name: /Informe disponible/i }));
    await waitFor(() => expect(mocks.read).toHaveBeenCalledWith("notification-1"));
    expect(mocks.push).toHaveBeenCalledWith(unread.link);
  });

  it("marca como leída, navega solo por enlace interno y permite descartar", async () => {
    render(<NotificationCenter routeBase="/app" />);
    expect(await screen.findByText("Informe disponible")).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Marcar como leída" }));
    await waitFor(() => expect(mocks.read).toHaveBeenCalledWith("notification-1"));
    fireEvent.click(screen.getByRole("button", { name: /Informe disponible/i }));
    await waitFor(() => expect(mocks.push).toHaveBeenCalledWith(unread.link));
    fireEvent.click(screen.getByRole("button", { name: "Descartar" }));
    await waitFor(() => expect(mocks.dismiss).toHaveBeenCalledWith("notification-1"));
    expect(screen.getByText("No hay notificaciones activas")).toBeVisible();
  });

  it("guarda digest y mantiene bloqueadas las alertas de seguridad", async () => {
    render(<NotificationPreferences />);
    expect(await screen.findByRole("heading", { name: "Todas las notificaciones" })).toBeVisible();
    fireEvent.click(screen.getByLabelText("Correo electrónico"));
    fireEvent.change(screen.getByLabelText("Frecuencia"), { target: { value: "daily" } });
    fireEvent.click(screen.getByRole("button", { name: "Guardar preferencias" }));
    await waitFor(() =>
      expect(mocks.updatePreference).toHaveBeenCalledWith(
        expect.objectContaining({
          notification_type: "*",
          channels: { in_app: true, email: true },
          digest_cadence: "daily",
          timezone: "Europe/Madrid",
        }),
      ),
    );
    fireEvent.click(screen.getByRole("button", { name: /Acceso sospechoso/i }));
    expect(screen.getByLabelText("Aplicación")).toBeDisabled();
    expect(screen.getByLabelText("Correo electrónico")).toBeDisabled();
    expect(screen.getByText(/alertas de seguridad se envían al instante/i)).toBeVisible();
  });
});
