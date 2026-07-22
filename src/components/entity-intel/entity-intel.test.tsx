import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { renderToString } from "react-dom/server";
import type { Mock } from "vitest";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

type MockGraphEvent = {
  target: { data(): unknown; closedNeighborhood?(): unknown; addClass?(name: string): void };
};
type MockElement = {
  id: Mock<() => string>;
  addClass: Mock<(name: string) => void>;
  removeClass: Mock<(name: string) => void>;
  hasClass: Mock<(name: string) => boolean>;
  data: Mock<(key?: string) => unknown>;
  connectedEdges: Mock<() => MockCollection>;
  closedNeighborhood: Mock<() => MockCollection>;
  position: Mock<(next?: { x: number; y: number } | "x" | "y") => { x: number; y: number } | number>;
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
  elements: Array<{
    data: Record<string, unknown>;
    position?: { x: number; y: number };
    classes?: string;
  }>;
  layout: Record<string, unknown>;
  style: Array<Record<string, unknown>>;
};
type MockCytoscapeInstance = {
  options: MockCytoscapeOptions;
  nodesList: MockElement[];
  edgesList: MockElement[];
  handlers: Record<string, (event: MockGraphEvent) => void>;
  destroy: Mock<() => void>;
  fit: Mock<(...args: unknown[]) => void>;
  center: Mock<() => void>;
  batch: Mock<(callback: () => void) => void>;
  maxZoom: Mock<() => number>;
  minZoom: Mock<() => number>;
  zoom: Mock<(next?: number | { level: number }) => number>;
  container: Mock<() => { getBoundingClientRect: () => { width: number; height: number } }>;
  elements: Mock<() => MockCollection>;
  nodes: Mock<(selector?: string) => MockCollection>;
  edges: Mock<() => MockCollection>;
  getElementById: Mock<(id: string) => MockCollection>;
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

  function element(
    data: Record<string, unknown>,
    initialClasses = "",
    initialPosition = { x: 0, y: 0 },
  ): MockElement {
    const classes = new Set(initialClasses.split(" ").filter(Boolean));
    let position = { ...initialPosition };
    return {
      id: vi.fn(() => String(data.id)),
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
      position: vi.fn((next?: { x: number; y: number } | "x" | "y") => {
        if (next === "x" || next === "y") return position[next];
        if (next) position = { ...next };
        return { ...position };
      }),
      classes,
    };
  }

  const factory = vi.fn((options: MockCytoscapeOptions) => {
    const nodes = options.elements
      .filter((item) => !item.data.source)
      .map((item) => element(item.data, item.classes, item.position));
    const edges = options.elements
      .filter((item) => item.data.source)
      .map((item) => element(item.data, item.classes));
    const nodesById = new Map(nodes.map((node) => [node.id(), node]));
    for (const node of nodes) {
      const connected = edges.filter((edge) => (
        String(edge.data("source")) === node.id() || String(edge.data("target")) === node.id()
      ));
      const neighbors = connected.flatMap((edge) => {
        const otherId = String(edge.data("source")) === node.id()
          ? String(edge.data("target"))
          : String(edge.data("source"));
        const other = nodesById.get(otherId);
        return other ? [other] : [];
      });
      node.connectedEdges.mockReturnValue(collection(connected));
      node.closedNeighborhood.mockReturnValue(collection([node, ...neighbors, ...connected]));
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
      getElementById: vi.fn((id: string) => collection(nodes.filter((node) => node.id() === id))),
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

import {
  EntityGraphExplorer,
  EntitySearchPanel,
} from "./entity-intel";
import { separateGraphNodePositions } from "./entity-graph-layout";

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

  it("descarta respuestas obsoletas del suggest y mantiene la consulta actual", async () => {
    vi.useFakeTimers();
    const resolvers = new Map<string, (value: unknown) => void>();
    mocks.suggest.mockImplementation(({ q }: { q: string }) => new Promise((resolve) => {
      resolvers.set(q, resolve);
    }));

    render(<EntitySearchPanel compact />);

    fireEvent.change(screen.getByLabelText("Entidad"), { target: { value: "ITU" } });
    await act(async () => {
      vi.advanceTimersByTime(260);
    });

    fireEvent.change(screen.getByLabelText("Entidad"), { target: { value: "ITURRI" } });
    await act(async () => {
      vi.advanceTimersByTime(260);
    });

    await act(async () => {
      resolvers.get("ITURRI")?.({
        kind: "company",
        suggestions: ["ITURRI SA", "ITURRIN SA"],
        cached_seconds: 600,
        cache_hit: false,
      });
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(screen.getByText("ITURRI SA")).toBeInTheDocument();

    await act(async () => {
      resolvers.get("ITU")?.({
        kind: "company",
        suggestions: ["ITUAS SL", "ITUBRE SL"],
        cached_seconds: 600,
        cache_hit: false,
      });
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(screen.queryByText("ITUAS SL")).not.toBeInTheDocument();
    expect(screen.getByText("ITURRI SA")).toBeInTheDocument();
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

  it("abre ficha con doble pulsación y navega con el tipo correcto de la relación", async () => {
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

    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(screen.getByText(/IBERDROLA CLIENTES ESPAÑA SOCIEDAD ANONIMA · 1 relaciones/)).toBeInTheDocument();

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

  it("deriva los tipos de vínculo, agrupa capitalizaciones y los marca todos al cargar", async () => {
    mocks.graph.mockResolvedValue({
      ...graphResponse,
      edges: [
        ...graphResponse.edges,
        {
          id: "edge-3",
          source: "ib",
          target: "miguel",
          role: "socio único",
          active: true,
          date: "2025-02-01",
        },
        {
          id: "edge-4",
          source: "ib",
          target: "ana",
          role: "Socio único",
          active: true,
          date: "2025-03-01",
        },
      ],
    });

    render(<EntityGraphExplorer name="IBERDROLA" type="company" />);

    const roleGroup = await screen.findByRole("group", { name: "Tipos de vínculo" });
    const roleChecks = within(roleGroup).getAllByRole("checkbox");
    expect(roleChecks).toHaveLength(3);
    roleChecks.forEach((checkbox) => expect(checkbox).toBeChecked());
    expect(
      within(roleGroup).getByRole("checkbox", { name: /Socio único, 2 vínculos/i }),
    ).toBeChecked();
    expect(within(roleGroup).queryAllByText(/socio único/i)).toHaveLength(1);
  });

  it("compone el filtro por rol con el cronograma sin revivir aristas temporales", async () => {
    render(<EntityGraphExplorer name="IBERDROLA" type="company" />);

    await waitFor(() => expect(mocks.cytoscapeInstances).toHaveLength(1));
    const instance = mocks.cytoscapeInstances[0];
    fireEvent.change(screen.getByLabelText("Fecha inicial del cronograma"), {
      target: { value: "365" },
    });
    await waitFor(() => expect(instance.edgesList[1].classes.has("is-time-filtered")).toBe(true));

    const apoderado = screen.getByRole("checkbox", { name: /Apoderado, 1 vínculo/i });
    fireEvent.click(apoderado);
    await waitFor(() => expect(instance.edgesList[1].classes.has("is-role-filtered")).toBe(true));
    fireEvent.click(apoderado);

    await waitFor(() => {
      expect(instance.edgesList[1].classes.has("is-role-filtered")).toBe(false);
      expect(instance.edgesList[1].classes.has("is-time-filtered")).toBe(true);
    });
    expect(mocks.cytoscapeInstances).toHaveLength(1);
  });

  it("ofrece los niveles existentes y oculta los saltos posteriores sin relayout", async () => {
    mocks.graph.mockResolvedValue({
      ...graphResponse,
      nodes: [
        ...graphResponse.nodes,
        { id: "remote", label: "NODO DE SEGUNDO NIVEL", type: "company", degree: 1 },
      ],
      edges: [
        ...graphResponse.edges,
        {
          id: "edge-remote",
          source: "miguel",
          target: "remote",
          role: "Consejero",
          active: true,
          date: "2026-06-01",
        },
      ],
    });

    render(<EntityGraphExplorer name="ITURRI SA" type="company" />);

    const depthSelect = await screen.findByLabelText("Número de niveles visibles");
    const options = within(depthSelect).getAllByRole("option");
    expect(options).toHaveLength(2);
    expect(options[0]).toHaveTextContent("Hasta nivel 1 · 3 nodos");
    expect(options[1]).toHaveTextContent("Hasta nivel 2 · 4 nodos");
    expect(depthSelect).toHaveValue("2");

    await waitFor(() => expect(mocks.cytoscapeInstances).toHaveLength(1));
    const instance = mocks.cytoscapeInstances[0];
    fireEvent.change(depthSelect, { target: { value: "1" } });

    await waitFor(() => {
      expect(instance.nodesList[3].classes.has("is-depth-filtered")).toBe(true);
      expect(instance.edgesList[2].classes.has("is-depth-filtered")).toBe(true);
    });
    expect(instance.nodesList[1].classes.has("is-depth-filtered")).toBe(false);
    expect(instance.edgesList[0].classes.has("is-depth-filtered")).toBe(false);
    expect(screen.getByText(/2 de 3 vínculos visibles/)).toBeInTheDocument();
    expect(mocks.cytoscapeInstances).toHaveLength(1);

    fireEvent.change(depthSelect, { target: { value: "2" } });
    await waitFor(() => {
      expect(instance.nodesList[3].classes.has("is-depth-filtered")).toBe(false);
      expect(instance.edgesList[2].classes.has("is-depth-filtered")).toBe(false);
    });
  });

  it("aísla vecinos directos al seleccionar y restaura al pulsar el mismo nodo", async () => {
    mocks.graph.mockResolvedValue({
      ...graphResponse,
      nodes: [
        ...graphResponse.nodes,
        { id: "remote", label: "NODO DE SEGUNDO NIVEL", type: "company", degree: 1 },
      ],
      edges: [
        ...graphResponse.edges,
        {
          id: "edge-remote",
          source: "miguel",
          target: "remote",
          role: "Consejero",
          active: true,
          date: "2026-06-01",
        },
      ],
    });
    const clock = vi.spyOn(Date, "now")
      .mockReturnValueOnce(1_000)
      .mockReturnValueOnce(1_500);

    render(<EntityGraphExplorer name="IBERDROLA" type="company" />);

    await waitFor(() => expect(mocks.cytoscapeInstances).toHaveLength(1));
    const instance = mocks.cytoscapeInstances[0];
    act(() => instance.handlers.tap({ target: instance.nodesList[0] }));

    await waitFor(() => {
      expect(instance.nodesList[3].classes.has("is-focus-filtered")).toBe(true);
      expect(instance.edgesList[2].classes.has("is-focus-filtered")).toBe(true);
    });
    expect(instance.nodesList[1].classes.has("is-focus-filtered")).toBe(false);
    expect(instance.fit).toHaveBeenCalled();

    act(() => instance.handlers.tap({ target: instance.nodesList[0] }));

    await waitFor(() => {
      expect(instance.nodesList[3].classes.has("is-focus-filtered")).toBe(false);
      expect(instance.edgesList[2].classes.has("is-focus-filtered")).toBe(false);
    });
    clock.mockRestore();
  });

  it("arranca con encuadre navegable y controles de zoom visibles", async () => {
    render(<EntityGraphExplorer name="IBERDROLA" type="company" />);

    await waitFor(() => expect(mocks.cytoscapeInstances).toHaveLength(1));
    await waitFor(() => expect(mocks.cytoscapeInstances[0].center).toHaveBeenCalled());
    expect(mocks.cytoscapeInstances[0].fit).not.toHaveBeenCalled();

    const instance = mocks.cytoscapeInstances[0];
    expect(instance.options.layout).toMatchObject({
      fit: false,
      nodeSeparation: 156,
      idealEdgeLength: 250,
      randomize: false,
    });

    fireEvent.click(screen.getByRole("button", { name: "Acercar grafo" }));
    expect(instance.zoom).toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "Volver al encuadre inicial" }));
    expect(instance.center).toHaveBeenCalled();
  });

  it("siembra posiciones deterministas no degeneradas antes de ejecutar fcose", async () => {
    const denseGraph = {
      ...graphResponse,
      nodes: [
        graphResponse.nodes[0],
        ...Array.from({ length: 32 }, (_, index) => ({
          id: `node-${index}`,
          label: `Nodo ${index}`,
          type: index % 2 === 0 ? "company" : "person",
          degree: 1,
        })),
      ],
      edges: Array.from({ length: 32 }, (_, index) => ({
        id: `edge-${index}`,
        source: "ib",
        target: `node-${index}`,
        role: "Relación",
        active: true,
        date: "2026-07-01",
      })),
    };
    mocks.graph.mockResolvedValue(denseGraph);

    render(<EntityGraphExplorer name="ITURRI SA" type="company" />);

    await waitFor(() => expect(mocks.cytoscapeInstances).toHaveLength(1));
    const nodeElements = mocks.cytoscapeInstances[0].options.elements.filter(
      (item) => !item.data.source,
    );
    const positions = nodeElements.map((item) => item.position);
    expect(positions.every(Boolean)).toBe(true);
    expect(positions[0]).toEqual({ x: 0, y: 0 });

    const distinctX = new Set(positions.map((position) => position?.x));
    const distinctY = new Set(positions.map((position) => position?.y));
    const diagonalKeys = new Set(
      positions.map((position) => (
        position ? Math.round((position.y - position.x) * 10) / 10 : null
      )),
    );
    expect(distinctX.size).toBeGreaterThan(12);
    expect(distinctY.size).toBeGreaterThan(12);
    expect(diagonalKeys.size).toBeGreaterThan(12);
    expect(mocks.cytoscapeInstances[0].options.layout).toMatchObject({ randomize: false });
  });

  it("mantiene un hueco visible entre 300 nodos aunque el layout los entregue solapados", () => {
    const separated = separateGraphNodePositions(Array.from({ length: 300 }, (_, index) => ({
      id: index === 0 ? "center" : `node-${index}`,
      x: 0,
      y: 0,
      radius: index === 0 ? 23 : 15,
      anchored: index === 0,
    })));

    expect(separated.find((node) => node.id === "center")).toMatchObject({ x: 0, y: 0 });
    for (let leftIndex = 0; leftIndex < separated.length; leftIndex += 1) {
      for (let rightIndex = leftIndex + 1; rightIndex < separated.length; rightIndex += 1) {
        const left = separated[leftIndex];
        const right = separated[rightIndex];
        const distance = Math.hypot(right.x - left.x, right.y - left.y);
        expect(distance).toBeGreaterThanOrEqual(left.radius + right.radius + 14 - 0.01);
      }
    }
  });

  it("al pasar por el nodo central no revela las etiquetas de toda su vecindad", async () => {
    render(<EntityGraphExplorer name="ITURRI SA" type="company" />);

    await waitFor(() => expect(mocks.cytoscapeInstances).toHaveLength(1));
    const instance = mocks.cytoscapeInstances[0];
    act(() => instance.handlers.mouseover({ target: instance.nodesList[0] }));

    expect(instance.nodesList[0].classes.has("is-hovered")).toBe(true);
    expect(instance.nodesList[0].classes.has("is-hover-label")).toBe(true);
    expect(instance.nodesList[1].classes.has("is-hover-label")).toBe(false);
    expect(instance.edgesList[0].classes.has("is-hover-label")).toBe(false);
  });

  it("solo activa todas las etiquetas al alcanzar un zoom de lectura", async () => {
    render(<EntityGraphExplorer name="ITURRI SA" type="company" />);

    await waitFor(() => expect(mocks.cytoscapeInstances).toHaveLength(1));
    const instance = mocks.cytoscapeInstances[0];
    expect(instance.nodesList[1].classes.has("is-readable-zoom")).toBe(false);

    instance.zoom({ level: 1.6 });
    act(() => instance.handlers.zoom({ target: instance.nodesList[0] }));

    expect(instance.nodesList[1].classes.has("is-readable-zoom")).toBe(true);
    expect(instance.edgesList[0].classes.has("is-readable-zoom")).toBe(true);
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
    expect(instance.options.style).toContainEqual(expect.objectContaining({
      selector: "node.is-orphaned-after-filter",
      style: expect.objectContaining({ display: "none" }),
    }));
    expect(mocks.cytoscapeInstances).toHaveLength(1);
  });
});
