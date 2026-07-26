"use client";

/**
 * Entity Graph V2 — interactive ego-network (radial) with enterprise controls.
 *
 * Adds navigation utilities comparable to Grafo v1 without force-layout hairballs:
 * - Zoom / pan / fit
 * - Re-root focus on any selected entity (explore branches in-place)
 * - Expand / collapse neighborhood of a node
 * - Isolation of direct environment
 * - Directory + adjacency matrix modes
 *
 * Does not modify EntityGraphExplorer (Grafo v1).
 */

import {
  ApiError,
  api,
  type EntityIntelGraphEdge,
  type EntityIntelGraphNode,
  type EntityIntelGraphResponse,
  type EntityIntelKind,
} from "@oracle/api-client";
import {
  Building2,
  ChevronRight,
  CircleDot,
  Expand,
  ExternalLink,
  Focus,
  GitBranchPlus,
  Grid3X3,
  List,
  Minimize2,
  Network,
  RefreshCw,
  Scan,
  Search,
  Shrink,
  UserRound,
  ZoomIn,
  ZoomOut,
} from "lucide-react";
import { useRouter } from "next/navigation";
import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type PointerEvent as ReactPointerEvent,
  type WheelEvent as ReactWheelEvent,
} from "react";
import { entityRoute } from "@/lib/entity-route";
import { graphNodeDepths } from "./entity-graph-layout";
import {
  allCategoryKeys,
  edgeMatchesRoleCategories,
  edgeRoleCategories,
  GRAPH_ROLE_CATEGORY_META,
  graphRoleCategoryOptions,
  primaryRoleCategory,
  type GraphRoleCategory,
} from "./entity-graph-roles";

type ViewMode = "radial" | "directory" | "matrix";
type TypeFilter = "all" | "company" | "person";
type DragMode = "pan" | "rotate" | null;

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
  categories: GraphRoleCategory[];
  primaryCategory: GraphRoleCategory;
  raw: EntityIntelGraphEdge;
}

interface RingPlacement {
  node: NormalizedNode;
  depth: number;
  angle: number;
  x: number;
  y: number;
  radius: number;
  parentId: string | null;
}

const VIEW_W = 920;
const VIEW_H = 640;
const CX = VIEW_W / 2;
const CY = VIEW_H / 2;
const RING_RADIUS: Record<number, number> = { 1: 200, 2: 300 };
const CENTER_R = 28;
const DEFAULT_RING_CAP = 72;
const MIN_ZOOM = 0.45;
const MAX_ZOOM = 2.8;

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
  const exact = nodes.find(
    (n) => normalizeFold(n.routeName) === needle || normalizeFold(n.label) === needle,
  );
  if (exact) return exact.id;
  const partial = nodes.find(
    (n) =>
      normalizeFold(n.label).includes(needle) || normalizeFold(n.routeName).includes(needle),
  );
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
    const categories = edgeRoleCategories(edge);
    return [
      {
        id: String(edge.id ?? `${source}-${target}-${index}`),
        source,
        target,
        role: edgeRole(edge),
        active: typeof edge.active === "boolean" ? edge.active : null,
        date: typeof edge.date === "string" ? edge.date : null,
        categories,
        primaryCategory: primaryRoleCategory(edge),
        raw: edge,
      },
    ];
  });
  const degreeFromEdges = new Map<string, number>();
  for (const edge of edges) {
    degreeFromEdges.set(edge.source, (degreeFromEdges.get(edge.source) ?? 0) + 1);
    degreeFromEdges.set(edge.target, (degreeFromEdges.get(edge.target) ?? 0) + 1);
  }
  for (const node of nodes) {
    if (node.degree <= 0) node.degree = degreeFromEdges.get(node.id) ?? 0;
  }
  const rootId = findCenterId(nodes, queryName);
  for (const node of nodes) node.isCenter = node.id === rootId;

  const adjacency = new Map<string, Set<string>>();
  for (const node of nodes) adjacency.set(node.id, new Set());
  for (const edge of edges) {
    adjacency.get(edge.source)?.add(edge.target);
    adjacency.get(edge.target)?.add(edge.source);
  }

  return { nodes, edges, rootId, adjacency };
}

function depthsFrom(
  focusId: string,
  adjacency: Map<string, Set<string>>,
  nodeIds: string[],
): Map<string, number> {
  return graphNodeDepths(
    focusId,
    nodeIds,
    [...adjacency.entries()].flatMap(([source, targets]) =>
      [...targets].map((target) => ({ source, target })),
    ),
  );
}

function nodeFill(kind: NormalizedNode["kind"], isFocus: boolean): string {
  if (isFocus) return "#0891b2";
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

/**
 * Place the label outside the node disc so the circle never covers the name.
 * Uses the radial angle (outward from graph focus) to pick left / right / top / bottom.
 */
function labelLayout(
  angle: number,
  nodeRadius: number,
): {
  x: number;
  y: number;
  textAnchor: "start" | "middle" | "end";
  dominantBaseline: "auto" | "middle" | "hanging";
} {
  const gap = nodeRadius + 10;
  const cos = Math.cos(angle);
  const sin = Math.sin(angle);
  // Prefer side labels when the node is more on the left/right of the ring.
  if (Math.abs(cos) >= Math.abs(sin) * 0.85) {
    if (cos >= 0) {
      return {
        x: gap,
        y: 0,
        textAnchor: "start",
        dominantBaseline: "middle",
      };
    }
    return {
      x: -gap,
      y: 0,
      textAnchor: "end",
      dominantBaseline: "middle",
    };
  }
  if (sin >= 0) {
    return {
      x: 0,
      y: gap + 2,
      textAnchor: "middle",
      dominantBaseline: "hanging",
    };
  }
  return {
    x: 0,
    y: -gap - 2,
    textAnchor: "middle",
    dominantBaseline: "auto",
  };
}

function placeRing(
  candidates: NormalizedNode[],
  depth: number,
  cap: number,
  parentId: string | null,
  rotation: number,
  degreeById?: Map<string, number>,
): RingPlacement[] {
  const degreeOf = (node: NormalizedNode) => degreeById?.get(node.id) ?? node.degree;
  const sorted = [...candidates].sort(
    (a, b) => degreeOf(b) - degreeOf(a) || a.label.localeCompare(b.label, "es"),
  );
  const limited = sorted.slice(0, cap);
  const ringR = RING_RADIUS[depth] ?? 210;
  const count = Math.max(limited.length, 1);
  return limited.map((node, index) => {
    const angle = -Math.PI / 2 + rotation + (index / count) * Math.PI * 2;
    const { x, y } = polar(angle, ringR);
    const deg = degreeOf(node);
    const radius = Math.min(18, Math.max(9, 8 + Math.sqrt(deg + 1) * 1.6));
    return { node, depth, angle, x, y, radius, parentId };
  });
}

function buildAdjacency(edges: Array<{ source: string; target: string }>, nodeIds: string[]) {
  const adjacency = new Map<string, Set<string>>();
  for (const id of nodeIds) adjacency.set(id, new Set());
  for (const edge of edges) {
    adjacency.get(edge.source)?.add(edge.target);
    adjacency.get(edge.target)?.add(edge.source);
  }
  return adjacency;
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
  const svgRef = useRef<SVGSVGElement | null>(null);
  const [graph, setGraph] = useState<EntityIntelGraphResponse | null>(initialGraph);
  const [loading, setLoading] = useState(!initialGraph);
  const [error, setError] = useState<string | null>(null);
  const [activeOnly, setActiveOnly] = useState(false);
  const [maxDepth, setMaxDepth] = useState<1 | 2>(1);
  const [ringCap, setRingCap] = useState(DEFAULT_RING_CAP);
  const [typeFilter, setTypeFilter] = useState<TypeFilter>("all");
  /** null = all families present in the graph (default on load). */
  const [enabledCategories, setEnabledCategories] = useState<Set<GraphRoleCategory> | null>(
    null,
  );
  const [viewMode, setViewMode] = useState<ViewMode>("radial");
  const [query, setQuery] = useState("");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [hoveredId, setHoveredId] = useState<string | null>(null);
  const [focusId, setFocusId] = useState<string | null>(null);
  const [expandedIds, setExpandedIds] = useState<Set<string>>(() => new Set());
  const [collapsedIds, setCollapsedIds] = useState<Set<string>>(() => new Set());
  const [isolatedId, setIsolatedId] = useState<string | null>(null);
  const [focusTrail, setFocusTrail] = useState<string[]>([]);
  const [rotation, setRotation] = useState(0);
  const [zoom, setZoom] = useState(1);
  const [pan, setPan] = useState({ x: 0, y: 0 });
  const dragRef = useRef<{
    mode: DragMode;
    startX: number;
    startY: number;
    startPanX: number;
    startPanY: number;
    startRot: number;
  } | null>(null);

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
      setFocusId(null);
      setExpandedIds(new Set());
      setCollapsedIds(new Set());
      setIsolatedId(null);
      setFocusTrail([]);
      setEnabledCategories(null); // all families on reload
      setZoom(1);
      setPan({ x: 0, y: 0 });
      setRotation(0);
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

  const roleCategoryOptions = useMemo(() => graphRoleCategoryOptions(graph), [graph]);

  const effectiveCategories = useMemo(() => {
    const available = allCategoryKeys(roleCategoryOptions);
    if (available.length === 0) {
      return new Set<GraphRoleCategory>([
        "governance",
        "representation",
        "audit",
        "ownership",
        "liquidation",
        "other",
      ]);
    }
    if (enabledCategories === null) return new Set(available);
    // Keep only categories that still exist in the loaded graph.
    const next = new Set<GraphRoleCategory>();
    for (const key of enabledCategories) {
      if (available.includes(key)) next.add(key);
    }
    return next.size > 0 ? next : new Set(available);
  }, [enabledCategories, roleCategoryOptions]);

  const allFamiliesEnabled =
    roleCategoryOptions.length > 0 &&
    roleCategoryOptions.every((opt) => effectiveCategories.has(opt.key));

  // Active radial focus (re-root without leaving the page).
  const activeFocusId = focusId ?? model?.rootId ?? null;

  const filteredEdges = useMemo(() => {
    if (!model) return [];
    return model.edges.filter((edge) => {
      if (activeOnly && edge.active === false) return false;
      return edgeMatchesRoleCategories(edge.raw, effectiveCategories);
    });
  }, [activeOnly, effectiveCategories, model]);

  const filteredAdjacency = useMemo(() => {
    if (!model) return new Map<string, Set<string>>();
    return buildAdjacency(
      filteredEdges,
      model.nodes.map((n) => n.id),
    );
  }, [filteredEdges, model]);

  const filteredDegree = useMemo(() => {
    const map = new Map<string, number>();
    for (const [id, neighbors] of filteredAdjacency) {
      map.set(id, neighbors.size);
    }
    return map;
  }, [filteredAdjacency]);

  const depths = useMemo(() => {
    if (!model || !activeFocusId) return new Map<string, number>();
    return depthsFrom(
      activeFocusId,
      filteredAdjacency,
      model.nodes.map((n) => n.id),
    );
  }, [activeFocusId, filteredAdjacency, model]);

  const visibleNodeIds = useMemo(() => {
    if (!model || !activeFocusId) return new Set<string>();
    const visible = new Set<string>([activeFocusId]);

    // Base ego neighborhood: only the global depth control (not expansion).
    for (const node of model.nodes) {
      if (node.id === activeFocusId) continue;
      const depth = depths.get(node.id);
      if (depth == null || depth < 1 || depth > maxDepth) continue;
      if (typeFilter !== "all" && node.kind !== typeFilter) continue;
      visible.add(node.id);
    }

    // Branch expansion: exclusive neighbors via filtered (role-family) adjacency only.
    for (const expanded of expandedIds) {
      if (!visible.has(expanded) && expanded !== activeFocusId) continue;
      if (collapsedIds.has(expanded)) continue;
      for (const neighbor of filteredAdjacency.get(expanded) ?? []) {
        if (neighbor === activeFocusId) continue;
        const n = model.nodes.find((node) => node.id === neighbor);
        if (!n) continue;
        if (typeFilter !== "all" && n.kind !== typeFilter) continue;
        visible.add(neighbor);
      }
    }

    // Collapse: hide nodes that only remain visible through a collapsed branch parent.
    if (collapsedIds.size > 0) {
      for (const nodeId of [...visible]) {
        if (nodeId === activeFocusId) continue;
        const depth = depths.get(nodeId) ?? 99;
        if (depth <= 1) continue;

        const adjacencyParents = [...(filteredAdjacency.get(nodeId) ?? [])];
        const collapsedParents = adjacencyParents.filter((p) => collapsedIds.has(p));
        if (collapsedParents.length === 0) continue;

        if (depth > maxDepth) {
          visible.delete(nodeId);
          continue;
        }

        const depth1Parents = adjacencyParents.filter((p) => (depths.get(p) ?? 99) === 1);
        if (depth1Parents.length > 0 && depth1Parents.every((p) => collapsedIds.has(p))) {
          visible.delete(nodeId);
        }
      }
    }

    // Isolation: focus + direct filtered neighbors (and expanded branch of the isolate).
    if (isolatedId) {
      const keep = new Set<string>([isolatedId]);
      for (const neighbor of filteredAdjacency.get(isolatedId) ?? []) keep.add(neighbor);
      if (expandedIds.has(isolatedId) && !collapsedIds.has(isolatedId)) {
        for (const neighbor of filteredAdjacency.get(isolatedId) ?? []) {
          for (const second of filteredAdjacency.get(neighbor) ?? []) keep.add(second);
        }
      }
      for (const id of [...visible]) {
        if (!keep.has(id)) visible.delete(id);
      }
      visible.add(isolatedId);
    }

    return visible;
  }, [
    activeFocusId,
    collapsedIds,
    depths,
    expandedIds,
    filteredAdjacency,
    isolatedId,
    maxDepth,
    model,
    typeFilter,
  ]);

  const visiblePlacements = useMemo(() => {
    if (!model || !activeFocusId) return [] as RingPlacement[];

    // Which expanded parent "owns" an expansion-only node (for layout near the branch).
    const expansionParent = new Map<string, string>();
    for (const expanded of expandedIds) {
      if (collapsedIds.has(expanded)) continue;
      for (const neighbor of filteredAdjacency.get(expanded) ?? []) {
        if (neighbor === activeFocusId) continue;
        const depth = depths.get(neighbor) ?? 99;
        // Only claim nodes that are not already in the base ego ring(s).
        if (depth <= maxDepth) continue;
        if (!visibleNodeIds.has(neighbor)) continue;
        if (!expansionParent.has(neighbor)) expansionParent.set(neighbor, expanded);
      }
    }

    const ring1: NormalizedNode[] = [];
    const ring2Base: NormalizedNode[] = [];
    const ring2ByParent = new Map<string, NormalizedNode[]>();

    for (const node of model.nodes) {
      if (!visibleNodeIds.has(node.id) || node.id === activeFocusId) continue;
      const depth = depths.get(node.id) ?? 99;
      if (depth < 1) continue;

      // Base depth-1 always on ring 1.
      if (depth === 1) {
        ring1.push(node);
        continue;
      }

      // Expansion-only: ring 2, grouped under their expanded parent.
      const parent = expansionParent.get(node.id);
      if (parent) {
        const bucket = ring2ByParent.get(parent) ?? [];
        bucket.push(node);
        ring2ByParent.set(parent, bucket);
        continue;
      }

      // Base depth-2 (global maxDepth === 2).
      if (depth <= maxDepth) {
        ring2Base.push(node);
      }
    }

    const placements: RingPlacement[] = [];
    placements.push(...placeRing(ring1, 1, ringCap, activeFocusId, rotation, filteredDegree));

    // Place base depth-2 evenly, then expansion children clustered near their parent angle.
    const parentAngle = new Map<string, number>();
    for (const p of placements) parentAngle.set(p.node.id, p.angle);

    if (maxDepth >= 2 && ring2Base.length > 0) {
      placements.push(...placeRing(ring2Base, 2, ringCap, null, rotation, filteredDegree));
    }

    let expansionSlotsLeft = ringCap;
    for (const [parentId, children] of ring2ByParent) {
      if (expansionSlotsLeft <= 0) break;
      const limited = [...children]
        .sort(
          (a, b) =>
            (filteredDegree.get(b.id) ?? b.degree) - (filteredDegree.get(a.id) ?? a.degree) ||
            a.label.localeCompare(b.label, "es"),
        )
        .slice(0, expansionSlotsLeft);
      expansionSlotsLeft -= limited.length;
      const baseAngle = parentAngle.get(parentId) ?? -Math.PI / 2 + rotation;
      const spread = Math.min(Math.PI / 2.4, Math.max(0.35, limited.length * 0.28));
      const ringR = RING_RADIUS[2] ?? 300;
      limited.forEach((node, index) => {
        const t = limited.length === 1 ? 0.5 : index / (limited.length - 1);
        const angle = baseAngle - spread / 2 + t * spread;
        const { x, y } = polar(angle, ringR);
        const deg = filteredDegree.get(node.id) ?? node.degree;
        const radius = Math.min(18, Math.max(9, 8 + Math.sqrt(deg + 1) * 1.6));
        placements.push({
          node,
          depth: 2,
          angle,
          x,
          y,
          radius,
          parentId,
        });
      });
    }

    return placements;
  }, [
    activeFocusId,
    collapsedIds,
    depths,
    expandedIds,
    filteredAdjacency,
    filteredDegree,
    maxDepth,
    model,
    ringCap,
    rotation,
    visibleNodeIds,
  ]);

  const placementById = useMemo(() => {
    const map = new Map<string, RingPlacement>();
    for (const p of visiblePlacements) map.set(p.node.id, p);
    return map;
  }, [visiblePlacements]);

  const focusNode = useMemo(
    () => model?.nodes.find((n) => n.id === activeFocusId) ?? null,
    [activeFocusId, model],
  );

  const selectedNode = useMemo(() => {
    if (!model || !selectedId) return null;
    return model.nodes.find((n) => n.id === selectedId) ?? null;
  }, [model, selectedId]);

  const selectedNeighborCount = useMemo(() => {
    if (!selectedId) return 0;
    return filteredAdjacency.get(selectedId)?.size ?? 0;
  }, [filteredAdjacency, selectedId]);

  /** Neighbors of the selection that expand would newly reveal (excludes focus + already base-visible). */
  const selectedExpandableCount = useMemo(() => {
    if (!model || !selectedId || !activeFocusId) return 0;
    let count = 0;
    for (const neighbor of filteredAdjacency.get(selectedId) ?? []) {
      if (neighbor === activeFocusId) continue;
      const depth = depths.get(neighbor) ?? 99;
      // Already in the base ego rings controlled by maxDepth.
      if (depth >= 1 && depth <= maxDepth) continue;
      const n = model.nodes.find((node) => node.id === neighbor);
      if (!n) continue;
      if (typeFilter !== "all" && n.kind !== typeFilter) continue;
      count += 1;
    }
    return count;
  }, [activeFocusId, depths, filteredAdjacency, maxDepth, model, selectedId, typeFilter]);

  const selectedIsExpanded = selectedId ? expandedIds.has(selectedId) : false;
  const selectedIsCollapsed = selectedId ? collapsedIds.has(selectedId) : false;

  const neighborRows = useMemo(() => {
    if (!model || !activeFocusId) return [];
    return model.nodes
      .filter((node) => {
        if (!visibleNodeIds.has(node.id) || node.id === activeFocusId) return false;
        if (query.trim()) {
          const q = normalizeFold(query);
          if (
            !normalizeFold(node.label).includes(q) &&
            !normalizeFold(node.routeName).includes(q)
          ) {
            return false;
          }
        }
        return true;
      })
      .map((node) => {
        const depth = depths.get(node.id) ?? 99;
        const linkRoles = filteredEdges
          .filter(
            (e) =>
              (e.source === activeFocusId && e.target === node.id) ||
              (e.target === activeFocusId && e.source === node.id),
          )
          .map((e) => e.role);
        return {
          node,
          depth,
          roles: Array.from(new Set(linkRoles)).slice(0, 4),
        };
      })
      .sort(
        (a, b) =>
          a.depth - b.depth ||
          b.node.degree - a.node.degree ||
          a.node.label.localeCompare(b.node.label, "es"),
      );
  }, [activeFocusId, depths, filteredEdges, model, query, visibleNodeIds]);

  const matrixNodes = useMemo(() => {
    if (!model || !activeFocusId) return [] as NormalizedNode[];
    const focus = model.nodes.find((n) => n.id === activeFocusId);
    if (!focus) return [];
    const direct = model.nodes
      .filter((n) => n.id !== activeFocusId && (depths.get(n.id) ?? 99) === 1)
      .sort(
        (a, b) =>
          (filteredDegree.get(b.id) ?? b.degree) - (filteredDegree.get(a.id) ?? a.degree) ||
          a.label.localeCompare(b.label, "es"),
      )
      .slice(0, 12);
    return [focus, ...direct];
  }, [activeFocusId, depths, filteredDegree, model]);

  const matrixLinks = useMemo(() => {
    const set = new Set<string>();
    for (const edge of filteredEdges) {
      set.add(`${edge.source}→${edge.target}`);
      set.add(`${edge.target}→${edge.source}`);
    }
    return set;
  }, [filteredEdges]);

  const radialEdges = useMemo(() => {
    if (!model || !activeFocusId) {
      return [] as Array<{ edge: NormalizedEdge; d: string; strong: boolean }>;
    }
    const result: Array<{ edge: NormalizedEdge; d: string; strong: boolean }> = [];
    const focusPos = { x: CX, y: CY };
    for (const edge of filteredEdges) {
      const touchesFocus =
        edge.source === activeFocusId || edge.target === activeFocusId;
      if (touchesFocus) {
        const other = edge.source === activeFocusId ? edge.target : edge.source;
        if (!visibleNodeIds.has(other)) continue;
        const place = placementById.get(other);
        if (!place) continue;
        const strong =
          hoveredId === other ||
          selectedId === other ||
          hoveredId === activeFocusId ||
          selectedId === activeFocusId;
        result.push({
          edge,
          strong,
          d: arcPath(focusPos.x, focusPos.y, place.x, place.y, 0.08),
        });
        continue;
      }
      if (!visibleNodeIds.has(edge.source) || !visibleNodeIds.has(edge.target)) continue;
      const p1 = placementById.get(edge.source);
      const p2 = placementById.get(edge.target);
      if (!p1 || !p2) continue;
      const strong =
        hoveredId === edge.source ||
        hoveredId === edge.target ||
        selectedId === edge.source ||
        selectedId === edge.target;
      // Peer edges: only when strong or both at depth 1 with maxDepth 1
      if (!strong && (p1.depth > 1 || p2.depth > 1)) continue;
      if (!strong && maxDepth === 2 && visiblePlacements.length > 40) continue;
      result.push({
        edge,
        strong,
        d: arcPath(p1.x, p1.y, p2.x, p2.y, 0.18),
      });
    }
    return result;
  }, [
    activeFocusId,
    filteredEdges,
    hoveredId,
    maxDepth,
    model,
    placementById,
    selectedId,
    visibleNodeIds,
    visiblePlacements.length,
  ]);

  const hiddenByCap = useMemo(() => {
    if (!model || !activeFocusId) return 0;
    let eligible = 0;
    for (const node of model.nodes) {
      if (node.id === activeFocusId) continue;
      const depth = depths.get(node.id);
      if (depth == null || depth < 1 || depth > maxDepth) continue;
      if (typeFilter !== "all" && node.kind !== typeFilter) continue;
      eligible += 1;
    }
    return Math.max(0, eligible - visiblePlacements.length);
  }, [activeFocusId, depths, maxDepth, model, typeFilter, visiblePlacements.length]);

  function openEntity(routeName: string, kind: EntityIntelKind | "entity") {
    const k: EntityIntelKind = kind === "person" ? "person" : "company";
    router.push(entityRoute(k, routeName));
  }

  function reRootTo(nodeId: string) {
    if (!model) return;
    const node = model.nodes.find((n) => n.id === nodeId);
    if (!node) return;
    setFocusTrail((trail) => {
      if (activeFocusId && trail[trail.length - 1] !== activeFocusId) {
        return [...trail, activeFocusId];
      }
      return trail.length ? trail : activeFocusId ? [activeFocusId] : [];
    });
    setFocusId(nodeId);
    setSelectedId(nodeId);
    setIsolatedId(null);
    setExpandedIds(new Set());
    setCollapsedIds(new Set());
    setRotation(0);
    setZoom(1);
    setPan({ x: 0, y: 0 });
    setMaxDepth(1);
  }

  function goBackFocus() {
    setFocusTrail((trail) => {
      if (!trail.length) {
        setFocusId(model?.rootId ?? null);
        return [];
      }
      const next = [...trail];
      const prev = next.pop()!;
      setFocusId(prev);
      setSelectedId(prev);
      return next;
    });
    setIsolatedId(null);
    setExpandedIds(new Set());
    setCollapsedIds(new Set());
    setZoom(1);
    setPan({ x: 0, y: 0 });
  }

  function resetToRoot() {
    setFocusId(model?.rootId ?? null);
    setFocusTrail([]);
    setIsolatedId(null);
    setExpandedIds(new Set());
    setCollapsedIds(new Set());
    setSelectedId(model?.rootId ?? null);
    setZoom(1);
    setPan({ x: 0, y: 0 });
    setRotation(0);
    setMaxDepth(1);
  }

  function expandSelected() {
    if (!selectedId || !model) return;
    // Branch-local only: never raise global maxDepth (that would reveal every 2º salto).
    setCollapsedIds((prev) => {
      const next = new Set(prev);
      next.delete(selectedId);
      return next;
    });
    setExpandedIds((prev) => new Set(prev).add(selectedId));
    setIsolatedId(null);
  }

  function collapseSelected() {
    if (!selectedId) return;
    setExpandedIds((prev) => {
      const next = new Set(prev);
      next.delete(selectedId);
      return next;
    });
    setCollapsedIds((prev) => new Set(prev).add(selectedId));
  }

  function isolateSelected() {
    if (!selectedId) return;
    setIsolatedId(selectedId);
    setExpandedIds(new Set());
  }

  function clearIsolation() {
    setIsolatedId(null);
  }

  function zoomBy(factor: number) {
    setZoom((z) => Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, z * factor)));
  }

  function fitView() {
    setZoom(1);
    setPan({ x: 0, y: 0 });
    setRotation(0);
  }

  function onPointerDown(event: ReactPointerEvent<SVGSVGElement>) {
    if (event.button !== 0) return;
    const target = event.target as Element;
    // Don't pan when clicking nodes (they stopPropagation). Background pans; Alt/Shift rotates.
    const mode: DragMode = event.altKey || event.shiftKey ? "rotate" : "pan";
    dragRef.current = {
      mode,
      startX: event.clientX,
      startY: event.clientY,
      startPanX: pan.x,
      startPanY: pan.y,
      startRot: rotation,
    };
    svgRef.current?.setPointerCapture?.(event.pointerId);
  }

  function onPointerMove(event: ReactPointerEvent<SVGSVGElement>) {
    if (!dragRef.current) return;
    const { mode, startX, startY, startPanX, startPanY, startRot } = dragRef.current;
    if (mode === "rotate") {
      setRotation(startRot + (event.clientX - startX) / 140);
      return;
    }
    setPan({
      x: startPanX + (event.clientX - startX) / zoom,
      y: startPanY + (event.clientY - startY) / zoom,
    });
  }

  function onPointerUp() {
    dragRef.current = null;
  }

  function onWheel(event: ReactWheelEvent<SVGSVGElement>) {
    event.preventDefault();
    const factor = event.deltaY > 0 ? 0.9 : 1.1;
    setZoom((z) => Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, z * factor)));
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

  if (!model || !focusNode || !activeFocusId) {
    return (
      <div className="entity-graph-v2">
        <p className="entity-graph-v2-empty">No hay datos de grafo para esta entidad.</p>
      </div>
    );
  }

  const worldTransform = `translate(${CX + pan.x} ${CY + pan.y}) scale(${zoom}) translate(${-CX} ${-CY})`;
  const isOffRoot = Boolean(focusId && model.rootId && focusId !== model.rootId);

  return (
    <div className="entity-graph-v2">
      <header className="entity-graph-v2-header">
        <div>
          <p className="section-kicker">Grafo v2 · exploración interactiva</p>
          <h2>Entorno de {focusNode.label}</h2>
          <p>
            Red ego radial con zoom, pan, re-centrado de foco y expansión/colapso de ramas.
            La legibilidad se mantiene con anillos de distancia; no se pinta el hairball completo.
          </p>
          {isOffRoot && (
            <p className="entity-graph-v2-trail">
              Explorando desde un nodo secundario
              {focusTrail.length > 0 ? ` · ${focusTrail.length} paso(s) en la ruta` : ""}.
            </p>
          )}
        </div>
        <div className="entity-graph-v2-metrics" aria-label="Métricas del grafo v2">
          <span>{visiblePlacements.length + 1} nodos visibles</span>
          <span>{model.nodes.length} recibidos</span>
          <span>{model.edges.length} vínculos</span>
          <span>Zoom {Math.round(zoom * 100)}%</span>
          {hiddenByCap > 0 && <span className="is-warn">+{hiddenByCap} fuera del tope</span>}
          {graph?.truncated && <span className="is-warn">Muestra truncada</span>}
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

        {viewMode === "radial" && (
          <div className="entity-graph-v2-zoombar" aria-label="Zoom y encuadre">
            <button type="button" className="vector-secondary compact" onClick={() => zoomBy(1.15)} aria-label="Acercar">
              <ZoomIn size={14} />
            </button>
            <button type="button" className="vector-secondary compact" onClick={() => zoomBy(1 / 1.15)} aria-label="Alejar">
              <ZoomOut size={14} />
            </button>
            <button type="button" className="vector-secondary compact" onClick={fitView} aria-label="Reencuadrar">
              <Scan size={14} /> Reencuadrar
            </button>
            <span>{Math.round(zoom * 100)}%</span>
          </div>
        )}

        <label>
          <span>Saltos</span>
          <select
            value={maxDepth}
            onChange={(e) => setMaxDepth(Number(e.target.value) as 1 | 2)}
            aria-label="Profundidad en saltos"
          >
            <option value={1}>1 salto</option>
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
            <option value={100}>100</option>
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

        {(isOffRoot || isolatedId || expandedIds.size > 0 || collapsedIds.size > 0) && (
          <button type="button" className="vector-secondary compact" onClick={resetToRoot}>
            <Minimize2 size={14} /> Restaurar foco raíz
          </button>
        )}

        {focusTrail.length > 0 && (
          <button type="button" className="vector-secondary compact" onClick={goBackFocus}>
            ← Foco anterior
          </button>
        )}

        <button type="button" className="vector-secondary compact" onClick={() => void loadGraph()}>
          <RefreshCw size={14} /> Recargar
        </button>
      </div>

      {roleCategoryOptions.length > 0 && (
        <section
          className="entity-graph-v2-role-families"
          aria-label="Lecturas rápidas por familia de vínculo"
        >
          <header>
            <div>
              <strong>Lecturas rápidas por familia</strong>
              <small>
                Filtros voluntarios; al entrar se muestran todas las relaciones. Activa una, varias
                o todas — también aplica al expandir ramas y al recentrar el foco.
              </small>
            </div>
            <div className="entity-role-filter-actions">
              <button
                type="button"
                onClick={() => setEnabledCategories(new Set(allCategoryKeys(roleCategoryOptions)))}
              >
                Todas
              </button>
            </div>
          </header>
          <div className="entity-graph-v2-role-family-chips">
            {roleCategoryOptions.map((category) => {
              const pressed = effectiveCategories.has(category.key);
              return (
                <button
                  type="button"
                  key={category.key}
                  aria-pressed={pressed}
                  aria-label={`${pressed ? "Ocultar" : "Mostrar"} ${category.label}, ${category.count} ${
                    category.count === 1 ? "vínculo" : "vínculos"
                  }`}
                  title={
                    pressed
                      ? `Clic: quitar ${category.label}. Doble clic: solo esta familia.`
                      : `Clic: incluir ${category.label}. Doble clic: solo esta familia.`
                  }
                  onClick={() => {
                    setEnabledCategories((prev) => {
                      const base =
                        prev === null
                          ? new Set(allCategoryKeys(roleCategoryOptions))
                          : new Set(prev);
                      if (base.has(category.key)) {
                        // Don't allow emptying completely — fall back to this family alone.
                        if (base.size <= 1) return base;
                        base.delete(category.key);
                      } else {
                        base.add(category.key);
                      }
                      return base;
                    });
                  }}
                  onDoubleClick={(event) => {
                    event.preventDefault();
                    setEnabledCategories(new Set([category.key]));
                  }}
                >
                  <i className={GRAPH_ROLE_CATEGORY_META[category.key].className} />
                  <span>{category.label}</span>
                  <small>{category.count}</small>
                </button>
              );
            })}
          </div>
          {!allFamiliesEnabled && (
            <p className="entity-graph-v2-role-filter-note" role="status">
              Filtrando{" "}
              {roleCategoryOptions
                .filter((c) => effectiveCategories.has(c.key))
                .map((c) => c.label)
                .join(", ")}
              . El anillo y la expansión solo usan estas familias.
            </p>
          )}
        </section>
      )}

      <div className="entity-graph-v2-body">
        <div className="entity-graph-v2-stage">
          {viewMode === "radial" && (
            <svg
              ref={svgRef}
              className="entity-graph-v2-svg"
              viewBox={`0 0 ${VIEW_W} ${VIEW_H}`}
              role="img"
              aria-label={`Grafo radial de ${focusNode.label}`}
              onPointerDown={onPointerDown}
              onPointerMove={onPointerMove}
              onPointerUp={onPointerUp}
              onPointerLeave={onPointerUp}
              onWheel={onWheel}
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

              <g transform={worldTransform}>
                {[1, 2]
                  .filter((d) => d <= Math.max(maxDepth, visiblePlacements.some((p) => p.depth === 2) ? 2 : 1))
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

                {radialEdges.map(({ edge, d, strong }) => (
                  <path
                    key={edge.id}
                    d={d}
                    className={`entity-graph-v2-edge role-category-${GRAPH_ROLE_CATEGORY_META[edge.primaryCategory].className}${strong ? " is-strong" : ""}`}
                    fill="none"
                  />
                ))}

                {visiblePlacements.map((place) => {
                  const active =
                    place.node.id === selectedId || place.node.id === hoveredId;
                  const dimmed =
                    Boolean(selectedId || hoveredId) &&
                    place.node.id !== selectedId &&
                    place.node.id !== hoveredId &&
                    place.node.id !== activeFocusId;
                  const isExpanded = expandedIds.has(place.node.id);
                  const isCollapsed = collapsedIds.has(place.node.id);
                  const ring1Count = visiblePlacements.filter((p) => p.depth === 1).length;
                  const ring2Count = visiblePlacements.filter((p) => p.depth === 2).length;
                  // Show names around the full ring when density allows; always for
                  // selection, hover, expansion, or high-degree nodes.
                  const showLabel =
                    active ||
                    isExpanded ||
                    place.depth === 1 ||
                    (place.depth === 2 && (ring2Count <= 36 || place.node.degree >= 2));
                  const label = labelLayout(place.angle, place.radius);
                  const maxChars =
                    place.depth === 1
                      ? ring1Count > 40
                        ? 14
                        : 22
                      : ring2Count > 40
                        ? 12
                        : 16;
                  return (
                    <g
                      key={place.node.id}
                      className={`entity-graph-v2-node${active ? " is-active" : ""}${dimmed ? " is-dimmed" : ""}${isExpanded ? " is-expanded" : ""}`}
                      transform={`translate(${place.x} ${place.y})`}
                      onMouseEnter={() => setHoveredId(place.node.id)}
                      onMouseLeave={() =>
                        setHoveredId((id) => (id === place.node.id ? null : id))
                      }
                      onPointerDown={(e) => e.stopPropagation()}
                      onClick={(e) => {
                        e.stopPropagation();
                        setSelectedId(place.node.id);
                      }}
                      onDoubleClick={(e) => {
                        e.stopPropagation();
                        reRootTo(place.node.id);
                      }}
                      style={{ cursor: "pointer" }}
                    >
                      <circle
                        r={place.radius}
                        fill={nodeFill(place.node.kind, false)}
                        stroke={
                          active ? "#0f172a" : isExpanded ? "#0f8a76" : isCollapsed ? "#94a3b8" : "#ffffff"
                        }
                        strokeWidth={active || isExpanded ? 2.5 : 1.5}
                        filter="url(#egv2-shadow)"
                      />
                      {isExpanded && (
                        <circle
                          r={place.radius + 5}
                          fill="none"
                          stroke="#0f8a76"
                          strokeWidth={1}
                          strokeDasharray="2 2"
                        />
                      )}
                      {showLabel && (
                        <text
                          x={label.x}
                          y={label.y}
                          textAnchor={label.textAnchor}
                          dominantBaseline={label.dominantBaseline}
                          className={`entity-graph-v2-node-label${active ? " is-emphasis" : ""}`}
                        >
                          {truncateLabel(place.node.label, maxChars)}
                        </text>
                      )}
                      <title>
                        {place.node.label}
                        {"\n"}
                        {place.node.kind === "person" ? "Persona" : "Empresa"}
                        {" · "}
                        {place.node.degree} vínculos · salto {place.depth}
                        {"\n"}
                        Clic: seleccionar · Doble clic: centrar exploración
                      </title>
                    </g>
                  );
                })}

                <g
                  className="entity-graph-v2-center"
                  transform={`translate(${CX} ${CY})`}
                  onPointerDown={(e) => e.stopPropagation()}
                  onClick={(e) => {
                    e.stopPropagation();
                    setSelectedId(activeFocusId);
                  }}
                  style={{ cursor: "pointer" }}
                >
                  <circle r={CENTER_R + 10} fill="#0891b215" />
                  <circle
                    r={CENTER_R}
                    fill={nodeFill(focusNode.kind, true)}
                    stroke="#0f172a"
                    strokeWidth={3}
                    filter="url(#egv2-shadow)"
                  />
                  <text y={4} textAnchor="middle" className="entity-graph-v2-center-glyph">
                    {focusNode.kind === "person" ? "P" : "E"}
                  </text>
                  {/* Focus label always below the disc so it is never covered */}
                  <text
                    y={CENTER_R + 16}
                    textAnchor="middle"
                    dominantBaseline="hanging"
                    className="entity-graph-v2-center-label"
                  >
                    {truncateLabel(focusNode.label, 36)}
                  </text>
                </g>
              </g>

              <text x={16} y={VIEW_H - 14} className="entity-graph-v2-hint">
                Rueda: zoom · Arrastrar: pan · Alt+arrastrar: rotar · Doble clic nodo: centrar
                exploración · Clic: seleccionar
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
                        <div className="entity-graph-v2-row-actions">
                          <button
                            type="button"
                            className="vector-secondary compact"
                            onClick={(e) => {
                              e.stopPropagation();
                              reRootTo(node.id);
                              setViewMode("radial");
                            }}
                          >
                            Centrar
                          </button>
                          <button
                            type="button"
                            className="vector-secondary compact"
                            onClick={(e) => {
                              e.stopPropagation();
                              openEntity(node.routeName, node.kind);
                            }}
                          >
                            Ficha <ChevronRight size={13} />
                          </button>
                        </div>
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
                Matriz de adyacencia de los 12 vecinos de mayor grado del 1er salto más el foco
                actual.
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
          {!selectedNode || selectedNode.id === activeFocusId ? (
            <>
              <h3>
                <CircleDot size={16} /> Foco actual
              </h3>
              <p>{focusNode.label}</p>
              <dl>
                <div>
                  <dt>Tipo</dt>
                  <dd>{focusNode.kind === "person" ? "Persona" : "Empresa"}</dd>
                </div>
                <div>
                  <dt>Grado (filtro actual)</dt>
                  <dd>{filteredDegree.get(focusNode.id) ?? 0}</dd>
                </div>
                <div>
                  <dt>Vecinos 1er salto</dt>
                  <dd>
                    {model.nodes.filter((n) => (depths.get(n.id) ?? 99) === 1).length}
                  </dd>
                </div>
                <div>
                  <dt>Familias activas</dt>
                  <dd>
                    {allFamiliesEnabled
                      ? "Todas"
                      : roleCategoryOptions
                          .filter((c) => effectiveCategories.has(c.key))
                          .map((c) => c.label)
                          .join(", ") || "—"}
                  </dd>
                </div>
                <div>
                  <dt>Ramas expandidas</dt>
                  <dd>{expandedIds.size}</dd>
                </div>
              </dl>
              <p className="entity-graph-v2-side-hint">
                Selecciona un nodo para expandir su vecindario, colapsarlo, aislar su entorno o
                re-centrar la exploración sin salir de la ficha. Las familias de vínculo filtran
                también las expansiones.
              </p>
              <div className="entity-graph-v2-legend">
                <span>
                  <i style={{ background: "#0891b2" }} /> Foco
                </span>
                <span>
                  <i style={{ background: "#2563eb" }} /> Empresa
                </span>
                <span>
                  <i style={{ background: "#7c3aed" }} /> Persona
                </span>
                <span>
                  <i style={{ background: "#0f8a76", borderRadius: 2 }} /> Rama expandida
                </span>
              </div>
            </>
          ) : (
            <>
              <h3>
                {selectedNode.kind === "person" ? (
                  <UserRound size={16} />
                ) : (
                  <Building2 size={16} />
                )}
                {selectedNode.label}
              </h3>
              <dl>
                <div>
                  <dt>Tipo</dt>
                  <dd>{selectedNode.kind === "person" ? "Persona" : "Empresa"}</dd>
                </div>
                <div>
                  <dt>Salto desde el foco</dt>
                  <dd>{depths.get(selectedNode.id) ?? "—"}</dd>
                </div>
                <div>
                  <dt>Grado</dt>
                  <dd>{selectedNode.degree}</dd>
                </div>
                <div>
                  <dt>Vecinos en muestra</dt>
                  <dd>{selectedNeighborCount}</dd>
                </div>
                <div>
                  <dt>Roles con el foco</dt>
                  <dd>
                    {filteredEdges
                      .filter(
                        (e) =>
                          (e.source === activeFocusId && e.target === selectedNode.id) ||
                          (e.target === activeFocusId && e.source === selectedNode.id),
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
                  onClick={() => reRootTo(selectedNode.id)}
                >
                  <Focus size={14} /> Centrar exploración aquí
                </button>
                {!selectedIsExpanded ? (
                  <button
                    type="button"
                    className="vector-secondary"
                    onClick={expandSelected}
                    disabled={selectedExpandableCount === 0}
                    title={
                      selectedExpandableCount === 0
                        ? "No hay vecinos ocultos en esta rama"
                        : `Mostrar ${selectedExpandableCount} vecinos de esta rama`
                    }
                  >
                    <GitBranchPlus size={14} /> Expandir vecinos ({selectedExpandableCount})
                  </button>
                ) : (
                  <button type="button" className="vector-secondary" onClick={collapseSelected}>
                    <Shrink size={14} /> Colapsar rama
                  </button>
                )}
                {isolatedId === selectedNode.id ? (
                  <button type="button" className="vector-secondary" onClick={clearIsolation}>
                    <Expand size={14} /> Quitar aislamiento
                  </button>
                ) : (
                  <button type="button" className="vector-secondary" onClick={isolateSelected}>
                    <Minimize2 size={14} /> Aislar entorno directo
                  </button>
                )}
                <button
                  type="button"
                  className="vector-secondary"
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
