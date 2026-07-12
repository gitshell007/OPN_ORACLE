import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  candidates: vi.fn(),
  importCandidate: vi.fn(),
  reviewCandidate: vi.fn(),
  success: vi.fn(),
}));

vi.mock("@oracle/api-client", () => ({
  ApiError: class ApiError extends Error {},
  api: { actors: {
    candidates: mocks.candidates,
    importCandidate: mocks.importCandidate,
    reviewCandidate: mocks.reviewCandidate,
  } },
}));
vi.mock("sonner", () => ({ toast: { success: mocks.success } }));
vi.mock("@/components/auth/auth-boundary", () => ({
  PermissionGate: ({ children }: { children: React.ReactNode }) => children,
}));

import { DossierActorCandidates } from "./dossier-actor-candidates";

describe("DossierActorCandidates", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.candidates.mockResolvedValue({
      data: [{
        id: "00000000-0000-4000-8000-000000000001",
        canonical_key: "catl",
        name: "CATL",
        suggested_actor_type: "organization",
        suggested_labels: ["baterías", "fabricante"],
        labels: [],
        status: "candidate",
        extraction_methods: ["text_pattern"],
        source_count: 1,
        existing_actor_id: null,
        sources: [{
          dossier_signal_id: "00000000-0000-4000-8000-000000000010",
          signal_id: "00000000-0000-4000-8000-000000000011",
          title: "CATL invierte en Zaragoza",
          source_name: "Fuente sectorial",
          source_url: "https://example.test/catl",
          excerpt: "Inversión industrial",
          published_at: null,
        }],
      }],
      meta: { total: 1 },
    });
    mocks.importCandidate.mockResolvedValue({ actor: { id: "actor-1" }, link: { id: "link-1" } });
    mocks.reviewCandidate.mockResolvedValue({ candidate: { status: "dismissed" } });
  });

  afterEach(cleanup);

  it("revisa tipo y etiquetas antes de importar con procedencia", async () => {
    const onImported = vi.fn();
    render(<DossierActorCandidates dossierId="dossier-1" onImported={onImported} />);
    fireEvent.click(await screen.findByRole("button", { name: "Revisar" }));
    expect(screen.getByText("CATL invierte en Zaragoza")).toBeVisible();
    fireEvent.change(screen.getByLabelText("Etiquetas (separadas por comas)"), {
      target: { value: "fabricante, socio industrial" },
    });
    fireEvent.change(screen.getByLabelText("Roles en este expediente (separados por comas)"), {
      target: { value: "competidor" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Incorporar actor" }));

    await waitFor(() => expect(mocks.importCandidate).toHaveBeenCalledWith(
      "dossier-1",
      "00000000-0000-4000-8000-000000000001",
      {
        actor_type: "organization",
        tags: ["fabricante", "socio industrial"],
        roles: ["competidor"],
      },
    ));
    expect(onImported).toHaveBeenCalled();
  });

  it("descarta candidatos y permite consultar los ya revisados", async () => {
    render(<DossierActorCandidates dossierId="dossier-1" onImported={vi.fn()} />);
    fireEvent.click((await screen.findAllByRole("button", { name: "Descartar CATL" }))[0]);

    await waitFor(() => expect(mocks.reviewCandidate).toHaveBeenCalledWith(
      "dossier-1",
      "00000000-0000-4000-8000-000000000001",
      { status: "dismissed" },
    ));
    fireEvent.click(screen.getByRole("checkbox", { name: "Mostrar descartados" }));
    await waitFor(() => expect(mocks.candidates).toHaveBeenLastCalledWith("dossier-1", true));
  });
});
