"use client";

import * as Tabs from "@radix-ui/react-tabs";
import {
  flexRender,
  getCoreRowModel,
  getFilteredRowModel,
  getSortedRowModel,
  useReactTable,
  type ColumnDef,
  type SortingState,
} from "@tanstack/react-table";
import {
  ApiError,
  api,
  type BackendDossier,
  type components,
  type EntityIntelDossierResponse,
  type EntityIntelGraphResponse,
  type EntityIntelKind,
  type EntityIntelReportJob,
  type EntityIntelRegistryAct,
  type EntityIntelRegistryProfile,
  type EntityIntelRegistryResponse,
  type EntityIntelRegistrySort,
  type EntityIntelRegistryView,
} from "@oracle/api-client";
import { Bot, Building2, ExternalLink, FileText, Link2, RefreshCw, Search, UserRound } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { PermissionGate } from "@/components/auth/auth-boundary";
import { JobProgress } from "@/components/reporting/job-progress";
import { ReportNarrativeSection } from "@/components/reporting/report-narrative-section";
import { AsyncActionButton } from "@/components/ui/async-action-button";
import { EntityGraphExplorer, EntitySearchPanel, entityRoute } from "./entity-intel";
import { registryCounterpartLabel } from "./registry-status";

const KIND_LABELS: Record<EntityIntelKind, string> = {
  company: "Empresa",
  person: "Persona",
};

const REGISTRY_PAGE_SIZE = 50;
const ENTITY_TAB_VALUES = [
  "profile",
  "registry",
  "graph",
  "disclosures",
  "patents",
  "news",
] as const;
const ENTITY_TAB_SET = new Set<string>(ENTITY_TAB_VALUES);
type EntityTab = typeof ENTITY_TAB_VALUES[number];
type EntityTool = "search" | "link" | "report";
type EntitySourceState = "results" | "empty" | "partial" | "error";
type DossierActorWriteInput = components["schemas"]["DossierActorWriteInput"];
type ActorType = NonNullable<DossierActorWriteInput["actor_type"]>;

interface EntityActRow {
  id: string;
  counterpart: string;
  counterpartKind: EntityIntelKind | null;
  role: string;
  action: string;
  dateLabel: string;
  province: string;
  sourceUrl: string | null;
}

interface SimpleItemRow {
  id: string;
  values: Record<string, string>;
  link: unknown;
  searchText: string;
}

interface EntitySourceStatusProps {
  state: EntitySourceState;
  title: string;
  detail: string;
  technicalDetail?: string | null;
}

function problemMessage(reason: unknown, fallback: string): string {
  return reason instanceof ApiError ? reason.problem.detail : fallback;
}

function formatDate(value: unknown): string | null {
  if (typeof value !== "string" || !value.trim()) return null;
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return null;
  return date.toLocaleDateString("es-ES");
}

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {};
}

function sectionData<T>(dossier: EntityIntelDossierResponse | null, key: string): T | null {
  const section = dossier?.sections[key];
  if (!section?.ok) return null;
  return (section.data ?? null) as T | null;
}

function sectionError(dossier: EntityIntelDossierResponse | null, key: string): string | null {
  const section = dossier?.sections[key];
  if (!section || section.ok) return null;
  return typeof section.error === "string" && section.error.trim()
    ? section.error
    : "Esta sección no está disponible ahora mismo.";
}

function registryProfile(registry: EntityIntelRegistryResponse | null): EntityIntelRegistryProfile | null {
  return registry?.profile ?? null;
}

function registryWithDefaults(data: unknown): EntityIntelRegistryResponse {
  const record = asRecord(data);
  const items = Array.isArray(record.items)
    ? record.items.filter((item): item is EntityIntelRegistryAct => Boolean(item) && typeof item === "object")
    : [];
  return {
    ...record,
    items,
    total: typeof record.total === "number" ? record.total : items.length,
    cached_seconds: typeof record.cached_seconds === "number" ? record.cached_seconds : 600,
    cache_hit: Boolean(record.cache_hit),
  };
}

function listItems(data: unknown): Record<string, unknown>[] {
  const record = asRecord(data);
  const items = Array.isArray(record.items) ? record.items : [];
  return items.filter((item): item is Record<string, unknown> => Boolean(item) && typeof item === "object");
}

function sourceTotal(data: unknown, receivedItems: number): number {
  const total = asRecord(data).total;
  return typeof total === "number" && Number.isInteger(total) && total >= receivedItems
    ? total
    : receivedItems;
}

function sourceErrors(data: unknown): string[] {
  const errors = asRecord(data).errors;
  return Array.isArray(errors)
    ? errors.filter((item): item is string => typeof item === "string" && item.trim().length > 0)
    : [];
}

function sourceEmbeddedError(data: unknown): string | null {
  const error = asRecord(data).error;
  return typeof error === "string" && error.trim() ? error.trim() : null;
}

function sourceState(
  itemCount: number,
  options: { error?: string | null; partial?: boolean } = {},
): EntitySourceState {
  if (options.error) return "error";
  if (options.partial) return "partial";
  return itemCount > 0 ? "results" : "empty";
}

function sourceTabAria(label: string, count: number, state: EntitySourceState): string {
  if (state === "error") return `${label}, consulta no disponible`;
  if (state === "partial") return `${label}, ${count} resultados, cobertura parcial`;
  if (state === "empty") return `${label}, sin resultados`;
  return `${label}, ${count} resultados`;
}

function sourceTabBadge(count: number, state: EntitySourceState, total?: number): string {
  if (state === "error") return "!";
  if (state === "partial" && total && total > count) return `${count}/${total}`;
  return String(count);
}

function EntitySourceStatus({
  state,
  title,
  detail,
  technicalDetail,
}: EntitySourceStatusProps) {
  const labels: Record<EntitySourceState, string> = {
    results: "Disponible",
    empty: "Sin resultados",
    partial: "Cobertura parcial",
    error: "No disponible",
  };
  return (
    <div
      className={`entity-source-status is-${state}`}
      role={state === "error" ? "alert" : "status"}
    >
      <span>{labels[state]}</span>
      <div>
        <strong>{title}</strong>
        <p>{detail}</p>
        {technicalDetail && <small>Detalle de la fuente: {technicalDetail}</small>}
      </div>
    </div>
  );
}

function patentFailureMessage(error: string): string {
  if (error.toLocaleLowerCase("es-ES").includes("epo_search_404")) {
    return (
      "La consulta de patentes no se pudo completar. EPO no encontró el nombre exacto " +
      "del solicitante; puede estar registrado con otra grafía o mediante una filial. " +
      "Este resultado no permite concluir que la entidad carezca de patentes."
    );
  }
  return (
    "La consulta de patentes no se pudo completar. La ausencia de resultados no permite " +
    "concluir que la entidad carezca de patentes."
  );
}

function text(value: unknown): string {
  return typeof value === "string" && value.trim() ? value.trim() : "Sin dato";
}

function normalizeForSearch(value: unknown): string {
  return String(value ?? "")
    .normalize("NFD")
    .replace(/\p{Diacritic}/gu, "")
    .toLocaleLowerCase("es-ES");
}

function sourceLink(url: unknown, label = "Fuente") {
  if (typeof url !== "string" || !url.trim()) return <span>Sin enlace</span>;
  return (
    <a href={url} target="_blank" rel="noreferrer">
      {label}
      <ExternalLink size={13} />
    </a>
  );
}

function sortLabel(direction: false | "asc" | "desc"): string {
  if (direction === "asc") return " ↑";
  if (direction === "desc") return " ↓";
  return "";
}

function sortButtonLabel(label: string, direction: false | "asc" | "desc"): string {
  if (direction === "asc") return `${label}, orden ascendente`;
  if (direction === "desc") return `${label}, orden descendente`;
  return `${label}, sin ordenar`;
}

function entityActorType(kind: EntityIntelKind): ActorType {
  return kind === "person" ? "person" : "organization";
}

function signalIdentifiers(profile: EntityIntelRegistryProfile | null): Record<string, string> {
  const record = asRecord(profile);
  return Object.fromEntries(
    ["nif", "cif", "vat", "registry_id", "registration_number", "lei"]
      .flatMap((key) => {
        const value = record[key];
        return typeof value === "string" && value.trim() ? [[key, value.trim()]] : [];
      }),
  );
}

export function EntityDossier({ name, type }: { name: string; type: EntityIntelKind }) {
  const [dossier, setDossier] = useState<EntityIntelDossierResponse | null>(null);
  const [registryPage, setRegistryPage] = useState<EntityIntelRegistryResponse | null>(null);
  const [offset, setOffset] = useState(0);
  const [registryView, setRegistryView] = useState<EntityIntelRegistryView>("current");
  const [registrySort, setRegistrySort] = useState<EntityIntelRegistrySort>("-date");
  const [registryQueryInput, setRegistryQueryInput] = useState("");
  const [registryQuery, setRegistryQuery] = useState("");
  const [province, setProvince] = useState("");
  const [loading, setLoading] = useState(true);
  const [registryLoading, setRegistryLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [registryError, setRegistryError] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<EntityTab>("profile");
  const [graphVisited, setGraphVisited] = useState(false);
  const [activeTool, setActiveTool] = useState<EntityTool | null>(null);
  const tabInteractionStarted = useRef(false);

  const loadDossier = useCallback(async () => {
    setLoading(true);
    setError(null);
    setRegistryError(null);
    try {
      const [dossierResult, registryResult] = await Promise.allSettled([
        api.entityIntel.dossier({ name, type }),
        api.entityIntel.registry({
          name,
          type,
          view: "current",
          limit: REGISTRY_PAGE_SIZE,
          offset: 0,
          sort: "-date",
        }),
      ]);
      if (dossierResult.status === "rejected") throw dossierResult.reason;
      const result = dossierResult.value;
      setDossier(result);
      if (registryResult.status === "fulfilled") {
        setRegistryPage(registryResult.value);
        setRegistryView("current");
      } else {
        const fallback = sectionData<EntityIntelRegistryResponse>(result, "registry");
        setRegistryPage(fallback ? registryWithDefaults(fallback) : null);
        setRegistryView("history");
        setRegistryError(problemMessage(
          registryResult.reason,
          "No se pudo calcular la vista completa de cargos. Se muestra el histórico recibido con la ficha.",
        ));
      }
      setRegistrySort("-date");
      setRegistryQueryInput("");
      setRegistryQuery("");
      setProvince("");
      setOffset(0);
    } catch (reason) {
      setError(problemMessage(reason, "No se pudo cargar la ficha de entidad."));
    } finally {
      setLoading(false);
    }
  }, [name, type]);

  useEffect(() => {
    let cancelled = false;
    queueMicrotask(() => {
      if (!cancelled) void loadDossier();
    });
    return () => {
      cancelled = true;
    };
  }, [loadDossier]);

  useEffect(() => {
    let cancelled = false;
    tabInteractionStarted.current = false;
    queueMicrotask(() => {
      if (cancelled || tabInteractionStarted.current) return;
      const url = new URL(window.location.href);
      const requestedTab = url.searchParams.get("tab");
      const nextTab = requestedTab && ENTITY_TAB_SET.has(requestedTab)
        ? requestedTab as EntityTab
        : "profile";
      setActiveTab(nextTab);
      setGraphVisited(nextTab === "graph");
      if (requestedTab && requestedTab !== nextTab) {
        url.searchParams.delete("tab");
        window.history.replaceState(window.history.state, "", url);
      }
    });
    return () => {
      cancelled = true;
    };
  }, [name, type]);

  const loadRegistryPage = useCallback(async (
    nextOffset: number,
    options: {
      view?: EntityIntelRegistryView;
      query?: string;
      province?: string;
      sort?: EntityIntelRegistrySort;
    } = {},
  ) => {
    const nextView = options.view ?? registryView;
    const nextQuery = options.query ?? registryQuery;
    const nextProvince = options.province ?? province;
    const nextSort = options.sort ?? registrySort;
    setRegistryLoading(true);
    setRegistryError(null);
    try {
      const result = await api.entityIntel.registry({
        name,
        type,
        limit: REGISTRY_PAGE_SIZE,
        offset: nextOffset,
        view: nextView,
        q: nextQuery,
        province: nextProvince,
        sort: nextSort,
      });
      setRegistryPage(result);
      setRegistryView(nextView);
      setRegistryQuery(nextQuery);
      setProvince(nextProvince);
      setRegistrySort(nextSort);
      setOffset(nextOffset);
    } catch (reason) {
      setRegistryError(problemMessage(reason, "No se pudo cargar esta página del histórico."));
    } finally {
      setRegistryLoading(false);
    }
  }, [name, province, registryQuery, registrySort, registryView, type]);

  const registry = useMemo(
    () => registryPage ?? registryWithDefaults(sectionData<EntityIntelRegistryResponse>(dossier, "registry")),
    [dossier, registryPage],
  );
  const profile = registryProfile(registry);
  const summary = registry.summary;
  const historyEvents = summary?.history_events ?? registry.source_total ?? registry.total ?? 0;
  const currentRelationships = summary?.current_relationships ?? null;
  const endedRelationships = summary?.ended_relationships ?? null;
  const companyActs = summary?.company_acts ?? profile?.total_acts ?? null;
  const provinces = useMemo(() => {
    if (Array.isArray(registry.available_provinces)) return registry.available_provinces;
    const fromProfile = Array.isArray(profile?.provinces) ? profile.provinces : [];
    const fromItems = registry.items.map((item) => item.province).filter((value): value is string => Boolean(value));
    return Array.from(new Set([...fromProfile, ...fromItems])).sort((a, b) => a.localeCompare(b, "es"));
  }, [profile, registry.available_provinces, registry.items]);
  const graph = sectionData<EntityIntelGraphResponse>(dossier, "graph");
  const disclosureData = sectionData<Record<string, unknown>>(dossier, "disclosures");
  const disclosures = listItems(disclosureData);
  const disclosureErrors = sourceErrors(disclosureData);
  const disclosureSectionError = sectionError(dossier, "disclosures");
  const disclosureError = disclosureSectionError
    ?? (disclosures.length === 0 && disclosureErrors.length > 0 ? "cnmv_sources_failed" : null);
  const disclosureState = sourceState(disclosures.length, {
    error: disclosureError,
    partial: disclosureErrors.length > 0,
  });
  const patentData = sectionData<Record<string, unknown>>(dossier, "patents");
  const patents = listItems(patentData);
  const patentTotal = sourceTotal(patentData, patents.length);
  const patentsTruncated = patentTotal > patents.length;
  const patentUnavailable = asRecord(patentData).available === false;
  const patentReason = asRecord(patentData).reason;
  const patentError = sectionError(dossier, "patents")
    ?? sourceEmbeddedError(patentData)
    ?? (patentUnavailable
      ? typeof patentReason === "string" && patentReason.trim()
        ? patentReason.trim()
        : "epo_unavailable"
      : null);
  const patentState = sourceState(patents.length, {
    error: patentError,
    partial: patentsTruncated,
  });
  const newsData = sectionData<Record<string, unknown>>(dossier, "news");
  const news = listItems(newsData);
  const newsErrors = sourceErrors(newsData);
  const newsError = sectionError(dossier, "news")
    ?? sourceEmbeddedError(newsData)
    ?? (news.length === 0 && newsErrors.length > 0 ? "news_sources_failed" : null);
  const newsState = sourceState(news.length, {
    error: newsError,
    partial: newsErrors.length > 0,
  });

  const constitution = profile?.constitution_date
    ? { label: "Constitución", value: formatDate(profile.constitution_date) }
    : profile?.first_act_date
      ? { label: "Primer acto BORME publicado", value: formatDate(profile.first_act_date) }
      : null;
  const cacheMinutes = dossier?.cached_seconds
    ? Math.max(1, Math.round(dossier.cached_seconds / 60))
    : null;
  const disclosureStatusDetail = disclosureState === "error"
    ? "No se pudo completar la consulta de comunicaciones recientes. Este estado no equivale a ausencia de hechos relevantes."
    : disclosureState === "partial"
      ? `Se recibieron ${disclosures.length} comunicaciones, pero una o más fuentes CNMV no respondieron.`
      : disclosureState === "empty"
        ? "La consulta terminó sin comunicaciones recientes. La fuente libre no cubre el histórico profundo."
        : `${disclosures.length} comunicaciones recientes disponibles.`;
  const patentStatusDetail = patentState === "error"
    ? patentFailureMessage(patentError ?? "epo_unavailable")
    : patentState === "partial"
      ? `Se muestran ${patents.length} de ${patentTotal} publicaciones localizadas. La muestra no es exhaustiva.`
      : patentState === "empty"
        ? "La consulta terminó sin publicaciones para esta denominación. No permite concluir que la entidad carezca de patentes."
        : `${patents.length} publicaciones de patente localizadas para esta denominación.`;
  const newsStatusDetail = newsState === "error"
    ? "No se pudo completar la búsqueda web. Este estado no equivale a ausencia de menciones."
    : newsState === "partial"
      ? `Se recibieron ${news.length} menciones, pero el proveedor comunicó una cobertura parcial.`
      : newsState === "empty"
        ? "La búsqueda web terminó sin menciones. No permite inferir que la entidad no tenga cobertura pública."
        : `${news.length} menciones web disponibles en el orden de relevancia del proveedor.`;

  function applyRegistryQuery(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    void loadRegistryPage(0, { query: registryQueryInput.trim() });
  }

  function changeRegistryView(nextView: EntityIntelRegistryView) {
    if (nextView === registryView) return;
    void loadRegistryPage(0, { view: nextView });
  }

  function changeRegistrySort(field: "date" | "counterpart" | "role" | "province") {
    const currentField = registrySort.replace(/^-/, "");
    const nextSort = (
      currentField === field
        ? registrySort.startsWith("-") ? field : `-${field}`
        : field === "date" ? "-date" : field
    ) as EntityIntelRegistrySort;
    void loadRegistryPage(0, { sort: nextSort });
  }

  function changeEntityTab(value: string) {
    const nextTab = ENTITY_TAB_SET.has(value) ? value as EntityTab : "profile";
    tabInteractionStarted.current = true;
    if (nextTab === "graph") setGraphVisited(true);
    setActiveTab(nextTab);
    setActiveTool(null);
    const url = new URL(window.location.href);
    if (nextTab === "profile") url.searchParams.delete("tab");
    else url.searchParams.set("tab", nextTab);
    window.history.replaceState(window.history.state, "", url);
  }

  return (
    <div className="entity-intel-page entity-dossier">
      <section className="page-heading">
        <div>
          <div className="eyebrow">Actores · ficha 360º</div>
          <h1>{dossier?.entity.name ?? name}</h1>
          <p>
            Inteligencia de entidad desde Signal. Las fechas BORME son fechas de publicación,
            no necesariamente fechas registrales efectivas.
          </p>
        </div>
        <button
          className="vector-secondary"
          disabled={loading}
          onClick={() => void loadDossier()}
        >
          <RefreshCw size={15} />
          {loading && dossier ? "Recargando vista…" : "Recargar vista"}
        </button>
      </section>

      {error && <div className="inline-error" role="alert">{error}</div>}
      {loading && !dossier ? (
        <div className="global-inventory-state" role="status">Cargando ficha de entidad...</div>
      ) : dossier ? (
        <>
          <section className="entity-dossier-header" aria-busy={loading}>
            <span className={`entity-kind-chip ${type}`}>
              {type === "person" ? <UserRound size={14} /> : <Building2 size={14} />}
              {KIND_LABELS[type]}
            </span>
            {profile?.status && <strong className={`entity-status-pill ${profile.status}`}>{profile.status}</strong>}
            {constitution?.value && (
              <span>
                {constitution.label}: <strong>{constitution.value}</strong>
              </span>
            )}
            <span><strong>{historyEvents}</strong> eventos de cargos</span>
            {companyActs !== null && <span><strong>{companyActs}</strong> actos societarios</span>}
            {provinces.length > 0 && <span>{provinces.join(", ")}</span>}
            {cacheMinutes && (
              <span className="entity-cache-status">
                {dossier.cache_hit ? "Respuesta reutilizada" : "Consulta completada"}
                {` · caché de Oracle hasta ${cacheMinutes} min`}
              </span>
            )}
          </section>

          <Tabs.Root value={activeTab} onValueChange={changeEntityTab} className="entity-tabs">
          <Tabs.List className="dossier-tabs" aria-label="Secciones de la ficha de entidad">
            <Tabs.Trigger value="profile">Perfil</Tabs.Trigger>
            <Tabs.Trigger value="registry">Órganos y cargos</Tabs.Trigger>
            <Tabs.Trigger value="graph">Grafo</Tabs.Trigger>
            <Tabs.Trigger
              value="disclosures"
              aria-label={sourceTabAria("Hechos relevantes", disclosures.length, disclosureState)}
            >
              Hechos relevantes
              <b aria-hidden="true">{sourceTabBadge(disclosures.length, disclosureState)}</b>
            </Tabs.Trigger>
            <Tabs.Trigger
              value="patents"
              aria-label={sourceTabAria("Patentes", patents.length, patentState)}
            >
              Patentes
              <b aria-hidden="true">{sourceTabBadge(patents.length, patentState, patentTotal)}</b>
            </Tabs.Trigger>
            <Tabs.Trigger
              value="news"
              aria-label={sourceTabAria("Noticias", news.length, newsState)}
            >
              Noticias
              <b aria-hidden="true">{sourceTabBadge(news.length, newsState)}</b>
            </Tabs.Trigger>
          </Tabs.List>

          <EntityDossierActions
            activeTool={activeTool}
            onActiveToolChange={setActiveTool}
            entityName={dossier.entity.name ?? name}
            entityLoading={loading}
            profile={profile}
            type={type}
          />

          <Tabs.Content value="profile" className="entity-tab-panel">
            {sectionError(dossier, "registry") ? (
              <div className="inline-error">{sectionError(dossier, "registry")}</div>
            ) : (
              <div className="entity-profile-grid">
                <section>
                  <h2>Identificación</h2>
                  <dl>
                    <div><dt>Nombre consultado</dt><dd>{name}</dd></div>
                    <div><dt>Tipo</dt><dd>{KIND_LABELS[type]}</dd></div>
                    <div><dt>Actos societarios publicados</dt><dd>{companyActs ?? "Sin dato"}</dd></div>
                    <div><dt>Eventos de cargos y órganos</dt><dd>{historyEvents}</dd></div>
                    <div><dt>Cargos actuales</dt><dd>{currentRelationships ?? "Sin dato"}</dd></div>
                    <div><dt>Relaciones cuyo último evento es cese</dt><dd>{endedRelationships ?? "Sin dato"}</dd></div>
                  </dl>
                </section>
                <section>
                  <h2>Cobertura BORME</h2>
                  <dl>
                    <div><dt>Provincias</dt><dd>{provinces.length ? provinces.join(", ") : "Sin dato"}</dd></div>
                    <div><dt>Primer acto</dt><dd>{formatDate(profile?.first_act_date) ?? "Sin dato"}</dd></div>
                    <div><dt>Último acto</dt><dd>{formatDate(profile?.last_act_date) ?? "Sin dato"}</dd></div>
                  </dl>
                </section>
                <section className="entity-source-limits">
                  <h2>Límites de la fuente</h2>
                  <p>Las fechas son de publicación en BORME. La fuente recoge cargos y socio único; no incluye capital social ni porcentajes. Los homónimos no están desambiguados automáticamente.</p>
                </section>
              </div>
            )}
          </Tabs.Content>

          <Tabs.Content value="registry" className="entity-tab-panel">
            {registryError && <div className="inline-error">{registryError}</div>}
            <div className="entity-registry-view-switch" role="tablist" aria-label="Vista registral">
              <button
                type="button"
                role="tab"
                aria-selected={registryView === "current"}
                className={registryView === "current" ? "is-active" : ""}
                onClick={() => changeRegistryView("current")}
              >
                Cargos actuales <span>{currentRelationships ?? "—"}</span>
              </button>
              <button
                type="button"
                role="tab"
                aria-selected={registryView === "history"}
                className={registryView === "history" ? "is-active" : ""}
                onClick={() => changeRegistryView("history")}
              >
                Histórico BORME <span>{historyEvents}</span>
              </button>
            </div>
            <p className="entity-registry-explanation">
              {registryView === "current"
                ? "Una fila por contraparte y cargo. El estado se obtiene del evento BORME más reciente de toda la serie disponible."
                : "Cada fila es una publicación histórica. Nombramiento y cese describen ese evento; no el estado actual de todas las filas anteriores."}
            </p>
            {summary?.history_complete === false && (
              <div className="inline-warning" role="note">
                Signal informa de {summary.history_events} eventos, pero Oracle solo recibió {summary.received_events}.
                Los agregados de relaciones son parciales.
              </div>
            )}
            <form className="entity-table-toolbar" onSubmit={applyRegistryQuery}>
              <label>
                Buscar en todo el histórico
                <input
                  type="search"
                  value={registryQueryInput}
                  onChange={(event) => setRegistryQueryInput(event.target.value)}
                  placeholder="Contraparte, cargo, acción…"
                />
              </label>
              <label>
                Provincia
                <select
                  value={province}
                  onChange={(event) => void loadRegistryPage(0, { province: event.target.value })}
                >
                  <option value="">Todas</option>
                  {provinces.map((item) => <option key={item} value={item}>{item}</option>)}
                </select>
              </label>
              <button className="vector-secondary" type="submit" disabled={registryLoading}>
                Aplicar filtros
              </button>
              {(registryQuery || province) && (
                <button
                  className="vector-ghost"
                  type="button"
                  onClick={() => {
                    setRegistryQueryInput("");
                    void loadRegistryPage(0, { query: "", province: "" });
                  }}
                >
                  Limpiar
                </button>
              )}
            </form>
            <EntityActsTable
              items={registry.items}
              type={type}
              view={registryView}
              sort={registrySort}
              onSort={changeRegistrySort}
            />
            {(registry.total ?? 0) > REGISTRY_PAGE_SIZE && (
              <div className="entity-pagination">
                <button
                  className="vector-secondary"
                  disabled={offset === 0 || registryLoading}
                  onClick={() => void loadRegistryPage(Math.max(0, offset - REGISTRY_PAGE_SIZE))}
                >
                  Anterior
                </button>
                <span>
                  {offset + 1}-{Math.min(offset + registry.items.length, registry.total ?? 0)} de {registry.total}
                </span>
                <button
                  className="vector-secondary"
                  disabled={offset + REGISTRY_PAGE_SIZE >= (registry.total ?? 0) || registryLoading}
                  onClick={() => void loadRegistryPage(offset + REGISTRY_PAGE_SIZE)}
                >
                  Siguiente
                </button>
              </div>
            )}
          </Tabs.Content>

          <Tabs.Content
            value="graph"
            className="entity-tab-panel"
            forceMount={graphVisited || activeTab === "graph" ? true : undefined}
          >
            {sectionError(dossier, "graph") ? (
              <div className="inline-error">{sectionError(dossier, "graph")}</div>
            ) : (
              <EntityGraphExplorer name={name} type={type} initialGraph={graph} embedded />
            )}
          </Tabs.Content>

          <Tabs.Content value="disclosures" className="entity-tab-panel">
            <EntitySourceStatus
              state={disclosureState}
              title="Comunicaciones CNMV"
              detail={disclosureStatusDetail}
              technicalDetail={disclosureSectionError}
            />
            {disclosures.length > 0 && (
              <SimpleItemsTable
                items={disclosures}
                columns={[
                  ["type", "Tipo"],
                  ["pub_date", "Fecha"],
                  ["feed_label", "Fuente"],
                ]}
                linkKey="link"
                note="CNMV: solo hechos recientes disponibles en Signal."
              />
            )}
          </Tabs.Content>

          <Tabs.Content value="patents" className="entity-tab-panel">
            <EntitySourceStatus
              state={patentState}
              title="Consulta de patentes EPO"
              detail={patentStatusDetail}
              technicalDetail={patentError}
            />
            {patents.length > 0 && (
              <SimpleItemsTable
                items={patents}
                columns={[
                  ["pub_number", "Publicación"],
                  ["title", "Título"],
                  ["applicants", "Solicitantes"],
                  ["date", "Fecha"],
                ]}
                linkKey="url"
                note={patentsTruncated
                  ? `Se muestran ${patents.length} de ${patentTotal} publicaciones de patente localizadas por EPO. La muestra no es exhaustiva.`
                  : undefined}
              />
            )}
          </Tabs.Content>

          <Tabs.Content value="news" className="entity-tab-panel">
            <EntitySourceStatus
              state={newsState}
              title="Menciones en búsqueda web"
              detail={newsStatusDetail}
              technicalDetail={newsError}
            />
            {news.length > 0 && (
              <SimpleItemsTable
                items={news}
                columns={[
                  ["title", "Título"],
                  ["source", "Fuente"],
                  ["snippet", "Resumen"],
                ]}
                linkKey="url"
                defaultSort={null}
                note="Orden de relevancia recibido del proveedor. Las menciones no están desambiguadas automáticamente: verifica entidad y fuente antes de utilizarlas."
              />
            )}
          </Tabs.Content>
        </Tabs.Root>
        </>
      ) : (
        <div className="global-inventory-state">
          No hay una ficha disponible. Reintenta la consulta desde esta vista.
        </div>
      )}
    </div>
  );
}

function EntityDossierActions({
  activeTool,
  onActiveToolChange,
  entityName,
  entityLoading,
  profile,
  type,
}: {
  activeTool: EntityTool | null;
  onActiveToolChange: (tool: EntityTool | null) => void;
  entityName: string;
  entityLoading: boolean;
  profile: EntityIntelRegistryProfile | null;
  type: EntityIntelKind;
}) {
  const [dossiers, setDossiers] = useState<BackendDossier[]>([]);
  const [dossiersLoading, setDossiersLoading] = useState(false);
  const [dossiersLoaded, setDossiersLoaded] = useState(false);
  const [dossiersError, setDossiersError] = useState<string | null>(null);
  const requestStarted = useRef(false);

  const loadDossiers = useCallback(async () => {
    if (requestStarted.current || dossiersLoaded) return;
    requestStarted.current = true;
    setDossiersLoading(true);
    setDossiersError(null);
    try {
      const result = await api.dossiers.list({
        page: 1,
        size: 100,
        sort: "-updated_at",
      });
      setDossiers(result.data);
      setDossiersLoaded(true);
    } catch (reason) {
      requestStarted.current = false;
      setDossiersError(problemMessage(reason, "No se pudieron cargar tus expedientes."));
    } finally {
      setDossiersLoading(false);
    }
  }, [dossiersLoaded]);

  useEffect(() => {
    if (activeTool !== "link" && activeTool !== "report") return;
    let cancelled = false;
    queueMicrotask(() => {
      if (!cancelled) void loadDossiers();
    });
    return () => {
      cancelled = true;
    };
  }, [activeTool, loadDossiers]);

  function toggleTool(tool: EntityTool) {
    onActiveToolChange(activeTool === tool ? null : tool);
  }

  return (
    <section className="entity-dossier-actions" aria-label="Acciones de la ficha">
      <div className="entity-dossier-actions-bar" role="toolbar" aria-label="Acciones secundarias">
        <button
          type="button"
          className={activeTool === "search" ? "vector-secondary is-active" : "vector-secondary"}
          aria-expanded={activeTool === "search"}
          aria-controls="entity-tool-search"
          onClick={() => toggleTool("search")}
        >
          <Search size={14} />
          Cambiar entidad
        </button>
        <PermissionGate permission="actor.write">
          <button
            type="button"
            className={activeTool === "link" ? "vector-secondary is-active" : "vector-secondary"}
            aria-expanded={activeTool === "link"}
            aria-controls="entity-tool-link"
            onClick={() => toggleTool("link")}
          >
            <Link2 size={14} />
            Añadir a expediente
          </button>
        </PermissionGate>
        <PermissionGate permission="report.generate">
          <button
            type="button"
            className={activeTool === "report" ? "vector-secondary is-active" : "vector-secondary"}
            aria-expanded={activeTool === "report"}
            aria-controls="entity-tool-report"
            onClick={() => toggleTool("report")}
          >
            <Bot size={14} />
            Informe IA
          </button>
        </PermissionGate>
      </div>

      {activeTool && (
        <div className="entity-dossier-action-panel" id={`entity-tool-${activeTool}`}>
          {activeTool === "search" && (
            <EntitySearchPanel initialQuery={entityName} initialKind={type} compact />
          )}
          {activeTool === "link" && (
            <LinkEntityToDossierControl
              entityName={entityName}
              profile={profile}
              type={type}
              dossiers={dossiers}
              dossiersLoading={dossiersLoading}
              dossiersError={dossiersError}
            />
          )}
          {activeTool === "report" && (
            <EntityReportControl
              entityName={entityName}
              entityLoading={entityLoading}
              type={type}
              dossiers={dossiers}
              dossiersLoading={dossiersLoading}
              dossiersError={dossiersError}
            />
          )}
        </div>
      )}
    </section>
  );
}

function LinkEntityToDossierControl({
  entityName,
  profile,
  type,
  dossiers,
  dossiersLoading,
  dossiersError,
}: {
  entityName: string;
  profile: EntityIntelRegistryProfile | null;
  type: EntityIntelKind;
  dossiers: BackendDossier[];
  dossiersLoading: boolean;
  dossiersError: string | null;
}) {
  const [dossierId, setDossierId] = useState("");
  const [linking, setLinking] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const selectedDossierId = dossiers.some((dossier) => dossier.id === dossierId)
    ? dossierId
    : dossiers[0]?.id ?? "";

  async function linkEntity() {
    if (!selectedDossierId || !entityName.trim()) return;
    const identifiers = signalIdentifiers(profile);
    const identifierProvenance = Object.fromEntries(
      Object.entries(identifiers).map(([key, value]) => [`identifier_${key}`, value]),
    );
    const payload: DossierActorWriteInput = {
      actor_type: entityActorType(type),
      canonical_name: entityName.trim(),
      roles: ["Entidad Signal"],
      tags: ["signal", "entity-intel"],
      provenance: {
        source: "signal_entity_intel",
        source_kind: "entity_dossier",
        entity_kind: type,
        source_name: entityName.trim(),
        ...identifierProvenance,
      },
      relationship_strength: 30,
      relevance_to_dossier: 30,
      recent_activity: 20,
      influence: 0,
      accessibility: 0,
      strategic_alignment: 0,
    };
    setLinking(true);
    setMessage(null);
    setError(null);
    try {
      await api.actors.attach(selectedDossierId, payload);
      setMessage("Entidad vinculada al expediente como actor interno.");
    } catch (reason) {
      setError(problemMessage(reason, "No se pudo vincular esta entidad al expediente."));
    } finally {
      setLinking(false);
    }
  }

  return (
    <PermissionGate permission="actor.write">
      <section className="entity-link-card" aria-label="Vincular entidad a expediente">
        <div>
          <span className="section-kicker">Expedientes</span>
          <h2>Añadir esta entidad a un expediente</h2>
          <p>
            Materializa la entidad de Signal como Actor interno del tenant y conserva la
            procedencia en la trazabilidad del actor.
          </p>
        </div>
        <div className="entity-link-actions">
          <label>
            <span>Expediente destino</span>
            <select
              value={selectedDossierId}
              onChange={(event) => setDossierId(event.target.value)}
              disabled={dossiersLoading || linking || dossiers.length === 0}
            >
              {dossiers.length === 0 ? (
                <option value="">
                  {dossiersLoading ? "Cargando expedientes…" : "Sin expedientes activos"}
                </option>
              ) : (
                dossiers.map((dossier) => (
                  <option key={dossier.id} value={dossier.id}>
                    {dossier.title || "Expediente sin título"}
                  </option>
                ))
              )}
            </select>
          </label>
          <AsyncActionButton
            type="button"
            className="vector-secondary"
            loading={linking}
            loadingLabel={
              <>
                <RefreshCw size={14} />
                Añadiendo…
              </>
            }
            disabled={dossiersLoading || !selectedDossierId}
            onClick={() => void linkEntity()}
          >
            <Link2 size={14} />
            Añadir actor
          </AsyncActionButton>
        </div>
        {message && <small className="entity-link-ok">{message}</small>}
        {dossiersError && <small className="entity-link-error" role="alert">{dossiersError}</small>}
        {error && <small className="entity-link-error" role="alert">{error}</small>}
      </section>
    </PermissionGate>
  );
}

const RUNNING_JOB_STATUSES = new Set(["queued", "running", "retrying"]);

type WaitingClaimKind = "fact" | "inference" | "recommendation" | "decision";

interface WaitingReportParagraph {
  text: string;
  kind: WaitingClaimKind;
  confidence: number;
  evidenceIds: string[];
}

interface WaitingReportSection {
  heading: string;
  paragraphs: WaitingReportParagraph[];
}

interface WaitingReportContent {
  title: string;
  executiveSummary: string;
  confidence: number;
  sections: WaitingReportSection[];
  openQuestions: string[];
  warnings: string[];
}

interface WaitingEvidenceSource {
  id: string;
  label: string;
  sourceKind: string;
  sourceUrl: string | null;
  extract: string;
}

function reportIntentKey(name: string, type: EntityIntelKind): string {
  const suffix =
    typeof crypto !== "undefined" && "randomUUID" in crypto
      ? crypto.randomUUID()
      : `${Date.now()}-${Math.random().toString(16).slice(2)}`;
  return `entity-report:${type}:${name.slice(0, 80)}:${suffix}`;
}

function stringList(value: unknown): string[] {
  return Array.isArray(value)
    ? value.filter((item): item is string => typeof item === "string" && item.trim().length > 0)
    : [];
}

function numberPercent(value: unknown): number {
  const numeric = Number(value);
  return Number.isFinite(numeric) ? Math.min(100, Math.max(0, numeric)) : 0;
}

function claimKind(value: unknown): WaitingClaimKind {
  return ["fact", "inference", "recommendation", "decision"].includes(String(value))
    ? value as WaitingClaimKind
    : "inference";
}

function jobResult(job: EntityIntelReportJob | null | undefined): Record<string, unknown> {
  return asRecord(job?.result);
}

function incorporatedReportId(job: EntityIntelReportJob | null | undefined): string | null {
  const value = jobResult(job).incorporated_report_id;
  return typeof value === "string" && value.trim() ? value.trim() : null;
}

function waitingReportContent(job: EntityIntelReportJob | null | undefined): WaitingReportContent | null {
  const output = asRecord(jobResult(job).output);
  if (!output) return null;
  const sections = Array.isArray(output.sections)
    ? output.sections.flatMap((rawSection) => {
        const section = asRecord(rawSection);
        if (!section || typeof section.heading !== "string") return [];
        const paragraphs = Array.isArray(section.paragraphs)
          ? section.paragraphs.flatMap((rawParagraph) => {
              const paragraph = asRecord(rawParagraph);
              if (!paragraph || typeof paragraph.text !== "string") return [];
              return [{
                text: paragraph.text,
                kind: claimKind(paragraph.kind),
                confidence: numberPercent(paragraph.confidence),
                evidenceIds: stringList(paragraph.evidence_ids),
              }];
            })
          : [];
        return [{ heading: section.heading, paragraphs }];
      })
    : [];
  return {
    title: typeof output.title === "string" && output.title.trim()
      ? output.title
      : "Informe de entidad en espera",
    executiveSummary: typeof output.executive_summary === "string"
      ? output.executive_summary
      : "",
    confidence: numberPercent(output.confidence),
    sections,
    openQuestions: stringList(output.open_questions),
    warnings: stringList(output.warnings),
  };
}

function waitingEvidenceSources(job: EntityIntelReportJob | null | undefined): WaitingEvidenceSource[] {
  const sources = jobResult(job).pending_evidence_sources;
  if (!Array.isArray(sources)) return [];
  return sources.flatMap((raw) => {
    const source = asRecord(raw);
    if (!source || typeof source.id !== "string") return [];
    return [{
      id: source.id,
      label: typeof source.label === "string" && source.label.trim()
        ? source.label
        : `Fuente reservada ${source.id.slice(0, 8)}`,
      sourceKind: typeof source.source_kind === "string" ? source.source_kind : "entity_intel",
      sourceUrl: typeof source.source_url === "string" && source.source_url.trim()
        ? source.source_url
        : null,
      extract: typeof source.extract === "string" ? source.extract : "",
    }];
  });
}

function EntityReportControl({
  entityName,
  entityLoading,
  type,
  dossiers,
  dossiersLoading,
  dossiersError,
}: {
  entityName: string;
  entityLoading: boolean;
  type: EntityIntelKind;
  dossiers: BackendDossier[];
  dossiersLoading: boolean;
  dossiersError: string | null;
}) {
  const [jobs, setJobs] = useState<EntityIntelReportJob[]>([]);
  const [activeJobId, setActiveJobId] = useState<string | null>(null);
  const [dossierId, setDossierId] = useState("");
  const [loading, setLoading] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [incorporating, setIncorporating] = useState(false);
  const [previewOpen, setPreviewOpen] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const loadReports = useCallback(async () => {
    if (!entityName.trim()) return;
    setLoading(true);
    setError(null);
    try {
      const reportResult = await api.entityIntel.reports({ name: entityName, type, limit: 10 });
      setJobs(reportResult.data);
      const running = reportResult.data.find((job) => RUNNING_JOB_STATUSES.has(job.status));
      setActiveJobId(running?.id ?? null);
      if (!reportResult.data.some((job) => job.status === "succeeded" && !incorporatedReportId(job))) {
        setPreviewOpen(false);
      }
    } catch (reason) {
      setError(problemMessage(reason, "No se pudieron cargar los informes de esta entidad."));
    } finally {
      setLoading(false);
    }
  }, [entityName, type]);

  const selectedDossierId = dossiers.some((dossier) => dossier.id === dossierId)
    ? dossierId
    : dossiers[0]?.id ?? "";

  useEffect(() => {
    let cancelled = false;
    queueMicrotask(() => {
      if (!cancelled) void loadReports();
    });
    return () => {
      cancelled = true;
    };
  }, [loadReports]);

  async function startReport() {
    if (entityLoading || !entityName.trim()) return;
    setGenerating(true);
    setMessage(null);
    setError(null);
    try {
      const result = await api.entityIntel.startReport(
        { name: entityName, type },
        reportIntentKey(entityName, type),
      );
      setActiveJobId(result.job_id);
      setJobs((current) => [result.job as EntityIntelReportJob, ...current]);
      setPreviewOpen(false);
      setMessage("Informe encolado. Puede tardar varios minutos; puedes salir y volver.");
    } catch (reason) {
      setError(problemMessage(reason, "No se pudo lanzar el informe de entidad."));
    } finally {
      setGenerating(false);
    }
  }

  async function incorporate(jobId: string) {
    if (!selectedDossierId) return;
    setIncorporating(true);
    setMessage(null);
    setError(null);
    try {
      const result = await api.entityIntel.incorporateReport(jobId, { dossier_id: selectedDossierId });
      setMessage(`Informe incorporado: ${result.report.title || "listo para revisar"}.`);
      await loadReports();
    } catch (reason) {
      setError(problemMessage(reason, "No se pudo incorporar el informe al expediente."));
    } finally {
      setIncorporating(false);
    }
  }

  const latestSucceeded = jobs.find((job) => job.status === "succeeded") ?? null;
  const latestIncorporatedReportId = incorporatedReportId(latestSucceeded);
  const pendingIncorporation = latestSucceeded && !latestIncorporatedReportId
    ? latestSucceeded
    : null;
  const previewContent = waitingReportContent(pendingIncorporation);
  const previewSources = waitingEvidenceSources(pendingIncorporation);

  return (
    <PermissionGate permission="report.generate">
      <section className="entity-link-card entity-report-card" aria-label="Informe IA de entidad">
        <div>
          <span className="section-kicker">Informe IA</span>
          <h2>Informe de la entidad</h2>
          <p>
            Genera en segundo plano un análisis de perfil registral, BORME, grafo y noticias.
            Puede tardar varios minutos; el resultado queda guardado para incorporarlo después.
          </p>
        </div>
        <div className="entity-link-actions">
          <AsyncActionButton
            type="button"
            className="vector-primary"
            loading={entityLoading || loading || generating}
            loadingLabel={
              generating ? (
                <>
                  <RefreshCw size={14} />
                  Encolando…
                </>
              ) : (
                "Cargando…"
              )
            }
            disabled={entityLoading || Boolean(activeJobId)}
            onClick={() => void startReport()}
          >
            <Bot size={14} />
            {latestSucceeded ? "Generar nuevo informe" : "Informe de la entidad"}
          </AsyncActionButton>
          <button
            type="button"
            className="vector-secondary"
            disabled={loading}
            onClick={() => void loadReports()}
          >
            <RefreshCw size={14} />
            Actualizar estado
          </button>
        </div>
        {activeJobId && (
          <JobProgress
            jobId={activeJobId}
            label="Generando informe de entidad"
            allowActions
            onTerminal={() => {
              setActiveJobId(null);
              void loadReports();
            }}
          />
        )}
        {pendingIncorporation && (
          <div className="entity-report-waiting-status" role="status">
            <FileText size={17} />
            <div>
              <strong>Informe en espera, todavía no incorporado.</strong>
              <span>
                Puedes leerlo antes de elegir expediente. Sus {previewSources.length} fuentes
                son evidencias reservadas: solo se materializan al incorporar.
              </span>
            </div>
            {previewContent && (
              <button
                type="button"
                className="vector-secondary"
                onClick={() => setPreviewOpen((current) => !current)}
              >
                {previewOpen ? "Ocultar vista previa" : "Ver informe en espera"}
              </button>
            )}
          </div>
        )}
        {pendingIncorporation && previewOpen && previewContent && (
          <EntityReportWaitingPreview content={previewContent} sources={previewSources} />
        )}
        {pendingIncorporation && (
          <div className="entity-report-incorporate">
            <label>
              <span>Expediente destino</span>
              <select
                value={selectedDossierId}
                disabled={dossiersLoading || incorporating || dossiers.length === 0}
                onChange={(event) => setDossierId(event.target.value)}
              >
                {dossiers.length === 0 ? (
                  <option value="">Sin expedientes activos</option>
                ) : (
                  dossiers.map((dossier) => (
                    <option key={dossier.id} value={dossier.id}>
                      {dossier.title || "Expediente sin título"}
                    </option>
                  ))
                )}
              </select>
            </label>
            <AsyncActionButton
              type="button"
              className="vector-primary"
              loading={incorporating}
              loadingLabel={
                <>
                  <RefreshCw size={14} />
                  Incorporando…
                </>
              }
              disabled={dossiersLoading || !selectedDossierId}
              onClick={() => void incorporate(pendingIncorporation.id)}
            >
              <Link2 size={14} />
              Incorporar a expediente
            </AsyncActionButton>
          </div>
        )}
        {!loading && !activeJobId && !latestSucceeded && (
          <small className="entity-link-muted">
            Aún no hay informes generados para esta entidad. Lanza uno para revisarlo aquí antes de incorporarlo.
          </small>
        )}
        {latestSucceeded && latestIncorporatedReportId && (
          <small className="entity-link-ok">
            Este informe ya se incorporó a un expediente.{" "}
            <a href={`/app/reports/${latestIncorporatedReportId}`}>
              Abrir informe incorporado
              <ExternalLink size={12} />
            </a>
          </small>
        )}
        {message && <small className="entity-link-ok">{message}</small>}
        {dossiersError && <small className="entity-link-error" role="alert">{dossiersError}</small>}
        {error && <small className="entity-link-error" role="alert">{error}</small>}
      </section>
    </PermissionGate>
  );
}

function EntityReportWaitingPreview({
  content,
  sources,
}: {
  content: WaitingReportContent;
  sources: WaitingEvidenceSource[];
}) {
  const sourceById = new Map(sources.map((source, index) => [source.id, { ...source, index }]));
  return (
    <section className="entity-report-preview" aria-label="Vista previa del informe en espera">
      <div className="entity-report-preview-banner" role="note">
        <strong>Vista previa sin incorporación</strong>
        <p>
          Este informe vive en el área de espera. Las citas apuntan a IDs reservados;
          todavía no son registros Evidence ni están vinculadas a ningún expediente.
        </p>
      </div>
      <div className="report-content-layout">
        <main className="report-content">
          <section className="report-executive-summary">
            <span className="section-kicker">Resumen ejecutivo</span>
            <h2>{content.title}</h2>
            <p>{content.executiveSummary || "El informe no incluye resumen ejecutivo."}</p>
            <span className="confidence">Confianza {content.confidence}%</span>
          </section>
          {content.sections.map((section, sectionIndex) => (
            <ReportNarrativeSection
              key={`${section.heading}-${sectionIndex}`}
              heading={section.heading}
              paragraphs={section.paragraphs}
              renderCitation={(evidenceId) => {
                const source = sourceById.get(evidenceId);
                return (
                  <a
                    key={evidenceId}
                    href={source ? `#entity-report-waiting-source-${source.index + 1}` : undefined}
                    aria-label={
                      source
                        ? `Ir a fuente reservada ${source.index + 1}`
                        : "Fuente reservada no incluida en el detalle"
                    }
                  >
                    [{source ? source.index + 1 : "?"}]
                  </a>
                );
              }}
            />
          ))}
          {!!content.openQuestions.length && (
            <section className="report-open-questions">
              <h2>Preguntas abiertas</h2>
              <ul>
                {content.openQuestions.map((question) => (
                  <li key={question}>{question}</li>
                ))}
              </ul>
            </section>
          )}
          {!!content.warnings.length && (
            <section className="report-warnings" role="note">
              <h2>Advertencias metodológicas</h2>
              <ul>
                {content.warnings.map((warning) => (
                  <li key={warning}>{warning}</li>
                ))}
              </ul>
            </section>
          )}
        </main>
        <aside className="report-source-index entity-report-waiting-sources">
          <span className="section-kicker">Fuentes reservadas</span>
          <h2>Entrarían al expediente</h2>
          <p>
            {sources.length} fuentes citables pendientes de materializar. No existen como
            evidencias reales hasta incorporar.
          </p>
          {sources.length ? (
            <ol>
              {sources.map((source, index) => (
                <li key={source.id} id={`entity-report-waiting-source-${index + 1}`}>
                  <div>
                    <span>[{index + 1}]</span>
                    <strong>{source.label}</strong>
                    <small>{source.sourceKind}</small>
                    {source.extract && <small>{source.extract}</small>}
                  </div>
                  {source.sourceUrl && (
                    <a
                      href={source.sourceUrl}
                      target="_blank"
                      rel="noreferrer"
                      aria-label={`Abrir fuente reservada ${index + 1}`}
                    >
                      <ExternalLink size={14} />
                    </a>
                  )}
                </li>
              ))}
            </ol>
          ) : (
            <p>No hay fuentes citables reservadas en este job.</p>
          )}
        </aside>
      </div>
    </section>
  );
}

function EntityActsTable({
  items,
  type,
  view,
  sort,
  onSort,
}: {
  items: EntityIntelRegistryAct[];
  type: EntityIntelKind;
  view: EntityIntelRegistryView;
  sort: EntityIntelRegistrySort;
  onSort: (field: "date" | "counterpart" | "role" | "province") => void;
}) {
  const rows = useMemo<EntityActRow[]>(() => items.map((item, index) => {
    const counterpart = typeof item.counterpart === "string" && item.counterpart.trim()
      ? item.counterpart.trim()
      : registryCounterpartLabel(type, item);
    const counterpartKind = item.counterpart_kind_verified
      && (item.counterpart_kind === "company" || item.counterpart_kind === "person")
      ? item.counterpart_kind
      : null;
    const role = item.role ?? item.act_type ?? "Sin cargo";
    const action = item.action ?? "acto";
    const province = item.province ?? "Sin dato";
    const dateLabel = formatDate(item.date) ?? "Sin fecha";
    const sourceUrl = typeof item.source_url === "string" ? item.source_url : null;
    return {
      id: `${sourceUrl ?? counterpart}-${index}`,
      counterpart,
      counterpartKind,
      role,
      action,
      dateLabel,
      province,
      sourceUrl,
    };
  }), [items, type]);

  function serverSortLabel(field: "date" | "counterpart" | "role" | "province") {
    if (sort.replace(/^-/, "") !== field) return "";
    return sort.startsWith("-") ? " ↓" : " ↑";
  }

  function serverSortAria(label: string, field: "date" | "counterpart" | "role" | "province") {
    if (sort.replace(/^-/, "") !== field) return `${label}, sin ordenar`;
    return `${label}, orden ${sort.startsWith("-") ? "descendente" : "ascendente"}`;
  }

  if (items.length === 0) {
    return (
      <div className="global-inventory-state">
        {view === "current"
          ? "No hay cargos actuales para estos filtros."
          : "No hay eventos BORME para estos filtros."}
      </div>
    );
  }
  return (
    <div className="entity-table-wrap" aria-busy={false}>
      <table className="entity-acts-table">
        <thead>
          <tr>
            <th>
              <button
                type="button"
                className="entity-sort-button"
                onClick={() => onSort("counterpart")}
                aria-label={serverSortAria(type === "person" ? "Empresa" : "Contraparte", "counterpart")}
              >
                {type === "person" ? "Empresa" : "Contraparte"}{serverSortLabel("counterpart")}
              </button>
            </th>
            <th>
              <button
                type="button"
                className="entity-sort-button"
                onClick={() => onSort("role")}
                aria-label={serverSortAria("Cargo", "role")}
              >
                Cargo{serverSortLabel("role")}
              </button>
            </th>
            {view === "history" && <th>Evento</th>}
            {view === "current" && <th>Estado</th>}
            <th>
              <button
                type="button"
                className="entity-sort-button"
                onClick={() => onSort("date")}
                aria-label={serverSortAria("Publicación BORME", "date")}
              >
                Publicación BORME{serverSortLabel("date")}
              </button>
            </th>
            <th>
              <button
                type="button"
                className="entity-sort-button"
                onClick={() => onSort("province")}
                aria-label={serverSortAria("Provincia", "province")}
              >
                Provincia{serverSortLabel("province")}
              </button>
            </th>
            <th>Fuente</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.id} className={view === "history" && row.action === "cese" ? "is-ended" : "is-active"}>
              <td>
                {row.counterpartKind ? (
                  <a href={entityRoute(row.counterpartKind, row.counterpart)}>{row.counterpart}</a>
                ) : (
                  <span title="Signal no clasifica esta contraparte como persona o empresa">
                    {row.counterpart}
                  </span>
                )}
              </td>
              <td>{row.role}</td>
              {view === "history" && <td>{row.action}</td>}
              {view === "current" && (
                <td><span className="entity-state active">Actual</span></td>
              )}
              <td>{row.dateLabel}</td>
              <td>{row.province}</td>
              <td>{sourceLink(row.sourceUrl, "BORME")}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function SimpleItemsTable({
  items,
  columns,
  linkKey,
  note,
  defaultSort,
}: {
  items: Record<string, unknown>[];
  columns: Array<[string, string]>;
  linkKey: string;
  note?: string;
  defaultSort?: string | null;
}) {
  const [globalFilter, setGlobalFilter] = useState("");
  const resolvedDefaultSort = defaultSort === undefined
    ? columns.find(([key]) => key.includes("date"))?.[0] ?? columns[0]?.[0] ?? ""
    : defaultSort ?? "";
  const [sorting, setSorting] = useState<SortingState>(
    resolvedDefaultSort
      ? [{ id: resolvedDefaultSort, desc: resolvedDefaultSort.includes("date") }]
      : [],
  );
  const rows = useMemo<SimpleItemRow[]>(() => items.map((item, index) => {
    const values = Object.fromEntries(
      columns.map(([key]) => [
        key,
        Array.isArray(item[key]) ? item[key].join(", ") : text(item[key]),
      ]),
    );
    return {
      id: `${values[columns[0]?.[0] ?? "id"] ?? index}-${index}`,
      values,
      link: item[linkKey],
      searchText: normalizeForSearch(`${Object.values(values).join(" ")} ${text(item[linkKey])}`),
    };
  }), [columns, items, linkKey]);
  const tableColumns = useMemo<ColumnDef<SimpleItemRow>[]>(() => [
    ...columns.map<ColumnDef<SimpleItemRow>>(([key, label]) => ({
      id: key,
      accessorFn: (row) => row.values[key] ?? "Sin dato",
      header: label,
    })),
    {
      id: "link",
      header: "Enlace",
      enableSorting: false,
      cell: ({ row }) => sourceLink(row.original.link, "Abrir"),
    },
  ], [columns]);
  // eslint-disable-next-line react-hooks/incompatible-library -- TanStack Table es el patrón canónico de datatables del proyecto.
  const table = useReactTable({
    data: rows,
    columns: tableColumns,
    state: { sorting, globalFilter },
    onSortingChange: setSorting,
    onGlobalFilterChange: setGlobalFilter,
    globalFilterFn: (row, _columnId, filterValue) =>
      row.original.searchText.includes(normalizeForSearch(filterValue)),
    getCoreRowModel: getCoreRowModel(),
    getFilteredRowModel: getFilteredRowModel(),
    getSortedRowModel: getSortedRowModel(),
  });
  const visibleRows = table.getRowModel().rows;

  if (items.length === 0) {
    return <div className="global-inventory-state">Sin datos disponibles en esta sección.</div>;
  }
  return (
    <>
      {note && <p className="entity-section-note">{note}</p>}
      <div className="entity-table-toolbar compact">
        <label>
          Filtrar tabla
          <input
            value={globalFilter}
            onChange={(event) => setGlobalFilter(event.target.value)}
            placeholder="Buscar en esta sección…"
            aria-label="Filtrar tabla de sección"
          />
        </label>
        <span>{visibleRows.length} de {rows.length} filas</span>
      </div>
      <div className="entity-table-wrap">
        <table className="entity-acts-table">
          <thead>
            {table.getHeaderGroups().map((headerGroup) => (
              <tr key={headerGroup.id}>
                {headerGroup.headers.map((header) => (
                  <th key={header.id}>
                    {header.column.getCanSort() ? (
                      <button
                        type="button"
                        className="entity-sort-button"
                        onClick={header.column.getToggleSortingHandler()}
                        aria-label={sortButtonLabel(String(header.column.columnDef.header), header.column.getIsSorted())}
                      >
                        {flexRender(header.column.columnDef.header, header.getContext())}
                        {sortLabel(header.column.getIsSorted())}
                      </button>
                    ) : (
                      flexRender(header.column.columnDef.header, header.getContext())
                    )}
                  </th>
                ))}
              </tr>
            ))}
          </thead>
          <tbody>
            {visibleRows.length ? visibleRows.map((row) => (
              <tr key={row.original.id}>
                {row.getVisibleCells().map((cell) => (
                  <td key={cell.id}>{flexRender(cell.column.columnDef.cell, cell.getContext())}</td>
                ))}
              </tr>
            )) : (
              <tr><td colSpan={tableColumns.length}>Sin coincidencias para el filtro.</td></tr>
            )}
          </tbody>
        </table>
      </div>
    </>
  );
}
