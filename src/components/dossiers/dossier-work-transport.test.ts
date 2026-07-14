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

describe("transporte productivo del trabajo de expediente", () => {
  it("pagina tareas dentro del expediente y codifica el identificador", async () => {
    const fetchMock = vi.fn().mockResolvedValue(json({ data: [], meta: { page: 2, size: 25, total: 0 } }));
    vi.stubGlobal("fetch", fetchMock);
    const { api } = await import("@oracle/api-client");

    await api.tasks.list("dossier/seguro", { page: 2, status: "open", search: "  propuesta " });

    const [rawUrl] = fetchMock.mock.calls[0] as [string];
    const url = new URL(rawUrl, "https://oracle.example.test");
    expect(url.pathname).toBe("/api/v1/dossiers/dossier%2Fseguro/tasks");
    expect(Object.fromEntries(url.searchParams)).toEqual({
      "page[number]": "2",
      "page[size]": "25",
      sort: "-updated_at",
      "filter[status]": "open",
      "filter[search]": "propuesta",
    });
  });

  it("aplica CSRF y concurrencia optimista al completar una tarea", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(json({ csrf_token: "csrf-test" }))
      .mockResolvedValueOnce(json({ id: "task-1", status: "done", version: 4 }));
    vi.stubGlobal("fetch", fetchMock);
    const { api } = await import("@oracle/api-client");

    await api.tasks.update("task-1", { status: "done", version: 3 }, 3);

    const [url, options] = fetchMock.mock.calls[1] as [string, RequestInit];
    expect(url).toBe("/api/v1/tasks/task-1");
    expect(options.method).toBe("PATCH");
    expect((options.headers as Headers).get("If-Match")).toBe('W/"3"');
    expect((options.headers as Headers).get("X-CSRF-Token")).toBe("csrf-test");
  });

  it("solicita un briefing IA bajo una reunión", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(json({ csrf_token: "csrf-test" }))
      .mockResolvedValueOnce(json({ briefing: null, job: { id: "job-1", status: "queued" } }));
    vi.stubGlobal("fetch", fetchMock);
    const { api } = await import("@oracle/api-client");

    await api.meetings.createBriefing("meeting-1", "briefing-test-key");

    const [url, options] = fetchMock.mock.calls[1] as [string, RequestInit];
    expect(url).toBe("/api/v1/meetings/meeting-1/briefings");
    expect((options.headers as Headers).get("Idempotency-Key")).toBe("briefing-test-key");
    expect(JSON.parse(String(options.body))).toEqual({});
  });

  it("cierra una reunión con If-Match e idempotencia", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(json({ csrf_token: "csrf-test" }))
      .mockResolvedValueOnce(json({
        meeting: { id: "meeting-1", status: "completed", version: 2 },
        decisions: [],
        tasks: [],
        replayed: false,
      }));
    vi.stubGlobal("fetch", fetchMock);
    const { api } = await import("@oracle/api-client");

    await api.meetings.complete(
      "meeting-1",
      { notes: "Resultados", decisions: [], tasks: [], version: 1 },
      1,
      "meeting-complete-key",
    );

    const [url, options] = fetchMock.mock.calls[1] as [string, RequestInit];
    expect(url).toBe("/api/v1/meetings/meeting-1/complete");
    expect(options.method).toBe("POST");
    expect((options.headers as Headers).get("If-Match")).toBe('W/"1"');
    expect((options.headers as Headers).get("Idempotency-Key")).toBe("meeting-complete-key");
    expect((options.headers as Headers).get("X-CSRF-Token")).toBe("csrf-test");
    expect(JSON.parse(String(options.body))).toEqual({
      notes: "Resultados",
      decisions: [],
      tasks: [],
      version: 1,
    });
  });
});
