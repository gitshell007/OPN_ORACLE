import { cleanup, fireEvent, render, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  latest: vi.fn(),
  run: vi.fn(),
  review: vi.fn(),
  create: vi.fn(),
  getOfferDraft: vi.fn(),
  prepareOfferDraft: vi.fn(),
  patchOfferDraft: vi.fn(),
  exportOfferDraftDocx: vi.fn(),
  toast: { success: vi.fn(), message: vi.fn(), error: vi.fn() },
}));

vi.mock("@oracle/api-client", () => ({
  ApiError: class ApiError extends Error {
    status: number;
    problem: { detail: string; code?: string };
    constructor(statusOrDetail: number | string, problem?: { detail: string; code?: string }) {
      if (typeof statusOrDetail === "string") {
        super(statusOrDetail);
        this.status = 400;
        this.problem = { detail: statusOrDetail };
      } else {
        super(problem?.detail || "error");
        this.status = statusOrDetail;
        this.problem = problem || { detail: "error" };
      }
    }
  },
  api: {
    dossierOpportunityAnalysis: {
      latest: mocks.latest,
      run: mocks.run,
      review: mocks.review,
      getOfferDraft: mocks.getOfferDraft,
      prepareOfferDraft: mocks.prepareOfferDraft,
      patchOfferDraft: mocks.patchOfferDraft,
      exportOfferDraftDocx: mocks.exportOfferDraftDocx,
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
        "Encaje perfil declarado ↔ CONTR 2026 11077: propuesta **GO CONDICIONADO** (puerta humana).",
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
            "[borrador declarado — **no** es hecho] Semilla de oferta económica para Lote 2.",
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

const persistedDraftFixture = {
  id: "draft-1",
  dossier_id: "dossier-1",
  source_artifact_id: "art-opp-1",
  version: 1,
  etag: 'W/"ood-v1"',
  created_at: "2026-08-06T12:00:00+00:00",
  updated_at: "2026-08-06T12:00:00+00:00",
  last_edited_by_user_id: "user-1",
  banner:
    "BORRADOR COMERCIAL — no es documento presentable. Requiere edición humana antes de cualquier presentación o envío.",
  human_gate: "draft_requires_human_edit",
  statement:
    "Borrador de oferta (esqueleto) para CONTR 2026 11077 · Lote 2: Red de agentes inteligentes.",
  tender_ref: "CONTR 2026 11077",
  lot_hint: "Lote 2: Red de agentes inteligentes",
  origin: "declared_draft" as const,
  based_on_verdict: "go_conditioned",
  sections: groundedArtifact.output.draft_offer!.sections!,
  administrative_checklist: groundedArtifact.output.draft_offer!.administrative_checklist!,
  gaps_summary: groundedArtifact.output.draft_offer!.gaps_summary!,
};

describe("DossierOpportunityAnalysisSection", () => {
  afterEach(() => {
    cleanup();
  });

  beforeEach(async () => {
    vi.clearAllMocks();
    mocks.latest.mockResolvedValue({ job: null, artifact: null });
    mocks.run.mockResolvedValue({
      job: { id: "job-1", status: "succeeded" },
      artifact: groundedArtifact,
    });
    mocks.create.mockResolvedValue({ id: "opp-created-1", title: groundedArtifact.output.title });
    mocks.review.mockResolvedValue({ review_id: "rev-1", artifact_status: "valid" });
    const { ApiError } = await import("@oracle/api-client");
    mocks.getOfferDraft.mockRejectedValue(
      new ApiError(404, { detail: "No hay borrador", code: "offer_draft_not_found" } as never),
    );
    mocks.prepareOfferDraft.mockResolvedValue({
      created: true,
      draft: persistedDraftFixture,
    });
    mocks.patchOfferDraft.mockImplementation(async (_id: string, input: { statement?: string; sections?: Array<{ key: string; our_response_draft: string }>; version?: number }) => ({
      draft: {
        ...persistedDraftFixture,
        version: (input.version || 1) + 1,
        etag: `W/"ood-v${(input.version || 1) + 1}"`,
        statement: input.statement ?? persistedDraftFixture.statement,
        sections: (persistedDraftFixture.sections || []).map((sec) => {
          const patch = (input.sections || []).find((s) => s.key === sec.key);
          return patch ? { ...sec, our_response_draft: patch.our_response_draft } : sec;
        }),
      },
    }));
    mocks.exportOfferDraftDocx.mockResolvedValue({
      blob: new Blob(["PK-fake-docx"], {
        type: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
      }),
      filename: "Borrador-oferta-demo-v1.docx",
      contentType:
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
      etag: 'W/"ood-v1"',
    });
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
    // SV2-RIESGO-DECL micro-fix: markdown **…** se renderiza, no se muestra crudo.
    const statement = within(proposal).getByTestId("dossier-opportunity-fit-statement");
    expect(statement).toHaveTextContent("GO CONDICIONADO");
    expect(statement.textContent || "").not.toMatch(/\*\*GO CONDICIONADO\*\*/);
    expect(statement.querySelector("strong")?.textContent).toBe("GO CONDICIONADO");
  });

  it("botón Preparar borrador materializa, edita y guarda secciones", async () => {
    mocks.latest.mockResolvedValue({ job: null, artifact: groundedArtifact });
    const view = render(<DossierOpportunityAnalysisSection dossierId="dossier-1" />);
    const proposal = await view.findByTestId("dossier-opportunity-proposal");
    const btn = within(proposal).getByTestId("dossier-opportunity-prepare-draft-offer");
    expect(btn).toHaveTextContent("Preparar borrador de oferta");
    expect(within(proposal).queryByTestId("dossier-opportunity-draft-offer")).toBeNull();

    fireEvent.click(btn);
    await waitFor(() => expect(mocks.prepareOfferDraft).toHaveBeenCalledWith("dossier-1"));
    const draft = await within(proposal).findByTestId("dossier-opportunity-draft-offer");
    expect(within(draft).getByTestId("dossier-opportunity-draft-banner")).toHaveTextContent(
      "BORRADOR COMERCIAL",
    );
    expect(within(draft).getByTestId("dossier-opportunity-draft-human-gate")).toHaveTextContent(
      "requiere edición humana",
    );
    expect(within(draft).getByTestId("dossier-opportunity-draft-section-award_economic")).toHaveTextContent(
      "Oferta económica",
    );
    const seed = within(draft).getByTestId(
      "dossier-opportunity-draft-section-seed-award_economic",
    ) as HTMLTextAreaElement;
    expect(seed.value).toMatch(/borrador declarado/);
    expect(seed.value).toMatch(/hecho/);
    expect(within(draft).getByTestId("dossier-opportunity-draft-section-award_technical")).toHaveTextContent(
      "juicio de valor",
    );
    expect(within(draft).getByTestId("dossier-opportunity-draft-gaps")).toHaveTextContent("F.2");
    expect(within(draft).getByTestId("dossier-opportunity-draft-check-deuc")).toHaveTextContent(
      "pendiente",
    );

    fireEvent.change(within(draft).getByTestId("dossier-opportunity-draft-statement"), {
      target: { value: "Introducción comercial revisada." },
    });
    fireEvent.change(seed, {
      target: { value: "[borrador declarado — no es hecho] Económica revisada." },
    });
    const tech = within(draft).getByTestId(
      "dossier-opportunity-draft-section-seed-award_technical",
    ) as HTMLTextAreaElement;
    fireEvent.change(tech, {
      target: { value: "[borrador declarado — no es hecho] Técnica revisada." },
    });
    fireEvent.click(within(proposal).getByTestId("dossier-opportunity-save-draft-offer"));
    await waitFor(() =>
      expect(mocks.patchOfferDraft).toHaveBeenCalledWith(
        "dossier-1",
        expect.objectContaining({
          statement: "Introducción comercial revisada.",
          sections: expect.arrayContaining([
            expect.objectContaining({
              key: "award_economic",
              our_response_draft: "[borrador declarado — no es hecho] Económica revisada.",
            }),
            expect.objectContaining({
              key: "award_technical",
              our_response_draft: "[borrador declarado — no es hecho] Técnica revisada.",
            }),
          ]),
        }),
        1,
      ),
    );
  });

  it("persiste el borrador tras remount y reaparecen las ediciones", async () => {
    mocks.latest.mockResolvedValue({ job: null, artifact: groundedArtifact });
    const { ApiError } = await import("@oracle/api-client");
    mocks.getOfferDraft.mockRejectedValueOnce(
      new ApiError(404, { detail: "missing", code: "offer_draft_not_found" } as never),
    );
    const first = render(<DossierOpportunityAnalysisSection dossierId="dossier-1" />);
    await first.findByTestId("dossier-opportunity-proposal");
    fireEvent.click(first.getByTestId("dossier-opportunity-prepare-draft-offer"));
    await waitFor(() => expect(mocks.prepareOfferDraft).toHaveBeenCalled());
    fireEvent.change(first.getByTestId("dossier-opportunity-draft-statement"), {
      target: { value: "Texto persistente tras reload." },
    });
    fireEvent.click(first.getByTestId("dossier-opportunity-save-draft-offer"));
    await waitFor(() => expect(mocks.patchOfferDraft).toHaveBeenCalled());
    first.unmount();

    mocks.getOfferDraft.mockResolvedValue({
      draft: {
        ...persistedDraftFixture,
        version: 2,
        etag: 'W/"ood-v2"',
        statement: "Texto persistente tras reload.",
      },
    });
    const second = render(<DossierOpportunityAnalysisSection dossierId="dossier-1" />);
    await second.findByTestId("dossier-opportunity-proposal");
    const statement = await second.findByTestId("dossier-opportunity-draft-statement");
    expect((statement as HTMLTextAreaElement).value).toBe("Texto persistente tras reload.");
  });

  it("copia borrador legible y reporta error de clipboard", async () => {
    mocks.latest.mockResolvedValue({ job: null, artifact: groundedArtifact });
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.assign(navigator, { clipboard: { writeText } });
    const view = render(<DossierOpportunityAnalysisSection dossierId="dossier-1" />);
    await view.findByTestId("dossier-opportunity-proposal");
    fireEvent.click(view.getByTestId("dossier-opportunity-prepare-draft-offer"));
    await view.findByTestId("dossier-opportunity-draft-offer");
    fireEvent.click(view.getByTestId("dossier-opportunity-copy-draft-offer"));
    await waitFor(() => expect(writeText).toHaveBeenCalled());
    const copied = String(writeText.mock.calls[0][0]);
    expect(copied).toMatch(/Secciones/);
    expect(copied).toMatch(/Oferta económica/);
    expect(copied).not.toMatch(/art-opp-1/);
    expect(copied).not.toMatch(/\{[\s\S]*"key"/);
    expect(mocks.toast.success).toHaveBeenCalled();

    writeText.mockRejectedValueOnce(new Error("denied"));
    fireEvent.click(view.getByTestId("dossier-opportunity-copy-draft-offer"));
    await waitFor(() => expect(mocks.toast.error).toHaveBeenCalled());
    expect(view.getByTestId("dossier-opportunity-draft-save-status")).toHaveTextContent(
      "Error al copiar",
    );
  });

  it("muestra conflicto de versión de forma accesible", async () => {
    mocks.latest.mockResolvedValue({ job: null, artifact: groundedArtifact });
    const { ApiError } = await import("@oracle/api-client");
    mocks.patchOfferDraft.mockRejectedValueOnce(
      new ApiError(409, {
        detail: "El borrador ha cambiado; recarga y vuelve a guardar.",
        code: "version_conflict",
      } as never),
    );
    const view = render(<DossierOpportunityAnalysisSection dossierId="dossier-1" />);
    await view.findByTestId("dossier-opportunity-proposal");
    fireEvent.click(view.getByTestId("dossier-opportunity-prepare-draft-offer"));
    await view.findByTestId("dossier-opportunity-draft-offer");
    fireEvent.change(view.getByTestId("dossier-opportunity-draft-statement"), {
      target: { value: "Cambio concurrente." },
    });
    fireEvent.click(view.getByTestId("dossier-opportunity-save-draft-offer"));
    const alert = await view.findByTestId("dossier-opportunity-draft-error");
    expect(alert).toHaveAttribute("role", "alert");
    expect(alert).toHaveTextContent("cambiado");
    expect(view.getByTestId("dossier-opportunity-draft-save-status")).toHaveTextContent(
      "Conflicto de versión",
    );
  });

  it("abre borrador durable sin artifact actual", async () => {
    mocks.latest.mockResolvedValue({ job: null, artifact: null });
    mocks.getOfferDraft.mockResolvedValue({
      draft: {
        ...persistedDraftFixture,
        statement: "Borrador sin análisis actual.",
      },
    });
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.assign(navigator, { clipboard: { writeText } });
    const view = render(<DossierOpportunityAnalysisSection dossierId="dossier-1" />);
    expect(await view.findByTestId("dossier-opportunity-empty")).toBeInTheDocument();
    const surface = await view.findByTestId("dossier-opportunity-draft-durable-surface");
    expect(surface).toBeInTheDocument();
    const statement = await view.findByTestId("dossier-opportunity-draft-statement");
    expect((statement as HTMLTextAreaElement).value).toBe("Borrador sin análisis actual.");
    fireEvent.change(statement, { target: { value: "Edición sin artifact." } });
    expect(view.getByTestId("dossier-opportunity-draft-save-status")).toHaveTextContent(
      "Sin guardar",
    );
    fireEvent.click(view.getByTestId("dossier-opportunity-copy-draft-offer"));
    await waitFor(() => expect(writeText).toHaveBeenCalled());
    expect(String(writeText.mock.calls[0][0])).toMatch(/Edición sin artifact/);
  });

  it("abre borrador durable cuando el artifact no tiene fit_assessment", async () => {
    const noFit = {
      ...groundedArtifact,
      output: {
        ...groundedArtifact.output,
        fit_assessment: undefined,
        draft_offer: undefined,
      },
    };
    mocks.latest.mockResolvedValue({ job: null, artifact: noFit });
    mocks.getOfferDraft.mockResolvedValue({
      draft: {
        ...persistedDraftFixture,
        statement: "Durable sin fit.",
      },
    });
    const view = render(<DossierOpportunityAnalysisSection dossierId="dossier-1" />);
    await view.findByTestId("dossier-opportunity-proposal");
    expect(view.queryByTestId("dossier-opportunity-fit-assessment")).toBeNull();
    const statement = await view.findByTestId("dossier-opportunity-draft-statement");
    expect((statement as HTMLTextAreaElement).value).toBe("Durable sin fit.");
    expect(view.getByTestId("dossier-opportunity-draft-durable-surface")).toBeInTheDocument();
  });

  it("abre borrador durable cuando hay fit sin verdict", async () => {
    const fitNoVerdict = {
      ...groundedArtifact,
      output: {
        ...groundedArtifact.output,
        fit_assessment: {
          statement: "Hay fit pero sin veredicto.",
          declared_evidence_ids: [],
          confidence: 40,
          origin: "declared_by_client",
        },
        draft_offer: undefined,
      },
    };
    mocks.latest.mockResolvedValue({ job: null, artifact: fitNoVerdict });
    mocks.getOfferDraft.mockResolvedValue({
      draft: {
        ...persistedDraftFixture,
        statement: "Durable sin verdict.",
      },
    });
    const view = render(<DossierOpportunityAnalysisSection dossierId="dossier-1" />);
    await view.findByTestId("dossier-opportunity-fit-assessment");
    expect(view.queryByTestId("dossier-opportunity-fit-verdict")).toBeNull();
    const statement = await view.findByTestId("dossier-opportunity-draft-statement");
    expect((statement as HTMLTextAreaElement).value).toBe("Durable sin verdict.");
  });

  it("no resetea ediciones locales dirty en refresh/rerun automático", async () => {
    mocks.latest.mockResolvedValue({ job: null, artifact: groundedArtifact });
    mocks.getOfferDraft.mockResolvedValue({ draft: persistedDraftFixture });
    const view = render(<DossierOpportunityAnalysisSection dossierId="dossier-1" />);
    const statement = await view.findByTestId("dossier-opportunity-draft-statement");
    expect((statement as HTMLTextAreaElement).value).toBe(persistedDraftFixture.statement);

    fireEvent.change(statement, {
      target: { value: "Edición local sucia que no debe perderse." },
    });
    expect(view.getByTestId("dossier-opportunity-draft-save-status")).toHaveTextContent(
      "Sin guardar",
    );

    // Server would return a different statement on refresh; dirty state must win.
    mocks.getOfferDraft.mockResolvedValue({
      draft: {
        ...persistedDraftFixture,
        version: 9,
        statement: "Texto del servidor que no debe reaplicarse.",
      },
    });
    mocks.latest.mockResolvedValue({
      job: null,
      artifact: {
        ...groundedArtifact,
        output: {
          ...groundedArtifact.output,
          title: "Propuesta regenerada",
        },
      },
    });

    fireEvent.click(view.getByTestId("dossier-opportunity-refresh"));
    await waitFor(() => expect(mocks.latest).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(mocks.getOfferDraft).toHaveBeenCalledTimes(2));

    const after = view.getByTestId("dossier-opportunity-draft-statement") as HTMLTextAreaElement;
    expect(after.value).toBe("Edición local sucia que no debe perderse.");
    expect(view.getByTestId("dossier-opportunity-draft-save-status")).toHaveTextContent(
      "Sin guardar",
    );
    expect(after.value).not.toBe("Texto del servidor que no debe reaplicarse.");
  });

  it("descarga Word con blob, nombre y revoke; disponible sin artifact", async () => {
    mocks.latest.mockResolvedValue({ job: null, artifact: null });
    mocks.getOfferDraft.mockResolvedValue({ draft: persistedDraftFixture });
    const createObjectURL = vi.fn(() => "blob:mock-docx-url");
    const revokeObjectURL = vi.fn();
    Object.defineProperty(URL, "createObjectURL", { writable: true, value: createObjectURL });
    Object.defineProperty(URL, "revokeObjectURL", { writable: true, value: revokeObjectURL });
    const click = vi.fn();
    const originalCreate = document.createElement.bind(document);
    vi.spyOn(document, "createElement").mockImplementation((tag: string) => {
      const el = originalCreate(tag);
      if (tag === "a") {
        Object.defineProperty(el, "click", { value: click });
      }
      return el;
    });

    const view = render(<DossierOpportunityAnalysisSection dossierId="dossier-1" />);
    expect(await view.findByTestId("dossier-opportunity-empty")).toBeInTheDocument();
    const downloadBtn = await view.findByTestId("dossier-opportunity-download-draft-docx");
    expect(downloadBtn).toBeEnabled();
    fireEvent.click(downloadBtn);
    await waitFor(() =>
      expect(mocks.exportOfferDraftDocx).toHaveBeenCalledWith("dossier-1", 1, {
        ifMatch: 1,
      }),
    );
    await waitFor(() => expect(createObjectURL).toHaveBeenCalled());
    expect(click).toHaveBeenCalled();
    expect(view.getByTestId("dossier-opportunity-draft-save-status")).toHaveTextContent(
      "descargado",
    );
  });

  it("bloquea descarga si hay cambios dirty sin guardar", async () => {
    mocks.latest.mockResolvedValue({ job: null, artifact: groundedArtifact });
    mocks.getOfferDraft.mockResolvedValue({ draft: persistedDraftFixture });
    const view = render(<DossierOpportunityAnalysisSection dossierId="dossier-1" />);
    const statement = await view.findByTestId("dossier-opportunity-draft-statement");
    fireEvent.change(statement, { target: { value: "Cambio local sin guardar." } });
    fireEvent.click(view.getByTestId("dossier-opportunity-download-draft-docx"));
    await waitFor(() =>
      expect(view.getByTestId("dossier-opportunity-draft-export-error")).toHaveTextContent(
        /guarda antes de exportar/i,
      ),
    );
    expect(mocks.exportOfferDraftDocx).not.toHaveBeenCalled();
    expect(view.getByTestId("dossier-opportunity-draft-save-status")).toHaveTextContent(
      "guarda antes de exportar",
    );
  });

  it("muestra conflicto de versión en la descarga Word", async () => {
    mocks.latest.mockResolvedValue({ job: null, artifact: groundedArtifact });
    mocks.getOfferDraft.mockResolvedValue({ draft: persistedDraftFixture });
    const { ApiError } = await import("@oracle/api-client");
    mocks.exportOfferDraftDocx.mockRejectedValueOnce(
      new ApiError(409, {
        detail: "El borrador ha cambiado; recarga y vuelve a guardar.",
        code: "version_conflict",
      } as never),
    );
    const view = render(<DossierOpportunityAnalysisSection dossierId="dossier-1" />);
    await view.findByTestId("dossier-opportunity-draft-offer");
    fireEvent.click(view.getByTestId("dossier-opportunity-download-draft-docx"));
    const alert = await view.findByTestId("dossier-opportunity-draft-export-error");
    expect(alert).toHaveAttribute("role", "alert");
    expect(alert).toHaveTextContent(/conflicto|cambiado/i);
    expect(view.getByTestId("dossier-opportunity-draft-save-status")).toHaveTextContent(
      "conflicto",
    );
  });
});
