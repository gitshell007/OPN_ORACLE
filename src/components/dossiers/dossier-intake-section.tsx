"use client";

import {
  ApiError,
  api,
  type BackendDossier,
  type IntakeArtifact,
  type IntakeOutput,
  type JobResponse,
} from "@oracle/api-client";
import {
  CheckCircle2,
  FileInput,
  Link2,
  RefreshCw,
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
import { productDossierTypeLabel } from "@/lib/product-copy";

const terminal = new Set(["succeeded", "failed", "cancelled"]);

function idempotencyKey(dossierId: string): string {
  const suffix =
    typeof crypto !== "undefined" && "randomUUID" in crypto
      ? crypto.randomUUID()
      : `${Date.now()}-${Math.random().toString(16).slice(2)}`;
  return `dossier-intake-${dossierId}-${suffix}`.slice(0, 200);
}

function errorMessage(reason: unknown, fallback: string) {
  return reason instanceof ApiError ? reason.problem.detail : fallback;
}

/** Solo hechos con al menos una evidencia; sin fuente no se exponen. */
function groundedFacts(output: IntakeOutput | null | undefined) {
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
function groundedInferences(output: IntakeOutput | null | undefined) {
  if (!output?.inferences?.length) return [];
  return output.inferences.filter(
    (item) =>
      typeof item.statement === "string" &&
      item.statement.trim() &&
      Array.isArray(item.evidence_ids) &&
      item.evidence_ids.length > 0,
  );
}

function typeLabel(value: string | undefined) {
  if (!value) return "—";
  try {
    return productDossierTypeLabel(value);
  } catch {
    return value;
  }
}

export function DossierIntakeSection({ dossierId }: { dossierId: string }) {
  const [dossier, setDossier] = useState<BackendDossier | null>(null);
  const [artifact, setArtifact] = useState<IntakeArtifact | null>(null);
  const [job, setJob] = useState<JobResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [running, setRunning] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");

  const output = artifact?.output ?? null;
  const facts = useMemo(() => groundedFacts(output), [output]);
  const inferences = useMemo(() => groundedInferences(output), [output]);
  const canReview =
    Boolean(artifact) &&
    artifact?.status !== "valid" &&
    artifact?.status !== "rejected" &&
    !running;

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [dossierResource, latest] = await Promise.all([
        api.dossiers.get(dossierId),
        api.dossierIntake.latest(dossierId),
      ]);
      setDossier(dossierResource);
      setJob(latest.job);
      setArtifact(latest.artifact);
      const proposal = latest.artifact?.output;
      if (proposal) {
        setTitle(proposal.proposed_title || dossierResource.title || "");
        setDescription(
          proposal.proposed_description || dossierResource.description || "",
        );
      } else {
        setTitle(dossierResource.title || "");
        setDescription(dossierResource.description || "");
      }
      const nonTerminal = latest.job && !terminal.has(latest.job.status);
      setRunning(Boolean(nonTerminal));
    } catch (reason) {
      setError(errorMessage(reason, "No se pudo cargar el análisis de entrada."));
    } finally {
      setLoading(false);
    }
  }, [dossierId]);

  useEffect(() => {
    const kickoff = window.setTimeout(() => void load(), 0);
    return () => window.clearTimeout(kickoff);
  }, [load]);

  async function runIntake() {
    setBusy(true);
    setError(null);
    try {
      const response = await api.dossierIntake.run(dossierId, idempotencyKey(dossierId));
      setJob(response.job);
      if (response.artifact) {
        setArtifact(response.artifact);
        const proposal = response.artifact.output;
        setTitle(proposal.proposed_title || title);
        setDescription(proposal.proposed_description || description);
      }
      const nonTerminal = response.job && !terminal.has(response.job.status);
      setRunning(Boolean(nonTerminal));
      if (!nonTerminal && response.job?.status === "succeeded") {
        toast.success("Propuesta lista", {
          description: "Revísala y confirma antes de aplicar cambios al expediente.",
        });
        await load();
      } else if (nonTerminal) {
        toast.message("Análisis en curso", {
          description: "Oracle está leyendo las evidencias del expediente.",
        });
      }
    } catch (reason) {
      setError(errorMessage(reason, "No se pudo lanzar el análisis de entrada."));
    } finally {
      setBusy(false);
    }
  }

  async function onJobTerminal(next: JobResponse) {
    setJob(next);
    setRunning(false);
    if (next.status === "succeeded") {
      try {
        const latest = await api.dossierIntake.latest(dossierId);
        setArtifact(latest.artifact);
        setJob(latest.job);
        if (latest.artifact?.output) {
          setTitle(latest.artifact.output.proposed_title || title);
          setDescription(latest.artifact.output.proposed_description || description);
        }
      } catch (reason) {
        setError(errorMessage(reason, "No se pudo recuperar la propuesta."));
      }
    }
  }

  async function applyProposal(event: FormEvent) {
    event.preventDefault();
    if (!artifact || !dossier) return;
    const nextTitle = title.trim();
    if (!nextTitle) {
      setError("El título no puede estar vacío.");
      return;
    }
    if (dossier.version == null) {
      setError("No se puede aplicar sin versión del expediente.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      // 1) Mutación de negocio solo por acción humana explícita.
      const updated = await api.dossiers.update(
        dossierId,
        { title: nextTitle, description: description.trim() },
        dossier.version,
      );
      setDossier(updated);
      // 2) Marca la revisión humana sobre el artefacto (auditoría).
      await api.dossierIntake.review(artifact.id, {
        decision: "accepted",
        reason: "Propuesta de intake aplicada al expediente por el usuario.",
        override: {
          applied_title: nextTitle,
          applied_description: description.trim(),
          proposed_dossier_type: output?.dossier_type ?? null,
          type_not_applied: true,
        },
      });
      toast.success("Expediente actualizado", {
        description:
          "Se aplicaron título y descripción. El tipo de expediente no se cambia automáticamente.",
      });
      await load();
    } catch (reason) {
      setError(errorMessage(reason, "No se pudo aplicar la propuesta."));
    } finally {
      setBusy(false);
    }
  }

  async function rejectProposal() {
    if (!artifact) return;
    setBusy(true);
    setError(null);
    try {
      await api.dossierIntake.review(artifact.id, {
        decision: "rejected",
        reason: "Propuesta de intake descartada por el usuario.",
      });
      toast.message("Propuesta descartada", {
        description: "El expediente no se ha modificado.",
      });
      await load();
    } catch (reason) {
      setError(errorMessage(reason, "No se pudo descartar la propuesta."));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="dossier-page dossier-section-page" data-testid="dossier-intake-section">
      <PageHeader
        eyebrow="Onboarding"
        title="Análisis de entrada"
        description="Convierte un pliego, correo o documento del expediente en una propuesta estructurada. Oracle propone; tú confirmas. No se crean entidades de negocio sin tu acción."
        actions={
          <div className="page-header-actions">
            <Link className="vector-secondary" href={`/app/dossiers/${dossierId}/documents`}>
              Documentos
            </Link>
            <PermissionGate permission="ai.execute">
              <AsyncActionButton
                className="vector-primary"
                loading={busy || running}
                disabled={running}
                onClick={() => void runIntake()}
                data-testid="dossier-intake-run"
              >
                <Sparkles size={15} aria-hidden="true" />
                {artifact ? "Regenerar propuesta" : "Analizar entrada"}
              </AsyncActionButton>
            </PermissionGate>
            <AsyncActionButton
              className="vector-secondary"
              loading={loading}
              onClick={() => void load()}
              data-testid="dossier-intake-refresh"
            >
              <RefreshCw size={15} aria-hidden="true" />
              Actualizar
            </AsyncActionButton>
          </div>
        }
      />

      {error ? (
        <p className="form-error" role="alert" data-testid="dossier-intake-error">
          {error}
        </p>
      ) : null}

      {job && running ? (
        <JobProgress
          jobId={job.id}
          label="Analizando evidencias del expediente"
          onTerminal={(next) => void onJobTerminal(next)}
        />
      ) : null}

      {loading && !artifact ? (
        <p role="status">Cargando…</p>
      ) : !artifact ? (
        <section className="vector-panel" data-testid="dossier-intake-empty">
          <header className="panel-heading">
            <FileInput size={18} aria-hidden="true" />
            <div>
              <h2>Sin propuesta todavía</h2>
              <p>
                Sube un pliego o correo en{" "}
                <Link href={`/app/dossiers/${dossierId}/documents`}>Documentos</Link> y lanza el
                análisis. La ejecución quedará registrada en la auditoría de IA con coste y
                evidencias.
              </p>
            </div>
          </header>
        </section>
      ) : (
        <div className="dossier-summary-grid" data-testid="dossier-intake-proposal">
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
                      <Link
                        href={`/app/admin/ai-audit`}
                        data-testid="dossier-intake-audit-link"
                      >
                        Ver en auditoría de IA
                      </Link>
                    </>
                  ) : null}
                </p>
              </div>
            </header>

            <dl className="detail-grid" data-testid="dossier-intake-meta">
              <div>
                <dt>Tipo propuesto</dt>
                <dd data-testid="dossier-intake-proposed-type">
                  {typeLabel(String(output?.dossier_type ?? ""))}
                  <small className="muted"> (no se aplica solo; el tipo se elige al crear)</small>
                </dd>
              </div>
              <div>
                <dt>Confianza</dt>
                <dd>{output?.confidence ?? "—"} %</dd>
              </div>
              <div>
                <dt>Hechos con fuente</dt>
                <dd>{facts.length}</dd>
              </div>
              <div>
                <dt>Inferencias con fuente</dt>
                <dd>{inferences.length}</dd>
              </div>
            </dl>

            {Array.isArray(output?.warnings) && output.warnings.length > 0 ? (
              <ul className="warning-list" data-testid="dossier-intake-warnings">
                {output.warnings.map((item) => (
                  <li key={item}>{item}</li>
                ))}
              </ul>
            ) : null}

            <PermissionGate permission="dossier.write">
              <form
                className="dossier-settings-form"
                onSubmit={(event) => void applyProposal(event)}
                data-testid="dossier-intake-apply-form"
              >
                <label>
                  Título a aplicar
                  <input
                    value={title}
                    onChange={(event) => setTitle(event.target.value)}
                    maxLength={240}
                    required
                    data-testid="dossier-intake-title"
                  />
                </label>
                <label>
                  Descripción a aplicar
                  <textarea
                    value={description}
                    onChange={(event) => setDescription(event.target.value)}
                    rows={5}
                    maxLength={10000}
                    data-testid="dossier-intake-description"
                  />
                </label>
                <div className="form-actions">
                  <AsyncActionButton
                    type="submit"
                    className="vector-primary"
                    loading={busy}
                    disabled={!canReview}
                    data-testid="dossier-intake-apply"
                  >
                    <CheckCircle2 size={15} aria-hidden="true" />
                    Confirmar y aplicar al expediente
                  </AsyncActionButton>
                  <PermissionGate permission="ai.review">
                    <AsyncActionButton
                      type="button"
                      className="vector-secondary"
                      loading={busy}
                      disabled={!canReview}
                      onClick={() => void rejectProposal()}
                      data-testid="dossier-intake-reject"
                    >
                      <XCircle size={15} aria-hidden="true" />
                      Descartar propuesta
                    </AsyncActionButton>
                  </PermissionGate>
                </div>
                <p className="muted">
                  Confirmar actualiza solo título y descripción del expediente y registra la
                  revisión humana. No crea actores, oportunidades ni riesgos.
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

            <h3>Hechos</h3>
            {facts.length === 0 ? (
              <p data-testid="dossier-intake-no-facts">No hay hechos con evidencia citada.</p>
            ) : (
              <ul data-testid="dossier-intake-facts">
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

            <h3>Inferencias con fuente</h3>
            {inferences.length === 0 ? (
              <p data-testid="dossier-intake-no-inferences">
                No hay inferencias con evidencia citada.
              </p>
            ) : (
              <ul data-testid="dossier-intake-inferences">
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

            {Array.isArray(output?.open_questions) && output.open_questions.length > 0 ? (
              <>
                <h3>Preguntas abiertas</h3>
                <ul data-testid="dossier-intake-questions">
                  {output.open_questions.map((question) => (
                    <li key={question}>{question}</li>
                  ))}
                </ul>
              </>
            ) : null}

            {Array.isArray(output?.recommendations) && output.recommendations.length > 0 ? (
              <>
                <h3>Próximos pasos sugeridos</h3>
                <ul data-testid="dossier-intake-recommendations">
                  {output.recommendations.map((item) => (
                    <li key={item.action}>
                      <strong>{item.action}</strong>
                      <span className="muted"> · {item.priority}</span>
                      <p>{item.rationale}</p>
                    </li>
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
