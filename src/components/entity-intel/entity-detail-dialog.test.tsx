import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  registry: vi.fn(),
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
        registry: mocks.registry,
      },
    },
  };
});

import { EntityDetailDialog } from "./entity-detail-dialog";

describe("EntityDetailDialog", () => {
  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  it("muestra una ficha legible y confirma antes de navegar a una relación", async () => {
    mocks.registry.mockResolvedValue({
      profile: { status: "activa", constitution_date: "2001-02-03" },
      items: [
        { person: "BURGOS CANTO MIGUEL", role: "Administrador", action: "nombramiento", date: "2026-07-01", source_url: "https://boe.test/1" },
        { person: "OTRA PERSONA", role: "Consejero", action: "cese", date: "2026-06-01", source_url: "https://boe.test/2" },
      ],
      total: 75,
      cached_seconds: 600,
      cache_hit: false,
    });
    const navigate = vi.fn();
    render(
      <EntityDetailDialog
        open
        entity={{
          id: "iberdrola",
          label: "IBERDROLA CLIENTES ESPAÑA SOCIEDAD ANONIMA",
          type: "company",
          norm: "IBERDROLA CLIENTES ESPANA SOCIEDAD ANONIMA",
          degree: 3,
          updated_at: "2026-07-16T00:00:00Z",
          active: true,
        }}
        relations={[
          {
            id: "rel-1",
            label: "BURGOS CANTO MIGUEL",
            routeName: "BURGOS CANTO MIGUEL NORMALIZADO",
            kind: "person",
            role: "Administrador",
            degree: 2,
          },
        ]}
        onOpenChange={vi.fn()}
        onNavigate={navigate}
      />,
    );

    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(screen.getByText("Empresa")).toBeInTheDocument();
    expect(screen.getAllByText("IBERDROLA CLIENTES ESPAÑA SOCIEDAD ANONIMA")).not.toHaveLength(0);
    expect(screen.getByText("16/7/2026")).toBeInTheDocument();
    expect(screen.getByText("3 conexiones")).toBeInTheDocument();
    expect(await screen.findByText("activa")).toBeInTheDocument();
    expect(screen.getAllByText("1 de los últimos 2 actos")).toHaveLength(2);
    expect(mocks.registry).toHaveBeenCalledWith({
      name: "IBERDROLA CLIENTES ESPANA SOCIEDAD ANONIMA",
      type: "company",
      limit: 50,
      offset: 0,
    });

    fireEvent.click(screen.getByRole("button", { name: /BURGOS CANTO MIGUEL/i }));
    expect(
      screen.getByText("¿Quieres consultar los datos de BURGOS CANTO MIGUEL?"),
    ).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Cancelar" }));
    expect(navigate).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: /BURGOS CANTO MIGUEL/i }));
    fireEvent.click(screen.getByRole("button", { name: /Consultar/i }));

    expect(navigate).toHaveBeenCalledWith("person", "BURGOS CANTO MIGUEL NORMALIZADO");
  });

  it("resetea la confirmación pendiente cuando cambia la entidad", async () => {
    mocks.registry.mockResolvedValue({
      items: [],
      total: 0,
      cached_seconds: 600,
      cache_hit: false,
    });
    const navigate = vi.fn();
    const { rerender } = render(
      <EntityDetailDialog
        open
        entity={{ id: "a", label: "Entidad A", type: "company" }}
        relations={[{ id: "rel-a", label: "Entidad relacionada", kind: "person", role: "Administrador" }]}
        onOpenChange={vi.fn()}
        onNavigate={navigate}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: /Entidad relacionada/i }));
    expect(screen.getByText(/¿Quieres consultar los datos de Entidad relacionada/i)).toBeInTheDocument();

    rerender(
      <EntityDetailDialog
        open
        entity={{ id: "b", label: "Entidad B", type: "company" }}
        relations={[]}
        onOpenChange={vi.fn()}
        onNavigate={navigate}
      />,
    );

    await waitFor(() => expect(screen.getAllByText("Entidad B").length).toBeGreaterThan(0));
    await waitFor(() => expect(screen.queryByText(/¿Quieres consultar los datos/i)).not.toBeInTheDocument());
  });
});
