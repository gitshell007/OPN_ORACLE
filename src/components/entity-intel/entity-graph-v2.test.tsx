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
    // Depth-2 only via BETA — must not appear when expanding ALFA.
    { id: "e", label: "OTRA LEJANA SL", type: "company", degree: 1, norm: "OTRA LEJANA SL" },
  ],
  edges: [
    { id: "e1", source: "magtel", target: "a", role: "ADMINISTRADOR", active: true },
    { id: "e2", source: "magtel", target: "b", role: "SOCIO", active: true },
    { id: "e3", source: "magtel", target: "c", role: "APODERADO", active: true },
    { id: "e4", source: "a", target: "d", role: "SOCIO", active: true },
    { id: "e5", source: "b", target: "e", role: "SOCIO", active: true },
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

  it("renderiza vista radial con foco y nombres en el anillo completo", async () => {
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
    expect(screen.queryByText("LEJANA SL")).not.toBeInTheDocument();
    // Labels on the full ring (not only one side): all 1-hop neighbors named.
    expect(screen.getByText("FILIAL ALFA SL")).toBeInTheDocument();
    expect(screen.getByText("FILIAL BETA SL")).toBeInTheDocument();
    expect(screen.getByText("PERSONA UNO")).toBeInTheDocument();
  });

  it("ofrece controles de zoom y reencuadre", async () => {
    render(
      <EntityGraphV2Explorer
        name="MAGTEL GLOBAL SL"
        type="company"
        initialGraph={sampleGraph}
      />,
    );
    await screen.findByText(/Entorno de MAGTEL GLOBAL SL/i);
    expect(screen.getByRole("button", { name: "Acercar" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Alejar" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Reencuadrar" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Acercar" }));
    expect(screen.getByText("115%")).toBeInTheDocument();
  });

  it("expande solo la rama del nodo seleccionado, no todo el 2º salto", async () => {
    render(
      <EntityGraphV2Explorer
        name="MAGTEL GLOBAL SL"
        type="company"
        initialGraph={sampleGraph}
      />,
    );
    await screen.findByText("FILIAL ALFA SL");
    expect(screen.queryByText("LEJANA SL")).not.toBeInTheDocument();
    expect(screen.queryByText("OTRA LEJANA SL")).not.toBeInTheDocument();

    fireEvent.click(screen.getByText("FILIAL ALFA SL"));
    expect(await screen.findByRole("button", { name: /Expandir vecinos \(1\)/i })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Expandir vecinos/i }));

    // Exclusive neighbor of ALFA appears…
    expect(await screen.findByText("LEJANA SL")).toBeInTheDocument();
    // …but BETA's exclusive depth-2 neighbor must stay hidden (branch-local expand).
    expect(screen.queryByText("OTRA LEJANA SL")).not.toBeInTheDocument();
    // 1er salto peers remain; global depth control was not forced to 2.
    expect(screen.getByText("FILIAL BETA SL")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Colapsar rama/i })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /Colapsar rama/i }));
    await waitFor(() => {
      expect(screen.queryByText("LEJANA SL")).not.toBeInTheDocument();
    });
    expect(screen.queryByText("OTRA LEJANA SL")).not.toBeInTheDocument();
  });

  it("permite centrar la exploración en otra entidad sin salir de la vista", async () => {
    render(
      <EntityGraphV2Explorer
        name="MAGTEL GLOBAL SL"
        type="company"
        initialGraph={sampleGraph}
      />,
    );
    await screen.findByText("FILIAL ALFA SL");
    fireEvent.click(screen.getByText("FILIAL ALFA SL"));
    fireEvent.click(await screen.findByRole("button", { name: /Centrar exploración aquí/i }));
    expect(await screen.findByText(/Entorno de FILIAL ALFA SL/i)).toBeInTheDocument();
    expect(screen.getByText(/Explorando desde un nodo secundario/i)).toBeInTheDocument();
  });

  it("filtra por familia de vínculo y al entrar muestra todas", async () => {
    render(
      <EntityGraphV2Explorer
        name="MAGTEL GLOBAL SL"
        type="company"
        initialGraph={sampleGraph}
      />,
    );
    await screen.findByText("FILIAL ALFA SL");
    // All families visible by default (administrador, socio, apoderado).
    expect(screen.getByText("PERSONA UNO")).toBeInTheDocument();
    expect(screen.getByText("FILIAL BETA SL")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Gobierno/i })).toHaveAttribute(
      "aria-pressed",
      "true",
    );

    // Solo Representación → apoderado (PERSONA UNO); no gobierno ni propiedad.
    fireEvent.doubleClick(screen.getByRole("button", { name: /Representación/i }));
    await waitFor(() => {
      expect(screen.getByText("PERSONA UNO")).toBeInTheDocument();
      expect(screen.queryByText("FILIAL ALFA SL")).not.toBeInTheDocument();
      expect(screen.queryByText("FILIAL BETA SL")).not.toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole("button", { name: /^Todas$/i }));
    expect(await screen.findByText("FILIAL ALFA SL")).toBeInTheDocument();
    expect(screen.getByText("FILIAL BETA SL")).toBeInTheDocument();
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
