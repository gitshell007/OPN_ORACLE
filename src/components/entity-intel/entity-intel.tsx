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

function problemMessage(reason: unknown, fallback: string): string {
  return reason instanceof ApiError ? reason.problem.detail : fallback;
}

function entityRoute(kind: EntityIntelKind, name: string): string {
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

  const loadSuggestions = useCallback(async () => {
    const value = query.trim();
    if (value.length < 2) {
      setSuggestions([]);
      setSuggestionsChecked(false);
      return;
    }
    setLoading(true);
    setSuggestionsChecked(false);
    setError(null);
    try {
      const result = await api.entityIntel.suggest({ q: value, kind, limit: 8 });
      setSuggestions(result.suggestions);
      setSuggestionsChecked(true);
    } catch (reason) {
      setError(problemMessage(reason, "No se pudieron cargar sugerencias de entidades."));
      setSuggestionsChecked(true);
    } finally {
      setLoading(false);
    }
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
    if (value.length >= 2) router.push(entityRoute(kind, value));
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
              onChange={(event) => setQuery(event.target.value)}
              placeholder="Ej. IBERDROLA"
            />
          </div>
        </label>
        <button className="vector-primary" disabled={query.trim().length < 2 || loading}>
          {loading ? <RefreshCw size={15} /> : <Network size={15} />}
          Abrir grafo
        </button>
      </form>
      {error && <p className="auth-inline-error" role="alert">{error}</p>}
      {kind === "person" && suggestionsChecked && !loading && !error && suggestions.length === 0 && query.trim().length >= 2 && (
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

function edgeRole(edge: EntityIntelGraphEdge): string {
  if (Array.isArray(edge.roles)) return edge.roles.join(", ");
  return String(edge.role ?? edge.roles ?? "Relación");
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
      kind: nodeKind(other),
      role: edgeRole(edge),
      date: typeof edge.date === "string" ? edge.date : null,
      active: typeof edge.active === "boolean" ? edge.active : null,
      degree: typeof other.degree === "number" ? other.degree : null,
    }];
  });
}

export function EntityGraphExplorer({
  name,
  type,
}: {
  name: string;
  type: EntityIntelKind;
}) {
  const router = useRouter();
  const containerRef = useRef<HTMLDivElement | null>(null);
  const graphRef = useRef<cytoscape.Core | null>(null);
  const returnFocusRef = useRef<HTMLDivElement | null>(null);
  const [graph, setGraph] = useState<EntityIntelGraphResponse | null>(null);
  const [selected, setSelected] = useState<EntityIntelGraphNode | null>(null);
  const [detailOpen, setDetailOpen] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const loadGraph = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const result = await api.entityIntel.graph({
        name,
        type,
        depth: 2,
        activeOnly: true,
      });
      setGraph(result);
      setSelected(null);
    } catch (reason) {
      setGraph(null);
      setError(problemMessage(reason, "No se pudo cargar el grafo de la entidad."));
    } finally {
      setLoading(false);
    }
  }, [name, type]);

  useEffect(() => {
    const kickoff = window.setTimeout(() => void loadGraph(), 0);
    return () => window.clearTimeout(kickoff);
  }, [loadGraph]);

  const elements = useMemo(() => (graph ? graphElements(graph) : []), [graph]);

  useEffect(() => {
    if (!containerRef.current || !graph || elements.length === 0) return undefined;
    let cancelled = false;
    let cleanupHandlers: (() => void) | null = null;
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
          wheelSensitivity: 0.18,
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
              selector: 'node[is_center = true]',
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
              selector: 'node[is_center = true].is-hovered',
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
            fit: true,
            padding: 42,
            randomize: true,
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
        const onTap = (event: cytoscape.EventObject) => {
          const node = event.target.data() as EntityIntelGraphNode;
          setSelected(node);
          setDetailOpen(true);
        };
        const container = containerRef.current;
        container.addEventListener("mouseleave", clearHover);
        instance.on("mouseover", "node", onMouseOver);
        instance.on("mouseout", "node", onMouseOut);
        instance.on("tap", "node", onTap);
        graphRef.current = instance;
        cleanupHandlers = () => {
          container.removeEventListener("mouseleave", clearHover);
          instance.removeListener("mouseover", "node", onMouseOver);
          instance.removeListener("mouseout", "node", onMouseOut);
          instance.removeListener("tap", "node", onTap);
        };
      },
    );
    return () => {
      cancelled = true;
      cleanupHandlers?.();
      graphRef.current?.destroy();
      graphRef.current = null;
    };
  }, [elements, graph]);

  const relations = useMemo(() => directRelations(graph, selected), [graph, selected]);

  return (
    <div className="entity-intel-page">
      <section className="page-heading">
        <div>
          <div className="eyebrow">Actores · grafo de entidad</div>
          <h1>{name}</h1>
          <p>
            Exploración básica de relaciones desde Signal. F1 solo consulta y
            visualiza; no incorpora datos a expedientes.
          </p>
        </div>
        <button className="vector-secondary" disabled={loading} onClick={() => void loadGraph()}>
          <RefreshCw size={15} />
          Actualizar grafo
        </button>
      </section>
      <EntitySearchPanel initialQuery={name} initialKind={type} compact />
      {error && <div className="inline-error" role="alert">{error}</div>}
      <section className="entity-graph-shell" aria-busy={loading}>
        <header>
          <div>
            <span className="section-kicker">Grafo</span>
            <h2>Relaciones detectadas</h2>
          </div>
          <div className="entity-graph-metrics">
            <span>{graph?.nodes.length ?? 0} nodos</span>
            <span>{graph?.edges.length ?? 0} enlaces</span>
            {graph?.cache_hit && <span>Caché activo</span>}
          </div>
        </header>
        {loading ? (
          <div className="global-inventory-state" role="status">
            Cargando grafo de entidad…
          </div>
        ) : graph && elements.length > 0 ? (
          <div className="entity-graph-layout">
            <div
              ref={containerRef}
              tabIndex={-1}
              className="entity-graph-canvas"
              aria-label={`Grafo de relaciones de ${name}`}
            />
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
                  <dd>2 niveles · relaciones activas</dd>
                </div>
                <div>
                  <dt>Origen</dt>
                  <dd>Signal vía Flask</dd>
                </div>
              </dl>
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
