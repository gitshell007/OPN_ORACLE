import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { EntityGraphV2Explorer } from "./entity-graph-v2";

const mocks = vi.hoisted(() => ({
  graph: vi.fn(),
  push: vi.fn(),
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: mocks.push }),
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
      entityIntel: {
        graph: mocks.graph,
      },
    },
  };
});

const sampleGraph = {
  nodes: [
    { id: "magtel", label: "MAGTEL GLOBAL SL", type: "company", is_center: true, degree: 4, norm: "MAGTEL GLOBAL SL" },
    { id: "a", label: "FILIAL ALFA SL", type: "company", degree: 6, norm: "FILIAL ALFA SL" },
    { id: "b", label: "FILIAL BETA SL", type: "company", degree: 3, norm: "FILIAL BETA SL" },
    { id: "c", label: "PERSONA UNO", type: "person", degree: 2, norm: "PERSONA UNO" },
    { id: "d", label: "LEJANA SL", type: "company", degree: 1, norm: "LEJANA SL" },
  ],
  edges: [
    { id: "e1", source: "magtel", target: "a", role: "ADMINISTRADOR", active: true },
    { id: "e2", source: "magtel", target: "b", role: "SOCIO", active: true },
    { id: "e3", source: "magtel", target: "c", role: "APODERADO", active: true },
    { id: "e4", source: "a", target: "d", role: "SOCIO", active: true },
  ],
  truncated: false,
  cached_seconds: 60,
  cache_hit: false,
};

describe("EntityGraphV2Explorer", () => {
  beforeEach(() => {
    mocks.graph.mockReset();
    mocks.push.mockReset();
    mocks.graph.mockResolvedValue(sampleGraph);
  });

  afterEach(() => {
    cleanup();
  });

  it("renderiza vista radial con foco y anillo de 1er salto", async () => {
    render(
      <EntityGraphV2Explorer
        name="MAGTEL GLOBAL SL"
        type="company"
        initialGraph={sampleGraph}
      />,
    );

    expect(await screen.findByText(/Entorno de MAGTEL GLOBAL SL/i)).toBeInTheDocument();
    expect(screen.getByRole("img", { name: /Grafo radial de MAGTEL GLOBAL SL/i })).toBeInTheDocument();
    expect(screen.getAllByText(/1er salto/i).length).toBeGreaterThan(0);
    // Depth 2 node should not appear at default depth 1
    expect(screen.queryByText("LEJANA SL")).not.toBeInTheDocument();
    expect(screen.getByText("FILIAL ALFA SL")).toBeInTheDocument();
  });

  it("permite cambiar a directorio y listar vecinos", async () => {
    render(
      <EntityGraphV2Explorer
        name="MAGTEL GLOBAL SL"
        type="company"
        initialGraph={sampleGraph}
      />,
    );
    await screen.findByText(/Entorno de MAGTEL GLOBAL SL/i);
    fireEvent.click(screen.getByRole("tab", { name: /Directorio/i }));
    expect(await screen.findByRole("columnheader", { name: /Entidad/i })).toBeInTheDocument();
    expect(screen.getByText("PERSONA UNO")).toBeInTheDocument();
  });

  it("expone matriz de adyacencia como modo alternativo", async () => {
    render(
      <EntityGraphV2Explorer
        name="MAGTEL GLOBAL SL"
        type="company"
        initialGraph={sampleGraph}
      />,
    );
    await screen.findByText(/Entorno de MAGTEL GLOBAL SL/i);
    fireEvent.click(screen.getByRole("tab", { name: /Matriz/i }));
    expect(await screen.findByText(/Matriz de adyacencia/i)).toBeInTheDocument();
  });

  it("recarga el grafo con solo activos cuando se marca el filtro", async () => {
    render(
      <EntityGraphV2Explorer
        name="MAGTEL GLOBAL SL"
        type="company"
        initialGraph={sampleGraph}
      />,
    );
    await screen.findByText(/Entorno de MAGTEL GLOBAL SL/i);
    fireEvent.click(screen.getByLabelText(/Solo vínculos activos/i));
    await waitFor(() =>
      expect(mocks.graph).toHaveBeenCalledWith(
        expect.objectContaining({ name: "MAGTEL GLOBAL SL", activeOnly: true }),
      ),
    );
  });
});
