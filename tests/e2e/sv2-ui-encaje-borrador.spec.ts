/**
 * SV2-UI-E2E · Playwright visual verification of:
 *  1) Encaje perfil ↔ pliego (¿pujamos?)
 *  2) Preparar borrador de oferta
 *  3) Empty honest state (no fit_assessment → no encaje / no draft button)
 *
 * Uses the auth E2E harness, disposable PostgreSQL and the real opportunity/latest
 * endpoint. The seed inserts anonymized artifacts; the browser never intercepts API calls.
 */
import { expect, test, type Page, type TestInfo } from "@playwright/test";
import fs from "node:fs";
import path from "node:path";

const FIT_DOSSIER = "G-14 Encaje y borrador E2E real";
const EMPTY_DOSSIER = "G-14 Estado vacío E2E real";

/** Screenshots for Codex/user evidence (outside the git worktree). */
const EVIDENCE_DIR =
  process.env.SV2_UI_E2E_EVIDENCE_DIR ||
  "/Users/gitshellmini/Desktop/Codex-Signal/runner/staging";

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

async function openDossier(page: Page, title: string): Promise<string> {
  await page.goto("/app/dossiers");
  await expect(page.locator("main")).toBeVisible({ timeout: 20_000 });
  const link = page.locator('a[href^="/app/dossiers/"]', { hasText: title }).first();
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

async function saveEvidence(page: Page, name: string, target?: ReturnType<Page["locator"]>) {
  try {
    fs.mkdirSync(EVIDENCE_DIR, { recursive: true });
    const file = path.join(EVIDENCE_DIR, name);
    if (target) {
      await target.screenshot({ path: file });
    } else {
      await page.screenshot({ path: file, fullPage: true });
    }
  } catch {
    // Evidence path may be unavailable in CI; assertions still run.
  }
}

test.describe("SV2-UI-E2E encaje + borrador (visual Playwright)", () => {
  test("bloque encaje: veredicto, puerta humana, ≥4 dimensiones, not_evaluable, condiciones", async ({
    page,
  }, testInfo) => {
    test.skip(
      testInfo.project.name === "mobile",
      "Contrato visual de encaje/borrador se valida en desktop.",
    );
    test.setTimeout(120_000);

    await loginOwner(page, testInfo);
    const base = await openDossier(page, FIT_DOSSIER);

    const latestResponse = page.waitForResponse(
      (response) =>
        response.request().method() === "GET" &&
        response.url().includes("/api/v1/ai/dossiers/") &&
        response.url().endsWith("/opportunity/latest"),
    );
    await page.goto(`${base}/opportunity-analysis`);
    const response = await latestResponse;
    expect(response.status()).toBe(200);
    const payload = (await response.json()) as {
      artifact?: { output?: { fit_assessment?: unknown; draft_offer?: unknown } };
    };
    expect(payload.artifact?.output?.fit_assessment).toBeTruthy();
    expect(payload.artifact?.output?.draft_offer).toBeTruthy();
    await expect(page.getByTestId("dossier-opportunity-analysis-section")).toBeVisible({
      timeout: 20_000,
    });
    await expect(page.getByTestId("dossier-opportunity-proposal")).toBeVisible({
      timeout: 20_000,
    });

    const fit = page.getByTestId("dossier-opportunity-fit-assessment");
    await expect(fit).toBeVisible();
    await expect(page.getByRole("heading", { name: /Encaje perfil ↔ pliego/ })).toBeVisible();

    // 1) Veredicto + badge
    const badge = page.getByTestId("dossier-opportunity-fit-verdict-rec");
    await expect(badge).toBeVisible();
    await expect(badge).toHaveText(/GO CONDICIONADO|GO|NO-GO/);
    await expect(badge).toHaveAttribute("data-verdict", /go_conditioned|go|no_go/);
    await expect(badge).toHaveClass(/badge/);

    // 2) Puerta humana
    const gate = page.getByTestId("dossier-opportunity-fit-human-gate");
    await expect(gate).toBeVisible();
    await expect(gate).toHaveText(/pendiente de confirmación del usuario|awaiting_user_confirmation/i);

    // 3) ≥4 filas de dimensión con Requisito (oficial) y Capacidad (declarado)
    const dims = page.getByTestId("dossier-opportunity-fit-dimensions");
    await expect(dims).toBeVisible();
    const dimKeys = ["cpv", "solvency", "lots", "deadline"] as const;
    for (const key of dimKeys) {
      const row = page.getByTestId(`dossier-opportunity-fit-dim-${key}`);
      await expect(row).toBeVisible();
      await expect(page.getByTestId(`dossier-opportunity-fit-dim-req-${key}`)).toContainText(
        "Requisito (oficial)",
      );
      await expect(page.getByTestId(`dossier-opportunity-fit-dim-cap-${key}`)).toContainText(
        "Capacidad (declarado)",
      );
    }

    // 4) not_evaluable → literal «no evaluable con lo declarado»
    const solvencyStatus = page.getByTestId("dossier-opportunity-fit-dim-status-solvency");
    await expect(solvencyStatus).toHaveAttribute("data-status", "not_evaluable");
    await expect(solvencyStatus).toContainText("no evaluable con lo declarado");
    await expect(page.getByTestId("dossier-opportunity-fit-dim-reason-solvency")).toContainText(
      /no evaluable con lo declarado/i,
    );

    // 5) Condiciones del veredicto
    const conditions = page.getByTestId("dossier-opportunity-fit-conditions");
    await expect(conditions).toBeVisible();
    const conditionItems = conditions.locator("li");
    await expect(conditionItems).toHaveCount(await conditionItems.count());
    expect(await conditionItems.count()).toBeGreaterThanOrEqual(1);
    await expect(conditions).toContainText(/F\.2|solvencia|acreditar/i);

    await saveEvidence(page, "sv2_ui_e2e_encaje.png", fit);
  });

  test("bloque borrador: banner, ≥3 secciones [oficial], semilla, checklist, gaps", async ({
    page,
  }, testInfo) => {
    test.skip(
      testInfo.project.name === "mobile",
      "Contrato visual de encaje/borrador se valida en desktop.",
    );
    test.setTimeout(120_000);

    await loginOwner(page, testInfo);
    const base = await openDossier(page, FIT_DOSSIER);

    const latestResponse = page.waitForResponse(
      (response) =>
        response.request().method() === "GET" &&
        response.url().includes("/api/v1/ai/dossiers/") &&
        response.url().endsWith("/opportunity/latest"),
    );
    await page.goto(`${base}/opportunity-analysis`);
    const response = await latestResponse;
    expect(response.status()).toBe(200);
    const payload = (await response.json()) as {
      artifact?: { output?: { fit_assessment?: unknown; draft_offer?: unknown } };
    };
    expect(payload.artifact?.output?.fit_assessment).toBeTruthy();
    expect(payload.artifact?.output?.draft_offer).toBeTruthy();
    await expect(page.getByTestId("dossier-opportunity-proposal")).toBeVisible({
      timeout: 20_000,
    });

    const prepare = page.getByTestId("dossier-opportunity-prepare-draft-offer");
    await expect(prepare).toBeVisible();
    await expect(prepare).toHaveText(/Preparar borrador de oferta/);
    await prepare.click();

    const draft = page.getByTestId("dossier-opportunity-draft-offer");
    await expect(draft).toBeVisible();

    // 1) Banner comercial
    const banner = page.getByTestId("dossier-opportunity-draft-banner");
    await expect(banner).toBeVisible();
    await expect(banner).toContainText("BORRADOR COMERCIAL");
    await expect(banner).toContainText(/no es documento presentable/i);

    // 2) ≥3 secciones con título y cita [oficial]
    const sections = page.getByTestId("dossier-opportunity-draft-sections");
    await expect(sections).toBeVisible();
    const sectionKeys = [
      "award_economic",
      "award_technical",
      "award_thresholds",
    ] as const;
    for (const key of sectionKeys) {
      const sec = page.getByTestId(`dossier-opportunity-draft-section-${key}`);
      await expect(sec).toBeVisible();
      await expect(
        page.getByTestId(`dossier-opportunity-draft-section-title-${key}`),
      ).not.toHaveText("");
      await expect(
        page.getByTestId(`dossier-opportunity-draft-section-req-${key}`),
      ).toContainText(/\[oficial\]|Requisito \(oficial\)/i);
    }

    // 3) Semilla marcada como borrador declarado (no hecho)
    const seed = page.getByTestId("dossier-opportunity-draft-section-seed-award_economic");
    await expect(seed).toContainText(/borrador declarado/i);
    await expect(seed).toContainText(/no es hecho/i);

    // 4) Checklist administrativa pending/blocked (DEUC, F.2, F.3…)
    const checklist = page.getByTestId("dossier-opportunity-draft-checklist");
    await expect(checklist).toBeVisible();
    await expect(page.getByTestId("dossier-opportunity-draft-check-deuc")).toContainText(
      /pendiente|DEUC/i,
    );
    await expect(
      page.getByTestId("dossier-opportunity-draft-check-solvencia_f2"),
    ).toContainText(/bloqueado|F\.2/i);
    await expect(
      page.getByTestId("dossier-opportunity-draft-check-solvencia_f3"),
    ).toContainText(/bloqueado|F\.3/i);

    // 5) Gaps de solvencia
    const gaps = page.getByTestId("dossier-opportunity-draft-gaps");
    await expect(gaps).toBeVisible();
    await expect(gaps).toContainText(/F\.2|F\.3|solvencia|acreditar/i);

    await saveEvidence(page, "sv2_ui_e2e_borrador.png", draft);
  });

  test("estado vacío honesto: sin fit_assessment no hay encaje ni botón de borrador", async ({
    page,
  }, testInfo) => {
    test.skip(
      testInfo.project.name === "mobile",
      "Contrato visual de encaje/borrador se valida en desktop.",
    );
    test.setTimeout(120_000);

    await loginOwner(page, testInfo);
    const base = await openDossier(page, EMPTY_DOSSIER);

    const latestResponse = page.waitForResponse(
      (response) =>
        response.request().method() === "GET" &&
        response.url().includes("/api/v1/ai/dossiers/") &&
        response.url().endsWith("/opportunity/latest"),
    );
    await page.goto(`${base}/opportunity-analysis`);
    const response = await latestResponse;
    expect(response.status()).toBe(200);
    const payload = (await response.json()) as {
      artifact?: { output?: { fit_assessment?: unknown; draft_offer?: unknown } };
    };
    expect(payload.artifact).toBeTruthy();
    expect(payload.artifact?.output?.fit_assessment).toBeFalsy();
    expect(payload.artifact?.output?.draft_offer).toBeFalsy();
    await expect(page.getByTestId("dossier-opportunity-proposal")).toBeVisible({
      timeout: 20_000,
    });

    // Propuesta sí se ve (hechos/recomendación), pero sin bloque de encaje fantasma
    await expect(page.getByTestId("dossier-opportunity-fit-assessment")).toHaveCount(0);
    await expect(
      page.getByRole("heading", { name: /Encaje perfil ↔ pliego/ }),
    ).toHaveCount(0);
    await expect(page.getByTestId("dossier-opportunity-prepare-draft-offer")).toHaveCount(0);
    await expect(page.getByTestId("dossier-opportunity-draft-offer")).toHaveCount(0);

    await saveEvidence(page, "sv2_ui_e2e_vacio.png");
  });
});
