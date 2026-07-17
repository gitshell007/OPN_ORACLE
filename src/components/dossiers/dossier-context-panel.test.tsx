import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  objectives: vi.fn(),
  hypotheses: vi.fn(),
  evidence: vi.fn(),
  createHypothesis: vi.fn(),
  updateHypothesis: vi.fn(),
  hypothesisEvidence: vi.fn(),
  linkEvidence: vi.fn(),
  removeHypothesis: vi.fn(),
  success: vi.fn(),
}));

vi.mock("@oracle/api-client", () => ({
  ApiError: class ApiError extends Error {},
  api: {
    objectives: { list: mocks.objectives },
    hypotheses: {
      list: mocks.hypotheses,
      create: mocks.createHypothesis,
      update: mocks.updateHypothesis,
      remove: mocks.removeHypothesis,
      evidence: mocks.hypothesisEvidence,
      linkEvidence: mocks.linkEvidence,
    },
    dossierEvidence: { list: mocks.evidence },
  },
}));
vi.mock("sonner", () => ({ toast: { success: mocks.success } }));
vi.mock("@/components/auth/auth-boundary", () => ({
  PermissionGate: ({ children }: { children: React.ReactNode }) => children,
}));

import { DossierContextPanel } from "./dossier-context-panel";

describe("DossierContextPanel", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.objectives.mockResolvedValue({ data: [{ id: "objective-1", title: "Analizar viabilidad", status: "open", description: "Contrastar el proyecto.", version: 1 }] });
    mocks.hypotheses.mockResolvedValue({ data: [{ id: "hypothesis-1", statement: "Existe un socio industrial viable", rationale: "La señal abre una puerta.", status: "open", confidence: 50, version: 2 }] });
    mocks.evidence.mockResolvedValue({ data: [{ id: "evidence-1", extract: "Fuente primaria confirmada." }] });
    mocks.updateHypothesis.mockResolvedValue({ id: "hypothesis-1" });
    mocks.createHypothesis.mockResolvedValue({ id: "hypothesis-2" });
    mocks.removeHypothesis.mockResolvedValue(undefined);
    mocks.hypothesisEvidence.mockResolvedValue({ data: [{ id: "evidence-1", extract: "Fuente primaria confirmada." }] });
    mocks.linkEvidence.mockResolvedValue({ linked: true });
  });

  afterEach(cleanup);

  it("muestra el objetivo y las hipótesis de la base inicial", async () => {
    render(<DossierContextPanel dossierId="dossier-1" />);
    expect(await screen.findByText("Analizar viabilidad")).toBeVisible();
    expect(screen.getByText("Existe un socio industrial viable")).toBeVisible();
  });

  it("edita el estado de una hipótesis y vincula evidencia", async () => {
    render(<DossierContextPanel dossierId="dossier-1" />);
    fireEvent.click(await screen.findByRole("button", { name: "Ver o editar hipótesis: Existe un socio industrial viable" }));
    fireEvent.change(screen.getByLabelText("Estado"), { target: { value: "supported" } });
    fireEvent.change(screen.getByLabelText("Vincular evidencia"), { target: { value: "evidence-1" } });
    fireEvent.click(screen.getByRole("button", { name: "Vincular" }));
    await waitFor(() => expect(mocks.linkEvidence).toHaveBeenCalledWith("hypothesis-1", "evidence-1"));
    fireEvent.click(screen.getByRole("button", { name: "Guardar" }));
    await waitFor(() => expect(mocks.updateHypothesis).toHaveBeenCalledWith(
      "hypothesis-1",
      expect.objectContaining({ status: "supported", version: 2 }),
      2,
    ));
  });

  it("pide confirmación antes de borrar una hipótesis", async () => {
    render(<DossierContextPanel dossierId="dossier-1" />);
    fireEvent.click(await screen.findByRole("button", { name: "Ver o editar hipótesis: Existe un socio industrial viable" }));

    fireEvent.click(screen.getByRole("button", { name: "Eliminar" }));
    expect(mocks.removeHypothesis).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "Confirmar borrado" }));

    await waitFor(() => expect(mocks.removeHypothesis).toHaveBeenCalledWith("hypothesis-1", 2));
  });
});
