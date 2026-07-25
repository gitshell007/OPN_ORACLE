import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  list: vi.fn(),
  create: vi.fn(),
  execute: vi.fn(),
  reviewEntity: vi.fn(),
  reportPreview: vi.fn(),
  success: vi.fn(),
}));

vi.mock("@oracle/api-client", () => ({
  ApiError: class ApiError extends Error {},
  api: {
    investigations: {
      list: mocks.list,
      create: mocks.create,
      execute: mocks.execute,
      reviewEntity: mocks.reviewEntity,
      reportPreview: mocks.reportPreview,
    },
  },
}));

vi.mock("sonner", () => ({ toast: { success: mocks.success } }));
vi.mock("@/components/auth/auth-boundary", () => ({
  PermissionGate: ({ children }: { children: React.ReactNode }) => children,
}));

import { DossierInvestigationsSection } from "./dossier-investigations-section";

const run = {
  id: "run-1",
  dossier_id: "dossier-1",
  question: "Investigar nexos y adjudicaciones.",
  seed: { name: "ITURRI SA", kind: "company", identifiers: {} },
  status: "awaiting_review",
  stage: "P5",
  progress: 90,
  cutoff_at: "2026-07-25T10:00:00Z",
  period_start: null,
  period_end: null,
  protocol_version: "investigation-protocol-v1",
  source_policy_version: "signal-reference-snapshots-v1",
  limits: {},
  source_policy: {},
  corpus_hash: "abc",
  stop_reason: null,
  version: 2,
  created_at: "2026-07-25T10:00:00Z",
  updated_at: "2026-07-25T10:10:00Z",
  steps: [],
  counts: {
    entities: 3,
    verified_entities: 1,
    candidate_entities: 2,
    relations: 2,
    procurement_participations: 1,
    claims: 2,
  },
  entities: [
    {
      id: "entity-1",
      name: "ITURRI SA",
      normalized_name: "ITURRI",
      kind: "company",
      identifiers: {},
      depth: 0,
      resolution_status: "verified",
      identity_confidence: 100,
      gate_reason: null,
      canonical_actor_id: null,
      aliases: [],
    },
    {
      id: "entity-2",
      name: "ITURRI PARTICIPADAS SL",
      normalized_name: "ITURRI PARTICIPADAS",
      kind: "company",
      identifiers: {},
      depth: 1,
      resolution_status: "candidate",
      identity_confidence: 0,
      gate_reason: "Requiere revisión.",
      canonical_actor_id: null,
      aliases: [],
    },
  ],
  relations: [],
  procurement_participations: [],
  claims: [],
} as const;

describe("DossierInvestigationsSection", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.list.mockResolvedValue({ items: [run] });
    mocks.reportPreview.mockResolvedValue({
      investigation: run,
      report: {
        title: "Informe de investigacion: ITURRI SA",
        protocol_version: "investigation-protocol-v1",
        source_policy_version: "signal-reference-snapshots-v1",
        corpus_hash: "abc",
        generated_at: "2026-07-25T10:11:00Z",
        sections: { executive_summary: "Resumen trazable." },
        markdown: "Resumen trazable.\n- PLACSP-1",
        limitations: [],
      },
      verified_entities: [run.entities[0]],
      candidate_entities: [run.entities[1]],
    });
    mocks.reviewEntity.mockResolvedValue({
      ...run,
      entities: [{ ...run.entities[1], resolution_status: "verified" }],
    });
    mocks.execute.mockResolvedValue({ investigation: run, job: { id: "job-1" } });
  });

  afterEach(cleanup);

  it("muestra métricas, revisión humana y borrador de informe", async () => {
    render(<DossierInvestigationsSection dossierId="dossier-1" />);

    expect(await screen.findByRole("heading", { name: "ITURRI SA" })).toBeVisible();
    expect(screen.getByText("3")).toBeVisible();
    expect(await screen.findByText("Resumen trazable.")).toBeVisible();

    const reviewBlock = screen.getByRole("heading", { name: /Revisión de identidad/ })
      .parentElement;
    expect(reviewBlock).not.toBeNull();
    expect(within(reviewBlock as HTMLElement).getByText("ITURRI PARTICIPADAS SL")).toBeVisible();

    fireEvent.click(
      screen.getByRole("button", { name: "Verificar ITURRI PARTICIPADAS SL" }),
    );
    await waitFor(() =>
      expect(mocks.reviewEntity).toHaveBeenCalledWith("run-1", "entity-2", {
        decision: "verify",
      }),
    );

    fireEvent.click(screen.getByRole("button", { name: /Ejecutar pasada/ }));
    await waitFor(() => expect(mocks.execute).toHaveBeenCalledWith("run-1", expect.any(String)));
  });
});
