"use client";

import {
  ApiError,
  api,
  type JobResponse,
  type RiskAnalysisArtifact,
  type RiskAnalysisOutput,
} from "@oracle/api-client";
import {
  CheckCircle2,
  Link2,
  RefreshCw,
  ShieldAlert,
  Sparkles,
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
  return `dossier-risk-${dossierId}-${suffix}`.slice(0, 200);
}

function errorMessage(reason: unknown, fallback: string) {
  return reason instanceof ApiError ? reason.problem.detail : fallback;
}

function groundedFacts(output: RiskAnalysisOutput | null | undefined) {
  if (!output?.facts?.length) return [];
  return output.facts.filter(
    (fact) =>
      typeof fact.statement === "string" &&
      fact.statement.trim() &&
      Array.isArray(fact.evidence_ids) &&
      fact.evidence_ids.length > 0,
  );
}

function groundedInferences(output: RiskAnalysisOutput | null | undefined) {
  if (!output?.inferences?.length) return [];
  return output.inferences.filter(
    (item) =>
      typeof item.statement === "string" &&
      item.statement.trim() &&
      Array.isArray(item.evidence_ids) &&
      item.evidence_ids.length > 0,
  );
}

function groundedScenarios(output: RiskAnalysisOutput | null | undefined) {
  if (!output?.scenarios?.length) return [];
  return output.scenarios.filter(
    (scenario) =>
      typeof scenario.name === "string" &&
      scenario.name.trim() &&
      Array.isArray(scenario.evidence_ids) &&
      scenario.evidence_ids.length > 0,
  );
}

function statusLabel(value: string | undefined) {
  switch (value) {
    case "watch":
      return "Vigilar";
    case "mitigate":
      return "Mitigar";
    case "accept_candidate":
      return "Aceptar candidato";
    case "dismiss_candidate":
      return "Descartar candidato";
    default:
      return value || "—";
  }
}

export function DossierRiskAnalysisSection({ dossierId }: { dossierId: string }) {
  const [artifact, setArtifact] = useState<RiskAnalysisArtifact | null>(null);
  const [job, setJob] = useState<JobResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [running, setRunning] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [createdId, setCreatedId] = useState<string | null>(null);

  const output = artifact?.output ?? null;
  const facts = useMemo(() => groundedFacts(output), [output]);
  const inferences = useMemo(() => groundedInferences(output), [output]);
  const scenarios = useMemo(() => groundedScenarios(output), [output]);
  const hasGrounding = facts.length > 0 || scenarios.length > 0;
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
      const latest = await api.dossierRiskAnalysis.latest(dossierId);
      setJob(latest.job);
      setArtifact(latest.artifact);
      const proposal = latest.artifact?.output;
      if (proposal) {
        setTitle(proposal.title || "");
        setDescription(proposal.description || "");
      }
      const nonTerminal = latest.job && !terminal.has(latest.job.status);
      setRunning(Boolean(nonTerminal));
    } catch (reason) {
      setError(errorMessage(reason, "No se pudo cargar el análisis de riesgo."));
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
      const response = await api.dossierRiskAnalysis.run(
        dossierId,
        idempotencyKey(dossierId),
      );
      setJob(response.job);
      if (response.artifact) {
        setArtifact(response.artifact);
        const proposal = response.artifact.output;
        setTitle(proposal.title || title);
        setDescription(proposal.description || description);
      }
      const nonTerminal = response.job && !terminal.has(response.job.status);
      setRunning(Boolean(nonTerminal));
      if (!nonTerminal && response.job?.status === "succeeded") {
        toast.success("Propuesta lista", {
          description: "Revísala y confirma antes de crear el riesgo en el expediente.",
        });
        await load();
      } else if (nonTerminal) {
        toast.message("Análisis en curso", {
          description: "Oracle está evaluando la evidencia del expediente.",
        });
      }
    } catch (reason) {
      setError(errorMessage(reason, "No se pudo lanzar el análisis de riesgo."));
    } finally {
      setBusy(false);
    }
  }

  async function onJobTerminal(next: JobResponse) {
    setJob(next);
    setRunning(false);
    if (next.status === "succeeded") {
      try {
        const latest = await api.dossierRiskAnalysis.latest(dossierId);
        setArtifact(latest.artifact);
        setJob(latest.job);
        if (latest.artifact?.output) {
          setTitle(latest.artifact.output.title || title);
          setDescription(latest.artifact.output.description || description);
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
      setError("Sin hechos o escenarios con evidencia citada no se puede crear el riesgo.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const scores = output.scores;
      const mitigation =
        output.mitigations?.[0]?.action?.trim() ||
        "Validar la propuesta del análisis de riesgo y definir mitigación.";
      const created = await api.risks.create(dossierId, {
        title: nextTitle,
        description: description.trim(),
        category: output.category || "other",
        status: "open",
        mitigation,
        impact: scores?.impact ?? 50,
        likelihood: scores?.likelihood ?? 50,
        velocity: scores?.velocity ?? 50,
        exposure: scores?.exposure ?? 50,
        uncertainty: scores?.uncertainty ?? 50,
        controllability: scores?.controllability ?? 50,
        confidence: output.confidence ?? 50,
        due_date: output.suggested_review_date ?? null,
      });
      setCreatedId(created.id);
      await api.dossierRiskAnalysis.review(artifact.id, {
        decision: "accepted",
        reason: "Propuesta de riesgo creada en el expediente por el usuario.",
        override: {
          created_risk_id: created.id,
          applied_title: nextTitle,
          recommended_status: output.recommended_status,
          evidence_ids: [
            ...facts.flatMap((fact) => fact.evidence_ids),
            ...scenarios.flatMap((scenario) => scenario.evidence_ids || []),
          ],
        },
      });
      toast.success("Riesgo creado", {
        description: "Aparece en el panel de riesgos de la portada del expediente.",
      });
      await load();
    } catch (reason) {
      setError(errorMessage(reason, "No se pudo crear el riesgo."));
    } finally {
      setBusy(false);
    }
  }

  async function rejectProposal() {
    if (!artifact) return;
    setBusy(true);
    setError(null);
    try {
      await api.dossierRiskAnalysis.review(artifact.id, {
        decision: "rejected",
        reason: "Propuesta de riesgo descartada por el usuario.",
      });
      toast.message("Propuesta descartada", {
        description: "No se ha creado ningún riesgo.",
      });
      await load();
    } catch (reason) {
      setError(errorMessage(reason, "No se pudo descartar la propuesta."));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="dossier-page dossier-section-page" data-testid="dossier-risk-analysis-section">
      <PageHeader
        eyebrow="Análisis"
        title="Análisis de riesgo"
        description="Oracle propone un riesgo a partir de la evidencia del expediente. Tú confirmas: sin tu acción no se crea ninguna fila de negocio. La propuesta solo se muestra si cita evidencia."
        actions={
          <div className="page-header-actions">
            <Link className="vector-secondary" href={`/app/dossiers/${dossierId}/risks`}>
              Riesgos
            </Link>
            <PermissionGate permission="ai.execute">
              <AsyncActionButton
                className="vector-primary"
                loading={busy || running}
                disabled={running}
                onClick={() => void runAnalysis()}
                data-testid="dossier-risk-run"
              >
                <Sparkles size={15} aria-hidden="true" />
                {artifact ? "Regenerar propuesta" : "Analizar riesgo"}
              </AsyncActionButton>
            </PermissionGate>
            <AsyncActionButton
              className="vector-secondary"
              loading={loading}
              onClick={() => void load()}
              data-testid="dossier-risk-refresh"
            >
              <RefreshCw size={15} aria-hidden="true" />
              Actualizar
            </AsyncActionButton>
          </div>
        }
      />

      {error ? (
        <p className="form-error" role="alert" data-testid="dossier-risk-error">
          {error}
        </p>
      ) : null}

      {createdId ? (
        <p role="status" data-testid="dossier-risk-created">
          Riesgo creado: <Link href={`/app/dossiers/${dossierId}`}>{createdId}</Link> · visible en
          el panel de la portada.
        </p>
      ) : null}

      {job && running ? (
        <JobProgress
          jobId={job.id}
          label="Analizando riesgo con evidencia del expediente"
          onTerminal={(next) => void onJobTerminal(next)}
        />
      ) : null}

      {loading && !artifact ? (
        <p role="status">Cargando…</p>
      ) : !artifact ? (
        <section className="vector-panel" data-testid="dossier-risk-empty">
          <header className="panel-heading">
            <ShieldAlert size={18} aria-hidden="true" />
            <div>
              <h2>Sin propuesta todavía</h2>
              <p>
                Lanza el análisis cuando haya documentos o evidencias en el expediente. La
                ejecución quedará en la auditoría de IA. Confirmar creará el riesgo en el panel de
                la portada.
              </p>
            </div>
          </header>
        </section>
      ) : (
        <div className="dossier-summary-grid" data-testid="dossier-risk-proposal">
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
                      <Link href="/app/admin/ai-audit" data-testid="dossier-risk-audit-link">
                        Ver en auditoría de IA
                      </Link>
                    </>
                  ) : null}
                </p>
              </div>
            </header>

            <dl className="detail-grid" data-testid="dossier-risk-meta">
              <div>
                <dt>Estado recomendado</dt>
                <dd data-testid="dossier-risk-recommended-status">
                  {statusLabel(String(output?.recommended_status ?? ""))}
                </dd>
              </div>
              <div>
                <dt>Categoría</dt>
                <dd>{output?.category || "—"}</dd>
              </div>
              <div>
                <dt>Score global</dt>
                <dd>{output?.scores?.overall ?? "—"}</dd>
              </div>
              <div>
                <dt>Hechos / escenarios con fuente</dt>
                <dd>
                  {facts.length} / {scenarios.length}
                </dd>
              </div>
            </dl>

            {!hasGrounding ? (
              <p className="form-error" role="status" data-testid="dossier-risk-no-grounding">
                La propuesta no cita hechos ni escenarios con evidencia. No se puede crear el
                riesgo (misma regla que el Competidor Sintético).
              </p>
            ) : null}

            {Array.isArray(output?.warnings) && output.warnings.length > 0 ? (
              <ul className="warning-list" data-testid="dossier-risk-warnings">
                {output.warnings.map((item) => (
                  <li key={item}>{item}</li>
                ))}
              </ul>
            ) : null}

            <PermissionGate permission="risk.write">
              <form
                className="dossier-settings-form"
                onSubmit={(event) => void applyProposal(event)}
                data-testid="dossier-risk-apply-form"
              >
                <label>
                  Título del riesgo
                  <input
                    value={title}
                    onChange={(event) => setTitle(event.target.value)}
                    maxLength={300}
                    required
                    data-testid="dossier-risk-title"
                  />
                </label>
                <label>
                  Descripción
                  <textarea
                    value={description}
                    onChange={(event) => setDescription(event.target.value)}
                    rows={5}
                    maxLength={10000}
                    data-testid="dossier-risk-description"
                  />
                </label>
                <div className="form-actions">
                  <AsyncActionButton
                    type="submit"
                    className="vector-primary"
                    loading={busy}
                    disabled={!canReview}
                    data-testid="dossier-risk-apply"
                  >
                    <CheckCircle2 size={15} aria-hidden="true" />
                    Confirmar y crear riesgo
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
                      data-testid="dossier-risk-reject"
                    >
                      <XCircle size={15} aria-hidden="true" />
                      Descartar propuesta
                    </AsyncActionButton>
                  </PermissionGate>
                </div>
                <p className="muted">
                  Confirmar crea un riesgo en el expediente (panel de la portada) y registra la
                  revisión humana. Descartar no crea filas de negocio.
                </p>
              </form>
            </PermissionGate>
          </section>

          <section className="vector-panel">
            <header className="panel-heading">
              <Link2 size={18} aria-hidden="true" />
              <div>
                <span className="section-kicker">Evidencias</span>
                <h2>Hechos, escenarios y mitigaciones</h2>
                <p>
                  Sin evidencia citada no se muestra el hallazgo (misma regla que el Competidor
                  Sintético).
                </p>
              </div>
            </header>

            <h3>Hechos</h3>
            {facts.length === 0 ? (
              <p data-testid="dossier-risk-no-facts">No hay hechos con evidencia citada.</p>
            ) : (
              <ul data-testid="dossier-risk-facts">
                {facts.map((fact) => (
                  <li key={`${fact.statement}-${fact.evidence_ids.join(",")}`}>
                    <p>{fact.statement}</p>
                    <small className="muted">
                      Evidencias: {fact.evidence_ids.length} ·{" "}
                      {fact.evidence_ids.slice(0, 3).join(", ")}
                      {fact.evidence_ids.length > 3 ? "…" : ""}
                    </small>
                  </li>
                ))}
              </ul>
            )}

            <h3>Escenarios con fuente</h3>
            {scenarios.length === 0 ? (
              <p data-testid="dossier-risk-no-scenarios">
                No hay escenarios con evidencia citada.
              </p>
            ) : (
              <ul data-testid="dossier-risk-scenarios">
                {scenarios.map((scenario) => (
                  <li key={scenario.name}>
                    <p>
                      <strong>{scenario.name}</strong> · P{scenario.probability} / I
                      {scenario.impact}
                    </p>
                    <p>{scenario.description}</p>
                  </li>
                ))}
              </ul>
            )}

            <h3>Inferencias con fuente</h3>
            {inferences.length === 0 ? (
              <p data-testid="dossier-risk-no-inferences">
                No hay inferencias con evidencia citada.
              </p>
            ) : (
              <ul data-testid="dossier-risk-inferences">
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

            {Array.isArray(output?.mitigations) && output.mitigations.length > 0 ? (
              <>
                <h3>Mitigaciones propuestas</h3>
                <ul data-testid="dossier-risk-mitigations">
                  {output.mitigations.map((item) => (
                    <li key={item.action}>
                      <strong>{item.action}</strong>
                      <span className="muted">
                        {" "}
                        · {item.owner_role} · efectividad {item.effectiveness}%
                      </span>
                      <p className="muted">Disparador: {item.trigger}</p>
                    </li>
                  ))}
                </ul>
              </>
            ) : null}

            {Array.isArray(output?.open_questions) && output.open_questions.length > 0 ? (
              <>
                <h3>Preguntas abiertas</h3>
                <ul data-testid="dossier-risk-questions">
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
