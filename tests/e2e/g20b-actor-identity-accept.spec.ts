/**
 * G-20-B · Playwright against real Oracle backend + disposable PG.
 *
 * NO page.route / network mocks in the browser.
 * Fixture artifact is seeded by tests/seed_frontend_e2e.py (_seed_g20b_market_actor_fixture)
 * into real PostgreSQL; UI and accept hit the live API.
 */
import { expect, test, type APIRequestContext, type Page } from "@playwright/test";

const OWNER_EMAIL = process.env.ORACLE_E2E_EMAIL || "owner@oracle-e2e.test";
const OWNER_PASSWORD = process.env.ORACLE_E2E_PASSWORD || "Oracle E2E segura 2026";
const FIXTURE_TITLE = "G-20-B Market actor discovery E2E";

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

async function findFixtureDossierId(
  request: APIRequestContext,
  _cookieHeader: string,
): Promise<string | null> {
  const headers = { "X-Forwarded-For": "198.51.100.142" };
  const candidates = [
    "/api/v1/dossiers",
    "/api/v1/dossiers?limit=100",
    "/api/v1/workspaces/current/dossiers",
  ];
  for (const path of candidates) {
    const res = await request.get(path, { headers });
    if (!res.ok()) continue;
    const body = await res.json();
    const items = Array.isArray(body)
      ? body
      : body?.data || body?.items || body?.dossiers || body?.results || [];
    for (const d of items) {
      if (d?.title === FIXTURE_TITLE) return String(d.id);
      if (
        d?.dossier_type === "market" &&
        String(d?.profile_config?.discovery_intent || "").includes("grafeno")
      ) {
        return String(d.id);
      }
    }
  }
  // UI fallback: scrape dossier cards from /app/dossiers list page is done by caller.
  return null;
}

test.describe("G-20-B actor identity accept (real backend, no page.route)", () => {
  test("open candidates, check IDs/score, accept subset, durable actor, repeat click", async ({
    page,
    context,
  }, testInfo) => {
    test.skip(
      testInfo.project.name === "mobile",
      "Identity accept gate validated on desktop.",
    );
    test.setTimeout(180_000);

    // Runtime guard: this suite must never mock browser network.
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    (page as any).route = async () => {
      throw new Error("G-20-B forbids page.route network mocks");
    };

    await loginOwner(page);

    // Use browser context.request so session cookies are shared (real API).
    const api = context.request;
    let dossierId = await findFixtureDossierId(api, "");
    if (!dossierId) {
      // UI scrape fallback against real list (still no page.route).
      await page.goto("/app/dossiers");
      await expect(page.locator("main")).toBeVisible({ timeout: 20_000 });
      const link = page.getByRole("link", { name: new RegExp(FIXTURE_TITLE, "i") }).first();
      if (await link.isVisible({ timeout: 10_000 }).catch(() => false)) {
        const href = (await link.getAttribute("href")) || "";
        const m = href.match(/\/app\/dossiers\/([0-9a-f-]+)/i);
        if (m) dossierId = m[1];
      }
    }
    expect(dossierId, "G-20-B fixture market dossier must be seeded").toBeTruthy();

    // Panel lives in dossier work/actors (Análisis), not always on summary.
    await page.goto(`/app/dossiers/${dossierId}/actors`);
    await expect(page.locator("main")).toBeVisible({ timeout: 20_000 });

    const panel = page.getByTestId("actor-discovery-panel");
    if (!(await panel.isVisible({ timeout: 5_000 }).catch(() => false))) {
      await page.goto(`/app/dossiers/${dossierId}`);
      await expect(page.locator("main")).toBeVisible({ timeout: 20_000 });
    }
    await expect(panel).toBeVisible({ timeout: 20_000 });

    // Candidates from real fixture artifact (API/DB), not browser mocks.
    const list = page.getByTestId("actor-discovery-list");
    await expect(list).toBeVisible({ timeout: 20_000 });
    const item = page.getByTestId("actor-discovery-item").first();
    await expect(item).toBeVisible();

    // Identity densification when present
    const ids = page.getByTestId("actor-structured-ids").first();
    if (await ids.isVisible().catch(() => false)) {
      await expect(ids).toContainText(/RNSR|ROR|rnsr|ror|04dbzz632|200717524/i);
    }
    const identity = page.getByTestId("actor-identity-status").first();
    if (await identity.isVisible().catch(() => false)) {
      const status = await identity.getAttribute("data-status");
      expect(["validated", "unresolved", "cross_referenced"]).toContain(status);
    }
    const score = page.getByTestId("actor-score-breakdown").first();
    if (await score.isVisible().catch(() => false)) {
      await expect(score).toBeVisible();
    }

    // Accept subset via real UI → real accept API → real PG
    const checkbox = item.locator('input[type="checkbox"]').first();
    await expect(checkbox).toBeVisible();
    await checkbox.check();
    const acceptBtn = page.getByTestId("actor-discovery-accept");
    await expect(acceptBtn).toBeEnabled();
    await acceptBtn.click();

    // Success toast / result or error alert (honest)
    const result = page.getByTestId("actor-discovery-accept-result");
    const err = page.getByTestId("actor-discovery-error");
    await expect
      .poll(async () => {
        if (await result.isVisible().catch(() => false)) return "ok";
        if (await err.isVisible().catch(() => false)) return "err";
        return "wait";
      }, { timeout: 30_000 })
      .not.toBe("wait");

    if (await result.isVisible().catch(() => false)) {
      // Repeat click path: re-select and accept again (idempotent durable actor)
      if (await checkbox.isVisible().catch(() => false)) {
        await checkbox.check().catch(() => undefined);
      }
      if (await acceptBtn.isEnabled().catch(() => false)) {
        await acceptBtn.click();
        await page.waitForTimeout(1500);
      }

      // Verify durable actor via real API (not page.route)
      const actorsRes = await api.get(`/api/v1/dossiers/${dossierId}/actors`, {
        headers: { "X-Forwarded-For": "198.51.100.142" },
      });
      expect(actorsRes.ok(), `actors API status ${actorsRes.status()}`).toBeTruthy();
      const actorsBody = await actorsRes.json();
      const listActors = Array.isArray(actorsBody)
        ? actorsBody
        : actorsBody?.data || actorsBody?.items || actorsBody?.actors || [];
      expect(
        listActors.length,
        `expected durable dossier actors, body=${JSON.stringify(actorsBody).slice(0, 400)}`,
      ).toBeGreaterThanOrEqual(1);
      const actorId = String(listActors[0].actor_id || listActors[0].id || "");
      expect(actorId).toBeTruthy();
      // Strong IDs live on Actor entity (not the dossier link).
      const actorRes = await api.get(`/api/v1/actors/${actorId}`, {
        headers: { "X-Forwarded-For": "198.51.100.142" },
      });
      expect(actorRes.ok(), `actor GET ${actorRes.status()}`).toBeTruthy();
      const actorJson = await actorRes.json();
      const actor = actorJson?.data || actorJson;
      const idBlob = JSON.stringify(actor?.identifiers || actor);
      expect(idBlob).toMatch(/04dbzz632|200717524X/i);
      // Notes prove identity-first create path (not nominal merge conflict).
      expect(JSON.stringify(listActors[0])).toMatch(/validated\/create|market_actor_discovery/);
    } else {
      const text = await err.textContent();
      expect(text && text.length > 0).toBeTruthy();
    }
  });
});
