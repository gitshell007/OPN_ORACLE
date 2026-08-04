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
    fit_assessment: {
      statement:
        "Encaje perfil declarado ↔ CONTR 2026 11077: propuesta GO CONDICIONADO (puerta humana).",
      declared_evidence_ids: ["decl-own-offer"],
      official_evidence_ids: ["ev-1"],
      confidence: 48,
      origin: "declared_by_client",
      tender_ref: "CONTR 2026 11077",
      dimensions: [
        {
          key: "cpv",
          label: "CPV",
          requirement: "[oficial] Ámbito: red de agentes inteligentes",
          requirement_origin: "official",
          official_evidence_ids: ["ev-1"],
          capability: "[declarado] CPV 72000000, 72200000",
          capability_origin: "declared_by_client",
          declared_evidence_ids: ["decl-cpv"],
          status: "partial",
          status_reason: "Ámbito TI/IA alineado sin CPV numérico oficial exacto",
        },
        {
          key: "solvency",
          label: "Solvencia (F.2 / F.3)",
          requirement: "[oficial] F.2 volumen ≥1,5×; F.3 servicios 3 años",
          requirement_origin: "official",
          official_evidence_ids: ["ev-1"],
          capability: "[declarado] El perfil no declara volumen anual de negocio",
          capability_origin: "declared_by_client",
          declared_evidence_ids: ["decl-own-offer"],
          status: "not_evaluable",
          status_reason: "no evaluable con lo declarado",
        },
      ],
      verdict: {
        recommendation: "go_conditioned",
        conditions: ["Solo si puede acreditar F.2 volumen ≥1,5×"],
        human_gate: "awaiting_user_confirmation",
        rationale: "Propuesta con puerta humana; no es decisión automática.",
      },
    },
    draft_offer: {
      banner:
        "BORRADOR COMERCIAL — no es documento presentable. Requiere edición humana antes de cualquier presentación o envío.",
      human_gate: "draft_requires_human_edit",
      statement:
        "Borrador de oferta (esqueleto) para CONTR 2026 11077 · Lote 2: Red de agentes inteligentes.",
      tender_ref: "CONTR 2026 11077",
      lot_hint: "Lote 2: Red de agentes inteligentes",
      draft_engine: "sv2_borrador_v1",
      origin: "declared_draft",
      based_on_verdict: "go_conditioned",
      sections: [
        {
          key: "award_economic",
          title: "Oferta económica (fórmulas)",
          points_hint: "65/60 umbral PCAP · criterio económico",
          requirement: "[oficial] Criterios evaluables mediante fórmulas (oferta económica).",
          requirement_origin: "official",
          official_evidence_ids: ["ev-1"],
          our_response_draft:
            "[borrador declarado — no es hecho] Semilla de oferta económica para Lote 2.",
          response_origin: "declared_generated",
          declared_evidence_ids: ["decl-own-offer"],
          gaps: ["Solo si puede acreditar F.2 volumen ≥1,5×"],
        },
        {
          key: "award_technical",
          title: "Oferta técnica (juicio de valor)",
          points_hint: "criterio técnico · juicio de valor",
          requirement: "[oficial] Criterios evaluables mediante juicio de valor (oferta técnica).",
          requirement_origin: "official",
          official_evidence_ids: ["ev-1"],
          our_response_draft:
            "[borrador declarado — no es hecho] Semilla de memoria técnica orientada a Lote 2.",
          response_origin: "declared_generated",
          declared_evidence_ids: ["decl-own-offer"],
          gaps: [],
        },
        {
          key: "award_thresholds",
          title: "Umbrales de puntuación 65/60",
          points_hint: "65 puntos (1 licitador) · 60 p.p. (varios)",
          requirement: "[oficial] Umbrales de puntuación del PCAP (65 / 60 puntos).",
          requirement_origin: "official",
          official_evidence_ids: ["ev-1"],
          our_response_draft:
            "[borrador declarado — no es hecho] Semilla sobre umbrales 65/60 del PCAP.",
          response_origin: "declared_generated",
          declared_evidence_ids: ["decl-own-offer"],
          gaps: [],
        },
      ],
      administrative_checklist: [
        {
          key: "deuc",
          label: "DEUC / Documento Europeo Único de Contratación",
          description: "Cumplimentar DEUC y firmar.",
          status: "pending",
          source: "pliego",
        },
        {
          key: "solvencia_f2",
          label: "Acreditación solvencia económica (F.2)",
          description: "Volumen anual ≥ 1,5× valor estimado.",
          status: "blocked",
          source: "pliego",
        },
      ],
      gaps_summary: ["Solo si puede acreditar F.2 volumen ≥1,5×"],
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

  it("muestra encaje dimensional con puerta humana y no evaluable", async () => {
    mocks.latest.mockResolvedValue({ job: null, artifact: groundedArtifact });
    const view = render(<DossierOpportunityAnalysisSection dossierId="dossier-1" />);
    const proposal = await view.findByTestId("dossier-opportunity-proposal");
    expect(within(proposal).getByTestId("dossier-opportunity-fit-assessment")).toBeInTheDocument();
    expect(within(proposal).getByTestId("dossier-opportunity-fit-verdict-rec")).toHaveTextContent(
      "GO CONDICIONADO",
    );
    expect(within(proposal).getByTestId("dossier-opportunity-fit-human-gate")).toHaveTextContent(
      "pendiente de confirmación del usuario",
    );
    expect(within(proposal).getByTestId("dossier-opportunity-fit-dim-solvency")).toHaveTextContent(
      "no evaluable con lo declarado",
    );
    expect(within(proposal).getByTestId("dossier-opportunity-fit-dim-cpv")).toHaveTextContent(
      "Requisito (oficial)",
    );
    expect(within(proposal).getByTestId("dossier-opportunity-fit-dim-cpv")).toHaveTextContent(
      "Capacidad (declarado)",
    );
    expect(within(proposal).getByTestId("dossier-opportunity-fit-conditions")).toHaveTextContent(
      "Solo si puede acreditar F.2",
    );
  });

  it("botón Preparar borrador de oferta muestra secciones, gaps y checklist", async () => {
    mocks.latest.mockResolvedValue({ job: null, artifact: groundedArtifact });
    const view = render(<DossierOpportunityAnalysisSection dossierId="dossier-1" />);
    const proposal = await view.findByTestId("dossier-opportunity-proposal");
    const btn = within(proposal).getByTestId("dossier-opportunity-prepare-draft-offer");
    expect(btn).toHaveTextContent("Preparar borrador de oferta");
    expect(within(proposal).queryByTestId("dossier-opportunity-draft-offer")).toBeNull();

    fireEvent.click(btn);
    const draft = within(proposal).getByTestId("dossier-opportunity-draft-offer");
    expect(within(draft).getByTestId("dossier-opportunity-draft-banner")).toHaveTextContent(
      "BORRADOR COMERCIAL",
    );
    expect(within(draft).getByTestId("dossier-opportunity-draft-human-gate")).toHaveTextContent(
      "requiere edición humana",
    );
    expect(within(draft).getByTestId("dossier-opportunity-draft-section-award_economic")).toHaveTextContent(
      "Oferta económica",
    );
    expect(within(draft).getByTestId("dossier-opportunity-draft-section-award_technical")).toHaveTextContent(
      "juicio de valor",
    );
    expect(within(draft).getByTestId("dossier-opportunity-draft-section-award_thresholds")).toHaveTextContent(
      "65/60",
    );
    expect(within(draft).getByTestId("dossier-opportunity-draft-gaps")).toHaveTextContent("F.2");
    expect(within(draft).getByTestId("dossier-opportunity-draft-check-deuc")).toHaveTextContent(
      "pendiente",
    );
    expect(within(draft).getByTestId("dossier-opportunity-draft-check-solvencia_f2")).toHaveTextContent(
      "bloqueado",
    );
  });
});
