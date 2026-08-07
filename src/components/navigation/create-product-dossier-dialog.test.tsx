import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  create: vi.fn(),
  readiness: vi.fn(),
  push: vi.fn(),
  run: vi.fn(),
  toastSuccess: vi.fn(),
  toastMessage: vi.fn(),
}));

vi.mock("@oracle/api-client", () => ({
  ApiError: class ApiError extends Error {
    problem = { detail: this.message };
    constructor(message: string) {
      super(message);
    }
  },
  api: {
    dossiers: { create: mocks.create, competitiveReadiness: mocks.readiness },
    marketActorDiscovery: { run: mocks.run },
  },
}));
vi.mock("next/navigation", () => ({ useRouter: () => ({ push: mocks.push }) }));
vi.mock("sonner", () => ({
  toast: { success: mocks.toastSuccess, message: mocks.toastMessage },
}));

import {
  CreateProductDossierDialog,
  marketStepBlockers,
} from "./create-product-dossier-dialog";

describe("CreateProductDossierDialog", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.create.mockResolvedValue({ id: "dossier-1" });
    mocks.run.mockResolvedValue({ job: { id: "job-1", status: "queued" }, artifact: null });
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

  it("con el asistente de mercado vacío muestra los requisitos pendientes visibles", async () => {
    render(<CreateProductDossierDialog open onOpenChange={vi.fn()} />);
    fireEvent.change(screen.getByLabelText("Tipo"), { target: { value: "market" } });

    const pending = await screen.findByTestId("market-step-pending");
    expect(pending).toHaveTextContent("Nombre del expediente");
    expect(pending).toHaveTextContent("Objetivo estratégico");
    // Continuar permanece accionable; al pulsar no avanza y reafirma el mensaje.
    fireEvent.click(screen.getByRole("button", { name: "Continuar" }));
    expect(screen.getByRole("alert")).toHaveTextContent(/Falta|Completa lo pendiente/i);
    expect(screen.getByText("Paso 1 de 4")).toBeInTheDocument();
    expect(mocks.create).not.toHaveBeenCalled();
  });

  it("en el paso ecosistema no obliga a mentir: salida «aún no lo sé» y payload honesto", async () => {
    sessionStorage.clear();
    render(<CreateProductDossierDialog open onOpenChange={vi.fn()} />);
    fireEvent.change(screen.getByLabelText("Tipo"), { target: { value: "market" } });
    fireEvent.change(screen.getByLabelText("Nombre"), { target: { value: "Grupos de investigación Francia" } });
    fireEvent.change(screen.getByLabelText("Objetivo estratégico"), { target: { value: "Encontrar laboratorios" } });
    fireEvent.click(screen.getByRole("button", { name: "Continuar" }));

    expect(await screen.findByText("Paso 2 de 4")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Oferta o capacidades propias"), { target: { value: "Colaboración científica" } });
    fireEvent.change(screen.getByLabelText("Sector"), { target: { value: "I+D" } });
    fireEvent.click(screen.getByRole("button", { name: "Continuar" }));

    expect(await screen.findByText("Paso 3 de 4")).toBeInTheDocument();
    const pendingEcosystem = screen.getByTestId("market-step-pending");
    expect(pendingEcosystem).toHaveTextContent(/conoces competidores|aún no lo sabes|no los buscas/i);

    fireEvent.click(screen.getByRole("radio", { name: "Aún no lo sé" }));
    expect(screen.getByTestId("competitors-unknown-hint")).toBeInTheDocument();
    expect(screen.queryByTestId("market-step-pending")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Continuar" }));

    expect(await screen.findByText("Paso 4 de 4")).toBeInTheDocument();
    // Sin decisión: mensaje visible y Crear expediente no envía.
    expect(screen.getByTestId("market-step-pending")).toHaveTextContent("Decisión concreta");
    fireEvent.click(screen.getByRole("button", { name: "Crear expediente" }));
    expect(mocks.create).not.toHaveBeenCalled();

    fireEvent.change(screen.getByLabelText("Decisión concreta"), {
      target: { value: "Identificar grupos sin inventar rivales" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Crear expediente" }));

    await waitFor(() => expect(mocks.create).toHaveBeenCalledWith(expect.objectContaining({
      type: "market",
      profile_config: expect.objectContaining({
        own_offer: "Colaboración científica",
        decision_to_make: "Identificar grupos sin inventar rivales",
        competitors: [],
        competitors_knowledge: "unknown",
      }),
    })));

    const stored = sessionStorage.getItem("oracle:wizard-prefill:dossier-1:monitor");
    expect(stored).toBeTruthy();
    expect(JSON.parse(stored as string)).toMatchObject({
      competitors_knowledge: "unknown",
      entities: [],
    });
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
    fireEvent.click(screen.getByRole("radio", { name: "Conozco competidores" }));
    fireEvent.change(screen.getByLabelText("Nombres de competidores"), {
      target: { value: "Compañía Gamma, Compañía Delta" },
    });
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
        competitors_knowledge: "known",
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
      competitors_knowledge: "known",
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

describe("marketStepBlockers", () => {
  it("lista lo pendiente sin interacción de campos", () => {
    expect(
      marketStepBlockers({
        step: "ecosystem",
        title: "x",
        goal: "y",
        ownOffer: "z",
        marketCountries: ["ES"],
        competitors: "",
        competitorsKnowledge: "",
        decisionToMake: "",
      }),
    ).toEqual([
      "Indica si conoces competidores, aún no lo sabes o no los buscas",
    ]);
    expect(
      marketStepBlockers({
        step: "ecosystem",
        title: "x",
        goal: "y",
        ownOffer: "z",
        marketCountries: ["ES"],
        competitors: "",
        competitorsKnowledge: "unknown",
        decisionToMake: "",
      }),
    ).toEqual([]);
    expect(
      marketStepBlockers({
        step: "decision",
        title: "x",
        goal: "y",
        ownOffer: "z",
        marketCountries: ["ES"],
        competitors: "",
        competitorsKnowledge: "not_seeking",
        decisionToMake: "",
      }),
    ).toEqual(["Decisión concreta a tomar"]);
  });

  it("research_group: permite continuar sin competidores con intención válida", () => {
    expect(
      marketStepBlockers({
        step: "ecosystem",
        title: "Mercado grafeno",
        goal: "Contactar labs",
        ownOffer: "Colaboración I+D",
        marketCountries: ["FR"],
        competitors: "",
        competitorsKnowledge: "",
        decisionToMake: "",
        discoveryIntent:
          "quiero contactar con grupos de investigación en Francia que trabajen en grafeno",
        discoveryActorType: "research_group",
      }),
    ).toEqual([]);
  });

  it("discovery_intent vacío o corto falla visible", () => {
    expect(
      marketStepBlockers({
        step: "ecosystem",
        title: "x",
        goal: "y",
        ownOffer: "z",
        marketCountries: ["FR"],
        competitors: "",
        competitorsKnowledge: "not_seeking",
        decisionToMake: "",
        discoveryIntent: "corto",
        discoveryActorType: "research_group",
      }),
    ).toContain("Intención de búsqueda (mínimo 10 caracteres)");
    expect(
      marketStepBlockers({
        step: "ecosystem",
        title: "x",
        goal: "y",
        ownOffer: "z",
        marketCountries: ["FR"],
        competitors: "",
        competitorsKnowledge: "not_seeking",
        decisionToMake: "",
        discoveryIntent: "   ",
        discoveryActorType: "research_group",
      }).some((b) => b.includes("encontrar") || b.includes("Intención")),
    ).toBe(true);
  });
});

const FR_INTENT =
  "quiero contactar con grupos de investigación en Francia que trabajen en grafeno";

async function fillMarketWizardToDecision(options?: {
  withActorDiscovery?: boolean;
}) {
  const withActor = options?.withActorDiscovery ?? false;
  fireEvent.change(screen.getByLabelText("Tipo"), { target: { value: "market" } });
  fireEvent.change(screen.getByLabelText("Nombre"), {
    target: { value: "Grupos investigación FR grafeno" },
  });
  fireEvent.change(screen.getByLabelText("Objetivo estratégico"), {
    target: { value: "Contactar laboratorios" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Continuar" }));

  expect(await screen.findByText("Paso 2 de 4")).toBeInTheDocument();
  fireEvent.change(screen.getByLabelText("Oferta o capacidades propias"), {
    target: { value: "Colaboración I+D grafeno" },
  });
  fireEvent.change(screen.getByLabelText("Sector"), { target: { value: "materiales" } });
  fireEvent.click(screen.getByRole("button", { name: "Continuar" }));

  expect(await screen.findByText("Paso 3 de 4")).toBeInTheDocument();
  if (withActor) {
    fireEvent.change(screen.getByTestId("discovery-intent"), {
      target: { value: FR_INTENT },
    });
    fireEvent.change(screen.getByTestId("discovery-actor-type"), {
      target: { value: "research_group" },
    });
  } else {
    fireEvent.click(screen.getByRole("radio", { name: "Aún no lo sé" }));
  }
  fireEvent.click(screen.getByRole("button", { name: "Continuar" }));

  expect(await screen.findByText("Paso 4 de 4")).toBeInTheDocument();
  fireEvent.change(screen.getByLabelText("Decisión concreta"), {
    target: { value: "Priorizar 3 grupos de investigación en FR" },
  });
}

describe("CreateProductDossierDialog G-19 intake→run", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    sessionStorage.clear();
    mocks.create.mockResolvedValue({ id: "dossier-D" });
    mocks.run.mockResolvedValue({ job: { id: "job-1", status: "queued" }, artifact: null });
    mocks.readiness.mockResolvedValue({
      ready: true,
      checks: [
        { key: "ai", ready: true, label: "Análisis con IA", detail: "OK", action_href: "/app/admin/ai" },
        { key: "signal", ready: true, label: "Signal Avanza", detail: "OK", action_href: "/app/admin/integrations/signal-avanza" },
      ],
    });
  });

  afterEach(cleanup);

  it("FR/research_group/graphene: create → run una vez con solo D/idempotency → Actores", async () => {
    render(<CreateProductDossierDialog open onOpenChange={vi.fn()} />);
    await fillMarketWizardToDecision({ withActorDiscovery: true });
    fireEvent.click(screen.getByRole("button", { name: "Crear expediente" }));

    await waitFor(() => expect(mocks.create).toHaveBeenCalledTimes(1));
    expect(mocks.create).toHaveBeenCalledWith(
      expect.objectContaining({
        type: "market",
        profile_config: expect.objectContaining({
          discovery_intent: FR_INTENT,
          discovery_actor_type: "research_group",
        }),
      }),
    );
    await waitFor(() => expect(mocks.run).toHaveBeenCalledTimes(1));
    expect(mocks.run).toHaveBeenCalledWith(
      { dossier_id: "dossier-D" },
      "g19-actor-run:dossier-D:intake",
    );
    // No client-editable intent on run body.
    const runArg = mocks.run.mock.calls[0][0];
    expect(runArg).toEqual({ dossier_id: "dossier-D" });
    expect(runArg).not.toHaveProperty("discovery_intent");
    expect(runArg).not.toHaveProperty("actor_type");
    expect(mocks.push).toHaveBeenCalledWith("/app/dossiers/dossier-D/actors");
  });

  it("enqueue 500: D creado, aviso correcto, navegación y create no se repite", async () => {
    mocks.run.mockRejectedValue(new Error("enqueue failed"));
    render(<CreateProductDossierDialog open onOpenChange={vi.fn()} />);
    await fillMarketWizardToDecision({ withActorDiscovery: true });
    fireEvent.click(screen.getByRole("button", { name: "Crear expediente" }));

    await waitFor(() => expect(mocks.create).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(mocks.run).toHaveBeenCalledTimes(1));
    await waitFor(() =>
      expect(mocks.toastMessage).toHaveBeenCalledWith(
        "Expediente creado; descubrimiento pendiente",
        expect.any(Object),
      ),
    );
    expect(mocks.push).toHaveBeenCalledWith("/app/dossiers/dossier-D/actors");
    expect(mocks.create).toHaveBeenCalledTimes(1);
    // No "could not create" path.
    expect(mocks.toastSuccess).not.toHaveBeenCalledWith(
      "Expediente creado",
      expect.anything(),
    );
  });

  it("sin discovery_intent no encola run y va a settings/monitor", async () => {
    render(<CreateProductDossierDialog open onOpenChange={vi.fn()} />);
    await fillMarketWizardToDecision({ withActorDiscovery: false });
    fireEvent.click(screen.getByRole("button", { name: "Crear expediente" }));

    await waitFor(() => expect(mocks.create).toHaveBeenCalledTimes(1));
    expect(mocks.run).not.toHaveBeenCalled();
    expect(mocks.push).toHaveBeenCalledWith(
      "/app/dossiers/dossier-D/settings?wizard_prefill=monitor",
    );
  });
});
