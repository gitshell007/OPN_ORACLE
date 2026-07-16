"use client";

import * as Tabs from "@radix-ui/react-tabs";
import {
  ApiError,
  api,
  type EntityIntelDossierResponse,
  type EntityIntelGraphResponse,
  type EntityIntelKind,
  type EntityIntelRegistryAct,
  type EntityIntelRegistryProfile,
  type EntityIntelRegistryResponse,
} from "@oracle/api-client";
import { Building2, ExternalLink, RefreshCw, UserRound } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { EntityGraphExplorer, EntitySearchPanel, entityRoute } from "./entity-intel";
import {
  latestRegistryStatuses,
  registryActDedupeKey,
  registryCounterpartLabel,
  registryStatusCounts,
  registryStatusKey,
} from "./registry-status";

const KIND_LABELS: Record<EntityIntelKind, string> = {
  company: "Empresa",
  person: "Persona",
};

const REGISTRY_PAGE_SIZE = 50;

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

function counterpartKind(kind: EntityIntelKind): EntityIntelKind {
  return kind === "company" ? "person" : "company";
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

function text(value: unknown): string {
  return typeof value === "string" && value.trim() ? value.trim() : "Sin dato";
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

export function EntityDossier({ name, type }: { name: string; type: EntityIntelKind }) {
  const [dossier, setDossier] = useState<EntityIntelDossierResponse | null>(null);
  const [registryPage, setRegistryPage] = useState<EntityIntelRegistryResponse | null>(null);
  const [registryHistory, setRegistryHistory] = useState<EntityIntelRegistryAct[]>([]);
  const [offset, setOffset] = useState(0);
  const [activeOnly, setActiveOnly] = useState(false);
  const [province, setProvince] = useState("");
  const [loading, setLoading] = useState(true);
  const [registryLoading, setRegistryLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [registryError, setRegistryError] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState("profile");

  const loadDossier = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const result = await api.entityIntel.dossier({ name, type });
      setDossier(result);
      const registry = sectionData<EntityIntelRegistryResponse>(result, "registry");
      const normalizedRegistry = registry ? registryWithDefaults(registry) : null;
      setRegistryPage(normalizedRegistry);
      setRegistryHistory(normalizedRegistry?.items ?? []);
    } catch (reason) {
      setDossier(null);
      setRegistryPage(null);
      setError(problemMessage(reason, "No se pudo cargar la ficha de entidad."));
    } finally {
      setLoading(false);
    }
  }, [name, type]);

  useEffect(() => {
    const handle = window.setTimeout(() => void loadDossier(), 0);
    return () => window.clearTimeout(handle);
  }, [loadDossier]);

  const loadRegistryPage = useCallback(async (nextOffset: number) => {
    if (nextOffset === 0) {
      const registry = sectionData<EntityIntelRegistryResponse>(dossier, "registry");
      const normalizedRegistry = registry ? registryWithDefaults(registry) : null;
      setRegistryPage(normalizedRegistry);
      setRegistryHistory(normalizedRegistry?.items ?? []);
      setOffset(0);
      return;
    }
    setRegistryLoading(true);
    setRegistryError(null);
    try {
      const result = await api.entityIntel.registry({
        name,
        type,
        limit: REGISTRY_PAGE_SIZE,
        offset: nextOffset,
      });
      setRegistryPage(result);
      setRegistryHistory((current) => {
        const seen = new Set(
          current.map((item) => registryActDedupeKey(type, item)),
        );
        return [
          ...current,
          ...result.items.filter((item) => {
            const key = registryActDedupeKey(type, item);
            if (seen.has(key)) return false;
            seen.add(key);
            return true;
          }),
        ];
      });
      setOffset(nextOffset);
    } catch (reason) {
      setRegistryError(problemMessage(reason, "No se pudo cargar esta página del histórico."));
    } finally {
      setRegistryLoading(false);
    }
  }, [dossier, name, type]);

  const registry = useMemo(
    () => registryPage ?? registryWithDefaults(sectionData<EntityIntelRegistryResponse>(dossier, "registry")),
    [dossier, registryPage],
  );
  const profile = registryProfile(registry);
  const counts = registryStatusCounts(registry.items, type);
  const provinces = useMemo(() => {
    const fromProfile = Array.isArray(profile?.provinces) ? profile.provinces : [];
    const fromItems = registry.items.map((item) => item.province).filter((value): value is string => Boolean(value));
    return Array.from(new Set([...fromProfile, ...fromItems])).sort((a, b) => a.localeCompare(b, "es"));
  }, [profile, registry.items]);
  const statuses = useMemo(
    () => latestRegistryStatuses(registryHistory.length ? registryHistory : registry.items, type),
    [registry.items, registryHistory, type],
  );
  const filteredItems = registry.items.filter((item) => {
    const key = registryStatusKey(type, item);
    const isActive = statuses.get(key)?.action !== "cese";
    if (activeOnly && !isActive) return false;
    if (province && item.province !== province) return false;
    return true;
  });
  const graph = sectionData<EntityIntelGraphResponse>(dossier, "graph");
  const disclosures = listItems(sectionData(dossier, "disclosures"));
  const patents = listItems(sectionData(dossier, "patents"));
  const news = listItems(sectionData(dossier, "news"));

  const constitution = profile?.constitution_date
    ? { label: "Constitución", value: formatDate(profile.constitution_date) }
    : profile?.first_act_date
      ? { label: "Primer acto BORME publicado", value: formatDate(profile.first_act_date) }
      : null;

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
        <button className="vector-secondary" disabled={loading} onClick={() => void loadDossier()}>
          <RefreshCw size={15} />
          Actualizar ficha
        </button>
      </section>

      <EntitySearchPanel initialQuery={name} initialKind={type} compact />

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
        <span>{registry.total ?? registry.items.length} actos</span>
        {provinces.length > 0 && <span>{provinces.join(", ")}</span>}
      </section>

      {error && <div className="inline-error" role="alert">{error}</div>}
      {loading ? (
        <div className="global-inventory-state" role="status">Cargando ficha de entidad...</div>
      ) : (
        <Tabs.Root value={activeTab} onValueChange={setActiveTab} className="entity-tabs">
          <Tabs.List className="dossier-tabs" aria-label="Secciones de la ficha de entidad">
            <Tabs.Trigger value="profile" onClick={() => setActiveTab("profile")}>Perfil</Tabs.Trigger>
            <Tabs.Trigger value="registry" onClick={() => setActiveTab("registry")}>Órganos y cargos</Tabs.Trigger>
            <Tabs.Trigger value="graph" onClick={() => setActiveTab("graph")}>Grafo</Tabs.Trigger>
            {disclosures.length > 0 && <Tabs.Trigger value="disclosures" onClick={() => setActiveTab("disclosures")}>Hechos relevantes</Tabs.Trigger>}
            {patents.length > 0 && <Tabs.Trigger value="patents" onClick={() => setActiveTab("patents")}>Patentes</Tabs.Trigger>}
            {news.length > 0 && <Tabs.Trigger value="news" onClick={() => setActiveTab("news")}>Noticias</Tabs.Trigger>}
          </Tabs.List>

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
                    <div><dt>Actos publicados</dt><dd>{profile?.total_acts ?? registry.total ?? registry.items.length}</dd></div>
                    <div><dt>Vínculos activos</dt><dd>{counts.active}</dd></div>
                    <div><dt>Ceses</dt><dd>{counts.ended}</dd></div>
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
                {Array.isArray(profile?.acts) && profile.acts.length > 0 && (
                  <section className="entity-wide">
                    <h2>Actos societarios</h2>
                    <EntityActsTable items={profile.acts} type={type} statuses={statuses} />
                  </section>
                )}
              </div>
            )}
          </Tabs.Content>

          <Tabs.Content value="registry" className="entity-tab-panel">
            {registryError && <div className="inline-error">{registryError}</div>}
            <div className="entity-table-toolbar">
              <label>
                <input
                  type="checkbox"
                  checked={activeOnly}
                  onChange={(event) => setActiveOnly(event.target.checked)}
                />
                Solo activos
              </label>
              <label>
                Provincia
                <select value={province} onChange={(event) => setProvince(event.target.value)}>
                  <option value="">Todas</option>
                  {provinces.map((item) => <option key={item} value={item}>{item}</option>)}
                </select>
              </label>
            </div>
            <EntityActsTable items={filteredItems} type={type} statuses={statuses} />
            {(registry.total ?? 0) > REGISTRY_PAGE_SIZE && (
              <div className="entity-pagination">
                <button
                  className="vector-secondary"
                  disabled={offset === 0 || registryLoading}
                  onClick={() => void loadRegistryPage(Math.max(0, offset - REGISTRY_PAGE_SIZE))}
                >
                  Anterior
                </button>
                <span>{offset + 1}-{Math.min(offset + REGISTRY_PAGE_SIZE, registry.total ?? 0)} de {registry.total}</span>
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

          <Tabs.Content value="graph" className="entity-tab-panel">
            {sectionError(dossier, "graph") ? (
              <div className="inline-error">{sectionError(dossier, "graph")}</div>
            ) : (
              <EntityGraphExplorer name={name} type={type} initialGraph={graph} embedded />
            )}
          </Tabs.Content>

          <Tabs.Content value="disclosures" className="entity-tab-panel">
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
          </Tabs.Content>

          <Tabs.Content value="patents" className="entity-tab-panel">
            <SimpleItemsTable
              items={patents}
              columns={[
                ["pub_number", "Publicación"],
                ["title", "Título"],
                ["applicants", "Solicitantes"],
                ["date", "Fecha"],
              ]}
              linkKey="url"
            />
          </Tabs.Content>

          <Tabs.Content value="news" className="entity-tab-panel">
            <SimpleItemsTable
              items={news}
              columns={[
                ["title", "Título"],
                ["source", "Fuente"],
                ["snippet", "Resumen"],
              ]}
              linkKey="url"
            />
          </Tabs.Content>
        </Tabs.Root>
      )}
    </div>
  );
}

function EntityActsTable({
  items,
  type,
  statuses,
}: {
  items: EntityIntelRegistryAct[];
  type: EntityIntelKind;
  statuses: ReturnType<typeof latestRegistryStatuses>;
}) {
  if (items.length === 0) {
    return <div className="global-inventory-state">Sin actos registrales para estos filtros.</div>;
  }
  return (
    <div className="entity-table-wrap">
      <table className="entity-acts-table">
        <thead>
          <tr>
            <th>Contraparte</th>
            <th>Cargo</th>
            <th>Acción</th>
            <th>Estado</th>
            <th>Publicación BORME</th>
            <th>Provincia</th>
            <th>Fuente</th>
          </tr>
        </thead>
        <tbody>
          {items.map((item, index) => {
            const counterpart = registryCounterpartLabel(type, item);
            const key = registryStatusKey(type, item);
            const active = statuses.get(key)?.action !== "cese";
            return (
              <tr key={`${item.source_url ?? counterpart}-${index}`} className={active ? "is-active" : "is-ended"}>
                <td>
                  <a href={entityRoute(counterpartKind(type), counterpart)}>{counterpart}</a>
                </td>
                <td>{item.role ?? item.act_type ?? "Sin cargo"}</td>
                <td>{item.action ?? "acto"}</td>
                <td><span className={`entity-state ${active ? "active" : "ended"}`}>{active ? "Activo" : "Cesado"}</span></td>
                <td>{formatDate(item.date) ?? "Sin fecha"}</td>
                <td>{item.province ?? "Sin dato"}</td>
                <td>{sourceLink(item.source_url, "BORME")}</td>
              </tr>
            );
          })}
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
}: {
  items: Record<string, unknown>[];
  columns: Array<[string, string]>;
  linkKey: string;
  note?: string;
}) {
  if (items.length === 0) {
    return <div className="global-inventory-state">Sin datos disponibles en esta sección.</div>;
  }
  return (
    <div className="entity-table-wrap">
      {note && <p className="entity-section-note">{note}</p>}
      <table className="entity-acts-table">
        <thead>
          <tr>
            {columns.map(([, label]) => <th key={label}>{label}</th>)}
            <th>Enlace</th>
          </tr>
        </thead>
        <tbody>
          {items.map((item, index) => (
            <tr key={`${text(item[columns[0]?.[0] ?? "id"])}-${index}`}>
              {columns.map(([key]) => (
                <td key={key}>{Array.isArray(item[key]) ? item[key].join(", ") : text(item[key])}</td>
              ))}
              <td>{sourceLink(item[linkKey], "Abrir")}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
