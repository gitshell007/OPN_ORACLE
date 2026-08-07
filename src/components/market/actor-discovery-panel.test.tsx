import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { MarketActorDiscoveryOutput } from "@oracle/api-client";

const mocks = vi.hoisted(() => ({
  getDossier: vi.fn(),
  latest: vi.fn(),
  run: vi.fn(),
  accept: vi.fn(),
  toastSuccess: vi.fn(),
  toastMessage: vi.fn(),
  authIdentity: {
    user: { id: "u1", platform_role: null as string | null },
    active_tenant_id: "t1",
    permissions: [] as string[],
  },
}));

vi.mock("@oracle/api-client", () => ({
  ApiError: class ApiError extends Error {
    problem = { detail: this.message };
    constructor(message: string) {
      super(message);
    }
  },
  api: {
    dossiers: { get: mocks.getDossier },
    marketActorDiscovery: {
      latest: mocks.latest,
      run: mocks.run,
      accept: mocks.accept,
    },
  },
}));

vi.mock("sonner", () => ({
  toast: { success: mocks.toastSuccess, message: mocks.toastMessage },
}));

vi.mock("next/link", () => ({
  default: ({
    href,
    children,
    ...rest
  }: {
    href: string;
    children: React.ReactNode;
    [key: string]: unknown;
  }) => (
    <a href={href} {...rest}>
      {children}
    </a>
  ),
}));

vi.mock("@/components/auth/auth-provider", () => ({
  useAuth: () => ({
    status: "authenticated",
    identity: mocks.authIdentity,
    error: null,
    can: () => true,
    login: vi.fn(),
    logout: vi.fn(),
    refresh: vi.fn(),
    switchTenant: vi.fn(),
  }),
}));

import {
  ActorDiscoveryPanel,
  resolveActorDiscoveryFailure,
} from "./actor-discovery-panel";

const INTENT =
  "quiero contactar con grupos de investigación en Francia que trabajen en grafeno";

const closedOutput: MarketActorDiscoveryOutput = {
  candidates: [
    {
      candidate_id: "11111111-1111-4111-8111-111111111111",
      actor_type: "research_group",
      organization: "Lab Grafeno CNRS",
      affiliation: "Université de Lorraine",
      country: "FR",
      summary: "Grupo con línea de grafeno en Francia.",
      rationale: "Coincide con la intención.",
      evidence_ids: ["22222222-2222-4222-8222-222222222222"],
      citable_sources: [
        {
          source_id: "22222222-2222-4222-8222-222222222222",
          title: "Paper grafeno",
          url: "https://example.org/grafeno",
          domain: "example.org",
          label: "Paper grafeno",
          origin_label: "Fuente encontrada por búsqueda",
        },
      ],
      confidence: 80,
      selectable: true,
    },
  ],
  warnings: [],
};

function marketDossier(actorType = "research_group") {
  return {
    id: "d1",
    dossier_type: "market",
    profile_config: {
      discovery_intent: INTENT,
      discovery_actor_type: actorType,
    },
  };
}

describe("resolveActorDiscoveryFailure", () => {
  it("clasifica por error_code aunque el mensaje cambie de redacción", () => {
    const info = resolveActorDiscoveryFailure({
      error_code: "ai_policy_denied",
      error_message: "redacción totalmente distinta que ya no menciona IA ni tenant",
    });
    expect(info.kind).toBe("ai_policy_denied");
    expect(info.message).toMatch(/administrador de plataforma/i);
    expect(info.actionHref).toBeUndefined();
  });

  it("con ai_policy_denied y super_admin ofrece enlace a IA", () => {
    const info = resolveActorDiscoveryFailure(
      {
        error_code: "ai_policy_denied",
        error_message: "cualquier prosa",
      },
      { isPlatformSuperAdmin: true },
    );
    expect(info.kind).toBe("ai_policy_denied");
    expect(info.actionHref).toBe("/app/admin/ai");
    expect(info.message).toMatch(/puedes activarla/i);
  });

  it("con ai_provider_unauthorized no depende del usuario", () => {
    const info = resolveActorDiscoveryFailure({
      error_code: "ai_provider_unauthorized",
      error_message: "prosa irrelevante con la palabra consumidor",
    });
    expect(info.kind).toBe("ai_unavailable");
    expect(info.message).toMatch(/no autoriz|no depende/i);
    expect(info.actionHref).toBeUndefined();
  });

  it("no clasifica por prosa cuando el código es genérico", () => {
    const info = resolveActorDiscoveryFailure({
      error_code: "permanent_failure",
      error_message:
        "El job no pudo completarse. Causa: AIPolicyDenied: La IA está deshabilitada para este tenant.",
    });
    expect(info.kind).toBe("generic");
    expect(info.actionHref).toBeUndefined();
  });
});

describe("ActorDiscoveryPanel — lenguaje de producto", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.authIdentity.user.platform_role = null;
    mocks.getDossier.mockResolvedValue(marketDossier());
    mocks.latest.mockResolvedValue({ job: null, artifact: null });
    mocks.run.mockResolvedValue({
      job: { id: "job-1", status: "queued" },
      artifact: null,
    });
    mocks.accept.mockResolvedValue({
      artifact_id: "a1",
      dossier_id: "d1",
      count: 1,
      materialized: [],
    });
  });

  afterEach(cleanup);

  it("no filtra códigos internos (G-19) ni jerga de servidor al usuario", async () => {
    render(<ActorDiscoveryPanel dossierId="d1" />);
    expect(await screen.findByTestId("actor-discovery-panel")).toBeInTheDocument();
    expect(screen.queryByText(/G-19/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/servidor/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/materializa evidencias citables/i)).not.toBeInTheDocument();
    expect(screen.getByText("Actores a encontrar")).toBeInTheDocument();
  });

  it("muestra el tipo de actor traducido y nunca el enum crudo company", async () => {
    mocks.getDossier.mockResolvedValue(marketDossier("company"));
    render(<ActorDiscoveryPanel dossierId="d1" />);
    expect(await screen.findByTestId("actor-discovery-intent")).toBeInTheDocument();
    const typeLabel = screen.getByTestId("actor-discovery-type-label");
    expect(typeLabel).toHaveTextContent("Empresa");
    expect(typeLabel).not.toHaveTextContent(/^company$/i);
    expect(screen.getByTestId("actor-discovery-intent")).not.toHaveTextContent(
      /Tipo:\s*company/i,
    );
    // No debe aparecer el enum crudo suelto en el bloque de meta
    const meta = screen.getByTestId("actor-discovery-intent");
    expect(within(meta).queryByText("company")).not.toBeInTheDocument();
  });

  it("propietario sin super_admin no recibe enlace a /app/admin/ai", async () => {
    mocks.authIdentity.user.platform_role = null;
    mocks.latest.mockResolvedValue({
      job: {
        id: "job-fail",
        status: "failed",
        error_code: "ai_policy_denied",
        error_message: "redacción distinta sin palabras clave antiguas",
      },
      artifact: null,
    });
    render(<ActorDiscoveryPanel dossierId="d1" />);
    const failed = await screen.findByTestId("actor-discovery-failed");
    expect(failed).toHaveAttribute("role", "alert");
    expect(failed).toHaveAttribute("data-failure-kind", "ai_policy_denied");
    expect(failed).toHaveTextContent(/administrador de plataforma/i);
    expect(screen.queryByTestId("actor-discovery-failure-action")).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /inteligencia artificial/i })).not.toBeInTheDocument();
  });

  it("super_admin con ai_policy_denied ve enlace accionable", async () => {
    mocks.authIdentity.user.platform_role = "super_admin";
    mocks.latest.mockResolvedValue({
      job: {
        id: "job-fail",
        status: "failed",
        error_code: "ai_policy_denied",
        error_message: "otra redacción cualquiera",
      },
      artifact: null,
    });
    render(<ActorDiscoveryPanel dossierId="d1" />);
    const failed = await screen.findByTestId("actor-discovery-failed");
    expect(failed).toHaveAttribute("data-failure-kind", "ai_policy_denied");
    const link = screen.getByTestId("actor-discovery-failure-action");
    expect(link).toHaveAttribute("href", "/app/admin/ai");
  });

  it("con ai_provider_unavailable indica que no depende del usuario", async () => {
    mocks.authIdentity.user.platform_role = null;
    mocks.latest.mockResolvedValue({
      job: {
        id: "job-fail",
        status: "failed",
        error_code: "ai_provider_unavailable",
        error_message: "prosa irrelevante",
      },
      artifact: null,
    });
    render(<ActorDiscoveryPanel dossierId="d1" />);
    const failed = await screen.findByTestId("actor-discovery-failed");
    expect(failed).toHaveAttribute("role", "alert");
    expect(failed).toHaveAttribute("data-failure-kind", "ai_unavailable");
    expect(failed).toHaveTextContent(/no depende/i);
    expect(screen.queryByTestId("actor-discovery-failure-action")).not.toBeInTheDocument();
  });

  it("los botones de solo icono tienen nombre accesible", async () => {
    render(<ActorDiscoveryPanel dossierId="d1" />);
    expect(await screen.findByTestId("actor-discovery-panel")).toBeInTheDocument();
    const reload = screen.getByTestId("actor-discovery-reload");
    expect(reload).toHaveAccessibleName(/actualizar estado/i);
    expect(reload).toHaveAttribute("title");
  });

  it("no muestra ruido si el expediente no tiene discovery_intent", async () => {
    mocks.getDossier.mockResolvedValue({
      id: "d1",
      dossier_type: "market",
      profile_config: {},
    });
    render(<ActorDiscoveryPanel dossierId="d1" />);
    await waitFor(() => expect(mocks.getDossier).toHaveBeenCalledWith("d1"));
    expect(screen.queryByTestId("actor-discovery-panel")).not.toBeInTheDocument();
    expect(mocks.latest).not.toHaveBeenCalled();
  });

  it("consulta latest(dossier_id) y permite iniciar/reintentar con solo dossier_id", async () => {
    render(<ActorDiscoveryPanel dossierId="d1" />);
    expect(await screen.findByTestId("actor-discovery-panel")).toBeInTheDocument();
    await waitFor(() => expect(mocks.latest).toHaveBeenCalledWith("d1"));
    expect(screen.getByTestId("actor-discovery-idle")).toBeInTheDocument();
    expect(screen.getByTestId("actor-discovery-intent")).toHaveTextContent(/grafeno/i);

    fireEvent.click(screen.getByTestId("actor-discovery-retry"));
    await waitFor(() =>
      expect(mocks.run).toHaveBeenCalledWith(
        { dossier_id: "d1" },
        expect.stringMatching(/^g19-actor-run:d1:retry:/),
      ),
    );
  });

  it("renderiza organización, afiliación, FR y citas; accept envía IDs exactos", async () => {
    mocks.latest.mockResolvedValue({
      job: { id: "job-1", status: "succeeded" },
      artifact: {
        id: "artifact-1",
        dossier_id: "d1",
        agent: "market_actor_discovery",
        schema_name: "MarketActorDiscoveryOutput",
        schema_version: "v1",
        status: "candidate",
        version: 3,
        created_at: "2026-08-06T00:00:00Z",
        updated_at: "2026-08-06T00:00:00Z",
        output: closedOutput,
      },
    });
    render(<ActorDiscoveryPanel dossierId="d1" />);
    expect(await screen.findByTestId("actor-discovery-result")).toBeInTheDocument();
    expect(screen.getByText("Lab Grafeno CNRS")).toBeInTheDocument();
    expect(screen.getByText("Université de Lorraine")).toBeInTheDocument();
    expect(screen.getByTestId("actor-type")).toHaveTextContent(/investigación/i);
    expect(screen.getByText("FR")).toBeInTheDocument();
    expect(screen.getByTestId("actor-source-link")).toHaveAttribute(
      "href",
      "https://example.org/grafeno",
    );

    fireEvent.click(screen.getByLabelText(/Seleccionar Lab Grafeno CNRS/i));
    fireEvent.click(screen.getByTestId("actor-discovery-accept"));

    await waitFor(() =>
      expect(mocks.accept).toHaveBeenCalledWith({
        dossier_id: "d1",
        artifact_id: "artifact-1",
        expected_version: 3,
        selected: [
          {
            candidate_id: "11111111-1111-4111-8111-111111111111",
            organization: "Lab Grafeno CNRS",
            source_ids: ["22222222-2222-4222-8222-222222222222"],
          },
        ],
      }),
    );
    expect(mocks.toastSuccess).toHaveBeenCalledWith(
      "Fuentes materializadas",
      expect.objectContaining({
        description: expect.stringMatching(/No se ha creado un Actor/i),
      }),
    );
  });

  it("latest de D1 no se invoca para D2 en el mismo montaje", async () => {
    const { rerender } = render(<ActorDiscoveryPanel dossierId="d1" />);
    await waitFor(() => expect(mocks.latest).toHaveBeenCalledWith("d1"));
    mocks.latest.mockClear();
    rerender(<ActorDiscoveryPanel dossierId="d2" />);
    await waitFor(() => expect(mocks.getDossier).toHaveBeenCalledWith("d2"));
    await waitFor(() => expect(mocks.latest).toHaveBeenCalledWith("d2"));
    expect(mocks.latest).not.toHaveBeenCalledWith("d1");
  });

  it("muestra estados loading y error accesibles", async () => {
    let resolveGet: (v: unknown) => void = () => undefined;
    mocks.getDossier.mockReturnValue(
      new Promise((resolve) => {
        resolveGet = resolve;
      }),
    );
    render(<ActorDiscoveryPanel dossierId="d1" />);
    expect(screen.getByTestId("actor-discovery-loading")).toBeInTheDocument();
    resolveGet(marketDossier());
    mocks.latest.mockRejectedValue(new Error("boom"));
    await waitFor(() =>
      expect(screen.getByTestId("actor-discovery-error")).toBeInTheDocument(),
    );
    expect(screen.getByTestId("actor-discovery-error")).toHaveAttribute("role", "alert");
  });
});
