/**
 * Identidad del despliegue en ejecución (fuente: GET /api/v1/meta).
 *
 * En deploy nativo el `release` es `{YYYYMMDDTHHMMSSZ}-native-{sha7}`
 * (ver infra/native-dev/build-release.sh). En local suele ser `development`.
 */

export type RuntimeMeta = {
  name: string;
  version: string;
  release: string;
  environment: string;
  capabilities: string[];
};

export type RuntimeBuildLabel = {
  /** Fecha/hora del build embebida en el release id, o null si no aplica. */
  builtAt: Date | null;
  /** SHA corto del commit cuando el release lo incluye. */
  shortSha: string | null;
  /** Texto principal legible (fecha o etiqueta de entorno). */
  primary: string;
  /** Texto secundario (SHA · environment / release crudo). */
  secondary: string;
  /** release crudo del meta. */
  release: string;
  environment: string;
};

const NATIVE_RELEASE =
  /^(\d{8}T\d{6}Z)-native-([0-9a-f]{4,40})$/i;

function parseNativeBuiltAt(stamp: string): Date | null {
  // 20260807T143022Z → 2026-08-07T14:30:22Z
  const m = stamp.match(
    /^(\d{4})(\d{2})(\d{2})T(\d{2})(\d{2})(\d{2})Z$/,
  );
  if (!m) return null;
  const iso = `${m[1]}-${m[2]}-${m[3]}T${m[4]}:${m[5]}:${m[6]}Z`;
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? null : date;
}

export function formatBuiltAt(date: Date): string {
  // Español de España, fijo a UTC para que coincida con el stamp del release.
  const datePart = new Intl.DateTimeFormat("es-ES", {
    timeZone: "UTC",
    day: "numeric",
    month: "short",
    year: "numeric",
  }).format(date);
  const timePart = new Intl.DateTimeFormat("es-ES", {
    timeZone: "UTC",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(date);
  return `${datePart}, ${timePart} UTC`;
}

export function buildRuntimeLabel(
  meta: Pick<RuntimeMeta, "release" | "environment" | "version">,
): RuntimeBuildLabel {
  const release = (meta.release || "").trim() || "development";
  const environment = (meta.environment || "").trim() || "unknown";
  const native = release.match(NATIVE_RELEASE);

  if (native) {
    const builtAt = parseNativeBuiltAt(native[1]);
    const shortSha = native[2].toLowerCase();
    return {
      builtAt,
      shortSha,
      primary: builtAt
        ? formatBuiltAt(builtAt)
        : `Release ${release}`,
      secondary: `${shortSha} · ${environment}`,
      release,
      environment,
    };
  }

  if (release === "development" || environment === "development") {
    return {
      builtAt: null,
      shortSha: null,
      primary: "Entorno de desarrollo",
      secondary: `v${meta.version} · ${environment}`,
      release,
      environment,
    };
  }

  return {
    builtAt: null,
    shortSha: null,
    primary: release,
    secondary: `v${meta.version} · ${environment}`,
    release,
    environment,
  };
}

export async function fetchRuntimeMeta(
  signal?: AbortSignal,
): Promise<RuntimeMeta | null> {
  try {
    const response = await fetch("/api/v1/meta", {
      credentials: "include",
      cache: "no-store",
      signal,
      headers: { Accept: "application/json" },
    });
    if (!response.ok) return null;
    const body = (await response.json()) as Partial<RuntimeMeta>;
    if (
      typeof body.release !== "string" ||
      typeof body.environment !== "string" ||
      typeof body.version !== "string"
    ) {
      return null;
    }
    return {
      name: typeof body.name === "string" ? body.name : "OPN Oracle",
      version: body.version,
      release: body.release,
      environment: body.environment,
      capabilities: Array.isArray(body.capabilities)
        ? body.capabilities.filter((c): c is string => typeof c === "string")
        : [],
    };
  } catch {
    return null;
  }
}
