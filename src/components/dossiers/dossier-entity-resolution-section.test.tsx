import { cleanup, fireEvent, render, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  latest: vi.fn(),
  run: vi.fn(),
  review: vi.fn(),
  merge: vi.fn(),
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
    dossierEntityResolution: {
      latest: mocks.latest,
      run: mocks.run,
      review: mocks.review,
    },
    actors: {
      merge: mocks.merge,
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

import { DossierEntityResolutionSection } from "./dossier-entity-resolution-section";

const evidenceId = "b15d77de-0000-4000-8000-000000000001";

const groundedArtifact = {
  id: "art-er-1",
  dossier_id: "dossier-1",
  agent: "entity_resolution",
  schema_name: "entity_resolution",
  schema_version: "v1",
  status: "pending_review",
  audit_log_id: "audit-er-1",
  created_at: "2026-08-04T03:00:00+00:00",
  updated_at: "2026-08-04T03:00:00+00:00",
  version: 1,
  output: {
    decision: "match",
    matched_actor_id: "actor-target",
    rationale: "Mismo CIF B12345678 en adjudicaciones.",
    facts: [
      {
        statement: "Ambas grafías comparten CIF B12345678 en PLACSP.",
        evidence_ids: [evidenceId],
      },
    ],
    inferences: [],
    recommendations: [],
    confidence: 90,
    open_questions: [],
    warnings: [],
  },
};

describe("DossierEntityResolutionSection", () => {
  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  beforeEach(() => {
    mocks.latest.mockResolvedValue({ job: null, artifact: groundedArtifact });
    mocks.review.mockResolvedValue({ decision: "accepted" });
    mocks.merge.mockResolvedValue({ id: "actor-target", canonical_name: "TYPSA" });
  });

  it("acepta sin fusionar por defecto", async () => {
    const { getByTestId } = render(<DossierEntityResolutionSection dossierId="dossier-1" />);
    await waitFor(() => expect(getByTestId("dossier-entity-resolution-accept")).toBeTruthy());
    fireEvent.click(getByTestId("dossier-entity-resolution-accept"));
    await waitFor(() => expect(mocks.review).toHaveBeenCalled());
    expect(mocks.merge).not.toHaveBeenCalled();
    expect(mocks.review).toHaveBeenCalledWith(
      "art-er-1",
      expect.objectContaining({
        decision: "accepted",
        override: expect.objectContaining({ merge_performed: false }),
      }),
    );
  });

  it("fusiona solo con confirmación explícita de origen y motivo", async () => {
    const { getByTestId } = render(<DossierEntityResolutionSection dossierId="dossier-1" />);
    await waitFor(() => expect(getByTestId("dossier-entity-resolution-merge")).toBeTruthy());
    fireEvent.change(getByTestId("dossier-entity-resolution-source"), {
      target: { value: "actor-source" },
    });
    fireEvent.change(getByTestId("dossier-entity-resolution-merge-reason"), {
      target: { value: "Mismo CIF en PLACSP" },
    });
    fireEvent.click(getByTestId("dossier-entity-resolution-merge"));
    await waitFor(() => expect(mocks.merge).toHaveBeenCalled());
    expect(mocks.merge).toHaveBeenCalledWith("actor-target", {
      source_actor_id: "actor-source",
      reason: "Mismo CIF en PLACSP",
    });
  });
});
