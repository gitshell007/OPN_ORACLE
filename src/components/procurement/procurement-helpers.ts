import { ApiError } from "@oracle/api-client";

export function problemMessage(reason: unknown, fallback: string): string {
  if (reason instanceof ApiError) {
    if (reason.status === 503)
      return "La integración de contratación pública no está disponible ahora. Reinténtalo en unos minutos o contacta con soporte si persiste.";
    if (reason.status === 502 || reason.status === 504)
      return "El registro de contratación no respondió a tiempo. Reinténtalo; si se repite, el proveedor puede estar saturado.";
    if (reason.status >= 500) {
      const detail = (reason.problem.detail || "").trim();
      // Flask default HTML/text 500 bodies are not actionable; use a stable message.
      if (
        !detail ||
        /internal server error/i.test(detail) ||
        /server encountered an internal error/i.test(detail) ||
        /<!doctype html/i.test(detail)
      ) {
        return "Error interno al consultar adjudicaciones. Reinténtalo; si persiste, avisa a soporte con la hora y la página.";
      }
    }
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
