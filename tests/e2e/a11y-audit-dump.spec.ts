/**
 * SV2-A11Y-2: measured axe dump for Gate Packet (not a green/red gate).
 * Writes raw violations to test-results/a11y-audit-dump.json — including known debt.
 *
 * Local (seed E2E):  npx playwright test tests/e2e/a11y-audit-dump.spec.ts --project=desktop
 * oracle-dev:        PLAYWRIGHT_BASE_URL=… ORACLE_E2E_EMAIL=… ORACLE_E2E_PASSWORD=…
 *                    npx playwright test tests/e2e/a11y-audit-dump.spec.ts --project=desktop
 */
import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page, type TestInfo } from "@playwright/test";
import fs from "node:fs";
import path from "node:path";

const WCAG_TAGS = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"];

const ROUTES = [
  "/app",
  "/app/dossiers",
  "/app/signals",
  "/app/actors",
  "/app/reports",
  "/app/admin/ai",
] as const;

/** Rutas de hoja del expediente (6 grupos + subnav clave + portada). */
const DOSSIER_LEAF_SEGMENTS = [
  "", // portada / Resumen
  "signals", // Vigilancia (subnav)
  "ask", // Análisis → Preguntar
  "tasks", // Decisión
  "documents", // Entregables
  "activity", // Actividad
] as const;

type DumpFinding = {
  route: string;
  id: string;
  impact: string | null | undefined;
  help: string;
  description: string;
  target: string;
  html?: string;
  failureSummary?: string;
};

function isRemote(): boolean {
  return Boolean(process.env.PLAYWRIGHT_BASE_URL?.trim());
}

async function login(page: Page, testInfo: TestInfo) {
  await page.setExtraHTTPHeaders({ "X-Forwarded-For": "198.51.100.140" });
  await page.goto("/login?next=%2Fapp");

  const remoteEmail = process.env.ORACLE_E2E_EMAIL?.trim();
  const remotePassword = process.env.ORACLE_E2E_PASSWORD?.trim();
  const email = remoteEmail || "owner@oracle-e2e.test";
  const password = remotePassword || "Oracle E2E segura 2026";

  await page.getByLabel("Correo electrónico").fill(email);
  await page.getByLabel("Contraseña", { exact: true }).fill(password);
  await page.getByRole("button", { name: "Entrar en Oracle" }).click();

  const org = page.getByLabel("Organización");
  const appLanded = page.waitForURL(/\/app/, { timeout: 25_000 });
  await Promise.race([
    org.waitFor({ state: "visible", timeout: 20_000 }).then(async () => {
      const label =
        process.env.ORACLE_E2E_TENANT_LABEL?.trim() ||
        (isRemote() ? "SV2 Demo Tenant" : "Asterion E2E");
      // Prefer label match; fall back to first non-empty option.
      try {
        await org.selectOption({ label });
      } catch {
        const options = await org.locator("option").allTextContents();
        const pick = options.map((t) => t.trim()).find((t) => t.length > 0);
        if (pick) await org.selectOption({ label: pick });
      }
      await page.getByRole("button", { name: "Entrar en Oracle" }).click();
    }),
    appLanded,
  ]);
  await expect(page).toHaveURL(/\/app/);
}

async function dumpAxe(page: Page, route: string): Promise<DumpFinding[]> {
  await expect(page.locator("body")).toBeVisible();
  // Settle layout before axe (nav animations / data fetch).
  await page.waitForTimeout(400);
  const result = await new AxeBuilder({ page }).withTags(WCAG_TAGS).analyze();
  return result.violations.flatMap((violation) =>
    violation.nodes.map((node) => ({
      route,
      id: violation.id,
      impact: violation.impact,
      help: violation.help,
      description: violation.description,
      target: node.target.join(" "),
      html: node.html?.slice(0, 240),
      failureSummary: node.failureSummary?.slice(0, 500),
    })),
  );
}

test("SV2-A11Y-2 dump axe findings for product routes", async ({ page }, testInfo) => {
  test.skip(
    testInfo.project.name === "mobile",
    "Audit dump runs once on desktop viewport.",
  );
  test.setTimeout(240_000);

  const findings: DumpFinding[] = [];
  const routeStatus: Array<{
    route: string;
    url: string;
    ok: boolean;
    notes: string;
    violationCount: number;
  }> = [];

  // Public + login
  for (const publicRoute of ["/", "/login"] as const) {
    await page.goto(publicRoute);
    await expect(page.locator("body")).toBeVisible();
    const batch = await dumpAxe(page, publicRoute);
    findings.push(...batch);
    routeStatus.push({
      route: publicRoute,
      url: page.url(),
      ok: true,
      notes: "public",
      violationCount: batch.length,
    });
  }

  await login(page, testInfo);

  for (const route of ROUTES) {
    await page.goto(route);
    const settled = page.url();
    let notes = "authenticated";
    let ok = true;
    if (settled.includes("/login")) {
      ok = false;
      notes = "redirected to login — auth/session blocked";
    } else {
      try {
        await expect(page.locator("main")).toBeVisible({ timeout: 15_000 });
      } catch {
        notes = "main not visible after goto";
      }
    }
    const batch = await dumpAxe(page, route);
    findings.push(...batch);
    routeStatus.push({
      route,
      url: settled,
      ok,
      notes,
      violationCount: batch.length,
    });
  }

  // Dossier detail + leaf routes (6 groups sample)
  let dossierBase = "";
  await page.goto("/app/dossiers");
  // Prefer demo name on remote; otherwise first dossier link.
  const demoLink = page
    .getByRole("link", { name: /Nexus Ibérica/i })
    .or(
      page
        .locator('a[href^="/app/dossiers/"]')
        .filter({ hasText: /Nexus Ibérica/i }),
    )
    .first();
  let href = "";
  if (await demoLink.isVisible().catch(() => false)) {
    href = (await demoLink.getAttribute("href")) ?? "";
  } else {
    href =
      (await page.locator('a[href^="/app/dossiers/"]').first().getAttribute("href")) ??
      "";
  }
  const match = href.match(/^(\/app\/dossiers\/[0-9a-f-]+)/i);
  if (match) {
    dossierBase = match[1];
    for (const segment of DOSSIER_LEAF_SEGMENTS) {
      const route = segment ? `${dossierBase}/${segment}` : dossierBase;
      await page.goto(route);
      try {
        await expect(page.locator("main")).toBeVisible({ timeout: 15_000 });
      } catch {
        /* still dump */
      }
      // Wait for grouped nav when present
      await page
        .getByTestId("dossier-nav-summary")
        .waitFor({ state: "visible", timeout: 10_000 })
        .catch(() => undefined);
      const batch = await dumpAxe(page, route);
      findings.push(...batch);
      routeStatus.push({
        route,
        url: page.url(),
        ok: true,
        notes: segment
          ? `dossier leaf segment=${segment}`
          : "dossier portada / Resumen",
        violationCount: batch.length,
      });
    }
  } else {
    routeStatus.push({
      route: "/app/dossiers/<id>",
      url: page.url(),
      ok: false,
      notes: "no dossier link available to audit detail screen",
      violationCount: 0,
    });
  }

  const outDir = path.join(process.cwd(), "test-results");
  fs.mkdirSync(outDir, { recursive: true });
  const payload = {
    generated_at: new Date().toISOString(),
    prompt: "SV2-A11Y-2",
    target: isRemote()
      ? process.env.PLAYWRIGHT_BASE_URL
      : "http://127.0.0.1:3000",
    wcag_tags: WCAG_TAGS,
    route_status: routeStatus,
    findings,
    summary: {
      total_findings: findings.length,
      by_impact: findings.reduce<Record<string, number>>((acc, f) => {
        const key = f.impact ?? "unknown";
        acc[key] = (acc[key] ?? 0) + 1;
        return acc;
      }, {}),
      by_route: findings.reduce<Record<string, number>>((acc, f) => {
        acc[f.route] = (acc[f.route] ?? 0) + 1;
        return acc;
      }, {}),
      by_rule: findings.reduce<Record<string, number>>((acc, f) => {
        acc[f.id] = (acc[f.id] ?? 0) + 1;
        return acc;
      }, {}),
    },
  };
  const outPath = path.join(outDir, "a11y-audit-dump.json");
  fs.writeFileSync(outPath, JSON.stringify(payload, null, 2));
  await testInfo.attach("a11y-audit-dump.json", {
    body: JSON.stringify(payload, null, 2),
    contentType: "application/json",
  });
  expect(fs.existsSync(outPath)).toBe(true);
  console.log(
    `[SV2-A11Y-2] dump written: ${outPath} findings=${findings.length} by_impact=${JSON.stringify(payload.summary.by_impact)} by_rule=${JSON.stringify(payload.summary.by_rule)}`,
  );
});
