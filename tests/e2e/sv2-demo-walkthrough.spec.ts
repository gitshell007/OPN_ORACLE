/**
 * SV2-E2E-CAMINO — recorrido UI del guion de demo (oracle-dev).
 *
 * Orden del guion (GUION_DEMO_LUNES / SV2):
 *   1. Portada del expediente demo: análisis con confianza ≠ 0 y ≥1 hecho con fuente
 *   2. Entregables → Documentos: documento de la demo listado
 *   3. Preguntar: pregunta del guion, espera al contenido (≤90s), citas + datos clave
 *   4. Entregables → Informes: ≥1 informe ready y artefacto descargable
 *   5. En cada pantalla: sin scroll horizontal del body y una sola cabecera de página
 *
 * Conversaciones creadas se etiquetan title=`sv2-e2e` (vía rewrite del POST).
 *
 * Ejecución contra oracle-dev (un comando):
 *   bash scripts/run-sv2-demo-e2e.sh
 *
 * No hardcodea UUIDs de informes/documentos: los resuelve por rol en pantalla/API.
 * Fallos no se tragan con try/catch: la aserción deja la prueba en rojo.
 */
import { expect, test, type Page, type TestInfo } from "@playwright/test";

/** Marcadores del guion (texto de la respuesta esperada). */
const SCRIPT_QUESTION =
  "¿Quién es el administrador único y qué licitación pública tiene en curso Nexus Ibérica?";
const KEY_MARKERS = ["LIC-OATDA-2026-017", "2.400.000", "15 de abril"] as const;

/** Nombre visible del expediente demo (no el UUID). */
const DEMO_DOSSIER_NAME = /Nexus Ibérica/i;

/** Documentos de la demo en el listado (rol: fuente subida al expediente). */
const DEMO_DOCUMENT_NAME = /demo_document/i;

const CONV_TITLE = "sv2-e2e";

function requireEnv(name: string): string {
  const value = process.env[name]?.trim();
  if (!value) {
    throw new Error(
      `Falta ${name}. Usa scripts/run-sv2-demo-e2e.sh o exporta las credenciales del owner demo.`,
    );
  }
  return value;
}

async function assertLayoutInvariants(page: Page, screen: string) {
  const headers = page.locator('[data-testid="page-header"]');
  await expect(
    headers,
    `${screen}: debe existir exactamente una cabecera de página`,
  ).toHaveCount(1);

  const metrics = await page.evaluate(() => {
    const body = document.body;
    return {
      scrollWidth: body.scrollWidth,
      clientWidth: body.clientWidth,
      innerWidth: window.innerWidth,
    };
  });
  expect(
    metrics.scrollWidth <= metrics.innerWidth + 1,
    `${screen}: sin scroll horizontal del body (scrollWidth=${metrics.scrollWidth}, innerWidth=${metrics.innerWidth})`,
  ).toBe(true);
}

async function loginDemoOwner(page: Page) {
  const email = requireEnv("ORACLE_E2E_EMAIL");
  const password = requireEnv("ORACLE_E2E_PASSWORD");

  await page.goto("/login?next=%2Fapp%2Fdossiers");
  await page.getByLabel("Correo electrónico").fill(email);
  await page.getByLabel("Contraseña", { exact: true }).fill(password);
  await page.getByRole("button", { name: "Entrar en Oracle" }).click();

  // Un solo tenant: entra directo. Varios: selector de organización.
  const org = page.getByLabel("Organización");
  const dossiersHeading = page.getByRole("heading", { name: /Expedientes/i });
  await Promise.race([
    org.waitFor({ state: "visible", timeout: 20_000 }).then(async () => {
      const tenantLabel =
        process.env.ORACLE_E2E_TENANT_LABEL?.trim() || "SV2 Demo Tenant";
      await org.selectOption({ label: tenantLabel });
      await page.getByRole("button", { name: "Entrar en Oracle" }).click();
    }),
    page.waitForURL(/\/app(\/dossiers)?/, { timeout: 20_000 }),
    dossiersHeading.waitFor({ state: "visible", timeout: 20_000 }),
  ]);

  await expect(page).toHaveURL(/\/app/);
}

/**
 * Abre el expediente demo por su nombre en el listado (no por UUID).
 */
async function openDemoDossier(page: Page): Promise<string> {
  await page.goto("/app/dossiers");
  await expect(page.locator("main")).toBeVisible({ timeout: 20_000 });

  const link = page
    .getByRole("link", { name: DEMO_DOSSIER_NAME })
    .or(page.locator('a[href^="/app/dossiers/"]').filter({ hasText: DEMO_DOSSIER_NAME }))
    .first();
  await expect(link, "expediente demo visible en el listado").toBeVisible({
    timeout: 20_000,
  });

  const href = (await link.getAttribute("href")) ?? "";
  const match = href.match(/^(\/app\/dossiers\/[0-9a-f-]+)/i);
  expect(match, `href de expediente parseable: ${href}`).toBeTruthy();
  const base = match![1];

  await link.click();
  await expect(page).toHaveURL(new RegExp(`${base}/?$`));
  await expect(page.getByTestId("dossier-nav-summary")).toBeVisible({
    timeout: 20_000,
  });
  return base;
}

/**
 * Reescribe el título de conversaciones creadas por la UI a `sv2-e2e`
 * para no mezclarlas con las de la demo en vivo.
 */
async function tagConversationsAsE2E(page: Page) {
  await page.route("**/api/v1/dossiers/*/conversations", async (route) => {
    if (route.request().method() !== "POST") {
      await route.continue();
      return;
    }
    const raw = route.request().postData() ?? "{}";
    let body: Record<string, unknown> = {};
    try {
      body = JSON.parse(raw) as Record<string, unknown>;
    } catch {
      body = {};
    }
    await route.continue({
      postData: JSON.stringify({ ...body, title: CONV_TITLE }),
      headers: {
        ...route.request().headers(),
        "content-type": "application/json",
      },
    });
  });
}

test.describe("SV2-E2E-CAMINO demo walkthrough (oracle-dev UI)", () => {
  test("guion completo: portada → documentos → preguntar → informes + layout", async ({
    page,
  }, testInfo: TestInfo) => {
    test.skip(
      testInfo.project.name === "mobile",
      "El guion de demo se valida en desktop (viewport de presentación).",
    );
    // Login + 4 pantallas + Ask hasta 90s.
    test.setTimeout(180_000);

    await tagConversationsAsE2E(page);
    await loginDemoOwner(page);
    const dossierBase = await openDemoDossier(page);
    const dossierId = dossierBase.split("/").pop()!;

    // ── 1. Portada: análisis con confianza ≠ 0 y ≥1 hecho con fuente ──────
    await expect(page.getByRole("heading", { name: /Oráculo del expediente/i })).toBeVisible({
      timeout: 30_000,
    });
    await expect(page.getByText("Cargando análisis del expediente...")).toHaveCount(0, {
      timeout: 30_000,
    });

    const confidenceRow = page.locator("dl").filter({ hasText: "Confianza" }).first();
    await expect(confidenceRow).toBeVisible({ timeout: 20_000 });
    const confidenceText = await confidenceRow.locator("dd").first().innerText();
    const confidenceMatch = confidenceText.match(/(\d+)/);
    expect(confidenceMatch, `confianza parseable en «${confidenceText}»`).toBeTruthy();
    const confidence = Number(confidenceMatch![1]);
    expect(confidence, `confianza del análisis debe ser ≠ 0 (got ${confidence})`).toBeGreaterThan(
      0,
    );

    const factsBlock = page
      .locator("article")
      .filter({ has: page.getByRole("heading", { name: "Hechos confirmados" }) })
      .first();
    await expect(factsBlock).toBeVisible();
    const factItems = factsBlock.locator("li");
    await expect(factItems.first(), "al menos un hecho confirmado").toBeVisible();
    // Cada hecho con evidencia muestra «Fuente #xxxxxxxx»
    const factWithSource = factsBlock.locator("li").filter({ hasText: /Fuente #/ }).first();
    await expect(
      factWithSource,
      "al menos un hecho con su fuente (Fuente #…)",
    ).toBeVisible();

    await assertLayoutInvariants(page, "portada");

    // ── 2. Entregables → Documentos: documento de la demo listado ─────────
    await page.getByTestId("dossier-nav-deliverables").click();
    // Destino por defecto del grupo es Informes; ir a Documentos por subnav o URL de rol.
    const docsSubnav = page.getByTestId("dossier-subnav-documents");
    if (await docsSubnav.count()) {
      await docsSubnav.click();
    } else {
      await page.goto(`${dossierBase}/documents`);
    }
    await expect(page).toHaveURL(new RegExp(`${dossierBase}/documents`));
    await expect(page.getByTestId("page-header")).toContainText(/Documentos/i);

    // Espera a la tabla / lista; el documento demo se identifica por nombre, no por id.
    await expect(page.getByText(DEMO_DOCUMENT_NAME).first()).toBeVisible({
      timeout: 20_000,
    });
    await assertLayoutInvariants(page, "documentos");

    // ── 3. Preguntar: pregunta del guion, contenido ≤90s, citas + claves ──
    await page.getByTestId("dossier-ask-shortcut").click();
    await expect(page).toHaveURL(new RegExp(`${dossierBase}/ask`));
    await expect(page.getByTestId("page-header")).toContainText(/Preguntar/i);
    await assertLayoutInvariants(page, "preguntar (antes)");

    // Si rehidrata una conversación previa, el textarea sigue siendo usable.
    const questionField = page.getByLabel("Tu pregunta");
    await expect(questionField).toBeVisible({ timeout: 20_000 });
    await questionField.fill(SCRIPT_QUESTION);

    const createConvPromise = page.waitForResponse(
      (res) =>
        res.request().method() === "POST" &&
        /\/api\/v1\/dossiers\/[^/]+\/conversations$/.test(res.url()) &&
        res.status() < 500,
      { timeout: 30_000 },
    );

    await page.getByRole("button", { name: /Enviar pregunta/i }).click();

    // Etiqueta sv2-e2e: el body reescrito debe llegar al servidor (o reutilizar sesión).
    const createResp = await createConvPromise.catch(() => null);
    if (createResp) {
      const reqBody = createResp.request().postData() ?? "";
      expect(reqBody, "conversación etiquetada sv2-e2e").toContain(CONV_TITLE);
    }

    // Espera al contenido de la respuesta (no a un sleep fijo). Hasta 90 s.
    const answerBlock = page.locator("pre.answer-block");
    await expect(answerBlock, "respuesta visible en ≤90s").toBeVisible({
      timeout: 90_000,
    });
    // Estado succeeded (si sigue en queued/running no hay pre con texto útil estable).
    await expect(page.getByText(/Estado:\s*succeeded/i)).toBeVisible({
      timeout: 5_000,
    });

    const answerText = await answerBlock.innerText();
    for (const marker of KEY_MARKERS) {
      expect(
        answerText,
        `la respuesta debe contener el dato clave «${marker}»`,
      ).toContain(marker);
    }

    // Citas visibles: lista .citation-list con al menos un .citation-link
    const citationList = page.locator("ul.citation-list");
    await expect(citationList, "bloque de citas visible").toBeVisible();
    const citationLinks = citationList.locator("a.citation-link");
    await expect(
      citationLinks.first(),
      "al menos una cita visible; si no hay citas la prueba debe ponerse roja",
    ).toBeVisible();
    const citationCount = await citationLinks.count();
    expect(citationCount, "citas count > 0").toBeGreaterThan(0);

    await assertLayoutInvariants(page, "preguntar (después)");

    // ── 4. Entregables → Informes: ready + artefacto descargable ──────────
    // Captura el listado de informes para resolver el ready por rol (status), no por UUID.
    const reportsListPromise = page.waitForResponse(
      (res) =>
        res.request().method() === "GET" &&
        /\/api\/v1\/dossiers\/[^/]+\/reports(\?|$)/.test(res.url()) &&
        res.status() === 200,
      { timeout: 30_000 },
    );

    await page.getByTestId("dossier-nav-deliverables").click();
    // Grupo Entregables default → reports; forzar subnav por si la ruta residual es otra.
    const reportsSubnav = page.getByTestId("dossier-subnav-reports");
    if (await reportsSubnav.count()) {
      await reportsSubnav.click();
    } else if (!page.url().includes("/reports")) {
      await page.goto(`${dossierBase}/reports`);
    }

    await expect(page).toHaveURL(new RegExp(`${dossierBase}/reports`));
    await expect(page.getByTestId("page-header")).toContainText(/Informes/i);

    const reportsResponse = await reportsListPromise;
    const reportsPayload = (await reportsResponse.json()) as {
      data?: Array<{ id: string; status: string; title?: string }>;
      items?: Array<{ id: string; status: string; title?: string }>;
    };
    const reports = reportsPayload.data ?? reportsPayload.items ?? [];
    const readyReports = reports.filter((r) => r.status === "ready");
    expect(
      readyReports.length,
      "API del listado: al menos un informe status=ready",
    ).toBeGreaterThan(0);

    // UI: badge de estado ready = «Listo para revisar»
    const readyRow = page
      .locator("tr.interactive-row")
      .filter({ hasText: /Listo para revisar/i })
      .first();
    await expect(
      readyRow,
      "fila de informe ready visible en Entregables → Informes",
    ).toBeVisible({ timeout: 20_000 });

    // Abre el detalle (papel del informe ready en la pantalla).
    await readyRow.click();
    // Drawer / visor del informe
    await expect(
      page.locator(".report-viewer, [role='dialog']").first(),
    ).toBeVisible({ timeout: 15_000 });

    const readyId = readyReports[0].id;

    // Descarga del artefacto del informe ready.
    // Los informes custom_assistant exponen el artefacto en
    // GET …/reports/custom/{id}/download (downloadable=true), no en artifacts[] del drawer clásico.
    // Comprobamos desde el contexto autenticado del browser (misma sesión que la UI).
    const downloadUrl = `/api/v1/dossiers/${dossierId}/reports/custom/${readyId}/download`;
    const downloadResponse = await page.request.get(downloadUrl);
    expect(
      downloadResponse.ok(),
      `artefacto del informe ready descargable HTTP ${downloadResponse.status()} (${downloadUrl})`,
    ).toBe(true);
    const body = await downloadResponse.body();
    expect(
      body.byteLength,
      "artefacto no vacío",
    ).toBeGreaterThan(100);

    // Cierra drawer si aplica y revalida layout de la lista de informes.
    await page.keyboard.press("Escape");
    await assertLayoutInvariants(page, "informes");
  });
});
