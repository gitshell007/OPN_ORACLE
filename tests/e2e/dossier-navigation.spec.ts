/**
 * SV2-UI-E2E: Playwright coverage of grouped dossier navigation.
 * Requires the auth E2E API harness (scripts/run-auth-e2e-api.sh) + seed.
 */
import { expect, test, type Page, type TestInfo } from "@playwright/test";

async function loginOwner(page: Page, _testInfo: TestInfo) {
  await page.setExtraHTTPHeaders({ "X-Forwarded-For": "198.51.100.142" });
  await page.goto("/login?next=%2Fapp%2Fdossiers");
  await page.getByLabel("Correo electrónico").fill("owner@oracle-e2e.test");
  await page
    .getByLabel("Contraseña", { exact: true })
    .fill("Oracle E2E segura 2026");
  await page.getByRole("button", { name: "Entrar en Oracle" }).click();
  await expect(page.getByLabel("Organización")).toBeVisible();
  await page.getByLabel("Organización").selectOption({ label: "Asterion E2E" });
  await page.getByRole("button", { name: "Entrar en Oracle" }).click();
  await expect(page).toHaveURL(/\/app\/dossiers/);
}

async function openFirstDossier(page: Page): Promise<string> {
  await page.goto("/app/dossiers");
  await expect(page.locator("main")).toBeVisible({ timeout: 20_000 });
  const link = page.locator('a[href^="/app/dossiers/"]').first();
  await expect(link).toBeVisible({ timeout: 20_000 });
  const href = (await link.getAttribute("href")) ?? "";
  const match = href.match(/^(\/app\/dossiers\/[0-9a-f-]+)/);
  expect(match, `dossier href parseable: ${href}`).toBeTruthy();
  const base = match![1];
  await page.goto(base);
  await expect(page.getByTestId("dossier-nav-summary")).toBeVisible({
    timeout: 20_000,
  });
  return base;
}

function assertNoBodyHorizontalScroll(page: Page) {
  return page.evaluate(() => {
    const body = document.body;
    return {
      scrollWidth: body.scrollWidth,
      innerWidth: window.innerWidth,
      ok: body.scrollWidth <= window.innerWidth,
    };
  });
}

test.describe("SV2-UI-E2E dossier grouped navigation", () => {
  test("6 grupos, destinos por defecto, activo, subnav, aria-current, atajos", async ({
    page,
  }, testInfo) => {
    test.skip(
      testInfo.project.name === "mobile",
      "Contrato de navegación de expediente se valida en desktop.",
    );
    test.setTimeout(120_000);

    await loginOwner(page, testInfo);
    const base = await openFirstDossier(page);

    // 1. Seis grupos visibles con destinos por defecto
    const expected: Record<string, RegExp> = {
      summary: new RegExp(`${base}/?$`),
      surveillance: new RegExp(`${base}/signals/?$`),
      analysis: new RegExp(`${base}/actors/?$`),
      decision: new RegExp(`${base}/decisions/?$`),
      deliverables: new RegExp(`${base}/reports/?$`),
      activity: new RegExp(`${base}/activity/?$`),
    };
    for (const [groupId, hrefRe] of Object.entries(expected)) {
      const el = page.getByTestId(`dossier-nav-${groupId}`);
      await expect(el).toBeVisible();
      const href = await el.getAttribute("href");
      expect(href, groupId).toMatch(hrefRe);
    }

    // Click Vigilancia → signals
    await page.getByTestId("dossier-nav-surveillance").click();
    await expect(page).toHaveURL(new RegExp(`${base}/signals`));
    await expect(page.getByTestId("dossier-nav-surveillance")).toHaveAttribute(
      "data-active",
      "true",
    );

    // 2. En /procurement el activo es Vigilancia, no Resumen
    await page.goto(`${base}/procurement`);
    await expect(page.getByTestId("dossier-nav-surveillance")).toHaveAttribute(
      "data-active",
      "true",
    );
    await expect(page.getByTestId("dossier-nav-summary")).not.toHaveAttribute(
      "data-active",
      "true",
    );

    // 3. Subnav presente en Vigilancia; ausente en Resumen y Actividad
    await expect(page.getByTestId("dossier-subnav-procurement")).toBeVisible();
    await expect(page.getByTestId("dossier-subnav-signals")).toBeVisible();

    await page.goto(base);
    await expect(page.getByTestId("dossier-nav-summary")).toBeVisible();
    await expect(page.locator(".dossier-subnav")).toHaveCount(0);

    await page.goto(`${base}/activity`);
    await expect(page.getByTestId("dossier-nav-activity")).toHaveAttribute(
      "data-active",
      "true",
    );
    await expect(page.locator(".dossier-subnav")).toHaveCount(0);

    // Subnav en Análisis / Decisión / Entregables
    for (const path of ["actors", "decisions", "reports"] as const) {
      await page.goto(`${base}/${path}`);
      await expect(page.locator(".dossier-subnav")).toBeVisible();
    }

    // 4. `aria-current="page"` se declara POR LANDMARK, no una vez por
    // documento: las migas de pan lo llevan por convención WAI-ARIA y la
    // navegación del expediente también. La regresión que protegemos es el
    // duplicado DENTRO de una misma navegación (lo provocaba el antiguo
    // <details>Más</details>, que repetía trece pestañas en el DOM).
    for (const path of ["signals", "procurement", ""] as const) {
      await page.goto(path ? `${base}/${path}` : base);
      // Ninguna navegación puede marcar dos veces la página actual.
      await expect
        .poll(async () =>
          page.evaluate(() =>
            Math.max(
              ...[...document.querySelectorAll("nav")].map(
                (nav) => nav.querySelectorAll('[aria-current="page"]').length,
              ),
            ),
          ),
        )
        .toBe(1);
      // Y dentro de la navegación del expediente, exactamente una y la correcta.
      const dossierCurrent = page.locator(
        '.dossier-nav [aria-current="page"], .dossier-subnav [aria-current="page"]',
      );
      await expect(dossierCurrent).toHaveCount(1);
      await expect(dossierCurrent).toHaveAttribute(
        "data-testid",
        path ? `dossier-subnav-${path}` : "dossier-nav-summary",
      );
    }

    // 6. Atajos ask y settings
    await expect(page.getByTestId("dossier-ask-shortcut")).toHaveAttribute(
      "href",
      `${base}/ask`,
    );
    await page.getByTestId("dossier-ask-shortcut").click();
    await expect(page).toHaveURL(new RegExp(`${base}/ask`));

    await expect(page.getByTestId("dossier-settings-shortcut")).toHaveAttribute(
      "href",
      `${base}/settings`,
    );
    await page.getByTestId("dossier-settings-shortcut").click();
    await expect(page).toHaveURL(new RegExp(`${base}/settings`));
  });

  test("sin scroll horizontal del body a 1280 y 1440 en expediente", async ({
    page,
  }, testInfo) => {
    test.skip(
      testInfo.project.name === "mobile",
      "Anchos de escritorio 1280/1440.",
    );
    test.setTimeout(90_000);

    await loginOwner(page, testInfo);
    const base = await openFirstDossier(page);

    for (const width of [1280, 1440] as const) {
      await page.setViewportSize({ width, height: 900 });
      await page.goto(`${base}/procurement`);
      await expect(page.getByTestId("dossier-nav-surveillance")).toBeVisible();
      const metrics = await assertNoBodyHorizontalScroll(page);
      expect(
        metrics.ok,
        `body scrollWidth ${metrics.scrollWidth} <= innerWidth ${metrics.innerWidth} @ ${width}`,
      ).toBe(true);
    }
  });
});
