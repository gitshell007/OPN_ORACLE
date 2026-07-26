/** Canonical entity dossier URLs and legacy path decoding. */

export type EntityRouteKind = "company" | "person";

export type EntityRouteExtras = {
  tab?: string;
  tool?: string;
};

/**
 * Canonical route puts the entity name in the query string so spaces and
 * punctuation never enter a path segment (Next.js router-state headers break
 * on unencoded spaces, which some browsers emit after decoding %20).
 */
export function entityRoute(
  kind: EntityRouteKind,
  name: string,
  extras: EntityRouteExtras = {},
): string {
  const query = new URLSearchParams();
  query.set("name", name.trim());
  if (extras.tab) query.set("tab", extras.tab);
  if (extras.tool) query.set("tool", extras.tool);
  return `/app/actors/entity/${kind}?${query.toString()}`;
}

/** Decode a legacy path segment (or catch-all parts) into a display name. */
export function decodeEntityPathName(raw: string | string[]): string {
  const parts = Array.isArray(raw) ? raw : [raw];
  const joined = parts
    .map((part) => {
      const value = part.trim();
      if (!value) return "";
      try {
        // Path may arrive still percent-encoded or with '+' as space substitute.
        return decodeURIComponent(value.replace(/\+/g, "%20"));
      } catch {
        return value.replace(/\+/g, " ");
      }
    })
    .filter(Boolean)
    // If a proxy decoded "%20" and a middle layer split on spaces, re-join.
    .join(" ")
    .replace(/\s+/g, " ")
    .trim();
  return joined;
}
