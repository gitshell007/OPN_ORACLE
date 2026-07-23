"use client";

import {
  ApiError,
  api,
  type EntityIntelGraphEdge,
  type EntityIntelGraphNode,
  type EntityIntelGraphResponse,
  type EntityIntelKind,
} from "@oracle/api-client";
import { CircleHelp, Network, RefreshCw, Search, Sparkles } from "lucide-react";
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
import { graphNodeDepths, separateGraphNodePositions } from "./entity-graph-layout";

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
const GRAPH_FIXED_NODE_SEPARATION = 156;
const GRAPH_FIXED_EDGE_LENGTH = 250;
const GRAPH_SEED_GOLDEN_ANGLE = Math.PI * (3 - Math.sqrt(5));
const GRAPH_SEED_RADIUS = 58;
const GRAPH_PRIORITY_LABEL_LIMIT = 8;
const GRAPH_ALL_LABELS_MIN_ZOOM = 1.5;
const GRAPH_FOCUS_PADDING = 72;
const GRAPH_NODE_RADIUS = 15;
const GRAPH_CENTER_NODE_RADIUS = 23;
const SMALL_GRAPH_LABEL_NODE_LIMIT = 12;
const SMALL_GRAPH_LABEL_EDGE_LIMIT = 16;
const GRAPH_HIDDEN_CLASSES = [
  "is-time-filtered",
  "is-role-filtered",
  "is-depth-filtered",
  "is-focus-filtered",
] as const;

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

interface RoleFilterOption {
  key: string;
  label: string;
  count: number;
  category: GraphRoleCategory | null;
}

interface RoleCategoryOption {
  key: GraphRoleCategory;
  label: string;
  count: number;
  roleKeys: string[];
}

interface RoleFilterState {
  key: string;
  enabledKeys: string[];
}

type GraphLabelDensity = "essential" | "adaptive" | "all";
type IsolationCameraIntent = "focus" | "restore";
type GraphRoleCategory = NonNullable<EntityIntelGraphEdge["role_categories"]>[number];

interface GraphRoleEntry {
  key: string;
  label: string;
  category: GraphRoleCategory | null;
}

const GRAPH_ROLE_CATEGORY_ORDER: GraphRoleCategory[] = [
  "governance",
  "representation",
  "audit",
  "ownership",
  "liquidation",
  "other",
];
const GRAPH_ROLE_CATEGORY_META: Record<
  GraphRoleCategory,
  { label: string; className: string }
> = {
  governance: { label: "Gobierno", className: "governance" },
  representation: { label: "Representación", className: "representation" },
  audit: { label: "Auditoría", className: "audit" },
  ownership: { label: "Propiedad", className: "ownership" },
  liquidation: { label: "Liquidación", className: "liquidation" },
  other: { label: "Sin clasificar", className: "other" },
};
const GRAPH_ROLE_CATEGORY_SET = new Set<GraphRoleCategory>(GRAPH_ROLE_CATEGORY_ORDER);

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

function separateGraphNodes(instance: cytoscape.Core) {
  const graphNodes: cytoscape.NodeSingular[] = [];
  instance.nodes().forEach((node: cytoscape.NodeSingular) => {
    graphNodes.push(node);
  });
  const centerId = graphNodes.find((node) => node.data("is_center") === true)?.id();
  const separated = separateGraphNodePositions(graphNodes.map((node) => ({
    id: node.id(),
    x: node.position("x"),
    y: node.position("y"),
    radius: node.data("is_center") === true ? GRAPH_CENTER_NODE_RADIUS : GRAPH_NODE_RADIUS,
    anchored: node.id() === centerId,
  })));
  const positionsById = new Map(separated.map((node) => [node.id, { x: node.x, y: node.y }]));
  instance.batch(() => {
    graphNodes.forEach((node) => {
      const position = positionsById.get(node.id());
      if (position) node.position(position);
    });
  });
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

function edgeRoleValues(edge: EntityIntelGraphEdge): string[] {
  const values = Array.isArray(edge.roles)
    ? edge.roles
    : [edge.role ?? edge.roles ?? "Relación"];
  const normalized = values
    .map((value) => String(value).trim().replace(/\s+/g, " "))
    .filter(Boolean);
  return normalized.length > 0 ? normalized : ["Relación"];
}

function edgeRole(edge: EntityIntelGraphEdge): string {
  return edgeRoleValues(edge).join(", ");
}

function primaryRoleCategory(edge: EntityIntelGraphEdge): GraphRoleCategory | null {
  return canonicalRoleCategories(edge)[0] ?? null;
}

function normalizedRoleKey(role: string): string {
  return role.normalize("NFKC").trim().replace(/\s+/g, " ").toLocaleLowerCase("es-ES");
}

function displayRole(role: string): string {
  const clean = role.trim().replace(/\s+/g, " ");
  return clean ? `${clean[0].toLocaleUpperCase("es-ES")}${clean.slice(1)}` : "Relación";
}

function canonicalRoleKeys(edge: EntityIntelGraphEdge): string[] {
  const keys = edge.role_keys;
  if (!Array.isArray(keys)) return [];
  return keys
    .map((key) => (typeof key === "string" ? key.trim() : ""))
    .filter(Boolean);
}

function canonicalRoleCategories(edge: EntityIntelGraphEdge): GraphRoleCategory[] {
  const categories = edge.role_categories;
  if (!Array.isArray(categories)) return [];
  return categories.filter(
    (category): category is GraphRoleCategory => GRAPH_ROLE_CATEGORY_SET.has(category),
  );
}

function edgeRoleEntries(edge: EntityIntelGraphEdge): GraphRoleEntry[] {
  const labels = edgeRoleValues(edge);
  const keys = canonicalRoleKeys(edge);
  const categories = canonicalRoleCategories(edge);
  if (keys.length === 0) {
    return labels.map((label) => ({
      key: normalizedRoleKey(label),
      label,
      category: null,
    }));
  }
  return keys.map((key, index) => ({
    key,
    label: labels[index] ?? labels[0] ?? "Relación",
    category: categories[index] ?? null,
  }));
}

function normalizedEntityIdentity(value: unknown): string | null {
  if (typeof value !== "string" && typeof value !== "number") return null;
  const normalized = String(value)
    .normalize("NFKC")
    .trim()
    .replace(/\s+/g, " ")
    .toLocaleLowerCase("es-ES");
  return normalized || null;
}

function graphNodeIdentityValues(node: EntityIntelGraphNode, index: number): Set<string> {
  return new Set(
    [nodeIdentity(node, index), node.id, node.norm, node.name, node.label]
      .map(normalizedEntityIdentity)
      .filter((value): value is string => value !== null),
  );
}

function graphCenterCandidates(graph: EntityIntelGraphResponse, queryName: string): Set<string> {
  const explicitCenter = graph.center;
  const explicitValues = explicitCenter && typeof explicitCenter === "object"
    ? Object.values(explicitCenter as Record<string, unknown>)
    : [explicitCenter];
  return new Set(
    [...explicitValues, queryName]
      .map(normalizedEntityIdentity)
      .filter((value): value is string => value !== null),
  );
}

export function graphRoleOptions(graph: EntityIntelGraphResponse | null): RoleFilterOption[] {
  if (!graph) return [];
  const roles = new Map<string, RoleFilterOption>();
  graph.edges.forEach((edge) => {
    const uniqueRoles = new Map<string, GraphRoleEntry>();
    edgeRoleEntries(edge).forEach((entry) => uniqueRoles.set(entry.key, entry));
    uniqueRoles.forEach((role, key) => {
      const current = roles.get(key);
      roles.set(key, {
        key,
        label: current?.label ?? displayRole(role.label),
        count: (current?.count ?? 0) + 1,
        category: current?.category ?? role.category,
      });
    });
  });
  return [...roles.values()].sort(
    (left, right) => right.count - left.count || left.label.localeCompare(right.label, "es"),
  );
}

export function graphRoleCategoryOptions(
  graph: EntityIntelGraphResponse | null,
): RoleCategoryOption[] {
  if (!graph) return [];
  const categories = new Map<
    GraphRoleCategory,
    { count: number; roleKeys: Set<string> }
  >();
  graph.edges.forEach((edge) => {
    const edgeCategories = new Map<GraphRoleCategory, Set<string>>();
    edgeRoleEntries(edge).forEach(({ key, category }) => {
      if (category === null) return;
      const roleKeys = edgeCategories.get(category) ?? new Set<string>();
      roleKeys.add(key);
      edgeCategories.set(category, roleKeys);
    });
    edgeCategories.forEach((roleKeys, category) => {
      const current = categories.get(category) ?? { count: 0, roleKeys: new Set<string>() };
      roleKeys.forEach((key) => current.roleKeys.add(key));
      current.count += 1;
      categories.set(category, current);
    });
  });
  return GRAPH_ROLE_CATEGORY_ORDER.flatMap((category) => {
    const current = categories.get(category);
    if (!current) return [];
    return [{
      key: category,
      label: GRAPH_ROLE_CATEGORY_META[category].label,
      count: current.count,
      roleKeys: [...current.roleKeys],
    }];
  });
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

function priorityLabelNodeIds(
  graph: EntityIntelGraphResponse,
  centerId: string | null,
): Set<string> {
  const degrees = new Map<string, number>();
  graph.nodes.forEach((node, index) => degrees.set(nodeIdentity(node, index), 0));
  graph.edges.forEach((edge) => {
    const source = String(edge.source);
    const target = String(edge.target);
    if (degrees.has(source)) degrees.set(source, (degrees.get(source) ?? 0) + 1);
    if (degrees.has(target)) degrees.set(target, (degrees.get(target) ?? 0) + 1);
  });
  const ranked = graph.nodes
    .map((node, index) => {
      const id = nodeIdentity(node, index);
      return {
        id,
        center: id === centerId,
        degree: Math.max(degrees.get(id) ?? 0, typeof node.degree === "number" ? node.degree : 0),
      };
    })
    .sort((left, right) => (
      Number(right.center) - Number(left.center)
      || right.degree - left.degree
      || left.id.localeCompare(right.id, "es")
    ));
  return new Set(ranked.slice(0, GRAPH_PRIORITY_LABEL_LIMIT).map((node) => node.id));
}

function graphElements(
  graph: EntityIntelGraphResponse,
  queryName: string,
): cytoscape.ElementDefinition[] {
  const known = new Set<string>();
  const centerId = graphCenterId(graph, queryName);
  const priorityLabels = priorityLabelNodeIds(graph, centerId);
  const nodes = graph.nodes.map((node, index) => {
    const id = nodeIdentity(node, index);
    const isCenter = id === centerId;
    known.add(id);
    const classes = [
      isCenter ? "is-center-node" : "",
      priorityLabels.has(id) ? "is-priority-label" : "",
    ].filter(Boolean).join(" ");
    return {
      data: {
        ...node,
        id,
        label: nodeLabel(node),
        entityType: String(node.type ?? "entity"),
        is_center: isCenter,
      },
      position: seededInitialPosition(id, index, { ...node, is_center: isCenter }),
      classes: classes || undefined,
    };
  });
  const edges = graph.edges.flatMap((edge, index) => {
    const source = String(edge.source);
    const target = String(edge.target);
    if (!known.has(source) || !known.has(target)) return [];
    const roleCategory = primaryRoleCategory(edge);
    const classes = [
      edge.active === false ? "is-inactive-edge" : "",
      roleCategory
        ? `role-category-${GRAPH_ROLE_CATEGORY_META[roleCategory].className}`
        : "",
    ].filter(Boolean).join(" ");
    return [
      {
        data: {
          ...edge,
          id: String(edge.id ?? `${source}-${target}-${index}`),
          source,
          target,
          label: edgeRole(edge),
        },
        classes: classes || undefined,
      },
    ];
  });
  return [...nodes, ...edges];
}

function graphCenterId(graph: EntityIntelGraphResponse, queryName: string): string | null {
  const centerIndex = graph.nodes.findIndex((node) => node.is_center === true);
  if (centerIndex >= 0) return nodeIdentity(graph.nodes[centerIndex], centerIndex);
  const candidates = graphCenterCandidates(graph, queryName);
  const matchingIndex = graph.nodes.findIndex((node, index) => {
    const values = graphNodeIdentityValues(node, index);
    return [...candidates].some((candidate) => values.has(candidate));
  });
  return matchingIndex >= 0 ? nodeIdentity(graph.nodes[matchingIndex], matchingIndex) : null;
}

function graphDepthMap(
  graph: EntityIntelGraphResponse | null,
  queryName: string,
): Map<string, number> {
  if (!graph) return new Map();
  const nodeIds = graph.nodes.map((node, index) => nodeIdentity(node, index));
  const centerId = graphCenterId(graph, queryName);
  return centerId ? graphNodeDepths(centerId, nodeIds, graph.edges) : new Map();
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
  const center = instance.nodes(".is-center-node");
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

function elementIsGraphHidden(element: cytoscape.SingularElementArgument): boolean {
  return GRAPH_HIDDEN_CLASSES.some((className) => element.hasClass(className));
}

function nodeIsGraphHidden(node: cytoscape.NodeSingular): boolean {
  return elementIsGraphHidden(node) || node.hasClass("is-orphaned-after-filter");
}

function defaultGraphLabelDensity(graph: EntityIntelGraphResponse | null): GraphLabelDensity {
  if (
    graph
    && graph.nodes.length <= SMALL_GRAPH_LABEL_NODE_LIMIT
    && graph.edges.length <= SMALL_GRAPH_LABEL_EDGE_LIMIT
  ) {
    return "all";
  }
  return "adaptive";
}

function applyGraphLabelDensity(
  instance: cytoscape.Core,
  density: GraphLabelDensity,
) {
  const elements = instance.elements();
  instance.batch(() => {
    elements.removeClass("is-readable-zoom is-all-label");
    if (density === "all") {
      elements.addClass("is-all-label");
    } else if (density === "adaptive" && instance.zoom() >= GRAPH_ALL_LABELS_MIN_ZOOM) {
      elements.addClass("is-readable-zoom");
    }
  });
}

interface GraphVisibilityCounts {
  edges: number;
  nodes: number;
}

function applyGraphVisibility(
  instance: cytoscape.Core,
  bounds: TemporalBounds | null,
  range: [number, number] | null,
  enabledRoleKeys: ReadonlySet<string>,
  nodeDepths: ReadonlyMap<string, number>,
  visibleDepthLimit: number | null,
  focusedNodeId: string | null,
): GraphVisibilityCounts {
  const start = bounds && range ? timelineDateFromOffset(bounds, range[0]) : null;
  const end = bounds && range ? timelineDateFromOffset(bounds, range[1]) : null;
  const focusedNodeIds = new Set(focusedNodeId ? [focusedNodeId] : []);
  let visibleEdgeCount = 0;
  let visibleNodeCount = 0;
  instance.batch(() => {
    instance.edges().forEach((edge: cytoscape.EdgeSingular) => {
      edge.removeClass("is-time-filtered is-role-filtered is-depth-filtered is-focus-filtered is-undated is-focus-label");
      const timestamp = parseEdgeDate(edge.data("date"));
      if (timestamp === null) {
        edge.addClass("is-undated");
      } else if (start !== null && end !== null && (timestamp < start || timestamp > end)) {
        edge.addClass("is-time-filtered");
      }
      const roleKeys = edgeRoleEntries(edge.data() as EntityIntelGraphEdge).map(({ key }) => key);
      if (!roleKeys.some((key) => enabledRoleKeys.has(key))) edge.addClass("is-role-filtered");
      const source = String(edge.data("source"));
      const target = String(edge.data("target"));
      const sourceDepth = nodeDepths.get(source);
      const targetDepth = nodeDepths.get(target);
      if (
        visibleDepthLimit !== null
        && (
          sourceDepth === undefined
          || targetDepth === undefined
          || sourceDepth > visibleDepthLimit
          || targetDepth > visibleDepthLimit
        )
      ) {
        edge.addClass("is-depth-filtered");
      }
      const touchesFocus = focusedNodeId !== null && (source === focusedNodeId || target === focusedNodeId);
      if (focusedNodeId !== null && !touchesFocus) edge.addClass("is-focus-filtered");
      if (touchesFocus && !elementIsGraphHidden(edge)) {
        focusedNodeIds.add(source);
        focusedNodeIds.add(target);
        edge.addClass("is-focus-label");
      }
      if (!elementIsGraphHidden(edge)) visibleEdgeCount += 1;
    });
    instance.nodes().forEach((node: cytoscape.NodeSingular) => {
      node.removeClass("is-orphaned-after-filter is-depth-filtered is-focus-filtered is-focus-label");
      const nodeId = String(node.id());
      const nodeDepth = nodeDepths.get(nodeId);
      if (
        visibleDepthLimit !== null
        && (nodeDepth === undefined || nodeDepth > visibleDepthLimit)
      ) {
        node.addClass("is-depth-filtered");
      }
      if (focusedNodeId !== null && !focusedNodeIds.has(nodeId)) {
        node.addClass("is-focus-filtered");
      }
      const connectedEdges = node.connectedEdges();
      const visibleEdges = connectedEdges
        .filter((edge: cytoscape.EdgeSingular) => !elementIsGraphHidden(edge));
      const anchorVisible = focusedNodeId === nodeId
        || (focusedNodeId === null && node.data("is_center") === true);
      if (
        connectedEdges.length > 0
        && visibleEdges.length === 0
        && !anchorVisible
      ) {
        node.addClass("is-orphaned-after-filter");
      }
      if (focusedNodeId !== null && focusedNodeIds.has(nodeId) && !elementIsGraphHidden(node)) {
        node.addClass("is-focus-label");
      }
      if (!nodeIsGraphHidden(node)) visibleNodeCount += 1;
    });
  });
  return { edges: visibleEdgeCount, nodes: visibleNodeCount };
}

function focusGraphNode(instance: cytoscape.Core, nodeId: string) {
  const node = instance.getElementById(nodeId);
  if (node.length === 0) return;
  const visibleNeighborhood = node
    .closedNeighborhood()
    .filter((element) => !elementIsGraphHidden(element));
  instance.fit(visibleNeighborhood, GRAPH_FOCUS_PADDING);
  if (instance.zoom() > 1.75) instance.zoom(1.75);
}

function fitVisibleGraph(instance: cytoscape.Core) {
  const visibleElements = instance.elements().filter(
    (element) => !elementIsGraphHidden(element) && !element.hasClass("is-orphaned-after-filter"),
  );
  if (visibleElements.length > 0) instance.fit(visibleElements, GRAPH_FOCUS_PADDING);
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
  const enabledRoleKeysRef = useRef<ReadonlySet<string>>(new Set());
  const nodeDepthsRef = useRef<ReadonlyMap<string, number>>(new Map());
  const visibleDepthLimitRef = useRef<number | null>(null);
  const selectedNodeIdRef = useRef<string | null>(null);
  const isolatedNodeIdRef = useRef<string | null>(null);
  const previousIsolatedNodeIdRef = useRef<string | null>(null);
  const isolationCameraIntentRef = useRef<IsolationCameraIntent | null>(null);
  const labelDensityRef = useRef<GraphLabelDensity>(defaultGraphLabelDensity(initialGraph));
  const returnFocusRef = useRef<HTMLDivElement | null>(null);
  const [activeOnly, setActiveOnly] = useState(false);
  const [graph, setGraph] = useState<EntityIntelGraphResponse | null>(initialGraph);
  const [selected, setSelected] = useState<EntityIntelGraphNode | null>(null);
  const [isolatedNodeId, setIsolatedNodeId] = useState<string | null>(null);
  const [detailEntity, setDetailEntity] = useState<EntityIntelGraphNode | null>(null);
  const [detailOpen, setDetailOpen] = useState(false);
  const [loading, setLoading] = useState(!initialGraph);
  const [error, setError] = useState<string | null>(null);
  const [zoomPercent, setZoomPercent] = useState(100);
  const [visibleEdgeCount, setVisibleEdgeCount] = useState(graph?.edges.length ?? 0);
  const [visibleNodeCount, setVisibleNodeCount] = useState(graph?.nodes.length ?? 0);
  const [timeFilter, setTimeFilter] = useState<TimeFilterState | null>(null);
  const [roleFilter, setRoleFilter] = useState<RoleFilterState | null>(null);
  const [requestedDepth, setRequestedDepth] = useState<number | null>(null);
  const [nodeQuery, setNodeQuery] = useState("");
  const [labelDensityOverride, setLabelDensityOverride] = useState<GraphLabelDensity | null>(null);

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
      setVisibleNodeCount(result.nodes.length);
      setVisibleEdgeCount(result.edges.length);
      setSelected(null);
      setIsolatedNodeId(null);
      setRequestedDepth(null);
      setTimeFilter(null);
      setRoleFilter(null);
      selectedNodeIdRef.current = null;
      isolatedNodeIdRef.current = null;
      previousIsolatedNodeIdRef.current = null;
      isolationCameraIntentRef.current = null;
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
        setVisibleNodeCount(initialGraph.nodes.length);
        setVisibleEdgeCount(initialGraph.edges.length);
        setSelected(null);
        setIsolatedNodeId(null);
        setRequestedDepth(null);
        setTimeFilter(null);
        setRoleFilter(null);
        selectedNodeIdRef.current = null;
        isolatedNodeIdRef.current = null;
        previousIsolatedNodeIdRef.current = null;
        isolationCameraIntentRef.current = null;
        setLoading(false);
      }, 0);
      return () => window.clearTimeout(handle);
    }
    const kickoff = window.setTimeout(() => void loadGraph(), 0);
    return () => window.clearTimeout(kickoff);
  }, [activeOnly, initialGraph, loadGraph]);

  const elements = useMemo(() => (graph ? graphElements(graph, name) : []), [graph, name]);
  const roleOptions = useMemo(() => graphRoleOptions(graph), [graph]);
  const roleCategoryOptions = useMemo(() => graphRoleCategoryOptions(graph), [graph]);
  const nodeDepths = useMemo(() => graphDepthMap(graph, name), [graph, name]);
  const hasResolvedCenter = nodeDepths.size > 0;
  const graphNodeCount = graph?.nodes.length ?? 0;
  const availableDepth = Math.max(1, ...nodeDepths.values());
  const visibleDepth = requestedDepth === null
    ? availableDepth
    : Math.min(requestedDepth, availableDepth);
  const visibleDepthLimit = hasResolvedCenter && visibleDepth < availableDepth
    ? visibleDepth
    : null;
  const depthOptions = useMemo(() => Array.from(
    { length: availableDepth },
    (_, index) => {
      const depth = index + 1;
      return {
        depth,
        nodeCount: depth === availableDepth
          ? graphNodeCount
          : [...nodeDepths.values()].filter((nodeDepth) => nodeDepth <= depth).length,
      };
    },
  ), [availableDepth, graphNodeCount, nodeDepths]);
  const depthVisibleNodeCount = depthOptions[visibleDepth - 1]?.nodeCount ?? graph?.nodes.length ?? 0;
  const roleOptionsKey = roleOptions
    .map((role) => `${role.key}:${role.count}:${role.category ?? "legacy"}`)
    .join("|");
  const enabledRoleKeys = useMemo(() => new Set(
    roleFilter?.key === roleOptionsKey
      ? roleFilter.enabledKeys
      : roleOptions.map((role) => role.key),
  ), [roleFilter, roleOptions, roleOptionsKey]);
  const allRolesVisible = roleOptions.every((role) => enabledRoleKeys.has(role.key));
  const activeRoleCategory = allRolesVisible
    ? null
    : roleCategoryOptions.find((category) => (
      category.roleKeys.length === enabledRoleKeys.size
      && category.roleKeys.every((key) => enabledRoleKeys.has(key))
    ))?.key ?? null;
  const unclassifiedRoles = roleOptions.filter((role) => role.category === "other");
  const temporalBounds = useMemo(() => temporalBoundsFor(graph), [graph]);
  const temporalKey = temporalBounds
    ? `${temporalBounds.min}:${temporalBounds.max}:${temporalBounds.maxOffset}`
    : null;
  const timeRange = temporalBounds
    ? timeFilter?.key === temporalKey
      ? timeFilter.range
      : [0, temporalBounds.maxOffset] satisfies [number, number]
    : null;
  const fullTimeRange = !temporalBounds
    || !timeRange
    || (timeRange[0] === 0 && timeRange[1] === temporalBounds.maxOffset);
  const hasLocalReduction = (
    visibleDepthLimit !== null
    || !allRolesVisible
    || !fullTimeRange
    || isolatedNodeId !== null
  );
  const allReceivedVisible = Boolean(
    graph
    && visibleNodeCount === graph.nodes.length
    && visibleEdgeCount === graph.edges.length,
  );
  const labelDensity = labelDensityOverride ?? defaultGraphLabelDensity(graph);
  const selectedNodeId = useMemo(() => (
    graph && selected ? selectedNodeIdentity(graph, selected) : null
  ), [graph, selected]);
  const matchingNodeResults = useMemo(() => {
    const normalizedQuery = normalizedEntityIdentity(nodeQuery);
    if (!graph || !normalizedQuery) return [];
    return graph.nodes
      .map((node, index) => ({ node, id: nodeIdentity(node, index), label: nodeLabel(node) }))
      .filter(({ node, label }) => (
        normalizedEntityIdentity(label)?.includes(normalizedQuery)
        || normalizedEntityIdentity(node.norm)?.includes(normalizedQuery)
      ))
      .sort((left, right) => left.label.localeCompare(right.label, "es"));
  }, [graph, nodeQuery]);
  const matchingNodes = matchingNodeResults.slice(0, 12);
  const matchingNodeIds = useMemo(
    () => new Set(matchingNodeResults.map(({ id }) => id)),
    [matchingNodeResults],
  );
  useEffect(() => {
    temporalBoundsRef.current = temporalBounds;
    timeRangeRef.current = timeRange;
    enabledRoleKeysRef.current = enabledRoleKeys;
    nodeDepthsRef.current = nodeDepths;
    visibleDepthLimitRef.current = visibleDepthLimit;
    selectedNodeIdRef.current = selectedNodeId;
    isolatedNodeIdRef.current = isolatedNodeId;
    labelDensityRef.current = labelDensity;
  }, [
    enabledRoleKeys,
    isolatedNodeId,
    labelDensity,
    nodeDepths,
    selectedNodeId,
    temporalBounds,
    timeRange,
    visibleDepthLimit,
  ]);

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
  }, []);

  const resetGraphFocus = useCallback(() => {
    const instance = graphRef.current;
    if (!instance) return;
    initialGraphFocus(instance);
  }, []);

  const fitCurrentGraph = useCallback(() => {
    const instance = graphRef.current;
    if (!instance) return;
    fitVisibleGraph(instance);
  }, []);

  const restoreAllReceived = useCallback(() => {
    isolationCameraIntentRef.current = null;
    setRequestedDepth(null);
    setRoleFilter(null);
    setTimeFilter(null);
    setIsolatedNodeId(null);
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
                label: "",
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
              selector: "node.is-priority-label, node.is-hover-label, node.is-focus-label, node.is-readable-zoom, node.is-all-label",
              style: { label: "data(label)" },
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
                label: "",
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
              selector: "edge.role-category-governance",
              style: {
                "line-color": "#3157b7",
                "target-arrow-color": "#3157b7",
                width: 1.7,
              },
            },
            {
              selector: "edge.role-category-representation",
              style: {
                "line-color": "#8396ad",
                "target-arrow-color": "#8396ad",
                width: 1,
              },
            },
            {
              selector: "edge.role-category-audit",
              style: {
                "line-color": "#7c3aed",
                "line-style": "dashed",
                "target-arrow-color": "#7c3aed",
                width: 1.35,
              },
            },
            {
              selector: "edge.role-category-ownership",
              style: {
                "line-color": "#0f8a76",
                "target-arrow-color": "#0f8a76",
                width: 2.1,
              },
            },
            {
              selector: "edge.role-category-liquidation",
              style: {
                "line-color": "#b45f06",
                "line-style": "dashed",
                "target-arrow-color": "#b45f06",
                width: 1.9,
              },
            },
            {
              selector: "edge.role-category-other",
              style: {
                "line-color": "#64748b",
                "line-style": "dotted",
                "target-arrow-color": "#64748b",
                width: 1.3,
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
              selector: "edge.is-hover-label, edge.is-focus-label, edge.is-readable-zoom, edge.is-all-label",
              style: { label: "data(label)" },
            },
            {
              selector: ".is-time-filtered, .is-role-filtered, .is-depth-filtered, .is-focus-filtered",
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
              selector: "node.is-search-match",
              style: {
                "border-color": "#f59e0b",
                "border-width": 5,
                "overlay-color": "#f59e0b",
                "overlay-opacity": 0.1,
              },
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
            padding: 56,
            randomize: false,
          } as cytoscape.LayoutOptions,
        });
        const clearHover = () => {
          if (containerRef.current) containerRef.current.style.cursor = "";
          instance.elements().removeClass("is-hovered is-dimmed is-hover-label");
        };
        const applyHover = (node: cytoscape.NodeSingular) => {
          clearHover();
          if (containerRef.current) containerRef.current.style.cursor = "pointer";
          const neighborhood = node.closedNeighborhood();
          instance.elements().not(neighborhood).addClass("is-dimmed");
          node.addClass("is-hovered is-hover-label");
        };
        const syncZoomLabels = () => applyGraphLabelDensity(instance, labelDensityRef.current);
        const onMouseOver = (event: cytoscape.EventObject) => applyHover(event.target as cytoscape.NodeSingular);
        const onMouseOut = () => clearHover();
        let lastTap: { id: string; at: number } | null = null;
        const onTap = (event: cytoscape.EventObject) => {
          const node = event.target.data() as EntityIntelGraphNode;
          const id = String(node.id ?? node.norm ?? node.name ?? node.label ?? "");
          const now = Date.now();
          const isDoubleTap = lastTap?.id === id && now - lastTap.at <= GRAPH_DOUBLE_TAP_MS;
          lastTap = { id, at: now };
          if (isDoubleTap) {
            selectedNodeIdRef.current = id;
            setSelected(node);
            setDetailEntity(node);
            setDetailOpen(true);
            return;
          }
          const nextSelected = selectedNodeIdRef.current === id ? null : node;
          selectedNodeIdRef.current = nextSelected ? id : null;
          setSelected(nextSelected);
        };
        let initialized = false;
        const applyInitialFocus = () => {
          if (initialized) return;
          initialized = true;
          if (focusTimer !== null) {
            window.clearTimeout(focusTimer);
            focusTimer = null;
          }
          separateGraphNodes(instance);
          const visibility = applyGraphVisibility(
            instance,
            temporalBoundsRef.current,
            timeRangeRef.current,
            enabledRoleKeysRef.current,
            nodeDepthsRef.current,
            visibleDepthLimitRef.current,
            isolatedNodeIdRef.current,
          );
          setVisibleEdgeCount(visibility.edges);
          setVisibleNodeCount(visibility.nodes);
          if (isolatedNodeIdRef.current) {
            focusGraphNode(instance, isolatedNodeIdRef.current);
          } else {
            initialGraphFocus(instance);
          }
          syncZoomLabels();
          setZoomPercent(Math.round(instance.zoom() * 100));
        };
        const onViewport = () => {
          syncZoomLabels();
          setZoomPercent(Math.round(instance.zoom() * 100));
        };
        const container = containerRef.current;
        container.addEventListener("mouseleave", clearHover);
        instance.on("mouseover", "node", onMouseOver);
        instance.on("mouseout", "node", onMouseOut);
        instance.on("tap", "node", onTap);
        instance.on("viewport", onViewport);
        instance.on("layoutstop", applyInitialFocus);
        graphRef.current = instance;
        focusTimer = window.setTimeout(applyInitialFocus, 900);
        cleanupHandlers = () => {
          container.removeEventListener("mouseleave", clearHover);
          instance.removeListener("mouseover", "node", onMouseOver);
          instance.removeListener("mouseout", "node", onMouseOut);
          instance.removeListener("tap", "node", onTap);
          instance.removeListener("viewport", onViewport);
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
    const visibility = applyGraphVisibility(
      graphRef.current,
      temporalBounds,
      timeRange,
      enabledRoleKeys,
      nodeDepths,
      visibleDepthLimit,
      isolatedNodeId,
    );
    setVisibleEdgeCount(visibility.edges);
    setVisibleNodeCount(visibility.nodes);
  }, [
    enabledRoleKeys,
    isolatedNodeId,
    nodeDepths,
    temporalBounds,
    timeRange,
    visibleDepthLimit,
  ]);

  useEffect(() => {
    const instance = graphRef.current;
    if (!instance || previousIsolatedNodeIdRef.current === isolatedNodeId) return;
    previousIsolatedNodeIdRef.current = isolatedNodeId;
    const cameraIntent = isolationCameraIntentRef.current;
    isolationCameraIntentRef.current = null;
    if (cameraIntent === "focus" && isolatedNodeId) {
      focusGraphNode(instance, isolatedNodeId);
    } else if (cameraIntent === "restore" && !isolatedNodeId) {
      initialGraphFocus(instance);
    }
  }, [isolatedNodeId]);

  useEffect(() => {
    if (!graphRef.current) return;
    applyGraphLabelDensity(graphRef.current, labelDensity);
  }, [labelDensity]);

  useEffect(() => {
    const instance = graphRef.current;
    if (!instance) return;
    instance.batch(() => {
      instance.nodes().removeClass("is-search-match");
      matchingNodeIds.forEach((id) => {
        instance.getElementById(id).addClass("is-search-match");
      });
    });
  }, [matchingNodeIds]);

  const detailTarget = detailOpen ? detailEntity ?? selected : selected;
  const relations = useMemo(() => directRelations(graph, detailTarget), [detailTarget, graph]);
  const openSelectedDetail = useCallback(() => {
    if (!selected) return;
    setDetailEntity(selected);
    setDetailOpen(true);
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
              Recargar corpus: solo activos
            </label>
            <span>{visibleNodeCount} de {graph?.nodes.length ?? 0} nodos visibles</span>
            <span>{visibleEdgeCount} de {graph?.edges.length ?? 0} enlaces visibles</span>
            {graph?.truncated && <span>Vista recortada por Signal</span>}
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
                <button
                  type="button"
                  aria-label="Encajar todos los elementos visibles"
                  onClick={fitCurrentGraph}
                >
                  Encajar visibles
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
              {selected && (
                <div className="entity-role-filter-actions">
                  {selectedNodeId !== isolatedNodeId && (
                    <button
                      type="button"
                      onClick={() => {
                        isolationCameraIntentRef.current = "focus";
                        setIsolatedNodeId(selectedNodeId);
                      }}
                    >
                      Aislar relaciones
                    </button>
                  )}
                  <button type="button" onClick={openSelectedDetail}>
                    Abrir ficha
                  </button>
                </div>
              )}
              {isolatedNodeId && (
                <button
                  type="button"
                  className="vector-secondary small entity-graph-clear-focus"
                  onClick={() => {
                    isolationCameraIntentRef.current = "restore";
                    setIsolatedNodeId(null);
                  }}
                >
                  Mostrar grafo completo
                </button>
              )}
              <div className="entity-table-toolbar compact">
                <label>
                  Buscar nodo
                  <input
                    type="search"
                    value={nodeQuery}
                    onChange={(event) => setNodeQuery(event.target.value)}
                    placeholder="Empresa o persona…"
                    aria-label="Buscar nodo del grafo"
                  />
                </label>
              </div>
              {nodeQuery.trim() && (
                <div className="entity-relation-list" aria-label="Nodos encontrados">
                  <p className="entity-graph-search-count" aria-live="polite">
                    {matchingNodes.length} de {matchingNodeResults.length} coincidencias mostradas.
                    La búsqueda resalta, pero no oculta ni mueve el grafo.
                  </p>
                  {matchingNodes.length > 0 ? matchingNodes.map(({ id, label, node }) => (
                    <button
                      type="button"
                      key={id}
                      onClick={() => {
                        selectedNodeIdRef.current = id;
                        setSelected(node);
                      }}
                    >
                      <span>
                        <strong>{label}</strong>
                        <small>{KIND_LABELS[nodeKind(node)]}</small>
                      </span>
                    </button>
                  )) : <p>No hay nodos que coincidan.</p>}
                </div>
              )}
              <section className="entity-graph-exploration" aria-label="Vista de trabajo del grafo">
                <header>
                  <div>
                    <span>Vista de trabajo</span>
                    <strong aria-live="polite">
                      {hasLocalReduction
                        ? "Vista reducida"
                        : allReceivedVisible
                          ? "100 % de lo recibido"
                          : "Cobertura parcial en pantalla"}
                    </strong>
                  </div>
                  <small>
                    {visibleNodeCount}/{graph.nodes.length} nodos ·{" "}
                    {visibleEdgeCount}/{graph.edges.length} enlaces
                  </small>
                </header>
                <p>
                  Los filtros reducen esta vista sin recolocar el grafo. Puedes recuperar todos los
                  datos recibidos y reencuadrar por separado.
                </p>
                <div className="entity-graph-exploration-actions">
                  <button
                    type="button"
                    disabled={!hasResolvedCenter || availableDepth === 1 || visibleDepth === 1}
                    onClick={() => setRequestedDepth(1)}
                  >
                    Ver entorno directo
                  </button>
                  <button
                    type="button"
                    disabled={!hasLocalReduction}
                    onClick={restoreAllReceived}
                  >
                    Restaurar todo lo recibido
                  </button>
                </div>
                <label className="entity-label-density">
                  <span>
                    <strong>Densidad de etiquetas</strong>
                    <small>Solo cambia los nombres mostrados; no la cobertura.</small>
                  </span>
                  <select
                    aria-label="Densidad de etiquetas del grafo"
                    value={labelDensity}
                    onChange={(event) => (
                      setLabelDensityOverride(event.target.value as GraphLabelDensity)
                    )}
                  >
                    <option value="essential">Esenciales</option>
                    <option value="adaptive">Adaptativas al zoom</option>
                    <option value="all">Todas</option>
                  </select>
                </label>
              </section>
              <details className="entity-graph-disclosure">
                <summary>
                  <span>Estructura y niveles</span>
                  <small>{depthVisibleNodeCount}/{graph.nodes.length} nodos por nivel</small>
                </summary>
                <div className="entity-graph-disclosure-body">
                  <label className="entity-depth-filter">
                    <span>
                      <strong>Niveles visibles</strong>
                      <small>{depthVisibleNodeCount} de {graph.nodes.length} nodos por nivel</small>
                    </span>
                    <select
                      aria-label="Número de niveles visibles"
                      value={visibleDepth}
                      disabled={!hasResolvedCenter || availableDepth === 1}
                      onChange={(event) => {
                        setRequestedDepth(Number(event.target.value));
                      }}
                    >
                      {depthOptions.map((option) => (
                        <option key={option.depth} value={option.depth}>
                          {option.depth === availableDepth
                            ? `Todos los niveles · ${option.nodeCount} nodos`
                            : `Hasta nivel ${option.depth} · ${option.nodeCount} nodos`}
                        </option>
                      ))}
                    </select>
                  </label>
                  {!hasResolvedCenter && (
                    <p className="entity-graph-note">
                      No se pudo calcular la distancia a la entidad central. Se muestran todos los
                      elementos recibidos y el filtro por nivel queda desactivado.
                    </p>
                  )}
                  <dl>
                    <div>
                      <dt>Tipo consultado</dt>
                      <dd>{KIND_LABELS[type]}</dd>
                    </div>
                    <div>
                      <dt>Profundidad</dt>
                      <dd>
                        Nivel {visibleDepth} de {availableDepth} disponible
                        {availableDepth === 1 ? "" : "s"} · {activeOnly ? "solo vínculos activos" : "activos y cesados"}
                      </dd>
                    </div>
                    <div>
                      <dt>Encuadre inicial</dt>
                      <dd>Centro y nodos clave etiquetados; más nombres al acercar</dd>
                    </div>
                  </dl>
                </div>
              </details>
              {roleOptions.length > 0 && (
                <details className="entity-graph-disclosure">
                  <summary>
                    <span>Tipos de vínculo</span>
                    <small>{enabledRoleKeys.size}/{roleOptions.length} tipos visibles</small>
                  </summary>
                  <div className="entity-graph-disclosure-body">
                    <fieldset className="entity-role-filter">
                      <legend>Tipos de vínculo</legend>
                      <p>
                        Desmarca ruido para leer la estructura; el grafo no se recoloca. Los
                        recuentos son pertenencias no excluyentes: un mismo enlace puede figurar en
                        varios tipos y su suma no representa la cobertura.
                      </p>
                      {roleCategoryOptions.length > 0 && (
                        <section
                          className="entity-role-category-presets"
                          aria-label="Lecturas rápidas por familia de vínculo"
                        >
                          <header>
                            <strong>Lecturas rápidas por familia</strong>
                            <small>
                              Son filtros voluntarios; al entrar se muestran todas las relaciones.
                            </small>
                          </header>
                          <div>
                            {roleCategoryOptions.map((category) => (
                              <button
                                type="button"
                                key={category.key}
                                aria-pressed={activeRoleCategory === category.key}
                                aria-label={`Ver solo ${category.label}, ${category.count} ${
                                  category.count === 1 ? "vínculo" : "vínculos"
                                }`}
                                onClick={() => setRoleFilter({
                                  key: roleOptionsKey,
                                  enabledKeys: category.roleKeys,
                                })}
                              >
                                <i className={GRAPH_ROLE_CATEGORY_META[category.key].className} />
                                <span>{category.label}</span>
                                <small>{category.count}</small>
                              </button>
                            ))}
                          </div>
                        </section>
                      )}
                      {unclassifiedRoles.length > 0 && (
                        <div className="entity-role-unclassified" role="note">
                          <CircleHelp size={16} aria-hidden="true" />
                          <div>
                            <strong>
                              {unclassifiedRoles.length} {unclassifiedRoles.length === 1
                                ? "tipo sin clasificar"
                                : "tipos sin clasificar"}
                            </strong>
                            <p>{unclassifiedRoles.map((role) => role.label).join(", ")}</p>
                            <small>
                              Oracle conserva estas etiquetas de Signal y las muestra bajo
                              «Sin clasificar»; no las descarta ni adivina su significado.
                            </small>
                          </div>
                        </div>
                      )}
                      <div className="entity-role-filter-actions">
                        <button
                          type="button"
                          onClick={() => setRoleFilter({
                            key: roleOptionsKey,
                            enabledKeys: roleOptions.map((role) => role.key),
                          })}
                        >
                          Marcar todos
                        </button>
                        <button
                          type="button"
                          onClick={() => setRoleFilter({ key: roleOptionsKey, enabledKeys: [] })}
                        >
                          Desmarcar todos
                        </button>
                      </div>
                      <div className="entity-role-filter-options">
                        {roleOptions.map((role) => (
                          <label key={role.key}>
                            <input
                              type="checkbox"
                              aria-label={`${role.label}, ${role.count} ${role.count === 1 ? "vínculo" : "vínculos"}`}
                              checked={enabledRoleKeys.has(role.key)}
                              onChange={(event) => {
                                const next = new Set(enabledRoleKeys);
                                if (event.target.checked) next.add(role.key);
                                else next.delete(role.key);
                                setRoleFilter({ key: roleOptionsKey, enabledKeys: [...next] });
                              }}
                            />
                            <span>{role.label}</span>
                            <small>{role.count} {role.count === 1 ? "vínculo" : "vínculos"}</small>
                          </label>
                        ))}
                      </div>
                    </fieldset>
                  </div>
                </details>
              )}
              <details className="entity-graph-disclosure">
                <summary>
                  <span>Periodo</span>
                  <small>{fullTimeRange ? "Periodo completo" : "Periodo acotado"}</small>
                </summary>
                <div className="entity-graph-disclosure-body">
                  {temporalBounds && timeRange ? (
                    <section className="entity-time-filter" aria-label="Cronograma del grafo">
                      <h3>Cronograma</h3>
                      <p>
                        {visibleEdgeCount} de {graph.edges.length} vínculos visibles. Los vínculos sin
                        fecha se mantienen visibles; los filtros de fecha, tipo y foco se componen y los
                        nodos sin vínculos visibles se ocultan, sin relayout.
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
                        {activeOnly ? " Aplicado sobre el corpus de vínculos activos recargado." : " Incluye vínculos activos y cesados."}
                      </small>
                    </section>
                  ) : (
                    <p className="entity-graph-note">
                      Este grafo no trae fechas en sus vínculos; el cronograma no puede acotar el rango.
                    </p>
                  )}
                </div>
              </details>
              <details className="entity-graph-disclosure">
                <summary>
                  <span>Leyenda y procedencia</span>
                  <small>Signal vía Flask</small>
                </summary>
                <div className="entity-graph-disclosure-body">
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
                  {roleCategoryOptions.length > 0 && (
                    <div
                      className="entity-role-category-legend"
                      aria-label="Jerarquía visual de familias de vínculo"
                    >
                      <strong>Jerarquía visual de vínculos</strong>
                      <p>
                        El color y el grosor ayudan a leer el conjunto; los nombres y filtros siguen
                        siendo la referencia accesible.
                      </p>
                      <div>
                        {roleCategoryOptions.map((category) => (
                          <span key={category.key}>
                            <i className={GRAPH_ROLE_CATEGORY_META[category.key].className} />
                            {category.label} · {category.count}
                          </span>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              </details>
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
        entity={detailTarget}
        relations={relations}
        returnFocusRef={returnFocusRef}
        onOpenChange={(open) => {
          setDetailOpen(open);
          if (!open) setDetailEntity(null);
        }}
        onNavigate={(nextKind, nextName) => {
          setDetailOpen(false);
          router.push(entityRoute(nextKind, nextName));
        }}
      />
    </div>
  );
}
