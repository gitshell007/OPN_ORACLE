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

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const result = await api.dossierActivity.get(dossierId, { limit: 100, offset: 0 });
      setData(result);
    } catch (reason) {
      setData(null);
      setError(
        reason instanceof ApiError
          ? reason.problem.detail
          : "No se pudo cargar la actividad del expediente.",
      );
    } finally {
      setLoading(false);
    }
  }, [dossierId]);

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
        <strong>Actividad no disponible</strong>
        <p>{error ?? "Sin datos."}</p>
        <button type="button" className="vector-secondary" onClick={() => void load()}>
          <RefreshCw size={15} /> Reintentar
        </button>
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

      <section className="vector-panel" aria-label="Listado de actividad">
        {items.length === 0 ? (
          <p>No hay vigilancias ni trabajos en este expediente.</p>
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
                </tr>
              </thead>
              <tbody>
                {items.map((item) => (
                  <tr key={`${item.kind}-${item.id}`}>
                    <td>{KIND_LABEL[item.kind] ?? item.kind}</td>
                    <td>
                      <strong>{item.title}</strong>
                      {item.alignment_state === "needs_review" ? (
                        <span className="status warning"> Revisión de alcance</span>
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
                    <td>{item.last_error ?? "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
}
