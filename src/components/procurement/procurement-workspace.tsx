"use client";

import * as Popover from "@radix-ui/react-popover";
import {
  api,
  type ProcurementSearchFeedback,
  type ProcurementSearchFeedbackDigest,
  type ProcurementSearchFeedbackReason,
  type ProcurementSearchProfile,
  type ProcurementTenderFilters,
  type ProcurementTenderItem,
  type ProcurementTendersResponse,
  type TenderSearchResource,
} from "@oracle/api-client";
import {
  ChevronLeft,
  ChevronRight,
  CircleHelp,
  ExternalLink,
  FileText,
  Pencil,
  Play,
  RefreshCw,
  Save,
  Search,
  Sparkles,
  Trash2,
} from "lucide-react";
import { useSearchParams } from "next/navigation";
import {
  type FormEvent,
  type ReactNode,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { PermissionGate } from "@/components/auth/auth-boundary";
import { AsyncActionButton } from "@/components/ui/async-action-button";
import { PinToDossierControl } from "./pin-to-dossier-control";
import { ProcurementAutocomplete } from "./procurement-autocomplete";
import {
  ProcurementFeedbackControl,
  type ProcurementFeedbackValue,
} from "./procurement-feedback-control";
import { ProcurementSearchWizard } from "./procurement-search-wizard";
import {
  cpvLabel,
  formatDate,
  formatMoney,
  parseCsv,
  problemMessage,
} from "./procurement-helpers";

type TenderSort = "signal" | "deadline_asc" | "deadline_desc" | "updated_desc";
type TenderScope = "active" | "historical" | "all";

interface TenderFiltersForm {
  cpv: string;
  minAmount: string;
  maxAmount: string;
  deadlineBefore: string;
  buyer: string;
  region: string;
  scope: TenderScope;
}

const emptyFilters: TenderFiltersForm = {
  cpv: "",
  minAmount: "",
  maxAmount: "",
  deadlineBefore: "",
  buyer: "",
  region: "",
  scope: "active",
};

interface SummaryState {
  loading?: boolean;
  cached?: boolean;
  text?: string | null;
  model?: string | null;
  error?: string | null;
}

function FieldHelp({
  label,
  children,
}: {
  label: string;
  children: ReactNode;
}) {
  return (
    <Popover.Root>
      <Popover.Trigger asChild>
        <button
          className="procurement-field-help-trigger"
          type="button"
          aria-label={`Ayuda sobre ${label}`}
        >
          <CircleHelp size={14} />
        </button>
      </Popover.Trigger>
      <Popover.Portal>
        <Popover.Content
          className="procurement-field-help-content"
          align="start"
          sideOffset={6}
        >
          {children}
          <Popover.Arrow className="procurement-field-help-arrow" />
        </Popover.Content>
      </Popover.Portal>
    </Popover.Root>
  );
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
    scope: filters.scope,
  };
}

function filtersFromRecord(value?: Record<string, unknown>): TenderFiltersForm {
  const legacyActive = typeof value?.active === "boolean" ? value.active : null;
  const storedScope =
    value?.scope === "active" || value?.scope === "all" ? value.scope : null;
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
    scope: storedScope ?? (legacyActive === false ? "all" : "active"),
  };
}

function canonicalStatusLabel(item: ProcurementTenderItem): string {
  if (item.canonical_status === "open") return "Abierta";
  if (item.canonical_status === "closed") return "Cerrada";
  if (item.canonical_status === "awarded") return "Adjudicada";
  if (item.canonical_status === "cancelled") return "Cancelada";
  return "Estado no confirmado por la fuente";
}

function summaryFromTender(item: ProcurementTenderItem): SummaryState | null {
  if (!item.llm_summary) return null;
  return {
    cached: true,
    text: item.llm_summary,
    model: item.llm_summary_model,
  };
}

function tenderText(item: ProcurementTenderItem, key: string): string | null {
  const value = item[key];
  return typeof value === "string" && value.trim() ? value.trim() : null;
}

function tenderTimestamp(
  item: ProcurementTenderItem,
  key: string,
): number | null {
  const value = tenderText(item, key);
  if (!value) return null;
  const parsed = Date.parse(value);
  return Number.isNaN(parsed) ? null : parsed;
}

function tenderCpvs(item: ProcurementTenderItem): string[] {
  if (Array.isArray(item.cpv)) {
    return item.cpv.filter(
      (value): value is string => typeof value === "string",
    );
  }
  return typeof item.cpv === "string" ? [item.cpv] : [];
}

function compareTenderDate(
  left: ProcurementTenderItem,
  right: ProcurementTenderItem,
  key: string,
  direction: 1 | -1,
): number {
  const leftDate = tenderTimestamp(left, key);
  const rightDate = tenderTimestamp(right, key);
  if (leftDate === null && rightDate === null) return 0;
  if (leftDate === null) return 1;
  if (rightDate === null) return -1;
  return (leftDate - rightDate) * direction;
}

function sortLoadedTenders(
  items: ProcurementTenderItem[],
  sort: TenderSort,
): ProcurementTenderItem[] {
  if (sort === "signal") return items;
  return items
    .map((item, index) => ({ item, index }))
    .sort((left, right) => {
      const compared =
        sort === "deadline_asc"
          ? compareTenderDate(left.item, right.item, "deadline", 1)
          : sort === "deadline_desc"
            ? compareTenderDate(left.item, right.item, "deadline", -1)
            : compareTenderDate(left.item, right.item, "feed_updated_at", -1);
      return compared || left.index - right.index;
    })
    .map(({ item }) => item);
}

export function ProcurementWorkspace() {
  const searchParams = useSearchParams();
  const initialKeywords = searchParams?.get("keywords") ?? "";
  const initialBuyer = searchParams?.get("buyer") ?? "";
  const initialRegion = searchParams?.get("region") ?? "";
  const initialScope = searchParams?.get("scope");
  const initialActive = searchParams?.get("active");
  const [keywords, setKeywords] = useState(initialKeywords);
  const [semanticLabel, setSemanticLabel] = useState("");
  const [filtersOpen, setFiltersOpen] = useState(false);
  const [filters, setFilters] = useState<TenderFiltersForm>({
    ...emptyFilters,
    buyer: initialBuyer,
    region: initialRegion,
    scope:
      initialScope === "all" || initialActive === "false" ? "all" : "active",
  });
  const [offset, setOffset] = useState(0);
  const [result, setResult] = useState<ProcurementTendersResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [summaries, setSummaries] = useState<Record<string, SummaryState>>({});
  const [searches, setSearches] = useState<TenderSearchResource[]>([]);
  const [searchProfiles, setSearchProfiles] = useState<
    ProcurementSearchProfile[]
  >([]);
  const [activeSearchProfile, setActiveSearchProfile] =
    useState<ProcurementSearchProfile | null>(null);
  const [feedbackByFolder, setFeedbackByFolder] = useState<
    Record<string, ProcurementSearchFeedback>
  >({});
  const [feedbackDigest, setFeedbackDigest] =
    useState<ProcurementSearchFeedbackDigest | null>(null);
  const [feedbackBusy, setFeedbackBusy] = useState<Set<string>>(new Set());
  const [feedbackError, setFeedbackError] = useState<string | null>(null);
  const [replanRequest, setReplanRequest] = useState<{
    digestHash: string;
    profileId: string;
    requestKey: number;
  } | null>(null);
  const [searchName, setSearchName] = useState("");
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editingName, setEditingName] = useState("");
  const [searchesError, setSearchesError] = useState<string | null>(null);
  const [sort, setSort] = useState<TenderSort>("signal");
  const [buyerSuggestions, setBuyerSuggestions] = useState<string[]>([]);
  const [buyerSuggesting, setBuyerSuggesting] = useState(false);
  const [buyerSelectedSuggestion, setBuyerSelectedSuggestion] = useState(false);
  const [knownRegions, setKnownRegions] = useState<string[]>([]);
  const buyerSuggestionSequence = useRef(0);

  const limit = 25;
  const effectiveKeywords = (keywords.trim() || semanticLabel.trim()).trim();
  const currentFilters = useMemo(() => filterRecord(filters), [filters]);

  const rememberRegions = useCallback((tenders: ProcurementTenderItem[]) => {
    const observed = tenders
      .map((item) => tenderText(item, "region"))
      .filter((region): region is string => region !== null);
    if (!observed.length) return;
    setKnownRegions((current) =>
      Array.from(new Set([...current, ...observed])).sort((left, right) =>
        left.localeCompare(right, "es"),
      ),
    );
  }, []);

  const regionSuggestions = useMemo(() => {
    const query = filters.region.trim().toLocaleLowerCase("es");
    return knownRegions
      .filter(
        (region) => !query || region.toLocaleLowerCase("es").includes(query),
      )
      .slice(0, 8);
  }, [filters.region, knownRegions]);

  const loadSearches = useCallback(async () => {
    setSearchesError(null);
    try {
      const searchResponse = await api.procurement.searches();
      setSearches(searchResponse.items);
      try {
        const profileResponse = await api.procurementSearchProfiles.list();
        setSearchProfiles(profileResponse.items);
      } catch {
        // Las versiones enriquecen el aside, pero no bloquean la búsqueda manual.
        setSearchProfiles([]);
      }
    } catch (reason) {
      setSearchesError(
        problemMessage(
          reason,
          "No se pudieron cargar las búsquedas guardadas.",
        ),
      );
    }
  }, []);

  const loadFeedback = useCallback(
    async (profile: ProcurementSearchProfile) => {
      setFeedbackError(null);
      try {
        const [feedback, digest] = await Promise.all([
          api.procurementSearchProfiles.listFeedback(profile.id),
          api.procurementSearchProfiles.feedbackDigest(profile.id),
        ]);
        setFeedbackByFolder(
          Object.fromEntries(
            feedback.items.map((item) => [item.folder_id, item]),
          ),
        );
        setFeedbackDigest(digest);
      } catch (reason) {
        setFeedbackByFolder({});
        setFeedbackDigest(null);
        setFeedbackError(
          problemMessage(reason, "No se pudo cargar el feedback de este plan."),
        );
      }
    },
    [],
  );

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
        rememberRegions(response.items);
        setOffset(response.offset ?? nextOffset);
      } catch (reason) {
        setError(
          problemMessage(reason, "No se pudieron cargar las licitaciones."),
        );
      } finally {
        setLoading(false);
      }
    },
    [currentFilters, effectiveKeywords, offset, rememberRegions],
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

  useEffect(() => {
    const query = filters.buyer.trim();
    const sequence = ++buyerSuggestionSequence.current;
    if (!filtersOpen || buyerSelectedSuggestion || query.length < 3) {
      setBuyerSuggestions([]);
      setBuyerSuggesting(false);
      return;
    }
    setBuyerSuggesting(true);
    const debounce = window.setTimeout(() => {
      void api.procurement
        .suggest({ q: query, kind: "buyer", limit: 8 })
        .then((response) => {
          if (buyerSuggestionSequence.current === sequence) {
            setBuyerSuggestions(response.suggestions);
          }
        })
        .catch(() => {
          if (buyerSuggestionSequence.current === sequence) {
            setBuyerSuggestions([]);
          }
        })
        .finally(() => {
          if (buyerSuggestionSequence.current === sequence) {
            setBuyerSuggesting(false);
          }
        });
    }, 260);
    return () => window.clearTimeout(debounce);
  }, [buyerSelectedSuggestion, filters.buyer, filtersOpen]);

  function submit(event: FormEvent) {
    event.preventDefault();
    setActiveSearchProfile(null);
    setFeedbackByFolder({});
    setFeedbackDigest(null);
    setFeedbackError(null);
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
      // Signal v1 descarta scope al guardar y fuerza active=true al ejecutar.
      const nextFilters = {
        ...filtersFromRecord(search.filters),
        scope: "active" as const,
      };
      setKeywords((search.keywords ?? []).join(", "));
      setSemanticLabel("");
      setFilters(nextFilters);
      setResult(response.results);
      rememberRegions(response.results.items);
      setOffset(response.results.offset ?? 0);
      const profile =
        searchProfiles.find(
          (candidate) => candidate.tender_search_id === search.id,
        ) ?? null;
      setActiveSearchProfile(profile);
      if (profile) {
        await loadFeedback(profile);
      } else {
        setFeedbackByFolder({});
        setFeedbackDigest(null);
      }
    } catch (reason) {
      setError(
        problemMessage(reason, "No se pudo ejecutar la búsqueda guardada."),
      );
    } finally {
      setLoading(false);
    }
  }

  async function recordFeedback(
    item: ProcurementTenderItem,
    verdict: "relevant" | "not_relevant",
    reason: ProcurementSearchFeedbackReason,
  ) {
    if (!activeSearchProfile) return;
    setFeedbackBusy((current) => new Set(current).add(item.folder_id));
    setFeedbackError(null);
    try {
      const feedback = await api.procurementSearchProfiles.createFeedback(
        activeSearchProfile.id,
        {
          plan_version: activeSearchProfile.version,
          folder_id: item.folder_id,
          verdict,
          reason,
          note: null,
          tender: {
            title: item.title || "Licitación sin título",
            cpvs: tenderCpvs(item),
          },
        },
      );
      setFeedbackByFolder((current) => ({
        ...current,
        [item.folder_id]: feedback,
      }));
      setFeedbackDigest(
        await api.procurementSearchProfiles.feedbackDigest(
          activeSearchProfile.id,
        ),
      );
    } catch (reasonValue) {
      setFeedbackError(
        problemMessage(reasonValue, "No se pudo registrar el feedback."),
      );
    } finally {
      setFeedbackBusy((current) => {
        const next = new Set(current);
        next.delete(item.folder_id);
        return next;
      });
    }
  }

  async function undoFeedback(item: ProcurementTenderItem) {
    if (!activeSearchProfile) return;
    const feedback = feedbackByFolder[item.folder_id];
    if (!feedback) return;
    setFeedbackBusy((current) => new Set(current).add(item.folder_id));
    setFeedbackError(null);
    try {
      await api.procurementSearchProfiles.removeFeedback(
        activeSearchProfile.id,
        feedback.id,
      );
      setFeedbackByFolder((current) => {
        const next = { ...current };
        delete next[item.folder_id];
        return next;
      });
      setFeedbackDigest(
        await api.procurementSearchProfiles.feedbackDigest(
          activeSearchProfile.id,
        ),
      );
    } catch (reason) {
      setFeedbackError(
        problemMessage(reason, "No se pudo deshacer el feedback."),
      );
    } finally {
      setFeedbackBusy((current) => {
        const next = new Set(current);
        next.delete(item.folder_id);
        return next;
      });
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
  const loadedItems = result?.items;
  const items = useMemo(
    () => sortLoadedTenders(loadedItems ?? [], sort),
    [loadedItems, sort],
  );
  const page = Math.floor(offset / limit) + 1;
  const pages = Math.max(1, Math.ceil(total / limit));
  const searchProfileVersions = useMemo(
    () =>
      new Map(
        searchProfiles
          .filter((profile) => profile.tender_search_id)
          .map((profile) => [
            profile.tender_search_id as string,
            profile.version,
          ]),
      ),
    [searchProfiles],
  );

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
        <div className="procurement-heading-actions">
          <ProcurementSearchWizard
            onWatchSaved={loadSearches}
            replanRequest={replanRequest}
          />
          <button
            className="vector-secondary"
            type="button"
            onClick={() => void loadTenders(offset)}
            disabled={loading}
          >
            <RefreshCw size={15} />
            Actualizar
          </button>
        </div>
      </section>

      <section className="vector-panel procurement-search-panel">
        <header>
          <div>
            <span className="section-kicker">Búsqueda</span>
            <h2>Licitaciones del índice PLACSP</h2>
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
          <div className="procurement-search-field">
            <div className="procurement-search-field-label">
              <label htmlFor="procurement-keywords">Términos de búsqueda</label>
              <FieldHelp label="términos de búsqueda">
                Escribe una o varias palabras que esperas encontrar en la
                licitación. Si usas varias, sepáralas con comas: por ejemplo,
                baterías, hidrógeno, mantenimiento.
              </FieldHelp>
            </div>
            <div className="procurement-search-control">
              <Search size={15} />
              <input
                id="procurement-keywords"
                value={keywords}
                onChange={(event) => setKeywords(event.target.value)}
                placeholder="Ej. baterías, hidrógeno, mantenimiento"
              />
            </div>
          </div>
          <div className="procurement-search-field">
            <div className="procurement-search-field-label">
              <label htmlFor="procurement-topic">Descripción del tema</label>
              <FieldHelp label="descripción del tema">
                Alternativa a los términos: describe la necesidad con una frase
                breve, por ejemplo, movilidad eléctrica municipal. Si escribes
                términos, este campo se desactiva para no mezclar los dos modos
                de búsqueda.
              </FieldHelp>
            </div>
            <div className="procurement-search-control">
              <input
                id="procurement-topic"
                value={semanticLabel}
                onChange={(event) => setSemanticLabel(event.target.value)}
                placeholder="Ej. movilidad eléctrica municipal"
                disabled={keywords.trim().length > 0}
              />
            </div>
          </div>
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
              <ProcurementAutocomplete
                label="Órgano comprador"
                value={filters.buyer}
                suggestions={buyerSuggestions}
                loading={buyerSuggesting}
                onChange={(value) => {
                  setBuyerSelectedSuggestion(false);
                  setBuyerSuggestions([]);
                  setFilters((current) => ({ ...current, buyer: value }));
                }}
                onSelect={(value) => {
                  setBuyerSelectedSuggestion(true);
                  setBuyerSuggestions([]);
                  setBuyerSuggesting(false);
                  setFilters((current) => ({ ...current, buyer: value }));
                }}
              />
              <ProcurementAutocomplete
                label="Región"
                value={filters.region}
                suggestions={regionSuggestions}
                onChange={(value) =>
                  setFilters((current) => ({ ...current, region: value }))
                }
                onSelect={(value) =>
                  setFilters((current) => ({ ...current, region: value }))
                }
              />
              <div className="procurement-filter-field">
                <label htmlFor="procurement-scope">Ámbito temporal</label>
                <select
                  id="procurement-scope"
                  aria-describedby="procurement-scope-help"
                  value={filters.scope}
                  onChange={(event) =>
                    setFilters((current) => ({
                      ...current,
                      scope: event.target.value as TenderScope,
                    }))
                  }
                >
                  <option value="active">Solo activas</option>
                  <option value="all">Todo el índice disponible</option>
                </select>
                <small id="procurement-scope-help">
                  Signal todavía no permite aislar licitaciones históricas. Todo
                  el índice incluye activas y registros no activos, pero no
                  equivale a un archivo histórico completo; el histórico fiable
                  se consulta por adjudicaciones.
                </small>
              </div>
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
            <div className="procurement-results-tools">
              <span className="procurement-count">{total} resultados</span>
              <label>
                <span>Orden de los resultados cargados</span>
                <select
                  value={sort}
                  onChange={(event) =>
                    setSort(event.target.value as TenderSort)
                  }
                >
                  <option value="signal">Orden recibido de Signal</option>
                  <option value="deadline_asc">Plazo: vence antes</option>
                  <option value="deadline_desc">Plazo: vence después</option>
                  <option value="updated_desc">
                    Actualización: más reciente
                  </option>
                </select>
              </label>
            </div>
          </header>
          {sort !== "signal" && (
            <p className="procurement-local-sort-note" role="status">
              Orden local sobre los {items.length} resultados cargados en esta
              página; no reordena los {total} resultados del corpus.
            </p>
          )}
          {activeSearchProfile && feedbackDigest && (
            <section
              className="procurement-feedback-digest"
              aria-labelledby="procurement-feedback-digest-heading"
            >
              <header>
                <div>
                  <span className="section-kicker">Aprendizaje explícito</span>
                  <h3 id="procurement-feedback-digest-heading">
                    Feedback sobre el plan v{feedbackDigest.plan_version}
                  </h3>
                  <p>
                    {feedbackDigest.new_feedback_count} feedback nuevos ·{" "}
                    {feedbackDigest.counts.not_relevant} no relevantes ·{" "}
                    {feedbackDigest.counts.relevant} relevantes
                  </p>
                </div>
                <AsyncActionButton
                  className="vector-ai"
                  disabled={feedbackDigest.new_feedback_count < 1}
                  onClick={() =>
                    setReplanRequest({
                      profileId: activeSearchProfile.id,
                      digestHash: feedbackDigest.digest_hash,
                      requestKey: Date.now(),
                    })
                  }
                >
                  <Sparkles size={14} />
                  Revisar el plan con este feedback
                </AsyncActionButton>
              </header>
              <div>
                <p>
                  <strong>Rechazos por motivo:</strong>{" "}
                  {Object.entries(feedbackDigest.reasons)
                    .filter(([, count]) => count > 0)
                    .map(([reason, count]) => `${reason}: ${count}`)
                    .join(" · ") || "sin rechazos"}
                </p>
                <p>
                  <strong>Candidatos a exclusión:</strong>{" "}
                  {feedbackDigest.exclusion_candidates.terms
                    .map((item) => `${item.value} (${item.count})`)
                    .join(", ") || "ninguno"}
                </p>
                <p>
                  <strong>Candidatos a refuerzo:</strong>{" "}
                  {feedbackDigest.reinforcement_candidates.terms
                    .map((item) => `${item.value} (${item.count})`)
                    .join(", ") || "ninguno"}
                </p>
              </div>
              <small>
                Este resumen se calcula con conteos deterministas. La IA solo se
                ejecutará si pulsas revisar.
              </small>
            </section>
          )}
          {feedbackError && (
            <div className="inline-error" role="alert">
              {feedbackError}
            </div>
          )}
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
                const feedback = feedbackByFolder[item.folder_id];
                return (
                  <article
                    className={`procurement-card${feedback ? " has-feedback" : ""}`}
                    key={item.folder_id}
                  >
                    <header>
                      <div>
                        <strong>{item.title || "Licitación sin título"}</strong>
                        <small>{item.buyer || "Órgano no publicado"}</small>
                      </div>
                      <span
                        className={`status tender-${item.canonical_status ?? "unknown"}`}
                      >
                        {canonicalStatusLabel(item)}
                      </span>
                    </header>
                    <p>
                      {item.summary_feed || "Sin resumen de feed disponible."}
                    </p>
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
                      <div>
                        <dt>Actualizada</dt>
                        <dd>
                          {formatDate(tenderText(item, "feed_updated_at"))}
                        </dd>
                      </div>
                    </dl>
                    {summary?.text && (
                      <aside className="procurement-summary">
                        <strong>Resumen Oracle</strong>
                        <p>{summary.text}</p>
                        <small>
                          {summary.cached
                            ? "Resumen en caché"
                            : "Resumen nuevo"}
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
                      <div
                        className="procurement-card-actions"
                        role="group"
                        aria-label={`Acciones para ${item.title || "licitación sin título"}`}
                      >
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
                      </div>
                      {activeSearchProfile && (
                        <PermissionGate permission="opportunity.write">
                          <ProcurementFeedbackControl
                            label={item.title || "licitación sin título"}
                            busy={feedbackBusy.has(item.folder_id)}
                            feedback={
                              feedback
                                ? ({
                                    id: feedback.id,
                                    reason: feedback.reason,
                                    verdict: feedback.verdict,
                                  } satisfies ProcurementFeedbackValue)
                                : null
                            }
                            onRelevant={() =>
                              void recordFeedback(item, "relevant", "other")
                            }
                            onNotRelevant={(reason) =>
                              void recordFeedback(item, "not_relevant", reason)
                            }
                            onUndo={() => void undoFeedback(item)}
                          />
                        </PermissionGate>
                      )}
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
          <nav
            className="inventory-pagination"
            aria-label="Páginas de licitaciones"
          >
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
            fallback={
              <p>Necesitas permiso de escritura para guardar búsquedas.</p>
            }
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
              <AsyncActionButton
                className="vector-primary"
                type="submit"
                disabled={filters.scope !== "active"}
              >
                <Save size={14} />
                Guardar actual
              </AsyncActionButton>
              {filters.scope !== "active" && (
                <small role="status">
                  Signal v1 solo conserva búsquedas guardadas de licitaciones
                  activas. Cambia el ámbito a «Solo activas» para guardarla.
                </small>
              )}
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
                      <strong>
                        {search.name || "Búsqueda sin nombre"}
                        {search.id && searchProfileVersions.has(search.id) && (
                          <span className="procurement-search-version">
                            v{searchProfileVersions.get(search.id)}
                          </span>
                        )}
                      </strong>
                      <small>
                        {(search.keywords ?? []).join(", ") ||
                          "Sin keywords guardadas"}
                      </small>
                    </div>
                  )}
                  <div className="procurement-search-actions">
                    <AsyncActionButton
                      className="vector-secondary"
                      type="button"
                      onClick={() => void runSearch(search)}
                    >
                      <Play size={14} />
                      Ejecutar
                    </AsyncActionButton>
                    <PermissionGate permission="opportunity.write">
                      {editingId === search.id ? (
                        <AsyncActionButton
                          className="vector-secondary"
                          type="button"
                          disabled={filters.scope !== "active"}
                          onClick={() => void patchSearch(search)}
                        >
                          Guardar edición
                        </AsyncActionButton>
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
                      <AsyncActionButton
                        className="vector-danger"
                        type="button"
                        onClick={() => void removeSearch(search)}
                      >
                        <Trash2 size={14} />
                        Eliminar
                      </AsyncActionButton>
                    </PermissionGate>
                  </div>
                </article>
              ))
            ) : (
              <p className="procurement-muted">
                Aún no hay búsquedas guardadas.
              </p>
            )}
          </div>
        </aside>
      </section>
    </div>
  );
}
