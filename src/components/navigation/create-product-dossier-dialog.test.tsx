import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({ create: vi.fn(), readiness: vi.fn(), push: vi.fn() }));

vi.mock("@oracle/api-client", () => ({
  ApiError: class ApiError extends Error {},
  api: { dossiers: { create: mocks.create, competitiveReadiness: mocks.readiness } },
}));
vi.mock("next/navigation", () => ({ useRouter: () => ({ push: mocks.push }) }));
vi.mock("sonner", () => ({ toast: { success: vi.fn() } }));

import { CreateProductDossierDialog } from "./create-product-dossier-dialog";

describe("CreateProductDossierDialog", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.create.mockResolvedValue({ id: "dossier-1" });
    mocks.readiness.mockResolvedValue({
      ready: false,
      checks: [
        { key: "ai", ready: false, label: "Análisis con IA", detail: "La política IA está desactivada.", action_href: "/app/admin/ai" },
        { key: "signal", ready: true, label: "Signal Avanza", detail: "Conexión activa.", action_href: "/app/admin/integrations/signal-avanza" },
      ],
    });
  });

  afterEach(cleanup);

  it("muestra y solicita la base inicial correspondiente al tipo elegido", async () => {
    render(<CreateProductDossierDialog open onOpenChange={vi.fn()} />);

    fireEvent.change(screen.getByLabelText("Tipo"), { target: { value: "tender_or_grant" } });
    expect(screen.getAllByText(/Preparar una licitación/i).length).toBeGreaterThan(0);
    expect(screen.getByText(/plazos, requisitos, publicaciones/i)).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("Nombre"), { target: { value: "Ayuda regional" } });
    fireEvent.change(screen.getByLabelText("Objetivo estratégico"), { target: { value: "Presentar una propuesta sólida" } });
    fireEvent.click(screen.getByRole("button", { name: "Crear expediente" }));

    await waitFor(() => expect(mocks.create).toHaveBeenCalledWith(expect.objectContaining({
      type: "tender_or_grant",
      create_starter_profile: true,
      accept_creation_intent: true,
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
      accept_creation_intent: true,
    })));
  });

  it("guía el intake de mercado en cuatro pasos y deja preparada la vigilancia", async () => {
    sessionStorage.clear();
    render(<CreateProductDossierDialog open onOpenChange={vi.fn()} />);
    fireEvent.change(screen.getByLabelText("Tipo"), { target: { value: "market" } });
    expect(screen.getByText("Paso 1 de 4")).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("Nombre"), { target: { value: "Mercado de almacenamiento" } });
    fireEvent.change(screen.getByLabelText("Objetivo estratégico"), { target: { value: "Decidir si entramos" } });
    fireEvent.click(screen.getByRole("button", { name: "Continuar" }));

    expect(await screen.findByText("Paso 2 de 4")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Quitar España" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Quitar Alemania" })).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Oferta o capacidades propias"), { target: { value: "Integración de baterías" } });
    fireEvent.change(screen.getByLabelText("Sector"), { target: { value: "almacenamiento energético" } });
    fireEvent.click(screen.getByRole("button", { name: "Continuar" }));

    expect(await screen.findByText("Paso 3 de 4")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Continuar" })).toBeDisabled();
    fireEvent.change(screen.getByPlaceholderText("Una o varias razones sociales, separadas por comas"), { target: { value: "Compañía Gamma, Compañía Delta" } });
    fireEvent.change(screen.getByLabelText("Posibles partners"), { target: { value: "Partner Local" } });
    fireEvent.change(screen.getByLabelText("Reguladores"), { target: { value: "CNMC" } });
    fireEvent.click(screen.getByRole("button", { name: "Continuar" }));

    expect(await screen.findByText("Paso 4 de 4")).toBeInTheDocument();
    expect(mocks.readiness).toHaveBeenCalled();
    expect(screen.getByText("La política IA está desactivada.")).toBeInTheDocument();
    // Casilla de base inicial solo en el último paso del wizard de mercado.
    expect(screen.getByRole("checkbox", { name: /Crear una base inicial/i })).toBeChecked();
    fireEvent.change(screen.getByLabelText("Decisión concreta"), { target: { value: "Entrar con partner local" } });
    fireEvent.click(screen.getByRole("button", { name: "Crear expediente" }));

    await waitFor(() => expect(mocks.create).toHaveBeenCalledWith(expect.objectContaining({
      type: "market",
      accept_creation_intent: true,
      create_starter_profile: true,
      initial_status: "active",
      geography: ["ES", "DE"],
      languages: ["es", "de"],
      sectors: ["almacenamiento energético"],
      profile_config: expect.objectContaining({
        own_offer: "Integración de baterías",
        decision_to_make: "Entrar con partner local",
        competitors: [
          { name: "Compañía Gamma", aliases: [] },
          { name: "Compañía Delta", aliases: [] },
        ],
        partners: ["Partner Local"],
        regulators: ["CNMC"],
      }),
    })));

    const stored = sessionStorage.getItem("oracle:wizard-prefill:dossier-1:monitor");
    expect(stored).toBeTruthy();
    expect(JSON.parse(stored as string)).toMatchObject({
      entities: ["Compañía Gamma", "Compañía Delta", "Partner Local", "CNMC"],
      geographies: ["ES", "DE"],
      languages: ["es", "de"],
      cadence: "daily",
    });
    expect(mocks.push).toHaveBeenCalledWith("/app/dossiers/dossier-1/settings?wizard_prefill=monitor");
  });

  it("revisa dependencias y crea un perfil competitivo activo sin ocultar bloqueos", async () => {
    render(<CreateProductDossierDialog open onOpenChange={vi.fn()} />);
    fireEvent.change(screen.getByLabelText("Tipo"), { target: { value: "competitive_intelligence" } });
    fireEvent.change(screen.getByLabelText("Nombre"), { target: { value: "Radar competitivo" } });
    fireEvent.change(screen.getByLabelText("Objetivo estratégico"), { target: { value: "Priorizar oportunidades con evidencia" } });
    fireEvent.change(screen.getByLabelText("Empresa o producto propio"), { target: { value: "Vehículos especiales" } });
    fireEvent.change(screen.getByPlaceholderText("Una o varias razones sociales, separadas por comas"), { target: { value: "Compañía Alfa, Compañía Beta" } });
    fireEvent.click(screen.getByRole("button", { name: "Revisar expediente" }));

    expect(await screen.findByText("La política IA está desactivada.")).toBeInTheDocument();
    expect(screen.getByText(/Puedes crear el expediente/)).toBeInTheDocument();
    expect(mocks.create).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Crear expediente" }));

    await waitFor(() => expect(mocks.create).toHaveBeenCalledWith(expect.objectContaining({
      type: "competitive_intelligence",
      initial_status: "active",
      profile_config: expect.objectContaining({
        own_offer: "Vehículos especiales",
        competitors: [{ name: "Compañía Alfa", aliases: [] }, { name: "Compañía Beta", aliases: [] }],
      }),
    })));
  });
});
