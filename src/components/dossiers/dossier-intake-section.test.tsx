import { cleanup, fireEvent, render, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  get: vi.fn(),
  latest: vi.fn(),
  run: vi.fn(),
  review: vi.fn(),
  update: vi.fn(),
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
    dossiers: {
      get: mocks.get,
      update: mocks.update,
    },
    dossierIntake: {
      latest: mocks.latest,
      run: mocks.run,
      review: mocks.review,
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

vi.mock("@/lib/product-copy", () => ({
  productDossierTypeLabel: (value: string) => `tipo:${value}`,
}));

import { DossierIntakeSection } from "./dossier-intake-section";

const dossier = {
  id: "dossier-1",
  title: "Borrador vacío",
  description: "Sin estructura",
  dossier_type: "custom",
  status: "draft",
  version: 3,
};

const groundedArtifact = {
  id: "art-1",
  dossier_id: "dossier-1",
  agent: "intake",
  schema_name: "intake",
  schema_version: "v1",
  status: "pending_review",
  audit_log_id: "audit-1",
  created_at: "2026-08-03T12:00:00+00:00",
  updated_at: "2026-08-03T12:00:00+00:00",
  version: 1,
  output: {
    proposed_title: "Pliego hospital",
    proposed_description: "Licitación de servicios TIC",
    dossier_type: "tender_or_grant",
    confidence: 72,
    facts: [
      {
        statement: "El órgano es el SERMAS",
        evidence_ids: ["ev-1"],
      },
      {
        statement: "Hecho inventado sin fuente",
        evidence_ids: [],
      },
    ],
    inferences: [
      {
        statement: "Inferencia con fuente",
        reasoning_summary: "Citado en el pliego",
        confidence: 60,
        evidence_ids: ["ev-1"],
      },
      {
        statement: "Inferencia sin fuente",
        reasoning_summary: "Modelo",
        confidence: 40,
        evidence_ids: [],
      },
    ],
    recommendations: [
      {
        action: "Revisar plazos",
        rationale: "Fecha límite en el documento",
        priority: "high" as const,
      },
    ],
    open_questions: ["¿Hay prórroga?"],
    warnings: ["Revisión humana requerida"],
  },
};

describe("DossierIntakeSection", () => {
  afterEach(() => {
    cleanup();
  });

  beforeEach(() => {
    vi.clearAllMocks();
    mocks.get.mockResolvedValue(dossier);
    mocks.latest.mockResolvedValue({ job: null, artifact: null });
    mocks.run.mockResolvedValue({
      job: { id: "job-1", status: "succeeded" },
      artifact: groundedArtifact,
    });
    mocks.update.mockResolvedValue({ ...dossier, title: "Pliego hospital", version: 4 });
    mocks.review.mockResolvedValue({ review_id: "rev-1", artifact_status: "valid" });
  });

  it("muestra vacío y lanza el análisis sin mutar el expediente", async () => {
    const view = render(<DossierIntakeSection dossierId="dossier-1" />);
    expect(await view.findByTestId("dossier-intake-empty")).toBeInTheDocument();
    fireEvent.click(view.getByTestId("dossier-intake-run"));
    await waitFor(() => expect(mocks.run).toHaveBeenCalledWith("dossier-1", expect.any(String)));
    // Solo propuesta: no PATCH ni review hasta confirmación humana.
    expect(mocks.update).not.toHaveBeenCalled();
    expect(mocks.review).not.toHaveBeenCalled();
  });

  it("camino feliz: confirma y aplica título/descripción al expediente", async () => {
    mocks.latest.mockResolvedValue({ job: null, artifact: groundedArtifact });
    const view = render(<DossierIntakeSection dossierId="dossier-1" />);
    const proposal = await view.findByTestId("dossier-intake-proposal");

    expect(within(proposal).getByTestId("dossier-intake-facts")).toHaveTextContent(
      "El órgano es el SERMAS",
    );
    expect(within(proposal).getByTestId("dossier-intake-facts")).not.toHaveTextContent(
      "Hecho inventado sin fuente",
    );
    expect(within(proposal).getByTestId("dossier-intake-inferences")).toHaveTextContent(
      "Inferencia con fuente",
    );
    expect(within(proposal).getByTestId("dossier-intake-inferences")).not.toHaveTextContent(
      "Inferencia sin fuente",
    );
    expect(within(proposal).getByTestId("dossier-intake-proposed-type")).toHaveTextContent(
      "tipo:tender_or_grant",
    );

    fireEvent.click(view.getByTestId("dossier-intake-apply"));
    await waitFor(() => {
      expect(mocks.update).toHaveBeenCalledWith(
        "dossier-1",
        {
          title: "Pliego hospital",
          description: "Licitación de servicios TIC",
        },
        3,
      );
      expect(mocks.review).toHaveBeenCalledWith(
        "art-1",
        expect.objectContaining({
          decision: "accepted",
          override: expect.objectContaining({
            applied_title: "Pliego hospital",
            type_not_applied: true,
          }),
        }),
      );
    });
  });

  it("camino cancelado: descarta sin mutar el expediente", async () => {
    mocks.latest.mockResolvedValue({ job: null, artifact: groundedArtifact });
    const view = render(<DossierIntakeSection dossierId="dossier-1" />);
    await view.findByTestId("dossier-intake-proposal");
    fireEvent.click(view.getByTestId("dossier-intake-reject"));
    await waitFor(() => {
      expect(mocks.review).toHaveBeenCalledWith(
        "art-1",
        expect.objectContaining({ decision: "rejected" }),
      );
      expect(mocks.update).not.toHaveBeenCalled();
    });
  });
});
