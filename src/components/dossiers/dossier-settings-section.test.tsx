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
  memoryGetEffective: vi.fn(),
  memoryPutProfile: vi.fn(),
  memoryTestConnection: vi.fn(),
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
      getEffective: mocks.memoryGetEffective,
      putProfile: mocks.memoryPutProfile,
      testConnection: mocks.memoryTestConnection,
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
    mocks.memoryGetEffective.mockResolvedValue({
      id: null,
      tenant_id: "tenant-1",
      dossier_id: "dossier-1",
      connection_id: null,
      mode: "disabled",
      mode_label_es: "Desactivada",
      version: 0,
      etag: 'W/"dmp-v0"',
      sources: ["document", "signal"],
      kinds: ["fact", "chunk"],
      classifications_allowed: ["public", "internal"],
      token_budget: 4000,
      limit: 20,
      status: "ephemeral_default",
      provenance: "effective_default_not_persisted",
      last_test_at: null,
      last_test_status: null,
      last_error: null,
      last_coverage: null,
      updated_at: null,
      persisted: false,
      publisher_reliable: false,
      actions_reliable: false,
      deferred_blockers: ["RACE-MDEV02-003"],
    });
    mocks.memoryPutProfile.mockResolvedValue({
      id: "profile-1",
      tenant_id: "tenant-1",
      dossier_id: "dossier-1",
      connection_id: null,
      mode: "shadow",
      mode_label_es: "Solo observar",
      version: 1,
      etag: 'W/"dmp-v1"',
      sources: ["document", "signal"],
      kinds: ["fact", "chunk"],
      classifications_allowed: ["public", "internal"],
      token_budget: 4000,
      limit: 10,
      status: "active",
      provenance: "tenant_default",
      last_test_at: null,
      last_test_status: null,
      last_error: null,
      last_coverage: null,
      updated_at: "2026-08-02T00:00:00Z",
      persisted: true,
      publisher_reliable: false,
      actions_reliable: false,
      deferred_blockers: ["RACE-MDEV02-003"],
    });
    mocks.memoryTestConnection.mockResolvedValue({
      ok: true,
      status: "ok",
      synthetic: false,
      last_test_status: "ok",
      message: null,
    });
  });
  afterEach(cleanup);

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

  it("carga la sección Memoria con defaults no persistidos y banner degradado", async () => {
    render(<DossierSettingsSection dossierId="dossier-1" />);
    const section = await screen.findByTestId("dossier-memory-settings");
    expect(within(section).getByRole("heading", { name: "Memoria del expediente" })).toBeVisible();
    expect(within(section).getByText(/defaults no persistidos/i)).toBeVisible();
    expect(within(section).getByText(/servicio degradado/i)).toBeVisible();
    expect(mocks.memoryGetEffective).toHaveBeenCalledWith("dossier-1");
  });

  it("guarda el perfil de memoria con If-Match (etag) y modo shadow", async () => {
    render(<DossierSettingsSection dossierId="dossier-1" />);
    const section = await screen.findByTestId("dossier-memory-settings");
    const mode = within(section).getByLabelText("Modo");
    fireEvent.change(mode, { target: { value: "shadow" } });
    const limit = within(section).getByLabelText("Límite de resultados");
    fireEvent.change(limit, { target: { value: "10" } });
    fireEvent.click(within(section).getByRole("button", { name: /Guardar memoria/i }));
    await waitFor(() =>
      expect(mocks.memoryPutProfile).toHaveBeenCalledWith(
        "dossier-1",
        expect.objectContaining({ mode: "shadow", limit: 10 }),
        'W/"dmp-v0"',
      ),
    );
    expect(mocks.success).toHaveBeenCalled();
  });

  it("prueba la conexión de memoria y recarga el perfil", async () => {
    render(<DossierSettingsSection dossierId="dossier-1" />);
    const section = await screen.findByTestId("dossier-memory-settings");
    // Probar conexión is disabled while mode is disabled.
    fireEvent.change(within(section).getByLabelText("Modo"), { target: { value: "shadow" } });
    fireEvent.click(within(section).getByRole("button", { name: /Probar conexión/i }));
    await waitFor(() => expect(mocks.memoryTestConnection).toHaveBeenCalledWith("dossier-1"));
    await waitFor(() => expect(mocks.memoryGetEffective.mock.calls.length).toBeGreaterThanOrEqual(2));
  });

  it("muestra error de memoria degradado sin tumbar el resto de la config", async () => {
    mocks.memoryGetEffective.mockRejectedValueOnce(new Error("permission denied"));
    render(<DossierSettingsSection dossierId="dossier-1" />);
    expect(await screen.findByRole("heading", { name: "Configuración" })).toBeVisible();
    expect(await screen.findByText(/No se pudo cargar la memoria/i)).toBeVisible();
    expect(screen.getByLabelText("Título")).toHaveValue("Expansión Delta");
  });
});
