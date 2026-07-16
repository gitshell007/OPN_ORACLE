import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { renderToString } from "react-dom/server";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  push: vi.fn(),
  suggest: vi.fn(),
  graph: vi.fn(),
  cytoscapeInstances: [] as Array<{
    handlers: Record<string, (event: { target: { data(): unknown; closedNeighborhood?(): unknown; addClass?(name: string): void } }) => void>;
    destroy: ReturnType<typeof vi.fn>;
    on: ReturnType<typeof vi.fn>;
    removeListener: ReturnType<typeof vi.fn>;
  }>,
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
        graph: mocks.graph,
      },
    },
  };
});

vi.mock("cytoscape-fcose", () => ({ default: vi.fn() }));

vi.mock("cytoscape", () => {
  const factory = vi.fn(() => {
    const instance = {
      handlers: {} as Record<string, (event: { target: { data(): unknown; closedNeighborhood?(): unknown; addClass?(name: string): void } }) => void>,
      destroy: vi.fn(),
      elements: vi.fn(() => ({
        removeClass: vi.fn(),
        not: vi.fn(() => ({ addClass: vi.fn() })),
      })),
      on: vi.fn((event: string, _selector: string, handler: (event: { target: { data(): unknown; closedNeighborhood?(): unknown; addClass?(name: string): void } }) => void) => {
        instance.handlers[event] = handler;
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
    mocks.graph.mockResolvedValue(graphResponse);
  });

  afterEach(cleanup);

  it("abre ficha al pulsar un nodo y navega con el tipo correcto de la relación", async () => {
    render(<EntityGraphExplorer name="IBERDROLA" type="company" />);

    await waitFor(() => expect(mocks.graph).toHaveBeenCalledWith({
      name: "IBERDROLA",
      type: "company",
      depth: 2,
      activeOnly: true,
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
      "/app/actors/entity/person/BURGOS%20CANTO%20MIGUEL",
    );
  });
});
