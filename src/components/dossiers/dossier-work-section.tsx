"use client";

import * as Dialog from "@radix-ui/react-dialog";
import {
  ApiError,
  api,
  type DossierResourcePage,
  type OracleActor,
  type OracleBriefing,
  type OracleDecision,
  type OracleDossierActor,
  type OracleMeeting,
  type OracleTask,
} from "@oracle/api-client";
import {
  ArrowRight,
  CheckCircle2,
  FileCheck2,
  Plus,
  RefreshCw,
  Search,
  UsersRound,
  X,
} from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";
import { toast } from "sonner";
import { PermissionGate } from "@/components/auth/auth-boundary";
import { productLinkedResourceLabel } from "@/lib/product-copy";
import { DossierActorCandidates } from "./dossier-actor-candidates";

export type DossierWorkKind = "actors" | "meetings" | "tasks" | "decisions";
type ActorType = "person" | "organization" | "institution" | "program" | "other";
type RawResource = OracleDossierActor | OracleMeeting | OracleTask | OracleDecision;

interface WorkRow {
  id: string;
  title: string;
  status: string;
  detail: string;
  secondary: string;
  version: number;
  updatedAt?: string;
  raw: RawResource;
  actor?: OracleActor;
  labels?: string[];
}

const ACTOR_TYPE_LABELS: Record<string, string> = {
  person: "Persona",
  organization: "Empresa u organización",
  institution: "Organismo o institución",
  program: "Programa o iniciativa",
  other: "Otro",
};

const COPY = {
  actors: {
    eyebrow: "Mapa relacional",
    title: "Actores",
    description: "Personas, organizaciones e instituciones vinculadas al contexto estratégico.",
    create: "Nuevo actor",
    permission: "actor.write",
  },
  meetings: {
    eyebrow: "Preparación y seguimiento",
    title: "Reuniones",
    description: "Agenda, objetivo, estado y preparación trazable de cada encuentro.",
    create: "Nueva reunión",
    permission: "meeting.write",
  },
  tasks: {
    eyebrow: "Trabajo operativo",
    title: "Tareas",
    description: "Siguientes acciones priorizadas y conectadas con el expediente.",
    create: "Nueva tarea",
    permission: "task.write",
  },
  decisions: {
    eyebrow: "Trazabilidad humana",
    title: "Decisiones",
    description: "Propuestas y decisiones explícitas, separadas de hechos e inferencias.",
    create: "Registrar propuesta",
    permission: "task.write",
  },
} as const;

const LABELS: Record<string, string> = {
  linked: "Vinculado",
  planned: "Planificada",
  completed: "Completada",
  cancelled: "Cancelada",
  open: "Abierta",
  in_progress: "En curso",
  blocked: "Bloqueada",
  done: "Completada",
  proposed: "Propuesta",
  approved: "Aprobada",
  rejected: "Rechazada",
  superseded: "Sustituida",
};

const TRANSITIONS: Record<DossierWorkKind, Record<string, string[]>> = {
  actors: {},
  meetings: { planned: ["completed", "cancelled"] },
  tasks: {
    open: ["in_progress", "blocked", "done", "cancelled"],
    in_progress: ["blocked", "done", "cancelled"],
    blocked: ["in_progress", "done", "cancelled"],
  },
  decisions: {
    proposed: ["approved", "rejected"],
    approved: ["superseded"],
  },
};

function formatDate(value?: string | null) {
  if (!value) return "Sin fecha registrada";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "Sin fecha registrada";
  return new Intl.DateTimeFormat("es-ES", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(date);
}

function message(reason: unknown, fallback: string) {
  return reason instanceof ApiError ? reason.problem.detail : fallback;
}

function actorConfidence(link: OracleDossierActor): number | null {
  const value = link.score_details?.confidence;
  return typeof value === "number" ? value : null;
}

function normalize(
  kind: DossierWorkKind,
  item: RawResource,
  actors: Map<string, OracleActor>,
): WorkRow {
  if (kind === "actors") {
    const link = item as OracleDossierActor;
    const actor = link.actor_id ? actors.get(link.actor_id) : undefined;
    const confidence = actorConfidence(link);
    const metadata = actor?.metadata as Record<string, unknown> | undefined;
    const labels = Array.isArray(metadata?.tags)
      ? metadata.tags.map((value) => String(value)).filter(Boolean)
      : [];
    return {
      id: link.id,
      title: actor?.canonical_name || "Actor sin nombre disponible",
      status: "linked",
      detail: (link.roles ?? []).join(", ") || "Rol pendiente de documentar",
      secondary: `${ACTOR_TYPE_LABELS[actor?.actor_type ?? "other"] ?? "Otro"} · Influencia ${link.influence ?? 0} · Relevancia ${link.relevance_to_dossier ?? 0}${confidence === null ? "" : ` · Confianza ${confidence} %`}`,
      version: link.version ?? 1,
      updatedAt: link.updated_at,
      raw: link,
      actor,
      labels,
    };
  }
  if (kind === "meetings") {
    const row = item as OracleMeeting;
    return {
      id: row.id,
      title: row.title || "Reunión sin título",
      status: row.status || "planned",
      detail: row.objective || "Objetivo pendiente de documentar",
      secondary: row.scheduled_at ? formatDate(row.scheduled_at) : "Fecha pendiente",
      version: row.version ?? 1,
      updatedAt: row.updated_at,
      raw: row,
    };
  }
  if (kind === "tasks") {
    const row = item as OracleTask;
    return {
      id: row.id,
      title: row.title || "Tarea sin título",
      status: row.status || "open",
      detail: row.linked_resource_type
        ? `Vinculada a una ${productLinkedResourceLabel(row.linked_resource_type)}`
        : "Acción manual del expediente",
      secondary: `${row.priority === "high" ? "Prioridad alta" : row.priority === "low" ? "Prioridad baja" : "Prioridad media"} · ${row.due_date ? formatDate(row.due_date) : "Sin vencimiento"}`,
      version: row.version ?? 1,
      updatedAt: row.updated_at,
      raw: row,
    };
  }
  const row = item as OracleDecision;
  return {
    id: row.id,
    title: row.title || "Decisión sin título",
    status: row.status || "proposed",
    detail: row.rationale || "Justificación pendiente de documentar",
    secondary: row.decided_at ? `Decidida ${formatDate(row.decided_at)}` : "Registro humano pendiente",
    version: row.version ?? 1,
    updatedAt: row.updated_at,
    raw: row,
  };
}

export function DossierWorkSection({ dossierId, kind }: { dossierId: string; kind: DossierWorkKind }) {
  const copy = COPY[kind];
  const pathname = usePathname();
  const router = useRouter();
  const searchParams = useSearchParams();
  const [rows, setRows] = useState<WorkRow[]>([]);
  const [meta, setMeta] = useState<DossierResourcePage<RawResource>["meta"]>();
  const [actorCatalog, setActorCatalog] = useState<OracleActor[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [appliedQuery, setAppliedQuery] = useState("");
  const [status, setStatus] = useState("");
  const [page, setPage] = useState(1);
  const [createOpen, setCreateOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [title, setTitle] = useState("");
  const [detail, setDetail] = useState("");
  const [scheduledAt, setScheduledAt] = useState("");
  const [participantIds, setParticipantIds] = useState<string[]>([]);
  const [priority, setPriority] = useState("medium");
  const [actorId, setActorId] = useState("");
  const [actorView, setActorView] = useState<"linked" | "candidates">(
    searchParams.get("view") === "candidates" ? "candidates" : "linked",
  );
  const [actorCreateMode, setActorCreateMode] = useState<"new" | "existing">("new");
  const [actorType, setActorType] = useState<ActorType>("organization");
  const [actorTags, setActorTags] = useState("");
  const [createError, setCreateError] = useState<string | null>(null);
  const [briefings, setBriefings] = useState<OracleBriefing[]>([]);
  const [briefingsLoading, setBriefingsLoading] = useState(false);
  const [briefingRunning, setBriefingRunning] = useState(false);
  const requestedSelection = searchParams.get("selected");

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      if (kind === "actors") {
        const links = await api.actors.listDossier(dossierId, { page: 1, size: 100 });
        const selectedLinks = requestedSelection && !links.data.some((link) => link.id === requestedSelection)
          ? await api.actors.listDossier(dossierId, { page: 1, size: 10, selectedIds: [requestedSelection] })
          : { data: [] as OracleDossierActor[] };
        const linkRows = [...links.data, ...selectedLinks.data];
        const actorIds = [...new Set(linkRows.map((link) => link.actor_id).filter(Boolean))] as string[];
        const actors = actorIds.length
          ? await api.actors.list({
              page: 1,
              size: 100,
              sort: "canonical_name",
              selectedIds: actorIds,
              search: appliedQuery || undefined,
            })
          : { data: [], meta: { page: 1, size: 100, total: 0 } };
        const map = new Map(actors.data.map((actor) => [actor.id, actor]));
        setRows(linkRows.filter((item) => item.actor_id && map.has(item.actor_id)).map((item) => normalize(kind, item, map)));
        setMeta({ page: 1, size: 100, total: actors.meta?.total ?? 0 });
      } else {
        const input = { page, size: 25 as const, status: status || undefined, search: appliedQuery || undefined };
        const result = kind === "meetings"
          ? await api.meetings.list(dossierId, input)
          : kind === "tasks"
            ? await api.tasks.list(dossierId, input)
            : await api.decisions.list(dossierId, input);
        let resourceRows = result.data;
        if (requestedSelection && !resourceRows.some((item) => item.id === requestedSelection)) {
          const selectedResult = kind === "meetings"
            ? await api.meetings.list(dossierId, { page: 1, size: 10, selectedIds: [requestedSelection] })
            : kind === "tasks"
              ? await api.tasks.list(dossierId, { page: 1, size: 10, selectedIds: [requestedSelection] })
              : await api.decisions.list(dossierId, { page: 1, size: 10, selectedIds: [requestedSelection] });
          resourceRows = [...resourceRows, ...selectedResult.data];
        }
        setRows(resourceRows.map((item) => normalize(kind, item, new Map())));
        setMeta(result.meta);
      }
    } catch (reason) {
      setRows([]);
      setMeta(undefined);
      setError(message(reason, `No se pudieron cargar ${copy.title.toLowerCase()}.`));
    } finally {
      setLoading(false);
    }
  }, [appliedQuery, copy.title, dossierId, kind, page, requestedSelection, status]);

  useEffect(() => {
    const kickoff = window.setTimeout(() => void load(), 0);
    return () => window.clearTimeout(kickoff);
  }, [load]);

  const selected = useMemo(
    () => rows.find((row) => row.id === searchParams.get("selected")) ?? null,
    [rows, searchParams],
  );

  useEffect(() => {
    if (kind !== "meetings" || !selected) {
      const clear = window.setTimeout(() => setBriefings([]), 0);
      return () => window.clearTimeout(clear);
    }
    const kickoff = window.setTimeout(() => {
      setBriefingsLoading(true);
      void api.meetings.briefings(selected.id)
        .then((result) => setBriefings(result.data))
        .catch(() => setBriefings([]))
        .finally(() => setBriefingsLoading(false));
    }, 0);
    return () => window.clearTimeout(kickoff);
  }, [kind, selected]);

  const transitions = selected ? TRANSITIONS[kind][selected.status] ?? [] : [];
  const pages = kind === "actors" ? 1 : Math.max(1, Math.ceil((meta?.total ?? 0) / 25));

  function applyFilters(event: FormEvent) {
    event.preventDefault();
    setPage(1);
    setAppliedQuery(query.trim());
  }

  function closeDetail() {
    router.replace(pathname, { scroll: false });
  }

  function resetCreate() {
    setTitle("");
    setDetail("");
    setScheduledAt("");
    setParticipantIds([]);
    setPriority("medium");
    setActorId("");
    setActorCreateMode("new");
    setActorType("organization");
    setActorTags("");
    setCreateError(null);
  }

  async function openCreate() {
    setCreateOpen(true);
    setCreateError(null);
    if (!["actors", "meetings"].includes(kind) || actorCatalog.length) return;
    try {
      setActorCatalog((await api.actors.list({ page: 1, size: 100, sort: "canonical_name" })).data);
    } catch (reason) {
      setError(message(reason, "No se pudo cargar el catálogo de actores."));
    }
  }

  async function create(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setCreateError(null);
    try {
      if (kind === "actors") {
        const roles = detail.trim() ? detail.split(",").map((role) => role.trim()).filter(Boolean) : [];
        const tags = actorTags.trim() ? actorTags.split(",").map((tag) => tag.trim()).filter(Boolean) : [];
        await api.actors.attach(dossierId, actorCreateMode === "existing" ? {
          actor_id: actorId,
          roles,
          influence: 50,
          relevance_to_dossier: 50,
        } : {
          canonical_name: title.trim(),
          actor_type: actorType,
          tags,
          provenance: { source: "manual" },
          roles: detail.trim() ? detail.split(",").map((role) => role.trim()).filter(Boolean) : [],
          influence: 50,
          relevance_to_dossier: 50,
        });
      } else if (kind === "meetings") {
        await api.meetings.create(dossierId, {
          title: title.trim(),
          objective: detail.trim(),
          ...(scheduledAt ? { scheduled_at: new Date(scheduledAt).toISOString() } : {}),
          ...(participantIds.length ? { actor_ids: participantIds } : {}),
        });
      } else if (kind === "tasks") {
        await api.tasks.create(dossierId, { title: title.trim(), priority });
      } else {
        await api.decisions.create(dossierId, { title: title.trim(), rationale: detail.trim() });
      }
      toast.success(kind === "actors" ? "Actor vinculado" : "Registro creado");
      setCreateOpen(false);
      resetCreate();
      await load();
    } catch (reason) {
      setCreateError(message(reason, "No se pudo crear el registro."));
    } finally {
      setBusy(false);
    }
  }

  async function transition(nextStatus: string) {
    if (!selected) return;
    setBusy(true);
    setError(null);
    try {
      if (kind === "meetings") {
        await api.meetings.update(selected.id, { status: nextStatus, version: selected.version }, selected.version);
      } else if (kind === "tasks") {
        await api.tasks.update(selected.id, { status: nextStatus, version: selected.version }, selected.version);
      } else if (kind === "decisions") {
        await api.decisions.update(selected.id, { status: nextStatus, version: selected.version }, selected.version);
      }
      toast.success(`Estado actualizado a ${LABELS[nextStatus] ?? nextStatus}`);
      closeDetail();
      await load();
    } catch (reason) {
      setError(message(reason, "No se pudo actualizar el estado."));
    } finally {
      setBusy(false);
    }
  }

  async function reinforceActorRelevance() {
    if (!selected || kind !== "actors") return;
    const link = selected.raw as OracleDossierActor;
    setBusy(true);
    setError(null);
    try {
      await api.actors.updateLink(
        link.id,
        {
          influence: link.influence ?? 0,
          relevance_to_dossier: Math.min(100, (link.relevance_to_dossier ?? 0) + 10),
          version: selected.version,
        },
        selected.version,
      );
      toast.success("Relevancia actualizada");
      closeDetail();
      await load();
    } catch (reason) {
      setError(message(reason, "No se pudo actualizar la relevancia."));
    } finally {
      setBusy(false);
    }
  }

  async function createBriefing() {
    if (!selected || kind !== "meetings") return;
    setBusy(true);
    setBriefingRunning(true);
    try {
      const response = await api.meetings.createBriefing(selected.id, crypto.randomUUID());
      if (response.briefing) {
        setBriefings((current) => [response.briefing!, ...current.filter((item) => item.id !== response.briefing!.id)]);
      }
      toast.success("Preparación solicitada", { description: "Oracle conservará la versión anterior hasta publicar el nuevo briefing." });
      window.setTimeout(() => {
        void api.meetings.briefings(selected.id)
          .then((result) => setBriefings(result.data))
          .finally(() => setBriefingRunning(false));
      }, 5000);
    } catch (reason) {
      setError(message(reason, "No se pudo preparar el documento."));
      setBriefingRunning(false);
    } finally {
      setBusy(false);
    }
  }

  function toggleParticipant(actorId: string) {
    setParticipantIds((current) =>
      current.includes(actorId) ? current.filter((item) => item !== actorId) : [...current, actorId],
    );
  }

  function briefingOutput(briefing: OracleBriefing) {
    const content = briefing.content as { output?: Record<string, unknown>; state?: string } | undefined;
    return content?.output;
  }

  return (
    <section className="vector-panel intelligence-section work-section" aria-labelledby={`${kind}-title`}>
      <header className="intelligence-heading">
        <div>
          <span className="section-kicker">{copy.eyebrow}</span>
          <h1 id={`${kind}-title`}>{copy.title}</h1>
          <p>{copy.description}</p>
        </div>
        <PermissionGate permission={copy.permission}>
          <button className="vector-primary" type="button" onClick={() => void openCreate()}>
            <Plus size={15} /> {copy.create}
          </button>
        </PermissionGate>
      </header>

      {kind === "actors" && (
        <div className="segmented actor-view-switch" role="group" aria-label="Vista de actores">
          <button type="button" aria-pressed={actorView === "linked"} onClick={() => setActorView("linked")}>Actores vinculados</button>
          <button type="button" aria-pressed={actorView === "candidates"} onClick={() => setActorView("candidates")}>Candidatos detectados</button>
        </div>
      )}

      {kind === "actors" && actorView === "candidates" ? (
        <DossierActorCandidates dossierId={dossierId} onImported={() => void load()} />
      ) : <>
      <form className="intelligence-filters" role="search" onSubmit={applyFilters}>
        <label className="intelligence-search">
          <span className="sr-only">Buscar en {copy.title.toLowerCase()}</span>
          <Search size={15} />
          <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder={`Buscar ${copy.title.toLowerCase()}…`} />
        </label>
        {kind !== "actors" && (
          <label>Estado
            <select value={status} onChange={(event) => { setStatus(event.target.value); setPage(1); }}>
              <option value="">Todos</option>
              {[...new Set(Object.keys(TRANSITIONS[kind]).concat(Object.values(TRANSITIONS[kind]).flat()))].map((value) => (
                <option key={value} value={value}>{LABELS[value] ?? value}</option>
              ))}
            </select>
          </label>
        )}
        <button className="vector-secondary" type="submit">Aplicar</button>
        <button className="icon-button bordered" type="button" aria-label="Recargar" onClick={() => void load()}><RefreshCw size={15} /></button>
      </form>

      {error && <p className="auth-inline-error" role="alert">{error}</p>}
      {loading ? (
        <div className="work-loading" role="status"><span className="auth-spinner" /> Cargando {copy.title.toLowerCase()}…</div>
      ) : rows.length === 0 ? (
        <div className="work-empty">
          {kind === "actors" ? <UsersRound size={24} /> : <CheckCircle2 size={24} />}
          <h2>{appliedQuery || status ? "No hay coincidencias" : `Aún no hay ${copy.title.toLowerCase()}`}</h2>
          <p>{appliedQuery || status ? "Ajusta los filtros y vuelve a intentarlo." : kind === "actors" ? "Crea un actor manualmente o revisa las entidades detectadas en las señales vinculadas." : `Usa «${copy.create}» para empezar a construir este contexto.`}</p>
          {kind === "actors" && !appliedQuery && !status && (
            <button className="vector-secondary" type="button" onClick={() => setActorView("candidates")}>
              Ver candidatos detectados
            </button>
          )}
        </div>
      ) : (
        <>
          <div className="work-table-wrap">
            <table className="work-table">
              <thead><tr><th>{kind === "actors" ? "Actor" : "Título"}</th><th>Estado</th><th>Contexto</th><th>Actualización</th><th><span className="sr-only">Acciones</span></th></tr></thead>
              <tbody>{rows.map((row) => (
                <tr key={row.id}>
                  <td><strong>{row.title}</strong><small>{row.secondary}</small></td>
                  <td><span className={`intelligence-status status-${row.status}`}>{LABELS[row.status] ?? row.status}</span></td>
                  <td>{row.detail}{row.labels?.length ? <div className="actor-labels">{row.labels.map((label) => <span key={label}>{label}</span>)}</div> : null}</td>
                  <td>{formatDate(row.updatedAt)}</td>
                  <td><Link className="vector-secondary compact" href={`${pathname}?selected=${encodeURIComponent(row.id)}`} scroll={false}>Abrir <ArrowRight size={13} /></Link></td>
                </tr>
              ))}</tbody>
            </table>
          </div>
          <div className="work-mobile-list">{rows.map((row) => (
            <article key={row.id}>
              <header><span className={`intelligence-status status-${row.status}`}>{LABELS[row.status] ?? row.status}</span><small>{formatDate(row.updatedAt)}</small></header>
              <h2>{row.title}</h2><p>{row.detail}</p>{row.labels?.length ? <div className="actor-labels">{row.labels.map((label) => <span key={label}>{label}</span>)}</div> : null}<small>{row.secondary}</small>
              <Link className="vector-secondary" href={`${pathname}?selected=${encodeURIComponent(row.id)}`} scroll={false}>Abrir detalle</Link>
            </article>
          ))}</div>
          <footer className="intelligence-pagination"><p>Página {page} de {pages} · {meta?.total ?? rows.length} registros</p><div><button className="icon-button bordered" disabled={page <= 1} aria-label="Página anterior" onClick={() => setPage((value) => value - 1)}>‹</button><button className="icon-button bordered" disabled={page >= pages} aria-label="Página siguiente" onClick={() => setPage((value) => value + 1)}>›</button></div></footer>
        </>
      )}
      </>}

      <Dialog.Root open={createOpen} onOpenChange={(open) => { setCreateOpen(open); if (!open) resetCreate(); }}>
        <Dialog.Portal><Dialog.Overlay className="dialog-overlay" /><Dialog.Content className="dialog-content work-dialog">
          <div className="dialog-header"><div><span className="section-kicker">{copy.eyebrow}</span><Dialog.Title>{copy.create}</Dialog.Title><Dialog.Description>Quedará incorporado al expediente activo y será visible para las personas autorizadas.</Dialog.Description></div><Dialog.Close className="icon-button" aria-label="Cerrar"><X /></Dialog.Close></div>
          <form onSubmit={create}>
            {kind === "actors" ? (
              <>
                <div className="segmented" role="group" aria-label="Modo de alta de actor"><button type="button" aria-pressed={actorCreateMode === "new"} onClick={() => setActorCreateMode("new")}>Crear nuevo</button><button type="button" aria-pressed={actorCreateMode === "existing"} onClick={() => setActorCreateMode("existing")}>Vincular existente</button></div>
                {actorCreateMode === "existing" ? <label>Actor existente<select required value={actorId} onChange={(event) => setActorId(event.target.value)}><option value="">Selecciona un actor</option>{actorCatalog.map((actor) => <option key={actor.id} value={actor.id}>{actor.canonical_name}</option>)}</select></label> : <><label>Nombre<input required minLength={2} maxLength={300} value={title} onChange={(event) => setTitle(event.target.value)} autoFocus /></label><label>Tipo<select value={actorType} onChange={(event) => setActorType(event.target.value as ActorType)}><option value="person">Persona</option><option value="organization">Empresa u organización</option><option value="institution">Organismo o institución</option><option value="program">Programa o iniciativa</option><option value="other">Otro</option></select></label><label>Etiquetas (separadas por comas)<input value={actorTags} onChange={(event) => setActorTags(event.target.value)} placeholder="fabricante, socio industrial" /></label></>}
              </>
            ) : (
              <label>Título<input required minLength={3} maxLength={300} value={title} onChange={(event) => setTitle(event.target.value)} /></label>
            )}
            {kind !== "tasks" && <label>{kind === "actors" ? "Roles (separados por comas)" : kind === "meetings" ? "Objetivo" : "Justificación"}<textarea value={detail} onChange={(event) => setDetail(event.target.value)} /></label>}
            {kind === "meetings" && <>
              <label>Fecha y hora<input type="datetime-local" value={scheduledAt} onChange={(event) => setScheduledAt(event.target.value)} /></label>
              <fieldset className="meeting-participants">
                <legend>Participantes</legend>
                {actorCatalog.length ? actorCatalog.slice(0, 12).map((actor) => (
                  <label key={actor.id}><input type="checkbox" checked={participantIds.includes(actor.id)} onChange={() => toggleParticipant(actor.id)} />{actor.canonical_name}</label>
                )) : <p>No hay actores disponibles todavía. Puedes vincularlos después desde el detalle.</p>}
              </fieldset>
            </>}
            {kind === "tasks" && <label>Prioridad<select value={priority} onChange={(event) => setPriority(event.target.value)}><option value="high">Alta</option><option value="medium">Media</option><option value="low">Baja</option></select></label>}
            {createError && <p className="form-error" role="alert">{createError}</p>}
            <div className="dialog-actions"><Dialog.Close className="vector-secondary" type="button">Cancelar</Dialog.Close><button className="vector-primary" disabled={busy || (kind === "actors" ? actorCreateMode === "new" ? title.trim().length < 2 : !actorId : title.trim().length < 3)}>{busy ? "Guardando…" : "Guardar"}</button></div>
          </form>
        </Dialog.Content></Dialog.Portal>
      </Dialog.Root>

      <Dialog.Root open={Boolean(selected)} onOpenChange={(open) => { if (!open) closeDetail(); }}>
        <Dialog.Portal><Dialog.Overlay className="dialog-overlay" /><Dialog.Content className="dialog-content intelligence-drawer work-drawer">
          {selected && <><header><div><span className="section-kicker">{copy.eyebrow}</span><Dialog.Title>{selected.title}</Dialog.Title><Dialog.Description>{selected.detail}</Dialog.Description></div><Dialog.Close className="icon-button bordered" aria-label="Cerrar"><X /></Dialog.Close></header>
          <div className="intelligence-drawer-body">
            <dl className="intelligence-facts"><div><dt>Estado</dt><dd>{LABELS[selected.status] ?? selected.status}</dd></div><div><dt>Versión auditada</dt><dd>{selected.version}</dd></div><div><dt>Actualización</dt><dd>{formatDate(selected.updatedAt)}</dd></div><div><dt>Origen</dt><dd>{kind === "decisions" ? "Decisión humana" : "Registro operativo"}</dd></div></dl>
            <section className="intelligence-detail-block"><h2>Contexto</h2><p>{selected.detail}</p><p>{selected.secondary}</p></section>
            {kind === "actors" && <section className="intelligence-detail-block"><h2>Confianza y procedencia</h2><p>{actorConfidence(selected.raw as OracleDossierActor) === null ? "La confianza no está documentada todavía." : `${actorConfidence(selected.raw as OracleDossierActor)} % de confianza registrada.`}</p><p>{selected.actor?.provenance && Object.keys(selected.actor.provenance).length ? Object.entries(selected.actor.provenance).map(([key, value]) => `${key}: ${String(value)}`).join(" · ") : "Sin procedencia explícita. No uses este actor como hecho verificado hasta añadir una fuente."}</p></section>}
            {kind === "actors" && <PermissionGate permission="actor.write"><section className="intelligence-detail-block"><h2>Ajustar contexto</h2><p>Aumenta diez puntos la relevancia para este expediente, sin modificar la ficha canónica del actor.</p><button className="vector-secondary" disabled={busy || ((selected.raw as OracleDossierActor).relevance_to_dossier ?? 0) >= 100} onClick={() => void reinforceActorRelevance()}>Reforzar relevancia</button></section></PermissionGate>}
            {kind === "meetings" && <section className="intelligence-detail-block"><h2>Preparación de la reunión</h2>{briefingRunning && <p role="status">Generando briefing con Oracle… La versión anterior seguirá disponible.</p>}{briefingsLoading ? <p role="status">Cargando la preparación…</p> : briefings.length ? <div className="work-briefings">{briefings.map((briefing) => { const output = briefingOutput(briefing); return <article key={briefing.id}><header><FileCheck2 size={15} /><span>Briefing v{briefing.version ?? 1}</span><small>{formatDate(briefing.created_at)}</small></header>{output ? <><p>{String(output.meeting_objective ?? "Objetivo pendiente de documentar.")}</p><ul>{(Array.isArray(output.key_messages) ? output.key_messages : []).slice(0, 3).map((item) => <li key={String(item)}>{String(item)}</li>)}</ul><small>Confianza {String(output.confidence ?? "—")} % · {Array.isArray(output.questions) ? output.questions.length : 0} preguntas preparadas</small></> : <p>Preparación en curso o pendiente de publicar.</p>}</article>; })}</div> : <p>Aún no hay una preparación. Cuando la crees, mantendrá separados los hechos, las interpretaciones y las recomendaciones.</p>}<PermissionGate permission="meeting.write"><button className="vector-secondary" disabled={busy || briefingRunning} onClick={() => void createBriefing()}><FileCheck2 size={15} /> {briefingRunning ? "Preparando…" : "Preparar reunión"}</button></PermissionGate></section>}
            {transitions.length > 0 && <PermissionGate permission={copy.permission}><section className="intelligence-detail-block"><h2>Siguientes acciones permitidas</h2><div className="work-transitions">{transitions.map((next) => <button key={next} className={next === "cancelled" || next === "rejected" ? "vector-danger" : "vector-secondary"} disabled={busy} onClick={() => void transition(next)}>{LABELS[next] ?? next}</button>)}</div></section></PermissionGate>}
          </div></>}
        </Dialog.Content></Dialog.Portal>
      </Dialog.Root>
    </section>
  );
}
