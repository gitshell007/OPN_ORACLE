import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { EntityDetailDialog } from "./entity-detail-dialog";

describe("EntityDetailDialog", () => {
  afterEach(cleanup);

  it("muestra una ficha legible y confirma antes de navegar a una relación", () => {
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

    fireEvent.click(screen.getByRole("button", { name: /BURGOS CANTO MIGUEL/i }));
    expect(
      screen.getByText("¿Quieres consultar los datos de BURGOS CANTO MIGUEL?"),
    ).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Cancelar" }));
    expect(navigate).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: /BURGOS CANTO MIGUEL/i }));
    fireEvent.click(screen.getByRole("button", { name: /Consultar/i }));

    expect(navigate).toHaveBeenCalledWith("person", "BURGOS CANTO MIGUEL");
  });
});
