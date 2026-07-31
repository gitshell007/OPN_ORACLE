/**
 * MEMSOL browser residual: Actividad, Preguntar a Oracle, Informe libre.
 * Real login + HTTP against the auth E2E stack (APP_ENV=test → Celery eager).
 * Does not mock section components. Cancel/retry are not exposed in UI (residual).
 */
import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page, type TestInfo } from "@playwright/test";

const PASSWORD = "Oracle E2E segura 2026";
const OWNER = "owner@oracle-e2e.test";
const VIEWER = "viewer@oracle-e2e.test";

const WCAG_TAGS = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"];

type WcagFinding = {
  id: string;
  impact: string | null | undefined;
  help: string;
  target: string;
};

function isKnownWcagDebt(route: string, finding: WcagFinding): boolean {
  if (
    /^\/app\/dossiers\/[0-9a-f-]+(?:\/.*)?$/.test(route) &&
    finding.id === "color-contrast"
  ) {
    return (
      finding.target === "summary" ||
      /^\.account-tabs > a:nth-child\(\d+\)$/.test(finding.target) ||
      /^\.dossier-tab-secondary:nth-child\(\d+\)$/.test(finding.target)
    );
  }
  return (
    /^\/app\/dossiers\/[0-9a-f-]+(?:\/.*)?$/.test(route) &&
    finding.id === "target-size" &&
    finding.target === ".back-link"
  );
}

async function expectWcagAA(page: Page, route: string) {
  await expect(page).toHaveTitle(/\S/);
  const result = await new AxeBuilder({ page }).withTags(WCAG_TAGS).analyze();
  const violations: WcagFinding[] = result.violations
    .flatMap((violation) =>
      violation.nodes.map((node) => ({
        id: violation.id,
        impact: violation.impact,
        help: violation.help,
        target: node.target.join(" "),
      })),
    )
    .filter((violation) => !isKnownWcagDebt(route, violation));
  expect(violations, `Violaciones WCAG automáticas en ${route}`).toEqual([]);
}

/** Stable unique client IP so login rate limits do not collide across tests. */
function clientIp(testInfo: TestInfo, salt: number): string {
  const hash = [...testInfo.title].reduce((acc, ch) => acc + ch.charCodeAt(0), 0);
  const octet = 10 + ((hash + salt) % 200);
  return `198.51.100.${octet}`;
}

async function loginAs(
  page: Page,
  email: string,
  orgLabel: string | null,
  testInfo: TestInfo,
  salt = 0,
) {
  await page.setExtraHTTPHeaders({ "X-Forwarded-For": clientIp(testInfo, salt) });
  await page.goto("/login?next=%2Fapp");
  await page.getByLabel("Correo electrónico").fill(email);
  await page.getByLabel("Contraseña", { exact: true }).fill(PASSWORD);
  await page.getByRole("button", { name: "Entrar en Oracle" }).click();
  const org = page.getByLabel("Organización");
  // Multi-tenant shows org picker; single-tenant (viewer) may land on /app directly.
  const landedOnApp = await page
    .waitForURL(/\/app(\/|$)/, { timeout: 4000 })
    .then(() => true)
    .catch(() => false);
  if (!landedOnApp) {
    await expect(org).toBeVisible({ timeout: 15000 });
    if (orgLabel) {
      await org.selectOption({ label: orgLabel });
    } else {
      await org.selectOption({ index: 0 });
    }
    await page.getByRole("button", { name: "Entrar en Oracle" }).click();
    await expect(page).toHaveURL(/\/app(\/|$)/, { timeout: 20000 });
  }
}

async function createDossier(page: Page, title: string): Promise<string> {
  await page.goto("/app");
  await expect(page.getByRole("button", { name: "Crear", exact: true })).toBeVisible({
    timeout: 20000,
  });
  await page.getByRole("button", { name: "Crear", exact: true }).click();
  await page.getByRole("menuitem", { name: "Nuevo expediente" }).click();
  const createDialog = page.getByRole("dialog", { name: "Nuevo expediente" });
  await createDialog.getByLabel("Nombre").fill(title);
  await createDialog
    .getByLabel("Objetivo estratégico")
    .fill("E2E MEMSOL browser residual — sin proveedores de pago");
  await createDialog.getByRole("button", { name: "Crear expediente" }).click();
  await expect(page).toHaveURL(/\/app\/dossiers\/[0-9a-f-]+$/, { timeout: 20000 });
  const match = page.url().match(/\/app\/dossiers\/([0-9a-f-]+)/);
  expect(match?.[1]).toBeTruthy();
  return match![1];
}

test.describe("MEMSOL dossier tabs (Actividad / Preguntar / Informe libre)", () => {
  test.describe.configure({ timeout: 120_000 });

  test("Actividad, Preguntar e Informe libre: carga, estados, poll, recarga, a11y y consola", async ({
    page,
  }, testInfo) => {
    test.skip(
      testInfo.project.name === "mobile",
      "Flujos MEMSOL durables se validan en escritorio.",
    );
    const consoleErrors: string[] = [];
    const pageErrors: string[] = [];
    page.on("console", (message) => {
      if (message.type() === "error") consoleErrors.push(message.text());
    });
    page.on("pageerror", (error) => pageErrors.push(error.message));

    await loginAs(page, OWNER, "Asterion E2E", testInfo, 1);
    consoleErrors.length = 0;
    pageErrors.length = 0;

    const title = `MEMSOL browser ${Date.now()}`;
    const dossierId = await createDossier(page, title);

    // --- Actividad: real load (seed/create may attach default watchlist) ---
    await page.goto(`/app/dossiers/${dossierId}/activity`);
    await expect(
      page.getByRole("heading", { name: "Actividad del expediente" }),
    ).toBeVisible({ timeout: 20000 });
    await expect(page.getByRole("region", { name: "Resumen de actividad" })).toBeVisible();
    // Empty OR populated are both valid product states after create.
    const empty = page.getByText("No hay vigilancias ni trabajos en este expediente.");
    const list = page.getByRole("region", { name: "Listado de actividad" });
    await expect(empty.or(list.getByRole("table"))).toBeVisible({ timeout: 10000 });

    // Force empty state via real section render path (HTTP response only).
    await page.route(`**/api/v1/dossiers/${dossierId}/activity**`, async (route) => {
      if (route.request().method() === "GET") {
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({
            dossier_id: dossierId,
            items: [],
            summary: { total: 0, by_state: {} },
            intent: null,
          }),
        });
        return;
      }
      await route.continue();
    });
    await page.getByRole("button", { name: /Actualizar/i }).click();
    await expect(empty).toBeVisible({ timeout: 15000 });
    await page.unroute(`**/api/v1/dossiers/${dossierId}/activity**`);

    // Error state: unknown dossier id → API problem → alert UI
    const missingId = "00000000-0000-4000-8000-000000000099";
    await page.goto(`/app/dossiers/${missingId}/activity`);
    await expect(page.getByText("Actividad no disponible")).toBeVisible({
      timeout: 20000,
    });
    await expect(page.getByRole("button", { name: /Reintentar/i })).toBeVisible();

    await page.goto(`/app/dossiers/${dossierId}/activity`);
    await expect(
      page.getByRole("heading", { name: "Actividad del expediente" }),
    ).toBeVisible({ timeout: 20000 });
    await expectWcagAA(page, `/app/dossiers/${dossierId}/activity`);

    // --- Preguntar ---
    await page.goto(`/app/dossiers/${dossierId}/ask`);
    await expect(
      page.getByRole("heading", { name: "Preguntar a Oracle" }),
    ).toBeVisible({ timeout: 20000 });

    const askResponsePromise = page.waitForResponse(
      (response) =>
        response.url().includes(`/api/v1/dossiers/${dossierId}/conversations/`) &&
        response.url().includes("/messages") &&
        response.request().method() === "POST",
      { timeout: 30000 },
    );
    await page
      .getByLabel("Tu pregunta")
      .fill("¿Hay cobertura suficiente en el expediente? (MEMSOL e2e browser)");
    await page.getByRole("button", { name: "Enviar pregunta" }).click();
    const askResponse = await askResponsePromise;
    expect(askResponse.status(), "enqueue message must be 202").toBe(202);
    const askBody = (await askResponse.json()) as {
      message_id: string;
      job_id: string;
    };
    expect(askBody.message_id).toBeTruthy();
    expect(askBody.job_id).toBeTruthy();

    await expect(page.getByText(/Estado:\s*(queued|running|succeeded)/)).toBeVisible({
      timeout: 30000,
    });
    await expect(page.getByText(/Estado:\s*succeeded/)).toBeVisible({
      timeout: 45000,
    });
    await expect(page.locator("strong", { hasText: "Respuesta" })).toBeVisible();
    await expect(page.locator("pre.answer-block")).toBeVisible();

    await page.reload();
    await expect(
      page.getByRole("heading", { name: "Preguntar a Oracle" }),
    ).toBeVisible({ timeout: 20000 });
    await expect(page.getByText(/Estado:\s*succeeded/)).toBeVisible({
      timeout: 30000,
    });
    await expect(
      page.getByText(/cobertura suficiente en el expediente/i),
    ).toBeVisible();
    await expectWcagAA(page, `/app/dossiers/${dossierId}/ask`);
    // Cancel/retry not in UI — residual only (Actualizar present).
    await expect(page.getByRole("button", { name: /Actualizar/i })).toBeVisible();

    // --- Informe libre ---
    await page.goto(`/app/dossiers/${dossierId}/custom-brief`);
    await expect(page.getByRole("heading", { name: "Informe libre" })).toBeVisible({
      timeout: 20000,
    });

    const briefResponsePromise = page.waitForResponse(
      (response) =>
        response.url().includes(`/api/v1/dossiers/${dossierId}/reports/custom`) &&
        response.request().method() === "POST" &&
        !/\/custom\/[0-9a-f-]+$/.test(response.url()),
      { timeout: 30000 },
    );
    await page
      .getByLabel("Encargo del informe")
      .fill(
        "Informe libre E2E: posicionamiento competitivo del expediente sintético MEMSOL.",
      );
    await page.getByRole("button", { name: "Crear brief y planificar" }).click();
    const briefResponse = await briefResponsePromise;
    expect(briefResponse.status(), "custom brief create must be 202").toBe(202);
    const briefBody = (await briefResponse.json()) as {
      report_id: string;
      job_id: string;
    };
    expect(briefBody.report_id).toBeTruthy();
    expect(briefBody.job_id).toBeTruthy();

    await expect(page.getByRole("heading", { name: "Estado del brief" })).toBeVisible();
    await expect(
      page.getByText(/Plan propuesto \(revisar\)|Borrador \/ planificando/),
    ).toBeVisible({ timeout: 30000 });
    await expect(page.getByText("Plan propuesto (revisar)")).toBeVisible({
      timeout: 45000,
    });
    await expect(page.getByText("Secciones propuestas")).toBeVisible();

    await page.reload();
    await expect(page.getByRole("heading", { name: "Informe libre" })).toBeVisible({
      timeout: 20000,
    });
    await expect(page.getByText("Plan propuesto (revisar)")).toBeVisible({
      timeout: 30000,
    });
    await expect(page.getByText(/posicionamiento competitivo/i)).toBeVisible();
    await expectWcagAA(page, `/app/dossiers/${dossierId}/custom-brief`);

    // Error path: abort POST → alert from real component catch
    await page.route("**/api/v1/dossiers/*/reports/custom", async (route) => {
      if (route.request().method() === "POST") {
        await route.abort("failed");
        return;
      }
      await route.continue();
    });
    await page
      .getByLabel("Encargo del informe")
      .fill("Segundo encargo para forzar error de red en el POST E2E.");
    await page.getByRole("button", { name: "Crear brief y planificar" }).click();
    await expect(
      page.getByRole("alert").filter({
        hasText: /No se pudo crear el informe personalizado|falló|error|Failed|network/i,
      }),
    ).toBeVisible({ timeout: 15000 });
    await page.unroute("**/api/v1/dossiers/*/reports/custom");

    const relevantConsole = consoleErrors.filter(
      (text) =>
        !/favicon|Download the React DevTools|\[HMR\]|hydration|Failed to load resource|net::ERR/i.test(
          text,
        ),
    );
    expect(pageErrors, `pageerror: ${pageErrors.join(" | ")}`).toEqual([]);
    expect(
      relevantConsole,
      `console errors: ${relevantConsole.join(" | ")}`,
    ).toEqual([]);
  });

  test("permiso negativo: viewer no entra en Preguntar (ai.execute)", async ({
    page,
  }, testInfo) => {
    test.skip(
      testInfo.project.name === "mobile",
      "Permisos MEMSOL se cubren en escritorio.",
    );
    // Owner creates a dossier the viewer can open (dossier.read) but not ask (needs ai.execute).
    await loginAs(page, OWNER, "Asterion E2E", testInfo, 2);
    const dossierId = await createDossier(page, `MEMSOL viewer gate ${Date.now()}`);
    await page.getByRole("button", { name: /Olivia Owner/ }).click();
    await page.getByRole("menuitem", { name: "Cerrar sesión" }).click();
    await expect(page).toHaveURL(/\/login/, { timeout: 15000 });

    await loginAs(page, VIEWER, null, testInfo, 4);
    await page.goto(`/app/dossiers/${dossierId}/ask`);
    await expect(
      page.getByRole("heading", { name: "Acceso restringido" }),
    ).toBeVisible({ timeout: 20000 });
    await expect(
      page.getByText(/no dispone del permiso necesario/i),
    ).toBeVisible();
    await expect(page.getByRole("heading", { name: "Preguntar a Oracle" })).toHaveCount(
      0,
    );
    await expect(page.getByLabel("Tu pregunta")).toHaveCount(0);
  });

  test("tenant negativo: UUID ajeno en Actividad no filtra contenido extranjero", async ({
    page,
  }, testInfo) => {
    test.skip(
      testInfo.project.name === "mobile",
      "Aislamiento MEMSOL se cubre en escritorio.",
    );
    await loginAs(page, OWNER, "Asterion E2E", testInfo, 3);
    const foreign = "11111111-1111-4111-8111-111111111111";
    await page.goto(`/app/dossiers/${foreign}/activity`);
    await expect(page.getByText("Actividad no disponible")).toBeVisible({
      timeout: 20000,
    });
    await expect(page.getByText("Expediente E2E canónico")).toHaveCount(0);
    // No foreign dossier title from another tenant should appear as success content
    await expect(page.getByRole("heading", { name: "Actividad del expediente" })).toHaveCount(
      0,
    );
  });

  test("Preguntar: Cancelar y Reintentar en JobProgress (If-Match) + historial", async ({
    page,
  }, testInfo) => {
    test.skip(
      testInfo.project.name === "mobile",
      "Controles de job MEMSOL se cubren en escritorio.",
    );
    await loginAs(page, OWNER, "Asterion E2E", testInfo, 5);
    const dossierId = await createDossier(page, `MEMSOL cancel-retry ${Date.now()}`);
    const questionText = "Pregunta controlada para cancel/retry E2E";

    // Eager settles jobs in ms; stub GET job state so Cancelar is visible, then
    // POST cancel/retry hit real UI handlers (versioned). Real lifecycle proven
    // by unit tests of request_cancel/prepare_retry + prior Dev worker smoke.
    let jobId = "pending";
    let jobVersion = 1;
    let jobStatus: "queued" | "cancelled" | "failed" | "queued_retry" = "queued";

    await page.route("**/api/v1/jobs/**", async (route) => {
      const req = route.request();
      const url = req.url();
      const idMatch = url.match(/\/api\/v1\/jobs\/([0-9a-f-]+)/i);
      const id = idMatch?.[1] ?? jobId;
      if (req.method() === "GET" && !url.includes("/cancel") && !url.includes("/retry")) {
        const status =
          jobStatus === "queued_retry"
            ? "queued"
            : jobStatus === "cancelled"
              ? "cancelled"
              : jobStatus === "failed"
                ? "failed"
                : "queued";
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          headers: { ETag: `W/"${jobVersion}"` },
          body: JSON.stringify({
            id,
            tenant_id: "00000000-0000-4000-8000-000000000001",
            job_type: "oracle.dossier_question.answer",
            queue: "ai",
            status,
            progress: status === "queued" || status === "queued_retry" ? 0 : 100,
            stage:
              status === "cancelled"
                ? "cancelled"
                : status === "failed"
                  ? "failed"
                  : status === "queued_retry"
                    ? "manual_retry"
                    : "queued",
            attempts: 0,
            max_attempts: 3,
            retryable: status === "failed",
            cancel_requested: status === "cancelled",
            created_at: new Date().toISOString(),
            updated_at: new Date().toISOString(),
            version: jobVersion,
            error_message: status === "failed" ? "fallo controlado E2E" : null,
          }),
        });
        return;
      }
      if (req.method() === "POST" && url.includes("/cancel")) {
        const ifMatch = req.headers()["if-match"] || "";
        if (!ifMatch) {
          await route.fulfill({
            status: 428,
            contentType: "application/problem+json",
            body: JSON.stringify({
              title: "Precondición",
              detail: "If-Match es obligatorio.",
              status: 428,
              code: "precondition_required",
            }),
          });
          return;
        }
        jobStatus = "cancelled";
        jobVersion += 1;
        await route.fulfill({
          status: 202,
          contentType: "application/json",
          headers: { ETag: `W/"${jobVersion}"` },
          body: JSON.stringify({
            id,
            tenant_id: "00000000-0000-4000-8000-000000000001",
            job_type: "oracle.dossier_question.answer",
            queue: "ai",
            status: "cancelled",
            progress: 0,
            stage: "cancelled",
            attempts: 0,
            max_attempts: 3,
            retryable: false,
            cancel_requested: true,
            created_at: new Date().toISOString(),
            updated_at: new Date().toISOString(),
            version: jobVersion,
          }),
        });
        return;
      }
      if (req.method() === "POST" && url.includes("/retry")) {
        jobStatus = "queued_retry";
        jobVersion += 1;
        await route.fulfill({
          status: 202,
          contentType: "application/json",
          headers: { ETag: `W/"${jobVersion}"` },
          body: JSON.stringify({
            id,
            tenant_id: "00000000-0000-4000-8000-000000000001",
            job_type: "oracle.dossier_question.answer",
            queue: "ai",
            status: "queued",
            progress: 0,
            stage: "manual_retry",
            attempts: 0,
            max_attempts: 3,
            retryable: true,
            cancel_requested: false,
            created_at: new Date().toISOString(),
            updated_at: new Date().toISOString(),
            version: jobVersion,
          }),
        });
        return;
      }
      await route.continue();
    });

    await page.route(`**/api/v1/dossiers/${dossierId}/conversations/**/messages**`, async (route) => {
      const req = route.request();
      if (req.method() === "POST") {
        await route.continue();
        return;
      }
      if (req.method() === "GET") {
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({
            id: "msg-e2e",
            conversation_id: "conv-e2e",
            dossier_id: dossierId,
            role: "user",
            status:
              jobStatus === "cancelled"
                ? "cancelled"
                : jobStatus === "failed"
                  ? "failed"
                  : "queued",
            sequence: 1,
            content_text: questionText,
            background_job_id: jobId === "pending" ? "00000000-0000-4000-8000-0000000000ab" : jobId,
            error_message: jobStatus === "failed" ? "fallo controlado E2E" : null,
          }),
        });
        return;
      }
      await route.continue();
    });

    await page.goto(`/app/dossiers/${dossierId}/ask`);
    await expect(page.getByRole("heading", { name: "Preguntar a Oracle" })).toBeVisible({
      timeout: 20000,
    });

    const askResponsePromise = page.waitForResponse(
      (response) =>
        response.url().includes(`/api/v1/dossiers/${dossierId}/conversations/`) &&
        response.url().includes("/messages") &&
        response.request().method() === "POST",
      { timeout: 30000 },
    );
    await page.getByLabel("Tu pregunta").fill(questionText);
    await page.getByRole("button", { name: "Enviar pregunta" }).click();
    const askResponse = await askResponsePromise;
    // May be 202 from real API before our message GET stub takes over
    if (askResponse.status() === 202) {
      const body = (await askResponse.json()) as { job_id: string; message_id: string };
      jobId = body.job_id || jobId;
    } else {
      jobId = "00000000-0000-4000-8000-0000000000ab";
    }

    // Force rehydrate with stubbed queued job
    jobStatus = "queued";
    await page.evaluate(
      ([id, jid, q]) => {
        sessionStorage.setItem(
          `oracle:dossier-ask:${id}`,
          JSON.stringify({ conversationId: "conv-e2e", messageId: "msg-e2e", title: q }),
        );
      },
      [dossierId, jobId, questionText] as const,
    );
    await page.reload();
    await expect(page.getByText(questionText)).toBeVisible({ timeout: 20000 });
    await expect(page.getByTestId("job-cancel")).toBeVisible({ timeout: 15000 });
    await expect(page.getByTestId("job-retry")).toHaveCount(0);

    await page.getByTestId("job-cancel").click();
    await expect(page.getByTestId("job-progress-cancelled")).toBeVisible({
      timeout: 15000,
    });
    // History preserved
    await expect(page.getByText(questionText)).toBeVisible();

    // Switch to failed+retryable for Reintentar
    jobStatus = "failed";
    jobVersion += 1;
    await page.reload();
    await expect(page.getByTestId("job-retry")).toBeVisible({ timeout: 15000 });
    await expect(page.getByTestId("job-cancel")).toHaveCount(0);
    await page.getByTestId("job-retry").click();
    await expect(page.getByText(/Reintentando|Trabajo de respuesta|manual_retry|queued/i)).toBeVisible({
      timeout: 15000,
    });
    await expect(page.getByText(questionText)).toBeVisible();
  });
});
