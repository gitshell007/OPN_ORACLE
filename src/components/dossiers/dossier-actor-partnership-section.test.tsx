import { cleanup, fireEvent, render, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  latest: vi.fn(),
  run: vi.fn(),
  review: vi.fn(),
  listDossier: vi.fn(),
  updateLink: vi.fn(),
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
    dossierActorPartnership: {
      latest: mocks.latest,
      run: mocks.run,
      review: mocks.review,
    },
    actors: {
      listDossier: mocks.listDossier,
      updateLink: mocks.updateLink,
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

import { DossierActorPartnershipSection } from "./dossier-actor-partnership-section";

const evidenceId = "b15d77de-0000-4000-8000-000000000001";

const groundedArtifact = {
  id: "art-ap-1",
  dossier_id: "dossier-1",
  agent: "actor_partnership",
  schema_name: "actor_partnership",
  schema_version: "v1",
  status: "pending_review",
  audit_log_id: "audit-ap-1",
  created_at: "2026-08-04T03:00:00+00:00",
  updated_at: "2026-08-04T03:00:00+00:00",
  version: 1,
  output: {
    actor_id: "actor-1",
    roles: [{ role: "competidor", basis: "fact", confidence: 70, evidence_ids: [evidenceId] }],
    scores: {
      influence: 70,
      relevance: 80,
      relationship_strength: 40,
      accessibility: 50,
      strategic_alignment: 60,
      recent_activity: 75,
      overall_priority: 72,
    },
    confirmed_relationships: [],
    inferred_relationships: [],
    observable_interests: [],
    information_gaps: [],
    relationships: [],
    engagement_actions: [],
    facts: [
      {
        statement: "Capgemini aparece como adjudicataria en PLACSP con importe publicado.",
        evidence_ids: [evidenceId],
      },
    ],
    inferences: [],
    recommendations: [],
    confidence: 60,
    open_questions: [],
    warnings: [],
  },
};

describe("DossierActorPartnershipSection", () => {
  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  beforeEach(() => {
    mocks.latest.mockResolvedValue({ job: null, artifact: groundedArtifact });
    mocks.listDossier.mockResolvedValue({
      data: [{ id: "link-1", actor_id: "actor-1", version: 3, priority: 10 }],
    });
    mocks.updateLink.mockResolvedValue({
      id: "link-1",
      actor_id: "actor-1",
      version: 4,
      priority: 72,
    });
    mocks.review.mockResolvedValue({ decision: "accepted" });
  });

  it("aplica scores solo con hechos citados y actor vinculado", async () => {
    const { getByTestId } = render(<DossierActorPartnershipSection dossierId="dossier-1" />);
    await waitFor(() => expect(getByTestId("dossier-actor-partnership-proposal")).toBeTruthy());
    fireEvent.click(getByTestId("dossier-actor-partnership-apply"));
    await waitFor(() => expect(mocks.updateLink).toHaveBeenCalled());
    expect(mocks.updateLink.mock.calls[0][0]).toBe("link-1");
    expect(mocks.updateLink.mock.calls[0][1].relevance_to_dossier).toBe(80);
    expect(mocks.review).toHaveBeenCalledWith(
      "art-ap-1",
      expect.objectContaining({ decision: "accepted" }),
    );
  });

  it("descarta sin mutar scores", async () => {
    const { getByTestId } = render(<DossierActorPartnershipSection dossierId="dossier-1" />);
    await waitFor(() => expect(getByTestId("dossier-actor-partnership-reject")).toBeTruthy());
    fireEvent.click(getByTestId("dossier-actor-partnership-reject"));
    await waitFor(() => expect(mocks.review).toHaveBeenCalled());
    expect(mocks.updateLink).not.toHaveBeenCalled();
    expect(mocks.review).toHaveBeenCalledWith(
      "art-ap-1",
      expect.objectContaining({ decision: "rejected" }),
    );
  });
});
