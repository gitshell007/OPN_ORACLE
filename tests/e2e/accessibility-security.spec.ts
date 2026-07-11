import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page, type TestInfo } from "@playwright/test";

const WCAG_TAGS = [
  "wcag2a",
  "wcag2aa",
  "wcag21a",
  "wcag21aa",
  "wcag22aa",
];

async function loginOwner(page: Page, testInfo: TestInfo) {
  const keyboard = testInfo.title.includes("teclado");
  const reload = testInfo.title.includes("recargas completas");
  const suffix = testInfo.project.name === "mobile"
    ? keyboard ? "94" : reload ? "96" : "92"
    : keyboard ? "93" : reload ? "95" : "91";
  await page.setExtraHTTPHeaders({ "X-Forwarded-For": `198.51.100.${suffix}` });
  await page.goto("/login?next=%2Fapp");
  await page.getByLabel("Correo electrónico").fill("owner@oracle-e2e.test");
  await page.getByLabel("Contraseña", { exact: true }).fill("Oracle E2E segura 2026");
  await page.getByRole("button", { name: "Entrar en Oracle" }).click();
  await expect(page.getByLabel("Organización")).toBeVisible();
  await page.getByLabel("Organización").selectOption({ label: "Asterion E2E" });
  await page.getByRole("button", { name: "Entrar en Oracle" }).click();
  await expect(page).toHaveURL(/\/app$/);
}

async function expectWcagAA(page: Page, route: string) {
  const result = await new AxeBuilder({ page }).withTags(WCAG_TAGS).analyze();
  const violations = result.violations.map((violation) => ({
    id: violation.id,
    impact: violation.impact,
    help: violation.help,
    targets: violation.nodes.map((node) => node.target.join(" ")),
  }));
  expect(violations, `Violaciones WCAG automáticas en ${route}`).toEqual([]);
}

async function navigateWithPalette(page: Page, label: string, route: string) {
  await page.keyboard.press("ControlOrMeta+k");
  const palette = page.getByRole("dialog", { name: "Comandos de Oracle" });
  await expect(palette).toBeVisible();
  await palette.getByRole("button", { name: new RegExp(`^Ir a ${label}`) }).click();
  await expect(page).toHaveURL(new RegExp(`${route.replaceAll("/", "\\/")}$`));
}

test("F13 publica cabeceras defensivas y no cachea superficies sensibles", async ({
  request,
}) => {
  for (const route of ["/login", "/forgot-password", "/app", "/platform/tenants"]) {
    const response = await request.get(route);
    const headers = response.headers();

    expect(headers["x-content-type-options"], route).toBe("nosniff");
    expect(headers["x-frame-options"], route).toBe("DENY");
    expect(headers["referrer-policy"], route).toBe("strict-origin-when-cross-origin");
    expect(headers["permissions-policy"], route).toContain("camera=()");
    expect(headers["x-powered-by"], route).toBeUndefined();
    // Next dev enforces revalidation globally; production is verified against
    // the force-dynamic/no-store policy in the production smoke.
    expect(headers["cache-control"], route).toMatch(/no-store|no-cache/);
    // HSTS must be emitted by the TLS edge only after HTTPS is validated.
    expect(headers["strict-transport-security"], route).toBeUndefined();
  }
});

test("F13 recorre rutas productivas sin violaciones WCAG ni errores de consola", async ({
  page,
}, testInfo) => {
  test.setTimeout(90_000);
  const consoleErrors: string[] = [];
  const pageErrors: string[] = [];
  page.on("console", (message) => {
    if (message.type() === "error") consoleErrors.push(message.text());
  });
  page.on("pageerror", (error) => pageErrors.push(error.message));

  await page.goto("/login");
  await expect(page.getByRole("heading", { name: "Bienvenido a Oracle" })).toBeVisible();
  await expectWcagAA(page, "/login");

  await loginOwner(page, testInfo);
  // Chromium can emit the expected anonymous /auth/me 401 one task after the
  // successful navigation; start the product-console gate after it settles.
  await page.waitForTimeout(150);
  consoleErrors.length = 0;
  pageErrors.length = 0;

  await expectWcagAA(page, "/app");
  const routes = [
    ["Expedientes", "/app/dossiers"],
    ["Señales", "/app/signals"],
    ["Oportunidades", "/app/opportunities"],
    ["Riesgos", "/app/risks"],
    ["Tareas", "/app/tasks"],
    ["Qué ha cambiado", "/app/changes"],
    ["Informes", "/app/reports"],
  ] as const;
  let dossierHref = "";
  for (const [label, route] of routes) {
    await navigateWithPalette(page, label, route);
    await expect(page.locator("main")).toBeVisible();
    await expect(page.getByRole("heading").first()).toBeVisible();
    if (route === "/app/dossiers") {
      dossierHref =
        (await page.locator('a[href^="/app/dossiers/"]').first().getAttribute("href")) ?? "";
    }
    await expectWcagAA(page, route);
  }

  expect(dossierHref).toMatch(/^\/app\/dossiers\/[0-9a-f-]+$/);
  await navigateWithPalette(page, "Expedientes", "/app/dossiers");
  await page.locator(`a[href="${dossierHref}"]`).first().evaluate((element: HTMLElement) => element.click());
  await expect(page).toHaveURL(new RegExp(`${dossierHref.replaceAll("/", "\\/")}$`));
  await expectWcagAA(page, dossierHref);
  for (const suffix of ["", "/signals", "/documents", "/settings"]) {
    const route = `${dossierHref}${suffix}`;
    if (suffix) {
      await page.locator(`a[href="${route}"]`).first().evaluate((element: HTMLElement) => element.click());
      await expect(page).toHaveURL(new RegExp(`${route.replaceAll("/", "\\/")}$`));
    }
    await expect(page.locator("main")).toBeVisible();
    await expect(page.getByRole("heading").first()).toBeVisible();
    await expectWcagAA(page, route);
  }

  expect(pageErrors).toEqual([]);
  expect(consoleErrors).toEqual([]);
});

test("F13 conserva navegación completa por teclado y restaura el foco", async ({
  page,
}, testInfo) => {
  await loginOwner(page, testInfo);
  await page.evaluate(() => (document.activeElement as HTMLElement | null)?.blur());
  await page.keyboard.press("Tab");
  await expect(page.getByRole("link", { name: "Saltar al contenido principal" })).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(page.locator("#main-content")).toBeFocused();

  await page.keyboard.press("ControlOrMeta+k");
  const palette = page.getByRole("dialog", { name: "Comandos de Oracle" });
  await expect(palette).toBeVisible();
  await expect(palette.getByRole("textbox", { name: "Buscar" })).toBeFocused();
  for (let index = 0; index < 8; index += 1) await page.keyboard.press("Tab");
  await expect(palette).toContainText("Ir a");
  expect(await palette.evaluate((element) => element.contains(document.activeElement))).toBe(true);
  await page.keyboard.press("Escape");
  await expect(palette).toBeHidden();
  await expect(page.getByRole("button", { name: "Abrir búsqueda global" })).toBeFocused();

  if (testInfo.project.name === "mobile") {
    const trigger = page.getByRole("button", { name: "Abrir navegación" });
    await trigger.click();
    await expect(page.getByRole("button", { name: "Cerrar navegación" }).first()).toBeFocused();
    await page.keyboard.press("Escape");
    await expect(trigger).toBeFocused();
  }
});

test("F13 la sesión sobrevive tres recargas completas consecutivas", async ({
  page,
}, testInfo) => {
  test.skip(testInfo.project.name === "mobile", "La invariancia de sesión se comprueba una vez en escritorio.");
  await loginOwner(page, testInfo);

  for (const route of ["/app", "/app/dossiers", "/app/signals"]) {
    const identityResponse = page.waitForResponse(
      (response) => response.url().endsWith("/api/v1/auth/me"),
    );
    await page.goto(route);
    const response = await identityResponse;
    const problem = (await response.json()) as { code?: string };
    expect(response.status(), `${route}: ${problem.code ?? "sin código"}`).toBe(200);
    await expect(page).toHaveURL(new RegExp(`${route.replaceAll("/", "\\/")}$`));
  }
});
