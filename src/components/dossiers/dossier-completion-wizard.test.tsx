import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  latest: vi.fn(),
  run: vi.fn(),
  push: vi.fn(),
}));

vi.mock("@oracle/api-client", () => ({
  api: {
    dossierCompletionWizard: {
      latest: mocks.latest,
      run: mocks.run,
    },
  },
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: mocks.push }),
}));

vi.mock("@/components/reporting/job-progress", () => ({
  JobProgress: ({ label }: { label?: string }) => <div>{label}</div>,
}));

import { DossierCompletionWizard } from "./dossier-completion-wizard";

const output = {
  summary: "Faltan vigilancia, licitaciones y actores.",
  confidence: 72,
  warnings: ["Mock"],
  section_diagnostics: [
    {
      section: "signals",
      status: "empty" as const,
      explanation: "No hay monitores activos.",
    },
  ],
  questions: [
    {
      id: "scope.geography",
      question: "¿Qué ámbito geográfico quieres vigilar primero?",
      why_it_matters: "Ajusta la vigilancia.",
      expected_input: "Ej.: España",
    },
  ],
  recommended_actions: [
    {
      kind: "create_actor" as const,
      title: "Añadir adjudicatarios habituales",
      rationale: "Permite mapear competencia.",
      prefill: {
        actor_type: "organization" as const,
        tags: ["fabricante"],
        roles: ["competidor", "adjudicatario habitual"],
      },
    },
  ],
};

describe("DossierCompletionWizard", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    sessionStorage.clear();
    mocks.latest.mockResolvedValue({
      job: null,
      artifact: {
        id: "artifact-1",
        output,
      },
    });
    mocks.run.mockResolvedValue({
      job: { id: "job-1", status: "queued" },
      artifact: { id: "artifact-1", output },
    });
  });

  afterEach(cleanup);

  it("recupera la última ronda y relanza con respuestas estructuradas", async () => {
    render(<DossierCompletionWizard dossierId="dossier-1" />);

    fireEvent.click(screen.getByRole("button", { name: "Mejorar con Oracle" }));
    const dialog = await screen.findByRole("dialog", {
      name: "Mejorar expediente con Oracle",
    });
    expect(within(dialog).getByText("Faltan vigilancia, licitaciones y actores.")).toBeVisible();
    fireEvent.change(
      within(dialog).getByPlaceholderText("Ej.: España"),
      { target: { value: "España" } },
    );
    fireEvent.click(within(dialog).getByRole("button", { name: "Lanzar nueva ronda" }));

    await waitFor(() =>
      expect(mocks.run).toHaveBeenCalledWith(
        "dossier-1",
        { answers: [{ question_id: "scope.geography", answer: "España" }] },
        expect.stringContaining("dossier-wizard-dossier-1-"),
      ),
    );
  });

  it("abre el formulario real de actor con prefill reservado", async () => {
    render(<DossierCompletionWizard dossierId="dossier-1" />);

    fireEvent.click(screen.getByRole("button", { name: "Mejorar con Oracle" }));
    const dialog = await screen.findByRole("dialog", {
      name: "Mejorar expediente con Oracle",
    });
    fireEvent.click(within(dialog).getByRole("button", { name: /Abrir formulario/i }));

    expect(mocks.push).toHaveBeenCalledWith(
      "/app/dossiers/dossier-1/actors?wizard_prefill=actor",
    );
    expect(
      JSON.parse(sessionStorage.getItem("oracle:wizard-prefill:dossier-1:actor") ?? "{}"),
    ).toEqual(output.recommended_actions[0].prefill);
  });
});
