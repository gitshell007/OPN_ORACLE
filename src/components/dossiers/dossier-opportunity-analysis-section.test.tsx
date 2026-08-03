import { cleanup, fireEvent, render, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  latest: vi.fn(),
  run: vi.fn(),
  review: vi.fn(),
  create: vi.fn(),
  toast: { success: vi.fn(), message: vi.fn(), error: vi.fn() },
}));

vi.mock("@oracle/api-client", () => ({
  ApiError: class ApiError extends Error {
    problem: { detail: string };
    constructor(detail: string) {
      super(detail);
      this.problem = { detail };
    }
  },
  api: {
    dossierOpportunityAnalysis: {
      latest: mocks.latest,
      run: mocks.run,
      review: mocks.review,
    },
    opportunities: {
      create: mocks.create,
    },
  },
}));

vi.mock("sonner", () => ({ toast: mocks.toast }));

vi.mock("next/link", () => ({
  default: ({
    children,
    href,
    ...rest
  }: {
    children: React.ReactNode;
    href: string;
  }) => (
    <a href={href} {...rest}>
      {children}
    </a>
  ),
}));

vi.mock("@/components/auth/auth-boundary", () => ({
  PermissionGate: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}));

vi.mock("@/components/reporting/job-progress", () => ({
  JobProgress: () => <div data-testid="job-progress" />,
}));

vi.mock("@/components/ui/async-action-button", () => ({
  AsyncActionButton: ({
    children,
    onClick,
    type = "button",
    disabled,
    loading: _loading,
    className,
    ...rest
  }: {
    children: React.ReactNode;
    onClick?: () => void;
    type?: "button" | "submit";
    disabled?: boolean;
    loading?: boolean;
    className?: string;
  }) => (
    <button type={type} onClick={onClick} disabled={disabled} className={className} {...rest}>
      {children}
    </button>
  ),
}));

vi.mock("@/components/ui/page-header", () => ({
  PageHeader: ({
    title,
    description,
    actions,
  }: {
    title: string;
    description?: string;
    actions?: React.ReactNode;
  }) => (
    <header>
      <h1>{title}</h1>
      {description ? <p>{description}</p> : null}
      {actions}
    </header>
  ),
}));

import { DossierOpportunityAnalysisSection } from "./dossier-opportunity-analysis-section";

const groundedArtifact = {
  id: "art-opp-1",
  dossier_id: "dossier-1",
  agent: "opportunity",
  schema_name: "opportunity",
  schema_version: "v1",
  status: "pending_review",
  audit_log_id: "audit-opp-1",
  created_at: "2026-08-03T12:00:00+00:00",
  updated_at: "2026-08-03T12:00:00+00:00",
  version: 1,
  output: {
    title: "Licitación EMT cubiertas",
    opportunity_type: "tender",
    summary: "Renovación de techos con importe publicado",
    recommendation: "investigate",
    scores: {
      strategic_fit: 60,
      urgency: 70,
      expected_value: 55,
      actionability: 50,
      relationship_leverage: 40,
      timing: 65,
      confidence: 70,
      execution_effort: 50,
      blocking_risk: 45,
      overall: 58,
    },
    confidence: 70,
    facts: [
      {
        statement: "Importe publicado 886799.64",
        evidence_ids: ["ev-1"],
      },
      {
        statement: "Hecho sin fuente",
        evidence_ids: [],
      },
    ],
    inferences: [
      {
        statement: "Ventana de participación abierta",
        reasoning_summary: "Deadline en el pliego",
        confidence: 65,
        evidence_ids: ["ev-1"],
      },
      {
        statement: "Inferencia sin fuente",
        reasoning_summary: "Modelo",
        confidence: 20,
        evidence_ids: [],
      },
    ],
    recommendations: [],
    open_questions: ["¿Encaja con Nexus software?"],
    warnings: ["Revisión humana requerida"],
    next_best_action: {
      action: "Validar CPV y capacidad",
      owner_role: "captación",
      rationale: "Confirmar encaje",
    },
  },
};

describe("DossierOpportunityAnalysisSection", () => {
  afterEach(() => {
    cleanup();
  });

  beforeEach(() => {
    vi.clearAllMocks();
    mocks.latest.mockResolvedValue({ job: null, artifact: null });
    mocks.run.mockResolvedValue({
      job: { id: "job-1", status: "succeeded" },
      artifact: groundedArtifact,
    });
    mocks.create.mockResolvedValue({ id: "opp-created-1", title: groundedArtifact.output.title });
    mocks.review.mockResolvedValue({ review_id: "rev-1", artifact_status: "valid" });
  });

  it("muestra vacío y lanza el análisis sin crear oportunidad", async () => {
    const view = render(<DossierOpportunityAnalysisSection dossierId="dossier-1" />);
    expect(await view.findByTestId("dossier-opportunity-empty")).toBeInTheDocument();
    fireEvent.click(view.getByTestId("dossier-opportunity-run"));
    await waitFor(() => expect(mocks.run).toHaveBeenCalledWith("dossier-1", expect.any(String)));
    expect(mocks.create).not.toHaveBeenCalled();
    expect(mocks.review).not.toHaveBeenCalled();
  });

  it("camino feliz: confirma y crea la oportunidad con hechos citados", async () => {
    mocks.latest.mockResolvedValue({ job: null, artifact: groundedArtifact });
    const view = render(<DossierOpportunityAnalysisSection dossierId="dossier-1" />);
    const proposal = await view.findByTestId("dossier-opportunity-proposal");

    expect(within(proposal).getByTestId("dossier-opportunity-facts")).toHaveTextContent(
      "Importe publicado 886799.64",
    );
    expect(within(proposal).getByTestId("dossier-opportunity-facts")).not.toHaveTextContent(
      "Hecho sin fuente",
    );
    expect(within(proposal).getByTestId("dossier-opportunity-inferences")).toHaveTextContent(
      "Ventana de participación abierta",
    );
    expect(within(proposal).getByTestId("dossier-opportunity-inferences")).not.toHaveTextContent(
      "Inferencia sin fuente",
    );

    fireEvent.click(view.getByTestId("dossier-opportunity-apply"));
    await waitFor(() => {
      expect(mocks.create).toHaveBeenCalledWith(
        "dossier-1",
        expect.objectContaining({
          title: "Licitación EMT cubiertas",
          opportunity_type: "tender",
          status: "identified",
        }),
      );
      expect(mocks.review).toHaveBeenCalledWith(
        "art-opp-1",
        expect.objectContaining({
          decision: "accepted",
          override: expect.objectContaining({
            created_opportunity_id: "opp-created-1",
          }),
        }),
      );
    });
  });

  it("camino cancelado: descarta sin crear oportunidad", async () => {
    mocks.latest.mockResolvedValue({ job: null, artifact: groundedArtifact });
    const view = render(<DossierOpportunityAnalysisSection dossierId="dossier-1" />);
    await view.findByTestId("dossier-opportunity-proposal");
    fireEvent.click(view.getByTestId("dossier-opportunity-reject"));
    await waitFor(() => {
      expect(mocks.review).toHaveBeenCalledWith(
        "art-opp-1",
        expect.objectContaining({ decision: "rejected" }),
      );
      expect(mocks.create).not.toHaveBeenCalled();
    });
  });
});
