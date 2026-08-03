"use client";

import {
  ApiError,
  api,
  type BackendDossier,
  type OracleDecision,
  type OracleOpportunity,
  type OracleRisk,
  type OracleTask,
} from "@oracle/api-client";
import { ArrowLeft, FileText, RefreshCw } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { DossierOracleSummaryPanel } from "@/components/dossiers/dossier-oracle-summary-panel";
import { DossierContextPanel } from "@/components/dossiers/dossier-context-panel";
import { PageHeader } from "@/components/ui/page-header";
import {
  productDossierTypeLabel,
  productResourceKindLabel,
  productStatusLabel,
} from "@/lib/product-copy";

type PanelLoadState = "idle" | "ok" | "error";

type SummaryPanelConfig = {
  title: string;
  href: string;
  emptyTitle: string;
  emptyDescription: string;
  ctaLabel: string;
};

const PANEL_COPY = {
  opportunities: {
    emptyTitle: "Aún no hay oportunidades registradas",
    emptyDescription:
      "Registra oportunidades del expediente o promueve una recomendación del Oráculo de arriba. No es un error de permisos.",
    ctaLabel: "Abrir oportunidades",
  },
  risks: {
    emptyTitle: "Aún no hay riesgos registrados",
    emptyDescription:
      "Añade riesgos del expediente o promueve una recomendación del Oráculo. El panel está vacío porque no hay filas de negocio.",
    ctaLabel: "Abrir riesgos",
  },
  tasks: {
    emptyTitle: "No hay siguientes acciones pendientes",
    emptyDescription:
      "Crea tareas en el expediente o convierte en tarea una acción recomendada por el Oráculo.",
    ctaLabel: "Abrir tareas",
  },
  decisions: {
    emptyTitle: "No hay decisiones registradas",
    emptyDescription:
      "Documenta decisiones del expediente o promueve una decisión pendiente del Oráculo.",
    ctaLabel: "Abrir decisiones",
  },
} as const;

function listErrorMessage(reason: unknown, fallback: string): string {
  return reason instanceof ApiError ? reason.problem.detail : fallback;
}

export function ProductDossier() {
  const { id } = useParams<{ id: string }>();
  const [dossier, setDossier] = useState<BackendDossier | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [opportunities, setOpportunities] = useState<OracleOpportunity[]>([]);
  const [risks, setRisks] = useState<OracleRisk[]>([]);
  const [tasks, setTasks] = useState<OracleTask[]>([]);
  const [decisions, setDecisions] = useState<OracleDecision[]>([]);
  const [opportunityState, setOpportunityState] = useState<PanelLoadState>("idle");
  const [riskState, setRiskState] = useState<PanelLoadState>("idle");
  const [taskState, setTaskState] = useState<PanelLoadState>("idle");
  const [decisionState, setDecisionState] = useState<PanelLoadState>("idle");
  const [opportunityError, setOpportunityError] = useState<string | null>(null);
  const [riskError, setRiskError] = useState<string | null>(null);
  const [taskError, setTaskError] = useState<string | null>(null);
  const [decisionError, setDecisionError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    setOpportunityState("idle");
    setRiskState("idle");
    setTaskState("idle");
    setDecisionState("idle");
    setOpportunityError(null);
    setRiskError(null);
    setTaskError(null);
    setDecisionError(null);
    try {
      const resource = await api.dossiers.get(id);
      setDossier(resource);
      const [opportunityResult, riskResult, taskResult, decisionResult] = await Promise.allSettled([
        api.opportunities.list(id, { page: 1, size: 10, sort: "-overall_score" }),
        api.risks.list(id, { page: 1, size: 10, sort: "-overall_score" }),
        api.tasks.list(id, { page: 1, size: 10, sort: "due_date" }),
        api.decisions.list(id, { page: 1, size: 10, sort: "-updated_at" }),
      ]);
      if (opportunityResult.status === "fulfilled") {
        setOpportunities(opportunityResult.value.data);
        setOpportunityState("ok");
      } else {
        setOpportunities([]);
        setOpportunityState("error");
        setOpportunityError(
          listErrorMessage(opportunityResult.reason, "No se pudieron cargar las oportunidades."),
        );
      }
      if (riskResult.status === "fulfilled") {
        setRisks(riskResult.value.data);
        setRiskState("ok");
      } else {
        setRisks([]);
        setRiskState("error");
        setRiskError(listErrorMessage(riskResult.reason, "No se pudieron cargar los riesgos."));
      }
      if (taskResult.status === "fulfilled") {
        setTasks(taskResult.value.data);
        setTaskState("ok");
      } else {
        setTasks([]);
        setTaskState("error");
        setTaskError(listErrorMessage(taskResult.reason, "No se pudieron cargar las tareas."));
      }
      if (decisionResult.status === "fulfilled") {
        setDecisions(decisionResult.value.data);
        setDecisionState("ok");
      } else {
        setDecisions([]);
        setDecisionState("error");
        setDecisionError(
          listErrorMessage(decisionResult.reason, "No se pudieron cargar las decisiones."),
        );
      }
    } catch (reason) {
      setDossier(null);
      setError(
        reason instanceof ApiError
          ? reason.problem.detail
          : "No se pudo cargar el expediente.",
      );
    } finally {
      setLoading(false);
    }
  }, [id]);
  useEffect(() => {
    const kickoff = window.setTimeout(() => void load(), 0);
    return () => window.clearTimeout(kickoff);
  }, [load]);

  if (loading) {
    return (
      <div className="dossier-loading" role="status" aria-label="Cargando expediente">
        <span />
        <span />
        <span />
      </div>
    );
  }
  if (!dossier || error) {
    return (
      <div className="not-found" role="alert">
        <strong>Expediente no disponible</strong>
        <p>{error ?? "No existe o ya no tienes acceso."}</p>
        <button className="vector-secondary" onClick={() => void load()}>
          <RefreshCw size={15} /> Reintentar
        </button>
        <Link className="vector-primary" href="/app/dossiers">
          Volver a Expedientes
        </Link>
      </div>
    );
  }
  return (
    <div className="dossier-page dossier-section-page">
      <Link className="back-link" href="/app/dossiers">
        <ArrowLeft size={15} /> Expedientes
      </Link>
      <PageHeader
        eyebrow="Resumen"
        title={dossier.title}
        description={dossier.strategic_goal || dossier.description || "Sin objetivo descrito."}
        meta={
          <>
            <span className={`status ${dossier.status === "active" ? "active" : ""}`}>
              {productStatusLabel(dossier.status)}
            </span>
            <span>{productDossierTypeLabel(dossier.dossier_type)}</span>
            <span>
              Actualizado{" "}
              {new Intl.DateTimeFormat("es-ES", {
                dateStyle: "medium",
                timeStyle: "short",
              }).format(new Date(dossier.updated_at))}
            </span>
          </>
        }
        actions={
          <Link className="vector-primary" href={`/app/dossiers/${id}/reports`}>
            <FileText size={16} /> Abrir informes
          </Link>
        }
      />
      <DossierOracleSummaryPanel dossierId={id} />
      <section className="vector-panel situation-panel">
        <header>
          <div>
            <span className="section-kicker">Resumen de situación</span>
            <h2>Situación del expediente</h2>
          </div>
        </header>
        <p className="living-summary">
          {dossier.description ||
            "El expediente todavía no tiene una descripción consolidada."}
        </p>
        <dl className="placeholder-contract">
          <div>
            <dt title="Media de oportunidades y riesgos: salud = clamp(50 + 0,5·oportunidad − 0,5·riesgo)">
              Salud
            </dt>
            <dd>
              {dossier.health_score}
              {dossier.opportunity_score === 0 &&
              dossier.risk_score === 0 &&
              dossier.health_score === 50 ? (
                <small> · neutro (sin oportunidades ni riesgos)</small>
              ) : null}
            </dd>
          </div>
          <div>
            <dt title="Media de overall_score de oportunidades del expediente (0 si no hay)">
              Oportunidad
            </dt>
            <dd>{dossier.opportunity_score}</dd>
          </div>
          <div>
            <dt title="Media de overall_score de riesgos del expediente (0 si no hay)">
              Riesgo
            </dt>
            <dd>{dossier.risk_score}</dd>
          </div>
        </dl>
        <div className="placeholder-actions">
          <Link className="vector-secondary" href={`/app/dossiers/${id}/signals`}>Señales</Link>
          <Link className="vector-secondary" href={`/app/dossiers/${id}/opportunities`}>Oportunidades</Link>
          <Link className="vector-secondary" href={`/app/dossiers/${id}/risks`}>Riesgos</Link>
          <Link className="vector-secondary" href={`/app/dossiers/${id}/documents`}>Documentos</Link>
        </div>
      </section>
      <section className="dossier-summary-grid" aria-label="Prioridades del expediente">
        <DossierContextPanel dossierId={id} />
        <SummaryList
          title="Oportunidades principales"
          href={`/app/dossiers/${id}/opportunities`}
          state={opportunityState}
          errorMessage={opportunityError}
          emptyTitle={PANEL_COPY.opportunities.emptyTitle}
          emptyDescription={PANEL_COPY.opportunities.emptyDescription}
          ctaLabel={PANEL_COPY.opportunities.ctaLabel}
          items={opportunities.slice(0, 3).map((item) => ({
            id: item.id,
            title: item.title || "Sin título",
            meta: `${productStatusLabel(item.status)} · Puntuación ${item.overall_score ?? "—"}`,
          }))}
        />
        <SummaryList
          title="Riesgos principales"
          href={`/app/dossiers/${id}/risks`}
          state={riskState}
          errorMessage={riskError}
          emptyTitle={PANEL_COPY.risks.emptyTitle}
          emptyDescription={PANEL_COPY.risks.emptyDescription}
          ctaLabel={PANEL_COPY.risks.ctaLabel}
          items={risks.slice(0, 3).map((item) => ({
            id: item.id,
            title: item.title || "Sin título",
            meta: `${productStatusLabel(item.status)} · Puntuación ${item.overall_score ?? "—"}`,
          }))}
        />
        <SummaryList
          title="Siguientes acciones"
          href={`/app/dossiers/${id}/tasks`}
          state={taskState}
          errorMessage={taskError}
          emptyTitle={PANEL_COPY.tasks.emptyTitle}
          emptyDescription={PANEL_COPY.tasks.emptyDescription}
          ctaLabel={PANEL_COPY.tasks.ctaLabel}
          items={tasks
            .filter((item) => !["done", "cancelled"].includes(item.status || ""))
            .slice(0, 3)
            .map((item) => ({
              id: item.id,
              title: item.title || "Sin título",
              meta: `${productResourceKindLabel(item.priority || "medium")} · ${item.due_date || "sin fecha"}`,
            }))}
        />
        <SummaryList
          title="Decisiones recientes"
          href={`/app/dossiers/${id}/decisions`}
          state={decisionState}
          errorMessage={decisionError}
          emptyTitle={PANEL_COPY.decisions.emptyTitle}
          emptyDescription={PANEL_COPY.decisions.emptyDescription}
          ctaLabel={PANEL_COPY.decisions.ctaLabel}
          items={decisions.slice(0, 3).map((item) => ({
            id: item.id,
            title: item.title || "Sin título",
            meta: productStatusLabel(item.status || "proposed"),
          }))}
        />
      </section>
    </div>
  );
}

export function SummaryList({
  title,
  href,
  items,
  state = "ok",
  errorMessage,
  emptyTitle = "Sin elementos todavía",
  emptyDescription = "Este panel se llena con registros del expediente, no con el análisis automático.",
  ctaLabel = "Abrir sección",
}: SummaryPanelConfig & {
  items: Array<{ id: string; title: string; meta: string }>;
  state?: PanelLoadState;
  errorMessage?: string | null;
}) {
  return (
    <article className="vector-panel dossier-summary-list">
      <header>
        <h2>{title}</h2>
        <Link href={href}>Ver todo</Link>
      </header>
      {state === "error" ? (
        <div className="dossier-summary-empty" role="alert">
          <strong>No se pudo cargar este panel</strong>
          <p>{errorMessage || "Error al consultar el servidor."}</p>
          <Link href={href}>{ctaLabel}</Link>
        </div>
      ) : items.length ? (
        <ul>
          {items.map((item) => (
            <li key={item.id}>
              <strong>{item.title}</strong>
              <span>{item.meta}</span>
            </li>
          ))}
        </ul>
      ) : (
        <div className="dossier-summary-empty">
          <strong>{emptyTitle}</strong>
          <p>{emptyDescription}</p>
          <Link href={href}>{ctaLabel}</Link>
        </div>
      )}
    </article>
  );
}
