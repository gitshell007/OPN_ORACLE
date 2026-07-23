import { expect, test, type Page, type TestInfo } from "@playwright/test";

const plan = {
  intent_summary: "Equipamiento y mantenimiento para emergencias públicas",
  include_terms: ["equipos de extinción"],
  synonyms: ["material contra incendios"],
  exclude_terms: ["formación"],
  candidate_cpv: [{ code: "35110000", label: "Equipo de extinción" }],
  buyers: ["Ayuntamiento de Sevilla"],
  geographies: ["Andalucía"],
  scope: "active",
  min_amount: null,
  max_amount: null,
  assumptions: ["Se buscan suministros y mantenimiento"],
  questions: ["¿Debe incluirse vestuario técnico?"],
  confidence: 72,
  discarded_count: 2,
  discarded_reasons: { invalid_cpv: 2 },
};

const artifact = {
  id: "00000000-0000-4000-8000-000000000080",
  dossier_id: null,
  agent: "tender_search_wizard",
  schema_name: "tender_search_wizard",
  schema_version: "1",
  status: "valid",
  output: plan,
  created_at: "2026-07-23T10:00:00Z",
  updated_at: "2026-07-23T10:00:00Z",
  version: 1,
};

const profile = {
  id: "00000000-0000-4000-8000-000000000081",
  schema: "procurement-search-profile/v1",
  original_description: "Equipamiento para emergencias",
  comparables: [],
  accepted_plan: plan,
  accepted_plan_hash: "hash",
  version: 1,
  ai_artifact_id: artifact.id,
  tender_search_id: null,
  accepted_by_user_id: "owner-e2e",
  created_at: "2026-07-23T10:00:00Z",
  updated_at: "2026-07-23T10:00:00Z",
  last_accepted_at: "2026-07-23T10:00:00Z",
};

async function loginOwner(page: Page, testInfo: TestInfo) {
  await page.setExtraHTTPHeaders({
    "X-Forwarded-For":
      testInfo.project.name === "mobile" ? "198.51.100.102" : "198.51.100.101",
  });
  await page.goto("/login?next=%2Fapp%2Fprocurement");
  await page.getByLabel("Correo electrónico").fill("owner@oracle-e2e.test");
  await page
    .getByLabel("Contraseña", { exact: true })
    .fill("Oracle E2E segura 2026");
  await page.getByRole("button", { name: "Entrar en Oracle" }).click();
  await page.getByLabel("Organización").selectOption({
    label: "Asterion E2E",
  });
  await page.getByRole("button", { name: "Entrar en Oracle" }).click();
  await expect(page).toHaveURL(/\/app\/procurement/);
}

async function installProcurementContract(page: Page) {
  let saved = false;
  await page.route("**/api/v1/procurement/tenders?**", async (route) => {
    await route.fulfill({
      json: {
        cache_hit: false,
        cached_seconds: 0,
        filters: { scope: "active" },
        items: [],
        total: 0,
        limit: 25,
        offset: 0,
      },
    });
  });
  await page.route(
    "**/api/v1/procurement/tender-searches",
    async (route) => {
      if (route.request().method() === "GET") {
        await route.fulfill({
          json: {
            items: saved
              ? [
                  {
                    id: "search-wizard-1",
                    name: "Equipamiento y mantenimiento para emergencias públicas",
                    keywords: ["equipos de extinción"],
                    filters: { scope: "active" },
                  },
                ]
              : [],
          },
        });
        return;
      }
      await route.fallback();
    },
  );
  await page.route(
    "**/api/v1/procurement-search-profiles",
    async (route) => {
      if (route.request().method() === "GET") {
        await route.fulfill({
          json: {
            items: saved
              ? [{ ...profile, tender_search_id: "search-wizard-1" }]
              : [],
          },
        });
        return;
      }
      await route.fulfill({ status: 201, json: profile });
    },
  );
  await page.route(
    "**/api/v1/ai/tender-search-wizard/latest",
    async (route) => {
      await route.fulfill({ json: { artifact: null, input: null, job: null } });
    },
  );
  await page.route(
    "**/api/v1/ai/tender-search-wizard/runs",
    async (route) => {
      await route.fulfill({
        status: 202,
        json: {
          artifact,
          job: {
            id: "job-wizard-1",
            status: "succeeded",
          },
        },
      });
    },
  );
  await page.route(
    "**/api/v1/procurement/search-plans/preview",
    async (route) => {
      await route.fulfill({
        json: {
          plan,
          preview: {
            translation_version: "v1",
            scope: "active",
            provider_requests: 2,
            probe_budget: {
              total: 8,
              term_limit: 4,
              cpv_limit: 4,
              selected: 2,
              skipped: 1,
            },
            probes: [
              {
                chip: {
                  kind: "term",
                  value: "equipos de extinción",
                  label: null,
                },
                query: {},
                total: 38,
                result: { items: [], total: 38 },
              },
              {
                chip: {
                  kind: "cpv",
                  value: "35110000",
                  label: "Equipo de extinción",
                },
                query: {},
                total: 14,
                result: { items: [], total: 14 },
              },
            ],
            unprobed_chips: [
              {
                kind: "term",
                value: "material contra incendios",
                label: null,
              },
            ],
            semantics: {
              global_order: false,
              merged_results: false,
              keyword_blocks: "independent",
              exclude_terms_applied: false,
              additional_buyers_applied: false,
              additional_geographies_applied: false,
              limitations: [],
            },
          },
        },
      });
    },
  );
  await page.route(
    `**/api/v1/procurement-search-profiles/${profile.id}/saved-search`,
    async (route) => {
      saved = true;
      await route.fulfill({
        json: {
          profile: { ...profile, tender_search_id: "search-wizard-1" },
          saved_search: {
            id: "search-wizard-1",
            name: "Equipamiento y mantenimiento para emergencias públicas",
          },
        },
      });
    },
  );
}

test("wizard gobernado funciona en Vector y no desborda", async ({
  page,
}, testInfo: TestInfo) => {
  await installProcurementContract(page);
  await loginOwner(page, testInfo);

  await expect(
    page.getByRole("heading", { name: "Licitaciones PLACSP" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Buscar con Oracle" }).click();
  await expect(
    page.getByRole("heading", { name: "Describe qué quieres encontrar" }),
  ).toBeVisible();
  await page
    .getByLabel("Qué vende tu empresa y qué contratos te interesan")
    .fill("Equipamiento y mantenimiento para emergencias públicas");
  await page.getByRole("button", { name: "Generar propuesta" }).click();

  await expect(
    page.getByRole("heading", { name: "Revisa el plan antes de usarlo" }),
  ).toBeVisible();
  await expect(page.getByText("Confianza Media")).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Guardar vigilancia" }),
  ).toHaveCount(0);
  await page.getByRole("button", { name: "Previsualizar ahora" }).click();
  await expect(page.getByText("38 coincidencias")).toBeVisible();
  await expect(
    page.getByText("Los resultados se solapan: los totales no se suman."),
  ).toBeVisible();

  await page.getByRole("button", { name: "Aceptar plan" }).click();
  await expect(page.getByText("Plan aceptado · v1")).toBeVisible();
  await page.getByRole("button", { name: "Guardar vigilancia" }).click();
  await expect(
    page.getByRole("button", { name: "Vigilancia guardada" }),
  ).toBeVisible();
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - window.innerWidth,
  );
  expect(overflow).toBeLessThanOrEqual(1);
  if (testInfo.project.name === "mobile") {
    const bounds = await page.locator(".procurement-wizard-dialog").boundingBox();
    expect(bounds?.width).toBeLessThanOrEqual(390);
    expect(bounds?.height).toBeLessThanOrEqual(844);
  }
  await page.screenshot({
    path: testInfo.outputPath(`procurement-wizard-${testInfo.project.name}.png`),
    fullPage: false,
  });
  await page.getByRole("button", { name: "Cerrar" }).click();
  await expect(
    page.locator(".procurement-saved-searches").getByText("v1", {
      exact: true,
    }),
  ).toBeVisible();
});
