"use client";

import {
  ApiError,
  api,
  type EntityIntelGraphEdge,
  type EntityIntelGraphNode,
  type EntityIntelGraphResponse,
  type EntityIntelKind,
} from "@oracle/api-client";
import { Network, RefreshCw, Search, Sparkles } from "lucide-react";
import { useRouter } from "next/navigation";
import {
  type FormEvent,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import type cytoscape from "cytoscape";
import { EntityDetailDialog, type EntityDetailRelation } from "./entity-detail-dialog";

const KIND_LABELS: Record<EntityIntelKind, string> = {
  company: "Empresa",
  person: "Persona",
};
const ENTITY_KIND_STORAGE_KEY = "opn:entity-intel:kind";
const ENTITY_KINDS = new Set<EntityIntelKind>(["company", "person"]);

let fcoseRegistered = false;
const DAY_MS = 24 * 60 * 60 * 1000;
const MIN_READABLE_GRAPH_ZOOM = 1.05;
const MAX_MANAGEABLE_INITIAL_ZOOM = 1.35;
const MAX_INITIAL_FOCUS_ELEMENTS = 90;
const GRAPH_DOUBLE_TAP_MS = 360;
const GRAPH_FIXED_NODE_SEPARATION = 96;
const GRAPH_FIXED_EDGE_LENGTH = 190;
const GRAPH_SEED_GOLDEN_ANGLE = Math.PI * (3 - Math.sqrt(5));
const GRAPH_SEED_RADIUS = 58;

interface TemporalBounds {
  min: number;
  max: number;
  maxOffset: number;
  datedEdges: number;
  undatedEdges: number;
}

interface TimeFilterState {
  key: string;
  range: [number, number];
}

function problemMessage(reason: unknown, fallback: string): string {
  return reason instanceof ApiError ? reason.problem.detail : fallback;
}

export function entityRoute(kind: EntityIntelKind, name: string): string {
  return `/app/actors/entity/${kind}/${encodeURIComponent(name)}`;
}

function validEntityKind(value: unknown): EntityIntelKind | null {
  return typeof value === "string" && ENTITY_KINDS.has(value as EntityIntelKind)
    ? value as EntityIntelKind
    : null;
}

function storedEntityKind(): EntityIntelKind | null {
  try {
    return validEntityKind(window.sessionStorage.getItem(ENTITY_KIND_STORAGE_KEY));
  } catch {
    return null;
  }
}

function persistEntityKind(kind: EntityIntelKind) {
  if (typeof window === "undefined") return;
  try {
    window.sessionStorage.setItem(ENTITY_KIND_STORAGE_KEY, kind);
  } catch {
    // La preferencia es de conveniencia; si sessionStorage no está disponible, se ignora.
  }
}

export function EntitySearchPanel({
  initialQuery = "",
  initialKind,
  compact = false,
}: {
  initialQuery?: string;
  initialKind?: EntityIntelKind;
  compact?: boolean;
}) {
  const router = useRouter();
  const [kind, setKind] = useState<EntityIntelKind>(initialKind ?? "company");
  const [query, setQuery] = useState(initialQuery);
  const [suggestions, setSuggestions] = useState<string[]>([]);
  const [suggestionsChecked, setSuggestionsChecked] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const previousInitialQuery = useRef(initialQuery);
  const previousInitialKind = useRef(initialKind);
  const userTouchedKind = useRef(false);
  const suggestionSequence = useRef(0);
  const latestSuggestionInput = useRef({ kind, query: query.trim() });

  const loadSuggestions = useCallback(async () => {
    const value = query.trim();
    const requestKind = kind;
    const sequence = suggestionSequence.current + 1;
    suggestionSequence.current = sequence;
    if (value.length < 3) {
      setSuggestions([]);
      setSuggestionsChecked(false);
      setLoading(false);
      setError(null);
      return;
    }
    setLoading(true);
    setSuggestionsChecked(false);
    setError(null);
    try {
      const result = await api.entityIntel.suggest({ q: value, kind: requestKind, limit: 8 });
      const latest = latestSuggestionInput.current;
      if (suggestionSequence.current !== sequence || latest.query !== value || latest.kind !== requestKind) return;
      setSuggestions(result.suggestions);
      setSuggestionsChecked(true);
    } catch (reason) {
      const latest = latestSuggestionInput.current;
      if (suggestionSequence.current !== sequence || latest.query !== value || latest.kind !== requestKind) return;
      setError(problemMessage(reason, "No se pudieron cargar sugerencias de entidades."));
      setSuggestionsChecked(true);
    } finally {
      const latest = latestSuggestionInput.current;
      if (suggestionSequence.current === sequence && latest.query === value && latest.kind === requestKind) {
        setLoading(false);
      }
    }
  }, [kind, query]);

  useEffect(() => {
    latestSuggestionInput.current = { kind, query: query.trim() };
  }, [kind, query]);

  useEffect(() => {
    if (initialKind) return undefined;
    const handle = window.setTimeout(() => {
      if (userTouchedKind.current) return;
      const stored = storedEntityKind();
      if (stored) setKind(stored);
    }, 0);
    return () => window.clearTimeout(handle);
  }, [initialKind]);

  useEffect(() => {
    if (previousInitialQuery.current === initialQuery) return undefined;
    previousInitialQuery.current = initialQuery;
    const handle = window.setTimeout(() => setQuery(initialQuery), 0);
    return () => window.clearTimeout(handle);
  }, [initialQuery]);

  useEffect(() => {
    if (previousInitialKind.current === initialKind) return undefined;
    previousInitialKind.current = initialKind;
    if (!initialKind) return undefined;
    const handle = window.setTimeout(() => setKind(initialKind), 0);
    return () => window.clearTimeout(handle);
  }, [initialKind]);

  useEffect(() => {
    const handle = window.setTimeout(() => void loadSuggestions(), 260);
    return () => window.clearTimeout(handle);
  }, [loadSuggestions]);

  function openEntity(name: string) {
    const value = name.trim();
    if (value.length >= 3) router.push(entityRoute(kind, value));
  }

  function submit(event: FormEvent) {
    event.preventDefault();
    openEntity(suggestions[0] ?? query);
  }

  return (
    <section className={compact ? "entity-search-card compact" : "entity-search-card"}>
      <div className="entity-search-copy">
        <span className="section-kicker">Inteligencia de entidades</span>
        <h2>Buscar entidad</h2>
        <p>
          Consulta empresas o personas en Signal y abre un grafo básico de relaciones.
          La clave y el tenant externo se resuelven siempre en el servidor.
        </p>
      </div>
      <form className="entity-search-form" onSubmit={submit}>
        <label>
          <span>Tipo</span>
          <select
            value={kind}
            onChange={(event) => {
              const nextKind = event.target.value as EntityIntelKind;
              userTouchedKind.current = true;
              suggestionSequence.current += 1;
              latestSuggestionInput.current = { kind: nextKind, query: query.trim() };
              setKind(nextKind);
              persistEntityKind(nextKind);
            }}
          >
            {Object.entries(KIND_LABELS).map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
        </label>
        <label className="entity-search-input">
          <span>Entidad</span>
          <div>
            <Search size={16} />
            <input
              value={query}
              onChange={(event) => {
                const nextQuery = event.target.value;
                suggestionSequence.current += 1;
                latestSuggestionInput.current = { kind, query: nextQuery.trim() };
                setSuggestions([]);
                setSuggestionsChecked(false);
                setError(null);
                if (nextQuery.trim().length < 3) {
                  setLoading(false);
                }
                setQuery(nextQuery);
              }}
              placeholder="Ej. IBERDROLA"
            />
          </div>
        </label>
        <button className="vector-primary" disabled={query.trim().length < 3 || loading}>
          {loading ? <RefreshCw size={15} /> : <Network size={15} />}
          Abrir grafo
        </button>
      </form>
      {error && <p className="auth-inline-error" role="alert">{error}</p>}
      {kind === "person" && suggestionsChecked && !loading && !error && suggestions.length === 0 && query.trim().length >= 3 && (
        <p className="entity-search-help">
          Las personas se registran por apellidos y nombre (p. ej. BURGOS CANTO MIGUEL).
          Probamos ambos órdenes automáticamente.
        </p>
      )}
      {suggestions.length > 0 && (
        <div className="entity-suggestions" aria-label="Sugerencias de entidades">
          {suggestions.map((item) => (
            <button type="button" key={item} onClick={() => openEntity(item)}>
              {item}
            </button>
          ))}
        </div>
      )}
    </section>
  );
}

function nodeIdentity(node: EntityIntelGraphNode, index: number): string {
  const value = node.id ?? node.norm ?? node.name ?? node.label ?? `node-${index}`;
  return String(value);
}

function nodeLabel(node: EntityIntelGraphNode): string {
  const value = node.label ?? node.name ?? node.norm ?? node.id;
  return String(value ?? "Entidad");
}

function stableHash(value: string): number {
  let hash = 2166136261;
  for (let index = 0; index < value.length; index += 1) {
    hash ^= value.charCodeAt(index);
    hash = Math.imul(hash, 16777619);
  }
  return hash >>> 0;
}

function seededInitialPosition(
  id: string,
  index: number,
  node: EntityIntelGraphNode,
): cytoscape.Position {
  if (node.is_center === true) return { x: 0, y: 0 };
  const ordinal = Math.max(1, index + 1);
  const jitter = (stableHash(id) % 1024) / 1024;
  const angle = (ordinal + jitter) * GRAPH_SEED_GOLDEN_ANGLE;
  const radius = GRAPH_SEED_RADIUS * Math.sqrt(ordinal);
  return {
    x: Math.round(Math.cos(angle) * radius * 100) / 100,
    y: Math.round(Math.sin(angle) * radius * 100) / 100,
  };
}

function edgeRole(edge: EntityIntelGraphEdge): string {
  if (Array.isArray(edge.roles)) return edge.roles.join(", ");
  return String(edge.role ?? edge.roles ?? "Relación");
}

function parseEdgeDate(value: unknown): number | null {
  if (typeof value !== "string" || !value.trim()) return null;
  const match = /^(\d{4})-(\d{2})-(\d{2})/.exec(value.trim());
  if (!match) return null;
  const [, year, month, day] = match;
  return Date.UTC(Number(year), Number(month) - 1, Number(day));
}

function formatTimelineDate(timestamp: number): string {
  return new Date(timestamp).toLocaleDateString("es-ES");
}

function timelineDateFromOffset(bounds: TemporalBounds, offset: number): number {
  return bounds.min + offset * DAY_MS;
}

function temporalBoundsFor(graph: EntityIntelGraphResponse | null): TemporalBounds | null {
  if (!graph) return null;
  const dates = graph.edges.flatMap((edge) => {
    const timestamp = parseEdgeDate(edge.date);
    return timestamp === null ? [] : [timestamp];
  });
  if (!dates.length) return null;
  const min = Math.min(...dates);
  const max = Math.max(...dates);
  return {
    min,
    max,
    maxOffset: Math.max(0, Math.round((max - min) / DAY_MS)),
    datedEdges: dates.length,
    undatedEdges: graph.edges.length - dates.length,
  };
}

function nodeKind(node: EntityIntelGraphNode | null | undefined): EntityIntelKind {
  return node?.type === "person" || node?.entityType === "person" ? "person" : "company";
}

function graphElements(graph: EntityIntelGraphResponse): cytoscape.ElementDefinition[] {
  const known = new Set<string>();
  const nodes = graph.nodes.map((node, index) => {
    const id = nodeIdentity(node, index);
    known.add(id);
    return {
      data: {
        ...node,
        id,
        label: nodeLabel(node),
        entityType: String(node.type ?? "entity"),
      },
      position: seededInitialPosition(id, index, node),
      classes: node.is_center === true ? "is-center-node" : undefined,
    };
  });
  const edges = graph.edges.flatMap((edge, index) => {
    const source = String(edge.source);
    const target = String(edge.target);
    if (!known.has(source) || !known.has(target)) return [];
    return [
      {
        data: {
          ...edge,
          id: String(edge.id ?? `${source}-${target}-${index}`),
          source,
          target,
          label: edgeRole(edge),
        },
        classes: edge.active === false ? "is-inactive-edge" : undefined,
      },
    ];
  });
  return [...nodes, ...edges];
}

function selectedDescription(item: EntityIntelGraphNode | null): string {
  if (!item) return "Selecciona un nodo del grafo para ver sus datos básicos.";
  const degree = typeof item.degree === "number" ? ` · ${item.degree} relaciones` : "";
  return `${nodeLabel(item)}${degree}`;
}

function selectedNodeIdentity(
  graph: EntityIntelGraphResponse,
  item: EntityIntelGraphNode,
): string {
  const explicit = item.id ?? item.norm ?? item.name ?? item.label;
  if (explicit !== undefined && explicit !== null) return String(explicit);
  const exactIndex = graph.nodes.findIndex((node) => node === item);
  if (exactIndex >= 0) return nodeIdentity(item, exactIndex);
  const matchingIndex = graph.nodes.findIndex(
    (node) => nodeLabel(node) === nodeLabel(item) && nodeKind(node) === nodeKind(item),
  );
  return nodeIdentity(item, matchingIndex >= 0 ? matchingIndex : -1);
}

function directRelations(
  graph: EntityIntelGraphResponse | null,
  item: EntityIntelGraphNode | null,
): EntityDetailRelation[] {
  if (!graph || !item) return [];
  const selectedId = selectedNodeIdentity(graph, item);
  const nodes = new Map(
    graph.nodes.map((node, index) => [nodeIdentity(node, index), node]),
  );
  return graph.edges.flatMap((edge, index) => {
    const source = String(edge.source);
    const target = String(edge.target);
    const otherId = source === selectedId ? target : target === selectedId ? source : null;
    if (!otherId) return [];
    const other = nodes.get(otherId);
    if (!other) return [];
    return [{
      id: String(edge.id ?? `${source}-${target}-${index}`),
      label: nodeLabel(other),
      routeName: String(other.norm ?? other.name ?? other.label ?? other.id ?? nodeLabel(other)),
      kind: nodeKind(other),
      role: edgeRole(edge),
      date: typeof edge.date === "string" ? edge.date : null,
      active: typeof edge.active === "boolean" ? edge.active : null,
      degree: typeof other.degree === "number" ? other.degree : null,
    }];
  });
}

function initialGraphFocus(instance: cytoscape.Core) {
  const centerNodes = instance.nodes(".is-center-node");
  const center = centerNodes.length > 0 ? centerNodes : instance.nodes().first();
  if (center.length === 0) return;
  const neighborhood = center.closedNeighborhood();
  const denseGraph = neighborhood.length > MAX_INITIAL_FOCUS_ELEMENTS;
  const container = instance.container();
  const bounds = container?.getBoundingClientRect();
  const renderedPosition = bounds
    ? { x: bounds.width / 2, y: bounds.height / 2 }
    : undefined;
  const preferredZoom = denseGraph
    ? MIN_READABLE_GRAPH_ZOOM
    : MAX_MANAGEABLE_INITIAL_ZOOM;
  const nextZoom = Math.min(instance.maxZoom(), Math.max(preferredZoom, MIN_READABLE_GRAPH_ZOOM));
  instance.zoom(renderedPosition ? { level: nextZoom, renderedPosition } : nextZoom);
  instance.center(center);
}

function applyTemporalGraphFilter(
  instance: cytoscape.Core,
  bounds: TemporalBounds | null,
  range: [number, number] | null,
) {
  const start = bounds && range ? timelineDateFromOffset(bounds, range[0]) : null;
  const end = bounds && range ? timelineDateFromOffset(bounds, range[1]) : null;
  instance.batch(() => {
    instance.edges().forEach((edge: cytoscape.EdgeSingular) => {
      edge.removeClass("is-time-filtered is-undated");
      const timestamp = parseEdgeDate(edge.data("date"));
      if (timestamp === null) {
        edge.addClass("is-undated");
        return;
      }
      if (start !== null && end !== null && (timestamp < start || timestamp > end)) {
        edge.addClass("is-time-filtered");
      }
    });
    instance.nodes().forEach((node: cytoscape.NodeSingular) => {
      node.removeClass("is-orphaned-after-filter");
      if (node.data("is_center") === true) return;
      const visibleEdges = node
        .connectedEdges()
        .filter((edge: cytoscape.EdgeSingular) => !edge.hasClass("is-time-filtered"));
      if (visibleEdges.length === 0) node.addClass("is-orphaned-after-filter");
    });
  });
}

export function EntityGraphExplorer({
  name,
  type,
  initialGraph = null,
  embedded = false,
}: {
  name: string;
  type: EntityIntelKind;
  initialGraph?: EntityIntelGraphResponse | null;
  embedded?: boolean;
}) {
  const router = useRouter();
  const containerRef = useRef<HTMLDivElement | null>(null);
  const graphRef = useRef<cytoscape.Core | null>(null);
  const temporalBoundsRef = useRef<TemporalBounds | null>(null);
  const timeRangeRef = useRef<[number, number] | null>(null);
  const returnFocusRef = useRef<HTMLDivElement | null>(null);
  const [activeOnly, setActiveOnly] = useState(false);
  const [graph, setGraph] = useState<EntityIntelGraphResponse | null>(initialGraph);
  const [selected, setSelected] = useState<EntityIntelGraphNode | null>(null);
  const [detailOpen, setDetailOpen] = useState(false);
  const [loading, setLoading] = useState(!initialGraph);
  const [error, setError] = useState<string | null>(null);
  const [zoomPercent, setZoomPercent] = useState(100);
  const [timeFilter, setTimeFilter] = useState<TimeFilterState | null>(null);

  const loadGraph = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const result = await api.entityIntel.graph({
        name,
        type,
        depth: 2,
        activeOnly,
      });
      setGraph(result);
      setSelected(null);
    } catch (reason) {
      setGraph(null);
      setError(problemMessage(reason, "No se pudo cargar el grafo de la entidad."));
    } finally {
      setLoading(false);
    }
  }, [activeOnly, name, type]);

  useEffect(() => {
    if (initialGraph && !activeOnly) {
      const handle = window.setTimeout(() => {
        setGraph(initialGraph);
        setSelected(null);
        setLoading(false);
      }, 0);
      return () => window.clearTimeout(handle);
    }
    const kickoff = window.setTimeout(() => void loadGraph(), 0);
    return () => window.clearTimeout(kickoff);
  }, [activeOnly, initialGraph, loadGraph]);

  const elements = useMemo(() => (graph ? graphElements(graph) : []), [graph]);
  const temporalBounds = useMemo(() => temporalBoundsFor(graph), [graph]);
  const temporalKey = temporalBounds
    ? `${temporalBounds.min}:${temporalBounds.max}:${temporalBounds.maxOffset}`
    : null;
  const timeRange = temporalBounds
    ? timeFilter?.key === temporalKey
      ? timeFilter.range
      : [0, temporalBounds.maxOffset] satisfies [number, number]
    : null;
  const visibleEdgeCount = useMemo(() => {
    if (!graph) return 0;
    if (!temporalBounds || !timeRange) return graph.edges.length;
    const start = timelineDateFromOffset(temporalBounds, timeRange[0]);
    const end = timelineDateFromOffset(temporalBounds, timeRange[1]);
    return graph.edges.filter((edge) => {
      const timestamp = parseEdgeDate(edge.date);
      return timestamp === null || (timestamp >= start && timestamp <= end);
    }).length;
  }, [graph, temporalBounds, timeRange]);

  useEffect(() => {
    temporalBoundsRef.current = temporalBounds;
    timeRangeRef.current = timeRange;
  }, [temporalBounds, timeRange]);

  const zoomGraph = useCallback((factor: number) => {
    const instance = graphRef.current;
    if (!instance) return;
    const container = instance.container();
    const bounds = container?.getBoundingClientRect();
    const renderedPosition = bounds
      ? { x: bounds.width / 2, y: bounds.height / 2 }
      : undefined;
    const nextZoom = Math.min(instance.maxZoom(), Math.max(instance.minZoom(), instance.zoom() * factor));
    instance.zoom(renderedPosition ? { level: nextZoom, renderedPosition } : nextZoom);
    setZoomPercent(Math.round(instance.zoom() * 100));
  }, []);

  const resetGraphFocus = useCallback(() => {
    const instance = graphRef.current;
    if (!instance) return;
    initialGraphFocus(instance);
    setZoomPercent(Math.round(instance.zoom() * 100));
  }, []);

  useEffect(() => {
    if (!containerRef.current || !graph || elements.length === 0) return undefined;
    let cancelled = false;
    let cleanupHandlers: (() => void) | null = null;
    let focusTimer: number | null = null;
    void Promise.all([import("cytoscape"), import("cytoscape-fcose")]).then(
      ([cytoscapeModule, fcoseModule]) => {
        if (cancelled || !containerRef.current) return;
        const cytoscapeFactory = cytoscapeModule.default;
        if (!fcoseRegistered) {
          cytoscapeFactory.use(fcoseModule.default);
          fcoseRegistered = true;
        }
        graphRef.current?.destroy();
        const reducedMotion = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ?? false;
        const instance = cytoscapeFactory({
          container: containerRef.current,
          elements,
          minZoom: 0.35,
          maxZoom: 2.2,
          style: [
            {
              selector: "node",
              style: {
                "background-color": "#2563eb",
                "border-color": "#dbeafe",
                "border-width": 2,
                color: "#102033",
                "font-size": 9,
                label: "data(label)",
                "min-zoomed-font-size": 6,
                "overlay-opacity": 0,
                "text-background-color": "#ffffff",
                "text-background-opacity": 0.86,
                "text-background-padding": "2px",
                "text-margin-y": -8,
                "text-max-width": "130px",
                "text-wrap": "wrap",
                height: 30,
                opacity: 1,
                "transition-duration": reducedMotion ? 0 : 140,
                "transition-property": "border-width, overlay-opacity, width, height, opacity",
                width: 30,
              },
            },
            {
              selector: 'node[entityType = "person"]',
              style: { "background-color": "#7c3aed" },
            },
            {
              selector: "node.is-center-node",
              style: {
                "background-color": "#0891b2",
                "border-color": "#0f172a",
                "border-width": 3,
                height: 46,
                width: 46,
              },
            },
            {
              selector: "edge",
              style: {
                "curve-style": "bezier",
                "font-size": 7,
                label: "data(label)",
                "line-color": "#9fb2c8",
                "target-arrow-color": "#9fb2c8",
                "target-arrow-shape": "triangle",
                "text-background-color": "#ffffff",
                "text-background-opacity": 0.75,
                "text-rotation": "autorotate",
                opacity: 1,
                "transition-duration": reducedMotion ? 0 : 140,
                "transition-property": "line-color, opacity, width",
                width: 1.2,
              },
            },
            {
              selector: "edge.is-inactive-edge",
              style: {
                "line-style": "dashed",
                opacity: 0.46,
              },
            },
            {
              selector: "edge.is-undated",
              style: {
                "line-style": "dotted",
                "line-color": "#64748b",
                "target-arrow-color": "#64748b",
              },
            },
            {
              selector: ".is-time-filtered",
              style: {
                display: "none",
              },
            },
            {
              selector: "node.is-orphaned-after-filter",
              style: {
                display: "none",
              },
            },
            {
              selector: ".is-hovered",
              style: {
                "border-width": 5,
                "overlay-color": "#1d56d8",
                "overlay-opacity": 0.12,
                height: 34,
                width: 34,
              },
            },
            {
              selector: "node.is-center-node.is-hovered",
              style: { height: 50, width: 50 },
            },
            {
              selector: ".is-dimmed",
              style: { opacity: 0.18 },
            },
            {
              selector: ":selected",
              style: {
                "background-color": "#f59e0b",
                "line-color": "#f59e0b",
                "target-arrow-color": "#f59e0b",
              },
            },
          ],
          layout: {
            name: "fcose",
            animate: false,
            fit: false,
            nodeSeparation: GRAPH_FIXED_NODE_SEPARATION,
            idealEdgeLength: GRAPH_FIXED_EDGE_LENGTH,
            edgeElasticity: 0.28,
            gravity: 0.12,
            gravityRange: 3.8,
            nestingFactor: 0.9,
            numIter: 1800,
            padding: 42,
            randomize: false,
          } as cytoscape.LayoutOptions,
        });
        const clearHover = () => {
          if (containerRef.current) containerRef.current.style.cursor = "";
          instance.elements().removeClass("is-hovered is-dimmed");
        };
        const applyHover = (node: cytoscape.NodeSingular) => {
          clearHover();
          if (containerRef.current) containerRef.current.style.cursor = "pointer";
          const neighborhood = node.closedNeighborhood();
          instance.elements().not(neighborhood).addClass("is-dimmed");
          node.addClass("is-hovered");
        };
        const onMouseOver = (event: cytoscape.EventObject) => applyHover(event.target as cytoscape.NodeSingular);
        const onMouseOut = () => clearHover();
        let lastTap: { id: string; at: number } | null = null;
        const onTap = (event: cytoscape.EventObject) => {
          const node = event.target.data() as EntityIntelGraphNode;
          const id = String(node.id ?? node.norm ?? node.name ?? node.label ?? "");
          const now = Date.now();
          const isDoubleTap = lastTap?.id === id && now - lastTap.at <= GRAPH_DOUBLE_TAP_MS;
          lastTap = { id, at: now };
          setSelected(node);
          if (isDoubleTap) setDetailOpen(true);
        };
        const applyInitialFocus = () => {
          initialGraphFocus(instance);
          applyTemporalGraphFilter(instance, temporalBoundsRef.current, timeRangeRef.current);
          setZoomPercent(Math.round(instance.zoom() * 100));
        };
        const onZoom = () => setZoomPercent(Math.round(instance.zoom() * 100));
        const container = containerRef.current;
        container.addEventListener("mouseleave", clearHover);
        instance.on("mouseover", "node", onMouseOver);
        instance.on("mouseout", "node", onMouseOut);
        instance.on("tap", "node", onTap);
        instance.on("zoom", onZoom);
        instance.on("layoutstop", applyInitialFocus);
        graphRef.current = instance;
        focusTimer = window.setTimeout(applyInitialFocus, 900);
        cleanupHandlers = () => {
          container.removeEventListener("mouseleave", clearHover);
          instance.removeListener("mouseover", "node", onMouseOver);
          instance.removeListener("mouseout", "node", onMouseOut);
          instance.removeListener("tap", "node", onTap);
          instance.removeListener("zoom", onZoom);
          instance.removeListener("layoutstop", applyInitialFocus);
        };
      },
    );
    return () => {
      cancelled = true;
      if (focusTimer !== null) window.clearTimeout(focusTimer);
      cleanupHandlers?.();
      graphRef.current?.destroy();
      graphRef.current = null;
    };
  }, [elements, graph]);

  useEffect(() => {
    if (!graphRef.current) return;
    applyTemporalGraphFilter(graphRef.current, temporalBounds, timeRange);
  }, [temporalBounds, timeRange]);

  const relations = useMemo(() => directRelations(graph, selected), [graph, selected]);
  const openSelectedDetail = useCallback(() => {
    if (selected) setDetailOpen(true);
  }, [selected]);

  return (
    <div className={embedded ? "entity-intel-page embedded" : "entity-intel-page"}>
      {!embedded && (
        <>
          <section className="page-heading">
            <div>
              <div className="eyebrow">Actores · grafo de entidad</div>
              <h1>{name}</h1>
              <p>
                Exploración básica de relaciones desde Signal. Incluye vínculos activos y cesados
                del BORME, sin interpretar capital social ni porcentajes accionariales.
              </p>
            </div>
            <button className="vector-secondary" disabled={loading} onClick={() => void loadGraph()}>
              <RefreshCw size={15} />
              Actualizar grafo
            </button>
          </section>
          <EntitySearchPanel initialQuery={name} initialKind={type} compact />
        </>
      )}
      {error && <div className="inline-error" role="alert">{error}</div>}
      <section className="entity-graph-shell" aria-busy={loading}>
        <header>
          <div>
            <span className="section-kicker">Grafo</span>
            <h2>Relaciones detectadas</h2>
          </div>
          <div className="entity-graph-metrics">
            <label className="entity-active-toggle">
              <input
                type="checkbox"
                checked={activeOnly}
                onChange={(event) => setActiveOnly(event.target.checked)}
              />
              Solo vínculos activos
            </label>
            <span>{graph?.nodes.length ?? 0} nodos</span>
            <span>{graph?.edges.length ?? 0} enlaces</span>
            {graph?.cache_hit && <span>Caché activo</span>}
            <button className="vector-secondary small" disabled={loading} onClick={() => void loadGraph()}>
              <RefreshCw size={14} />
              Actualizar
            </button>
          </div>
        </header>
        {loading ? (
          <div className="global-inventory-state" role="status">
            Cargando grafo de entidad…
          </div>
        ) : graph && elements.length > 0 ? (
          <div className="entity-graph-layout">
            <div className="entity-graph-stage">
              <div className="entity-graph-controls" aria-label="Controles de zoom del grafo">
                <button type="button" aria-label="Acercar grafo" onClick={() => zoomGraph(1.22)}>
                  +
                </button>
                <button type="button" aria-label="Alejar grafo" onClick={() => zoomGraph(0.82)}>
                  −
                </button>
                <button type="button" aria-label="Volver al encuadre inicial" onClick={resetGraphFocus}>
                  Reencuadrar
                </button>
                <span aria-live="polite">Zoom {zoomPercent}%</span>
              </div>
              <div
                ref={containerRef}
                tabIndex={0}
                className="entity-graph-canvas"
                aria-label={`Grafo de relaciones de ${name}`}
                onKeyDown={(event) => {
                  if (event.key !== "Enter" && event.key !== " ") return;
                  if (!selected) return;
                  event.preventDefault();
                  openSelectedDetail();
                }}
              />
            </div>
            <aside className="entity-graph-side">
              <h3>Lectura rápida</h3>
              <p>{selectedDescription(selected)}</p>
              <dl>
                <div>
                  <dt>Tipo consultado</dt>
                  <dd>{KIND_LABELS[type]}</dd>
                </div>
                <div>
                  <dt>Profundidad</dt>
                  <dd>2 niveles · {activeOnly ? "solo vínculos activos" : "activos y cesados"}</dd>
                </div>
                <div>
                  <dt>Encuadre inicial</dt>
                  <dd>Centro legible; primer nivel si no satura la vista</dd>
                </div>
                <div>
                  <dt>Origen</dt>
                  <dd>Signal vía Flask</dd>
                </div>
              </dl>
              {temporalBounds && timeRange ? (
                <section className="entity-time-filter" aria-label="Cronograma del grafo">
                  <h3>Cronograma</h3>
                  <p>
                    {visibleEdgeCount} de {graph.edges.length} vínculos visibles. Los vínculos sin
                    fecha se mantienen visibles; los nodos sin vínculos dentro del rango se ocultan,
                    sin relayout.
                  </p>
                  <label>
                    <span>Desde {formatTimelineDate(timelineDateFromOffset(temporalBounds, timeRange[0]))}</span>
                    <input
                      aria-label="Fecha inicial del cronograma"
                      type="range"
                      min={0}
                      max={temporalBounds.maxOffset}
                      value={timeRange[0]}
                      onChange={(event) => {
                        const next = Number(event.target.value);
                        const nextKey = temporalKey ?? "";
                        setTimeFilter((current) => {
                          const [, end] = current?.key === nextKey
                            ? current.range
                            : [0, temporalBounds.maxOffset];
                          return {
                            key: nextKey,
                            range: [Math.min(next, end), end],
                          };
                        });
                      }}
                    />
                  </label>
                  <label>
                    <span>Hasta {formatTimelineDate(timelineDateFromOffset(temporalBounds, timeRange[1]))}</span>
                    <input
                      aria-label="Fecha final del cronograma"
                      type="range"
                      min={0}
                      max={temporalBounds.maxOffset}
                      value={timeRange[1]}
                      onChange={(event) => {
                        const next = Number(event.target.value);
                        const nextKey = temporalKey ?? "";
                        setTimeFilter((current) => {
                          const [start] = current?.key === nextKey
                            ? current.range
                            : [0, temporalBounds.maxOffset];
                          return {
                            key: nextKey,
                            range: [start, Math.max(next, start)],
                          };
                        });
                      }}
                    />
                  </label>
                  <small>
                    {temporalBounds.datedEdges} vínculos fechados · {temporalBounds.undatedEdges} sin fecha.
                    {activeOnly ? " Combinado con «Solo vínculos activos»: el rango se aplica sobre vínculos activos ya cargados." : " Incluye vínculos activos y cesados."}
                  </small>
                </section>
              ) : (
                <p className="entity-graph-note">
                  Este grafo no trae fechas en sus vínculos; el cronograma no puede acotar el rango.
                </p>
              )}
              {graph.truncated && (
                <p className="entity-graph-warning">
                  <Sparkles size={14} />
                  Signal recortó el grafo para mantener la consulta manejable.
                </p>
              )}
              {graph.note && <p className="entity-graph-note">{graph.note}</p>}
              <div className="entity-graph-legend" aria-label="Leyenda">
                <span><i className="company" /> Empresa</span>
                <span><i className="person" /> Persona</span>
                <span><i className="center" /> Entidad central</span>
                <span><i className="inactive" /> Vínculo cesado</span>
                <span><i className="undated" /> Vínculo sin fecha</span>
              </div>
            </aside>
          </div>
        ) : (
          <div className="global-inventory-state">
            <strong>No hay relaciones visibles</strong>
            <p>Prueba con otra entidad sugerida o actualiza la consulta.</p>
          </div>
        )}
      </section>
      <div ref={returnFocusRef} tabIndex={-1} aria-hidden="true" />
      <EntityDetailDialog
        open={detailOpen}
        entity={selected}
        relations={relations}
        returnFocusRef={returnFocusRef}
        onOpenChange={setDetailOpen}
        onNavigate={(nextKind, nextName) => {
          setDetailOpen(false);
          router.push(entityRoute(nextKind, nextName));
        }}
      />
    </div>
  );
}
