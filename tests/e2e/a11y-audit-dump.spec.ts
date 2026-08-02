/**
 * SV2-UI-A11Y: measured axe dump for Gate Packet (not a green/red gate).
 * Writes raw violations to test-results/a11y-audit-dump.json — including known debt.
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

async function loginOwner(page: Page, testInfo: TestInfo) {
  await page.setExtraHTTPHeaders({ "X-Forwarded-For": "198.51.100.140" });
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
}

async function dumpAxe(page: Page, route: string): Promise<DumpFinding[]> {
  await expect(page).toHaveTitle(/\S/);
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
      failureSummary: node.failureSummary?.slice(0, 400),
    })),
  );
}

test("SV2-UI-A11Y dump axe findings for product routes", async ({ page }, testInfo) => {
  test.skip(
    testInfo.project.name === "mobile",
    "Audit dump runs once on desktop viewport.",
  );
  test.setTimeout(180_000);

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

  await loginOwner(page, testInfo);

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

  // Dossier detail: pick first link from list if available
  let dossierRoute = "";
  await page.goto("/app/dossiers");
  const href =
    (await page.locator('a[href^="/app/dossiers/"]').first().getAttribute("href")) ??
    "";
  if (/^\/app\/dossiers\/[0-9a-f-]+/.test(href)) {
    dossierRoute = href.replace(/\/(signals|documents|settings|reports).*$/, "");
    await page.goto(dossierRoute);
    await expect(page.locator("main")).toBeVisible({ timeout: 15_000 });
    const batch = await dumpAxe(page, dossierRoute);
    findings.push(...batch);
    routeStatus.push({
      route: dossierRoute,
      url: page.url(),
      ok: true,
      notes: "dossier detail from list",
      violationCount: batch.length,
    });
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
    prompt: "SV2-UI-A11Y",
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
  // Attach for Playwright report
  await testInfo.attach("a11y-audit-dump.json", {
    body: JSON.stringify(payload, null, 2),
    contentType: "application/json",
  });
  // Soft assertion: dump must exist; violations are the deliverable
  expect(fs.existsSync(outPath)).toBe(true);
  console.log(
    `[SV2-UI-A11Y] dump written: ${outPath} findings=${findings.length}`,
  );
});
