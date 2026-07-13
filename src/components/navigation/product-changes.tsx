"use client";

import { ApiError, api, type OracleChange, type WeeklyChangeDigest } from "@oracle/api-client";
import { ArrowRight, History, RefreshCw, Search } from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { FormEvent, useCallback, useEffect, useState } from "react";

const RESOURCE_LABELS: Record<string, string> = {
  signal: "Señal",
  opportunity: "Oportunidad",
  risk: "Riesgo",
  task: "Tarea",
  meeting: "Reunión",
  decision: "Decisión",
};
const STATUS_LABELS: Record<string, string> = {
  new: "nuevo",
  reviewed: "revisado",
  promoted: "promovido",
  dismissed: "descartado",
  identified: "identificado",
  qualified: "cualificado",
  pursuing: "en curso",
  open: "abierto",
  in_progress: "en curso",
  monitoring: "en vigilancia",
  done: "completado",
  completed: "completado",
  planned: "planificado",
};

type WeeklyChangeOutput = {
  period_start?: string;
  period_end?: string;
  coverage_summary?: string;
  changes?: Array<{
    area?: string;
    change?: string;
    significance?: string;
    previous_state?: string;
    current_state?: string;
  }>;
  no_change_areas?: string[];
};

function digestOutput(digest: WeeklyChangeDigest | null): WeeklyChangeOutput | null {
  const output = digest?.digest?.output;
  return output && typeof output === "object" ? (output as WeeklyChangeOutput) : null;
}

function jobInProgress(digest: WeeklyChangeDigest | null) {
  return ["queued", "running", "retrying"].includes(String(digest?.job?.status ?? ""));
}

export function ProductChanges() {
  const router = useRouter();
  const params = useSearchParams();
  const page = Math.max(1, Number(params.get("page")) || 1);
  const type = params.get("type") ?? "";
  const since = params.get("since") ?? "";
  const query = params.get("q") ?? "";
  const [search, setSearch] = useState(query);
  const [items, setItems] = useState<OracleChange[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [digest, setDigest] = useState<WeeklyChangeDigest | null>(null);
  const [digestLoading, setDigestLoading] = useState(true);
  const [digestRefreshing, setDigestRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const output = digestOutput(digest);
  const digestBusy = digestRefreshing || jobInProgress(digest);

  const load = useCallback(async () => {
    setLoading(true);
    setDigestLoading(true);
    try {
      const result = await api.changes.list({ page, size: 10, type: type || undefined, since: since || undefined, search: query || undefined });
      setItems(result.data);
      setTotal(result.meta.total);
      setError(null);
    } catch (reason) {
      setError(reason instanceof ApiError ? reason.problem.detail : "No se pudieron cargar los cambios.");
    } finally {
      setLoading(false);
    }
    try {
      setDigest(await api.changes.digest());
    } catch {
      setDigest(null);
    } finally {
      setDigestLoading(false);
    }
  }, [page, query, since, type]);

  useEffect(() => {
    const kickoff = window.setTimeout(() => void load(), 0);
    return () => window.clearTimeout(kickoff);
  }, [load]);

  function update(next: Record<string, string | undefined>) {
    const value = new URLSearchParams(params.toString());
    for (const [key, item] of Object.entries(next)) {
      if (item) value.set(key, item);
      else value.delete(key);
    }
    router.replace(`/app/changes?${value.toString()}`);
  }

  function submit(event: FormEvent) {
    event.preventDefault();
    update({ q: search.trim() || undefined, page: undefined });
  }

  async function refreshDigest() {
    setDigestRefreshing(true);
    try {
      const next = await api.changes.refreshDigest({
        idempotencyKey: crypto.randomUUID(),
      });
      setDigest(next);
      window.setTimeout(() => void api.changes.digest().then(setDigest).catch(() => undefined), 3500);
    } catch (reason) {
      setError(reason instanceof ApiError ? reason.problem.detail : "No se pudo solicitar el digest estratégico.");
    } finally {
      setDigestRefreshing(false);
    }
  }

  const pages = Math.max(1, Math.ceil(total / 10));
  return (
    <div className="product-changes">
      <section className="page-heading">
        <div><div className="eyebrow">Prioridad y trazabilidad</div><h1>Qué ha cambiado</h1><p>Transiciones semánticas recientes, acotadas y vinculadas a su expediente.</p></div>
        <button className="vector-secondary" disabled={loading} onClick={() => void load()}><RefreshCw size={15} /> Actualizar</button>
      </section>
      <section className="changes-digest vector-panel" aria-busy={digestLoading || digestBusy}>
        <header>
          <div>
            <span className="section-kicker">Digest estratégico</span>
            <h2>Resumen semanal de cambios</h2>
            <p>{digest?.dossier_title ? `Expediente: ${digest.dossier_title}` : "Se prepara sobre el expediente con actividad reciente."}</p>
          </div>
          <button className="vector-secondary" disabled={digestLoading || digestBusy} onClick={() => void refreshDigest()}><RefreshCw size={15} /> {digestBusy ? "Preparando…" : "Actualizar digest"}</button>
        </header>
        {digestLoading ? (
          <p role="status">Consultando el último digest…</p>
        ) : output ? (
          <div className="changes-digest-content">
            <p>{output.coverage_summary || "Digest generado sin comentario de cobertura."}</p>
            <div className="changes-digest-grid">
              {(output.changes ?? []).slice(0, 4).map((item, index) => (
                <article key={`${item.area}-${index}`}>
                  <span>{item.significance ? item.significance.toUpperCase() : "CAMBIO"}</span>
                  <h3>{item.area || "Área estratégica"}</h3>
                  <p>{item.change}</p>
                  <small>{item.previous_state} → {item.current_state}</small>
                </article>
              ))}
            </div>
            {!(output.changes ?? []).length && <p>No se han detectado cambios estratégicos materiales en el periodo.</p>}
          </div>
        ) : (
          <div className="global-inventory-state">
            <strong>Aún no hay digest estratégico</strong>
            <p>Solicita la primera generación y la pantalla conservará la versión anterior mientras se recalcula.</p>
          </div>
        )}
      </section>
      <form className="changes-filters" role="search" onSubmit={submit}>
        <label><span className="sr-only">Buscar cambios</span><Search size={16} /><input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Buscar por motivo o expediente…" /></label>
        <select aria-label="Tipo de recurso" value={type} onChange={(event) => update({ type: event.target.value || undefined, page: undefined })}><option value="">Todos los tipos</option><option value="signal">Señales</option><option value="opportunity">Oportunidades</option><option value="risk">Riesgos</option><option value="task">Tareas</option><option value="meeting">Reuniones</option></select>
        <label className="changes-date"><span>Desde</span><input type="date" value={since.slice(0, 10)} onChange={(event) => update({ since: event.target.value || undefined, page: undefined })} /></label>
        <button className="vector-primary">Buscar</button>
      </form>
      {error && <div className="inline-error" role="alert">{error}<button onClick={() => void load()}>Reintentar</button></div>}
      <section className="changes-list" aria-busy={loading}>
        {loading ? <p role="status">Priorizando cambios…</p> : items.length ? items.map((item) => (
          <article key={item.id}>
            <div className="change-icon"><History size={17} aria-hidden="true" /></div>
            <div className="change-content">
              <header><span className="change-fact">Hecho registrado</span><time dateTime={item.occurred_at}>{new Date(item.occurred_at).toLocaleString("es-ES")}</time></header>
              <h2>{item.dossier_title}</h2>
              <p><strong>{RESOURCE_LABELS[item.resource_type] ?? item.resource_type}</strong> cambió de <span className="status">{STATUS_LABELS[item.from_status] ?? item.from_status}</span> a <span className="status">{STATUS_LABELS[item.to_status] ?? item.to_status}</span>.</p>
              <blockquote>{item.reason || "Transición registrada sin motivo adicional."}</blockquote>
              <footer><span>Cambio registrado en el historial</span><Link href={item.href}>Ver detalle <ArrowRight size={14} /></Link></footer>
            </div>
          </article>
        )) : <div className="global-inventory-state"><strong>No hay cambios para este periodo</strong><p>Amplía la fecha o ajusta los filtros.</p></div>}
      </section>
      <div className="changes-footer"><p>Marcar como revisado se habilitará cuando exista un registro durable; no se simula localmente.</p><nav aria-label="Páginas de cambios"><button disabled={page <= 1} onClick={() => update({ page: String(page - 1) })}>Anterior</button><span>{page} / {pages}</span><button disabled={page >= pages} onClick={() => update({ page: String(page + 1) })}>Siguiente</button></nav></div>
    </div>
  );
}
