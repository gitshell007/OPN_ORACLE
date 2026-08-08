/**
 * ORA-UI-PANEL-INSETS — evidence on real Vector routes (authenticated).
 *
 * Primary: bounding boxes / computed styles on live product panels after
 * login against the disposable E2E harness (scripts/run-auth-e2e-api.sh + seed).
 *
 * Auxiliary: optional contract fixture — not the primary evidence.
 *
 * GHA note: frontend-e2e is skipped on push→oracle-dev; run this suite via
 * pull_request→master, workflow_dispatch, or local Playwright.
 */
import { expect, test, type Page } from "@playwright/test";
import path from "node:path";

const OWNER_EMAIL = process.env.ORACLE_E2E_EMAIL || "owner@oracle-e2e.test";
const OWNER_PASSWORD =
  process.env.ORACLE_E2E_PASSWORD || "Oracle E2E segura 2026";
/** Market + discovery intent + own_offer, no AI job (idle empty + profile). */
const IDLE_MARKET_TITLE = "ORA-UI Market discovery idle E2E";
/** Market with discovery artifact (strip + list/CTA). */
const STRIP_MARKET_TITLE = "G-20-B Market actor discovery E2E";

const EVIDENCE_DIR =
  process.env.VECTOR_PANEL_INSETS_EVIDENCE_DIR ||
  path.join(process.cwd(), "docs/ui/panel-insets-captures");

const VIEWPORTS = [
  { name: "desktop-1440", width: 1440, height: 900, minInset: 12 },
  { name: "tablet-1024", width: 1024, height: 768, minInset: 12 },
  { name: "mobile-390", width: 390, height: 844, minInset: 12 },
] as const;

async function loginOwner(page: Page) {
  await page.setExtraHTTPHeaders({ "X-Forwarded-For": "198.51.100.142" });
  await page.goto("/login?next=%2Fapp%2Fdossiers");
  if (/\/app\//.test(page.url())) {
    return;
  }
  await page.getByLabel("Correo electrónico").fill(OWNER_EMAIL);
  await page.getByLabel("Contraseña", { exact: true }).fill(OWNER_PASSWORD);
  await page.getByRole("button", { name: "Entrar en Oracle" }).click();
  const org = page.getByLabel("Organización");
  await expect(org).toBeVisible({ timeout: 20_000 });
  await org.selectOption({ label: "Asterion E2E" });
  await page.getByRole("button", { name: "Entrar en Oracle" }).click();
  await expect(page).toHaveURL(/\/app\/dossiers/, { timeout: 30_000 });
}

async function openDossierByTitle(page: Page, title: string): Promise<string> {
  await page.goto("/app/dossiers");
  await expect(page.locator("main")).toBeVisible({ timeout: 20_000 });
  const link = page.getByRole("link", { name: new RegExp(title, "i") }).first();
  await expect(link, `seed dossier «${title}» visible`).toBeVisible({
    timeout: 25_000,
  });
  const href = (await link.getAttribute("href")) || "";
  const match = href.match(/^(\/app\/dossiers\/[0-9a-f-]+)/i);
  expect(match, `parseable dossier href: ${href}`).toBeTruthy();
  const base = match![1];
  await page.goto(base);
  await expect(page.getByTestId("dossier-nav-summary")).toBeVisible({
    timeout: 20_000,
  });
  await expect(page.locator("main")).toBeVisible();
  return base;
}

async function noHorizontalOverflow(
  page: Page,
  panel: ReturnType<Page["getByTestId"]>,
) {
  // Panel itself must not force horizontal scroll of its box.
  const panelOverflow = await panel.evaluate((el) => ({
    scrollWidth: el.scrollWidth,
    clientWidth: el.clientWidth,
  }));
  expect(
    panelOverflow.scrollWidth,
    "panel must not overflow itself horizontally",
  ).toBeLessThanOrEqual(panelOverflow.clientWidth + 2);

  // Main product column (not off-canvas sidebar) should fit the viewport.
  const mainOverflow = await page.evaluate(() => {
    const main = document.querySelector("main");
    if (!main) return null;
    const r = main.getBoundingClientRect();
    return {
      right: r.right,
      inner: window.innerWidth,
    };
  });
  if (mainOverflow) {
    expect(mainOverflow.right).toBeLessThanOrEqual(mainOverflow.inner + 2);
  }
}

type InsetTarget = {
  panel: ReturnType<Page["getByTestId"]>;
  header: ReturnType<Page["locator"]>;
  body: ReturnType<Page["getByTestId"]>;
  text: ReturnType<Page["locator"]>;
  cta: ReturnType<Page["locator"]>;
  strip?: ReturnType<Page["locator"]>;
};

async function assertPanelInsets(
  page: Page,
  target: InsetTarget,
  minInset: number,
) {
  await expect(target.panel).toBeVisible();
  await expect(target.header).toBeVisible();
  await expect(target.body).toBeVisible();
  await expect(target.text).toBeVisible();
  await expect(target.cta).toBeVisible();

  const panelBox = await target.panel.boundingBox();
  const textBox = await target.text.boundingBox();
  const ctaBox = await target.cta.boundingBox();
  expect(panelBox).toBeTruthy();
  expect(textBox).toBeTruthy();
  expect(ctaBox).toBeTruthy();

  expect(textBox!.x - panelBox!.x).toBeGreaterThanOrEqual(minInset);
  expect(
    panelBox!.x + panelBox!.width - (textBox!.x + textBox!.width),
  ).toBeGreaterThanOrEqual(minInset - 1);
  expect(ctaBox!.x - panelBox!.x).toBeGreaterThanOrEqual(minInset);

  const pads = await target.panel.evaluate((panelEl) => {
    const header = panelEl.querySelector("header");
    const body = panelEl.querySelector(
      "[data-testid$='-body'], .vector-panel-body",
    );
    if (!header || !body) return null;
    const hs = getComputedStyle(header);
    const bs = getComputedStyle(body);
    return {
      headerPadL: parseFloat(hs.paddingLeft || "0"),
      bodyPadL: parseFloat(bs.paddingLeft || "0"),
      bodyPadR: parseFloat(bs.paddingRight || "0"),
    };
  });
  expect(pads).toBeTruthy();
  expect(pads!.bodyPadL).toBeGreaterThanOrEqual(minInset);
  expect(pads!.bodyPadR).toBeGreaterThanOrEqual(minInset);
  expect(Math.abs(pads!.headerPadL - pads!.bodyPadL)).toBeLessThanOrEqual(1);

  if (target.strip && (await target.strip.isVisible().catch(() => false))) {
    const stripBox = await target.strip.boundingBox();
    expect(stripBox).toBeTruthy();
    expect(Math.abs(stripBox!.x - panelBox!.x)).toBeLessThanOrEqual(2);
    expect(
      Math.abs(
        stripBox!.x + stripBox!.width - (panelBox!.x + panelBox!.width),
      ),
    ).toBeLessThanOrEqual(2);
    const stripPadL = await target.strip.evaluate((el) =>
      parseFloat(getComputedStyle(el).paddingLeft || "0"),
    );
    expect(Math.abs(stripPadL - pads!.headerPadL)).toBeLessThanOrEqual(1);
  }

  await noHorizontalOverflow(page, target.panel);
}

async function shot(page: Page, name: string) {
  await page.screenshot({
    path: path.join(EVIDENCE_DIR, name),
    fullPage: true,
  });
}

for (const viewport of VIEWPORTS) {
  test(`real Vector routes · profile + actors empty + strip · ${viewport.name}`, async ({
    page,
  }, testInfo) => {
    if (testInfo.project.name === "mobile" && viewport.name !== "mobile-390") {
      test.skip();
    }
    if (testInfo.project.name === "desktop" && viewport.name === "mobile-390") {
      test.skip();
    }
    test.setTimeout(180_000);
    await page.setViewportSize({
      width: viewport.width,
      height: viewport.height,
    });

    // One login per viewport → avoids login rate-limit across many tests.
    await loginOwner(page);

    // --- 1) DossierProfilePanel (read-only) on summary ---
    const idleBase = await openDossierByTitle(page, IDLE_MARKET_TITLE);
    await page.goto(idleBase);
    await expect(page.getByTestId("dossier-nav-summary")).toBeVisible({
      timeout: 20_000,
    });
    {
      const panel = page.getByTestId("dossier-profile-summary");
      await expect(panel).toBeVisible({ timeout: 20_000 });
      const body = page.getByTestId("dossier-profile-body");
      const header = panel.locator("header").first();
      const text = body.locator("p, dd").first();
      const cta = body.getByRole("link").first();
      await assertPanelInsets(
        page,
        { panel, header, body, text, cta },
        viewport.minInset,
      );
      await shot(page, `dossier-summary-profile-${viewport.name}.png`);
    }

    // --- 2) ActorDiscoveryPanel idle empty + header CTA ---
    await page.goto(`${idleBase}/actors`);
    await expect(page.locator("main")).toBeVisible({ timeout: 20_000 });
    {
      const panel = page.getByTestId("actor-discovery-panel");
      await expect(panel).toBeVisible({ timeout: 20_000 });
      const body = page.getByTestId("actor-discovery-body");
      const header = panel.locator("header").first();
      const idle = page.getByTestId("actor-discovery-idle");
      await expect(idle).toBeVisible({ timeout: 20_000 });
      const text = idle.locator("p").first();
      const cta = page.getByTestId("actor-discovery-retry");
      const strip = page.getByTestId("actor-discovery-intent");
      await assertPanelInsets(
        page,
        { panel, header, body, text, cta, strip },
        viewport.minInset,
      );
      await shot(page, `dossier-actors-discovery-empty-${viewport.name}.png`);
    }

    // --- 3) Strip full-bleed on market with discovery artifact ---
    const stripBase = await openDossierByTitle(page, STRIP_MARKET_TITLE);
    await page.goto(`${stripBase}/actors`);
    await expect(page.locator("main")).toBeVisible({ timeout: 20_000 });
    {
      const panel = page.getByTestId("actor-discovery-panel");
      await expect(panel).toBeVisible({ timeout: 20_000 });
      const body = page.getByTestId("actor-discovery-body");
      const header = panel.locator("header").first();
      const strip = page.getByTestId("actor-discovery-intent");
      await expect(strip).toBeVisible({ timeout: 15_000 });
      const empty = page.getByTestId("actor-discovery-empty-result");
      const hasEmpty = await empty.isVisible().catch(() => false);
      const text = hasEmpty
        ? empty.locator("p").first()
        : body.locator("p, li, label, strong").first();
      const cta = page
        .getByTestId("actor-discovery-accept")
        .or(page.getByTestId("actor-discovery-retry"))
        .first();
      await assertPanelInsets(
        page,
        { panel, header, body, text, cta, strip },
        viewport.minInset,
      );
      await shot(page, `dossier-actors-discovery-strip-${viewport.name}.png`);
    }
  });
}

/**
 * Auxiliary only: synthetic contract smoke. Must not replace route evidence.
 */
test("auxiliary synthetic contract (not product evidence)", async ({
  page,
}, testInfo) => {
  test.skip(testInfo.project.name === "mobile", "aux once on desktop");
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.setContent(
    `<!doctype html><html><body>
    <section class="vector-panel" data-testid="aux-panel">
      <header data-testid="aux-header"><h2>Aux</h2></header>
      <div class="vector-panel-body" data-testid="aux-body"><p data-testid="aux-p">x</p></div>
    </section></body></html>`,
  );
  await page.addStyleTag({
    content: `
    :root { --space-3:12px; --space-4:16px; --va-panel:#fff; --va-border:#ccc; --va-radius:6px; }
    .vector-panel { --vector-panel-pad-x:var(--space-4); --vector-panel-pad-y:var(--space-3);
      --vector-panel-pad-y-header:var(--space-3); background:#fff; border:1px solid #ccc; width:480px; margin:20px; }
    .vector-panel > header { padding: var(--vector-panel-pad-y-header) var(--vector-panel-pad-x); border-bottom:1px solid #ccc; }
    .vector-panel-body { padding: var(--vector-panel-pad-y) var(--vector-panel-pad-x); }
    `,
  });
  await assertPanelInsets(
    page,
    {
      panel: page.getByTestId("aux-panel"),
      header: page.getByTestId("aux-header"),
      body: page.getByTestId("aux-body"),
      text: page.getByTestId("aux-p"),
      cta: page.getByTestId("aux-p"),
    },
    12,
  );
});
