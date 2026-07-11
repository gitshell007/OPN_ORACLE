import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({ create: vi.fn(), push: vi.fn() }));

vi.mock("@oracle/api-client", () => ({
  ApiError: class ApiError extends Error {},
  api: { dossiers: { create: mocks.create } },
}));
vi.mock("next/navigation", () => ({ useRouter: () => ({ push: mocks.push }) }));
vi.mock("sonner", () => ({ toast: { success: vi.fn() } }));

import { CreateProductDossierDialog } from "./create-product-dossier-dialog";

describe("CreateProductDossierDialog", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.create.mockResolvedValue({ id: "dossier-1" });
  });

  afterEach(cleanup);

  it("muestra y solicita la base inicial correspondiente al tipo elegido", async () => {
    render(<CreateProductDossierDialog open onOpenChange={vi.fn()} />);

    fireEvent.change(screen.getByLabelText("Tipo"), { target: { value: "tender_or_grant" } });
    expect(screen.getByText(/Preparar una licitación/i)).toBeInTheDocument();
    expect(screen.getByText(/plazos, requisitos, publicaciones/i)).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("Nombre"), { target: { value: "Ayuda regional" } });
    fireEvent.change(screen.getByLabelText("Objetivo estratégico"), { target: { value: "Presentar una propuesta sólida" } });
    fireEvent.click(screen.getByRole("button", { name: "Crear expediente" }));

    await waitFor(() => expect(mocks.create).toHaveBeenCalledWith(expect.objectContaining({
      type: "tender_or_grant",
      create_starter_profile: true,
    })));
  });

  it("permite crear un expediente vacío de forma explícita", async () => {
    render(<CreateProductDossierDialog open onOpenChange={vi.fn()} />);
    fireEvent.change(screen.getByLabelText("Nombre"), { target: { value: "Expediente libre" } });
    fireEvent.change(screen.getByLabelText("Objetivo estratégico"), { target: { value: "Aclarar un asunto" } });
    fireEvent.click(screen.getByRole("checkbox", { name: /Crear una base inicial/i }));
    fireEvent.click(screen.getByRole("button", { name: "Crear expediente" }));

    await waitFor(() => expect(mocks.create).toHaveBeenCalledWith(expect.objectContaining({
      create_starter_profile: false,
    })));
  });
});
