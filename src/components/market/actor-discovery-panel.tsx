"use client";

/**
 * Panel vivo de descubrimiento de actores en el expediente de Mercado.
 * Consulta latest(dossier_id), muestra estados honestos, reintenta y acepta
 * con candidate_id + source_ids (materializa Evidence, no crea Actor).
 */

import {
  ApiError,
  api,
  type BackendDossier,
  type MarketActorDiscoveryArtifact,
  type MarketActorDiscoveryOutput,
  type TenderSearchWizardJob,
} from "@oracle/api-client";
import { RefreshCw } from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
import { toast } from "sonner";
import {
  ActorDiscoveryList,
  actorIsSelectable,
  buildActorAcceptSelection,
} from "@/components/market/actor-discovery-list";
import { AsyncActionButton } from "@/components/ui/async-action-button";
import { productActorTypeLabel, productStatusLabel } from "@/lib/product-copy";

const terminal = new Set(["succeeded", "failed", "cancelled"]);

export type ActorDiscoveryFailureKind =
  | "ai_policy_denied"
  | "ai_unavailable"
  | "generic";

export type ActorDiscoveryFailureInfo = {
  kind: ActorDiscoveryFailureKind;
  headline: string;
  message: string;
  actionHref?: string;
  actionLabel?: string;
};

function errorMessage(reason: unknown, fallback: string) {
  return reason instanceof ApiError ? reason.problem.detail : fallback;
}

function hasDiscoveryIntent(dossier: BackendDossier | null | undefined): boolean {
  if (!dossier || dossier.dossier_type !== "market") return false;
  const profile = dossier.profile_config ?? {};
  const intent = String(profile.discovery_intent ?? "").trim();
  const actorType = String(profile.discovery_actor_type ?? "").trim();
  return intent.length >= 10 && Boolean(actorType);
}

function retryIdempotencyKey(dossierId: string): string {
  const suffix =
    typeof crypto !== "undefined" && "randomUUID" in crypto
      ? crypto.randomUUID()
      : `${Date.now()}-${Math.random().toString(16).slice(2)}`;
  return `g19-actor-run:${dossierId}:retry:${suffix}`.slice(0, 200);
}

/** Interpreta error_code / error_message del job (causa raíz en background_jobs). */
export function resolveActorDiscoveryFailure(
  job: Pick<TenderSearchWizardJob, "error_code" | "error_message"> | null | undefined,
): ActorDiscoveryFailureInfo {
  const code = String(job?.error_code ?? "");
  const raw = String(job?.error_message ?? "");
  const haystack = `${code}\n${raw}`;

  if (
    /\bAIPolicyDenied\b/i.test(haystack) ||
    /IA está deshabilitada para este tenant/i.test(raw) ||
    /inteligencia artificial.*desactivad/i.test(raw)
  ) {
    return {
      kind: "ai_policy_denied",
      headline: "La inteligencia artificial está desactivada",
      message:
        "Su organización tiene la IA deshabilitada, por eso no se puede buscar actores. Un administrador puede activarla en Administración › Inteligencia artificial.",
      actionHref: "/app/admin/ai",
      actionLabel: "Ir a Inteligencia artificial",
    };
  }

  if (
    /\bAIUnavailable\b/i.test(haystack) ||
    /Signal (tiene deshabilitada|rechazó|rechazo|no est)/i.test(raw) ||
    /no autorizad/i.test(raw) ||
    /consumidor/i.test(raw)
  ) {
    return {
      kind: "ai_unavailable",
      headline: "El servicio de análisis no pudo completar la búsqueda",
      message:
        "El proveedor externo rechazó o no autorizó esta tarea. No depende de la configuración de su cuenta ni se resuelve desde Administración de la organización. Puede reintentar más tarde o contactar al administrador de la plataforma.",
    };
  }

  const stripped = raw
    .replace(/^El job no pudo completarse\.\s*(Causa:\s*)?/i, "")
    .replace(/^Se agotaron los reintentos permitidos\.\s*(Última causa:\s*)?/i, "")
    .replace(/^[A-Za-z]+Error:\s*/g, "")
    .trim();

  if (stripped && !/^(permanent_failure|temporary_failure|retry_exhausted)$/i.test(stripped)) {
    return {
      kind: "generic",
      headline: "No se pudo completar el descubrimiento",
      message: stripped.length > 280 ? `${stripped.slice(0, 277)}…` : stripped,
    };
  }

  return {
    kind: "generic",
    headline: "No se pudo completar el descubrimiento",
    message:
      "La última ejecución no se pudo completar. Puede reintentarla sin duplicar el expediente.",
  };
}

function discoveryJobStatusLabel(
  loading: boolean,
  running: boolean,
  jobStatus: string | null,
  hasArtifact: boolean,
): string {
  if (loading) return "Cargando…";
  if (running || jobStatus === "queued" || jobStatus === "running" || jobStatus === "retrying") {
    return productStatusLabel(jobStatus === "queued" ? "queued" : jobStatus === "retrying" ? "retrying" : "running");
  }
  if (jobStatus === "succeeded") return "Completado";
  if (jobStatus === "failed") return "Fallido";
  if (jobStatus === "cancelled") return "Cancelado";
  if (hasArtifact) return "Resultado disponible";
  return "Sin ejecución";
}

export function ActorDiscoveryPanel({ dossierId }: { dossierId: string }) {
  const [dossier, setDossier] = useState<BackendDossier | null>(null);
  const [artifact, setArtifact] = useState<MarketActorDiscoveryArtifact | null>(null);
  const [job, setJob] = useState<TenderSearchWizardJob | null>(null);
  const [loading, setLoading] = useState(true);
  const [running, setRunning] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [acceptResult, setAcceptResult] = useState<{ count: number } | null>(null);
  const [visible, setVisible] = useState(false);

  const output: MarketActorDiscoveryOutput | null = artifact?.output ?? null;
  const selectableCount = useMemo(
    () => (output?.candidates ?? []).filter(actorIsSelectable).length,
    [output],
  );

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const d = await api.dossiers.get(dossierId);
      setDossier(d);
      const show = hasDiscoveryIntent(d);
      setVisible(show);
      if (!show) {
        setJob(null);
        setArtifact(null);
        setRunning(false);
        return;
      }
      const latest = await api.marketActorDiscovery.latest(dossierId);
      setJob(latest.job);
      setArtifact(latest.artifact);
      const nonTerminal = latest.job && !terminal.has(latest.job.status);
      setRunning(Boolean(nonTerminal));
    } catch (reason) {
      setError(errorMessage(reason, "No se pudo cargar el descubrimiento de actores."));
    } finally {
      setLoading(false);
    }
  }, [dossierId]);

  useEffect(() => {
    const kickoff = window.setTimeout(() => void load(), 0);
    return () => window.clearTimeout(kickoff);
  }, [load]);

  // Poll while queued/running.
  useEffect(() => {
    if (!running || !visible) return;
    const timer = window.setInterval(() => {
      void (async () => {
        try {
          const latest = await api.marketActorDiscovery.latest(dossierId);
          setJob(latest.job);
          setArtifact(latest.artifact);
          const nonTerminal = latest.job && !terminal.has(latest.job.status);
          if (!nonTerminal) {
            setRunning(false);
            if (latest.job?.status === "succeeded") {
              toast.success("Descubrimiento listo", {
                description: "Revisa los actores sugeridos y acepta los que quieras materializar.",
              });
            }
          }
        } catch {
          // keep polling; surface on manual reload
        }
      })();
    }, 2500);
    return () => window.clearInterval(timer);
  }, [running, visible, dossierId]);

  async function runDiscovery() {
    setBusy(true);
    setError(null);
    setAcceptResult(null);
    try {
      const response = await api.marketActorDiscovery.run(
        { dossier_id: dossierId },
        retryIdempotencyKey(dossierId),
      );
      setJob(response.job);
      if (response.artifact) setArtifact(response.artifact);
      const nonTerminal = response.job && !terminal.has(response.job.status);
      setRunning(Boolean(nonTerminal));
      toast.message("Descubrimiento en curso", {
        description: "Oracle está buscando actores con el perfil del expediente.",
      });
    } catch (reason) {
      setError(errorMessage(reason, "No se pudo encolar el descubrimiento de actores."));
    } finally {
      setBusy(false);
    }
  }

  function onToggle(candidateId: string, next: boolean) {
    setSelected((prev) => {
      const copy = new Set(prev);
      if (next) copy.add(candidateId);
      else copy.delete(candidateId);
      return copy;
    });
  }

  async function acceptSelected() {
    if (!artifact) return;
    const selections = buildActorAcceptSelection(output, selected);
    if (selections.length === 0) {
      setError("Selecciona al menos un candidato con cita cerrada.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const result = await api.marketActorDiscovery.accept({
        dossier_id: dossierId,
        artifact_id: artifact.id,
        expected_version: artifact.version,
        selected: selections,
      });
      const actorsCount = result.actors_count ?? result.actors?.length ?? 0;
      setAcceptResult({ count: result.count });
      toast.success(
        actorsCount > 0 ? "Actores y fuentes materializados" : "Fuentes materializadas",
        {
          description:
            actorsCount > 0
              ? `${actorsCount} actor(es) y ${result.count} evidencia(s) en el expediente (solo la selección).`
              : `No se ha creado un Actor; ${result.count} evidencia(s) ligadas al expediente.`,
        },
      );
      setSelected(new Set());
      await load();
    } catch (reason) {
      if (reason instanceof ApiError && reason.problem.code === "identity_conflict") {
        setError(
          reason.problem.detail ||
            "Conflicto de identidad (RNSR/ROR/HAL/CORDIS incompatibles). No se ha escrito nada. Revisa el candidato y reintenta.",
        );
      } else {
        setError(errorMessage(reason, "No se pudieron materializar las fuentes seleccionadas."));
      }
    } finally {
      setBusy(false);
    }
  }

  if (!visible && !loading) {
    return null;
  }

  const jobStatus = job?.status ?? null;
  const statusLabel = discoveryJobStatusLabel(loading, running, jobStatus, Boolean(artifact));
  const failure =
    !loading && jobStatus === "failed" ? resolveActorDiscoveryFailure(job) : null;

  const showList =
    Boolean(artifact?.output) &&
    (jobStatus === "succeeded" || jobStatus === null || !running);
  const isIdle = !job && !artifact && !running;

  const discoveryIntent = dossier?.profile_config?.discovery_intent
    ? String(dossier.profile_config.discovery_intent)
    : "";
  const discoveryActorTypeRaw = dossier?.profile_config?.discovery_actor_type
    ? String(dossier.profile_config.discovery_actor_type)
    : "";
  const discoveryActorTypeLabel = discoveryActorTypeRaw
    ? productActorTypeLabel(discoveryActorTypeRaw)
    : "";

  const statusTone =
    jobStatus === "failed"
      ? "failed"
      : jobStatus === "succeeded"
        ? "succeeded"
        : running || jobStatus === "queued" || jobStatus === "running" || jobStatus === "retrying"
          ? "running"
          : "idle";

  return (
    <section
      className="vector-panel actor-discovery-panel"
      data-testid="actor-discovery-panel"
      aria-labelledby="actor-discovery-panel-title"
    >
      <header className="actor-discovery-panel-header">
        <div className="actor-discovery-panel-intro">
          <span className="section-kicker">Análisis de mercado</span>
          <h2 id="actor-discovery-panel-title">Actores a encontrar</h2>
          <p className="muted actor-discovery-panel-lede">
            Oracle propone organizaciones y grupos alineados con la intención del expediente.
            Al aceptar, se guardan las fuentes citables; no se crea un actor en la red hasta
            que usted lo confirme en el flujo de revisión.
          </p>
        </div>
        <div className="actor-discovery-panel-actions">
          <span
            className={`status-badge actor-discovery-status is-${statusTone}`}
            data-testid="actor-discovery-status"
            data-status={jobStatus ?? "idle"}
            aria-live="polite"
          >
            {statusLabel}
          </span>
          <AsyncActionButton
            className="vector-secondary"
            type="button"
            loading={busy || running}
            onClick={() => void runDiscovery()}
            data-testid="actor-discovery-retry"
          >
            <RefreshCw size={15} aria-hidden />
            {isIdle ? "Iniciar descubrimiento" : "Reintentar"}
          </AsyncActionButton>
          <button
            className="icon-button bordered"
            type="button"
            aria-label="Actualizar estado del descubrimiento"
            title="Actualizar estado del descubrimiento"
            data-testid="actor-discovery-reload"
            onClick={() => void load()}
          >
            <RefreshCw size={15} aria-hidden />
          </button>
        </div>
      </header>

      {discoveryIntent ? (
        <dl className="actor-discovery-meta" data-testid="actor-discovery-intent">
          <div className="actor-discovery-meta-item">
            <dt>Intención</dt>
            <dd>{discoveryIntent}</dd>
          </div>
          {discoveryActorTypeRaw ? (
            <div className="actor-discovery-meta-item">
              <dt>Tipo</dt>
              <dd data-testid="actor-discovery-type-label">{discoveryActorTypeLabel}</dd>
            </div>
          ) : null}
        </dl>
      ) : null}

      {error ? (
        <p className="auth-inline-error" role="alert" data-testid="actor-discovery-error">
          {error}
        </p>
      ) : null}

      {loading ? (
        <div className="work-loading" role="status" data-testid="actor-discovery-loading">
          <span className="auth-spinner" /> Cargando descubrimiento…
        </div>
      ) : null}

      {!loading && isIdle ? (
        <div className="work-empty" data-testid="actor-discovery-idle">
          <p>Aún no hay una ejecución de descubrimiento para este expediente.</p>
          <p className="muted">
            Pulse «Iniciar descubrimiento» para buscar con la intención y el tipo guardados.
          </p>
        </div>
      ) : null}

      {!loading && (running || jobStatus === "queued" || jobStatus === "running") ? (
        <div role="status" data-testid="actor-discovery-running" className="actor-discovery-running">
          <p>Descubrimiento en curso…</p>
          <p className="muted">Estado: {productStatusLabel(jobStatus)}</p>
        </div>
      ) : null}

      {failure ? (
        <div
          className="actor-discovery-failure"
          role="alert"
          data-testid="actor-discovery-failed"
          data-failure-kind={failure.kind}
        >
          <p className="actor-discovery-failure-headline">{failure.headline}</p>
          <p className="actor-discovery-failure-message">{failure.message}</p>
          {failure.actionHref && failure.actionLabel ? (
            <p className="actor-discovery-failure-action">
              <Link
                href={failure.actionHref}
                data-testid="actor-discovery-failure-action"
              >
                {failure.actionLabel}
              </Link>
            </p>
          ) : null}
        </div>
      ) : null}

      {!loading && showList && artifact ? (
        <div data-testid="actor-discovery-result">
          {selectableCount === 0 && (output?.candidates?.length ?? 0) === 0 ? (
            <div data-testid="actor-discovery-empty-result">
              <p className="muted">
                No hay actores publicables con cita cerrada en este resultado.
              </p>
            </div>
          ) : null}
          <ActorDiscoveryList
            output={output}
            selectedCandidateIds={selected}
            onToggle={onToggle}
          />
          <div className="actor-discovery-accept-bar">
            <AsyncActionButton
              className="vector-primary"
              type="button"
              loading={busy}
              disabled={selected.size === 0 || busy}
              onClick={() => void acceptSelected()}
              data-testid="actor-discovery-accept"
              aria-label="Materializar fuentes de los actores seleccionados"
              title="Materializar fuentes de los actores seleccionados"
            >
              Materializar fuentes seleccionadas
            </AsyncActionButton>
            {acceptResult ? (
              <p className="muted" data-testid="actor-discovery-accept-result">
                {acceptResult.count} evidencia(s) materializada(s). No se creó un Actor.
              </p>
            ) : null}
          </div>
        </div>
      ) : null}
    </section>
  );
}
