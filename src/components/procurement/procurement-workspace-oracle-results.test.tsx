import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  executeSearchPlan: vi.fn(),
  tenders: vi.fn(),
  searches: vi.fn(),
  profiles: vi.fn(),
  watches: vi.fn(),
  listFeedback: vi.fn(),
  feedbackDigest: vi.fn(),
  dossiers: vi.fn(),
}));

const plan = {
  intent_summary: "Vehículos y repuestos para defensa",
  include_terms: ["acorazados"],
  synonyms: ["repuestos TOA"],
  exclude_terms: [],
  candidate_cpv: [{ code: "35400000", label: "Vehículos militares" }],
  buyers: ["Ministerio de Defensa"],
  geographies: [],
  scope: "active" as const,
  min_amount: null,
  max_amount: null,
  assumptions: [],
  questions: [],
  confidence: 84,
  discarded_count: 0,
  discarded_reasons: {},
};

const profile = {
  id: "profile-oracle",
  original_description: "Equipamiento para vehículos del ejército",
  version: 1,
};

const tender = {
  folder_id: "DEF-1",
  title: "Repuestos para vehículos acorazados",
  buyer: "Parque y Centro de Mantenimiento",
  canonical_status: "open",
  cpv: ["35400000"],
  amount: 120000,
  deadline: "2026-09-01",
  region: "Madrid",
  source_url: "https://contrataciondelestado.es/def-1",
  is_active: true,
};

function execution() {
  return {
    plan,
    execution: {
      results: {
        items: Array.from({ length: 60 }, (_, index) => ({
          ...tender,
          folder_id: `DEF-${index + 1}`,
          title: `Repuestos para vehículos acorazados · ${index + 1}`,
        })),
        total: 60,
        limit: 100,
        offset: 0,
      },
      probes: [],
      provider_requests: 2,
    },
  };
}

vi.mock("@oracle/api-client", () => ({
  ApiError: class ApiError extends Error {},
  api: {
    procurement: {
      tenders: mocks.tenders,
      searches: mocks.searches,
      executeSearchPlan: mocks.executeSearchPlan,
      suggest: vi.fn().mockResolvedValue({ suggestions: [] }),
    },
    procurementSearchProfiles: {
      list: mocks.profiles,
      listFeedback: mocks.listFeedback,
      feedbackDigest: mocks.feedbackDigest,
    },
    procurementSearchWatches: {
      list: mocks.watches,
      items: vi.fn().mockResolvedValue({ items: [] }),
    },
    dossiers: { list: mocks.dossiers },
  },
}));

vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams(),
}));

vi.mock("@/components/auth/auth-boundary", () => ({
  PermissionGate: ({ children }: { children: React.ReactNode }) => children,
}));

vi.mock("./pin-to-dossier-control", () => ({
  PinToDossierControl: () => <span>Control de fijado</span>,
}));

vi.mock("./procurement-search-wizard", () => ({
  ProcurementSearchWizard: ({
    onSearchExecuted,
  }: {
    onSearchExecuted?: (result: unknown) => void | Promise<void>;
  }) => (
    <button
      type="button"
      onClick={() =>
        void onSearchExecuted?.({
          plan,
          profile,
          run: {
            search: {
              id: "plan-exec:profile-oracle",
              name: "Vigilancia sintética",
              keywords: ["acorazados"],
              filters: { scope: "active", cpv: "35400000" },
            },
            results: execution().execution.results,
          },
          watchPersisted: false,
          watchWarning:
            "La búsqueda se ejecutó, pero no se pudo guardar la vigilancia opcional.",
        })
      }
    >
      Simular búsqueda Oracle
    </button>
  ),
}));

import { ProcurementWorkspace } from "./procurement-workspace";

describe("resultados multisonda en ProcurementWorkspace", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.tenders.mockResolvedValue({
      items: [],
      total: 0,
      limit: 25,
      offset: 0,
    });
    mocks.searches.mockResolvedValue({ items: [] });
    mocks.profiles.mockResolvedValue({ items: [] });
    mocks.watches.mockResolvedValue({ items: [] });
    mocks.listFeedback.mockResolvedValue({ items: [] });
    mocks.feedbackDigest.mockResolvedValue({
      plan_version: 1,
      new_feedback_count: 0,
      counts: { relevant: 0, not_relevant: 0 },
      reasons: {},
      exclusion_candidates: { terms: [], cpvs: [] },
      reinforcement_candidates: { terms: [], cpvs: [] },
    });
    mocks.dossiers.mockResolvedValue({ data: [], meta: { total: 0 } });
    mocks.executeSearchPlan.mockResolvedValue(execution());
  });

  afterEach(cleanup);

  it("conserva el plan y pagina la ventana Oracle sin proyectar filtros estrechos", async () => {
    render(<ProcurementWorkspace />);
    await screen.findByText("No hay licitaciones para estos criterios");

    fireEvent.click(
      screen.getByRole("button", { name: "Simular búsqueda Oracle" }),
    );
    expect(
      await screen.findByText("Repuestos para vehículos acorazados · 1"),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/Resultados inmediatos del plan Oracle/),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/Si guardas una vigilancia/),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("alert"),
    ).toHaveTextContent("no se pudo guardar la vigilancia opcional");
    expect(screen.getByLabelText("Términos de búsqueda")).toHaveValue("");
    expect(screen.getByLabelText("Descripción del tema")).toHaveValue(
      "Equipamiento para vehículos del ejército",
    );
    expect(
      screen.getByRole("navigation", { name: "Páginas de licitaciones" }),
    ).toHaveTextContent("Página 1 de 3 · ventana Oracle de hasta 100");

    fireEvent.click(screen.getByRole("button", { name: "Siguiente" }));
    expect(mocks.executeSearchPlan).not.toHaveBeenCalled();
    expect(
      await screen.findByText("Repuestos para vehículos acorazados · 26"),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("navigation", { name: "Páginas de licitaciones" }),
    ).toHaveTextContent("Página 2 de 3");

    fireEvent.click(screen.getByRole("button", { name: "Actualizar" }));
    await waitFor(() =>
      expect(mocks.executeSearchPlan).toHaveBeenLastCalledWith(plan, {
        limit: 100,
        offset: 0,
      }),
    );
    expect(mocks.tenders).toHaveBeenCalledTimes(1);
  });
});
