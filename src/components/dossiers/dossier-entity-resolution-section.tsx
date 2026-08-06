"use client";

import {
  ApiError,
  api,
  type EntityResolutionArtifact,
  type EntityResolutionOutput,
  type JobResponse,
} from "@oracle/api-client";
import {
  CheckCircle2,
  GitMerge,
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

const terminal = new Set(["succeeded", "failed", "cancelled"]);

function idempotencyKey(dossierId: string): string {
  const suffix =
    typeof crypto !== "undefined" && "randomUUID" in crypto
      ? crypto.randomUUID()
      : `${Date.now()}-${Math.random().toString(16).slice(2)}`;
  return `dossier-entity-resolution-${dossierId}-${suffix}`.slice(0, 200);
}

function errorMessage(reason: unknown, fallback: string) {
  return reason instanceof ApiError ? reason.problem.detail : fallback;
}

function groundedFacts(output: EntityResolutionOutput | null | undefined) {
  if (!output?.facts?.length) return [];
  return output.facts.filter(
    (fact) =>
      typeof fact.statement === "string" &&
      fact.statement.trim() &&
      Array.isArray(fact.evidence_ids) &&
      fact.evidence_ids.length > 0,
  );
}

function decisionLabel(value: string | undefined) {
  switch (value) {
    case "match":
      return "Match (mismo actor)";
    case "no_match":
      return "No match";
    case "needs_review":
      return "Requiere revisión";
    case "create_new":
      return "Crear nuevo";
    default:
      return value || "—";
  }
}

export function DossierEntityResolutionSection({ dossierId }: { dossierId: string }) {
  const [artifact, setArtifact] = useState<EntityResolutionArtifact | null>(null);
  const [job, setJob] = useState<JobResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [running, setRunning] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [sourceActorId, setSourceActorId] = useState("");
  const [mergeReason, setMergeReason] = useState("");
  const [mergedTargetId, setMergedTargetId] = useState<string | null>(null);

  const output = artifact?.output ?? null;
  const facts = useMemo(() => groundedFacts(output), [output]);
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
      const latest = await api.dossierEntityResolution.latest(dossierId);
      setJob(latest.job);
      setArtifact(latest.artifact);
      const nonTerminal = latest.job && !terminal.has(latest.job.status);
      setRunning(Boolean(nonTerminal));
    } catch (reason) {
      setError(errorMessage(reason, "No se pudo cargar la resolución de entidades."));
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
    setMergedTargetId(null);
    try {
      const response = await api.dossierEntityResolution.run(
        dossierId,
        idempotencyKey(dossierId),
      );
      setJob(response.job);
      if (response.artifact) setArtifact(response.artifact);
      const nonTerminal = response.job && !terminal.has(response.job.status);
      setRunning(Boolean(nonTerminal));
      if (!nonTerminal && response.job?.status === "succeeded") {
        toast.success("Propuesta lista", {
          description: "Nada se fusiona solo: revisa y confirma.",
        });
        await load();
      } else if (nonTerminal) {
        toast.message("Resolución en curso", {
          description: "Oracle compara entidades con NIF/CIF y evidencia.",
        });
      }
    } catch (reason) {
      setError(errorMessage(reason, "No se pudo lanzar la resolución de entidades."));
    } finally {
      setBusy(false);
    }
  }

  async function onJobTerminal(next: JobResponse) {
    setJob(next);
    setRunning(false);
    if (next.status === "succeeded") {
      try {
        const latest = await api.dossierEntityResolution.latest(dossierId);
        setArtifact(latest.artifact);
        setJob(latest.job);
      } catch (reason) {
        setError(errorMessage(reason, "No se pudo recuperar la propuesta."));
      }
    }
  }

  async function acceptWithoutMerge(event: FormEvent) {
    event.preventDefault();
    if (!artifact || !output) return;
    if (!hasGrounding) {
      setError("Sin hechos con evidencia citada no se puede aceptar la propuesta.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await api.dossierEntityResolution.review(artifact.id, {
        decision: "accepted",
        reason: "Propuesta de resolución aceptada sin fusión automática.",
        override: {
          decision: output.decision,
          matched_actor_id: output.matched_actor_id,
          rationale: output.rationale,
          evidence_ids: facts.flatMap((fact) => fact.evidence_ids),
          merge_performed: false,
        },
      });
      toast.success("Propuesta aceptada", {
        description:
          output.decision === "match"
            ? "Registrada. La fusión sigue siendo opcional y manual abajo."
            : "Registrada sin mutar el directorio de actores.",
      });
      await load();
    } catch (reason) {
      setError(errorMessage(reason, "No se pudo aceptar la propuesta."));
    } finally {
      setBusy(false);
    }
  }

  async function confirmMerge(event: FormEvent) {
    event.preventDefault();
    if (!artifact || !output) return;
    if (output.decision !== "match" || !output.matched_actor_id) {
      setError("Solo se puede fusionar cuando la decisión es match con matched_actor_id.");
      return;
    }
    const source = sourceActorId.trim();
    const target = String(output.matched_actor_id);
    if (!source || source === target) {
      setError("Indica el actor origen (UUID) distinto del destino propuesto.");
      return;
    }
    if (mergeReason.trim().length < 3) {
      setError("El motivo de fusión es obligatorio (mín. 3 caracteres).");
      return;
    }
    if (!hasGrounding) {
      setError("Sin hechos citados no se autoriza la fusión.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const [targetActor, sourceActor] = await Promise.all([
        api.actors.get(target),
        api.actors.get(source),
      ]);
      const preview = await api.actors.mergePreview(target, {
        source_actor_id: source,
      });
      if (preview.blocked) {
        setError(preview.block_reason || "Fusión bloqueada por NIF distintos.");
        return;
      }
      const merged = await api.actors.merge(target, {
        source_actor_id: source,
        reason: mergeReason.trim(),
        confirm: true,
        expected_target_version:
          preview.confirmation_required.expected_target_version ||
          Number(targetActor.version || 1),
        expected_source_version:
          preview.confirmation_required.expected_source_version ||
          Number(sourceActor.version || 1),
        match_reason: "entity_resolution",
      });
      setMergedTargetId(merged.id);
      await api.dossierEntityResolution.review(artifact.id, {
        decision: "accepted",
        reason: "Fusión confirmada por persona tras propuesta de resolución.",
        override: {
          decision: output.decision,
          matched_actor_id: target,
          source_actor_id: source,
          merge_performed: true,
          evidence_ids: facts.flatMap((fact) => fact.evidence_ids),
          merge_reason: mergeReason.trim(),
        },
      });
      toast.success("Fusión confirmada", {
        description: "Queda en auditoría actor.merged. El origen se unifica en el destino.",
      });
      await load();
    } catch (reason) {
      setError(errorMessage(reason, "No se pudo fusionar (fail-closed)."));
    } finally {
      setBusy(false);
    }
  }

  async function rejectProposal() {
    if (!artifact) return;
    setBusy(true);
    setError(null);
    try {
      await api.dossierEntityResolution.review(artifact.id, {
        decision: "rejected",
        reason: "Propuesta de resolución de entidades descartada por el usuario.",
      });
      toast.message("Propuesta descartada", {
        description: "No se ha fusionado ni creado ningún actor.",
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
      data-testid="dossier-entity-resolution-section"
    >
      <PageHeader
        eyebrow="Análisis"
        title="Resolución de entidades"
        description="Oracle propone match / no match / revisión con el NIF por delante del nombre. Nunca fusiona solo: la persona confirma."
        actions={
          <div className="page-header-actions">
            <Link className="vector-secondary" href="/app/actors/duplicates">
              Candidatos a fusión
            </Link>
            <PermissionGate permission="ai.execute">
              <AsyncActionButton
                className="vector-primary"
                loading={busy || running}
                disabled={running}
                onClick={() => void runAnalysis()}
                data-testid="dossier-entity-resolution-run"
              >
                <Sparkles size={15} aria-hidden="true" />
                {artifact ? "Regenerar resolución" : "Resolver entidades"}
              </AsyncActionButton>
            </PermissionGate>
            <AsyncActionButton
              className="vector-secondary"
              loading={loading}
              onClick={() => void load()}
              data-testid="dossier-entity-resolution-refresh"
            >
              <RefreshCw size={15} aria-hidden="true" />
              Actualizar
            </AsyncActionButton>
          </div>
        }
      />

      {error ? (
        <p className="form-error" role="alert" data-testid="dossier-entity-resolution-error">
          {error}
        </p>
      ) : null}

      {mergedTargetId ? (
        <p role="status" data-testid="dossier-entity-resolution-merged">
          Fusión aplicada sobre {mergedTargetId.slice(0, 8)}… · ver también Candidatos a fusión.
        </p>
      ) : null}

      {job && running ? (
        <JobProgress
          jobId={job.id}
          label="Resolviendo entidades (NIF manda sobre el nombre)"
          onTerminal={(next) => void onJobTerminal(next)}
        />
      ) : null}

      {loading && !artifact ? (
        <p role="status">Cargando…</p>
      ) : !artifact ? (
        <section className="vector-panel" data-testid="dossier-entity-resolution-empty">
          <header className="panel-heading">
            <GitMerge size={18} aria-hidden="true" />
            <div>
              <h2>Sin propuesta todavía</h2>
              <p>
                Lanza la resolución cuando haya actores con o sin NIF. Sin identificador común
                solo verás candidatos de baja confianza, nunca fusión automática.
              </p>
            </div>
          </header>
        </section>
      ) : (
        <div className="dossier-summary-grid" data-testid="dossier-entity-resolution-proposal">
          <section className="vector-panel">
            <header className="panel-heading">
              <Sparkles size={18} aria-hidden="true" />
              <div>
                <span className="section-kicker">Propuesta del agente</span>
                <h2>Revisión humana obligatoria · sin merge automático</h2>
                <p>
                  Estado: <strong>{artifact.status}</strong>
                  {artifact.audit_log_id ? (
                    <>
                      {" "}
                      ·{" "}
                      <Link href="/app/admin/ai-audit" data-testid="dossier-entity-resolution-audit-link">
                        Ver en auditoría de IA
                      </Link>
                    </>
                  ) : null}
                </p>
              </div>
            </header>

            <dl className="detail-grid" data-testid="dossier-entity-resolution-meta">
              <div>
                <dt>Decisión</dt>
                <dd data-testid="dossier-entity-resolution-decision">
                  {decisionLabel(output?.decision)}
                </dd>
              </div>
              <div>
                <dt>Actor destino propuesto</dt>
                <dd data-testid="dossier-entity-resolution-matched">
                  {output?.matched_actor_id || "—"}
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

            {output?.rationale ? (
              <p data-testid="dossier-entity-resolution-rationale">{output.rationale}</p>
            ) : null}

            {!hasGrounding ? (
              <p className="form-error" role="status" data-testid="dossier-entity-resolution-no-grounding">
                Sin hechos citados no se acepta la propuesta ni se fusiona.
              </p>
            ) : null}

            {Array.isArray(output?.warnings) && output.warnings.length > 0 ? (
              <ul className="warning-list" data-testid="dossier-entity-resolution-warnings">
                {output.warnings.map((item) => (
                  <li key={item}>{item}</li>
                ))}
              </ul>
            ) : null}

            <PermissionGate permission="ai.review">
              <form
                className="dossier-settings-form"
                onSubmit={(event) => void acceptWithoutMerge(event)}
                data-testid="dossier-entity-resolution-accept-form"
              >
                <div className="form-actions">
                  <AsyncActionButton
                    type="submit"
                    className="vector-primary"
                    loading={busy}
                    disabled={!canReview}
                    data-testid="dossier-entity-resolution-accept"
                  >
                    <CheckCircle2 size={15} aria-hidden="true" />
                    Aceptar propuesta (sin fusionar)
                  </AsyncActionButton>
                  <AsyncActionButton
                    type="button"
                    className="vector-secondary"
                    loading={busy}
                    disabled={!artifact || running}
                    onClick={() => void rejectProposal()}
                    data-testid="dossier-entity-resolution-reject"
                  >
                    <XCircle size={15} aria-hidden="true" />
                    Descartar
                  </AsyncActionButton>
                </div>
              </form>
            </PermissionGate>

            {output?.decision === "match" && output.matched_actor_id ? (
              <PermissionGate permission="actor.write">
                <form
                  className="dossier-settings-form"
                  onSubmit={(event) => void confirmMerge(event)}
                  data-testid="dossier-entity-resolution-merge-form"
                  style={{ marginTop: "1rem" }}
                >
                  <h3>Fusión opcional (solo si la persona lo pide)</h3>
                  <p className="muted">
                    El NIF debe mandar. Indica el actor origen y un motivo. Es irreversible con un
                    clic.
                  </p>
                  <label>
                    Actor origen (UUID a absorber)
                    <input
                      value={sourceActorId}
                      onChange={(event) => setSourceActorId(event.target.value)}
                      placeholder="uuid del actor origen"
                      data-testid="dossier-entity-resolution-source"
                    />
                  </label>
                  <label>
                    Motivo de fusión
                    <input
                      value={mergeReason}
                      onChange={(event) => setMergeReason(event.target.value)}
                      minLength={3}
                      placeholder="Mismo CIF en adjudicaciones PLACSP"
                      data-testid="dossier-entity-resolution-merge-reason"
                    />
                  </label>
                  <AsyncActionButton
                    type="submit"
                    className="vector-primary"
                    loading={busy}
                    disabled={!canReview}
                    data-testid="dossier-entity-resolution-merge"
                  >
                    <GitMerge size={15} aria-hidden="true" />
                    Confirmar fusión en destino propuesto
                  </AsyncActionButton>
                </form>
              </PermissionGate>
            ) : null}
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
              <ul data-testid="dossier-entity-resolution-facts">
                {facts.map((fact) => (
                  <li key={`${fact.statement}-${fact.evidence_ids.join(",")}`}>
                    {fact.statement}
                    <span className="muted"> · {fact.evidence_ids.length} cita(s)</span>
                  </li>
                ))}
              </ul>
            )}
          </section>
        </div>
      )}
    </div>
  );
}
