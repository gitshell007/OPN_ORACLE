"use client";

import {
  api,
  type ProcurementTenderFilters,
  type ProcurementTenderItem,
  type ProcurementTendersResponse,
  type TenderSearchResource,
} from "@oracle/api-client";
import {
  ChevronLeft,
  ChevronRight,
  ExternalLink,
  FileText,
  Pencil,
  Play,
  RefreshCw,
  Save,
  Search,
  Trash2,
} from "lucide-react";
import {
  type FormEvent,
  useCallback,
  useEffect,
  useMemo,
  useState,
} from "react";
import { PermissionGate } from "@/components/auth/auth-boundary";
import { PinToDossierControl } from "./pin-to-dossier-control";
import {
  cpvLabel,
  formatDate,
  formatMoney,
  parseCsv,
  problemMessage,
} from "./procurement-helpers";

type ActiveFilter = "" | "true" | "false";

interface TenderFiltersForm {
  cpv: string;
  minAmount: string;
  maxAmount: string;
  deadlineBefore: string;
  buyer: string;
  region: string;
  active: ActiveFilter;
}

const emptyFilters: TenderFiltersForm = {
  cpv: "",
  minAmount: "",
  maxAmount: "",
  deadlineBefore: "",
  buyer: "",
  region: "",
  active: "true",
};

interface SummaryState {
  loading?: boolean;
  cached?: boolean;
  text?: string | null;
  model?: string | null;
  error?: string | null;
}

function numericValue(value: string): number | undefined {
  if (!value.trim()) return undefined;
  const normalized = Number(value.replace(",", "."));
  return Number.isFinite(normalized) ? normalized : undefined;
}

function filterRecord(filters: TenderFiltersForm): ProcurementTenderFilters {
  return {
    cpv: filters.cpv.trim() || undefined,
    min_amount: numericValue(filters.minAmount),
    max_amount: numericValue(filters.maxAmount),
    deadline_before: filters.deadlineBefore || undefined,
    buyer: filters.buyer.trim() || undefined,
    region: filters.region.trim() || undefined,
    active:
      filters.active === ""
        ? undefined
        : filters.active === "true",
  };
}

function filtersFromRecord(value?: Record<string, unknown>): TenderFiltersForm {
  return {
    cpv: typeof value?.cpv === "string" ? value.cpv : "",
    minAmount:
      typeof value?.min_amount === "number"
        ? String(value.min_amount)
        : typeof value?.min_amount === "string"
          ? value.min_amount
          : "",
    maxAmount:
      typeof value?.max_amount === "number"
        ? String(value.max_amount)
        : typeof value?.max_amount === "string"
          ? value.max_amount
          : "",
    deadlineBefore:
      typeof value?.deadline_before === "string" ? value.deadline_before : "",
    buyer: typeof value?.buyer === "string" ? value.buyer : "",
    region: typeof value?.region === "string" ? value.region : "",
    active:
      typeof value?.active === "boolean"
        ? value.active
          ? "true"
          : "false"
        : "",
  };
}

function summaryFromTender(item: ProcurementTenderItem): SummaryState | null {
  if (!item.llm_summary) return null;
  return {
    cached: true,
    text: item.llm_summary,
    model: item.llm_summary_model,
  };
}

export function ProcurementWorkspace() {
  const [keywords, setKeywords] = useState("");
  const [semanticLabel, setSemanticLabel] = useState("");
  const [filtersOpen, setFiltersOpen] = useState(false);
  const [filters, setFilters] = useState<TenderFiltersForm>(emptyFilters);
  const [offset, setOffset] = useState(0);
  const [result, setResult] = useState<ProcurementTendersResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [summaries, setSummaries] = useState<Record<string, SummaryState>>({});
  const [searches, setSearches] = useState<TenderSearchResource[]>([]);
  const [searchName, setSearchName] = useState("");
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editingName, setEditingName] = useState("");
  const [searchesError, setSearchesError] = useState<string | null>(null);

  const limit = 25;
  const effectiveKeywords = (keywords.trim() || semanticLabel.trim()).trim();
  const currentFilters = useMemo(() => filterRecord(filters), [filters]);

  const loadSearches = useCallback(async () => {
    setSearchesError(null);
    try {
      const response = await api.procurement.searches();
      setSearches(response.items);
    } catch (reason) {
      setSearchesError(
        problemMessage(reason, "No se pudieron cargar las búsquedas guardadas."),
      );
    }
  }, []);

  const loadTenders = useCallback(
    async (nextOffset = offset) => {
      setLoading(true);
      setError(null);
      try {
        const response = await api.procurement.tenders({
          keywords: effectiveKeywords || undefined,
          ...currentFilters,
          limit,
          offset: nextOffset,
        });
        setResult(response);
        setOffset(response.offset ?? nextOffset);
      } catch (reason) {
        setError(
          problemMessage(reason, "No se pudieron cargar las licitaciones."),
        );
      } finally {
        setLoading(false);
      }
    },
    [currentFilters, effectiveKeywords, offset],
  );

  useEffect(() => {
    const kickoff = window.setTimeout(() => void loadSearches(), 0);
    return () => window.clearTimeout(kickoff);
  }, [loadSearches]);

  useEffect(() => {
    const kickoff = window.setTimeout(() => void loadTenders(0), 0);
    return () => window.clearTimeout(kickoff);
    // La carga inicial debe ejecutarse una vez; el usuario decide cuándo aplicar nuevos filtros.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function submit(event: FormEvent) {
    event.preventDefault();
    void loadTenders(0);
  }

  async function summarize(item: ProcurementTenderItem) {
    const cached = summaryFromTender(item);
    if (cached) {
      setSummaries((current) => ({ ...current, [item.folder_id]: cached }));
      return;
    }
    setSummaries((current) => ({
      ...current,
      [item.folder_id]: { loading: true },
    }));
    try {
      const response = await api.procurement.summarizeTender(item.folder_id);
      setSummaries((current) => ({
        ...current,
        [item.folder_id]: {
          cached: response.cached,
          text: response.item.llm_summary ?? response.item.summary_feed ?? null,
          model: response.item.llm_summary_model,
        },
      }));
    } catch (reason) {
      setSummaries((current) => ({
        ...current,
        [item.folder_id]: {
          error: problemMessage(reason, "No se pudo generar el resumen."),
        },
      }));
    }
  }

  async function saveSearch(event: FormEvent) {
    event.preventDefault();
    const name = searchName.trim();
    if (!name) return;
    try {
      await api.procurement.createSearch({
        name,
        keywords: parseCsv(effectiveKeywords),
        filters: { ...currentFilters },
      });
      setSearchName("");
      await loadSearches();
    } catch (reason) {
      setSearchesError(
        problemMessage(reason, "No se pudo guardar la búsqueda."),
      );
    }
  }

  async function runSearch(search: TenderSearchResource) {
    if (!search.id) return;
    setLoading(true);
    setError(null);
    try {
      const response = await api.procurement.runSearch(search.id, {
        limit,
        offset: 0,
      });
      const nextFilters = filtersFromRecord(search.filters);
      setKeywords((search.keywords ?? []).join(", "));
      setSemanticLabel("");
      setFilters(nextFilters);
      setResult(response.results);
      setOffset(response.results.offset ?? 0);
    } catch (reason) {
      setError(
        problemMessage(reason, "No se pudo ejecutar la búsqueda guardada."),
      );
    } finally {
      setLoading(false);
    }
  }

  async function patchSearch(search: TenderSearchResource) {
    if (!search.id) return;
    try {
      await api.procurement.patchSearch(search.id, {
        name: editingName.trim() || search.name || "Búsqueda sin nombre",
        keywords: parseCsv(effectiveKeywords),
        filters: { ...currentFilters },
      });
      setEditingId(null);
      setEditingName("");
      await loadSearches();
    } catch (reason) {
      setSearchesError(
        problemMessage(reason, "No se pudo editar la búsqueda guardada."),
      );
    }
  }

  async function removeSearch(search: TenderSearchResource) {
    if (!search.id) return;
    try {
      await api.procurement.deleteSearch(search.id);
      await loadSearches();
    } catch (reason) {
      setSearchesError(
        problemMessage(reason, "No se pudo eliminar la búsqueda guardada."),
      );
    }
  }

  const total = result?.total ?? 0;
  const items = result?.items ?? [];
  const page = Math.floor(offset / limit) + 1;
  const pages = Math.max(1, Math.ceil(total / limit));

  return (
    <div className="procurement-page">
      <section className="page-heading">
        <div>
          <div className="eyebrow">Contratación pública</div>
          <h1>Licitaciones PLACSP</h1>
          <p>
            Busca oportunidades públicas, resume pliegos y fija referencias
            citables a expedientes estratégicos.
          </p>
        </div>
        <button
          className="vector-secondary"
          type="button"
          onClick={() => void loadTenders(offset)}
          disabled={loading}
        >
          <RefreshCw size={15} />
          Actualizar
        </button>
      </section>

      <section className="vector-panel procurement-search-panel">
        <header>
          <div>
            <span className="section-kicker">Búsqueda</span>
            <h2>Licitaciones activas y archivadas</h2>
          </div>
          <button
            className="vector-secondary"
            type="button"
            onClick={() => setFiltersOpen((current) => !current)}
          >
            {filtersOpen ? "Ocultar filtros" : "Mostrar filtros"}
          </button>
        </header>
        <form className="procurement-search-form" onSubmit={submit}>
          <label>
            <span>Keywords CSV</span>
            <div>
              <Search size={15} />
              <input
                value={keywords}
                onChange={(event) => setKeywords(event.target.value)}
                placeholder="baterías, hidrógeno, mantenimiento"
              />
            </div>
          </label>
          <label>
            <span>Etiqueta semántica</span>
            <input
              value={semanticLabel}
              onChange={(event) => setSemanticLabel(event.target.value)}
              placeholder="p. ej. movilidad eléctrica"
              disabled={keywords.trim().length > 0}
            />
          </label>
          <button className="vector-primary" type="submit" disabled={loading}>
            Buscar
          </button>
          {filtersOpen && (
            <div className="procurement-filters">
              <label>
                <span>CPV</span>
                <input
                  value={filters.cpv}
                  onChange={(event) =>
                    setFilters((current) => ({
                      ...current,
                      cpv: event.target.value,
                    }))
                  }
                  placeholder="30200000"
                />
              </label>
              <label>
                <span>Importe mínimo</span>
                <input
                  inputMode="decimal"
                  value={filters.minAmount}
                  onChange={(event) =>
                    setFilters((current) => ({
                      ...current,
                      minAmount: event.target.value,
                    }))
                  }
                />
              </label>
              <label>
                <span>Importe máximo</span>
                <input
                  inputMode="decimal"
                  value={filters.maxAmount}
                  onChange={(event) =>
                    setFilters((current) => ({
                      ...current,
                      maxAmount: event.target.value,
                    }))
                  }
                />
              </label>
              <label>
                <span>Fecha límite antes de</span>
                <input
                  type="date"
                  value={filters.deadlineBefore}
                  onChange={(event) =>
                    setFilters((current) => ({
                      ...current,
                      deadlineBefore: event.target.value,
                    }))
                  }
                />
              </label>
              <label>
                <span>Órgano comprador</span>
                <input
                  value={filters.buyer}
                  onChange={(event) =>
                    setFilters((current) => ({
                      ...current,
                      buyer: event.target.value,
                    }))
                  }
                />
              </label>
              <label>
                <span>Región</span>
                <input
                  value={filters.region}
                  onChange={(event) =>
                    setFilters((current) => ({
                      ...current,
                      region: event.target.value,
                    }))
                  }
                />
              </label>
              <label>
                <span>Estado</span>
                <select
                  value={filters.active}
                  onChange={(event) =>
                    setFilters((current) => ({
                      ...current,
                      active: event.target.value as ActiveFilter,
                    }))
                  }
                >
                  <option value="">Todas</option>
                  <option value="true">Solo activas</option>
                  <option value="false">No activas</option>
                </select>
              </label>
            </div>
          )}
        </form>
      </section>

      <section className="procurement-layout">
        <div className="vector-panel procurement-results" aria-busy={loading}>
          <header>
            <div>
              <span className="section-kicker">Resultados</span>
              <h2>Licitaciones encontradas</h2>
            </div>
            <span className="procurement-count">{total} resultados</span>
          </header>
          {error && (
            <div className="inline-error" role="alert">
              {error}
              <button type="button" onClick={() => void loadTenders(offset)}>
                Reintentar
              </button>
            </div>
          )}
          {loading ? (
            <div className="global-inventory-state" role="status">
              Consultando contratación pública…
            </div>
          ) : items.length ? (
            <div className="procurement-card-list">
              {items.map((item) => {
                const summary = summaries[item.folder_id];
                return (
                  <article className="procurement-card" key={item.folder_id}>
                    <header>
                      <div>
                        <strong>{item.title || "Licitación sin título"}</strong>
                        <small>{item.buyer || "Órgano no publicado"}</small>
                      </div>
                      <span className="status">
                        {item.status || (item.is_active ? "Activa" : "Sin estado")}
                      </span>
                    </header>
                    <p>{item.summary_feed || "Sin resumen de feed disponible."}</p>
                    <dl>
                      <div>
                        <dt>Plazo</dt>
                        <dd>{formatDate(item.deadline)}</dd>
                      </div>
                      <div>
                        <dt>Importe</dt>
                        <dd>{formatMoney(item.amount)}</dd>
                      </div>
                      <div>
                        <dt>CPV</dt>
                        <dd>{cpvLabel(item.cpv)}</dd>
                      </div>
                      <div>
                        <dt>Región</dt>
                        <dd>{item.region || "No publicada"}</dd>
                      </div>
                    </dl>
                    {summary?.text && (
                      <aside className="procurement-summary">
                        <strong>Resumen Oracle</strong>
                        <p>{summary.text}</p>
                        <small>
                          {summary.cached ? "Resumen en caché" : "Resumen nuevo"}
                          {summary.model ? ` · ${summary.model}` : ""}
                        </small>
                      </aside>
                    )}
                    {summary?.error && (
                      <div className="inline-error" role="alert">
                        {summary.error}
                      </div>
                    )}
                    <footer>
                      <button
                        className="vector-secondary"
                        type="button"
                        onClick={() => void summarize(item)}
                        disabled={summary?.loading}
                      >
                        <FileText size={14} />
                        {summary?.loading ? "Resumiendo…" : "Resumen"}
                      </button>
                      {item.source_url && (
                        <a
                          className="vector-secondary"
                          href={item.source_url}
                          target="_blank"
                          rel="noreferrer"
                        >
                          <ExternalLink size={14} />
                          Ver fuente oficial
                        </a>
                      )}
                      <PinToDossierControl
                        compact
                        kind="tender"
                        folderId={item.folder_id}
                      />
                    </footer>
                  </article>
                );
              })}
            </div>
          ) : (
            <div className="global-inventory-state">
              <strong>No hay licitaciones para estos criterios</strong>
              <p>Prueba con otras palabras clave, CPV u órgano comprador.</p>
            </div>
          )}
          <nav className="inventory-pagination" aria-label="Páginas de licitaciones">
            <button
              type="button"
              disabled={page <= 1 || loading}
              onClick={() => void loadTenders(Math.max(0, offset - limit))}
            >
              <ChevronLeft size={15} />
              Anterior
            </button>
            <span>
              Página {page} de {pages}
            </span>
            <button
              type="button"
              disabled={page >= pages || loading}
              onClick={() => void loadTenders(offset + limit)}
            >
              Siguiente
              <ChevronRight size={15} />
            </button>
          </nav>
        </div>

        <aside className="vector-panel procurement-saved-searches">
          <header>
            <div>
              <span className="section-kicker">Vigilancia</span>
              <h2>Búsquedas guardadas</h2>
            </div>
            <button
              className="icon-button bordered"
              type="button"
              aria-label="Actualizar búsquedas guardadas"
              onClick={() => void loadSearches()}
            >
              <RefreshCw size={15} />
            </button>
          </header>
          <PermissionGate
            permission="opportunity.write"
            fallback={<p>Necesitas permiso de escritura para guardar búsquedas.</p>}
          >
            <form className="procurement-save-search" onSubmit={saveSearch}>
              <label>
                <span>Nombre</span>
                <input
                  value={searchName}
                  onChange={(event) => setSearchName(event.target.value)}
                  placeholder="Vigilancia movilidad eléctrica"
                />
              </label>
              <button className="vector-primary" type="submit">
                <Save size={14} />
                Guardar actual
              </button>
            </form>
          </PermissionGate>
          {searchesError && (
            <div className="inline-error" role="alert">
              {searchesError}
            </div>
          )}
          <div className="procurement-search-list">
            {searches.length ? (
              searches.map((search) => (
                <article key={search.id || search.name}>
                  {editingId === search.id ? (
                    <label>
                      <span>Nuevo nombre</span>
                      <input
                        value={editingName}
                        onChange={(event) => setEditingName(event.target.value)}
                      />
                    </label>
                  ) : (
                    <div>
                      <strong>{search.name || "Búsqueda sin nombre"}</strong>
                      <small>
                        {(search.keywords ?? []).join(", ") ||
                          "Sin keywords guardadas"}
                      </small>
                    </div>
                  )}
                  <div className="procurement-search-actions">
                    <button
                      className="vector-secondary"
                      type="button"
                      onClick={() => void runSearch(search)}
                    >
                      <Play size={14} />
                      Ejecutar
                    </button>
                    <PermissionGate permission="opportunity.write">
                      {editingId === search.id ? (
                        <button
                          className="vector-secondary"
                          type="button"
                          onClick={() => void patchSearch(search)}
                        >
                          Guardar edición
                        </button>
                      ) : (
                        <button
                          className="vector-secondary"
                          type="button"
                          onClick={() => {
                            setEditingId(search.id ?? null);
                            setEditingName(search.name || "");
                          }}
                        >
                          <Pencil size={14} />
                          Editar
                        </button>
                      )}
                      <button
                        className="vector-danger"
                        type="button"
                        onClick={() => void removeSearch(search)}
                      >
                        <Trash2 size={14} />
                        Eliminar
                      </button>
                    </PermissionGate>
                  </div>
                </article>
              ))
            ) : (
              <p className="procurement-muted">Aún no hay búsquedas guardadas.</p>
            )}
          </div>
        </aside>
      </section>
    </div>
  );
}
