import type { EntityIntelKind, EntityIntelRegistryAct } from "@oracle/api-client";

export interface RegistryStatus {
  action: string;
  item: EntityIntelRegistryAct;
}

function normalized(value: unknown): string {
  return String(value ?? "").trim().toLocaleLowerCase("es-ES");
}

export function registryCounterpartLabel(
  kind: EntityIntelKind,
  item: EntityIntelRegistryAct,
): string {
  return String(kind === "company" ? item.person ?? "" : item.company ?? "").trim()
    || "Sin contraparte";
}

export function registryStatusKey(kind: EntityIntelKind, item: EntityIntelRegistryAct): string {
  return [
    normalized(registryCounterpartLabel(kind, item)),
    normalized(item.role),
  ].join("::");
}

export function registryActDedupeKey(kind: EntityIntelKind, item: EntityIntelRegistryAct): string {
  return [
    normalized(registryCounterpartLabel(kind, item)),
    normalized(item.source_url),
    normalized(item.date),
    normalized(item.role),
  ].join("::");
}

function dateRank(value: unknown): number | null {
  if (typeof value !== "string" || !value.trim()) return null;
  const time = new Date(value).getTime();
  return Number.isNaN(time) ? null : time;
}

function stableFallbackRank(kind: EntityIntelKind, item: EntityIntelRegistryAct): string {
  return [
    normalized(item.action),
    normalized(item.source_url),
    normalized(item.details),
    normalized(item.province),
    registryStatusKey(kind, item),
  ].join("::");
}

function isNewerOrStableTie(
  kind: EntityIntelKind,
  candidate: EntityIntelRegistryAct,
  current: EntityIntelRegistryAct,
): boolean {
  const candidateDate = dateRank(candidate.date);
  const currentDate = dateRank(current.date);
  if (candidateDate !== null && currentDate !== null && candidateDate !== currentDate) {
    return candidateDate > currentDate;
  }
  if (candidateDate !== null && currentDate === null) return true;
  if (candidateDate === null && currentDate !== null) return false;
  return stableFallbackRank(kind, candidate) > stableFallbackRank(kind, current);
}

export function latestRegistryStatuses(
  items: EntityIntelRegistryAct[],
  kind: EntityIntelKind,
): Map<string, RegistryStatus> {
  const latest = new Map<string, RegistryStatus>();
  for (const item of items) {
    const key = registryStatusKey(kind, item);
    if (!key.replaceAll("::", "").trim()) continue;
    const current = latest.get(key);
    if (!current || isNewerOrStableTie(kind, item, current.item)) {
      latest.set(key, {
        action: String(item.action ?? ""),
        item,
      });
    }
  }
  return latest;
}

export function registryStatusCounts(
  items: EntityIntelRegistryAct[],
  kind: EntityIntelKind,
): { active: number; ended: number } {
  const latest = latestRegistryStatuses(items, kind);
  let active = 0;
  let ended = 0;
  for (const status of latest.values()) {
    if (normalized(status.action) === "cese") ended += 1;
    else active += 1;
  }
  return { active, ended };
}
