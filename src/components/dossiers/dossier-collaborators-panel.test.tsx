import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  listCollaborators: vi.fn(),
  setCollaborator: vi.fn(),
  removeCollaborator: vi.fn(),
  assignableList: vi.fn(),
  success: vi.fn(),
}));

vi.mock("@oracle/api-client", () => ({
  ApiError: class ApiError extends Error {
    problem = { detail: this.message };
  },
  api: {
    dossiers: {
      listCollaborators: mocks.listCollaborators,
      setCollaborator: mocks.setCollaborator,
      removeCollaborator: mocks.removeCollaborator,
    },
    assignableUsers: {
      list: mocks.assignableList,
    },
  },
}));

vi.mock("sonner", () => ({ toast: { success: mocks.success } }));
vi.mock("@/components/auth/auth-boundary", () => ({
  PermissionGate: ({ children }: { children: React.ReactNode }) => children,
}));

import { DossierCollaboratorsPanel } from "./dossier-collaborators-panel";

describe("DossierCollaboratorsPanel", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.listCollaborators.mockResolvedValue({
      data: [
        {
          tenant_id: "t1",
          dossier_id: "d1",
          user_id: "user-ana",
          role: "viewer",
          display_name: "Ana Analista",
          email: "ana@oracle.invalid",
        },
      ],
    });
    mocks.assignableList.mockResolvedValue({
      items: [
        {
          id: "user-ana",
          display_name: "Ana Analista",
          email: "ana@oracle.invalid",
        },
        {
          id: "user-borja",
          display_name: "Borja Editor",
          email: "borja@oracle.invalid",
        },
      ],
    });
    mocks.setCollaborator.mockResolvedValue({
      tenant_id: "t1",
      dossier_id: "d1",
      user_id: "user-borja",
      role: "editor",
      display_name: "Borja Editor",
      email: "borja@oracle.invalid",
    });
  });
  afterEach(cleanup);

  it("muestra quién tiene acceso e invita con nivel", async () => {
    render(<DossierCollaboratorsPanel dossierId="d1" />);

    await waitFor(() => {
      expect(screen.getByText(/Ana Analista/)).toBeTruthy();
    });
    expect(
      screen.getByText(/No es posible compartir con usuarios de otra organización/i),
    ).toBeTruthy();

    fireEvent.change(screen.getByLabelText(/Compañero de la organización/i), {
      target: { value: "user-borja" },
    });
    fireEvent.change(screen.getByLabelText(/Nivel de acceso/i), {
      target: { value: "editor" },
    });
    fireEvent.click(screen.getByRole("button", { name: /Invitar/i }));

    await waitFor(() => {
      expect(mocks.setCollaborator).toHaveBeenCalledWith("d1", "user-borja", {
        role: "editor",
      });
    });
    expect(mocks.success).toHaveBeenCalled();
  });

  it("busca miembros del tenant por email", async () => {
    render(<DossierCollaboratorsPanel dossierId="d1" />);
    await waitFor(() => {
      expect(screen.getByLabelText(/Buscar por email/i)).toBeTruthy();
    });
    mocks.assignableList.mockClear();
    mocks.assignableList.mockResolvedValue({
      items: [
        {
          id: "user-borja",
          display_name: "Borja Editor",
          email: "borja@oracle.invalid",
        },
      ],
    });

    fireEvent.change(screen.getByLabelText(/Buscar por email/i), {
      target: { value: "borja@" },
    });

    await waitFor(() => {
      expect(mocks.assignableList).toHaveBeenCalledWith({ q: "borja@" });
    });
  });
});
