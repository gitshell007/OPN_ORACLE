"use client";

import {
  ApiError,
  api,
  type DossierSignalEnvelope,
  type OracleActor,
  type OracleMeeting,
  type OracleOpportunity,
  type OracleRisk,
  type OracleTask,
} from "@oracle/api-client";
import { ChevronLeft, ChevronRight, RefreshCw, Search } from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { FormEvent, useCallback, useEffect, useState } from "react";
import { productStatusLabel } from "@/lib/product-copy";

export type GlobalResourceSection =
  | "signals"
  | "opportunities"
  | "risks"
  | "actors"
  | "meetings"
  | "tasks";

interface Row {
  id: string;
  title: string;
  dossierId?: string;
  dossierTitle?: string;
  status: string;
  kind: string;
  score?: number;
  date?: string | null;
  updatedAt?: string;
}

const sectionCopy: Record<GlobalResourceSection, { title: string; description: string }> = {
  signals: { title: "Señales", description: "Bandeja global de señales vinculadas a expedientes autorizados." },
  opportunities: { title: "Oportunidades", description: "Cartera agregada para priorizar el siguiente movimiento." },
  risks: { title: "Riesgos", description: "Riesgos que protegen el avance de los expedientes activos." },
  actors: { title: "Actores", description: "Directorio canónico limitado a contextos estratégicos accesibles." },
  meetings: { title: "Reuniones", description: "Agenda y seguimiento de reuniones entre expedientes." },
  tasks: { title: "Tareas", description: "Trabajo pendiente de la organización con origen y prioridad visibles." },
};

const sectionStatuses: Record<Exclude<GlobalResourceSection, "actors">, Array<[string, string]>> = {
  signals: [["new", "Nueva"], ["reviewed", "Revisada"], ["promoted", "Promovida"], ["dismissed", "Descartada"]],
  opportunities: [["identified", "Identificada"], ["qualified", "Cualificada"], ["pursuing", "En curso"], ["won", "Ganada"], ["lost", "Perdida"], ["dismissed", "Descartada"]],
  risks: [["open", "Abierto"], ["monitoring", "En vigilancia"], ["mitigated", "Mitigado"], ["accepted", "Aceptado"], ["closed", "Cerrado"]],
  meetings: [["planned", "Planificada"], ["completed", "Completada"], ["cancelled", "Cancelada"]],
  tasks: [["open", "Abierta"], ["in_progress", "En curso"], ["blocked", "Bloqueada"], ["done", "Completada"], ["cancelled", "Cancelada"]],
};

function dossierMap(items: { id: string; title: string }[]) {
  return new Map(items.map((item) => [item.id, item.title]));
}

function signalRow(item: DossierSignalEnvelope, dossiers: Map<string, string>): Row {
  return {
    id: item.link.id,
    title: item.signal.title || "Señal sin título",
    dossierId: item.link.dossier_id,
    dossierTitle: item.link.dossier_id ? dossiers.get(item.link.dossier_id) : undefined,
    status: item.link.status || "new",
    kind: item.signal.source_name || item.signal.source_type || "Señal",
    score: item.link.overall_score,
    date: item.signal.published_at,
    updatedAt: item.link.updated_at,
  };
}

function ownedRow(
  item: OracleOpportunity | OracleRisk | OracleMeeting | OracleTask,
  dossiers: Map<string, string>,
  section: Exclude<GlobalResourceSection, "signals" | "actors">,
): Row {
  const score = "overall_score" in item ? item.overall_score : undefined;
  const date = "deadline" in item ? item.deadline : "due_date" in item ? item.due_date : "scheduled_at" in item ? item.scheduled_at : undefined;
  const kind = section === "opportunities" && "opportunity_type" in item
    ? item.opportunity_type
    : section === "risks" && "category" in item
      ? item.category
      : section === "tasks" && "priority" in item
        ? item.priority
        : section.slice(0, -1);
  return {
    id: item.id,
    title: item.title || "Sin título",
    dossierId: item.dossier_id,
    dossierTitle: item.dossier_id ? dossiers.get(item.dossier_id) : undefined,
    status: item.status || "—",
    kind: kind || section.slice(0, -1),
    score,
    date,
    updatedAt: item.updated_at,
  };
}

export function GlobalResourceInventory({ section }: { section: GlobalResourceSection }) {
  const router = useRouter();
  const params = useSearchParams();
  const [search, setSearch] = useState(params.get("q") ?? "");
  const [rows, setRows] = useState<Row[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const page = Math.max(1, Number(params.get("page")) || 1);
  const status = params.get("status") ?? params.get("filter[status]") ?? "";
  const query = params.get("q") ?? "";
  const selectedId = params.get("selected");
  const copy = sectionCopy[section];

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    const input = {
      page,
      size: 25 as const,
      search: query,
      status: status || undefined,
      selectedIds: selectedId ? [selectedId] : undefined,
    };
    try {
      if (section === "signals") {
        const result = await api.dossierSignals.listGlobal(input);
        const dossiers = dossierMap(result.included.dossiers);
        setRows(result.data.map((item) => signalRow(item, dossiers)));
        setTotal(result.meta.total ?? result.data.length);
      } else if (section === "actors") {
        const result = await api.actors.list(input);
        setRows(result.data.map((item: OracleActor) => ({
          id: item.id,
          title: item.canonical_name || "Actor sin nombre",
          status: "Activo",
          kind: item.actor_type || "Actor",
          updatedAt: item.updated_at,
        })));
        setTotal(result.meta?.total ?? result.data.length);
      } else {
        const result = section === "opportunities"
          ? await api.opportunities.listGlobal(input)
          : section === "risks"
            ? await api.risks.listGlobal(input)
            : section === "meetings"
              ? await api.meetings.listGlobal(input)
              : await api.tasks.listGlobal(input);
        const dossiers = dossierMap(result.included.dossiers);
        setRows(result.data.map((item) => ownedRow(item, dossiers, section)));
        setTotal(result.meta.total ?? result.data.length);
      }
    } catch (reason) {
      setError(reason instanceof ApiError ? reason.problem.detail : `No se pudo cargar ${copy.title.toLowerCase()}.`);
    } finally {
      setLoading(false);
    }
  }, [copy.title, page, query, section, selectedId, status]);

  useEffect(() => {
    const kickoff = window.setTimeout(() => void load(), 0);
    return () => window.clearTimeout(kickoff);
  }, [load]);

  function update(next: Record<string, string | undefined>) {
    const value = new URLSearchParams(params.toString());
    for (const [key, item] of Object.entries(next)) {
      if (item) value.set(key, item);
      else value.delete(key);
      if (key === "status") value.delete("filter[status]");
    }
    router.replace(`/app/${section}?${value.toString()}`);
  }

  function submit(event: FormEvent) {
    event.preventDefault();
    update({ q: search.trim() || undefined, page: undefined });
  }

  const pages = Math.max(1, Math.ceil(total / 25));
  return (
    <div className="global-inventory">
      <section className="page-heading">
        <div><div className="eyebrow">Vista global</div><h1>{copy.title}</h1><p>{copy.description}</p></div>
        <button className="vector-secondary" onClick={() => void load()} disabled={loading}><RefreshCw size={15} /> Actualizar</button>
      </section>
      <form className="global-inventory-toolbar" role="search" onSubmit={submit}>
        <label><span className="sr-only">Buscar en {copy.title}</span><Search size={16} /><input value={search} onChange={(event) => setSearch(event.target.value)} placeholder={`Buscar ${copy.title.toLowerCase()}…`} /></label>
        {section !== "actors" && <select aria-label="Filtrar por estado" value={status} onChange={(event) => update({ status: event.target.value || undefined, page: undefined })}><option value="">Todos los estados</option>{sectionStatuses[section].map(([value, label]) => <option value={value} key={value}>{label}</option>)}</select>}
        <button className="vector-primary">Buscar</button>
        <span>{total} resultados</span>
      </form>
      {error && <div className="inline-error" role="alert">{error}<button onClick={() => void load()}>Reintentar</button></div>}
      <section className="global-inventory-panel" aria-busy={loading}>
        {loading ? <p className="global-inventory-state" role="status">Cargando {copy.title.toLowerCase()}…</p> : rows.length ? (
          <>
            <div className="table-scroll global-inventory-table"><table><thead><tr><th>Elemento</th><th>Expediente</th><th>Estado / tipo</th><th>Puntuación / fecha</th></tr></thead><tbody>{rows.map((row) => <tr key={row.id} className={row.id === selectedId ? "selected-resource" : undefined} aria-selected={row.id === selectedId}><td><strong>{row.title}</strong><small>{row.updatedAt ? `Actualizado ${new Date(row.updatedAt).toLocaleDateString("es-ES")}` : row.id}</small></td><td>{row.dossierId ? <Link href={`/app/dossiers/${row.dossierId}`}>{row.dossierTitle || "Abrir expediente"}</Link> : "Directorio global"}</td><td><span className="status">{productStatusLabel(row.status)}</span><small>{row.kind}</small></td><td>{row.score === undefined ? "—" : row.score}{row.date && <small>{new Date(row.date).toLocaleDateString("es-ES")}</small>}</td></tr>)}</tbody></table></div>
            <div className="global-inventory-cards">{rows.map((row) => <article key={row.id} className={row.id === selectedId ? "selected-resource" : undefined}><header><strong>{row.title}</strong><span className="status">{productStatusLabel(row.status)}</span></header><p>{row.kind}{row.score === undefined ? "" : ` · Puntuación ${row.score}`}</p>{row.dossierId && <Link href={`/app/dossiers/${row.dossierId}`}>{row.dossierTitle || "Abrir expediente"}</Link>}</article>)}</div>
          </>
        ) : <div className="global-inventory-state"><strong>No hay resultados</strong><p>Ajusta los filtros o revisa otro expediente.</p></div>}
      </section>
      <nav className="inventory-pagination" aria-label={`Páginas de ${copy.title}`}><button disabled={page <= 1} onClick={() => update({ page: String(page - 1) })}><ChevronLeft size={15} /> Anterior</button><span>Página {page} de {pages}</span><button disabled={page >= pages} onClick={() => update({ page: String(page + 1) })}>Siguiente <ChevronRight size={15} /></button></nav>
    </div>
  );
}
