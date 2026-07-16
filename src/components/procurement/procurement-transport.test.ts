import { afterEach, describe, expect, it, vi } from "vitest";

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.resetModules();
});

describe("transporte de contratación pública", () => {
  it("serializa filtros de licitaciones sin claves libres", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      json({
        cache_hit: false,
        cached_seconds: 0,
        filters: {},
        items: [],
        limit: 25,
        offset: 0,
        total: 0,
      }),
    );
    vi.stubGlobal("fetch", fetchMock);
    const { api } = await import("@oracle/api-client");

    await api.procurement.tenders({
      keywords: "baterías, movilidad",
      cpv: "31400000",
      min_amount: 1000,
      max_amount: 9000,
      deadline_before: "2026-08-01",
      buyer: "Gobierno de Aragón",
      region: "Aragón",
      active: true,
      limit: 50,
      offset: 25,
    });

    const [url, options] = fetchMock.mock.calls[0] as [string, RequestInit];
    const parsed = new URL(url, "https://oracle.example.test");
    expect(parsed.pathname).toBe("/api/v1/procurement/tenders");
    expect(Object.fromEntries(parsed.searchParams)).toEqual({
      limit: "50",
      offset: "25",
      keywords: "baterías, movilidad",
      cpv: "31400000",
      min_amount: "1000",
      max_amount: "9000",
      deadline_before: "2026-08-01",
      buyer: "Gobierno de Aragón",
      region: "Aragón",
      active: "true",
    });
    expect(options.credentials).toBe("include");
  });

  it("codifica folder_id con barras al pedir resumen y mantiene el body de pin intacto", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(json({ csrf_token: "csrf-test" }))
      .mockResolvedValueOnce(json({ cached: true, item: { folder_id: "2026/123/ABC" } }))
      .mockResolvedValueOnce(json({ id: "pin-1", folder_id: "2026/123/ABC" }));
    vi.stubGlobal("fetch", fetchMock);
    const { api } = await import("@oracle/api-client");

    await api.procurement.summarizeTender("2026/123/ABC");
    await api.dossierProcurement.pin("dossier/seguro", {
      kind: "tender",
      folder_id: "2026/123/ABC",
    });

    expect(fetchMock.mock.calls[1][0]).toBe(
      "/api/v1/procurement/tenders/2026%2F123%2FABC/summary",
    );
    const [pinUrl, pinOptions] = fetchMock.mock.calls[2] as [string, RequestInit];
    expect(pinUrl).toBe("/api/v1/dossiers/dossier%2Fseguro/procurement");
    expect(JSON.parse(String(pinOptions.body))).toEqual({
      kind: "tender",
      folder_id: "2026/123/ABC",
    });
  });
});
