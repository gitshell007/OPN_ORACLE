import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { EntityProcurementSection } from "./entity-procurement-section";

const mocks = vi.hoisted(() => ({
  awards: vi.fn(),
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
      procurement: {
        awards: mocks.awards,
      },
    },
  };
});

vi.mock("@/components/procurement/pin-to-dossier-control", () => ({
  PinToDossierControl: () => <button type="button">Fijar</button>,
}));

describe("EntityProcurementSection", () => {
  beforeEach(() => {
    mocks.awards.mockReset();
    mocks.awards.mockResolvedValue({
      company_norm: "ITURRI SA",
      buyer_norm: "",
      total: 2,
      items: [
        {
          folder_id: "folder-1",
          title: "Suministro de equipos",
          buyer: "Ministerio de Defensa",
          winner: "ITURRI SA",
          award_amount: 120000,
          award_date: "2025-06-01",
          status: "Adjudicada",
          cpv: ["35110000"],
        },
        {
          folder_id: "folder-2",
          title: "Vestuario técnico",
          buyer: "Guardia Civil",
          winner: "ITURRI SA",
          award_amount: 45000,
          award_date: "2024-01-10",
          status: "Adjudicada",
        },
      ],
      cached_seconds: 60,
      cache_hit: false,
    });
  });

  afterEach(cleanup);

  it("carga adjudicaciones de la empresa al montar", async () => {
    const onTotalChange = vi.fn();
    render(
      <EntityProcurementSection
        name="ITURRI SA"
        type="company"
        onTotalChange={onTotalChange}
      />,
    );

    expect(await screen.findByText("Suministro de equipos")).toBeInTheDocument();
    expect(screen.getByText("Ministerio de Defensa")).toBeInTheDocument();
    expect(screen.getByText("Vestuario técnico")).toBeInTheDocument();
    await waitFor(() => expect(onTotalChange).toHaveBeenCalledWith(2));
    expect(mocks.awards).toHaveBeenCalledWith({
      company: "ITURRI SA",
      limit: 25,
      offset: 0,
    });
  });

  it("explica que las personas no tienen filtro PLACSP por nombre", async () => {
    render(<EntityProcurementSection name="JUAN PEREZ" type="person" />);
    expect(
      await screen.findByText(/no hay un histórico PLACSP filtrable por nombre/i),
    ).toBeInTheDocument();
    expect(mocks.awards).not.toHaveBeenCalled();
  });

  it("muestra error recuperable si Signal falla", async () => {
    mocks.awards.mockRejectedValueOnce(new Error("timeout"));
    render(<EntityProcurementSection name="ITURRI SA" type="company" />);
    expect(
      await screen.findByText(/No se pudieron consultar las adjudicaciones/i),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Reintentar" }));
    expect(await screen.findByText("Suministro de equipos")).toBeInTheDocument();
  });
});
