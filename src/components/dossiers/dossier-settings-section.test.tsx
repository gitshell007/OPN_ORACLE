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
  memoryPut: vi.fn(),
  memoryMaterialize: vi.fn(),
  listCollaborators: vi.fn(),
  assignableList: vi.fn(),
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
      listCollaborators: mocks.listCollaborators,
      setCollaborator: vi.fn(),
      removeCollaborator: vi.fn(),
    },
    signalAvanza: {
      connections: mocks.connections,
      monitors: mocks.monitors,
      createMonitor: mocks.createMonitor,
      action: mocks.monitorAction,
    },
    dossierMemory: {
      getEffective: mocks.memoryGet,
      putProfile: mocks.memoryPut,
      materializeProfile: mocks.memoryMaterialize,
    },
    assignableUsers: {
      list: mocks.assignableList,
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
    mocks.listCollaborators.mockResolvedValue({ data: [] });
    mocks.assignableList.mockResolvedValue({ items: [] });
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

  it("carga y guarda el perfil custom vía PATCH profile_config", async () => {
    const customDossier = {
      ...dossier,
      dossier_type: "custom",
      title: "SV2 Demo · Nexus Ibérica Sistemas",
      version: 3,
      profile_config: {
        version: "v1",
        own_offer: "Software e IA",
        decision_to_make: "Priorizar PLACSP software",
        competitors: [
          { name: "Capgemini", aliases: [] },
          { name: "NTT DATA", aliases: [] },
          { name: "Inetum", aliases: [] },
        ],
        cpv: ["72000000", "72200000"],
        barriers: ["Homologación"],
        keywords: ["software", "IA"],
        geographies: ["ES"],
        target_buyers: [],
        segments: [],
        success_indicators: [],
        sources: [],
        business_objective: "",
      },
    };
    mocks.get.mockResolvedValue(customDossier);
    mocks.update.mockResolvedValue({
      ...customDossier,
      version: 4,
      profile_config: {
        version: "custom.v1",
        own_offer: "Software, plataformas e IA para AAPP",
        decision_to_make: "Priorizar PLACSP software",
        competitors: customDossier.profile_config.competitors,
        cpv: ["72000000", "72200000", "72212000"],
        barriers: ["Homologación"],
        keywords: ["software", "IA"],
        geographies: ["ES"],
        target_buyers: [],
        segments: [],
        success_indicators: [],
        sources: [],
        business_objective: "",
      },
    });

    render(<DossierSettingsSection dossierId="dossier-1" />);

    expect(await screen.findByRole("heading", { name: "Perfil del expediente" })).toBeVisible();
    expect(screen.getByLabelText("Oferta propia")).toHaveValue("Software e IA");
    expect(screen.getByLabelText("Competidores")).toHaveValue("Capgemini, NTT DATA, Inetum");
    expect(screen.getByLabelText("Códigos CPV")).toHaveValue("72000000, 72200000");
    expect(screen.getByLabelText("Barreras")).toHaveValue("Homologación");
    expect(screen.getByLabelText("Decisión a tomar")).toHaveValue("Priorizar PLACSP software");

    fireEvent.change(screen.getByLabelText("Oferta propia"), {
      target: { value: "Software, plataformas e IA para AAPP" },
    });
    fireEvent.change(screen.getByLabelText("Códigos CPV"), {
      target: { value: "72000000, 72200000, 72212000" },
    });
    fireEvent.click(screen.getByRole("button", { name: /Guardar perfil/ }));

    await waitFor(() =>
      expect(mocks.update).toHaveBeenCalledWith(
        "dossier-1",
        expect.objectContaining({
          version: 3,
          profile_config: expect.objectContaining({
            version: "custom.v1",
            own_offer: "Software, plataformas e IA para AAPP",
            decision_to_make: "Priorizar PLACSP software",
            competitors: [
              { name: "Capgemini", aliases: [] },
              { name: "NTT DATA", aliases: [] },
              { name: "Inetum", aliases: [] },
            ],
            cpv: ["72000000", "72200000", "72212000"],
            barriers: ["Homologación"],
          }),
        }),
        3,
      ),
    );
    expect(mocks.success).toHaveBeenCalledWith("Perfil del expediente actualizado");
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
    fireEvent.change(
      screen.getByPlaceholderText("baterías, subvenciones, almacenamiento"),
      { target: { value: "baterías, subvenciones" } },
    );
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

  /**
   * Exact shapes produced by GET /dossiers/<id>/memory/effective after SV2-HONESTIDAD-SALUD-E2E:
   * top-level publisher_* projected from nested capability (single source of truth).
   * Fixtures are endpoint-shaped — not independent invented objects.
   */
  const effectiveHttpPersisted = {
    id: "mem-1",
    tenant_id: "tenant-1",
    dossier_id: "dossier-1",
    connection_id: null,
    mode: "augment" as const,
    mode_label_es: "Usar para responder",
    version: 2,
    etag: 'W/"dmp-v2-test"',
    sources: ["document"],
    kinds: ["fact"],
    classifications_allowed: ["public"],
    token_budget: 4000,
    limit: 20,
    status: "active",
    state: "active",
    provenance: "server_policy_on_create",
    config_source: "user",
    scope: {
      scope_type: "dossier" as const,
      scope_id: "dossier-1",
      dossier_only: true,
      uses_tenant_curated: false,
      uses_global_memory: false,
      cross_tenant: false,
      included_sources: ["document"],
      included_kinds: ["fact"],
      included_classifications: ["public"],
      exclusions: ["other_dossiers", "other_tenants", "global_memory", "tenant_curated_cross_dossier"],
      summary_es:
        "Usa memoria solo de este expediente (mismo tenant) para responder. No mezcla otros expedientes ni otros tenants.",
    },
    last_test_at: null,
    last_test_status: null,
    last_error: null,
    last_coverage: null,
    updated_at: "2026-08-06T00:00:00Z",
    persisted: true,
    publisher_reliable: true,
    publisher_status: "ok",
    message: "Memory retrieve path operational (dossier-scoped only).",
    resolution_source: "default_profile",
    profiles_diverge: false,
    deferred_connection_profile_count: 0,
    deferred_connection_profiles: [],
    effective_profile: {
      id: "dmp-1",
      mode: "augment" as const,
      version: 2,
      scope_type: "dossier" as const,
      resolution_source: "default_profile",
      persisted: true,
      state: "active",
      connection_id: null,
    },
    configured_profile: {
      id: "dmp-1",
      mode: "augment" as const,
      version: 2,
    },
    capability: {
      host_mode: "http",
      effective_mode: "disabled",
      publisher_reliable: true,
      publisher_status: "ok",
      message: "Memory retrieve path operational (dossier-scoped only).",
      scope_type: "dossier",
      dossier_only: true,
      uses_global_memory: false,
      uses_tenant_curated: false,
      cross_tenant: false,
    },
  };

  const effectiveLegacyMissing = {
    id: null,
    tenant_id: "tenant-1",
    dossier_id: "dossier-1",
    connection_id: null,
    mode: "disabled" as const,
    mode_label_es: "Desactivada",
    version: 0,
    etag: 'W/"dmp-v0-legacy"',
    sources: ["document", "signal"],
    kinds: ["fact", "chunk", "summary"],
    classifications_allowed: ["public", "internal"],
    token_budget: 4000,
    limit: 20,
    status: "legacy_missing",
    state: "legacy_missing",
    provenance: "legacy_missing",
    config_source: "legacy_missing",
    message_es:
      "Este expediente no tiene perfil de memoria persistido (legado). No se ha escrito nada en esta lectura.",
    last_test_at: null,
    last_test_status: null,
    last_error: null,
    last_coverage: null,
    updated_at: null,
    persisted: false,
    publisher_reliable: false,
    publisher_status: "unavailable",
    message: "Memory publisher unavailable (host disabled or connection unhealthy).",
    resolution_source: "legacy_missing",
    profiles_diverge: false,
    deferred_connection_profile_count: 0,
    deferred_connection_profiles: [],
    effective_profile: {
      id: null,
      mode: "disabled" as const,
      version: null,
      scope_type: "dossier" as const,
      resolution_source: "legacy_missing",
      persisted: false,
      state: "legacy_missing",
      connection_id: null,
    },
    capability: {
      host_mode: "disabled",
      effective_mode: "disabled",
      publisher_reliable: false,
      publisher_status: "unavailable",
      message: "Memory publisher unavailable (host disabled or connection unhealthy).",
      scope_type: "dossier",
      dossier_only: true,
      uses_global_memory: false,
      uses_tenant_curated: false,
      cross_tenant: false,
    },
  };

  it("endpoint http/persisted: top-level healthy → no banner degradado", async () => {
    expect(effectiveHttpPersisted.publisher_reliable).toBe(
      effectiveHttpPersisted.capability.publisher_reliable,
    );
    mocks.memoryGet.mockResolvedValue(effectiveHttpPersisted);
    render(<DossierSettingsSection dossierId="dossier-1" />);
    const section = await screen.findByTestId("dossier-memory-settings");
    await waitFor(() =>
      expect(within(section).getByTestId("dossier-memory-meta")).toHaveTextContent(/Versión 2/),
    );
    expect(within(section).getByRole("heading", { name: "Memoria de este expediente" })).toBeVisible();
    expect(within(section).getByTestId("dossier-memory-scope")).toHaveTextContent(
      /solo de este expediente/i,
    );
    expect(within(section).getByTestId("dossier-memory-effective-mode")).toHaveTextContent(
      "augment",
    );
    expect(within(section).getByTestId("dossier-memory-resolution-source")).toHaveTextContent(
      "default_profile",
    );
    expect(within(section).queryByText(/servicio no disponible\/degradado/i)).not.toBeInTheDocument();
    expect(effectiveHttpPersisted).not.toHaveProperty("actions_reliable");
    expect(effectiveHttpPersisted).not.toHaveProperty("deferred_blockers");
  });

  it("legacy_missing: muestra materializar y no afirma que recuerda", async () => {
    expect(effectiveLegacyMissing.publisher_reliable).toBe(
      effectiveLegacyMissing.capability.publisher_reliable,
    );
    expect(effectiveLegacyMissing.publisher_reliable).toBe(false);
    mocks.memoryGet.mockResolvedValue(effectiveLegacyMissing);
    render(<DossierSettingsSection dossierId="dossier-1" />);
    const section = await screen.findByTestId("dossier-memory-settings");
    await waitFor(() =>
      expect(within(section).getByTestId("dossier-memory-legacy")).toBeInTheDocument(),
    );
    expect(within(section).getByText(/no recuerda contexto/i)).toBeInTheDocument();
    expect(
      within(section).getByRole("button", { name: /Materializar perfil de memoria/i }),
    ).toBeInTheDocument();
  });

  it("guarda modo con expected_version y CAS", async () => {
    mocks.memoryGet.mockResolvedValue(effectiveHttpPersisted);
    mocks.memoryPut.mockResolvedValue({
      ...effectiveHttpPersisted,
      mode: "disabled",
      version: 3,
      etag: 'W/"dmp-v3-test"',
    });
    render(<DossierSettingsSection dossierId="dossier-1" />);
    const section = await screen.findByTestId("dossier-memory-settings");
    await waitFor(() =>
      expect(within(section).getByTestId("dossier-memory-mode")).toBeInTheDocument(),
    );
    fireEvent.change(within(section).getByTestId("dossier-memory-mode"), {
      target: { value: "disabled" },
    });
    fireEvent.click(within(section).getByRole("button", { name: /Guardar memoria/i }));
    await waitFor(() =>
      expect(mocks.memoryPut).toHaveBeenCalledWith(
        "dossier-1",
        expect.objectContaining({
          mode: "disabled",
          expected_version: 2,
        }),
        'W/"dmp-v2-test"',
      ),
    );
  });

  it("muestra overrides de conexión diferidos sin cambiar el modo efectivo", async () => {
    mocks.memoryGet.mockResolvedValue({
      ...effectiveHttpPersisted,
      mode: "disabled",
      effective_profile: {
        id: "dmp-1",
        mode: "disabled",
        version: 2,
        scope_type: "dossier",
        resolution_source: "default_profile",
        persisted: true,
        state: "active",
        connection_id: null,
      },
      deferred_connection_profile_count: 1,
      deferred_connection_profiles: [
        {
          id: "dmp-conn",
          connection_id: "conn-1",
          mode: "augment",
          version: 1,
          status: "deferred_connection_override",
          product_supported: false,
        },
      ],
    });
    render(<DossierSettingsSection dossierId="dossier-1" />);
    const section = await screen.findByTestId("dossier-memory-settings");
    await waitFor(() =>
      expect(within(section).getByTestId("dossier-memory-effective-mode")).toHaveTextContent(
        "disabled",
      ),
    );
    expect(within(section).getByTestId("dossier-memory-deferred-overrides")).toHaveTextContent(
      /diferidos/i,
    );
    expect(within(section).getByTestId("dossier-memory-resolution-source")).toHaveTextContent(
      "default_profile",
    );
  });
});
