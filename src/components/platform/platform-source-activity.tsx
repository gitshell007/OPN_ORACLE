"use client";

import { ApiError, api } from "@oracle/api-client";
import { Newspaper, RefreshCw } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { toast } from "sonner";
import { AsyncActionButton } from "@/components/ui/async-action-button";

type SourceRow = {
  id: string;
  source_key: string;
  source_label: string;
  activity_date: string;
  status: "published" | "not_published" | "error" | string;
  item_count: number;
  section_counts?: Record<string, number>;
  official_identifier?: string | null;
  detail?: string;
  error_message?: string | null;
  checked_at?: string | null;
};

type SortKey = "activity_date" | "source_key" | "item_count" | "status" | "checked_at";

const STATUS_LABELS: Record<string, string> = {
  published: "Publicado",
  not_published: "Sin publicación",
  error: "Error",
};

function formatDate(value?: string | null): string {
  if (!value) return "—";
  const dayOnly = value.length <= 10;
  const date = new Date(dayOnly ? `${value}T12:00:00` : value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat(
    "es-ES",
    dayOnly ? { dateStyle: "medium" } : { dateStyle: "short", timeStyle: "short" },
  ).format(date);
}

export function PlatformSourceActivity() {
  const [items, setItems] = useState<SourceRow[]>([]);
  const [meta, setMeta] = useState({ total: 0, published_days: 0, item_count_sum: 0 });
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [source, setSource] = useState("");
  const [sort, setSort] = useState<{ key: SortKey; dir: "asc" | "desc" }>({
    key: "activity_date",
    dir: "desc",
  });
  const [cleared, setCleared] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const result = await api.platform.sourceActivity({
        source: source || undefined,
        q: query.trim() || undefined,
        sort: sort.key,
        direction: sort.dir,
      });
      setItems(result.items);
      setMeta({
        total: result.meta.total,
        published_days: result.meta.published_days,
        item_count_sum: result.meta.item_count_sum,
      });
      setCleared(false);
    } catch (reason) {
      setError(
        reason instanceof ApiError
          ? reason.problem.detail
          : "No se pudo cargar el registro de fuentes oficiales.",
      );
    } finally {
      setLoading(false);
    }
  }, [query, sort.dir, sort.key, source]);

  useEffect(() => {
    const kickoff = window.setTimeout(() => void load(), 0);
    return () => window.clearTimeout(kickoff);
  }, [load]);

  const visible = useMemo(() => (cleared ? [] : items), [cleared, items]);

  async function refresh() {
    setRefreshing(true);
    try {
      const result = await api.platform.refreshSourceActivity(14);
      toast.success("Comprobación actualizada", {
        description: `${result.refreshed} observaciones de BORME/BOE reescritas.`,
      });
      await load();
    } catch (reason) {
      toast.error(
        reason instanceof ApiError
          ? reason.problem.detail
          : "No se pudo refrescar el registro de fuentes.",
      );
    } finally {
      setRefreshing(false);
    }
  }

  function toggleSort(key: SortKey) {
    setSort((current) =>
      current.key === key
        ? { key, dir: current.dir === "asc" ? "desc" : "asc" }
        : { key, dir: key === "activity_date" || key === "checked_at" ? "desc" : "asc" },
    );
  }

  return (
    <div className="platform-page">
      <header className="admin-heading">
        <div>
          <p className="eyebrow">Plataforma · Superadmin</p>
          <h1>Fuentes oficiales</h1>
          <p>
            Registro diario de publicación de BORME y BOE (API de datos abiertos del BOE): si hubo
            sumario y cuántos registros de contenido aparecen cada día. La tarea programada lo
            actualiza por la mañana; también puedes forzar una comprobación.
          </p>
        </div>
        <AsyncActionButton
          className="vector-secondary"
          type="button"
          loading={refreshing}
          onClick={() => void refresh()}
        >
          <RefreshCw size={15} /> Actualizar ahora
        </AsyncActionButton>
      </header>

      <section className="platform-summary" aria-label="Resumen del periodo visible">
        <article>
          <span>Observaciones</span>
          <strong>{meta.total}</strong>
        </article>
        <article>
          <span>Días con publicación</span>
          <strong>{meta.published_days}</strong>
        </article>
        <article>
          <span>Registros contados</span>
          <strong>{meta.item_count_sum}</strong>
        </article>
      </section>

      <section className="admin-table-card">
        <header className="admin-card-heading">
          <div>
            <h2>
              <Newspaper size={16} aria-hidden="true" /> Actividad de ingesta oficial
            </h2>
            <p>
              BORME cuenta identificadores de sección A/B/C; BOE cuenta secciones A/B. Fin de semana
              y festivos suelen figurar como «Sin publicación».
            </p>
          </div>
        </header>

        <div className="audit-toolbar">
          <label className="search-field">
            <span className="sr-only">Buscar en el registro</span>
            <input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="Buscar por fuente, estado o detalle…"
            />
          </label>
          <label>
            <span className="sr-only">Fuente</span>
            <select
              aria-label="Filtrar por fuente"
              value={source}
              onChange={(event) => setSource(event.target.value)}
            >
              <option value="">Todas las fuentes</option>
              <option value="borme">BORME</option>
              <option value="boe">BOE</option>
            </select>
          </label>
          <div className="placeholder-actions">
            <button className="vector-secondary" type="button" onClick={() => setCleared(true)} disabled={!items.length || cleared}>
              Vaciar vista
            </button>
            <button
              className="vector-secondary"
              type="button"
              onClick={() => {
                setCleared(false);
                setQuery("");
                setSource("");
              }}
              disabled={!cleared && !query && !source}
            >
              Restaurar
            </button>
          </div>
        </div>

        {error && (
          <div className="inline-error" role="alert">
            {error}
            <button type="button" onClick={() => void load()}>
              Reintentar
            </button>
          </div>
        )}

        {loading ? (
          <p role="status">Cargando registro de fuentes…</p>
        ) : (
          <div className="table-scroll">
            <table className="admin-table">
              <thead>
                <tr>
                  {(
                    [
                      ["activity_date", "Fecha"],
                      ["source_key", "Fuente"],
                      ["status", "Estado"],
                      ["item_count", "Registros"],
                      ["checked_at", "Comprobado"],
                    ] as const
                  ).map(([key, label]) => (
                    <th key={key}>
                      <button type="button" onClick={() => toggleSort(key)}>
                        {label}
                        {sort.key === key ? (sort.dir === "asc" ? " ↑" : " ↓") : ""}
                      </button>
                    </th>
                  ))}
                  <th>Detalle</th>
                </tr>
              </thead>
              <tbody>
                {visible.map((item) => (
                  <tr key={item.id}>
                    <td>{formatDate(item.activity_date)}</td>
                    <td>
                      <strong>{item.source_label}</strong>
                      {item.official_identifier ? (
                        <small> {item.official_identifier}</small>
                      ) : null}
                    </td>
                    <td>
                      <span className={`status ${item.status}`}>
                        {STATUS_LABELS[item.status] ?? item.status}
                      </span>
                    </td>
                    <td>
                      <strong>{item.item_count}</strong>
                      {item.section_counts && Object.keys(item.section_counts).length > 0 ? (
                        <small>
                          {" "}
                          {Object.entries(item.section_counts)
                            .sort(([a], [b]) => a.localeCompare(b))
                            .map(([key, value]) => `${key}:${value}`)
                            .join(" · ")}
                        </small>
                      ) : null}
                    </td>
                    <td>{formatDate(item.checked_at)}</td>
                    <td>
                      {item.detail || "—"}
                      {item.error_message ? (
                        <small className="form-error"> {item.error_message}</small>
                      ) : null}
                    </td>
                  </tr>
                ))}
                {!visible.length && (
                  <tr>
                    <td colSpan={6}>
                      {cleared
                        ? "Vista vaciada. Usa Restaurar o Actualizar ahora."
                        : "Aún no hay observaciones. Pulsa «Actualizar ahora» para consultar BORME y BOE."}
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
}
