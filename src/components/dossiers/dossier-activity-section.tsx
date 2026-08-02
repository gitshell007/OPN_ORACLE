"use client";

import {
  ApiError,
  api,
  type DossierActivityItem,
  type DossierActivityResponse,
} from "@oracle/api-client";
import { RefreshCw } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { PageHeader } from "@/components/ui/page-header";

const STATE_LABEL: Record<string, string> = {
  prepared: "Preparado",
  active: "Activo",
  paused: "Pausado",
  pending: "Pendiente",
  running: "En ejecución",
  retrying: "Reintentando",
  needs_attention: "Necesita atención",
  finished: "Finalizado",
};

const KIND_LABEL: Record<string, string> = {
  watchlist: "Vigilancia",
  signal_monitor: "Monitor Signal",
  procurement_watch: "Licitaciones",
  background_job: "Trabajo",
  surveillance_action: "Acción de vigilancia",
};

const ACTION_TYPE_LABEL: Record<string, string> = {
  news_mentions: "Noticias y menciones",
  official_publications: "Publicaciones oficiales",
  actor_tenders: "Licitaciones del actor",
  offering_tenders: "Licitaciones de la oferta",
  research_digest: "Digest de investigación",
  no_follow: "Sin seguimiento",
};

const INTENT_LABEL: Record<string, string> = {
  market: "Mercado",
  procurement: "Licitaciones y ayudas",
  research: "Investigación",
  "competitive-intelligence": "Inteligencia competitiva",
  custom: "Objetivo estratégico",
};

const PRIORITY_LABEL: Record<string, string> = {
  low: "Baja",
  medium: "Media",
  high: "Alta",
  critical: "Crítica",
};

function formatWhen(value?: string | null): string {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  return new Intl.DateTimeFormat("es-ES", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(date);
}

export function DossierActivitySection({ dossierId }: { dossierId: string }) {
  const [data, setData] = useState<DossierActivityResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [forbidden, setForbidden] = useState(false);
  const [alignmentBusy, setAlignmentBusy] = useState<string | null>(null);
  const [actionMessage, setActionMessage] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    setForbidden(false);
    try {
      const result = await api.dossierActivity.get(dossierId, { limit: 100, offset: 0 });
      setData(result);
    } catch (reason) {
      setData(null);
      if (reason instanceof ApiError && (reason.status === 403 || reason.status === 401)) {
        setForbidden(true);
        setError("No tienes permiso para ver la actividad de este expediente.");
      } else {
        setError(
          reason instanceof ApiError
            ? reason.problem.detail
            : "No se pudo cargar la actividad del expediente.",
        );
      }
    } finally {
      setLoading(false);
    }
  }, [dossierId]);

  async function resolveAlignment(
    item: DossierActivityItem,
    decision: "adopt" | "keep" | "retire",
  ) {
    const version = Number(item.target?.row_version ?? 0);
    const path =
      decision === "retire"
        ? `/api/v1/dossiers/${dossierId}/surveillance-actions/${item.id}/alignment/retire`
        : `/api/v1/dossiers/${dossierId}/surveillance-actions/${item.id}/alignment/${decision}`;
    setAlignmentBusy(`${item.id}:${decision}`);
    setActionMessage(null);
    try {
      const response = await fetch(path, {
        method: "POST",
        credentials: "same-origin",
        headers: {
          "Content-Type": "application/json",
          "Idempotency-Key": `align-${decision}-${item.id}-${crypto.randomUUID()}`,
          "If-Match": `W/"${version || 1}"`,
        },
      });
      if (response.status === 403 || response.status === 401) {
        setActionMessage("No tienes permiso para resolver el desalineamiento.");
        return;
      }
      if (!response.ok) {
        const body = (await response.json().catch(() => null)) as { detail?: string } | null;
        setActionMessage(body?.detail ?? "No se pudo aplicar la decisión.");
        return;
      }
      setActionMessage(
        decision === "adopt"
          ? "Alcance adoptado con la intención vigente."
          : decision === "keep"
            ? "Se conserva el alcance anterior (override)."
            : "Vigilancia retirada.",
      );
      await load();
    } catch {
      setActionMessage("Error de red al resolver la revisión de alcance.");
    } finally {
      setAlignmentBusy(null);
    }
  }

  useEffect(() => {
    const kickoff = window.setTimeout(() => void load(), 0);
    return () => window.clearTimeout(kickoff);
  }, [load]);

  if (loading) {
    return (
      <div className="dossier-loading" role="status" aria-label="Cargando actividad">
        <span />
        <span />
        <span />
      </div>
    );
  }

  if (error || !data) {
    return (
      <div className="not-found" role="alert">
        <strong>{forbidden ? "Acceso restringido" : "Actividad no disponible"}</strong>
        <p>{error ?? "Sin datos."}</p>
        {!forbidden ? (
          <button type="button" className="vector-secondary" onClick={() => void load()}>
            <RefreshCw size={15} /> Reintentar
          </button>
        ) : null}
      </div>
    );
  }

  const items: DossierActivityItem[] = data.items ?? [];

  return (
    <div className="dossier-section-page">
      <PageHeader
        eyebrow="Vigilancias y trabajos"
        title="Actividad del expediente"
        description="Vista consolidada de monitores, vigilancias, licitaciones y jobs. No activa recolección por sí sola."
        actions={
          <button type="button" className="vector-secondary" onClick={() => void load()}>
            <RefreshCw size={15} /> Actualizar
          </button>
        }
      />

      <section className="vector-panel" aria-label="Resumen de actividad">
        <dl className="placeholder-contract">
          <div>
            <dt>Total</dt>
            <dd>{data.summary.total}</dd>
          </div>
          {Object.entries(data.summary.by_state)
            .filter(([, count]) => count > 0)
            .map(([state, count]) => (
              <div key={state}>
                <dt>{STATE_LABEL[state] ?? state}</dt>
                <dd>{count}</dd>
              </div>
            ))}
        </dl>
        {data.intent ? (
          <div className="dossier-memory-summary">
            <div>
              <span className="section-kicker">Memoria aceptada · versión {data.intent.version}</span>
              <h2>{INTENT_LABEL[data.intent.schema_key] ?? data.intent.schema_key}</h2>
              <p>{data.intent.request_text}</p>
              <small>
                Contrato {data.intent.schema_key}.{data.intent.schema_version} · alcance aceptado y
                utilizado por Preguntar e Informe libre.
              </small>
            </div>
            <div>
              <h3>Qué necesita saber Oracle</h3>
              {data.requirements.length ? (
                <ul>
                  {data.requirements.map((item) => (
                    <li key={item.id}>
                      <strong>{item.question}</strong>
                      <span>{PRIORITY_LABEL[item.priority] ?? item.priority}</span>
                    </li>
                  ))}
                </ul>
              ) : (
                <p>Sin requisitos activos.</p>
              )}
            </div>
            <div>
              <h3>Oferta propia</h3>
              {data.offerings.length ? (
                <ul>{data.offerings.map((item) => <li key={item.id}>{item.name}</li>)}</ul>
              ) : (
                <p>No se ha definido una oferta para este expediente.</p>
              )}
            </div>
          </div>
        ) : (
          <p>Sin intención aceptada todavía. Define el objetivo desde Configuración antes de preguntar.</p>
        )}
      </section>

      {actionMessage ? (
        <p className="status" role="status">
          {actionMessage}
        </p>
      ) : null}

      <section className="vector-panel" aria-label="Listado de actividad">
        {items.length === 0 ? (
          <p>
            No hay vigilancias ni trabajos en este expediente. Puedes vincular un actor o competidor
            sin seguimiento y confirmar después cada tipo de vigilancia.
          </p>
        ) : (
          <div className="table-wrap">
            <table className="dense-table">
              <thead>
                <tr>
                  <th scope="col">Tipo</th>
                  <th scope="col">Título</th>
                  <th scope="col">Estado</th>
                  <th scope="col">Cadencia</th>
                  <th scope="col">Próximo / último</th>
                  <th scope="col">Error</th>
                  <th scope="col">Acciones</th>
                </tr>
              </thead>
              <tbody>
                {items.map((item) => {
                  const actionType =
                    typeof item.target?.action_type === "string"
                      ? item.target.action_type
                      : undefined;
                  const degraded = Boolean(item.target?.degraded);
                  return (
                    <tr key={`${item.kind}-${item.id}`}>
                      <td>
                        {KIND_LABEL[item.kind] ?? item.kind}
                        {actionType ? (
                          <>
                            <br />
                            <small>{ACTION_TYPE_LABEL[actionType] ?? actionType}</small>
                          </>
                        ) : null}
                      </td>
                      <td>
                        <strong>{item.title}</strong>
                        {item.alignment_state === "needs_review" ? (
                          <span className="status warning"> Revisión de alcance</span>
                        ) : null}
                        {degraded ? (
                          <span className="status warning"> Degradado</span>
                        ) : null}
                      </td>
                      <td>
                        <span
                          className={
                            item.product_state === "needs_attention"
                              ? "status danger"
                              : item.product_state === "active"
                                ? "status active"
                                : "status"
                          }
                        >
                          {STATE_LABEL[item.product_state] ?? item.product_state}
                        </span>
                      </td>
                      <td>{item.cadence ?? "—"}</td>
                      <td>
                        {formatWhen(item.next_run_at)}
                        <br />
                        <small>{formatWhen(item.last_success_at ?? item.last_attempt_at)}</small>
                      </td>
                      <td>
                        {item.last_error ?? "—"}
                        {degraded && item.target?.degraded_reason ? (
                          <>
                            <br />
                            <small>{String(item.target.degraded_reason)}</small>
                          </>
                        ) : null}
                      </td>
                      <td>
                        {item.kind === "surveillance_action" &&
                        item.alignment_state === "needs_review" ? (
                          <div className="inline-actions" role="group" aria-label="Revisión de alcance">
                            <button
                              type="button"
                              className="vector-primary"
                              disabled={alignmentBusy === `${item.id}:adopt`}
                              onClick={() => void resolveAlignment(item, "adopt")}
                            >
                              Adoptar
                            </button>
                            <button
                              type="button"
                              className="vector-secondary"
                              disabled={alignmentBusy === `${item.id}:keep`}
                              onClick={() => void resolveAlignment(item, "keep")}
                            >
                              Conservar
                            </button>
                            <button
                              type="button"
                              className="vector-secondary"
                              disabled={alignmentBusy === `${item.id}:retire`}
                              onClick={() => void resolveAlignment(item, "retire")}
                            >
                              Retirar
                            </button>
                          </div>
                        ) : (
                          "—"
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
}
