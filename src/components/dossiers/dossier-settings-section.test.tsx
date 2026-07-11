import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  get: vi.fn(),
  update: vi.fn(),
  archive: vi.fn(),
  monitors: vi.fn(),
  monitorAction: vi.fn(),
  success: vi.fn(),
}));

vi.mock("@oracle/api-client", () => ({
  ApiError: class ApiError extends Error {
    problem = { detail: this.message };
  },
  api: {
    dossiers: {
      get: mocks.get,
      update: mocks.update,
      archive: mocks.archive,
    },
    signalAvanza: {
      monitors: mocks.monitors,
      action: mocks.monitorAction,
    },
  },
}));

vi.mock("sonner", () => ({ toast: { success: mocks.success } }));
vi.mock("@/components/auth/auth-boundary", () => ({
  PermissionGate: ({ children }: { children: React.ReactNode }) => children,
}));

import { DossierSettingsSection } from "./dossier-settings-section";

const dossier = {
  id: "dossier-1",
  tenant_id: "tenant-1",
  title: "Expansión Delta",
  description: "Seguimiento de una expansión regional.",
  dossier_type: "project",
  status: "active" as const,
  strategic_goal: "Validar alianzas antes del siguiente hito.",
  health_score: 78,
  opportunity_score: 86,
  risk_score: 31,
  owner_user_id: "user-1",
  version: 4,
  archived_at: null,
  created_at: "2026-07-11T08:00:00Z",
  updated_at: "2026-07-11T08:30:00Z",
};

describe("DossierSettingsSection", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.get.mockResolvedValue(dossier);
    mocks.monitors.mockResolvedValue({ data: [] });
    mocks.update.mockResolvedValue({ ...dossier, status: "paused", version: 5 });
  });
  afterEach(cleanup);

  it("mantiene accesible la configuración si los monitores no están autorizados", async () => {
    mocks.monitors.mockRejectedValueOnce(new Error("forbidden"));
    render(<DossierSettingsSection dossierId="dossier-1" />);

    expect(await screen.findByRole("heading", { name: "Configuración" })).toBeVisible();
    expect(screen.getByLabelText("Título")).toHaveValue("Expansión Delta");
    expect(screen.getByText(/monitores no están disponibles con tus permisos/i)).toBeVisible();
  });

  it("solo ofrece transiciones de estado admitidas por el backend", async () => {
    render(<DossierSettingsSection dossierId="dossier-1" />);

    const status = await screen.findByLabelText("Estado");
    const options = within(status).getAllByRole("option");
    expect(options.map((option) => option.textContent)).toEqual(["Activo", "Pausado"]);
    expect(within(status).queryByRole("option", { name: "Borrador" })).not.toBeInTheDocument();

    fireEvent.change(status, { target: { value: "paused" } });
    fireEvent.click(screen.getByRole("button", { name: /Guardar cambios/ }));
    await waitFor(() =>
      expect(mocks.update).toHaveBeenCalledWith(
        "dossier-1",
        expect.objectContaining({ status: "paused", version: 4 }),
        4,
      ),
    );
  });
});
