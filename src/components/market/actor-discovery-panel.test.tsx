import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { MarketActorDiscoveryOutput } from "@oracle/api-client";

const mocks = vi.hoisted(() => ({
  getDossier: vi.fn(),
  latest: vi.fn(),
  run: vi.fn(),
  accept: vi.fn(),
  toastSuccess: vi.fn(),
  toastMessage: vi.fn(),
}));

vi.mock("@oracle/api-client", () => ({
  ApiError: class ApiError extends Error {
    problem = { detail: this.message };
    constructor(message: string) {
      super(message);
    }
  },
  api: {
    dossiers: { get: mocks.getDossier },
    marketActorDiscovery: {
      latest: mocks.latest,
      run: mocks.run,
      accept: mocks.accept,
    },
  },
}));

vi.mock("sonner", () => ({
  toast: { success: mocks.toastSuccess, message: mocks.toastMessage },
}));

import { ActorDiscoveryPanel } from "./actor-discovery-panel";

const INTENT =
  "quiero contactar con grupos de investigación en Francia que trabajen en grafeno";

const closedOutput: MarketActorDiscoveryOutput = {
  candidates: [
    {
      candidate_id: "11111111-1111-4111-8111-111111111111",
      actor_type: "research_group",
      organization: "Lab Grafeno CNRS",
      affiliation: "Université de Lorraine",
      country: "FR",
      summary: "Grupo con línea de grafeno en Francia.",
      rationale: "Coincide con la intención.",
      evidence_ids: ["22222222-2222-4222-8222-222222222222"],
      citable_sources: [
        {
          source_id: "22222222-2222-4222-8222-222222222222",
          title: "Paper grafeno",
          url: "https://example.org/grafeno",
          domain: "example.org",
          label: "Paper grafeno",
          origin_label: "Fuente encontrada por búsqueda",
        },
      ],
      confidence: 80,
      selectable: true,
    },
  ],
  warnings: [],
};

describe("ActorDiscoveryPanel G-19 live", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.getDossier.mockResolvedValue({
      id: "d1",
      dossier_type: "market",
      profile_config: {
        discovery_intent: INTENT,
        discovery_actor_type: "research_group",
      },
    });
    mocks.latest.mockResolvedValue({ job: null, artifact: null });
    mocks.run.mockResolvedValue({
      job: { id: "job-1", status: "queued" },
      artifact: null,
    });
    mocks.accept.mockResolvedValue({
      artifact_id: "a1",
      dossier_id: "d1",
      count: 1,
      materialized: [],
    });
  });

  afterEach(cleanup);

  it("no muestra ruido si el expediente no tiene discovery_intent", async () => {
    mocks.getDossier.mockResolvedValue({
      id: "d1",
      dossier_type: "market",
      profile_config: {},
    });
    render(<ActorDiscoveryPanel dossierId="d1" />);
    await waitFor(() => expect(mocks.getDossier).toHaveBeenCalledWith("d1"));
    expect(screen.queryByTestId("actor-discovery-panel")).not.toBeInTheDocument();
    expect(mocks.latest).not.toHaveBeenCalled();
  });

  it("consulta latest(dossier_id) y permite iniciar/reintentar con solo dossier_id", async () => {
    render(<ActorDiscoveryPanel dossierId="d1" />);
    expect(await screen.findByTestId("actor-discovery-panel")).toBeInTheDocument();
    await waitFor(() => expect(mocks.latest).toHaveBeenCalledWith("d1"));
    expect(screen.getByTestId("actor-discovery-idle")).toBeInTheDocument();
    expect(screen.getByTestId("actor-discovery-intent")).toHaveTextContent(/grafeno/i);

    fireEvent.click(screen.getByTestId("actor-discovery-retry"));
    await waitFor(() =>
      expect(mocks.run).toHaveBeenCalledWith(
        { dossier_id: "d1" },
        expect.stringMatching(/^g19-actor-run:d1:retry:/),
      ),
    );
  });

  it("renderiza organización, afiliación, FR y citas; accept envía IDs exactos", async () => {
    mocks.latest.mockResolvedValue({
      job: { id: "job-1", status: "succeeded" },
      artifact: {
        id: "artifact-1",
        dossier_id: "d1",
        agent: "market_actor_discovery",
        schema_name: "MarketActorDiscoveryOutput",
        schema_version: "v1",
        status: "candidate",
        version: 3,
        created_at: "2026-08-06T00:00:00Z",
        updated_at: "2026-08-06T00:00:00Z",
        output: closedOutput,
      },
    });
    render(<ActorDiscoveryPanel dossierId="d1" />);
    expect(await screen.findByTestId("actor-discovery-result")).toBeInTheDocument();
    expect(screen.getByText("Lab Grafeno CNRS")).toBeInTheDocument();
    expect(screen.getByText("Université de Lorraine")).toBeInTheDocument();
    expect(screen.getByTestId("actor-type")).toHaveTextContent(/investigación/i);
    expect(screen.getByText("FR")).toBeInTheDocument();
    expect(screen.getByTestId("actor-source-link")).toHaveAttribute(
      "href",
      "https://example.org/grafeno",
    );

    fireEvent.click(screen.getByLabelText(/Seleccionar Lab Grafeno CNRS/i));
    fireEvent.click(screen.getByTestId("actor-discovery-accept"));

    await waitFor(() =>
      expect(mocks.accept).toHaveBeenCalledWith({
        dossier_id: "d1",
        artifact_id: "artifact-1",
        expected_version: 3,
        selected: [
          {
            candidate_id: "11111111-1111-4111-8111-111111111111",
            organization: "Lab Grafeno CNRS",
            source_ids: ["22222222-2222-4222-8222-222222222222"],
          },
        ],
      }),
    );
    expect(mocks.toastSuccess).toHaveBeenCalledWith(
      "Fuentes materializadas",
      expect.objectContaining({
        description: expect.stringMatching(/No se ha creado un Actor/i),
      }),
    );
  });

  it("latest de D1 no se invoca para D2 en el mismo montaje", async () => {
    const { rerender } = render(<ActorDiscoveryPanel dossierId="d1" />);
    await waitFor(() => expect(mocks.latest).toHaveBeenCalledWith("d1"));
    mocks.latest.mockClear();
    rerender(<ActorDiscoveryPanel dossierId="d2" />);
    await waitFor(() => expect(mocks.getDossier).toHaveBeenCalledWith("d2"));
    await waitFor(() => expect(mocks.latest).toHaveBeenCalledWith("d2"));
    expect(mocks.latest).not.toHaveBeenCalledWith("d1");
  });

  it("muestra estados loading y error accesibles", async () => {
    let resolveGet: (v: unknown) => void = () => undefined;
    mocks.getDossier.mockReturnValue(
      new Promise((resolve) => {
        resolveGet = resolve;
      }),
    );
    render(<ActorDiscoveryPanel dossierId="d1" />);
    expect(screen.getByTestId("actor-discovery-loading")).toBeInTheDocument();
    resolveGet({
      id: "d1",
      dossier_type: "market",
      profile_config: {
        discovery_intent: INTENT,
        discovery_actor_type: "research_group",
      },
    });
    mocks.latest.mockRejectedValue(new Error("boom"));
    await waitFor(() =>
      expect(screen.getByTestId("actor-discovery-error")).toBeInTheDocument(),
    );
  });
});
