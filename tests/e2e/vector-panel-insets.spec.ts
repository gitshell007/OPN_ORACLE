import { expect, test } from "@playwright/test";

/**
 * ORA-UI-PANEL-INSETS — contract of Vector panel body inset.
 * Uses setContent + tokens so the check does not depend on auth or product data.
 * Asserts geometry (bounding boxes / computed padding), not class names or CSS source.
 */

const PANEL_CONTRACT_CSS = `
:root {
  --space-2: 8px;
  --space-3: 12px;
  --space-4: 16px;
  --va-panel: #fff;
  --va-border: #d7e3f1;
  --va-radius: 6px;
  --va-shadow: none;
}
.vector-panel {
  --vector-panel-pad-x: var(--space-4);
  --vector-panel-pad-y: var(--space-3);
  --vector-panel-pad-y-header: var(--space-3);
  background: var(--va-panel);
  border: 1px solid var(--va-border);
  border-radius: var(--va-radius);
  box-shadow: var(--va-shadow);
  min-width: 0;
  width: min(720px, 100%);
  margin: 24px auto;
}
.vector-panel > header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: var(--vector-panel-pad-y-header) var(--vector-panel-pad-x);
  border-bottom: 1px solid var(--va-border);
  gap: var(--space-3);
}
.vector-panel-body {
  padding: var(--vector-panel-pad-y) var(--vector-panel-pad-x);
  min-width: 0;
  overflow-wrap: anywhere;
}
.vector-panel-body--stack {
  display: grid;
  gap: var(--space-3);
}
.vector-panel-strip {
  margin: 0;
  padding: var(--space-3) var(--vector-panel-pad-x);
  border-bottom: 1px solid var(--va-border);
  background: #f8fafc;
}
.vector-panel-body--flush { padding: 0; }
body { margin: 0; font-family: system-ui, sans-serif; background: #efece6; color: #0c1440; }
p { margin: 0; }
button { min-height: 40px; }
`;

const PANEL_HTML = `
<section class="vector-panel" data-testid="fixture-panel">
  <header data-testid="fixture-header">
    <h2 style="margin:0;font-size:15px">Perfil del expediente</h2>
  </header>
  <div class="vector-panel-strip" data-testid="fixture-strip">Franja semántica full-bleed</div>
  <div class="vector-panel-body vector-panel-body--stack" data-testid="fixture-body">
    <p data-testid="fixture-copy">
      No hay actores publicables con cita cerrada en este resultado.
    </p>
    <button type="button" data-testid="fixture-cta">Materializar fuentes seleccionadas</button>
  </div>
</section>
`;

async function assertBodyInset(
  page: import("@playwright/test").Page,
  minInsetPx: number,
) {
  const panel = page.getByTestId("fixture-panel");
  const body = page.getByTestId("fixture-body");
  const copy = page.getByTestId("fixture-copy");
  const cta = page.getByTestId("fixture-cta");
  const header = page.getByTestId("fixture-header");

  await expect(panel).toBeVisible();
  await expect(body).toBeVisible();

  const panelBox = await panel.boundingBox();
  const copyBox = await copy.boundingBox();
  const ctaBox = await cta.boundingBox();
  const headerBox = await header.boundingBox();
  expect(panelBox).toBeTruthy();
  expect(copyBox).toBeTruthy();
  expect(ctaBox).toBeTruthy();
  expect(headerBox).toBeTruthy();

  const leftInset = (copyBox!.x - panelBox!.x);
  const rightInset = panelBox!.x + panelBox!.width - (copyBox!.x + copyBox!.width);
  expect(leftInset, "copy must not sit on the panel's left edge").toBeGreaterThanOrEqual(
    minInsetPx,
  );
  expect(rightInset, "copy must not sit on the panel's right edge").toBeGreaterThanOrEqual(
    minInsetPx - 1,
  );
  expect(ctaBox!.x - panelBox!.x).toBeGreaterThanOrEqual(minInsetPx);

  // Header title and body copy share the same horizontal start (aligned inset).
  const headerPadLeft = await header.evaluate((el) => {
    const cs = getComputedStyle(el);
    return parseFloat(cs.paddingLeft || "0");
  });
  const bodyPadLeft = await body.evaluate((el) => {
    const cs = getComputedStyle(el);
    return parseFloat(cs.paddingLeft || "0");
  });
  expect(bodyPadLeft).toBeGreaterThanOrEqual(minInsetPx);
  expect(Math.abs(headerPadLeft - bodyPadLeft)).toBeLessThanOrEqual(1);

  // No meaningful horizontal page overflow (allow 2px subpixel/scrollbar slack).
  const overflow = await page.evaluate(() => {
    const doc = document.documentElement;
    return {
      scrollWidth: doc.scrollWidth,
      clientWidth: doc.clientWidth,
    };
  });
  expect(overflow.scrollWidth).toBeLessThanOrEqual(overflow.clientWidth + 2);
}

const VIEWPORTS = [
  { name: "desktop-1440", width: 1440, height: 900, minInset: 12 },
  { name: "tablet-1024", width: 1024, height: 768, minInset: 12 },
  { name: "mobile-390", width: 390, height: 844, minInset: 12 },
] as const;

for (const viewport of VIEWPORTS) {
  test(`vector panel body has inset vs panel edge (${viewport.name})`, async ({
    page,
  }, testInfo) => {
    // Run each size once: desktop project covers 1440/1024; mobile project 390.
    if (testInfo.project.name === "mobile" && viewport.name !== "mobile-390") {
      test.skip();
    }
    if (testInfo.project.name === "desktop" && viewport.name === "mobile-390") {
      test.skip();
    }
    await page.setViewportSize({ width: viewport.width, height: viewport.height });
    await page.setContent(
      `<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"></head><body>${PANEL_HTML}</body></html>`,
    );
    await page.addStyleTag({
      content: `${PANEL_CONTRACT_CSS}\n*,*::before,*::after{box-sizing:border-box}`,
    });
    await assertBodyInset(page, viewport.minInset);
  });
}
