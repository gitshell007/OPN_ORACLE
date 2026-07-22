import { expect, test } from "@playwright/test";

test("el escaparate conserva Vector y Horizon como referencia", async ({
  page,
}) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: /Dos formas/ })).toBeVisible();
  await expect(
    page.getByRole("link", { name: /Abrir Vector/ }),
  ).toHaveAttribute("href", "/concept-a/portfolio");
  await expect(
    page.getByRole("link", { name: /Abrir Horizon/ }),
  ).toHaveAttribute("href", "/concept-b/portfolio");
});

test("Horizon sigue aislado como prototipo no autenticado", async ({
  page,
}) => {
  await page.goto("/concept-b/portfolio");
  await expect(page.locator("main h1")).toBeVisible();
  await page.goto("/concept-b/dossiers/dach-2027");
  await expect(
    page.getByRole("heading", { name: "Expansión DACH 2027" }),
  ).toBeVisible();
});

test("login corporativo es accesible y no persiste credenciales", async ({
  page,
}) => {
  await page.goto("/login?next=https%3A%2F%2Fevil.example");
  await expect(
    page.getByRole("heading", { name: "Bienvenido a Oracle" }),
  ).toBeVisible();
  await page.getByLabel("Correo electrónico").fill("persona@example.test");
  await page
    .getByLabel("Contraseña", { exact: true })
    .fill("frase de prueba no enviada");
  const stored = await page.evaluate(() => ({
    local: Object.keys(localStorage),
    session: Object.keys(sessionStorage),
  }));
  expect(
    stored.local.filter((key) => /token|session|password|csrf/i.test(key)),
  ).toEqual([]);
  expect(
    stored.session.filter((key) => /token|session|password|csrf/i.test(key)),
  ).toEqual([]);
});

test("recuperación mantiene respuesta anti-enumeración", async ({ page }) => {
  await page.goto("/forgot-password");
  await expect(
    page.getByRole("heading", { name: "Recupera el acceso" }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Enviar instrucciones" }),
  ).toBeVisible();
  await page.getByLabel("Correo electrónico").fill("no-existe@oracle-e2e.test");
  await page.getByRole("button", { name: "Enviar instrucciones" }).click();
  await expect(page.getByText("Solicitud recibida")).toBeVisible();
});

test("la aplicación canónica redirige al login sin sesión", async ({ page }) => {
  await page.goto("/app");
  await expect(page).toHaveURL(/\/login\?next=/);
  await expect(
    page.getByRole("heading", { name: "Bienvenido a Oracle" }),
  ).toBeVisible();
});

test("login real abre Vector canónico, navegación, sesiones y administración tenant", async ({
  page,
}, testInfo) => {
  test.skip(
    testInfo.project.name === "mobile",
    "El flujo completo se valida en escritorio; login se renderiza también en móvil.",
  );
  await page.goto("/login?next=%2Fapp");
  await page.getByLabel("Correo electrónico").fill("owner@oracle-e2e.test");
  await page
    .getByLabel("Contraseña", { exact: true })
    .fill("Oracle E2E segura 2026");
  await page.getByRole("button", { name: "Entrar en Oracle" }).click();
  await expect(page.getByLabel("Organización")).toBeVisible();
  await page.getByLabel("Organización").selectOption({ label: "Asterion E2E" });
  await page.getByRole("button", { name: "Entrar en Oracle" }).click();
  await expect(page).toHaveURL(/\/app$/);
  await expect(page.getByText("Olivia Owner")).toBeVisible();
  await expect(page.getByRole("link", { name: "Señales", exact: true })).toHaveAttribute(
    "href",
    "/app/signals",
  );
  const productNavLinks = await page
    .getByRole("navigation", { name: "Navegación principal" })
    .getByRole("link")
    .evaluateAll((links) => links.map((link) => link.getAttribute("href")));
  expect(productNavLinks.some((href) => href?.includes("#"))).toBe(false);
  expect(productNavLinks.some((href) => href?.startsWith("/concept-"))).toBe(false);
  await page.getByRole("button", { name: "Crear", exact: true }).click();
  await page.getByRole("menuitem", { name: "Nuevo expediente" }).click();
  const createDialog = page.getByRole("dialog", { name: "Nuevo expediente" });
  await createDialog.getByLabel("Nombre").fill("Expediente E2E canónico");
  await createDialog
    .getByLabel("Objetivo estratégico")
    .fill("Validar la creación real desde el shell definitivo");
  await createDialog.getByRole("button", { name: "Crear expediente" }).click();
  await expect(page).toHaveURL(/\/app\/dossiers\/[0-9a-f-]+$/);
  await expect(
    page.getByRole("heading", { name: "Expediente E2E canónico" }),
  ).toBeVisible();
  await page.goto("/app/account/sessions");
  await expect(
    page.getByRole("heading", { name: "Sesiones activas" }),
  ).toBeVisible();
  await expect(page.getByText("Este dispositivo")).toBeVisible();
  await page.goto("/app/admin/members");
  await expect(
    page.getByRole("heading", { name: "Miembros y roles" }),
  ).toBeVisible();
  await expect(page.getByText("owner@oracle-e2e.test")).toBeVisible();
  await page.goto("/app");
  await page.getByRole("button", { name: /Asterion E2E/ }).click();
  await page.getByRole("menuitem", { name: /Boreal E2E/ }).click();
  await expect(page.getByRole("button", { name: /Boreal E2E/ })).toBeVisible();
  const stored = await page.evaluate(() => ({
    local: Object.keys(localStorage),
    session: Object.keys(sessionStorage),
  }));
  expect(
    [...stored.local, ...stored.session].filter((key) =>
      /token|session|password|csrf/i.test(key),
    ),
  ).toEqual([]);
  await page.getByRole("button", { name: /Olivia Owner/ }).click();
  await page.getByRole("menuitem", { name: "Cerrar sesión" }).click();
  await expect(page).toHaveURL(/\/login/);
});

test("miembro sin permiso recibe forbidden útil en tenant-admin", async ({
  page,
}, testInfo) => {
  test.skip(
    testInfo.project.name === "mobile",
    "Permisos administrativos se cubren en escritorio.",
  );
  await page.goto("/login?next=%2Fapp%2Fadmin%2Fmembers");
  await page.getByLabel("Correo electrónico").fill("viewer@oracle-e2e.test");
  await page
    .getByLabel("Contraseña", { exact: true })
    .fill("Oracle E2E segura 2026");
  await page.getByRole("button", { name: "Entrar en Oracle" }).click();
  await expect(
    page.getByRole("heading", { name: "Acceso restringido" }),
  ).toBeVisible();
});

test("superadmin real accede solo al portal de plataforma", async ({
  page,
}, testInfo) => {
  test.skip(
    testInfo.project.name === "mobile",
    "El portal completo se cubre en escritorio.",
  );
  await page.goto("/login?next=%2Fplatform%2Ftenants");
  await page.getByLabel("Correo electrónico").fill("platform@oracle-e2e.test");
  await page
    .getByLabel("Contraseña", { exact: true })
    .fill("Oracle E2E segura 2026");
  await page.getByRole("button", { name: "Entrar en Oracle" }).click();
  await expect(page).toHaveURL(/\/platform\/tenants$/);
  await expect(
    page.getByRole("heading", { name: "Organizaciones" }),
  ).toBeVisible();
  await expect(page.getByText("Asterion E2E")).toBeVisible();
  await expect(page.getByText("Datos de plataforma").first()).toBeVisible();
  await page.goto("/app");
  await expect(page).toHaveURL(/\/platform\/tenants$/);
  await expect(page.getByRole("heading", { name: "Organizaciones" })).toBeVisible();
});

test("Vector F11 abre informes, notificaciones, preferencias y exportaciones", async ({
  page,
}, testInfo) => {
  const consoleErrors: string[] = [];
  page.on("console", (message) => {
    if (message.type() === "error") consoleErrors.push(message.text());
  });
  await page.goto("/login?next=%2Fapp%2Freports");
  await page.getByLabel("Correo electrónico").fill("owner@oracle-e2e.test");
  await page
    .getByLabel("Contraseña", { exact: true })
    .fill("Oracle E2E segura 2026");
  await page.getByRole("button", { name: "Entrar en Oracle" }).click();
  await expect(page.getByLabel("Organización")).toBeVisible();
  await page.getByLabel("Organización").selectOption({ label: "Asterion E2E" });
  await page.getByRole("button", { name: "Entrar en Oracle" }).click();
  await expect(page).toHaveURL(/\/app\/reports$/);
  await expect(
    page.getByRole("heading", { name: "Biblioteca de informes" }),
  ).toBeVisible();
  await expect(page.getByText("Aún no hay informes")).toBeVisible();
  // El 401 de /auth/me previo al login y el 409 de selección de tenant son
  // estados esperados del flujo de acceso, no errores de las rutas F11.
  consoleErrors.length = 0;
  const noOverflow = async () => {
    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth > document.documentElement.clientWidth,
    );
    expect(overflow).toBe(false);
  };
  await noOverflow();
  await page.screenshot({ path: testInfo.outputPath("f11-reports.png"), fullPage: true });
  await page.getByRole("button", { name: /Notificaciones/ }).click();
  await expect(page.getByText("No hay notificaciones activas.")).toBeVisible();
  await page.goto("/app/notifications");
  await expect(
    page.getByRole("heading", { name: "Centro de notificaciones" }),
  ).toBeVisible();
  await noOverflow();
  await page.goto("/app/account/notifications");
  await expect(
    page.getByRole("heading", { name: "Preferencias de notificación" }),
  ).toBeVisible();
  await noOverflow();
  await page.goto("/app/exports");
  await expect(
    page.getByRole("heading", { name: "Exportaciones", exact: true }),
  ).toBeVisible();
  await expect(page.getByText("Aún no hay exportaciones")).toBeVisible();
  await noOverflow();
  await page.screenshot({ path: testInfo.outputPath("f11-exports.png"), fullPage: true });
  await page.route("**/api/v1/reports/report-visual", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        id: "report-visual",
        dossier_id: "11111111-1111-4111-8111-111111111111",
        title: "Informe ejecutivo · Proyecto Delta",
        status: "ready",
        report_type: "executive",
        template_key: "executive_dossier",
        template_version: "v1",
        generation_version: 2,
        classification: "internal",
        confidentiality_label: "Uso interno",
        job_id: null,
        parent_report_id: null,
        ready_at: "2026-07-11T01:00:00Z",
        reviewed_at: null,
        published_at: null,
        error_code: null,
        version: 3,
        revision: {
          id: "22222222-2222-4222-8222-222222222222",
          revision_no: 1,
          status: "ready",
          title: "Informe ejecutivo · Proyecto Delta",
          change_summary: "Primera generación trazable",
          created_at: "2026-07-11T01:00:00Z",
          content: {
            title: "Informe ejecutivo · Proyecto Delta",
            executive_summary:
              "El expediente conserva impulso y requiere una decisión de coordinación esta semana.",
            confidence: 84,
            facts: [],
            inferences: [],
            recommendations: [],
            open_questions: ["¿Qué actor validará el siguiente hito?"],
            warnings: ["Resultado sintético reservado a validación visual."],
            sections: [
              {
                heading: "Estado actual",
                paragraphs: [
                  {
                    text: "El hito técnico fue confirmado en la última revisión documental.",
                    kind: "fact",
                    confidence: 93,
                    evidence_ids: ["33333333-3333-4333-8333-333333333333"],
                  },
                  {
                    text: "La ventana de coordinación es favorable si se confirma el patrocinio interno.",
                    kind: "inference",
                    confidence: 76,
                    evidence_ids: ["33333333-3333-4333-8333-333333333333"],
                  },
                ],
              },
              {
                heading: "Próximos pasos",
                paragraphs: [
                  {
                    text: "Convocar una sesión de decisión con responsables y evidencias abiertas.",
                    kind: "recommendation",
                    confidence: 81,
                    evidence_ids: [],
                  },
                ],
              },
            ],
            source_index: [],
            top_opportunities: [],
            top_risks: [],
            recommended_actions: [],
            decisions_required: [],
          },
        },
        artifacts: [],
        reviews: [],
        evidence: [
          {
            id: "33333333-3333-4333-8333-333333333333",
            extract: "Extracto sintético utilizado exclusivamente para comprobar la interacción de citas.",
            locator: "Documento Delta · página 4 · párrafo 2",
            source_label: "Acta de revisión Delta",
            classification: "internal",
            checksum: "visual-checksum",
          },
        ],
        created_at: "2026-07-11T00:30:00Z",
        updated_at: "2026-07-11T01:00:00Z",
      }),
    });
  });
  await page.goto("/app/reports/report-visual");
  await expect(
    page.getByRole("heading", { name: "Informe ejecutivo · Proyecto Delta" }),
  ).toBeVisible();
  await noOverflow();
  await page.screenshot({ path: testInfo.outputPath("f11-viewer.png"), fullPage: true });
  await page.getByRole("button", { name: "Abrir evidencia 1" }).first().click();
  await expect(
    page.getByText(/Extracto sintético utilizado exclusivamente/),
  ).toBeVisible();
  await page.getByRole("button", { name: "Cerrar evidencia" }).click();
  if (testInfo.project.name === "desktop") {
    for (const viewport of [
      { width: 1280, height: 800 },
      { width: 1024, height: 768 },
    ]) {
      await page.setViewportSize(viewport);
      for (const path of [
        "/app/reports",
        "/app/notifications",
        "/app/account/notifications",
        "/app/exports",
      ]) {
        await page.goto(path);
        if (path === "/app/reports")
          await expect(page.getByText("Aún no hay informes")).toBeVisible();
        if (path === "/app/exports")
          await expect(page.getByText("Aún no hay exportaciones")).toBeVisible();
        await noOverflow();
      }
      await page.screenshot({
        path: testInfo.outputPath(`f11-exports-${viewport.width}.png`),
        fullPage: true,
      });
      await page.goto("/app/reports/report-visual");
      await expect(
        page.getByText("El expediente conserva impulso y requiere una decisión de coordinación esta semana."),
      ).toBeVisible();
      await noOverflow();
      await page.screenshot({
        path: testInfo.outputPath(`f11-viewer-${viewport.width}.png`),
        fullPage: true,
      });
    }
  }
  expect(consoleErrors).toEqual([]);
});
