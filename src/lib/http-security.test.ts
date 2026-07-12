import { describe, expect, it } from "vitest";
import {
  BASELINE_SECURITY_HEADERS,
  PRODUCTION_CSP_REPORT_ONLY,
  SENSITIVE_CACHE_HEADERS,
} from "./http-security";

function headersByName(headers: { key: string; value: string }[]) {
  return new Map(headers.map(({ key, value }) => [key.toLowerCase(), value]));
}

describe("cabeceras HTTP del frontend", () => {
  it("bloquea framing, sniffing y capacidades no utilizadas", () => {
    const headers = headersByName(BASELINE_SECURITY_HEADERS);

    expect(headers.get("x-frame-options")).toBe("DENY");
    expect(headers.get("x-content-type-options")).toBe("nosniff");
    expect(headers.get("referrer-policy")).toBe("strict-origin-when-cross-origin");
    expect(headers.get("permissions-policy")).toContain("camera=()");
  });

  it("impide cachear rutas autenticadas o de credenciales", () => {
    const headers = headersByName(SENSITIVE_CACHE_HEADERS);

    expect(headers.get("cache-control")).toContain("no-store");
    expect(headers.get("cache-control")).toContain("private");
    expect(headers.get("pragma")).toBe("no-cache");
  });

  it("mantiene CSP sin unsafe-eval y con framing denegado", () => {
    expect(PRODUCTION_CSP_REPORT_ONLY).toContain("frame-ancestors 'none'");
    expect(PRODUCTION_CSP_REPORT_ONLY).toContain("object-src 'none'");
    expect(PRODUCTION_CSP_REPORT_ONLY).not.toContain("unsafe-eval");
  });
});

