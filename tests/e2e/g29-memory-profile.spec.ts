/**
 * G-29 · Playwright against real Oracle backend + disposable PG.
 *
 * NO page.route / network mocks in the browser.
 * Creates a dossier via UI (real CSRF), checks memory profile in settings,
 * changes mode, reloads, confirms persistence. Stale conflict via real API+CSRF.
 */
import { expect, test, type APIRequestContext, type Page } from "@playwright/test";

const OWNER_EMAIL = process.env.ORACLE_E2E_EMAIL || "owner@oracle-e2e.test";
const OWNER_PASSWORD = process.env.ORACLE_E2E_PASSWORD || "Oracle E2E segura 2026";

async function loginOwner(page: Page) {
  await page.setExtraHTTPHeaders({ "X-Forwarded-For": "198.51.100.142" });
  await page.goto("/login?next=%2Fapp%2Fdossiers");
  await page.getByLabel("Correo electrónico").fill(OWNER_EMAIL);
  await page.getByLabel("Contraseña", { exact: true }).fill(OWNER_PASSWORD);
  await page.getByRole("button", { name: "Entrar en Oracle" }).click();
  await expect(page.getByLabel("Organización")).toBeVisible({ timeout: 15_000 });
  await page.getByLabel("Organización").selectOption({ label: "Asterion E2E" });
  await page.getByRole("button", { name: "Entrar en Oracle" }).click();
  await expect(page).toHaveURL(/\/app\/dossiers/, { timeout: 30_000 });
}

async function csrfToken(request: APIRequestContext): Promise<string> {
  const res = await request.get("/api/v1/auth/csrf", {
    headers: { "X-Forwarded-For": "198.51.100.142" },
  });
  expect(res.ok(), await res.text()).toBeTruthy();
  const body = await res.json();
  return String(body.csrf_token || body.token || "");
}

test.describe("G-29 memory profile (real backend, no page.route)", () => {
  test("create dossier, visible profile, change mode, reload, stale 409", async ({
    page,
    context,
  }, testInfo) => {
    test.skip(
      testInfo.project.name === "mobile",
      "G-29 memory gate validated on desktop.",
    );
    test.setTimeout(180_000);

    // Runtime guard: this suite must never mock browser network.
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    (page as any).route = async () => {
      throw new Error("G-29 forbids page.route network mocks");
    };

    await loginOwner(page);
    const api = context.request;
    const headersBase = { "X-Forwarded-For": "198.51.100.142" };

    // Create dialog shows honest memory notice
    await page.getByRole("button", { name: /Nuevo expediente|Crear expediente|Nuevo/i }).first().click();
    const dialog = page.getByRole("dialog", { name: /Nuevo expediente/i });
    await expect(dialog).toBeVisible({ timeout: 15_000 });
    await expect(dialog.getByTestId("create-dossier-memory-notice")).toBeVisible();
    await expect(dialog.getByTestId("create-dossier-memory-notice")).toContainText(/Desactivada/i);

    const title = `G-29 Memoria honesta ${Date.now()}`;
    await dialog.getByLabel("Nombre").fill(title);
    await dialog.getByLabel("Tipo", { exact: true }).selectOption("custom");
    await dialog.getByLabel("Objetivo estratégico").fill("Probar perfil de memoria G-29");
    await dialog.getByRole("button", { name: /Crear expediente|Crear|Guardar/i }).click();

    // Wait for navigation to new dossier
    await expect(page).toHaveURL(/\/app\/dossiers\/[0-9a-f-]{36}/, { timeout: 30_000 });
    const dossierId = page.url().match(/\/app\/dossiers\/([0-9a-f-]{36})/)?.[1];
    expect(dossierId).toBeTruthy();

    // API: profile persisted with server default disabled
    const profileRes = await api.get(
      `/api/v1/dossiers/${encodeURIComponent(dossierId!)}/memory/profile`,
      { headers: headersBase },
    );
    expect(profileRes.ok(), await profileRes.text()).toBeTruthy();
    const profile = await profileRes.json();
    expect(profile.persisted).toBe(true);
    expect(profile.mode).toBe("disabled");
    expect(profile.status).not.toBe("legacy_missing");
    expect(profile.scope?.dossier_only).toBe(true);
    expect(profile.scope?.uses_global_memory).toBe(false);
    expect(profile.scope?.uses_tenant_curated).toBe(false);
    const etag = String(profile.etag);
    const version = Number(profile.version);

    // UI settings
    await page.goto(`/app/dossiers/${dossierId}/settings`);
    const section = page.getByTestId("dossier-memory-settings");
    await expect(section).toBeVisible({ timeout: 30_000 });
    await expect(section.getByRole("heading", { name: "Memoria de este expediente" })).toBeVisible();
    await expect(section.getByTestId("dossier-memory-mode")).toBeVisible();
    await expect(section.getByTestId("dossier-memory-scope")).toBeVisible();

    await section.getByTestId("dossier-memory-mode").selectOption("shadow");
    await section.getByRole("button", { name: /Guardar memoria/i }).click();
    await expect(section.getByTestId("dossier-memory-meta")).toContainText(/Versión/, {
      timeout: 15_000,
    });

    await page.reload();
    await expect(page.getByTestId("dossier-memory-settings")).toBeVisible({ timeout: 30_000 });
    await expect(page.getByTestId("dossier-memory-mode")).toHaveValue("shadow");

    const after = await (
      await api.get(`/api/v1/dossiers/${encodeURIComponent(dossierId!)}/memory/profile`, {
        headers: headersBase,
      })
    ).json();
    expect(after.mode).toBe("shadow");
    expect(Number(after.version)).toBeGreaterThan(version);

    // Stale concurrency via real API + CSRF (no page.route)
    const token = await csrfToken(api);
    const stale = await api.put(
      `/api/v1/dossiers/${encodeURIComponent(dossierId!)}/memory/profile`,
      {
        headers: {
          ...headersBase,
          "Content-Type": "application/json",
          "X-CSRF-Token": token,
          "If-Match": etag,
        },
        data: { mode: "augment", expected_version: version },
      },
    );
    expect(stale.status()).toBe(409);
  });
});
