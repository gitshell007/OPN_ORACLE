"use client";

import {
  ApiError,
  api,
  type JobResponse,
  type OpportunityAnalysisArtifact,
  type OpportunityAnalysisOutput,
} from "@oracle/api-client";
import {
  CheckCircle2,
  Link2,
  RefreshCw,
  Sparkles,
  Target,
  XCircle,
} from "lucide-react";
import Link from "next/link";
import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";
import { toast } from "sonner";
import { PermissionGate } from "@/components/auth/auth-boundary";
import { JobProgress } from "@/components/reporting/job-progress";
import { AsyncActionButton } from "@/components/ui/async-action-button";
import { PageHeader } from "@/components/ui/page-header";

const terminal = new Set(["succeeded", "failed", "cancelled"]);

function idempotencyKey(dossierId: string): string {
  const suffix =
    typeof crypto !== "undefined" && "randomUUID" in crypto
      ? crypto.randomUUID()
      : `${Date.now()}-${Math.random().toString(16).slice(2)}`;
  return `dossier-opportunity-${dossierId}-${suffix}`.slice(0, 200);
}

function errorMessage(reason: unknown, fallback: string) {
  return reason instanceof ApiError ? reason.problem.detail : fallback;
}

/** Solo hechos con al menos una evidencia; sin fuente no se exponen. */
function groundedFacts(output: OpportunityAnalysisOutput | null | undefined) {
  if (!output?.facts?.length) return [];
  return output.facts.filter(
    (fact) =>
      typeof fact.statement === "string" &&
      fact.statement.trim() &&
      Array.isArray(fact.evidence_ids) &&
      fact.evidence_ids.length > 0,
  );
}

/** Inferencias solo si citan evidencia (misma regla que Competidor Sintético). */
function groundedInferences(output: OpportunityAnalysisOutput | null | undefined) {
  if (!output?.inferences?.length) return [];
  return output.inferences.filter(
    (item) =>
      typeof item.statement === "string" &&
      item.statement.trim() &&
      Array.isArray(item.evidence_ids) &&
      item.evidence_ids.length > 0,
  );
}

function groundedActors(output: OpportunityAnalysisOutput | null | undefined) {
  if (!output?.candidate_actors?.length) return [];
  return output.candidate_actors.filter(
    (actor) =>
      typeof actor.name === "string" &&
      actor.name.trim() &&
      Array.isArray(actor.evidence_ids) &&
      actor.evidence_ids.length > 0,
  );
}

function recommendationLabel(value: string | undefined) {
  switch (value) {
    case "go":
      return "Avanzar (go)";
    case "investigate":
      return "Investigar";
    case "hold":
      return "Mantener en espera";
    case "no_go":
      return "No avanzar (no-go)";
    default:
      return value || "—";
  }
}

export function DossierOpportunityAnalysisSection({ dossierId }: { dossierId: string }) {
  const [artifact, setArtifact] = useState<OpportunityAnalysisArtifact | null>(null);
  const [job, setJob] = useState<JobResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [running, setRunning] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [title, setTitle] = useState("");
  const [summary, setSummary] = useState("");
  const [createdId, setCreatedId] = useState<string | null>(null);

  const output = artifact?.output ?? null;
  const facts = useMemo(() => groundedFacts(output), [output]);
  const inferences = useMemo(() => groundedInferences(output), [output]);
  const actors = useMemo(() => groundedActors(output), [output]);
  const hasGrounding = facts.length > 0;
  const canReview =
    Boolean(artifact) &&
    artifact?.status !== "valid" &&
    artifact?.status !== "rejected" &&
    !running &&
    hasGrounding;

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const latest = await api.dossierOpportunityAnalysis.latest(dossierId);
      setJob(latest.job);
      setArtifact(latest.artifact);
      const proposal = latest.artifact?.output;
      if (proposal) {
        setTitle(proposal.title || "");
        setSummary(proposal.summary || "");
      }
      const nonTerminal = latest.job && !terminal.has(latest.job.status);
      setRunning(Boolean(nonTerminal));
    } catch (reason) {
      setError(errorMessage(reason, "No se pudo cargar el análisis de oportunidad."));
    } finally {
      setLoading(false);
    }
  }, [dossierId]);

  useEffect(() => {
    const kickoff = window.setTimeout(() => void load(), 0);
    return () => window.clearTimeout(kickoff);
  }, [load]);

  async function runAnalysis() {
    setBusy(true);
    setError(null);
    setCreatedId(null);
    try {
      const response = await api.dossierOpportunityAnalysis.run(
        dossierId,
        idempotencyKey(dossierId),
      );
      setJob(response.job);
      if (response.artifact) {
        setArtifact(response.artifact);
        const proposal = response.artifact.output;
        setTitle(proposal.title || title);
        setSummary(proposal.summary || summary);
      }
      const nonTerminal = response.job && !terminal.has(response.job.status);
      setRunning(Boolean(nonTerminal));
      if (!nonTerminal && response.job?.status === "succeeded") {
        toast.success("Propuesta lista", {
          description: "Revísala y confirma antes de crear la oportunidad en el expediente.",
        });
        await load();
      } else if (nonTerminal) {
        toast.message("Análisis en curso", {
          description: "Oracle está evaluando la evidencia del expediente.",
        });
      }
    } catch (reason) {
      setError(errorMessage(reason, "No se pudo lanzar el análisis de oportunidad."));
    } finally {
      setBusy(false);
    }
  }

  async function onJobTerminal(next: JobResponse) {
    setJob(next);
    setRunning(false);
    if (next.status === "succeeded") {
      try {
        const latest = await api.dossierOpportunityAnalysis.latest(dossierId);
        setArtifact(latest.artifact);
        setJob(latest.job);
        if (latest.artifact?.output) {
          setTitle(latest.artifact.output.title || title);
          setSummary(latest.artifact.output.summary || summary);
        }
      } catch (reason) {
        setError(errorMessage(reason, "No se pudo recuperar la propuesta."));
      }
    }
  }

  async function applyProposal(event: FormEvent) {
    event.preventDefault();
    if (!artifact || !output) return;
    const nextTitle = title.trim();
    if (!nextTitle) {
      setError("El título no puede estar vacío.");
      return;
    }
    if (!hasGrounding) {
      setError("Sin hechos con evidencia citada no se puede crear la oportunidad.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const scores = output.scores;
      const nextAction =
        output.next_best_action?.action?.trim() ||
        "Validar la propuesta del análisis de oportunidad y vincular seguimiento.";
      // 1) Mutación de negocio solo por acción humana explícita.
      const created = await api.opportunities.create(dossierId, {
        title: nextTitle,
        description: summary.trim(),
        opportunity_type: output.opportunity_type || "other",
        status: "identified",
        next_action: nextAction,
        strategic_fit: scores?.strategic_fit ?? 50,
        urgency: scores?.urgency ?? 50,
        expected_value: scores?.expected_value ?? 50,
        actionability: scores?.actionability ?? 50,
        relationship_leverage: scores?.relationship_leverage ?? 50,
        timing: scores?.timing ?? 50,
        confidence: scores?.confidence ?? output.confidence ?? 50,
        execution_effort: scores?.execution_effort ?? 50,
        blocking_risk: scores?.blocking_risk ?? 50,
        due_date: output.deadline ?? null,
      });
      setCreatedId(created.id);
      // 2) Marca la revisión humana sobre el artefacto (auditoría).
      await api.dossierOpportunityAnalysis.review(artifact.id, {
        decision: "accepted",
        reason: "Propuesta de oportunidad creada en el expediente por el usuario.",
        override: {
          created_opportunity_id: created.id,
          applied_title: nextTitle,
          recommendation: output.recommendation,
          evidence_ids: facts.flatMap((fact) => fact.evidence_ids),
        },
      });
      toast.success("Oportunidad creada", {
        description: "Aparece en el panel de oportunidades de la portada del expediente.",
      });
      await load();
    } catch (reason) {
      setError(errorMessage(reason, "No se pudo crear la oportunidad."));
    } finally {
      setBusy(false);
    }
  }

  async function rejectProposal() {
    if (!artifact) return;
    setBusy(true);
    setError(null);
    try {
      await api.dossierOpportunityAnalysis.review(artifact.id, {
        decision: "rejected",
        reason: "Propuesta de oportunidad descartada por el usuario.",
      });
      toast.message("Propuesta descartada", {
        description: "No se ha creado ninguna oportunidad.",
      });
      await load();
    } catch (reason) {
      setError(errorMessage(reason, "No se pudo descartar la propuesta."));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div
      className="dossier-page dossier-section-page"
      data-testid="dossier-opportunity-analysis-section"
    >
      <PageHeader
        eyebrow="Análisis"
        title="Análisis de oportunidad"
        description="Oracle propone una oportunidad a partir de la evidencia del expediente. Tú confirmas: sin tu acción no se crea ninguna fila de negocio. La propuesta solo se muestra si cita evidencia."
        actions={
          <div className="page-header-actions">
            <Link className="vector-secondary" href={`/app/dossiers/${dossierId}/opportunities`}>
              Oportunidades
            </Link>
            <PermissionGate permission="ai.execute">
              <AsyncActionButton
                className="vector-primary"
                loading={busy || running}
                disabled={running}
                onClick={() => void runAnalysis()}
                data-testid="dossier-opportunity-run"
              >
                <Sparkles size={15} aria-hidden="true" />
                {artifact ? "Regenerar propuesta" : "Analizar oportunidad"}
              </AsyncActionButton>
            </PermissionGate>
            <AsyncActionButton
              className="vector-secondary"
              loading={loading}
              onClick={() => void load()}
              data-testid="dossier-opportunity-refresh"
            >
              <RefreshCw size={15} aria-hidden="true" />
              Actualizar
            </AsyncActionButton>
          </div>
        }
      />

      {error ? (
        <p className="form-error" role="alert" data-testid="dossier-opportunity-error">
          {error}
        </p>
      ) : null}

      {createdId ? (
        <p role="status" data-testid="dossier-opportunity-created">
          Oportunidad creada:{" "}
          <Link href={`/app/dossiers/${dossierId}`}>{createdId}</Link> · visible en el panel de
          la portada.
        </p>
      ) : null}

      {job && running ? (
        <JobProgress
          jobId={job.id}
          label="Analizando oportunidad con evidencia del expediente"
          onTerminal={(next) => void onJobTerminal(next)}
        />
      ) : null}

      {loading && !artifact ? (
        <p role="status">Cargando…</p>
      ) : !artifact ? (
        <section className="vector-panel" data-testid="dossier-opportunity-empty">
          <header className="panel-heading">
            <Target size={18} aria-hidden="true" />
            <div>
              <h2>Sin propuesta todavía</h2>
              <p>
                Lanza el análisis cuando haya documentos o evidencias en el expediente. La
                ejecución quedará en la auditoría de IA. Confirmar creará la oportunidad en el
                panel de la portada.
              </p>
            </div>
          </header>
        </section>
      ) : (
        <div className="dossier-summary-grid" data-testid="dossier-opportunity-proposal">
          <section className="vector-panel">
            <header className="panel-heading">
              <Sparkles size={18} aria-hidden="true" />
              <div>
                <span className="section-kicker">Propuesta del agente</span>
                <h2>Revisión humana obligatoria</h2>
                <p>
                  Estado del artefacto: <strong>{artifact.status}</strong>
                  {artifact.audit_log_id ? (
                    <>
                      {" "}
                      ·{" "}
                      <Link href="/app/admin/ai-audit" data-testid="dossier-opportunity-audit-link">
                        Ver en auditoría de IA
                      </Link>
                    </>
                  ) : null}
                </p>
              </div>
            </header>

            <dl className="detail-grid" data-testid="dossier-opportunity-meta">
              <div>
                <dt>Recomendación</dt>
                <dd data-testid="dossier-opportunity-recommendation">
                  {recommendationLabel(String(output?.recommendation ?? ""))}
                </dd>
              </div>
              <div>
                <dt>Tipo</dt>
                <dd>{output?.opportunity_type || "—"}</dd>
              </div>
              <div>
                <dt>Score global</dt>
                <dd>{output?.scores?.overall ?? "—"}</dd>
              </div>
              <div>
                <dt>Hechos con fuente</dt>
                <dd>{facts.length}</dd>
              </div>
            </dl>

            {!hasGrounding ? (
              <p className="form-error" role="status" data-testid="dossier-opportunity-no-grounding">
                La propuesta no cita hechos con evidencia. No se puede crear la oportunidad (misma
                regla que el Competidor Sintético).
              </p>
            ) : null}

            {Array.isArray(output?.warnings) && output.warnings.length > 0 ? (
              <ul className="warning-list" data-testid="dossier-opportunity-warnings">
                {output.warnings.map((item) => (
                  <li key={item}>{item}</li>
                ))}
              </ul>
            ) : null}

            <PermissionGate permission="opportunity.write">
              <form
                className="dossier-settings-form"
                onSubmit={(event) => void applyProposal(event)}
                data-testid="dossier-opportunity-apply-form"
              >
                <label>
                  Título de la oportunidad
                  <input
                    value={title}
                    onChange={(event) => setTitle(event.target.value)}
                    maxLength={300}
                    required
                    data-testid="dossier-opportunity-title"
                  />
                </label>
                <label>
                  Resumen / descripción
                  <textarea
                    value={summary}
                    onChange={(event) => setSummary(event.target.value)}
                    rows={5}
                    maxLength={10000}
                    data-testid="dossier-opportunity-summary"
                  />
                </label>
                <div className="form-actions">
                  <AsyncActionButton
                    type="submit"
                    className="vector-primary"
                    loading={busy}
                    disabled={!canReview}
                    data-testid="dossier-opportunity-apply"
                  >
                    <CheckCircle2 size={15} aria-hidden="true" />
                    Confirmar y crear oportunidad
                  </AsyncActionButton>
                  <PermissionGate permission="ai.review">
                    <AsyncActionButton
                      type="button"
                      className="vector-secondary"
                      loading={busy}
                      disabled={
                        !artifact ||
                        artifact.status === "valid" ||
                        artifact.status === "rejected" ||
                        running
                      }
                      onClick={() => void rejectProposal()}
                      data-testid="dossier-opportunity-reject"
                    >
                      <XCircle size={15} aria-hidden="true" />
                      Descartar propuesta
                    </AsyncActionButton>
                  </PermissionGate>
                </div>
                <p className="muted">
                  Confirmar crea una oportunidad en el expediente (panel de la portada) y registra
                  la revisión humana. Descartar no crea filas de negocio.
                </p>
              </form>
            </PermissionGate>
          </section>

          <section className="vector-panel">
            <header className="panel-heading">
              <Link2 size={18} aria-hidden="true" />
              <div>
                <span className="section-kicker">Evidencias</span>
                <h2>Hechos e inferencias con fuente</h2>
                <p>
                  Sin evidencia citada no se muestra el hallazgo (misma regla que el Competidor
                  Sintético).
                </p>
              </div>
            </header>

            <h3>Hechos (fuente oficial / externa)</h3>
            {facts.length === 0 ? (
              <p data-testid="dossier-opportunity-no-facts">No hay hechos con evidencia citada.</p>
            ) : (
              <ul data-testid="dossier-opportunity-facts">
                {facts.map((fact) => (
                  <li key={`${fact.statement}-${fact.evidence_ids.join(",")}`}>
                    <p>{fact.statement}</p>
                    <small className="muted">
                      Evidencias oficiales: {fact.evidence_ids.length} ·{" "}
                      {fact.evidence_ids.slice(0, 3).join(", ")}
                      {fact.evidence_ids.length > 3 ? "…" : ""}
                    </small>
                  </li>
                ))}
              </ul>
            )}

            {output?.fit_assessment?.statement ? (
              <>
                <h3>Encaje con oferta declarada</h3>
                <div
                  className="opportunity-fit-assessment"
                  data-testid="dossier-opportunity-fit-assessment"
                >
                  <p data-testid="dossier-opportunity-fit-statement">
                    {output.fit_assessment.statement}
                  </p>
                  <small className="muted" data-testid="dossier-opportunity-fit-origin">
                    Origen:{" "}
                    {output.fit_assessment.origin === "declared_by_client" ||
                    !output.fit_assessment.origin
                      ? "Declarado por el cliente (perfil del expediente)"
                      : String(output.fit_assessment.origin)}
                    {" · "}
                    IDs declarados:{" "}
                    {(output.fit_assessment.declared_evidence_ids || []).length}
                    {(output.fit_assessment.official_evidence_ids || []).length > 0
                      ? ` · IDs oficiales enlazados: ${
                          output.fit_assessment.official_evidence_ids?.length ?? 0
                        }`
                      : ""}
                    {" · "}
                    Confianza {output.fit_assessment.confidence ?? "—"}%
                  </small>
                </div>
              </>
            ) : null}

            <h3>Inferencias con fuente</h3>
            {inferences.length === 0 ? (
              <p data-testid="dossier-opportunity-no-inferences">
                No hay inferencias con evidencia citada.
              </p>
            ) : (
              <ul data-testid="dossier-opportunity-inferences">
                {inferences.map((item) => (
                  <li key={`${item.statement}-${item.confidence}`}>
                    <p>{item.statement}</p>
                    <small className="muted">
                      Confianza {item.confidence}% · {item.reasoning_summary}
                    </small>
                  </li>
                ))}
              </ul>
            )}

            {actors.length > 0 ? (
              <>
                <h3>Actores candidatos con fuente</h3>
                <ul data-testid="dossier-opportunity-actors">
                  {actors.map((actor) => (
                    <li key={`${actor.name}-${actor.role}`}>
                      <strong>{actor.name}</strong>
                      <span className="muted"> · {actor.role}</span>
                    </li>
                  ))}
                </ul>
              </>
            ) : null}

            {output?.next_best_action?.action ? (
              <>
                <h3>Siguiente mejor acción</h3>
                <p data-testid="dossier-opportunity-nba">
                  <strong>{output.next_best_action.action}</strong>
                  <span className="muted"> · {output.next_best_action.owner_role}</span>
                </p>
                <p className="muted">{output.next_best_action.rationale}</p>
              </>
            ) : null}

            {Array.isArray(output?.open_questions) && output.open_questions.length > 0 ? (
              <>
                <h3>Preguntas abiertas</h3>
                <ul data-testid="dossier-opportunity-questions">
                  {output.open_questions.map((question) => (
                    <li key={question}>{question}</li>
                  ))}
                </ul>
              </>
            ) : null}
          </section>
        </div>
      )}
    </div>
  );
}
