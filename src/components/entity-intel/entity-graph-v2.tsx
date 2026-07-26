"use client";

/**
 * Entity Graph V2 — enterprise ego-network visualization.
 *
 * Design goals (corporate intelligence / market-data style):
 * - Default to a readable 1-hop radial neighborhood around the focus entity
 * - Progressive disclosure (depth 1 → 2) instead of a full force hairball
 * - Ranked directory + optional adjacency matrix for dense relationship sets
 * - Pure SVG/React (no cytoscape) so layout is deterministic and inspectable
 *
 * Does not modify EntityGraphExplorer (Grafo v1).
 */

import { ApiError, api, type EntityIntelGraphEdge, type EntityIntelGraphNode, type EntityIntelGraphResponse, type EntityIntelKind } from "@oracle/api-client";
import {
  Building2,
  ChevronRight,
  CircleDot,
  ExternalLink,
  Grid3X3,
  List,
  Network,
  RefreshCw,
  Search,
  UserRound,
} from "lucide-react";
import { useRouter } from "next/navigation";
import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type PointerEvent as ReactPointerEvent,
} from "react";
import { entityRoute } from "@/lib/entity-route";
import { graphNodeDepths } from "./entity-graph-layout";

type ViewMode = "radial" | "directory" | "matrix";
type TypeFilter = "all" | "company" | "person";

interface NormalizedNode {
  id: string;
  label: string;
  kind: EntityIntelKind | "entity";
  degree: number;
  isCenter: boolean;
  routeName: string;
  raw: EntityIntelGraphNode;
}

interface NormalizedEdge {
  id: string;
  source: string;
  target: string;
  role: string;
  active: boolean | null;
  date: string | null;
}

interface RingPlacement {
  node: NormalizedNode;
  depth: number;
  angle: number;
  x: number;
  y: number;
  radius: number;
}

const VIEW_W = 920;
const VIEW_H = 640;
const CX = VIEW_W / 2;
const CY = VIEW_H / 2;
const RING_RADIUS: Record<number, number> = { 1: 210, 2: 305 };
const CENTER_R = 28;
const DEFAULT_RING_CAP = 36;

function problemMessage(reason: unknown, fallback: string): string {
  return reason instanceof ApiError ? reason.problem.detail : fallback;
}

function nodeId(node: EntityIntelGraphNode, index: number): string {
  return String(node.id ?? node.norm ?? node.name ?? node.label ?? `n-${index}`);
}

function nodeLabel(node: EntityIntelGraphNode): string {
  return String(node.label ?? node.name ?? node.norm ?? node.id ?? "Sin nombre");
}

function nodeKind(node: EntityIntelGraphNode): EntityIntelKind | "entity" {
  const value = String(node.type ?? "").toLocaleLowerCase("es-ES");
  if (value === "company" || value === "person") return value;
  return "entity";
}

function edgeRole(edge: EntityIntelGraphEdge): string {
  if (typeof edge.role === "string" && edge.role.trim()) return edge.role.trim();
  if (Array.isArray(edge.roles) && edge.roles[0]) return String(edge.roles[0]);
  if (typeof edge.roles === "string" && edge.roles.trim()) return edge.roles.trim();
  return "Vínculo";
}

function normalizeFold(value: string): string {
  return value
    .normalize("NFD")
    .replace(/\p{Diacritic}/gu, "")
    .toLocaleLowerCase("es-ES")
    .trim();
}

function findCenterId(nodes: NormalizedNode[], queryName: string): string | null {
  const marked = nodes.find((n) => n.isCenter);
  if (marked) return marked.id;
  const needle = normalizeFold(queryName);
  const exact = nodes.find((n) => normalizeFold(n.routeName) === needle || normalizeFold(n.label) === needle);
  if (exact) return exact.id;
  const partial = nodes.find((n) => normalizeFold(n.label).includes(needle) || normalizeFold(n.routeName).includes(needle));
  return partial?.id ?? nodes[0]?.id ?? null;
}

function buildNormalized(graph: EntityIntelGraphResponse, queryName: string) {
  const nodes: NormalizedNode[] = graph.nodes.map((node, index) => {
    const id = nodeId(node, index);
    return {
      id,
      label: nodeLabel(node),
      kind: nodeKind(node),
      degree: typeof node.degree === "number" ? node.degree : 0,
      isCenter: node.is_center === true,
      routeName: String(node.norm ?? node.name ?? node.label ?? id),
      raw: node,
    };
  });
  const known = new Set(nodes.map((n) => n.id));
  const edges: NormalizedEdge[] = graph.edges.flatMap((edge, index) => {
    const source = String(edge.source);
    const target = String(edge.target);
    if (!known.has(source) || !known.has(target) || source === target) return [];
    return [{
      id: String(edge.id ?? `${source}-${target}-${index}`),
      source,
      target,
      role: edgeRole(edge),
      active: typeof edge.active === "boolean" ? edge.active : null,
      date: typeof edge.date === "string" ? edge.date : null,
    }];
  });
  const degreeFromEdges = new Map<string, number>();
  for (const edge of edges) {
    degreeFromEdges.set(edge.source, (degreeFromEdges.get(edge.source) ?? 0) + 1);
    degreeFromEdges.set(edge.target, (degreeFromEdges.get(edge.target) ?? 0) + 1);
  }
  for (const node of nodes) {
    if (node.degree <= 0) node.degree = degreeFromEdges.get(node.id) ?? 0;
  }
  const centerId = findCenterId(nodes, queryName);
  for (const node of nodes) node.isCenter = node.id === centerId;
  const depths = centerId
    ? graphNodeDepths(centerId, nodes.map((n) => n.id), edges)
    : new Map<string, number>();
  return { nodes, edges, centerId, depths };
}

function nodeFill(kind: NormalizedNode["kind"], isCenter: boolean): string {
  if (isCenter) return "#0891b2";
  if (kind === "person") return "#7c3aed";
  if (kind === "company") return "#2563eb";
  return "#64748b";
}

function truncateLabel(label: string, max = 28): string {
  if (label.length <= max) return label;
  return `${label.slice(0, max - 1)}…`;
}

function polar(angle: number, radius: number): { x: number; y: number } {
  return {
    x: CX + Math.cos(angle) * radius,
    y: CY + Math.sin(angle) * radius,
  };
}

function placeRing(
  candidates: NormalizedNode[],
  depth: number,
  cap: number,
): RingPlacement[] {
  const sorted = [...candidates].sort(
    (a, b) => b.degree - a.degree || a.label.localeCompare(b.label, "es"),
  );
  const limited = sorted.slice(0, cap);
  const ringR = RING_RADIUS[depth] ?? 210;
  const count = Math.max(limited.length, 1);
  return limited.map((node, index) => {
    // Start at top (-π/2) and go clockwise for a stable reading order.
    const angle = -Math.PI / 2 + (index / count) * Math.PI * 2;
    const { x, y } = polar(angle, ringR);
    const radius = Math.min(18, Math.max(9, 8 + Math.sqrt(node.degree + 1) * 1.6));
    return { node, depth, angle, x, y, radius };
  });
}

function arcPath(x1: number, y1: number, x2: number, y2: number, bulge = 0.22): string {
  const mx = (x1 + x2) / 2;
  const my = (y1 + y2) / 2;
  const dx = x2 - x1;
  const dy = y2 - y1;
  const cx = mx - dy * bulge;
  const cy = my + dx * bulge;
  return `M ${x1} ${y1} Q ${cx} ${cy} ${x2} ${y2}`;
}

export function EntityGraphV2Explorer({
  name,
  type,
  initialGraph = null,
}: {
  name: string;
  type: EntityIntelKind;
  initialGraph?: EntityIntelGraphResponse | null;
}) {
  const router = useRouter();
  const [graph, setGraph] = useState<EntityIntelGraphResponse | null>(initialGraph);
  const [loading, setLoading] = useState(!initialGraph);
  const [error, setError] = useState<string | null>(null);
  const [activeOnly, setActiveOnly] = useState(false);
  const [maxDepth, setMaxDepth] = useState<1 | 2>(1);
  const [ringCap, setRingCap] = useState(DEFAULT_RING_CAP);
  const [typeFilter, setTypeFilter] = useState<TypeFilter>("all");
  const [viewMode, setViewMode] = useState<ViewMode>("radial");
  const [query, setQuery] = useState("");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [hoveredId, setHoveredId] = useState<string | null>(null);
  const [rotation, setRotation] = useState(0);
  const dragRef = useRef<{ startX: number; startRot: number } | null>(null);

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
      setSelectedId(null);
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
        setLoading(false);
      }, 0);
      return () => window.clearTimeout(handle);
    }
    const kickoff = window.setTimeout(() => void loadGraph(), 0);
    return () => window.clearTimeout(kickoff);
  }, [activeOnly, initialGraph, loadGraph]);

  const model = useMemo(
    () => (graph ? buildNormalized(graph, name) : null),
    [graph, name],
  );

  const filteredEdges = useMemo(() => {
    if (!model) return [];
    return model.edges.filter((edge) => {
      if (activeOnly && edge.active === false) return false;
      return true;
    });
  }, [activeOnly, model]);

  const visiblePlacements = useMemo(() => {
    if (!model?.centerId) return [] as RingPlacement[];
    const byDepth = new Map<number, NormalizedNode[]>();
    for (const node of model.nodes) {
      if (node.id === model.centerId) continue;
      const depth = model.depths.get(node.id);
      if (depth == null || depth < 1 || depth > maxDepth) continue;
      if (typeFilter !== "all" && node.kind !== typeFilter) continue;
      const bucket = byDepth.get(depth) ?? [];
      bucket.push(node);
      byDepth.set(depth, bucket);
    }
    const placements: RingPlacement[] = [];
    for (const depth of [1, 2] as const) {
      if (depth > maxDepth) continue;
      const candidates = byDepth.get(depth) ?? [];
      for (const placed of placeRing(candidates, depth, ringCap)) {
        placements.push({
          ...placed,
          angle: placed.angle + rotation,
          ...polar(placed.angle + rotation, RING_RADIUS[depth] ?? 210),
        });
      }
    }
    return placements;
  }, [maxDepth, model, ringCap, rotation, typeFilter]);

  const placementById = useMemo(() => {
    const map = new Map<string, RingPlacement>();
    for (const p of visiblePlacements) map.set(p.node.id, p);
    return map;
  }, [visiblePlacements]);

  const centerNode = useMemo(
    () => model?.nodes.find((n) => n.id === model.centerId) ?? null,
    [model],
  );

  const selectedNode = useMemo(() => {
    if (!model || !selectedId) return null;
    return model.nodes.find((n) => n.id === selectedId) ?? null;
  }, [model, selectedId]);

  const neighborRows = useMemo(() => {
    if (!model?.centerId) return [];
    const rows = model.nodes
      .filter((node) => {
        if (node.id === model.centerId) return false;
        const depth = model.depths.get(node.id) ?? 99;
        if (depth > maxDepth) return false;
        if (typeFilter !== "all" && node.kind !== typeFilter) return false;
        if (query.trim()) {
          const q = normalizeFold(query);
          if (!normalizeFold(node.label).includes(q) && !normalizeFold(node.routeName).includes(q)) {
            return false;
          }
        }
        return true;
      })
      .map((node) => {
        const depth = model.depths.get(node.id) ?? 99;
        const linkRoles = filteredEdges
          .filter(
            (e) =>
              (e.source === model.centerId && e.target === node.id) ||
              (e.target === model.centerId && e.source === node.id),
          )
          .map((e) => e.role);
        return {
          node,
          depth,
          roles: Array.from(new Set(linkRoles)).slice(0, 4),
        };
      })
      .sort((a, b) => a.depth - b.depth || b.node.degree - a.node.degree || a.node.label.localeCompare(b.node.label, "es"));
    return rows;
  }, [filteredEdges, maxDepth, model, query, typeFilter]);

  const matrixNodes = useMemo(() => {
    if (!model?.centerId) return [] as NormalizedNode[];
    const direct = model.nodes
      .filter((n) => n.id !== model.centerId && (model.depths.get(n.id) ?? 99) === 1)
      .sort((a, b) => b.degree - a.degree || a.label.localeCompare(b.label, "es"))
      .slice(0, 12);
    return [model.nodes.find((n) => n.id === model.centerId)!, ...direct].filter(Boolean);
  }, [model]);

  const matrixLinks = useMemo(() => {
    const set = new Set<string>();
    for (const edge of filteredEdges) {
      set.add(`${edge.source}→${edge.target}`);
      set.add(`${edge.target}→${edge.source}`);
    }
    return set;
  }, [filteredEdges]);

  const radialEdges = useMemo(() => {
    if (!model?.centerId) return [] as Array<{ edge: NormalizedEdge; d: string; strong: boolean }>;
    const result: Array<{ edge: NormalizedEdge; d: string; strong: boolean }> = [];
    for (const edge of filteredEdges) {
      const a = edge.source === model.centerId ? edge.target : edge.target === model.centerId ? edge.source : null;
      if (a) {
        const place = placementById.get(a);
        if (!place) continue;
        const strong =
          hoveredId === a || selectedId === a || hoveredId === model.centerId || selectedId === model.centerId;
        result.push({
          edge,
          strong,
          d: arcPath(CX, CY, place.x, place.y, 0.08),
        });
        continue;
      }
      // Peer edges only when both ends are visible and depth ≤ 1 (reduces clutter).
      const p1 = placementById.get(edge.source);
      const p2 = placementById.get(edge.target);
      if (!p1 || !p2) continue;
      if (p1.depth > 1 || p2.depth > 1) continue;
      const strong =
        hoveredId === edge.source ||
        hoveredId === edge.target ||
        selectedId === edge.source ||
        selectedId === edge.target;
      if (!strong && maxDepth === 2) continue; // hide peer edges unless focused when dense
      result.push({
        edge,
        strong,
        d: arcPath(p1.x, p1.y, p2.x, p2.y, 0.18),
      });
    }
    return result;
  }, [filteredEdges, hoveredId, maxDepth, model, placementById, selectedId]);

  const hiddenByCap = useMemo(() => {
    if (!model?.centerId) return 0;
    let total = 0;
    let shown = 0;
    for (const node of model.nodes) {
      if (node.id === model.centerId) continue;
      const depth = model.depths.get(node.id);
      if (depth == null || depth < 1 || depth > maxDepth) continue;
      if (typeFilter !== "all" && node.kind !== typeFilter) continue;
      total += 1;
    }
    shown = visiblePlacements.length;
    return Math.max(0, total - shown);
  }, [maxDepth, model, typeFilter, visiblePlacements.length]);

  function openEntity(routeName: string, kind: EntityIntelKind | "entity") {
    const k: EntityIntelKind = kind === "person" ? "person" : "company";
    router.push(entityRoute(k, routeName));
  }

  function onPointerDown(event: ReactPointerEvent<SVGSVGElement>) {
    if (event.button !== 0) return;
    dragRef.current = { startX: event.clientX, startRot: rotation };
    (event.target as Element).setPointerCapture?.(event.pointerId);
  }
  function onPointerMove(event: ReactPointerEvent<SVGSVGElement>) {
    if (!dragRef.current) return;
    const delta = (event.clientX - dragRef.current.startX) / 140;
    setRotation(dragRef.current.startRot + delta);
  }
  function onPointerUp() {
    dragRef.current = null;
  }

  if (loading) {
    return (
      <div className="entity-graph-v2" role="status">
        <div className="entity-graph-v2-loading">
          <RefreshCw className="entity-graph-v2-spin" size={18} />
          Construyendo vista radial de entorno…
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="entity-graph-v2">
        <div className="inline-error" role="alert">
          {error}
          <button type="button" onClick={() => void loadGraph()}>
            Reintentar
          </button>
        </div>
      </div>
    );
  }

  if (!model || !centerNode) {
    return (
      <div className="entity-graph-v2">
        <p className="entity-graph-v2-empty">No hay datos de grafo para esta entidad.</p>
      </div>
    );
  }

  const stats = {
    totalNodes: model.nodes.length,
    totalEdges: model.edges.length,
    visibleNodes: visiblePlacements.length + 1,
    visibleEdges: radialEdges.length,
    truncated: Boolean(graph?.truncated),
  };

  return (
    <div className="entity-graph-v2">
      <header className="entity-graph-v2-header">
        <div>
          <p className="section-kicker">Grafo v2 · red ego radial</p>
          <h2>Entorno de {centerNode.label}</h2>
          <p>
            Vista enterprise por anillos de distancia (1–2 saltos). No es un force-layout completo:
            prioriza legibilidad y divulgación progresiva, como en herramientas de inteligencia
            corporativa y grafo de contrapartes.
          </p>
        </div>
        <div className="entity-graph-v2-metrics" aria-label="Métricas del grafo v2">
          <span>{stats.visibleNodes} nodos visibles</span>
          <span>{stats.totalNodes} recibidos</span>
          <span>{stats.totalEdges} vínculos</span>
          {hiddenByCap > 0 && <span className="is-warn">+{hiddenByCap} fuera del tope</span>}
          {stats.truncated && <span className="is-warn">Muestra truncada por proveedor</span>}
        </div>
      </header>

      <div className="entity-graph-v2-toolbar" role="toolbar" aria-label="Controles del grafo v2">
        <div className="entity-graph-v2-modes" role="tablist" aria-label="Modo de visualización">
          <button
            type="button"
            role="tab"
            aria-selected={viewMode === "radial"}
            className={viewMode === "radial" ? "is-active" : ""}
            onClick={() => setViewMode("radial")}
          >
            <Network size={14} /> Radial
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={viewMode === "directory"}
            className={viewMode === "directory" ? "is-active" : ""}
            onClick={() => setViewMode("directory")}
          >
            <List size={14} /> Directorio
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={viewMode === "matrix"}
            className={viewMode === "matrix" ? "is-active" : ""}
            onClick={() => setViewMode("matrix")}
          >
            <Grid3X3 size={14} /> Matriz
          </button>
        </div>

        <label>
          <span>Saltos</span>
          <select
            value={maxDepth}
            onChange={(e) => setMaxDepth(Number(e.target.value) as 1 | 2)}
            aria-label="Profundidad en saltos"
          >
            <option value={1}>1 salto (recomendado)</option>
            <option value={2}>2 saltos</option>
          </select>
        </label>

        <label>
          <span>Tope por anillo</span>
          <select
            value={ringCap}
            onChange={(e) => setRingCap(Number(e.target.value))}
            aria-label="Máximo de nodos por anillo"
          >
            <option value={24}>24</option>
            <option value={36}>36</option>
            <option value={48}>48</option>
            <option value={72}>72</option>
          </select>
        </label>

        <label>
          <span>Tipo</span>
          <select
            value={typeFilter}
            onChange={(e) => setTypeFilter(e.target.value as TypeFilter)}
            aria-label="Filtrar por tipo de entidad"
          >
            <option value="all">Todos</option>
            <option value="company">Empresas</option>
            <option value="person">Personas</option>
          </select>
        </label>

        <label className="entity-graph-v2-check">
          <input
            type="checkbox"
            checked={activeOnly}
            onChange={(e) => setActiveOnly(e.target.checked)}
          />
          Solo vínculos activos
        </label>

        <button type="button" className="vector-secondary compact" onClick={() => void loadGraph()}>
          <RefreshCw size={14} /> Recargar
        </button>
      </div>

      <div className="entity-graph-v2-body">
        <div className="entity-graph-v2-stage">
          {viewMode === "radial" && (
            <svg
              className="entity-graph-v2-svg"
              viewBox={`0 0 ${VIEW_W} ${VIEW_H}`}
              role="img"
              aria-label={`Grafo radial de ${centerNode.label}`}
              onPointerDown={onPointerDown}
              onPointerMove={onPointerMove}
              onPointerUp={onPointerUp}
              onPointerLeave={onPointerUp}
            >
              <defs>
                <radialGradient id="egv2-bg" cx="50%" cy="50%" r="65%">
                  <stop offset="0%" stopColor="#f8fbff" />
                  <stop offset="100%" stopColor="#eef3fa" />
                </radialGradient>
                <filter id="egv2-shadow" x="-30%" y="-30%" width="160%" height="160%">
                  <feDropShadow dx="0" dy="1" stdDeviation="1.4" floodOpacity="0.18" />
                </filter>
              </defs>
              <rect width={VIEW_W} height={VIEW_H} fill="url(#egv2-bg)" />

              {/* Guide rings */}
              {[1, 2]
                .filter((d) => d <= maxDepth)
                .map((d) => (
                  <g key={`ring-${d}`}>
                    <circle
                      cx={CX}
                      cy={CY}
                      r={RING_RADIUS[d]}
                      fill="none"
                      stroke="#c9d7e8"
                      strokeDasharray="4 6"
                      strokeWidth={1}
                    />
                    <text
                      x={CX + RING_RADIUS[d] - 8}
                      y={CY - 8}
                      className="entity-graph-v2-ring-label"
                      textAnchor="end"
                    >
                      {d === 1 ? "1er salto" : "2º salto"}
                    </text>
                  </g>
                ))}

              {/* Edges */}
              {radialEdges.map(({ edge, d, strong }) => (
                <path
                  key={edge.id}
                  d={d}
                  className={strong ? "entity-graph-v2-edge is-strong" : "entity-graph-v2-edge"}
                  fill="none"
                />
              ))}

              {/* Peripheral nodes */}
              {visiblePlacements.map((place) => {
                const active =
                  place.node.id === selectedId || place.node.id === hoveredId;
                const dimmed =
                  (selectedId || hoveredId) &&
                  place.node.id !== selectedId &&
                  place.node.id !== hoveredId;
                const showLabel =
                  active ||
                  place.depth === 1 && place.node.degree >= 3 ||
                  place.depth === 1 && visiblePlacements.filter((p) => p.depth === 1).length <= 18;
                return (
                  <g
                    key={place.node.id}
                    className={`entity-graph-v2-node${active ? " is-active" : ""}${dimmed ? " is-dimmed" : ""}`}
                    transform={`translate(${place.x} ${place.y})`}
                    onMouseEnter={() => setHoveredId(place.node.id)}
                    onMouseLeave={() => setHoveredId((id) => (id === place.node.id ? null : id))}
                    onClick={() => setSelectedId(place.node.id)}
                    onDoubleClick={() => openEntity(place.node.routeName, place.node.kind)}
                    style={{ cursor: "pointer" }}
                  >
                    <circle
                      r={place.radius}
                      fill={nodeFill(place.node.kind, false)}
                      stroke={active ? "#0f172a" : "#ffffff"}
                      strokeWidth={active ? 2.5 : 1.5}
                      filter="url(#egv2-shadow)"
                    />
                    {showLabel && (
                      <text
                        y={place.radius + 12}
                        textAnchor="middle"
                        className="entity-graph-v2-node-label"
                      >
                        {truncateLabel(place.node.label, place.depth === 1 ? 22 : 16)}
                      </text>
                    )}
                    <title>
                      {place.node.label}
                      {"\n"}
                      {place.node.kind === "person" ? "Persona" : "Empresa"}
                      {" · "}
                      {place.node.degree} vínculos · salto {place.depth}
                    </title>
                  </g>
                );
              })}

              {/* Center */}
              <g
                className="entity-graph-v2-center"
                transform={`translate(${CX} ${CY})`}
                onClick={() => setSelectedId(centerNode.id)}
                style={{ cursor: "pointer" }}
              >
                <circle r={CENTER_R + 10} fill="#0891b215" />
                <circle
                  r={CENTER_R}
                  fill={nodeFill(centerNode.kind, true)}
                  stroke="#0f172a"
                  strokeWidth={3}
                  filter="url(#egv2-shadow)"
                />
                <text y={4} textAnchor="middle" className="entity-graph-v2-center-glyph">
                  {centerNode.kind === "person" ? "P" : "E"}
                </text>
                <text y={CENTER_R + 18} textAnchor="middle" className="entity-graph-v2-center-label">
                  {truncateLabel(centerNode.label, 34)}
                </text>
              </g>

              <text x={16} y={VIEW_H - 14} className="entity-graph-v2-hint">
                Arrastra horizontalmente para rotar · clic selecciona · doble clic abre ficha
              </text>
            </svg>
          )}

          {viewMode === "directory" && (
            <div className="entity-graph-v2-directory">
              <div className="entity-graph-v2-directory-search">
                <Search size={15} aria-hidden="true" />
                <input
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  placeholder="Filtrar vecinos por nombre…"
                  aria-label="Filtrar vecinos"
                />
              </div>
              <table>
                <thead>
                  <tr>
                    <th>Entidad</th>
                    <th>Tipo</th>
                    <th>Salto</th>
                    <th>Grado</th>
                    <th>Roles con el foco</th>
                    <th />
                  </tr>
                </thead>
                <tbody>
                  {neighborRows.slice(0, 120).map(({ node, depth, roles }) => (
                    <tr
                      key={node.id}
                      className={selectedId === node.id ? "is-selected" : ""}
                      onClick={() => setSelectedId(node.id)}
                    >
                      <td>
                        <strong>{node.label}</strong>
                      </td>
                      <td>{node.kind === "person" ? "Persona" : "Empresa"}</td>
                      <td>{depth}</td>
                      <td>{node.degree}</td>
                      <td>{roles.length ? roles.join(", ") : "—"}</td>
                      <td>
                        <button
                          type="button"
                          className="vector-secondary compact"
                          onClick={(e) => {
                            e.stopPropagation();
                            openEntity(node.routeName, node.kind);
                          }}
                        >
                          Abrir <ChevronRight size={13} />
                        </button>
                      </td>
                    </tr>
                  ))}
                  {!neighborRows.length && (
                    <tr>
                      <td colSpan={6}>Ningún vecino con los filtros actuales.</td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          )}

          {viewMode === "matrix" && (
            <div className="entity-graph-v2-matrix-wrap">
              <p>
                Matriz de adyacencia de los 12 vecinos de mayor grado del 1er salto más el foco.
                Una celda marcada indica al menos un vínculo en la muestra.
              </p>
              <div className="entity-graph-v2-matrix-scroll">
                <table className="entity-graph-v2-matrix">
                  <thead>
                    <tr>
                      <th />
                      {matrixNodes.map((n) => (
                        <th key={n.id} title={n.label}>
                          {truncateLabel(n.label, 10)}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {matrixNodes.map((row) => (
                      <tr key={row.id}>
                        <th title={row.label}>{truncateLabel(row.label, 16)}</th>
                        {matrixNodes.map((col) => {
                          if (row.id === col.id) {
                            return <td key={col.id} className="is-diag" />;
                          }
                          const linked = matrixLinks.has(`${row.id}→${col.id}`);
                          return (
                            <td
                              key={col.id}
                              className={linked ? "is-link" : ""}
                              title={
                                linked
                                  ? `${row.label} ↔ ${col.label}`
                                  : `${row.label} — ${col.label}`
                              }
                            >
                              {linked ? "●" : ""}
                            </td>
                          );
                        })}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </div>

        <aside className="entity-graph-v2-side" aria-label="Detalle del nodo">
          {!selectedNode ? (
            <>
              <h3>
                <CircleDot size={16} /> Foco actual
              </h3>
              <p>{centerNode.label}</p>
              <dl>
                <div>
                  <dt>Tipo</dt>
                  <dd>{centerNode.kind === "person" ? "Persona" : "Empresa"}</dd>
                </div>
                <div>
                  <dt>Grado en muestra</dt>
                  <dd>{centerNode.degree}</dd>
                </div>
                <div>
                  <dt>Vecinos 1er salto</dt>
                  <dd>
                    {model.nodes.filter((n) => (model.depths.get(n.id) ?? 99) === 1).length}
                  </dd>
                </div>
                <div>
                  <dt>Vecinos 2º salto</dt>
                  <dd>
                    {model.nodes.filter((n) => (model.depths.get(n.id) ?? 99) === 2).length}
                  </dd>
                </div>
              </dl>
              <p className="entity-graph-v2-side-hint">
                Selecciona un nodo del anillo o del directorio para ver roles y abrir su ficha.
              </p>
              <div className="entity-graph-v2-legend">
                <span><i style={{ background: "#0891b2" }} /> Foco</span>
                <span><i style={{ background: "#2563eb" }} /> Empresa</span>
                <span><i style={{ background: "#7c3aed" }} /> Persona</span>
              </div>
            </>
          ) : (
            <>
              <h3>
                {selectedNode.kind === "person" ? <UserRound size={16} /> : <Building2 size={16} />}
                {selectedNode.label}
              </h3>
              <dl>
                <div>
                  <dt>Tipo</dt>
                  <dd>{selectedNode.kind === "person" ? "Persona" : "Empresa"}</dd>
                </div>
                <div>
                  <dt>Salto desde el foco</dt>
                  <dd>{model.depths.get(selectedNode.id) ?? "—"}</dd>
                </div>
                <div>
                  <dt>Grado</dt>
                  <dd>{selectedNode.degree}</dd>
                </div>
                <div>
                  <dt>Roles con el foco</dt>
                  <dd>
                    {filteredEdges
                      .filter(
                        (e) =>
                          (e.source === model.centerId && e.target === selectedNode.id) ||
                          (e.target === model.centerId && e.source === selectedNode.id),
                      )
                      .map((e) => e.role)
                      .filter((v, i, a) => a.indexOf(v) === i)
                      .join(", ") || "Sin vínculo directo en la muestra"}
                  </dd>
                </div>
              </dl>
              <div className="entity-graph-v2-side-actions">
                <button
                  type="button"
                  className="vector-primary"
                  onClick={() => openEntity(selectedNode.routeName, selectedNode.kind)}
                >
                  Abrir ficha <ExternalLink size={14} />
                </button>
                <button
                  type="button"
                  className="vector-secondary"
                  onClick={() => setSelectedId(null)}
                >
                  Quitar selección
                </button>
              </div>
            </>
          )}
        </aside>
      </div>
    </div>
  );
}
