import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  push: vi.fn(),
  dossier: vi.fn(),
  registry: vi.fn(),
  suggest: vi.fn(),
  graph: vi.fn(),
  dossiersList: vi.fn(),
  attachActor: vi.fn(),
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
      actors: {
        attach: mocks.attachActor,
      },
      dossiers: {
        list: mocks.dossiersList,
      },
      entityIntel: {
        dossier: mocks.dossier,
        registry: mocks.registry,
        suggest: mocks.suggest,
        graph: mocks.graph,
      },
    },
  };
});

vi.mock("@/components/auth/auth-boundary", () => ({
  PermissionGate: ({ children }: { children: ReactNode }) => <>{children}</>,
}));

vi.mock("cytoscape", () => ({ default: Object.assign(vi.fn(() => ({
  destroy: vi.fn(),
  elements: vi.fn(() => ({ removeClass: vi.fn(), not: vi.fn(() => ({ addClass: vi.fn() })) })),
  on: vi.fn(),
  removeListener: vi.fn(),
})), { use: vi.fn() }) }));
vi.mock("cytoscape-fcose", () => ({ default: vi.fn() }));

import { EntityDossier } from "./entity-dossier";

const dossierResponse = {
  entity: { name: "IBERDROLA CLIENTES ESPAÑA SOCIEDAD ANONIMA", type: "company" },
  sections: {
    registry: {
      ok: true,
      data: {
        query: "IBERDROLA",
        total: 3,
        profile: {
          status: "activa",
          constitution_date: "2001-02-03",
          provinces: ["BIZKAIA", "MADRID"],
          total_acts: 3,
          first_act_date: "2001-02-10",
          last_act_date: "2026-07-01",
        },
        items: [
          {
            person: "BURGOS CANTO MIGUEL",
            role: "Administrador",
            action: "nombramiento",
            date: "2026-07-01",
            province: "BIZKAIA",
            source_url: "https://boe.test/1",
          },
          {
            person: "PEREZ LOPEZ ANA",
            role: "Consejera",
            action: "cese",
            date: "2025-01-01",
            province: "MADRID",
            source_url: "https://boe.test/2",
          },
          {
            person: "PEREZ LOPEZ ANA",
            role: "Consejera",
            action: "nombramiento",
            date: "2019-01-01",
            province: "MADRID",
            source_url: "https://boe.test/3",
          },
        ],
        cached_seconds: 600,
        cache_hit: false,
      },
    },
    graph: {
      ok: false,
      error: "Grafo deshabilitado en Signal.",
    },
    news: {
      ok: true,
      data: {
        items: [{ title: "Noticia relevante", source: "Medio", url: "https://news.test" }],
      },
    },
  },
  cached_seconds: 600,
  cache_hit: false,
};

describe("EntityDossier", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.dossier.mockResolvedValue(dossierResponse);
    mocks.suggest.mockResolvedValue({ suggestions: [], kind: "company", cached_seconds: 600, cache_hit: false });
    mocks.registry.mockResolvedValue({ items: [], total: 0, cached_seconds: 600, cache_hit: false });
    mocks.graph.mockResolvedValue({ nodes: [], edges: [], truncated: false, cached_seconds: 600, cache_hit: false });
    mocks.dossiersList.mockResolvedValue({
      data: [{ id: "dossier-1", title: "Expediente ITURRI", updated_at: "2026-07-17" }],
    });
    mocks.attachActor.mockResolvedValue({ id: "link-1" });
  });

  afterEach(cleanup);

  it("muestra cabecera de perfil y límites de fuente", async () => {
    render(<EntityDossier name="IBERDROLA" type="company" />);

    expect(await screen.findByText("IBERDROLA CLIENTES ESPAÑA SOCIEDAD ANONIMA")).toBeInTheDocument();
    expect(screen.getByText("activa")).toBeInTheDocument();
    expect(screen.getByText(/Constitución:/)).toBeInTheDocument();
    expect(screen.getByText(/Las fechas son de publicación en BORME/i)).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Noticias" })).toBeInTheDocument();
  });

  it("muestra degradación de grafo sin tumbar el resto", async () => {
    render(<EntityDossier name="IBERDROLA" type="company" />);

    fireEvent.click(await screen.findByRole("tab", { name: "Grafo" }));

    expect(screen.getByText("Grafo deshabilitado en Signal.")).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Perfil" })).toBeInTheDocument();
  });

  it("diferencia activos y cesados y filtra por activos", async () => {
    render(<EntityDossier name="IBERDROLA" type="company" />);

    fireEvent.click(await screen.findByRole("tab", { name: "Órganos y cargos" }));

    expect(screen.getByText("BURGOS CANTO MIGUEL")).toBeInTheDocument();
    expect(screen.getAllByText("PEREZ LOPEZ ANA")).toHaveLength(2);
    expect(screen.getAllByText("Cesado")).toHaveLength(2);

    fireEvent.click(screen.getByLabelText("Solo activos"));

    expect(screen.getByText("BURGOS CANTO MIGUEL")).toBeInTheDocument();
    expect(screen.queryByText("PEREZ LOPEZ ANA")).not.toBeInTheDocument();
  });

  it("ordena cronológicamente por defecto y permite filtrar la tabla de cargos", async () => {
    render(<EntityDossier name="IBERDROLA" type="company" />);

    fireEvent.click(await screen.findByRole("tab", { name: "Órganos y cargos" }));

    const rows = await screen.findAllByRole("row");
    expect(rows[1]).toHaveTextContent("BURGOS CANTO MIGUEL");

    fireEvent.click(screen.getByRole("button", { name: /Publicación BORME, orden descendente/i }));
    await waitFor(() => {
      const sortedRows = screen.getAllByRole("row");
      expect(sortedRows[1]).toHaveTextContent("PEREZ LOPEZ ANA");
      expect(sortedRows[1]).toHaveTextContent("2019");
    });

    fireEvent.change(screen.getByLabelText("Filtrar tabla de actos"), { target: { value: "BIZKAIA" } });

    expect(screen.getByText("BURGOS CANTO MIGUEL")).toBeInTheDocument();
    expect(screen.queryByText("PEREZ LOPEZ ANA")).not.toBeInTheDocument();
  });

  it("materializa la entidad de Signal como actor interno al vincularla a un expediente", async () => {
    render(<EntityDossier name="IBERDROLA" type="company" />);

    expect(await screen.findByText("Expediente ITURRI")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /Añadir actor/i }));

    await waitFor(() => expect(mocks.attachActor).toHaveBeenCalledWith(
      "dossier-1",
      expect.objectContaining({
        actor_type: "organization",
        canonical_name: "IBERDROLA CLIENTES ESPAÑA SOCIEDAD ANONIMA",
        roles: ["Entidad Signal"],
        tags: ["signal", "entity-intel"],
        provenance: expect.objectContaining({
          source: "signal_entity_intel",
          entity_kind: "company",
          source_name: "IBERDROLA CLIENTES ESPAÑA SOCIEDAD ANONIMA",
        }),
      }),
    ));
    expect(await screen.findByText(/Entidad vinculada al expediente/i)).toBeInTheDocument();
  });

  it("carga una página adicional del histórico si hay paginación", async () => {
    mocks.dossier.mockResolvedValueOnce({
      ...dossierResponse,
      sections: {
        ...dossierResponse.sections,
        registry: {
          ok: true,
          data: {
            ...dossierResponse.sections.registry.data,
            total: 75,
          },
        },
      },
    });
    mocks.registry.mockResolvedValueOnce({
      items: [{ person: "SEGUNDA PAGINA", role: "Administrador", action: "nombramiento", date: "2026-01-01" }],
      total: 75,
      cached_seconds: 600,
      cache_hit: false,
    });
    render(<EntityDossier name="IBERDROLA" type="company" />);

    fireEvent.click(await screen.findByRole("tab", { name: "Órganos y cargos" }));
    fireEvent.click(screen.getByRole("button", { name: "Siguiente" }));

    await waitFor(() => expect(mocks.registry).toHaveBeenCalledWith({
      name: "IBERDROLA",
      type: "company",
      limit: 50,
      offset: 50,
    }));
    expect(await screen.findByText("SEGUNDA PAGINA")).toBeInTheDocument();
  });
});
