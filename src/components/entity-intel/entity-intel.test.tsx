import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { renderToString } from "react-dom/server";
import type { Mock } from "vitest";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

type MockGraphEvent = {
  target: { data(): unknown; closedNeighborhood?(): unknown; addClass?(name: string): void };
};
type MockElement = {
  addClass: Mock<(name: string) => void>;
  removeClass: Mock<(name: string) => void>;
  hasClass: Mock<(name: string) => boolean>;
  data: Mock<(key?: string) => unknown>;
  connectedEdges: Mock<() => MockCollection>;
  closedNeighborhood: Mock<() => MockCollection>;
  classes: Set<string>;
};
type MockCollection = MockElement[] & {
  addClass: Mock<(name: string) => MockCollection>;
  removeClass: Mock<(name: string) => MockCollection>;
  not: Mock<() => { addClass: Mock<() => void> }>;
  first: Mock<() => MockCollection>;
  closedNeighborhood: Mock<() => MockCollection>;
};
type MockCytoscapeOptions = {
  elements: Array<{ data: Record<string, unknown>; classes?: string }>;
  layout: Record<string, unknown>;
};
type MockCytoscapeInstance = {
  options: MockCytoscapeOptions;
  nodesList: MockElement[];
  edgesList: MockElement[];
  handlers: Record<string, (event: MockGraphEvent) => void>;
  destroy: Mock<() => void>;
  fit: Mock<() => void>;
  center: Mock<() => void>;
  batch: Mock<(callback: () => void) => void>;
  maxZoom: Mock<() => number>;
  minZoom: Mock<() => number>;
  zoom: Mock<(next?: number | { level: number }) => number>;
  container: Mock<() => { getBoundingClientRect: () => { width: number; height: number } }>;
  elements: Mock<() => MockCollection>;
  nodes: Mock<(selector?: string) => MockCollection>;
  edges: Mock<() => MockCollection>;
  on: Mock<(event: string, selectorOrHandler: unknown, maybeHandler?: (event: MockGraphEvent) => void) => void>;
  removeListener: Mock<() => void>;
};

const mocks = vi.hoisted(() => ({
  push: vi.fn(),
  suggest: vi.fn(),
  registry: vi.fn(),
  graph: vi.fn(),
  cytoscapeInstances: [] as MockCytoscapeInstance[],
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: mocks.push }),
}));

vi.mock("@oracle/api-client", () => {
  class ApiError extends Error {
    constructor(public problem: { detail: string }) {
      super(problem.detail);
    }
  }
  return {
    ApiError,
    api: {
      entityIntel: {
        suggest: mocks.suggest,
        registry: mocks.registry,
        graph: mocks.graph,
      },
    },
  };
});

vi.mock("cytoscape-fcose", () => ({ default: vi.fn() }));

vi.mock("cytoscape", () => {
  function collection(items: MockElement[]): MockCollection {
    const list = [...items] as MockCollection;
    list.addClass = vi.fn((name: string) => {
      list.forEach((item) => item.addClass?.(name));
      return list;
    });
    list.removeClass = vi.fn((name: string) => {
      list.forEach((item) => item.removeClass?.(name));
      return list;
    });
    list.not = vi.fn(() => ({ addClass: vi.fn() }));
    list.first = vi.fn(() => collection(list.length ? [list[0]] : []));
    list.closedNeighborhood = vi.fn(() => collection(list));
    return list;
  }

  function element(data: Record<string, unknown>, initialClasses = ""): MockElement {
    const classes = new Set(initialClasses.split(" ").filter(Boolean));
    return {
      addClass: vi.fn((name: string) => {
        for (const item of name.split(" ")) classes.add(item);
      }),
      removeClass: vi.fn((name: string) => {
        for (const item of name.split(" ")) classes.delete(item);
      }),
      hasClass: vi.fn((name: string) => classes.has(name)),
      data: vi.fn((key?: string) => (key ? data[key] : data)),
      connectedEdges: vi.fn(() => collection([])),
      closedNeighborhood: vi.fn(() => collection([])),
      classes,
    };
  }

  const factory = vi.fn((options: MockCytoscapeOptions) => {
    const nodes = options.elements
      .filter((item) => !item.data.source)
      .map((item) => element(item.data, item.classes));
    const edges = options.elements
      .filter((item) => item.data.source)
      .map((item) => element(item.data, item.classes));
    for (const node of nodes) {
      node.connectedEdges.mockReturnValue(collection(edges));
      node.closedNeighborhood.mockReturnValue(collection([node, ...edges]));
    }
    let zoomLevel = 1;
    const instance = {
      options,
      nodesList: nodes,
      edgesList: edges,
      handlers: {} as Record<string, (event: { target: { data(): unknown; closedNeighborhood?(): unknown; addClass?(name: string): void } }) => void>,
      destroy: vi.fn(),
      fit: vi.fn(),
      center: vi.fn(),
      batch: vi.fn((callback: () => void) => callback()),
      maxZoom: vi.fn(() => 2.2),
      minZoom: vi.fn(() => 0.35),
      zoom: vi.fn((next?: number | { level: number }) => {
        if (typeof next === "number") zoomLevel = next;
        if (next && typeof next === "object") zoomLevel = next.level;
        return zoomLevel;
      }),
      container: vi.fn(() => ({ getBoundingClientRect: () => ({ width: 900, height: 620 }) })),
      elements: vi.fn(() => collection([...nodes, ...edges])),
      nodes: vi.fn((selector?: string) => (
        selector === ".is-center-node"
          ? collection(nodes.filter((node) => node.hasClass("is-center-node")))
          : collection(nodes)
      )),
      edges: vi.fn(() => collection(edges)),
      on: vi.fn((event: string, selectorOrHandler: unknown, maybeHandler?: (event: MockGraphEvent) => void) => {
        const handler = typeof selectorOrHandler === "function"
          ? selectorOrHandler as (event: MockGraphEvent) => void
          : maybeHandler;
        if (handler) instance.handlers[event] = handler;
      }),
      removeListener: vi.fn(),
    };
    mocks.cytoscapeInstances.push(instance);
    return instance;
  });
  Object.assign(factory, { use: vi.fn() });
  return { default: factory };
});

import { EntityGraphExplorer, EntitySearchPanel } from "./entity-intel";

const graphResponse = {
  center: "IBERDROLA",
  nodes: [
    {
      id: "ib",
      label: "IBERDROLA CLIENTES ESPAÑA SOCIEDAD ANONIMA",
      type: "company",
      is_center: true,
      degree: 1,
    },
    {
      id: "miguel",
      label: "BURGOS CANTO MIGUEL",
      norm: "BURGOS CANTO MIGUEL NORMALIZADO",
      type: "person",
      degree: 1,
    },
    {
      id: "ana",
      label: "ANA REGISTRAL",
      norm: "ANA REGISTRAL NORMALIZADA",
      type: "person",
      degree: 1,
    },
  ],
  edges: [
    {
      id: "edge-1",
      source: "ib",
      target: "miguel",
      role: "Administrador",
      active: true,
      date: "2026-07-01",
    },
    {
      id: "edge-2",
      source: "ib",
      target: "ana",
      role: "Apoderado",
      active: false,
      date: "2024-01-01",
    },
  ],
  truncated: false,
  cached_seconds: 600,
  cache_hit: false,
};

describe("EntitySearchPanel", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    window.sessionStorage.clear();
    mocks.suggest.mockResolvedValue({
      kind: "person",
      suggestions: [],
      cached_seconds: 600,
      cache_hit: false,
    });
  });

  afterEach(() => {
    cleanup();
    vi.useRealTimers();
  });

  it("retrasa la lectura de sessionStorage hasta después de hidratar", async () => {
    vi.useFakeTimers();
    window.sessionStorage.setItem("opn:entity-intel:kind", "person");

    const serverHtml = renderToString(<EntitySearchPanel compact />);
    expect(serverHtml).toContain('<option value="company" selected="">Empresa</option>');

    render(<EntitySearchPanel compact />);
    const typeSelect = screen.getByLabelText("Tipo") as HTMLSelectElement;
    expect(typeSelect.value).toBe("company");

    await act(async () => {
      vi.runOnlyPendingTimers();
    });

    expect(typeSelect.value).toBe("person");
    vi.useRealTimers();
  });

  it("no pisa la elección del usuario con la preferencia diferida", async () => {
    vi.useFakeTimers();
    window.sessionStorage.setItem("opn:entity-intel:kind", "company");
    render(<EntitySearchPanel compact />);
    const typeSelect = screen.getByLabelText("Tipo") as HTMLSelectElement;

    fireEvent.change(typeSelect, { target: { value: "person" } });
    await act(async () => {
      vi.runOnlyPendingTimers();
    });

    expect(typeSelect.value).toBe("person");
    vi.useRealTimers();
  });

  it("persiste el tipo elegido y prioriza initialKind explícito", async () => {
    window.sessionStorage.setItem("opn:entity-intel:kind", "person");
    const { rerender } = render(<EntitySearchPanel compact />);

    const typeSelect = screen.getByLabelText("Tipo") as HTMLSelectElement;
    await waitFor(() => expect(typeSelect.value).toBe("person"));

    fireEvent.change(typeSelect, { target: { value: "company" } });
    expect(window.sessionStorage.getItem("opn:entity-intel:kind")).toBe("company");

    rerender(<EntitySearchPanel initialQuery="Miguel Burgos" initialKind="person" compact />);
    await waitFor(() => expect((screen.getByLabelText("Tipo") as HTMLSelectElement).value).toBe("person"));
    await waitFor(() => expect(screen.getByLabelText("Entidad")).toHaveValue("Miguel Burgos"));

    rerender(<EntitySearchPanel initialQuery="Burgos Canto Miguel" initialKind="person" compact />);
    await waitFor(() => expect(screen.getByLabelText("Entidad")).toHaveValue("Burgos Canto Miguel"));
  });

  it("muestra ayuda de orden de apellidos cuando no hay sugerencias de persona", async () => {
    render(<EntitySearchPanel initialKind="person" compact />);

    fireEvent.change(screen.getByLabelText("Entidad"), { target: { value: "Miguel Burgos" } });

    expect(
      await screen.findByText(/Probamos ambos órdenes automáticamente/i),
    ).toBeInTheDocument();
  });
});

describe("EntityGraphExplorer", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.cytoscapeInstances.length = 0;
    mocks.suggest.mockResolvedValue({
      kind: "company",
      suggestions: [],
      cached_seconds: 600,
      cache_hit: false,
    });
    mocks.registry.mockResolvedValue({
      items: [],
      total: 0,
      cached_seconds: 600,
      cache_hit: false,
    });
    mocks.graph.mockResolvedValue(graphResponse);
  });

  afterEach(cleanup);

  it("abre ficha al pulsar un nodo y navega con el tipo correcto de la relación", async () => {
    render(<EntityGraphExplorer name="IBERDROLA" type="company" />);

    await waitFor(() => expect(mocks.graph).toHaveBeenCalledWith({
      name: "IBERDROLA",
      type: "company",
      depth: 2,
      activeOnly: false,
    }));
    await waitFor(() => expect(mocks.cytoscapeInstances).toHaveLength(1));

    act(() => {
      mocks.cytoscapeInstances[0].handlers.tap({
        target: {
          data: () => graphResponse.nodes[0],
          closedNeighborhood: () => ({}),
          addClass: vi.fn(),
        },
      });
    });

    expect(await screen.findByRole("dialog")).toBeInTheDocument();
    expect(screen.getAllByText("IBERDROLA CLIENTES ESPAÑA SOCIEDAD ANONIMA")).not.toHaveLength(0);

    fireEvent.click(screen.getByRole("button", { name: /BURGOS CANTO MIGUEL/i }));
    fireEvent.click(screen.getByRole("button", { name: /Consultar/i }));

    expect(mocks.push).toHaveBeenCalledWith(
      "/app/actors/entity/person/BURGOS%20CANTO%20MIGUEL%20NORMALIZADO",
    );
  });

  it("recarga con solo activos cuando se activa el filtro", async () => {
    render(<EntityGraphExplorer name="IBERDROLA" type="company" />);

    await waitFor(() => expect(mocks.graph).toHaveBeenCalledWith({
      name: "IBERDROLA",
      type: "company",
      depth: 2,
      activeOnly: false,
    }));

    fireEvent.click(await screen.findByLabelText("Solo vínculos activos"));

    await waitFor(() => expect(mocks.graph).toHaveBeenLastCalledWith({
      name: "IBERDROLA",
      type: "company",
      depth: 2,
      activeOnly: true,
    }));
  });

  it("arranca con encuadre navegable y controles de zoom visibles", async () => {
    render(<EntityGraphExplorer name="IBERDROLA" type="company" />);

    await waitFor(() => expect(mocks.cytoscapeInstances).toHaveLength(1));
    await waitFor(() => expect(mocks.cytoscapeInstances[0].fit).toHaveBeenCalled());

    const instance = mocks.cytoscapeInstances[0];
    expect(instance.options.layout).toMatchObject({
      fit: false,
      randomize: false,
    });

    fireEvent.click(screen.getByRole("button", { name: "Acercar grafo" }));
    expect(instance.zoom).toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "Volver al encuadre inicial" }));
    expect(instance.center).toHaveBeenCalled();
  });

  it("filtra el grafo por cronograma sin reconstruir elementos", async () => {
    render(<EntityGraphExplorer name="IBERDROLA" type="company" />);

    await waitFor(() => expect(mocks.cytoscapeInstances).toHaveLength(1));
    const instance = mocks.cytoscapeInstances[0];

    const startInput = screen.getByLabelText("Fecha inicial del cronograma");
    fireEvent.change(startInput, { target: { value: "365" } });

    await waitFor(() => {
      expect(instance.edgesList[1].addClass).toHaveBeenCalledWith("is-time-filtered");
    });
    expect(mocks.cytoscapeInstances).toHaveLength(1);
  });
});
