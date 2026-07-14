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

const KIND_LABELS: Record<EntityIntelKind, string> = {
  company: "Empresa",
  person: "Persona",
};

let fcoseRegistered = false;

function problemMessage(reason: unknown, fallback: string): string {
  return reason instanceof ApiError ? reason.problem.detail : fallback;
}

function entityRoute(kind: EntityIntelKind, name: string): string {
  return `/app/actors/entity/${kind}/${encodeURIComponent(name)}`;
}

export function EntitySearchPanel({
  initialQuery = "",
  compact = false,
}: {
  initialQuery?: string;
  compact?: boolean;
}) {
  const router = useRouter();
  const [kind, setKind] = useState<EntityIntelKind>("company");
  const [query, setQuery] = useState(initialQuery);
  const [suggestions, setSuggestions] = useState<string[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadSuggestions = useCallback(async () => {
    const value = query.trim();
    if (value.length < 2) {
      setSuggestions([]);
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const result = await api.entityIntel.suggest({ q: value, kind, limit: 8 });
      setSuggestions(result.suggestions);
    } catch (reason) {
      setError(problemMessage(reason, "No se pudieron cargar sugerencias de entidades."));
    } finally {
      setLoading(false);
    }
  }, [kind, query]);

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
            onChange={(event) => setKind(event.target.value as EntityIntelKind)}
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

export function EntityGraphExplorer({
  name,
  type,
}: {
  name: string;
  type: EntityIntelKind;
}) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const graphRef = useRef<cytoscape.Core | null>(null);
  const [graph, setGraph] = useState<EntityIntelGraphResponse | null>(null);
  const [selected, setSelected] = useState<EntityIntelGraphNode | null>(null);
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
    void Promise.all([import("cytoscape"), import("cytoscape-fcose")]).then(
      ([cytoscapeModule, fcoseModule]) => {
        if (cancelled || !containerRef.current) return;
        const cytoscapeFactory = cytoscapeModule.default;
        if (!fcoseRegistered) {
          cytoscapeFactory.use(fcoseModule.default);
          fcoseRegistered = true;
        }
        graphRef.current?.destroy();
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
                width: 1.2,
              },
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
        instance.on("tap", "node", (event) => {
          setSelected(event.target.data() as EntityIntelGraphNode);
        });
        graphRef.current = instance;
      },
    );
    return () => {
      cancelled = true;
      graphRef.current?.destroy();
      graphRef.current = null;
    };
  }, [elements, graph]);

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
      <EntitySearchPanel initialQuery={name} compact />
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
    </div>
  );
}
