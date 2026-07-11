import { expect, test, type Page } from "@playwright/test";

async function loginOwner(page: Page, next = "/app/dossiers") {
  await page.setExtraHTTPHeaders({ "X-Forwarded-For": "198.51.100.12" });
  await page.goto(`/login?next=${encodeURIComponent(next)}`);
  await page.getByLabel("Correo electrónico").fill("owner@oracle-e2e.test");
  await page.getByLabel("Contraseña", { exact: true }).fill("Oracle E2E segura 2026");
  await page.getByRole("button", { name: "Entrar en Oracle" }).click();
  await expect(page.getByLabel("Organización")).toBeVisible();
  await page.getByLabel("Organización").selectOption({ label: "Asterion E2E" });
  await page.getByRole("button", { name: "Entrar en Oracle" }).click();
  await expect(page).toHaveURL(new RegExp(next.replaceAll("/", "\\/")));
}

test("F12 recorre inteligencia, ejecución, documentos y configuración contra Flask", async ({ page }, testInfo) => {
  test.setTimeout(60_000);
  test.skip(testInfo.project.name === "mobile", "Las mutaciones F12 se ejercitan una vez en escritorio.");
  await loginOwner(page);
  await expect(page.getByRole("heading", { name: "Expedientes", exact: true })).toBeVisible();
  await page.getByText("Expansión regional", { exact: true }).first().click();
  await expect(page.getByRole("heading", { name: "Expansión regional" })).toBeVisible();
  const dossierUrl = page.url();

  await page.goto(`${dossierUrl}/signals`);
  await expect(page.getByRole("heading", { name: "Señales" })).toBeVisible();
  await page.getByRole("button", { name: /Inspeccionar/ }).first().click();
  await page.getByRole("button", { name: "Marcar revisada" }).click();
  await page.getByRole("dialog", { name: "Confirmar revisión" }).getByRole("button", { name: "Confirmar" }).click();
  await expect(page.getByText("Señal revisada")).toBeVisible();
  await page.getByRole("button", { name: /Inspeccionar/ }).first().click();
  await page.getByRole("button", { name: "Promover" }).click();
  const promotion = page.getByRole("dialog", { name: "Promover señal" });
  await promotion.getByLabel("Título").fill("Oportunidad promovida E2E");
  await promotion.getByRole("button", { name: "Crear recurso" }).click();
  await expect(page.getByText("Oportunidad creada")).toBeVisible();

  await page.goto(`${dossierUrl}/opportunities`);
  await page.getByRole("button", { name: /Inspeccionar/ }).first().click();
  const opportunityDrawer = page.getByRole("dialog", { name: /.+/ }).last();
  await opportunityDrawer.getByLabel("Siguiente estado permitido").selectOption("qualified");
  await opportunityDrawer.getByRole("button", { name: "Actualizar estado" }).click();
  await page.getByRole("dialog", { name: "Confirmar cambio de estado" }).getByRole("button", { name: "Confirmar" }).click();
  await expect(page.getByText("Estado actualizado")).toBeVisible();

  await page.goto("/app/dossiers");
  await page.getByText("Alianza tecnológica", { exact: true }).first().click();
  await expect(page.getByRole("heading", { name: "Alianza tecnológica" })).toBeVisible();
  const riskDossierUrl = page.url();
  await page.goto(`${riskDossierUrl}/risks`);
  await page.getByRole("button", { name: /Inspeccionar/ }).first().click();
  const riskDrawer = page.getByRole("dialog", { name: /.+/ }).last();
  await riskDrawer.getByLabel("Siguiente estado permitido").selectOption("monitoring");
  await riskDrawer.getByRole("button", { name: "Actualizar estado" }).click();
  await page.getByRole("dialog", { name: "Confirmar cambio de estado" }).getByRole("button", { name: "Confirmar" }).click();
  await expect(page.getByText("Estado actualizado")).toBeVisible();

  await page.goto(`${dossierUrl}/actors`);
  await page.getByRole("button", { name: "Vincular actor" }).click();
  const actorDialog = page.getByRole("dialog", { name: "Vincular actor" });
  const actorSelect = actorDialog.getByLabel("Actor existente");
  await expect.poll(() => actorSelect.locator("option").count()).toBeGreaterThan(1);
  const actorOptions = await actorSelect.locator("option").allTextContents();
  await actorSelect.selectOption({ label: actorOptions.at(-1) });
  await actorDialog.getByLabel("Roles (separados por comas)").fill("socio potencial");
  await actorDialog.getByRole("button", { name: "Guardar" }).click();
  await expect(page.getByText("Actor vinculado")).toBeVisible();

  await page.goto(`${dossierUrl}/meetings`);
  await page.getByRole("link", { name: "Abrir", exact: true }).first().click();
  await page.getByRole("button", { name: "Preparar briefing" }).click();
  await expect(page.getByText("Estructura de briefing creada")).toBeVisible();

  await page.goto(`${dossierUrl}/tasks`);
  await page.getByRole("link", { name: "Abrir", exact: true }).first().click();
  await page.getByRole("button", { name: "En curso" }).click();
  await expect(page.getByText(/Estado actualizado/)).toBeVisible();

  await page.goto(`${dossierUrl}/documents`);
  await page.locator('input[type="file"]').setInputFiles({
    name: "fuente-e2e.txt",
    mimeType: "text/plain",
    buffer: Buffer.from("Evidencia E2E verificable para el expediente."),
  });
  await expect(page.getByText("Documento recibido")).toBeVisible();
  await expect(page.getByText("fuente-e2e.txt").first()).toBeVisible();

  await page.goto(`${dossierUrl}/settings`);
  await expect(page.getByRole("heading", { name: "Configuración" })).toBeVisible();
  await page.getByLabel("Objetivo estratégico").fill("Objetivo actualizado por la regresión F12");
  await page.getByRole("button", { name: "Guardar cambios" }).click();
  await expect(page.getByText("Expediente actualizado")).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath("phase12-settings-1440.png"), fullPage: true });
  for (const viewport of [{ width: 1280, height: 800 }, { width: 1024, height: 768 }]) {
    await page.setViewportSize(viewport);
    await page.goto("/app/dossiers");
    await expect(page.getByRole("heading", { name: "Expedientes", exact: true })).toBeVisible();
    await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true);
  }
});

test("F12 mantiene inventarios y contexto sin overflow en móvil", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "mobile", "Validación responsive específica.");
  await loginOwner(page, "/app/signals");
  await expect(page.getByRole("heading", { name: "Señales" })).toBeVisible();
  for (const [path, heading] of [["/app/signals", "Señales"], ["/app/opportunities", "Oportunidades"], ["/app/risks", "Riesgos"], ["/app/actors", "Actores"], ["/app/changes", "Qué ha cambiado"]] as const) {
    await page.goto(path);
    await expect(page.getByRole("heading", { name: heading, exact: true })).toBeVisible();
    await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true);
  }
  await expect(page.getByText("Priorizando cambios…")).not.toBeVisible();
  await page.screenshot({ path: testInfo.outputPath("phase12-changes-mobile.png"), fullPage: true });
});
