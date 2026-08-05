"use client";

import {
  ApiError,
  api,
  type ActorAnalysisArtifact,
  type ActorAnalysisOutput,
  type JobResponse,
  type OracleDossierActor,
} from "@oracle/api-client";
import {
  CheckCircle2,
  RefreshCw,
  Sparkles,
  UsersRound,
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
  return `dossier-actor-priority-${dossierId}-${suffix}`.slice(0, 200);
}

function errorMessage(reason: unknown, fallback: string) {
  return reason instanceof ApiError ? reason.problem.detail : fallback;
}

function groundedFacts(output: ActorAnalysisOutput | null | undefined) {
  if (!output?.facts?.length) return [];
  return output.facts.filter(
    (fact) =>
      typeof fact.statement === "string" &&
      fact.statement.trim() &&
      Array.isArray(fact.evidence_ids) &&
      fact.evidence_ids.length > 0,
  );
}

function groundedInferences(output: ActorAnalysisOutput | null | undefined) {
  if (!output?.inferences?.length) return [];
  return output.inferences.filter(
    (item) =>
      typeof item.statement === "string" &&
      item.statement.trim() &&
      Array.isArray(item.evidence_ids) &&
      item.evidence_ids.length > 0,
  );
}

function clampScore(value: unknown, fallback = 50): number {
  const n = typeof value === "number" ? value : Number(value);
  if (!Number.isFinite(n)) return fallback;
  return Math.max(0, Math.min(100, Math.round(n)));
}

export function DossierActorPartnershipSection({ dossierId }: { dossierId: string }) {
  const [artifact, setArtifact] = useState<ActorAnalysisArtifact | null>(null);
  const [job, setJob] = useState<JobResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [running, setRunning] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [actors, setActors] = useState<OracleDossierActor[]>([]);
  const [appliedLinkId, setAppliedLinkId] = useState<string | null>(null);

  const output = artifact?.output ?? null;
  const facts = useMemo(() => groundedFacts(output), [output]);
  const inferences = useMemo(() => groundedInferences(output), [output]);
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
      const [latest, actorPage] = await Promise.all([
        api.dossierActorPartnership.latest(dossierId),
        api.actors.listDossier(dossierId, { page: 1, size: 50 }),
      ]);
      setJob(latest.job);
      setArtifact(latest.artifact);
      setActors(actorPage.data ?? []);
      const nonTerminal = latest.job && !terminal.has(latest.job.status);
      setRunning(Boolean(nonTerminal));
    } catch (reason) {
      setError(errorMessage(reason, "No se pudo cargar la priorización de actores."));
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
    setAppliedLinkId(null);
    try {
      const response = await api.dossierActorPartnership.run(
        dossierId,
        idempotencyKey(dossierId),
      );
      setJob(response.job);
      if (response.artifact) setArtifact(response.artifact);
      const nonTerminal = response.job && !terminal.has(response.job.status);
      setRunning(Boolean(nonTerminal));
      if (!nonTerminal && response.job?.status === "succeeded") {
        toast.success("Propuesta lista", {
          description: "Revísala y confirma antes de aplicar scores al expediente.",
        });
        await load();
      } else if (nonTerminal) {
        toast.message("Análisis en curso", {
          description: "Oracle está priorizando actores con la evidencia del expediente.",
        });
      }
    } catch (reason) {
      setError(errorMessage(reason, "No se pudo lanzar la priorización de actores."));
    } finally {
      setBusy(false);
    }
  }

  async function onJobTerminal(next: JobResponse) {
    setJob(next);
    setRunning(false);
    if (next.status === "succeeded") {
      try {
        const latest = await api.dossierActorPartnership.latest(dossierId);
        setArtifact(latest.artifact);
        setJob(latest.job);
      } catch (reason) {
        setError(errorMessage(reason, "No se pudo recuperar la propuesta."));
      }
    }
  }

  async function applyProposal(event: FormEvent) {
    event.preventDefault();
    if (!artifact || !output) return;
    if (!hasGrounding) {
      setError("Sin hechos con evidencia citada no se pueden aplicar scores.");
      return;
    }
    const actorId = output.actor_id;
    if (!actorId) {
      setError("La propuesta no identifica un actor_id del expediente.");
      return;
    }
    const link = actors.find((item) => item.actor_id === actorId);
    if (!link?.id || link.version == null) {
      setError(
        "El actor propuesto no está vinculado a este expediente. Impórtalo o enlázalo antes de aplicar scores.",
      );
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const scores = output.scores;
      const updated = await api.actors.updateLink(
        link.id,
        {
          influence: clampScore(scores?.influence),
          relevance_to_dossier: clampScore(scores?.relevance),
          relationship_strength: clampScore(scores?.relationship_strength),
          accessibility: clampScore(scores?.accessibility),
          strategic_alignment: clampScore(scores?.strategic_alignment),
          recent_activity: clampScore(scores?.recent_activity),
          roles:
            output.roles
              ?.map((role) => role.role)
              .filter((role) => typeof role === "string" && role.trim())
              .slice(0, 12) || undefined,
        },
        link.version,
      );
      setAppliedLinkId(updated.id);
      await api.dossierActorPartnership.review(artifact.id, {
        decision: "accepted",
        reason: "Scores de priorización aplicados al actor del expediente por el usuario.",
        override: {
          applied_dossier_actor_id: updated.id,
          actor_id: actorId,
          priority: updated.priority,
          evidence_ids: facts.flatMap((fact) => fact.evidence_ids),
        },
      });
      toast.success("Prioridad aplicada", {
        description: "Visible en la pestaña Actores del expediente (orden por prioridad).",
      });
      await load();
    } catch (reason) {
      setError(errorMessage(reason, "No se pudieron aplicar los scores al actor."));
    } finally {
      setBusy(false);
    }
  }

  async function rejectProposal() {
    if (!artifact) return;
    setBusy(true);
    setError(null);
    try {
      await api.dossierActorPartnership.review(artifact.id, {
        decision: "rejected",
        reason: "Propuesta de priorización de actores descartada por el usuario.",
      });
      toast.message("Propuesta descartada", {
        description: "No se ha cambiado ningún actor del expediente.",
      });
      await load();
    } catch (reason) {
      setError(errorMessage(reason, "No se pudo descartar la propuesta."));
    } finally {
      setBusy(false);
    }
  }

  const scores = output?.scores;

  return (
    <div
      className="dossier-page dossier-section-page"
      data-testid="dossier-actor-partnership-section"
    >
      <PageHeader
        eyebrow="Análisis"
        title="Priorización de actores"
        description="Oracle ordena quién importa en el expediente con hechos citados. Tú confirmas: sin tu acción no se cambian scores ni roles."
        actions={
          <div className="page-header-actions">
            <Link className="vector-secondary" href={`/app/dossiers/${dossierId}/actors`}>
              Actores
            </Link>
            <PermissionGate permission="ai.execute">
              <AsyncActionButton
                className="vector-primary"
                loading={busy || running}
                disabled={running}
                onClick={() => void runAnalysis()}
                data-testid="dossier-actor-partnership-run"
              >
                <Sparkles size={15} aria-hidden="true" />
                {artifact ? "Regenerar priorización" : "Priorizar actores"}
              </AsyncActionButton>
            </PermissionGate>
            <AsyncActionButton
              className="vector-secondary"
              loading={loading}
              onClick={() => void load()}
              data-testid="dossier-actor-partnership-refresh"
            >
              <RefreshCw size={15} aria-hidden="true" />
              Actualizar
            </AsyncActionButton>
          </div>
        }
      />

      {error ? (
        <p className="form-error" role="alert" data-testid="dossier-actor-partnership-error">
          {error}
        </p>
      ) : null}

      {appliedLinkId ? (
        <p role="status" data-testid="dossier-actor-partnership-applied">
          Prioridad aplicada al vínculo {appliedLinkId.slice(0, 8)}… · visible en Actores.
        </p>
      ) : null}

      {job && running ? (
        <JobProgress
          jobId={job.id}
          label="Priorizando actores con evidencia del expediente"
          onTerminal={(next) => void onJobTerminal(next)}
        />
      ) : null}

      {loading && !artifact ? (
        <p role="status">Cargando…</p>
      ) : !artifact ? (
        <section className="vector-panel" data-testid="dossier-actor-partnership-empty">
          <header className="panel-heading">
            <UsersRound size={18} aria-hidden="true" />
            <div>
              <h2>Sin propuesta todavía</h2>
              <p>
                Lanza la priorización cuando haya actores y evidencia (p. ej. adjudicaciones
                PLACSP). Confirmar actualizará los scores del actor en el expediente.
              </p>
            </div>
          </header>
        </section>
      ) : (
        <div className="dossier-summary-grid" data-testid="dossier-actor-partnership-proposal">
          <section className="vector-panel">
            <header className="panel-heading">
              <Sparkles size={18} aria-hidden="true" />
              <div>
                <span className="section-kicker">Propuesta del agente</span>
                <h2>Revisión humana obligatoria</h2>
                <p>
                  Estado: <strong>{artifact.status}</strong>
                  {artifact.audit_log_id ? (
                    <>
                      {" "}
                      ·{" "}
                      <Link href="/app/admin/ai-audit" data-testid="dossier-actor-partnership-audit-link">
                        Ver en auditoría de IA
                      </Link>
                    </>
                  ) : null}
                </p>
              </div>
            </header>

            <dl className="detail-grid" data-testid="dossier-actor-partnership-meta">
              <div>
                <dt>Actor propuesto</dt>
                <dd data-testid="dossier-actor-partnership-actor-id">
                  {output?.actor_id || "—"}
                </dd>
              </div>
              <div>
                <dt>Prioridad global</dt>
                <dd data-testid="dossier-actor-partnership-priority">
                  {scores?.overall_priority ?? "—"}
                </dd>
              </div>
              <div>
                <dt>Confianza</dt>
                <dd>{output?.confidence ?? "—"}</dd>
              </div>
              <div>
                <dt>Hechos con fuente</dt>
                <dd>{facts.length}</dd>
              </div>
            </dl>

            {!hasGrounding ? (
              <p className="form-error" role="status" data-testid="dossier-actor-partnership-no-grounding">
                La propuesta no cita hechos con evidencia. No se pueden aplicar scores.
              </p>
            ) : null}

            {Array.isArray(output?.warnings) && output.warnings.length > 0 ? (
              <ul className="warning-list" data-testid="dossier-actor-partnership-warnings">
                {output.warnings.map((item) => (
                  <li key={item}>{item}</li>
                ))}
              </ul>
            ) : null}

            <PermissionGate permission="actor.write">
              <form
                className="dossier-settings-form"
                onSubmit={(event) => void applyProposal(event)}
                data-testid="dossier-actor-partnership-apply-form"
              >
                <div className="form-actions">
                  <AsyncActionButton
                    type="submit"
                    className="vector-primary"
                    loading={busy}
                    disabled={!canReview}
                    data-testid="dossier-actor-partnership-apply"
                  >
                    <CheckCircle2 size={15} aria-hidden="true" />
                    Confirmar y aplicar prioridad
                  </AsyncActionButton>
                  <PermissionGate permission="ai.review">
                    <AsyncActionButton
                      type="button"
                      className="vector-secondary"
                      loading={busy}
                      disabled={!artifact || running}
                      onClick={() => void rejectProposal()}
                      data-testid="dossier-actor-partnership-reject"
                    >
                      <XCircle size={15} aria-hidden="true" />
                      Descartar
                    </AsyncActionButton>
                  </PermissionGate>
                </div>
              </form>
            </PermissionGate>
          </section>

          <section className="vector-panel">
            <header className="panel-heading">
              <div>
                <h2>Hechos citados</h2>
              </div>
            </header>
            {facts.length === 0 ? (
              <p className="muted">Sin hechos con evidencia.</p>
            ) : (
              <ul data-testid="dossier-actor-partnership-facts">
                {facts.map((fact) => (
                  <li key={`${fact.statement}-${fact.evidence_ids.join(",")}`}>
                    {fact.statement}
                    <span className="muted"> · {fact.evidence_ids.length} cita(s)</span>
                  </li>
                ))}
              </ul>
            )}
            {inferences.length > 0 ? (
              <>
                <h3>Inferencias con fuente</h3>
                <ul data-testid="dossier-actor-partnership-inferences">
                  {inferences.map((item) => (
                    <li key={`${item.statement}-${item.confidence}`}>
                      {item.statement}{" "}
                      <span className="muted">({item.confidence}%)</span>
                    </li>
                  ))}
                </ul>
              </>
            ) : null}
            {Array.isArray(output?.engagement_actions) && output.engagement_actions.length > 0 ? (
              <>
                <h3>Acciones de engagement (no automáticas)</h3>
                <ul data-testid="dossier-actor-partnership-engagement">
                  {output.engagement_actions.map((item) => (
                    <li key={`${item.action}-${item.channel}`}>
                      <strong>{item.priority}</strong>: {item.action} vía {item.channel} —{" "}
                      {item.objective}
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
