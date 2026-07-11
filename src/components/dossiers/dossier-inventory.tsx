"use client";

import {
  ApiError,
  api,
  type BackendDossier,
  type DossierListQuery,
  type DossierSort,
} from "@oracle/api-client";
import {
  ArrowDown,
  ArrowUp,
  ArrowUpDown,
  ChevronLeft,
  ChevronRight,
  Columns3,
  FilePlus2,
  RefreshCw,
  Search,
} from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";
import { PermissionGate } from "@/components/auth/auth-boundary";
import { useAuth } from "@/components/auth/auth-provider";
import { CreateProductDossierDialog } from "@/components/navigation/create-product-dossier-dialog";

const STATUS_OPTIONS = ["draft", "active", "paused", "archived"] as const;
const TYPE_OPTIONS = [
  "project",
  "strategic_account",
  "market",
  "technology",
  "tender_or_grant",
  "investment",
  "partnership",
  "product_launch",
  "regulatory_affair",
  "risk_watch",
  "custom",
] as const;
const SORT_OPTIONS: readonly DossierSort[] = [
  "updated_at",
  "-updated_at",
  "title",
  "-title",
  "status",
  "-status",
  "health_score",
  "-health_score",
  "opportunity_score",
  "-opportunity_score",
  "risk_score",
  "-risk_score",
];
const PAGE_SIZES = [10, 25, 50] as const;
const OPTIONAL_COLUMNS = ["type", "health", "opportunity", "risk", "owner", "updated"] as const;
type OptionalColumn = (typeof OPTIONAL_COLUMNS)[number];
type Density = "compact" | "balanced" | "comfortable";

const STATUS_LABELS: Record<string, string> = {
  draft: "Borrador",
  active: "Activo",
  paused: "Pausado",
  archived: "Archivado",
};
const TYPE_LABELS: Record<string, string> = {
  project: "Proyecto",
  strategic_account: "Cuenta estratégica",
  market: "Mercado",
  technology: "Tecnología",
  tender_or_grant: "Licitación o convocatoria",
  investment: "Inversión",
  partnership: "Alianza",
  product_launch: "Lanzamiento",
  regulatory_affair: "Asunto regulatorio",
  risk_watch: "Vigilancia de riesgo",
  custom: "Otro",
};
const COLUMN_LABELS: Record<OptionalColumn, string> = {
  type: "Tipo",
  health: "Salud",
  opportunity: "Oportunidad",
  risk: "Riesgo",
  owner: "Propietario",
  updated: "Actualizado",
};

function allowed<T extends string>(value: string | null, values: readonly T[]): T | undefined {
  return value && values.includes(value as T) ? (value as T) : undefined;
}

function positiveInteger(value: string | null, fallback: number): number {
  const parsed = Number(value);
  return Number.isSafeInteger(parsed) && parsed > 0 ? parsed : fallback;
}

function queryFromUrl(searchParams: URLSearchParams, userId: string): DossierListQuery {
  const requestedSize = positiveInteger(searchParams.get("size"), 25);
  return {
    page: positiveInteger(searchParams.get("page"), 1),
    size: PAGE_SIZES.includes(requestedSize as 10 | 25 | 50)
      ? (requestedSize as 10 | 25 | 50)
      : 25,
    sort: allowed(searchParams.get("sort"), SORT_OPTIONS) ?? "-updated_at",
    status: allowed(
      searchParams.get("status") ?? searchParams.get("filter[status]"),
      STATUS_OPTIONS,
    ),
    type: allowed(searchParams.get("type"), TYPE_OPTIONS),
    owner: searchParams.get("owner") === "me" ? userId : undefined,
    search: searchParams.get("q")?.trim() || undefined,
  };
}

function score(value: number): string {
  return Number.isFinite(value) ? String(Math.round(value)) : "—";
}

function dateLabel(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "Sin fecha";
  return new Intl.DateTimeFormat("es-ES", {
    day: "2-digit",
    month: "short",
    year: "numeric",
    timeZone: "Europe/Madrid",
  }).format(date);
}

function SortIcon({ active, descending }: { active: boolean; descending: boolean }) {
  if (!active) return <ArrowUpDown size={14} aria-hidden="true" />;
  return descending ? <ArrowDown size={14} aria-hidden="true" /> : <ArrowUp size={14} aria-hidden="true" />;
}

export function DossierInventory() {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const auth = useAuth();
  const userId = auth.identity!.user.id;
  const urlKey = searchParams.toString();
  const query = useMemo(
    () => queryFromUrl(new URLSearchParams(urlKey), userId),
    [urlKey, userId],
  );
  const [items, setItems] = useState<BackendDossier[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<ApiError | Error | null>(null);
  const [requestVersion, setRequestVersion] = useState(0);
  const [selected, setSelected] = useState<string[]>([]);
  const [density, setDensity] = useState<Density>("balanced");
  const [visibleColumns, setVisibleColumns] = useState<OptionalColumn[]>([
    ...OPTIONAL_COLUMNS,
  ]);
  const [createOpen, setCreateOpen] = useState(false);
  const densityKey = `oracle:ui:density:${userId}`;
  const columnsKey = `oracle:dossiers:columns:${userId}`;

  useEffect(() => {
    const kickoff = window.setTimeout(() => {
      const storage = window.localStorage;
      if (!storage) return;
      const storedDensity = storage.getItem(densityKey);
      if (["compact", "balanced", "comfortable"].includes(storedDensity ?? ""))
        setDensity(storedDensity as Density);
      try {
        const storedColumns = JSON.parse(storage.getItem(columnsKey) ?? "null") as unknown;
        if (Array.isArray(storedColumns)) {
          const valid = storedColumns.filter((item): item is OptionalColumn =>
            OPTIONAL_COLUMNS.includes(item as OptionalColumn),
          );
          setVisibleColumns(valid);
        }
      } catch {
        storage.removeItem(columnsKey);
      }
    }, 0);
    return () => window.clearTimeout(kickoff);
  }, [columnsKey, densityKey]);

  function updateDensity(value: Density) {
    setDensity(value);
    window.localStorage?.setItem(densityKey, value);
  }

  function toggleColumn(column: OptionalColumn) {
    setVisibleColumns((current) => {
      const next = current.includes(column)
        ? current.filter((value) => value !== column)
        : [...current, column];
      window.localStorage?.setItem(columnsKey, JSON.stringify(next));
      return next;
    });
  }

  useEffect(() => {
    let active = true;
    const kickoff = window.setTimeout(() => {
      setLoading(true);
      setError(null);
      setSelected([]);
      void api.dossiers
        .list(query)
        .then((result) => {
          if (!active) return;
          setItems(result.data);
          setTotal(result.meta.total);
        })
        .catch((reason: unknown) => {
          if (active)
            setError(reason instanceof Error ? reason : new Error("Error de red"));
        })
        .finally(() => {
          if (active) setLoading(false);
        });
    }, 0);
    return () => {
      active = false;
      window.clearTimeout(kickoff);
    };
  }, [query, requestVersion]);

  const updateUrl = useCallback(
    (changes: Record<string, string | null>) => {
      const next = new URLSearchParams(urlKey);
      for (const [key, value] of Object.entries(changes)) {
        if (value) next.set(key, value);
        else next.delete(key);
        if (key === "status") next.delete("filter[status]");
      }
      const suffix = next.toString();
      router.replace(suffix ? `${pathname}?${suffix}` : pathname, { scroll: false });
    },
    [pathname, router, urlKey],
  );

  const applySearch = (event: FormEvent) => {
    event.preventDefault();
    const form = new FormData(event.currentTarget as HTMLFormElement);
    const value = String(form.get("q") ?? "").trim();
    updateUrl({ q: value || null, page: null });
  };

  const toggleSort = (field: Exclude<DossierSort, `-${string}`>) => {
    const next = query.sort === field ? `-${field}` : field;
    updateUrl({ sort: next, page: null });
  };

  const page = query.page ?? 1;
  const size = query.size ?? 25;
  const pageCount = Math.max(1, Math.ceil(total / size));
  const allSelected = items.length > 0 && items.every((item) => selected.includes(item.id));
  const show = (column: OptionalColumn) => visibleColumns.includes(column);

  const toggleSelected = (id: string) =>
    setSelected((current) =>
      current.includes(id) ? current.filter((value) => value !== id) : [...current, id],
    );
  const toggleAll = () =>
    setSelected(allSelected ? [] : items.map((item) => item.id));
  const ownerLabel = (item: BackendDossier) =>
    item.owner_user_id === userId
      ? "Tú"
      : "Equipo";

  return (
    <div className="dossier-inventory" data-density={density}>
      <header className="page-heading dossier-inventory-heading">
        <div>
          <span className="section-kicker">Cartera · inventario operativo</span>
          <h1>Expedientes</h1>
          <p>Busca, compara y abre los expedientes estratégicos a los que tienes acceso.</p>
        </div>
        <PermissionGate permission="dossier.write">
          <button className="vector-primary" onClick={() => setCreateOpen(true)}>
            <FilePlus2 size={16} aria-hidden="true" /> Nuevo expediente
          </button>
        </PermissionGate>
      </header>

      <section className="vector-panel dossier-inventory-panel" aria-labelledby="dossier-list-title">
        <header>
          <div>
            <span className="section-kicker">{total} expedientes autorizados</span>
            <h2 id="dossier-list-title">Inventario</h2>
          </div>
          <button
            className="icon-button bordered"
            aria-label="Actualizar expedientes"
            onClick={() => setRequestVersion((value) => value + 1)}
          >
            <RefreshCw size={16} aria-hidden="true" />
          </button>
        </header>

        <div className="dossier-inventory-toolbar">
          <form className="search-field dossier-search" role="search" onSubmit={applySearch}>
            <Search size={16} aria-hidden="true" />
            <input
              key={query.search ?? ""}
              name="q"
              defaultValue={query.search ?? ""}
              placeholder="Buscar por nombre o descripción…"
              aria-label="Buscar expedientes"
            />
            <button className="vector-secondary" type="submit">Buscar</button>
          </form>
          <label>
            <span>Estado</span>
            <select
              aria-label="Filtrar por estado"
              value={query.status ?? ""}
              onChange={(event) => updateUrl({ status: event.target.value || null, page: null })}
            >
              <option value="">Todos</option>
              {STATUS_OPTIONS.map((value) => <option key={value} value={value}>{STATUS_LABELS[value]}</option>)}
            </select>
          </label>
          <label>
            <span>Tipo</span>
            <select
              aria-label="Filtrar por tipo"
              value={query.type ?? ""}
              onChange={(event) => updateUrl({ type: event.target.value || null, page: null })}
            >
              <option value="">Todos</option>
              {TYPE_OPTIONS.map((value) => <option key={value} value={value}>{TYPE_LABELS[value]}</option>)}
            </select>
          </label>
          <label>
            <span>Propietario</span>
            <select
              aria-label="Filtrar por propietario"
              value={query.owner ? "me" : ""}
              onChange={(event) => updateUrl({ owner: event.target.value || null, page: null })}
            >
              <option value="">Todos</option>
              <option value="me">Mis expedientes</option>
            </select>
          </label>
          <label>
            <span>Densidad</span>
            <select
              aria-label="Densidad de filas"
              value={density}
              onChange={(event) => updateDensity(event.target.value as Density)}
            >
              <option value="compact">Compacta</option>
              <option value="balanced">Equilibrada</option>
              <option value="comfortable">Cómoda</option>
            </select>
          </label>
          <details className="dossier-columns">
            <summary className="vector-secondary"><Columns3 size={16} aria-hidden="true" /> Columnas</summary>
            <fieldset>
              <legend>Columnas visibles</legend>
              {OPTIONAL_COLUMNS.map((column) => (
                <label key={column}>
                  <input
                    type="checkbox"
                    checked={show(column)}
                    onChange={() => toggleColumn(column)}
                  />
                  {COLUMN_LABELS[column]}
                </label>
              ))}
            </fieldset>
          </details>
        </div>

        {selected.length > 0 && (
          <div className="dossier-selection" role="status">
            <strong>{selected.length} seleccionados</strong>
            <span>La selección se limita a esta página.</span>
            <button className="vector-secondary" onClick={() => setSelected([])}>Limpiar selección</button>
          </div>
        )}

        {loading ? (
          <div className="dossier-inventory-loading" role="status" aria-live="polite">
            <span className="auth-spinner" /> Cargando expedientes…
          </div>
        ) : error ? (
          <div className="dossier-inventory-state" role="alert">
            <h3>{error instanceof ApiError && error.status === 403 ? "Acceso restringido" : "No se pudo cargar el inventario"}</h3>
            <p>{error instanceof ApiError && error.status === 403
              ? "Tu cuenta no dispone del permiso necesario para consultar expedientes."
              : "Conservamos tus filtros. Reintenta cuando se recupere la conexión."}</p>
            {!(error instanceof ApiError && error.status === 403) && (
              <button className="vector-secondary" onClick={() => setRequestVersion((value) => value + 1)}>Reintentar</button>
            )}
          </div>
        ) : items.length === 0 ? (
          <div className="dossier-inventory-state">
            <h3>{urlKey ? "No hay resultados" : "Aún no hay expedientes"}</h3>
            <p>{urlKey ? "Prueba con otros filtros o limpia la búsqueda." : "Crea el primer expediente para activar el radar estratégico."}</p>
            {urlKey ? (
              <button className="vector-secondary" onClick={() => router.replace(pathname, { scroll: false })}>Limpiar filtros</button>
            ) : (
              <PermissionGate permission="dossier.write">
                <button className="vector-primary" onClick={() => setCreateOpen(true)}>Crear primer expediente</button>
              </PermissionGate>
            )}
          </div>
        ) : (
          <>
            <div className="dossier-inventory-table-wrap">
              <table className="dossier-table dossier-inventory-table">
                <thead>
                  <tr>
                    <th className="selection-column">
                      <input type="checkbox" checked={allSelected} onChange={toggleAll} aria-label="Seleccionar todos los expedientes de esta página" />
                    </th>
                    <th aria-sort={query.sort === "title" ? "ascending" : query.sort === "-title" ? "descending" : "none"}>
                      <button onClick={() => toggleSort("title")}>Expediente <SortIcon active={query.sort === "title" || query.sort === "-title"} descending={query.sort === "-title"} /></button>
                    </th>
                    {show("type") && <th>Tipo</th>}
                    {show("health") && <th aria-sort={query.sort === "health_score" ? "ascending" : query.sort === "-health_score" ? "descending" : "none"}><button onClick={() => toggleSort("health_score")}>Salud <SortIcon active={query.sort === "health_score" || query.sort === "-health_score"} descending={query.sort === "-health_score"} /></button></th>}
                    {show("opportunity") && <th aria-sort={query.sort === "opportunity_score" ? "ascending" : query.sort === "-opportunity_score" ? "descending" : "none"}><button onClick={() => toggleSort("opportunity_score")}>Oportunidad <SortIcon active={query.sort === "opportunity_score" || query.sort === "-opportunity_score"} descending={query.sort === "-opportunity_score"} /></button></th>}
                    {show("risk") && <th aria-sort={query.sort === "risk_score" ? "ascending" : query.sort === "-risk_score" ? "descending" : "none"}><button onClick={() => toggleSort("risk_score")}>Riesgo <SortIcon active={query.sort === "risk_score" || query.sort === "-risk_score"} descending={query.sort === "-risk_score"} /></button></th>}
                    <th aria-sort={query.sort === "status" ? "ascending" : query.sort === "-status" ? "descending" : "none"}><button onClick={() => toggleSort("status")}>Estado <SortIcon active={query.sort === "status" || query.sort === "-status"} descending={query.sort === "-status"} /></button></th>
                    {show("owner") && <th>Propietario</th>}
                    {show("updated") && <th aria-sort={query.sort === "updated_at" ? "ascending" : query.sort === "-updated_at" ? "descending" : "none"}><button onClick={() => toggleSort("updated_at")}>Actualizado <SortIcon active={query.sort === "updated_at" || query.sort === "-updated_at"} descending={query.sort === "-updated_at"} /></button></th>}
                  </tr>
                </thead>
                <tbody>
                  {items.map((item) => (
                    <tr key={item.id} className={selected.includes(item.id) ? "selected" : undefined}>
                      <td className="selection-column"><input type="checkbox" checked={selected.includes(item.id)} onChange={() => toggleSelected(item.id)} aria-label={`Seleccionar ${item.title}`} /></td>
                      <td className="sticky-name"><Link href={`/app/dossiers/${item.id}`}><strong>{item.title}</strong><small>{item.strategic_goal || "Objetivo por completar"}</small></Link></td>
                      {show("type") && <td>{TYPE_LABELS[item.dossier_type] ?? item.dossier_type}</td>}
                      {show("health") && <td><strong>{score(item.health_score)}</strong><small> / 100</small></td>}
                      {show("opportunity") && <td><strong>{score(item.opportunity_score)}</strong><small> / 100</small></td>}
                      {show("risk") && <td><strong>{score(item.risk_score)}</strong><small> / 100</small></td>}
                      <td><span className={`status-badge status-${item.status}`}>{STATUS_LABELS[item.status] ?? item.status}</span></td>
                      {show("owner") && <td>{ownerLabel(item)}</td>}
                      {show("updated") && <td>{dateLabel(item.updated_at)}</td>}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            <div className="dossier-mobile-list" aria-label="Expedientes">
              {items.map((item) => (
                <article key={item.id} className={selected.includes(item.id) ? "selected" : undefined}>
                  <label className="dossier-card-select">
                    <input type="checkbox" checked={selected.includes(item.id)} onChange={() => toggleSelected(item.id)} />
                    <span className="sr-only">Seleccionar {item.title}</span>
                  </label>
                  <div>
                    <span className={`status-badge status-${item.status}`}>{STATUS_LABELS[item.status] ?? item.status}</span>
                    <Link href={`/app/dossiers/${item.id}`}><h3>{item.title}</h3></Link>
                    <p>{TYPE_LABELS[item.dossier_type] ?? item.dossier_type} · {ownerLabel(item)}</p>
                  </div>
                  <dl>
                    <div><dt>Oportunidad</dt><dd>{score(item.opportunity_score)}/100</dd></div>
                    <div><dt>Riesgo</dt><dd>{score(item.risk_score)}/100</dd></div>
                    <div><dt>Actualizado</dt><dd>{dateLabel(item.updated_at)}</dd></div>
                  </dl>
                  <Link className="vector-secondary" href={`/app/dossiers/${item.id}`}>Abrir expediente</Link>
                </article>
              ))}
            </div>
          </>
        )}

        {!loading && !error && total > 0 && (
          <footer className="dossier-pagination" aria-label="Paginación de expedientes">
            <p>Página {Math.min(page, pageCount)} de {pageCount} · {total} resultados</p>
            <label>
              <span>Por página</span>
              <select aria-label="Expedientes por página" value={size} onChange={(event) => updateUrl({ size: event.target.value, page: null })}>
                {PAGE_SIZES.map((value) => <option key={value} value={value}>{value}</option>)}
              </select>
            </label>
            <div>
              <button className="icon-button bordered" aria-label="Página anterior" disabled={page <= 1} onClick={() => updateUrl({ page: String(page - 1) })}><ChevronLeft size={17} /></button>
              <button className="icon-button bordered" aria-label="Página siguiente" disabled={page >= pageCount} onClick={() => updateUrl({ page: String(page + 1) })}><ChevronRight size={17} /></button>
            </div>
          </footer>
        )}
      </section>
      <CreateProductDossierDialog open={createOpen} onOpenChange={setCreateOpen} />
    </div>
  );
}
