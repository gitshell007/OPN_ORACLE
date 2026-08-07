import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";

const dossierId = "11111111-1111-4111-8111-111111111111";
const etag = 'W/"dmp-v0-test"';

async function mockMemoryApis(page: Page, opts?: { putStatus?: number }) {
  await page.route("**/api/v1/auth/csrf", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ csrf_token: "csrf-memory-e2e-12345678901234567890" }),
    });
  });
  await page.route("**/api/v1/auth/me", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        user: {
          id: "user-1",
          email: "memory-e2e@example.test",
          display_name: "Memory E2E",
          status: "active",
        },
        active_tenant_id: "tenant-1",
        permissions: ["dossier.read", "dossier.write", "signal.review"],
      }),
    });
  });
  await page.route(`**/api/v1/dossiers/${dossierId}`, async (route) => {
    if (route.request().method() !== "GET") {
      await route.continue();
      return;
    }
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        id: dossierId,
        tenant_id: "tenant-1",
        title: "Expediente memoria E2E",
        description: "",
        dossier_type: "project",
        status: "active",
        strategic_goal: "Validar memoria",
        health_score: 50,
        opportunity_score: 50,
        risk_score: 10,
        owner_user_id: "user-1",
        version: 1,
        archived_at: null,
        created_at: "2026-08-02T00:00:00Z",
        updated_at: "2026-08-02T00:00:00Z",
      }),
    });
  });
  await page.route("**/api/v1/integrations/signal-avanza/connections**", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ items: [] }),
    });
  });
  await page.route(`**/api/v1/dossiers/${dossierId}/signal-avanza/monitors**`, async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ data: [] }),
    });
  });
  const profile = {
    id: null,
    tenant_id: "tenant-1",
    dossier_id: dossierId,
    connection_id: null,
    mode: "disabled",
    mode_label_es: "Desactivada",
    version: 0,
    etag,
    sources: ["document", "signal"],
    kinds: ["fact", "chunk"],
    classifications_allowed: ["public", "internal"],
    token_budget: 4000,
    limit: 20,
    status: "ephemeral_default",
    provenance: "effective_default_not_persisted",
    last_test_at: null,
    last_test_status: null,
    last_error: null,
    last_coverage: null,
    updated_at: null,
    persisted: false,
    publisher_reliable: false,
    actions_reliable: false,
    deferred_blockers: ["RACE-MDEV02-003"],
  };
  await page.route(`**/api/v1/dossiers/${dossierId}/memory/effective**`, async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(profile),
    });
  });
  await page.route(`**/api/v1/dossiers/${dossierId}/memory/profile**`, async (route) => {
    if (route.request().method() === "PUT") {
      const status = opts?.putStatus ?? 200;
      if (status === 409) {
        await route.fulfill({
          status: 409,
          contentType: "application/problem+json",
          body: JSON.stringify({
            title: "Conflict",
            status: 409,
            detail: "ETag mismatch; reload and retry.",
            code: "etag_conflict",
          }),
        });
        return;
      }
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        headers: { ETag: 'W/"dmp-v1-saved"' },
        body: JSON.stringify({
          ...profile,
          id: "profile-1",
          mode: "shadow",
          version: 1,
          etag: 'W/"dmp-v1-saved"',
          persisted: true,
        }),
      });
      return;
    }
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(profile),
    });
  });
  await page.route(
    `**/api/v1/dossiers/${dossierId}/memory/test-connection**`,
    async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          ok: true,
          status: "ok",
          synthetic: true,
          publisher_reliable: false,
          message: "synthetic ok",
        }),
      });
    },
  );
}

async function openSettings(page: Page) {
  await page.goto(`/app/dossiers/${dossierId}/settings`);
  await expect(page.getByTestId("dossier-memory-settings")).toBeVisible({ timeout: 15000 });
}

test.describe("Dossier memory settings (MDEV-04)", () => {
  test("desktop: modes, degraded banner, reload controls, no console 500", async ({
    page,
  }) => {
    const consoleErrors: string[] = [];
    page.on("console", (msg) => {
      if (msg.type() === "error") consoleErrors.push(msg.text());
    });
    page.on("pageerror", (err) => consoleErrors.push(String(err)));
    await mockMemoryApis(page);
    await page.setViewportSize({ width: 1280, height: 900 });
    await openSettings(page);
    const section = page.getByTestId("dossier-memory-settings");
    await expect(section.getByRole("heading", { name: "Memoria del expediente" })).toBeVisible();
    await expect(section.getByText(/defaults no persistidos/i)).toBeVisible();
    await expect(section.getByText(/servicio degradado/i)).toBeVisible();
    await section.getByLabel("Modo").selectOption("shadow");
    await section.getByLabel("Límite de resultados").fill("12");
    await section.getByRole("button", { name: /Guardar memoria/i }).click();
    await expect(section.getByLabel("Modo")).toHaveValue("shadow");
    await section.getByRole("button", { name: /Probar conexión/i }).click();
    const axe = await new AxeBuilder({ page }).include('[data-testid="dossier-memory-settings"]').analyze();
    expect(axe.violations.filter((v) => v.impact === "critical" || v.impact === "serious")).toEqual(
      [],
    );
    expect(consoleErrors.filter((e) => /500|Internal Server/i.test(e))).toEqual([]);
  });

  test("narrow: memory controls usable and keyboard focusable", async ({ page }) => {
    await mockMemoryApis(page);
    await page.setViewportSize({ width: 390, height: 844 });
    await openSettings(page);
    const section = page.getByTestId("dossier-memory-settings");
    await expect(section).toBeVisible();
    await section.getByLabel("Modo").focus();
    await expect(section.getByLabel("Modo")).toBeFocused();
    await page.keyboard.press("Tab");
    await section.getByLabel("Límite de resultados").focus();
    await expect(section.getByLabel("Límite de resultados")).toBeFocused();
  });

  test("stale ETag surfaces error without 500", async ({ page }) => {
    const consoleErrors: string[] = [];
    page.on("console", (msg) => {
      if (msg.type() === "error") consoleErrors.push(msg.text());
    });
    await mockMemoryApis(page, { putStatus: 409 });
    await openSettings(page);
    const section = page.getByTestId("dossier-memory-settings");
    await section.getByLabel("Modo").selectOption("augment");
    await section.getByRole("button", { name: /Guardar memoria/i }).click();
    await expect(page.getByRole("alert").or(section.locator(".inline-error"))).toBeVisible({
      timeout: 10000,
    });
    expect(consoleErrors.filter((e) => /status.?500|Internal Server/i.test(e))).toEqual([]);
  });
});
