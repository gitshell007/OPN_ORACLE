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
    dossierRiskAnalysis: {
      latest: mocks.latest,
      run: mocks.run,
      review: mocks.review,
    },
    risks: {
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

import { DossierRiskAnalysisSection } from "./dossier-risk-analysis-section";

const groundedArtifact = {
  id: "art-risk-1",
  dossier_id: "dossier-1",
  agent: "risk",
  schema_name: "risk",
  schema_version: "v1",
  status: "pending_review",
  audit_log_id: "audit-risk-1",
  created_at: "2026-08-03T12:00:00+00:00",
  updated_at: "2026-08-03T12:00:00+00:00",
  version: 1,
  output: {
    title: "Plazo corto de presentación",
    category: "operational",
    description: "Deadline próximo según pliego",
    recommended_status: "watch",
    scores: {
      impact: 60,
      likelihood: 55,
      velocity: 70,
      exposure: 50,
      uncertainty: 40,
      controllability: 45,
      overall: 55,
    },
    confidence: 60,
    facts: [
      {
        statement: "Deadline 2026-08-05T16:30:00Z",
        evidence_ids: ["ev-1"],
      },
    ],
    inferences: [],
    recommendations: [],
    open_questions: [],
    warnings: [],
    scenarios: [
      {
        name: "No se presenta a tiempo",
        description: "Pérdida de la ventana",
        probability: 40,
        impact: 70,
        evidence_ids: ["ev-1"],
      },
    ],
    mitigations: [
      {
        action: "Priorizar documentación",
        owner_role: "captación",
        effectiveness: 60,
        trigger: "Faltan 5 días",
      },
    ],
    risk_context_declared: [
      {
        statement: "Barrera declarada por el cliente: Homologación sectorial",
        category: "homologation",
        declared_evidence_ids: ["decl-barriers"],
        origin: "declared_by_client",
        relevance: "Contexto de riesgo del perfil",
      },
      {
        statement: "Barrera declarada por el cliente: Solvencia económica limitada",
        category: "solvency",
        declared_evidence_ids: ["decl-barriers"],
        origin: "declared_by_client",
      },
    ],
  },
};

describe("DossierRiskAnalysisSection", () => {
  afterEach(() => {
    cleanup();
  });

  beforeEach(() => {
    vi.clearAllMocks();
    mocks.latest.mockResolvedValue({ job: null, artifact: null });
    mocks.run.mockResolvedValue({
      job: { id: "job-r1", status: "succeeded" },
      artifact: groundedArtifact,
    });
    mocks.create.mockResolvedValue({ id: "risk-created-1", title: groundedArtifact.output.title });
    mocks.review.mockResolvedValue({ review_id: "rev-r1", artifact_status: "valid" });
  });

  it("muestra vacío y lanza el análisis sin crear riesgo", async () => {
    const view = render(<DossierRiskAnalysisSection dossierId="dossier-1" />);
    expect(await view.findByTestId("dossier-risk-empty")).toBeInTheDocument();
    fireEvent.click(view.getByTestId("dossier-risk-run"));
    await waitFor(() => expect(mocks.run).toHaveBeenCalledWith("dossier-1", expect.any(String)));
    expect(mocks.create).not.toHaveBeenCalled();
    expect(mocks.review).not.toHaveBeenCalled();
  });

  it("camino feliz: confirma y crea el riesgo con citas", async () => {
    mocks.latest.mockResolvedValue({ job: null, artifact: groundedArtifact });
    const view = render(<DossierRiskAnalysisSection dossierId="dossier-1" />);
    const proposal = await view.findByTestId("dossier-risk-proposal");
    expect(within(proposal).getByTestId("dossier-risk-facts")).toHaveTextContent(
      "Deadline 2026-08-05",
    );
    expect(within(proposal).getByTestId("dossier-risk-scenarios")).toHaveTextContent(
      "No se presenta a tiempo",
    );
    const declared = within(proposal).getByTestId("dossier-risk-context-declared");
    expect(declared).toHaveTextContent("Declarado por el cliente");
    expect(declared).toHaveTextContent("Homologación sectorial");
    expect(declared).toHaveTextContent("Solvencia económica limitada");
    fireEvent.click(view.getByTestId("dossier-risk-apply"));
    await waitFor(() => {
      expect(mocks.create).toHaveBeenCalledWith(
        "dossier-1",
        expect.objectContaining({
          title: "Plazo corto de presentación",
          category: "operational",
          status: "open",
        }),
      );
      expect(mocks.review).toHaveBeenCalledWith(
        "art-risk-1",
        expect.objectContaining({ decision: "accepted" }),
      );
    });
  });

  it("camino cancelado: descarta sin crear riesgo", async () => {
    mocks.latest.mockResolvedValue({ job: null, artifact: groundedArtifact });
    const view = render(<DossierRiskAnalysisSection dossierId="dossier-1" />);
    await view.findByTestId("dossier-risk-proposal");
    fireEvent.click(view.getByTestId("dossier-risk-reject"));
    await waitFor(() => {
      expect(mocks.review).toHaveBeenCalledWith(
        "art-risk-1",
        expect.objectContaining({ decision: "rejected" }),
      );
      expect(mocks.create).not.toHaveBeenCalled();
    });
  });
});
