import { afterEach, describe, expect, it, vi } from "vitest";

function json(body: unknown, status = 200, headers: Record<string,string> = {}) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type":"application/json", ...headers } });
}

afterEach(() => { vi.unstubAllGlobals(); vi.resetModules(); });

describe("transporte auth", () => {
  it("envía cookie y CSRF sin escribir tokens en storage", async () => {
    const storage = vi.spyOn(Storage.prototype, "setItem");
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(json({ csrf_token:"csrf-inicial-seguro-123456789012345" }))
      .mockResolvedValueOnce(json({ session_id:"00000000-0000-4000-8000-000000000001", requires_tenant_selection:false }))
      .mockResolvedValueOnce(json({ csrf_token:"csrf-renovado-seguro-12345678901234" }))
      .mockResolvedValueOnce(new Response(null, { status:204 }));
    vi.stubGlobal("fetch", fetchMock);
    const { api } = await import("@oracle/api-client");
    await api.auth.login({ email:"ana@example.test", password:"frase larga segura" });
    const options = fetchMock.mock.calls[1][1] as RequestInit;
    expect(options.credentials).toBe("include");
    expect(new Headers(options.headers).get("X-CSRF-Token")).toBe("csrf-inicial-seguro-123456789012345");
    await api.auth.logout();
    const logoutOptions = fetchMock.mock.calls[3][1] as RequestInit;
    expect(new Headers(logoutOptions.headers).get("X-CSRF-Token")).toBe("csrf-renovado-seguro-12345678901234");
    expect(storage).not.toHaveBeenCalled();
    storage.mockRestore();
  });

  it("tras reautenticar renueva CSRF antes de continuar", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(json({ csrf_token:"csrf-antiguo-123456789012345678901" }))
      .mockResolvedValueOnce(json({ status:"fresh" }))
      .mockResolvedValueOnce(json({ csrf_token:"csrf-nuevo-1234567890123456789012" }));
    vi.stubGlobal("fetch", fetchMock);
    const { api } = await import("@oracle/api-client");
    await api.auth.reauthenticate("frase larga segura");
    expect(fetchMock.mock.calls.map(call => call[0])).toEqual(["/api/v1/auth/csrf", "/api/v1/auth/reauthenticate", "/api/v1/auth/csrf"]);
    const reauthOptions = fetchMock.mock.calls[1][1] as RequestInit;
    expect(new Headers(reauthOptions.headers).get("X-CSRF-Token")).toBe("csrf-antiguo-123456789012345678901");
  });

  it("descarta CSRF al expirar sesión y usa uno nuevo al volver a entrar", async () => {
    const expired = { type:"about:blank", title:"Sesión caducada", status:401, detail:"Inicia sesión.", instance:"/api/v1/auth/me", code:"session_expired", request_id:"req-expired" };
    const login = { session_id:"00000000-0000-4000-8000-000000000001", requires_tenant_selection:false };
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(json({ csrf_token:"csrf-antes-login-111111111111111111" }))
      .mockResolvedValueOnce(json(login))
      .mockResolvedValueOnce(json({ csrf_token:"csrf-sesion-vieja-22222222222222222" }))
      .mockResolvedValueOnce(json(expired, 401))
      .mockResolvedValueOnce(json({ csrf_token:"csrf-relogin-fresco-333333333333333" }))
      .mockResolvedValueOnce(json(login))
      .mockResolvedValueOnce(json({ csrf_token:"csrf-sesion-nueva-4444444444444444" }));
    vi.stubGlobal("fetch", fetchMock);
    const { api } = await import("@oracle/api-client");
    await api.auth.login({email:"ana@example.test",password:"frase larga segura"});
    await expect(api.auth.me()).rejects.toMatchObject({status:401});
    await api.auth.login({email:"ana@example.test",password:"frase larga segura"});
    const secondLogin = fetchMock.mock.calls[5][1] as RequestInit;
    expect(new Headers(secondLogin.headers).get("X-CSRF-Token")).toBe("csrf-relogin-fresco-333333333333333");
  });

  it("expone Problem Details y Retry-After", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(json({ type:"about:blank",title:"Límite",status:429,detail:"Espera",instance:"/login",code:"login_temporarily_locked",request_id:"req-1" }, 429, {"Retry-After":"30"})));
    const { api } = await import("@oracle/api-client");
    await expect(api.auth.me()).rejects.toMatchObject({ status:429, retryAfter:30 });
  });
});
