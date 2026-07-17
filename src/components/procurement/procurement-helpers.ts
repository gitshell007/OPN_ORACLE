import { ApiError } from "@oracle/api-client";

export function problemMessage(reason: unknown, fallback: string): string {
  if (reason instanceof ApiError) {
    if (reason.status === 503)
      return "La integración de contratación pública no está disponible ahora. Reinténtalo en unos minutos o contacta con soporte si persiste.";
    return reason.problem.detail || fallback;
  }
  return fallback;
}

export function parseCsv(value: string): string[] {
  return value
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
}

export function formatDate(value?: string | null): string {
  if (!value) return "Sin fecha";
  if (value.includes("/")) {
    const [start, end] = value.split("/", 2);
    if (start && end && start.length >= 10 && end.length >= 10) {
      return `${formatDate(start)} - ${formatDate(end)}`;
    }
  }
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return parsed.toLocaleDateString("es-ES");
}

export function formatMoney(value?: number | null): string {
  if (value === undefined || value === null || Number.isNaN(value))
    return "Importe no publicado";
  return new Intl.NumberFormat("es-ES", {
    style: "currency",
    currency: "EUR",
    maximumFractionDigits: 0,
  }).format(value);
}

export function cpvLabel(cpv?: string[]): string {
  return cpv?.length ? cpv.slice(0, 3).join(", ") : "CPV no publicado";
}

export function snapshotText(
  snapshot: Record<string, unknown>,
  keys: string[],
): string | null {
  for (const key of keys) {
    const value = snapshot[key];
    if (typeof value === "string" && value.trim()) return value;
  }
  return null;
}

export function snapshotNumber(
  snapshot: Record<string, unknown>,
  keys: string[],
): number | null {
  for (const key of keys) {
    const value = snapshot[key];
    if (typeof value === "number" && Number.isFinite(value)) return value;
    if (typeof value === "string" && value.trim()) {
      let normalized = value.trim();
      if (normalized.includes(",")) {
        normalized = normalized.replace(/\./g, "").replace(",", ".");
      } else if (/^\d{1,3}(?:\.\d{3})+$/.test(normalized)) {
        normalized = normalized.replace(/\./g, "");
      }
      const parsed = Number(normalized.replace(/[^\d.-]/g, ""));
      if (Number.isFinite(parsed)) return parsed;
    }
  }
  return null;
}
