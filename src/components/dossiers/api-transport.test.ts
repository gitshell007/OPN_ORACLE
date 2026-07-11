import { afterEach, describe, expect, it, vi } from "vitest";

function json(body: unknown) {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.resetModules();
});

describe("transporte tipado de expedientes", () => {
  it("serializa únicamente la query allowlisted del listado Flask", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      json({ data: [], meta: { page: 2, size: 10, total: 0 } }),
    );
    vi.stubGlobal("fetch", fetchMock);
    const { api } = await import("@oracle/api-client");

    await api.dossiers.list({
      page: 2,
      size: 10,
      sort: "-risk_score",
      search: "  Delta norte  ",
      status: "active",
      type: "project",
      owner: "11111111-1111-4111-8111-111111111111",
      selectedIds: [
        "22222222-2222-4222-8222-222222222222",
        "33333333-3333-4333-8333-333333333333",
      ],
    });

    const [url, options] = fetchMock.mock.calls[0] as [string, RequestInit];
    const parsed = new URL(url, "https://oracle.example.test");
    expect(Object.fromEntries(parsed.searchParams)).toEqual({
      "page[number]": "2",
      "page[size]": "10",
      sort: "-risk_score",
      "filter[status]": "active",
      "filter[type]": "project",
      "filter[owner]": "11111111-1111-4111-8111-111111111111",
      "filter[search]": "Delta norte",
      "filter[selected_ids]":
        "22222222-2222-4222-8222-222222222222,33333333-3333-4333-8333-333333333333",
    });
    expect(options.credentials).toBe("include");
    expect(options.cache).toBe("no-store");
  });

  it("conserva los defaults deterministas para consumidores existentes", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      json({ data: [], meta: { page: 1, size: 25, total: 0 } }),
    );
    vi.stubGlobal("fetch", fetchMock);
    const { api } = await import("@oracle/api-client");

    await api.dossiers.list();

    expect(fetchMock.mock.calls[0][0]).toBe(
      "/api/v1/dossiers?page%5Bnumber%5D=1&page%5Bsize%5D=25&sort=-updated_at",
    );
  });

  it("serializa filtros server-side de señales sin incorporar claves libres", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      json({ data: [], meta: { page: 3, size: 25, total: 0 } }),
    );
    vi.stubGlobal("fetch", fetchMock);
    const { api } = await import("@oracle/api-client");

    await api.dossierSignals.list("dossier/seguro", {
      page: 3,
      status: "reviewed",
      search: "  fuente oficial ",
      scoreMin: 70,
      scoreMax: 95,
    });

    const [url] = fetchMock.mock.calls[0] as [string];
    const parsed = new URL(url, "https://oracle.example.test");
    expect(parsed.pathname).toBe(
      "/api/v1/dossiers/dossier%2Fseguro/signals",
    );
    expect(Object.fromEntries(parsed.searchParams)).toEqual({
      "page[number]": "3",
      "page[size]": "25",
      sort: "-updated_at",
      "filter[status]": "reviewed",
      "filter[search]": "fuente oficial",
      "filter[score_min]": "70",
      "filter[score_max]": "95",
    });
  });

  it("envía concurrencia optimista al actualizar una oportunidad", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(json({ csrf_token: "csrf-test" }))
      .mockResolvedValueOnce(json({ id: "op-1", version: 5 }));
    vi.stubGlobal("fetch", fetchMock);
    const { api } = await import("@oracle/api-client");

    await api.opportunities.update(
      "op-1",
      { status: "qualified", version: 4 },
      4,
    );

    const [url, options] = fetchMock.mock.calls[1] as [string, RequestInit];
    expect(url).toBe("/api/v1/opportunities/op-1");
    expect(options.method).toBe("PATCH");
    const headers = options.headers as Headers;
    expect(headers.get("If-Match")).toBe('W/"4"');
    expect(headers.get("X-CSRF-Token")).toBe("csrf-test");
    expect(JSON.parse(String(options.body))).toEqual({
      status: "qualified",
      version: 4,
    });
  });

  it("incluye la clave idempotente al promover una señal", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(json({ csrf_token: "csrf-test" }))
      .mockResolvedValueOnce(
        json({ kind: "risk", resource: { id: "risk-1" } }),
      );
    vi.stubGlobal("fetch", fetchMock);
    const { api } = await import("@oracle/api-client");

    await api.dossierSignals.promote(
      "link-1",
      { kind: "risk", title: "Riesgo de plazo" },
      "promotion-key",
    );

    const [, options] = fetchMock.mock.calls[1] as [string, RequestInit];
    expect((options.headers as Headers).get("Idempotency-Key")).toBe(
      "promotion-key",
    );
  });

  it("serializa los filtros de inventario global sin fan-out por expediente", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      json({ data: [], included: { dossiers: [] }, meta: { page: 2, size: 25, total: 0 } }),
    );
    vi.stubGlobal("fetch", fetchMock);
    const { api } = await import("@oracle/api-client");

    await api.opportunities.listGlobal({
      page: 2,
      status: "qualified",
      search: "  expansión norte ",
      scoreMin: 65,
      dossierId: "11111111-1111-4111-8111-111111111111",
    });

    const [url] = fetchMock.mock.calls[0] as [string];
    const parsed = new URL(url, "https://oracle.example.test");
    expect(parsed.pathname).toBe("/api/v1/opportunities");
    expect(Object.fromEntries(parsed.searchParams)).toEqual({
      "page[number]": "2",
      "page[size]": "25",
      sort: "-updated_at",
      "filter[status]": "qualified",
      "filter[search]": "expansión norte",
      "filter[score_min]": "65",
      "filter[dossier_id]": "11111111-1111-4111-8111-111111111111",
    });
  });

  it("codifica la búsqueda global y propaga la cancelación", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      json({ query: "delta", limit_per_group: 5, groups: {}, items: [] }),
    );
    vi.stubGlobal("fetch", fetchMock);
    const { api } = await import("@oracle/api-client");
    const controller = new AbortController();

    await api.search.query(" delta ", {
      limit: 4,
      types: ["dossiers", "documents"],
      signal: controller.signal,
    });

    const [url, options] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/api/v1/search?q=delta&limit=4&types=dossiers%2Cdocuments");
    expect(options.signal).toBe(controller.signal);
  });
});
