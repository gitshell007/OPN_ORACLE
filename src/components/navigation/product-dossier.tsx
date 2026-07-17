"use client";

import { ApiError, api, type BackendDossier, type OracleDecision, type OracleOpportunity, type OracleRisk, type OracleTask } from "@oracle/api-client";
import { ArrowLeft, FileText, RefreshCw } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { DossierOracleSummaryPanel } from "@/components/dossiers/dossier-oracle-summary-panel";
import { DossierContextPanel } from "@/components/dossiers/dossier-context-panel";
import {
  productDossierTypeLabel,
  productResourceKindLabel,
  productStatusLabel,
} from "@/lib/product-copy";

export function ProductDossier() {
  const { id } = useParams<{ id: string }>();
  const [dossier, setDossier] = useState<BackendDossier | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [opportunities, setOpportunities] = useState<OracleOpportunity[]>([]);
  const [risks, setRisks] = useState<OracleRisk[]>([]);
  const [tasks, setTasks] = useState<OracleTask[]>([]);
  const [decisions, setDecisions] = useState<OracleDecision[]>([]);
  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const resource = await api.dossiers.get(id);
      setDossier(resource);
      const [opportunityResult, riskResult, taskResult, decisionResult] = await Promise.allSettled([
        api.opportunities.list(id, { page: 1, size: 10, sort: "-overall_score" }),
        api.risks.list(id, { page: 1, size: 10, sort: "-overall_score" }),
        api.tasks.list(id, { page: 1, size: 10, sort: "due_date" }),
        api.decisions.list(id, { page: 1, size: 10, sort: "-updated_at" }),
      ]);
      setOpportunities(opportunityResult.status === "fulfilled" ? opportunityResult.value.data : []);
      setRisks(riskResult.status === "fulfilled" ? riskResult.value.data : []);
      setTasks(taskResult.status === "fulfilled" ? taskResult.value.data : []);
      setDecisions(decisionResult.status === "fulfilled" ? decisionResult.value.data : []);
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
    <div className="dossier-page">
      <Link className="back-link" href="/app/dossiers">
        <ArrowLeft size={15} /> Expedientes
      </Link>
      <header className="dossier-header">
        <div>
          <div className="dossier-meta">
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
          </div>
          <h1>{dossier.title}</h1>
          <p>{dossier.strategic_goal || dossier.description || "Sin objetivo descrito."}</p>
        </div>
        <div className="dossier-actions">
          <Link className="vector-primary" href={`/app/dossiers/${id}/reports`}>
            <FileText size={16} /> Abrir informes
          </Link>
        </div>
      </header>
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
          <div><dt>Salud</dt><dd>{dossier.health_score}</dd></div>
          <div><dt>Oportunidad</dt><dd>{dossier.opportunity_score}</dd></div>
          <div><dt>Riesgo</dt><dd>{dossier.risk_score}</dd></div>
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
        <SummaryList title="Oportunidades principales" href={`/app/dossiers/${id}/opportunities`} items={opportunities.slice(0, 3).map((item) => ({ id: item.id, title: item.title || "Sin título", meta: `${productStatusLabel(item.status)} · Puntuación ${item.overall_score ?? "—"}` }))} />
        <SummaryList title="Riesgos principales" href={`/app/dossiers/${id}/risks`} items={risks.slice(0, 3).map((item) => ({ id: item.id, title: item.title || "Sin título", meta: `${productStatusLabel(item.status)} · Puntuación ${item.overall_score ?? "—"}` }))} />
        <SummaryList title="Siguientes acciones" href={`/app/dossiers/${id}/tasks`} items={tasks.filter((item) => !["done", "cancelled"].includes(item.status || "")).slice(0, 3).map((item) => ({ id: item.id, title: item.title || "Sin título", meta: `${productResourceKindLabel(item.priority || "medium")} · ${item.due_date || "sin fecha"}` }))} />
        <SummaryList title="Decisiones recientes" href={`/app/dossiers/${id}/decisions`} items={decisions.slice(0, 3).map((item) => ({ id: item.id, title: item.title || "Sin título", meta: productStatusLabel(item.status || "proposed") }))} />
      </section>
    </div>
  );
}

function SummaryList({ title, href, items }: { title: string; href: string; items: Array<{ id: string; title: string; meta: string }> }) {
  return <article className="vector-panel dossier-summary-list"><header><h2>{title}</h2><Link href={href}>Ver todo</Link></header>{items.length ? <ul>{items.map((item) => <li key={item.id}><strong>{item.title}</strong><span>{item.meta}</span></li>)}</ul> : <p>No hay elementos accesibles.</p>}</article>;
}
