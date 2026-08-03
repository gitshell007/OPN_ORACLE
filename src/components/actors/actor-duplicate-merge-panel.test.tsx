import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  aliasCandidates: vi.fn(),
  merge: vi.fn(),
  success: vi.fn(),
}));

vi.mock("@oracle/api-client", () => ({
  ApiError: class ApiError extends Error {
    problem = { detail: this.message };
  },
  api: {
    actors: {
      aliasCandidates: mocks.aliasCandidates,
      merge: mocks.merge,
    },
  },
}));

vi.mock("sonner", () => ({ toast: { success: mocks.success } }));
vi.mock("@/components/auth/auth-boundary", () => ({
  PermissionGate: ({ children }: { children: React.ReactNode }) => children,
}));

import { ActorDuplicateMergePanel } from "./actor-duplicate-merge-panel";

const candidate = {
  identity_key: "ITURRI",
  status: "candidate",
  reason: "Coincidencia de denominación sin forma jurídica; requiere revisión.",
  actors: [
    { id: "actor-sa", name: "ITURRI SA", identifiers: {}, aliases: [] },
    { id: "actor-plain", name: "Iturri", identifiers: {}, aliases: ["Iturri S.A."] },
  ],
};

describe("ActorDuplicateMergePanel", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.aliasCandidates.mockResolvedValue({ items: [candidate] });
    mocks.merge.mockResolvedValue({
      id: "actor-sa",
      canonical_name: "ITURRI SA",
      aliases: ["Iturri", "Iturri S.A."],
    });
  });
  afterEach(cleanup);

  it("lista candidatos y fusiona solo tras confirmación humana con motivo", async () => {
    render(<ActorDuplicateMergePanel />);

    await waitFor(() => {
      expect(screen.getByText(/Clave «ITURRI»/)).toBeTruthy();
    });
    expect(screen.getAllByText("ITURRI SA").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Iturri").length).toBeGreaterThan(0);
    expect(
      screen.getByText(/No es reversible con un clic/i),
    ).toBeTruthy();
    expect(mocks.merge).not.toHaveBeenCalled();

    fireEvent.change(screen.getByPlaceholderText(/Misma empresa/i), {
      target: { value: "Misma empresa, distinta forma jurídica" },
    });
    fireEvent.click(screen.getByRole("button", { name: /Confirmar fusión/i }));

    await waitFor(() => {
      expect(mocks.merge).toHaveBeenCalledWith("actor-sa", {
        source_actor_id: "actor-plain",
        reason: "Misma empresa, distinta forma jurídica",
      });
    });
    expect(mocks.success).toHaveBeenCalled();
  });

  it("muestra estado vacío cuando no hay candidatos", async () => {
    mocks.aliasCandidates.mockResolvedValue({ items: [] });
    render(<ActorDuplicateMergePanel />);
    await waitFor(() => {
      expect(screen.getByText(/No hay candidatos/i)).toBeTruthy();
    });
  });
});
