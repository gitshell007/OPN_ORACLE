import { chromium } from "playwright";

const browser = await chromium.launch({ headless: true });
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
const captures = [
  ["concept-a/portfolio", "concept-a-portfolio.png"],
  ["concept-a/dossiers/dach-2027", "concept-a-dossier.png"],
  ["concept-a/settings", "concept-a-settings.png"],
  ["concept-b/portfolio", "horizon-portfolio.png"],
  ["concept-b/dossiers/dach-2027", "horizon-dossier.png"],
  ["concept-b/settings", "horizon-settings.png"],
];

for (const [route, file] of captures) {
  await page.goto(`http://127.0.0.1:3000/${route}`, { waitUntil: "networkidle" });
  await page.waitForTimeout(500);
  await page.screenshot({ path: `docs/ui-prototypes/${file}`, fullPage: true });
}

await browser.close();
