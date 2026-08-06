import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  aliasCandidates: vi.fn(),
  merge: vi.fn(),
  mergePreview: vi.fn(),
  success: vi.fn(),
}));

vi.mock("@oracle/api-client", () => ({
  ApiError: class ApiError extends Error {
    problem = { detail: this.message, code: "version_conflict" };
  },
  api: {
    actors: {
      aliasCandidates: mocks.aliasCandidates,
      merge: mocks.merge,
      mergePreview: mocks.mergePreview,
    },
  },
}));

vi.mock("sonner", () => ({ toast: { success: mocks.success } }));
vi.mock("@/components/auth/auth-boundary", () => ({
  PermissionGate: ({ children }: { children: React.ReactNode }) => children,
}));

import { ActorDuplicateMergePanel } from "./actor-duplicate-merge-panel";

const nameCandidate = {
  identity_key: "ITURRI",
  status: "candidate",
  match_reason: "normalized_name",
  priority: 10,
  confidence: "low",
  suggested_target_id: "actor-sa",
  reason: "Coincidencia de denominación sin forma jurídica; requiere revisión.",
  actors: [
    {
      id: "actor-sa",
      name: "ITURRI SA",
      identifiers: {},
      aliases: [],
      tax_id: null,
      version: 1,
      has_durable_tax_id_column: false,
      tax_id_provenance: { origin_label: "sin procedencia fiscal", verified: false },
    },
    {
      id: "actor-plain",
      name: "Iturri",
      identifiers: {},
      aliases: ["Iturri S.A."],
      tax_id: null,
      version: 1,
      has_durable_tax_id_column: false,
      tax_id_provenance: { origin_label: "sin procedencia fiscal", verified: false },
    },
  ],
};

const taxCandidate = {
  identity_key: "tax:es:B08377715",
  status: "candidate",
  match_reason: "tax_id",
  priority: 100,
  confidence: "high",
  suggested_target_id: "cap-a",
  tax_id: "B08377715",
  reason: "Coincidencia fiscal por NIF/CIF durable B08377715.",
  actors: [
    {
      id: "cap-a",
      name: "CAPGEMINI ESPAÑA SL",
      identifiers: { tax_id: "B08377715" },
      aliases: [],
      tax_id: "B08377715",
      tax_id_scheme: "ES_CIF",
      tax_id_country: "ES",
      version: 2,
      has_durable_tax_id_column: true,
      tax_id_provenance: {
        origin_label: "columna fiscal durable (declarado; no verificación oficial)",
        verified: false,
      },
    },
    {
      id: "cap-b",
      name: "Capgemini España S.L.",
      identifiers: { tax_id: "B08377715" },
      aliases: [],
      tax_id: "B08377715",
      tax_id_scheme: "ES_CIF",
      tax_id_country: "ES",
      version: 1,
      has_durable_tax_id_column: false,
      tax_id_provenance: {
        origin_label: "declarado (sin columna durable; no verificación oficial)",
        verified: false,
      },
    },
  ],
};

const blockedCandidate = {
  identity_key: "name-blocked:ACME",
  status: "blocked",
  match_reason: "tax_id_conflict",
  priority: 50,
  confidence: "blocked",
  blocking_tax_ids: ["A11111111", "B22222222"],
  reason: "Misma denominación normalizada pero NIF/CIF durables distintos.",
  actors: [
    {
      id: "a1",
      name: "ACME SL",
      identifiers: {},
      aliases: [],
      tax_id: "A11111111",
      version: 1,
      has_durable_tax_id_column: true,
      tax_id_provenance: { origin_label: "columna fiscal durable", verified: false },
    },
    {
      id: "a2",
      name: "Acme S.L.",
      identifiers: {},
      aliases: [],
      tax_id: "B22222222",
      version: 1,
      has_durable_tax_id_column: true,
      tax_id_provenance: { origin_label: "columna fiscal durable", verified: false },
    },
  ],
};

const meta = {
  organizations_evaluated: 18,
  organizations_with_tax_id: 3,
  tax_id_coverage_pct: 16.67,
  criteria_evaluated: ["tax_id", "normalized_name"],
  counts: { tax_id: 1, normalized_name: 1, tax_id_conflict_blocked: 0, total_items: 2 },
  limitations: "3/18 organizaciones con NIF/CIF durable evaluable.",
  empty_state_message:
    "No hay candidatos bajo los criterios evaluados. Cobertura NIF: 3/18 (16.67%).",
};

describe("ActorDuplicateMergePanel", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.aliasCandidates.mockResolvedValue({ items: [nameCandidate], meta });
    mocks.mergePreview.mockResolvedValue({
      blocked: false,
      target: nameCandidate.actors[0],
      source: nameCandidate.actors[1],
      resulting_aliases: ["Iturri", "Iturri S.A."],
      reference_impact: {
        source_only: {
          dossier_actors: 1,
          opportunity_actors: 0,
          risk_actors: 0,
          meeting_actors: 0,
          relationships: 0,
        },
        combined_before: {
          dossier_actors: 1,
          opportunity_actors: 0,
          risk_actors: 0,
          meeting_actors: 0,
          relationships: 0,
        },
        summary: "Se moverán/deduplicarán 1 vínculos de expediente del origen.",
      },
      confirmation_required: {
        confirm: true,
        reason_min_length: 3,
        expected_target_version: 1,
        expected_source_version: 1,
      },
    });
    mocks.merge.mockResolvedValue({
      id: "actor-sa",
      canonical_name: "ITURRI SA",
      aliases: ["Iturri", "Iturri S.A."],
      tax_id: null,
      version: 2,
    });
  });
  afterEach(cleanup);

  it("lista candidatos y fusiona solo tras preview + confirmación humana con motivo y CAS", async () => {
    render(<ActorDuplicateMergePanel />);

    await waitFor(() => {
      expect(screen.getByText(/Clave «ITURRI»/)).toBeTruthy();
    });
    expect(screen.getAllByText("ITURRI SA").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Iturri").length).toBeGreaterThan(0);
    expect(screen.getByText(/Coincidencia nominal/i)).toBeTruthy();
    expect(screen.getByText(/3\/18 con NIF durable/i)).toBeTruthy();
    expect(mocks.merge).not.toHaveBeenCalled();

    fireEvent.change(screen.getByPlaceholderText(/Misma empresa/i), {
      target: { value: "Misma empresa, distinta forma jurídica" },
    });
    fireEvent.click(screen.getByRole("button", { name: /Previsualizar fusión/i }));

    await waitFor(() => {
      expect(mocks.mergePreview).toHaveBeenCalledWith("actor-sa", {
        source_actor_id: "actor-plain",
      });
      expect(screen.getByText(/Preview antes de mutar/i)).toBeTruthy();
    });

    fireEvent.click(screen.getByRole("checkbox"));
    fireEvent.click(screen.getByRole("button", { name: /Confirmar fusión/i }));

    await waitFor(() => {
      expect(mocks.merge).toHaveBeenCalledWith("actor-sa", {
        source_actor_id: "actor-plain",
        reason: "Misma empresa, distinta forma jurídica",
        confirm: true,
        expected_target_version: 1,
        expected_source_version: 1,
        match_reason: "normalized_name",
      });
    });
    expect(mocks.success).toHaveBeenCalled();
  });

  it("ordena y muestra match fiscal Capgemini con NIF/procedencia", async () => {
    mocks.aliasCandidates.mockResolvedValue({
      items: [taxCandidate, nameCandidate],
      meta,
    });
    render(<ActorDuplicateMergePanel />);
    await waitFor(() => {
      expect(screen.getByText(/Coincidencia fiscal \(NIF\/CIF\)/i)).toBeTruthy();
    });
    expect(screen.getAllByText(/B08377715/).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/CAPGEMINI ESPAÑA SL/i).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/Capgemini España S\.L\./i).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/no verificación oficial/i).length).toBeGreaterThan(0);
    // tax match appears before name match in document order
    const fiscal = screen.getByText(/Coincidencia fiscal \(NIF\/CIF\)/i);
    const nominal = screen.getByText(/Coincidencia nominal/i);
    expect(
      fiscal.compareDocumentPosition(nominal) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
  });

  it("presenta conflictos de NIF como bloqueados sin formulario de fusión", async () => {
    mocks.aliasCandidates.mockResolvedValue({ items: [blockedCandidate], meta });
    render(<ActorDuplicateMergePanel />);
    await waitFor(() => {
      expect(screen.getByText(/Bloqueo: NIF distintos/i)).toBeTruthy();
    });
    expect(screen.getByText(/Fusión bloqueada/i)).toBeTruthy();
    expect(screen.queryByRole("button", { name: /Previsualizar fusión/i })).toBeNull();
    expect(screen.queryByRole("button", { name: /Confirmar fusión/i })).toBeNull();
  });

  it("estado vacío honesto: no dice limpio y muestra cobertura", async () => {
    mocks.aliasCandidates.mockResolvedValue({ items: [], meta });
    render(<ActorDuplicateMergePanel />);
    await waitFor(() => {
      expect(screen.getByText(/No hay candidatos bajo los criterios evaluados/i)).toBeTruthy();
    });
    expect(screen.queryByText(/directorio está limpio/i)).toBeNull();
    expect(screen.getAllByText(/Cobertura NIF: 3\/18/i).length).toBeGreaterThan(0);
  });
});
