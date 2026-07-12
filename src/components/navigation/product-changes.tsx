"use client";

import { ApiError, api, type OracleChange } from "@oracle/api-client";
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
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
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

  const pages = Math.max(1, Math.ceil(total / 10));
  return (
    <div className="product-changes">
      <section className="page-heading">
        <div><div className="eyebrow">Prioridad y trazabilidad</div><h1>Qué ha cambiado</h1><p>Transiciones semánticas recientes, acotadas y vinculadas a su expediente.</p></div>
        <button className="vector-secondary" disabled={loading} onClick={() => void load()}><RefreshCw size={15} /> Actualizar</button>
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
