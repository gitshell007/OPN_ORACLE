import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  get: vi.fn(),
  update: vi.fn(),
  archive: vi.fn(),
  connections: vi.fn(),
  monitors: vi.fn(),
  createMonitor: vi.fn(),
  monitorAction: vi.fn(),
  success: vi.fn(),
  memoryGet: vi.fn(),
}));

vi.mock("@oracle/api-client", () => ({
  ApiError: class ApiError extends Error {
    problem = { detail: this.message };
  },
  api: {
    dossiers: {
      get: mocks.get,
      update: mocks.update,
      archive: mocks.archive,
    },
    signalAvanza: {
      connections: mocks.connections,
      monitors: mocks.monitors,
      createMonitor: mocks.createMonitor,
      action: mocks.monitorAction,
    },
    dossierMemory: {
      getEffective: mocks.memoryGet,
    },
  },
}));

vi.mock("sonner", () => ({ toast: { success: mocks.success } }));
vi.mock("@/components/auth/auth-boundary", () => ({
  PermissionGate: ({ children }: { children: React.ReactNode }) => children,
}));
const navState = vi.hoisted(() => ({ search: "" }));
vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams(navState.search),
}));

import { DossierSettingsSection } from "./dossier-settings-section";

const dossier = {
  id: "dossier-1",
  tenant_id: "tenant-1",
  title: "Expansión Delta",
  description: "Seguimiento de una expansión regional.",
  dossier_type: "project",
  status: "active" as const,
  strategic_goal: "Validar alianzas antes del siguiente hito.",
  health_score: 78,
  opportunity_score: 86,
  risk_score: 31,
  owner_user_id: "user-1",
  version: 4,
  archived_at: null,
  created_at: "2026-07-11T08:00:00Z",
  updated_at: "2026-07-11T08:30:00Z",
};

describe("DossierSettingsSection", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    navState.search = "";
    sessionStorage.clear();
    mocks.get.mockResolvedValue(dossier);
    mocks.connections.mockResolvedValue({
      items: [
        {
          id: "connection-1",
          provider: "signal-avanza",
          name: "Signal Avanza principal",
          status: "active",
          adapter_mode: "http",
          api_version: "2026-07-01",
          base_url: "https://signal.example.test",
          circuit_state: "closed",
          last_health_at: null,
          last_success_at: null,
          last_error: null,
          version: 1,
        },
      ],
    });
    mocks.monitors.mockResolvedValue({ data: [] });
    mocks.createMonitor.mockResolvedValue({ id: "monitor-1", outbox_event_id: "event-1" });
    mocks.update.mockResolvedValue({ ...dossier, status: "paused", version: 5 });
    mocks.memoryGet.mockRejectedValue(new Error("memory unavailable"));
  });
  afterEach(cleanup);

  it("carga y guarda el perfil de mercado vía PATCH profile_config", async () => {
    const marketDossier = {
      ...dossier,
      dossier_type: "market",
      version: 7,
      profile_config: {
        version: "market.v1",
        own_offer: "Integración de baterías",
        decision_to_make: "Entrar o no",
        competitors: [{ name: "Gamma", aliases: [] }],
        barriers: ["Permisos"],
        segments: [],
        channels: [],
        target_buyers: [],
        partners: [],
        regulators: [],
        success_indicators: [],
        keywords: ["almacenamiento"],
        horizon: "",
      },
    };
    mocks.get.mockResolvedValue(marketDossier);
    mocks.update.mockResolvedValue({
      ...marketDossier,
      version: 8,
      profile_config: {
        ...marketDossier.profile_config,
        own_offer: "Integración de sistemas de baterías",
        decision_to_make: "Entrar con partner local",
      },
    });

    render(<DossierSettingsSection dossierId="dossier-1" />);

    expect(await screen.findByRole("heading", { name: "Perfil del expediente" })).toBeVisible();
    expect(screen.getByLabelText("Oferta propia")).toHaveValue("Integración de baterías");
    expect(screen.getByLabelText("Competidores")).toHaveValue("Gamma");
    expect(screen.getByLabelText("Barreras")).toHaveValue("Permisos");

    fireEvent.change(screen.getByLabelText("Oferta propia"), {
      target: { value: "Integración de sistemas de baterías" },
    });
    fireEvent.change(screen.getByLabelText("Decisión a tomar"), {
      target: { value: "Entrar con partner local" },
    });
    fireEvent.click(screen.getByRole("button", { name: /Guardar perfil/ }));

    await waitFor(() =>
      expect(mocks.update).toHaveBeenCalledWith(
        "dossier-1",
        expect.objectContaining({
          version: 7,
          profile_config: expect.objectContaining({
            own_offer: "Integración de sistemas de baterías",
            decision_to_make: "Entrar con partner local",
            competitors: [{ name: "Gamma", aliases: [] }],
            barriers: ["Permisos"],
          }),
        }),
        7,
      ),
    );
    expect(mocks.success).toHaveBeenCalledWith("Perfil del expediente actualizado");
    await waitFor(() =>
      expect(screen.getByLabelText("Oferta propia")).toHaveValue(
        "Integración de sistemas de baterías",
      ),
    );
  });

  it("mantiene accesible la configuración si los monitores no están autorizados", async () => {
    mocks.monitors.mockRejectedValueOnce(new Error("forbidden"));
    render(<DossierSettingsSection dossierId="dossier-1" />);

    expect(await screen.findByRole("heading", { name: "Configuración" })).toBeVisible();
    expect(screen.getByLabelText("Título")).toHaveValue("Expansión Delta");
    expect(screen.getByText(/no puedes consultar las vigilancias con tus permisos/i)).toBeVisible();
  });

  it("solo ofrece transiciones de estado admitidas por el backend", async () => {
    render(<DossierSettingsSection dossierId="dossier-1" />);

    const status = await screen.findByLabelText("Estado");
    const options = within(status).getAllByRole("option");
    expect(options.map((option) => option.textContent)).toEqual(["Activo", "Pausado"]);
    expect(within(status).queryByRole("option", { name: "Borrador" })).not.toBeInTheDocument();

    fireEvent.change(status, { target: { value: "paused" } });
    fireEvent.click(screen.getByRole("button", { name: /Guardar cambios/ }));
    await waitFor(() =>
      expect(mocks.update).toHaveBeenCalledWith(
        "dossier-1",
        expect.objectContaining({ status: "paused", version: 4 }),
        4,
      ),
    );
  });

  it("crea un monitor con la configuración de vigilancia compatible", async () => {
    render(<DossierSettingsSection dossierId="dossier-1" />);

    await screen.findByRole("heading", { name: "Nueva vigilancia" });
    fireEvent.change(screen.getByLabelText("Nombre de la vigilancia"), {
      target: { value: "Competencia y regulación" },
    });
    fireEvent.change(screen.getByLabelText(/^Consulta principal/), {
      target: { value: "almacenamiento energético" },
    });
    fireEvent.change(screen.getByLabelText(/^Palabras clave/), {
      target: { value: "baterías, subvenciones" },
    });
    fireEvent.change(screen.getByLabelText(/^Competidores y entidades/), {
      target: { value: "Empresa Delta\nOrganismo Gamma" },
    });
    fireEvent.change(screen.getByLabelText(/^Idiomas/), {
      target: { value: "es, en" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Crear vigilancia" }));

    await waitFor(() =>
      expect(mocks.createMonitor).toHaveBeenCalledWith("dossier-1", {
        connection_id: "connection-1",
        name: "Competencia y regulación",
        query: "almacenamiento energético",
        keywords: ["baterías", "subvenciones"],
        entities: [
          { type: "company", name: "Empresa Delta" },
          { type: "company", name: "Organismo Gamma" },
        ],
        cadence: "daily",
        source_types: ["news", "company_signal", "official_publication"],
        languages: ["es", "en"],
        geographies: ["ES"],
        retention_days: 90,
      }),
    );
  });

  it("permite crear un monitor sin consulta si hay palabras clave o entidades", async () => {
    render(<DossierSettingsSection dossierId="dossier-1" />);

    await screen.findByRole("heading", { name: "Nueva vigilancia" });
    expect(screen.getByText("Redes y foros")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Nombre de la vigilancia"), {
      target: { value: "Radar de mercado" },
    });
    fireEvent.change(screen.getByLabelText(/^Competidores y entidades/), {
      target: { value: "Compañía Gamma" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Crear vigilancia" }));

    await waitFor(() =>
      expect(mocks.createMonitor).toHaveBeenCalledWith(
        "dossier-1",
        expect.objectContaining({
          query: "",
          entities: [{ type: "company", name: "Compañía Gamma" }],
        }),
      ),
    );
  });

  it("rechaza un monitor sin consulta, palabras clave ni entidades", async () => {
    render(<DossierSettingsSection dossierId="dossier-1" />);

    await screen.findByRole("heading", { name: "Nueva vigilancia" });
    fireEvent.change(screen.getByLabelText("Nombre de la vigilancia"), {
      target: { value: "Radar vacío" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Crear vigilancia" }));

    expect(
      await screen.findByText(/Define al menos una consulta, palabras clave o entidades/),
    ).toBeInTheDocument();
    expect(mocks.createMonitor).not.toHaveBeenCalled();
  });

  it("aplica el prefill del intake incluyendo las entidades", async () => {
    navState.search = "wizard_prefill=monitor";
    sessionStorage.setItem(
      "oracle:wizard-prefill:dossier-1:monitor",
      JSON.stringify({
        name: "Radar de mercado: Almacenamiento",
        query: "",
        keywords: ["almacenamiento energético"],
        entities: ["Compañía Gamma", "Regulador Energía"],
        languages: ["es", "de"],
        geographies: ["ES", "DE"],
        source_types: ["news", "company_signal", "regulatory_signal", "official_publication"],
        cadence: "daily",
      }),
    );
    render(<DossierSettingsSection dossierId="dossier-1" />);

    await waitFor(() =>
      expect(screen.getByLabelText("Nombre de la vigilancia")).toHaveValue(
        "Radar de mercado: Almacenamiento",
      ),
    );
    expect(screen.getByLabelText(/^Competidores y entidades/)).toHaveValue(
      "Compañía Gamma, Regulador Energía",
    );
    expect(screen.getByRole("button", { name: "Quitar Alemania" })).toBeInTheDocument();
    expect(sessionStorage.getItem("oracle:wizard-prefill:dossier-1:monitor")).toBeNull();
  });
});
