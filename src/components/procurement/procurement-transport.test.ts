import { afterEach, describe, expect, it, vi } from "vitest";
import type { TenderSearchPlan } from "@oracle/api-client";

function json(
  body: unknown,
  status = 200,
  headers: Record<string, string> = {},
) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json", ...headers },
  });
}

function searchPlan(): TenderSearchPlan {
  return {
    assumptions: ["La protección personal incluye vestuario técnico."],
    buyers: ["Ayuntamiento de Cádiz"],
    candidate_cpv: [
      { code: "35110000", label: "Equipo de extinción de incendios" },
    ],
    confidence: 0.87,
    discarded_count: 0,
    discarded_reasons: {},
    exclude_terms: ["juguete"],
    geographies: ["Andalucía"],
    include_terms: ["equipos de protección"],
    intent_summary: "Equipamiento de protección y emergencias.",
    max_amount: 500_000,
    min_amount: 10_000,
    questions: [],
    scope: "active",
    synonyms: ["EPI"],
  };
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
      scope: "all",
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
      scope: "all",
    });
    expect(options.credentials).toBe("include");
  });

  it("codifica folder_id con barras al pedir resumen y mantiene el body de pin intacto", async () => {
    const folderId = "OBR/CNT/2026000031";
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(json({ csrf_token: "csrf-test" }))
      .mockResolvedValueOnce(
        json({ cached: true, item: { folder_id: folderId } }),
      )
      .mockResolvedValueOnce(json({ id: "pin-1", folder_id: folderId }));
    vi.stubGlobal("fetch", fetchMock);
    const { api } = await import("@oracle/api-client");

    await api.procurement.summarizeTender(folderId);
    await api.dossierProcurement.pin("dossier/seguro", {
      kind: "tender",
      folder_id: folderId,
    });

    expect(fetchMock.mock.calls[1][0]).toBe(
      "/api/v1/procurement/tenders/OBR%2FCNT%2F2026000031/summary",
    );
    const [pinUrl, pinOptions] = fetchMock.mock.calls[2] as [
      string,
      RequestInit,
    ];
    expect(pinUrl).toBe("/api/v1/dossiers/dossier%2Fseguro/procurement");
    expect(JSON.parse(String(pinOptions.body))).toEqual({
      kind: "tender",
      folder_id: folderId,
    });
  });

  it("serializa sugerencias registrales de procurement", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      json({
        kind: "winner",
        suggestions: ["ITURRI, S.A."],
        cached_seconds: 300,
        cache_hit: false,
      }),
    );
    vi.stubGlobal("fetch", fetchMock);
    const { api } = await import("@oracle/api-client");

    await api.procurement.suggest({ q: " Iturri ", kind: "winner", limit: 8 });

    const [url] = fetchMock.mock.calls[0] as [string];
    const parsed = new URL(url, "https://oracle.example.test");
    expect(parsed.pathname).toBe("/api/v1/procurement/suggest");
    expect(Object.fromEntries(parsed.searchParams)).toEqual({
      q: "Iturri",
      kind: "winner",
      limit: "8",
    });
  });

  it("consulta la taxonomía CPV local con límite fijo y sin reintentos opacos", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      json({
        query: "ropa de protección",
        items: [{ code: "35113400", label: "Ropa de protección" }],
        limit: 8,
        cached_seconds: 0,
      }),
    );
    vi.stubGlobal("fetch", fetchMock);
    const { api } = await import("@oracle/api-client");

    await api.procurement.suggestCpvs("  ropa de protección  ");

    const [url, options] = fetchMock.mock.calls[0] as [string, RequestInit];
    const parsed = new URL(url, "https://oracle.example.test");
    expect(parsed.pathname).toBe("/api/v1/procurement/cpv/suggest");
    expect(Object.fromEntries(parsed.searchParams)).toEqual({
      q: "ropa de protección",
      limit: "8",
    });
    expect(options.method).toBe("GET");
    expect(options.credentials).toBe("include");
  });

  it("envía Idempotency-Key al generar el informe documental", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(json({ csrf_token: "csrf-test" }))
      .mockResolvedValueOnce(
        json(
          { job_id: "job-1", replayed: false, report: { id: "report-1" } },
          202,
        ),
      );
    vi.stubGlobal("fetch", fetchMock);
    const { api } = await import("@oracle/api-client");

    await api.dossierProcurement.createDocumentReport(
      "dossier-1",
      {},
      "procurement-report-dossier-1-test",
    );

    const [url, options] = fetchMock.mock.calls[1] as [string, RequestInit];
    expect(url).toBe("/api/v1/dossiers/dossier-1/procurement/reports");
    expect(options.method).toBe("POST");
    expect((options.headers as Headers).get("Idempotency-Key")).toBe(
      "procurement-report-dossier-1-test",
    );
  });

  it("codifica la comparable, recorta el nombre y mantiene la sesión", async () => {
    const fetchMock = vi.fn().mockResolvedValue(json({}));
    vi.stubGlobal("fetch", fetchMock);
    const { api } = await import("@oracle/api-client");

    await api.procurement.comparableProfile("  ITURRI / Emergencias  ");

    const [url, options] = fetchMock.mock.calls[0] as [string, RequestInit];
    const parsed = new URL(url, "https://oracle.example.test");
    expect(parsed.pathname).toBe("/api/v1/procurement/comparable-profile");
    expect(Object.fromEntries(parsed.searchParams)).toEqual({
      company: "ITURRI / Emergencias",
    });
    expect(options.method).toBe("GET");
    expect(options.credentials).toBe("include");
  });

  it("envuelve el plan de preview y envía CSRF con la cookie de sesión", async () => {
    const plan = { ...searchPlan(), max_amount: null, min_amount: null };
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(json({ csrf_token: "csrf-preview" }))
      .mockResolvedValueOnce(json({ plan, preview: {} }));
    vi.stubGlobal("fetch", fetchMock);
    const { api } = await import("@oracle/api-client");

    await api.procurement.previewSearchPlan(plan);

    expect(fetchMock.mock.calls[0][0]).toBe("/api/v1/auth/csrf");
    const [url, options] = fetchMock.mock.calls[1] as [string, RequestInit];
    expect(url).toBe("/api/v1/procurement/search-plans/preview");
    expect(options.method).toBe("POST");
    expect(options.credentials).toBe("include");
    expect(new Headers(options.headers).get("X-CSRF-Token")).toBe(
      "csrf-preview",
    );
    expect(JSON.parse(String(options.body))).toEqual({ plan });
  });

  it("lee el último wizard y crea una ejecución idempotente", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(json({ artifact: null, input: null, job: null }))
      .mockResolvedValueOnce(json({ csrf_token: "csrf-wizard" }))
      .mockResolvedValueOnce(json({ job: { id: "job-1" } }, 202));
    vi.stubGlobal("fetch", fetchMock);
    const { api } = await import("@oracle/api-client");

    await api.tenderSearchWizard.latest();
    await api.tenderSearchWizard.run(
      {
        comparable: "ITURRI",
        description: "Busco equipos de protección para emergencias",
      },
      "wizard-iturri-2026-07-23",
    );

    const [latestUrl, latestOptions] = fetchMock.mock.calls[0] as [
      string,
      RequestInit,
    ];
    expect(latestUrl).toBe("/api/v1/ai/tender-search-wizard/latest");
    expect(latestOptions.method).toBe("GET");
    expect(latestOptions.credentials).toBe("include");

    const [runUrl, runOptions] = fetchMock.mock.calls[2] as [
      string,
      RequestInit,
    ];
    expect(runUrl).toBe("/api/v1/ai/tender-search-wizard/runs");
    expect(runOptions.method).toBe("POST");
    expect(runOptions.credentials).toBe("include");
    expect(new Headers(runOptions.headers).get("X-CSRF-Token")).toBe(
      "csrf-wizard",
    );
    expect(new Headers(runOptions.headers).get("Idempotency-Key")).toBe(
      "wizard-iturri-2026-07-23",
    );
    expect(JSON.parse(String(runOptions.body))).toEqual({
      comparable: "ITURRI",
      description: "Busco equipos de protección para emergencias",
    });
  });

  it("transporta el ciclo explícito y versionado del perfil de búsqueda", async () => {
    const plan = { ...searchPlan(), max_amount: null, min_amount: null };
    const createBody = {
      accepted_plan: plan,
      ai_artifact_id: "artifact-1",
      comparables: ["ITURRI"],
      original_description: "Equipos de protección para emergencias",
    };
    const acceptBody = {
      accepted_plan: { ...plan, include_terms: ["equipos de extinción"] },
      ai_artifact_id: "artifact-2",
      expected_version: 3,
    };
    const saveBody = { expected_version: 4, name: "Emergencias activas" };
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(json({ items: [] }))
      .mockResolvedValueOnce(json({ id: "perfil/andalucía" }))
      .mockResolvedValueOnce(json({ csrf_token: "csrf-profile" }))
      .mockResolvedValueOnce(json({ id: "profile-1", version: 3 }))
      .mockResolvedValueOnce(json({ id: "profile-1", version: 4 }))
      .mockResolvedValueOnce(json({ profile: {}, saved_search: {} }));
    vi.stubGlobal("fetch", fetchMock);
    const { api } = await import("@oracle/api-client");

    await api.procurementSearchProfiles.list();
    await api.procurementSearchProfiles.get("perfil/andalucía");
    await api.procurementSearchProfiles.create(createBody);
    await api.procurementSearchProfiles.accept("perfil/andalucía", acceptBody);
    await api.procurementSearchProfiles.saveSearch(
      "perfil/andalucía",
      saveBody,
    );

    expect(fetchMock.mock.calls[0][0]).toBe(
      "/api/v1/procurement-search-profiles",
    );
    expect(fetchMock.mock.calls[1][0]).toBe(
      "/api/v1/procurement-search-profiles/perfil%2Fandaluc%C3%ADa",
    );
    expect(fetchMock.mock.calls[2][0]).toBe("/api/v1/auth/csrf");

    const mutations = fetchMock.mock.calls.slice(3) as [string, RequestInit][];
    expect(mutations.map(([url]) => url)).toEqual([
      "/api/v1/procurement-search-profiles",
      "/api/v1/procurement-search-profiles/perfil%2Fandaluc%C3%ADa/acceptances",
      "/api/v1/procurement-search-profiles/perfil%2Fandaluc%C3%ADa/saved-search",
    ]);
    expect(mutations.map(([, options]) => options.method)).toEqual([
      "POST",
      "POST",
      "POST",
    ]);
    for (const [, options] of mutations) {
      expect(options.credentials).toBe("include");
      expect(new Headers(options.headers).get("X-CSRF-Token")).toBe(
        "csrf-profile",
      );
    }
    expect(JSON.parse(String(mutations[0][1].body))).toEqual(createBody);
    expect(JSON.parse(String(mutations[1][1].body))).toEqual(acceptBody);
    expect(JSON.parse(String(mutations[2][1].body))).toEqual(saveBody);
    expect(JSON.parse(String(mutations[1][1].body)).expected_version).toBe(3);
    expect(JSON.parse(String(mutations[2][1].body)).expected_version).toBe(4);
  });

  it("expone Retry-After cuando el wizard está limitado", async () => {
    const problem = {
      type: "about:blank",
      title: "Demasiadas solicitudes",
      status: 429,
      detail: "Espera antes de volver a generar.",
      instance: "/api/v1/ai/tender-search-wizard/latest",
      code: "rate_limit_exceeded",
      request_id: "req-wizard-limit",
    };
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(json(problem, 429, { "Retry-After": "45" })),
    );
    const { api } = await import("@oracle/api-client");

    await expect(api.tenderSearchWizard.latest()).rejects.toMatchObject({
      status: 429,
      retryAfter: 45,
      problem,
    });
  });
});
