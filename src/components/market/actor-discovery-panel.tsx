"use client";

/**
 * G-19 · panel vivo de descubrimiento de actores en el expediente de Mercado.
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
import { RefreshCw, Sparkles } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { toast } from "sonner";
import {
  ActorDiscoveryList,
  actorIsSelectable,
  buildActorAcceptSelection,
} from "@/components/market/actor-discovery-list";
import { AsyncActionButton } from "@/components/ui/async-action-button";

const terminal = new Set(["succeeded", "failed", "cancelled"]);

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
              : `${result.count} evidencia(s) ligadas al expediente.`,
        },
      );
      setSelected(new Set());
      await load();
    } catch (reason) {
      setError(errorMessage(reason, "No se pudieron materializar las fuentes seleccionadas."));
    } finally {
      setBusy(false);
    }
  }

  if (!visible && !loading) {
    return null;
  }

  const jobStatus = job?.status ?? null;
  const statusLabel = loading
    ? "Cargando…"
    : running || jobStatus === "queued" || jobStatus === "running"
      ? jobStatus === "queued"
        ? "En cola"
        : "En ejecución"
      : jobStatus === "succeeded"
        ? "Completado"
        : jobStatus === "failed"
          ? "Fallido"
          : jobStatus === "cancelled"
            ? "Cancelado"
            : artifact
              ? "Resultado disponible"
              : "Sin ejecución";

  const showList =
    Boolean(artifact?.output) &&
    (jobStatus === "succeeded" || jobStatus === null || !running);
  const isIdle = !job && !artifact && !running;

  return (
    <section
      className="vector-panel actor-discovery-panel"
      data-testid="actor-discovery-panel"
      aria-labelledby="actor-discovery-panel-title"
    >
      <header className="actor-discovery-panel-header">
        <div>
          <span className="section-kicker">Descubrimiento G-19</span>
          <h2 id="actor-discovery-panel-title">Actores a encontrar</h2>
          <p className="muted">
            Intención y tipo salen del perfil del expediente (servidor). La aceptación
            materializa evidencias citables; no crea un Actor automáticamente.
          </p>
        </div>
        <div className="actor-discovery-panel-actions">
          <span
            className="status"
            data-testid="actor-discovery-status"
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
            <RefreshCw size={15} />
            {isIdle ? "Iniciar descubrimiento" : "Reintentar"}
          </AsyncActionButton>
          <button
            className="icon-button bordered"
            type="button"
            aria-label="Recargar estado"
            onClick={() => void load()}
          >
            <RefreshCw size={15} />
          </button>
        </div>
      </header>

      {dossier?.profile_config?.discovery_intent ? (
        <p className="actor-discovery-intent" data-testid="actor-discovery-intent">
          <Sparkles size={14} aria-hidden />{" "}
          <strong>Intención:</strong>{" "}
          {String(dossier.profile_config.discovery_intent)}
          {dossier.profile_config.discovery_actor_type ? (
            <>
              {" "}
              · <strong>Tipo:</strong> {String(dossier.profile_config.discovery_actor_type)}
            </>
          ) : null}
        </p>
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
            Pulsa «Iniciar descubrimiento» para encolar con el perfil guardado.
          </p>
        </div>
      ) : null}

      {!loading && (running || jobStatus === "queued" || jobStatus === "running") ? (
        <div role="status" data-testid="actor-discovery-running">
          <p>Descubrimiento en curso…</p>
          <p className="muted">Estado del job: {jobStatus}</p>
        </div>
      ) : null}

      {!loading && jobStatus === "failed" ? (
        <div role="alert" data-testid="actor-discovery-failed">
          <p>La última ejecución falló. Puedes reintentar sin duplicar el expediente.</p>
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
