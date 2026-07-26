/**
 * Shared graph role-family helpers for Grafo v1/v2.
 * Categories mirror the backend contract in entity_intel._GRAPH_ROLE_ALIASES.
 */

import type { EntityIntelGraphEdge, EntityIntelGraphResponse } from "@oracle/api-client";

export type GraphRoleCategory =
  | "governance"
  | "representation"
  | "audit"
  | "ownership"
  | "liquidation"
  | "other";

export interface GraphRoleCategoryOption {
  key: GraphRoleCategory;
  label: string;
  count: number;
  roleKeys: string[];
}

export const GRAPH_ROLE_CATEGORY_ORDER: GraphRoleCategory[] = [
  "governance",
  "representation",
  "audit",
  "ownership",
  "liquidation",
  "other",
];

export const GRAPH_ROLE_CATEGORY_META: Record<
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

/** Structural alias key → category (subset aligned with backend). */
const ROLE_ALIAS_CATEGORY: Record<string, GraphRoleCategory> = {
  adm_unico: "governance",
  administrador_unico: "governance",
  adm_solid: "governance",
  administrador_solidario: "governance",
  adm_mancom: "governance",
  administrador_mancomunado: "governance",
  administrador: "governance",
  consejero: "governance",
  consejero_delegado: "governance",
  presidente: "governance",
  vicepresidente: "governance",
  secretario: "governance",
  vicesecretario: "governance",
  apoderado: "representation",
  apoderada: "representation",
  auditor: "audit",
  socio_unico: "ownership",
  socio: "ownership",
  liquidador: "liquidation",
};

function aliasKey(value: string): string {
  return value
    .normalize("NFKD")
    .replace(/\p{M}/gu, "")
    .toLocaleLowerCase("es-ES")
    .replace(/[\W_]+/g, " ")
    .trim()
    .replace(/\s+/g, "_");
}

function roleLabels(edge: EntityIntelGraphEdge): string[] {
  const values: string[] = [];
  if (typeof edge.role === "string" && edge.role.trim()) values.push(edge.role.trim());
  if (Array.isArray(edge.roles)) {
    for (const role of edge.roles) {
      if (typeof role === "string" && role.trim()) values.push(role.trim());
    }
  } else if (typeof edge.roles === "string" && edge.roles.trim()) {
    values.push(edge.roles.trim());
  }
  if (Array.isArray(edge.source_roles)) {
    for (const role of edge.source_roles) {
      if (typeof role === "string" && role.trim()) values.push(role.trim());
    }
  }
  return [...new Set(values)];
}

function fallbackCategory(label: string): GraphRoleCategory {
  const key = aliasKey(label);
  return ROLE_ALIAS_CATEGORY[key] ?? "other";
}

function fallbackRoleKey(label: string): string {
  const key = aliasKey(label);
  return key || "relacion";
}

/** Categories for an edge (provider contract first, alias fallback otherwise). */
export function edgeRoleCategories(edge: EntityIntelGraphEdge): GraphRoleCategory[] {
  const fromContract = Array.isArray(edge.role_categories)
    ? edge.role_categories.filter((c): c is GraphRoleCategory => GRAPH_ROLE_CATEGORY_SET.has(c))
    : [];
  if (fromContract.length > 0) return [...new Set(fromContract)];

  const labels = roleLabels(edge);
  if (labels.length === 0) return ["other"];
  return [...new Set(labels.map(fallbackCategory))];
}

export function edgeRoleKeys(edge: EntityIntelGraphEdge): string[] {
  const fromContract = Array.isArray(edge.role_keys)
    ? edge.role_keys.filter((k): k is string => typeof k === "string" && k.trim().length > 0)
    : [];
  if (fromContract.length > 0) return [...new Set(fromContract)];
  const labels = roleLabels(edge);
  if (labels.length === 0) return ["relacion"];
  return [...new Set(labels.map(fallbackRoleKey))];
}

export function primaryRoleCategory(edge: EntityIntelGraphEdge): GraphRoleCategory {
  return edgeRoleCategories(edge)[0] ?? "other";
}

export function edgeMatchesRoleCategories(
  edge: EntityIntelGraphEdge,
  enabled: ReadonlySet<GraphRoleCategory>,
): boolean {
  if (enabled.size === 0) return false;
  const cats = edgeRoleCategories(edge);
  return cats.some((c) => enabled.has(c));
}

export function graphRoleCategoryOptions(
  graph: EntityIntelGraphResponse | null | undefined,
): GraphRoleCategoryOption[] {
  if (!graph) return [];
  const categories = new Map<GraphRoleCategory, { count: number; roleKeys: Set<string> }>();

  for (const edge of graph.edges) {
    const cats = edgeRoleCategories(edge);
    const keys = edgeRoleKeys(edge);
    const uniqueCats = new Set(cats);
    for (const category of uniqueCats) {
      const current = categories.get(category) ?? { count: 0, roleKeys: new Set<string>() };
      current.count += 1;
      for (const key of keys) current.roleKeys.add(key);
      categories.set(category, current);
    }
  }

  return GRAPH_ROLE_CATEGORY_ORDER.flatMap((category) => {
    const current = categories.get(category);
    if (!current) return [];
    return [
      {
        key: category,
        label: GRAPH_ROLE_CATEGORY_META[category].label,
        count: current.count,
        roleKeys: [...current.roleKeys],
      },
    ];
  });
}

export function allCategoryKeys(
  options: GraphRoleCategoryOption[],
): GraphRoleCategory[] {
  return options.map((o) => o.key);
}
