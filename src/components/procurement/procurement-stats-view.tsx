"use client";

import { ApiError } from "@oracle/api-client";
import { BarChart3, RefreshCw } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";

export type ProcurementAnalyticsParams = {
  sample_size?: number;
  top_n?: number;
  sort?: "count" | "amount_sum";
  direction?: "asc" | "desc";
};

export type ProcurementAnalyticsPayload = {
  registry: Record<string, unknown>;
  sample: {
    requested: number;
    collected: number;
    provider_total?: number | null;
    scope: string;
    note?: string;
  };
  rankings: {
    sample_size?: number;
    with_amount?: number;
    amount_sum?: number;
    top_cpv: Array<{ key: string; label: string; count: number; amount_sum: number }>;
    top_buyers: Array<{ key: string; label: string; count: number; amount_sum: number }>;
    top_regions: Array<{ key: string; label: string; count: number; amount_sum: number }>;
    top_terms: Array<{ key: string; label: string; count: number; amount_sum: number }>;
    statuses: Array<{ key: string; label: string; count: number; amount_sum: number }>;
    amount_buckets: Array<{ key: string; label: string; count: number; amount_sum: number }>;
  };
  controls: {
    sample_size: number;
    top_n: number;
    sort_by: string;
    direction: string;
  };
};

type RankRow = {
  key: string;
  label: string;
  count: number;
  amount_sum: number;
};

function formatMoney(value: number): string {
  return new Intl.NumberFormat("es-ES", {
    style: "currency",
    currency: "EUR",
    maximumFractionDigits: 0,
  }).format(value);
}

function formatInt(value: number): string {
  return new Intl.NumberFormat("es-ES").format(value);
}

function RankTable({
  title,
  description,
  rows,
  sortBy,
}: {
  title: string;
  description: string;
  rows: RankRow[];
  sortBy: "count" | "amount_sum";
}) {
  const max = Math.max(1, ...rows.map((row) => (sortBy === "amount_sum" ? row.amount_sum : row.count)));
  return (
    <section className="admin-table-card">
      <header className="admin-card-heading">
        <div>
          <h2>{title}</h2>
          <p>{description}</p>
        </div>
      </header>
      <div className="table-scroll">
        <table className="admin-table">
          <thead>
            <tr>
              <th>#</th>
              <th>Concepto</th>
              <th>Convocatorias</th>
              <th>Importe muestra</th>
              <th>Peso</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row, index) => {
              const metric = sortBy === "amount_sum" ? row.amount_sum : row.count;
              const width = Math.max(4, Math.round((metric / max) * 100));
              return (
                <tr key={row.key}>
                  <td>{index + 1}</td>
                  <td>
                    <strong>{row.label}</strong>
                    {row.label !== row.key ? <small> {row.key}</small> : null}
                  </td>
                  <td>{formatInt(row.count)}</td>
                  <td>{row.amount_sum > 0 ? formatMoney(row.amount_sum) : "—"}</td>
                  <td>
                    <div className="platform-rank-bar" aria-hidden="true">
                      <span style={{ width: `${width}%` }} />
                    </div>
                  </td>
                </tr>
              );
            })}
            {!rows.length && (
              <tr>
                <td colSpan={5}>Sin datos en la muestra actual.</td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </section>
  );
}

export type ProcurementStatsViewProps = {
  loadAnalytics: (params: ProcurementAnalyticsParams) => Promise<ProcurementAnalyticsPayload>;
  eyebrow: string;
  description?: string;
};

export function ProcurementStatsView({
  loadAnalytics,
  eyebrow,
  description = "Vista de mercado PLACSP: inventario del registro Signal y rankings sobre una muestra acotada de licitaciones abiertas. Elige tamaño de muestra, top-N y criterio de ordenación.",
}: ProcurementStatsViewProps) {
  const [data, setData] = useState<ProcurementAnalyticsPayload | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [sampleSize, setSampleSize] = useState(300);
  const [topN, setTopN] = useState(25);
  const [sortBy, setSortBy] = useState<"count" | "amount_sum">("count");
  const [direction, setDirection] = useState<"asc" | "desc">("desc");
  const [activeTable, setActiveTable] = useState<
    "cpv" | "buyers" | "regions" | "buckets" | "terms" | "statuses"
  >("cpv");

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const result = await loadAnalytics({
        sample_size: sampleSize,
        top_n: topN,
        sort: sortBy,
        direction,
      });
      setData(result);
    } catch (reason) {
      setError(
        reason instanceof ApiError
          ? reason.problem.detail
          : "No se pudieron calcular las estadísticas de licitaciones.",
      );
    } finally {
      setLoading(false);
    }
  }, [direction, loadAnalytics, sampleSize, sortBy, topN]);

  useEffect(() => {
    const kickoff = window.setTimeout(() => void load(), 0);
    return () => window.clearTimeout(kickoff);
  }, [load]);

  const registry = data?.registry ?? {};
  const rankings = data?.rankings;
  const sample = data?.sample;

  const registryCards = useMemo(() => {
    const entries = Number(registry.entries ?? 0);
    const companies = Number(registry.distinct_companies ?? 0);
    const people = Number(registry.distinct_people ?? 0);
    const days = Number(registry.days_processed ?? 0);
    return [
      { label: "Entradas de registro", value: formatInt(entries) },
      { label: "Empresas distintas", value: formatInt(companies) },
      { label: "Personas distintas", value: formatInt(people) },
      { label: "Días procesados", value: formatInt(days) },
    ];
  }, [registry]);

  const activeRows: RankRow[] = useMemo(() => {
    if (!rankings) return [];
    switch (activeTable) {
      case "buyers":
        return rankings.top_buyers;
      case "regions":
        return rankings.top_regions;
      case "buckets":
        return rankings.amount_buckets;
      case "terms":
        return rankings.top_terms;
      case "statuses":
        return rankings.statuses;
      default:
        return rankings.top_cpv;
    }
  }, [activeTable, rankings]);

  const tableMeta: Record<typeof activeTable, { title: string; description: string }> = {
    cpv: {
      title: "CPV más convocados",
      description: "Códigos CPV más frecuentes en la muestra de licitaciones abiertas.",
    },
    buyers: {
      title: "Organismos que más convocan",
      description: "Compradores públicos con más expedientes abiertos en la muestra.",
    },
    regions: {
      title: "Regiones con más actividad",
      description: "Distribución territorial de las convocatorias muestreadas.",
    },
    buckets: {
      title: "Tramos de importe",
      description: "Cuántas licitaciones caen en cada banda de presupuesto estimado.",
    },
    terms: {
      title: "Términos frecuentes en títulos",
      description: "Palabras recurrentes (sin stopwords) en los títulos de la muestra.",
    },
    statuses: {
      title: "Estados canónicos",
      description: "Reparto de estados normalizados en la muestra.",
    },
  };

  return (
    <div className="platform-page">
      <header className="admin-heading">
        <div>
          <p className="eyebrow">{eyebrow}</p>
          <h1>Estadísticas de licitaciones</h1>
          <p>{description}</p>
        </div>
        <button className="vector-secondary" type="button" onClick={() => void load()} disabled={loading}>
          <RefreshCw size={15} /> {loading ? "Calculando…" : "Recalcular"}
        </button>
      </header>

      <section className="settings-section">
        <header>
          <h2>Controles de análisis</h2>
          <p>Los rankings se recalculan en servidor sobre la muestra de mercado PLACSP (no son datos privados del tenant).</p>
        </header>
        <div className="platform-analytics-controls">
          <label>
            <span>Muestra</span>
            <select
              value={sampleSize}
              onChange={(event) => setSampleSize(Number(event.target.value))}
              aria-label="Tamaño de la muestra"
            >
              {[100, 200, 300, 500, 750, 1000].map((value) => (
                <option key={value} value={value}>
                  {value} licitaciones
                </option>
              ))}
            </select>
          </label>
          <label>
            <span>Top N</span>
            <select
              value={topN}
              onChange={(event) => setTopN(Number(event.target.value))}
              aria-label="Número de filas del ranking"
            >
              {[10, 15, 25, 50, 75, 100].map((value) => (
                <option key={value} value={value}>
                  Top {value}
                </option>
              ))}
            </select>
          </label>
          <label>
            <span>Ordenar por</span>
            <select
              value={sortBy}
              onChange={(event) => setSortBy(event.target.value as "count" | "amount_sum")}
              aria-label="Criterio de ordenación"
            >
              <option value="count">Nº de convocatorias</option>
              <option value="amount_sum">Importe acumulado (muestra)</option>
            </select>
          </label>
          <label>
            <span>Dirección</span>
            <select
              value={direction}
              onChange={(event) => setDirection(event.target.value as "asc" | "desc")}
              aria-label="Dirección de ordenación"
            >
              <option value="desc">Mayor → menor</option>
              <option value="asc">Menor → mayor</option>
            </select>
          </label>
        </div>
      </section>

      {error && (
        <div className="inline-error" role="alert">
          {error}
          <button type="button" onClick={() => void load()}>
            Reintentar
          </button>
        </div>
      )}

      <section className="platform-summary" aria-label="Inventario del registro">
        {registryCards.map((card) => (
          <article key={card.label}>
            <span>{card.label}</span>
            <strong>{card.value}</strong>
          </article>
        ))}
        <article>
          <span>Muestra analizada</span>
          <strong>
            {sample ? `${formatInt(sample.collected)} / ${formatInt(sample.requested)}` : "—"}
          </strong>
        </article>
        <article>
          <span>Abiertas en proveedor</span>
          <strong>
            {sample?.provider_total != null ? formatInt(sample.provider_total) : "—"}
          </strong>
        </article>
      </section>

      {registry.error ? (
        <div className="inline-warning" role="status">
          Inventario Signal no disponible: {String(registry.error)}
        </div>
      ) : null}

      {sample?.note ? <p className="reporting-hint">{sample.note}</p> : null}

      {rankings ? (
        <section className="platform-summary" aria-label="Resumen de la muestra">
          <article>
            <span>Con importe</span>
            <strong>
              {formatInt(rankings.with_amount ?? 0)} / {formatInt(rankings.sample_size ?? 0)}
            </strong>
          </article>
          <article>
            <span>Suma importes muestra</span>
            <strong>{formatMoney(rankings.amount_sum ?? 0)}</strong>
          </article>
          <article>
            <span>CPV distintos</span>
            <strong>{formatInt(rankings.top_cpv.length)}</strong>
          </article>
          <article>
            <span>Organismos distintos (top)</span>
            <strong>{formatInt(rankings.top_buyers.length)}</strong>
          </article>
        </section>
      ) : null}

      <div className="audit-view-tabs" role="tablist" aria-label="Tablas de ranking">
        {(
          [
            ["cpv", "CPV"],
            ["buyers", "Organismos"],
            ["regions", "Regiones"],
            ["buckets", "Tramos €"],
            ["terms", "Términos"],
            ["statuses", "Estados"],
          ] as const
        ).map(([id, label]) => (
          <button
            key={id}
            type="button"
            role="tab"
            aria-selected={activeTable === id}
            className={activeTable === id ? "active" : ""}
            onClick={() => setActiveTable(id)}
          >
            {label}
          </button>
        ))}
      </div>

      {loading && !data ? (
        <p role="status">Cargando estadísticas de licitaciones…</p>
      ) : (
        <RankTable
          title={tableMeta[activeTable].title}
          description={tableMeta[activeTable].description}
          rows={activeRows}
          sortBy={activeTable === "buckets" || activeTable === "terms" || activeTable === "statuses" ? "count" : sortBy}
        />
      )}

      <section className="admin-form-card">
        <header>
          <div>
            <h2>
              <BarChart3 size={16} aria-hidden="true" /> Ideas de seguimiento
            </h2>
            <p>
              Usa estos recortes para orientar monitores Signal, perfiles de búsqueda y expedientes
              ofensivos.
            </p>
          </div>
        </header>
        <ul className="platform-insights-list">
          <li>
            <strong>Hot CPV:</strong> los códigos del top pueden alimentar watchlists y el wizard de
            búsqueda de licitaciones.
          </li>
          <li>
            <strong>Organismos recurrentes:</strong> candidatos a actores prioritarios o a
            inteligencia competitiva por comprador.
          </li>
          <li>
            <strong>Tramos de importe:</strong> detecta si el mercado abierto está concentrado en
            microcontratos o en lotes grandes.
          </li>
          <li>
            <strong>Regiones:</strong> prioriza presencia territorial o filtrado geográfico en
            monitores diarios.
          </li>
          <li>
            <strong>Términos de título:</strong> pistas de lenguaje de pliego para keywords de
            vigilancia (sin sustituir CPV).
          </li>
        </ul>
        <p className="reporting-hint">
          Limitación deliberada: la muestra es de licitaciones abiertas. El histórico de
          adjudicaciones se explora por empresa en el workspace de contratación, no como ranking
          global (Signal exige filtro de company/buyer en awards).
        </p>
      </section>
    </div>
  );
}
