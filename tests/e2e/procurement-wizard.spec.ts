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

const replan = {
  ...plan,
  include_terms: ["equipos de extinción", "bomberos"],
  exclude_terms: ["limpieza"],
  assumptions: [
    ...plan.assumptions,
    "El feedback descartó resultados de limpieza operativa.",
  ],
};

const replanArtifact = {
  ...artifact,
  id: "00000000-0000-4000-8000-000000000082",
  output: replan,
  created_at: "2026-07-23T10:05:00Z",
  updated_at: "2026-07-23T10:05:00Z",
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

const tender = {
  folder_id: "EXP-E2E-FEEDBACK",
  title: "Servicio de limpieza de dependencias municipales",
  summary_feed: "Limpieza ordinaria de edificios públicos.",
  buyer: "Ayuntamiento de Sevilla",
  status: "Open",
  canonical_status: "open",
  cpv: ["90910000"],
  amount: 45000,
  deadline: "2026-08-20",
  region: "Andalucía",
  source_url: "https://contrataciondelestado.es/wps/portal/licitacion-e2e",
  is_active: true,
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
  let feedbackSaved = false;
  let profileVersion = 1;
  let watchEnabled = false;
  const watch = () => ({
    id: "watch-e2e-1",
    profile_id: profile.id,
    tender_search_id: "search-wizard-1",
    name: "Equipamiento y mantenimiento para emergencias públicas",
    enabled: watchEnabled,
    notifications_enabled: watchEnabled,
    cadence_seconds: 900,
    new_count: 1,
    last_success_at: "2026-07-23T10:07:00Z",
    last_attempt_at: "2026-07-23T10:07:00Z",
    last_error_code: null,
    last_error_message: null,
    created_at: "2026-07-23T10:00:00Z",
    updated_at: "2026-07-23T10:07:00Z",
  });
  const currentProfile = () => ({
    ...profile,
    version: profileVersion,
    accepted_plan: profileVersion === 1 ? plan : replan,
    ai_artifact_id: profileVersion === 1 ? artifact.id : replanArtifact.id,
    tender_search_id: saved ? "search-wizard-1" : null,
    last_accepted_at:
      profileVersion === 1
        ? "2026-07-23T10:00:00Z"
        : "2026-07-23T10:06:00Z",
  });
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
    "**/api/v1/procurement/tender-searches/search-wizard-1/run?**",
    async (route) => {
      await route.fulfill({
        json: {
          search: {
            id: "search-wizard-1",
            name: "Equipamiento y mantenimiento para emergencias públicas",
            keywords: ["equipos de extinción"],
            filters: { scope: "active" },
          },
          results: {
            cache_hit: false,
            cached_seconds: 0,
            filters: { scope: "active" },
            items: [tender],
            total: 1,
            limit: 25,
            offset: 0,
          },
        },
      });
    },
  );
  await page.route("**/api/v1/procurement-search-watches", async (route) => {
    await route.fulfill({ json: { items: saved ? [watch()] : [] } });
  });
  await page.route(
    "**/api/v1/procurement-search-watches/watch-e2e-1",
    async (route) => {
      if (route.request().method() === "PATCH") {
        watchEnabled = Boolean(route.request().postDataJSON()?.enabled);
      }
      await route.fulfill({ json: watch() });
    },
  );
  await page.route(
    "**/api/v1/procurement-search-watches/watch-e2e-1/items",
    async (route) => {
      await route.fulfill({
        json: {
          items: [
            {
              id: "watch-item-e2e-1",
              folder_id: tender.folder_id,
              snapshot: {
                title: tender.title,
                buyer: tender.buyer,
                amount: String(tender.amount),
                deadline: tender.deadline,
                canonical_status: "open",
                cpvs: tender.cpv,
              },
              state: "new",
              changed_fields: ["new"],
              first_seen_at: "2026-07-23T10:07:00Z",
              last_changed_at: "2026-07-23T10:07:00Z",
              reviewed_at: null,
            },
          ],
        },
      });
    },
  );
  await page.route(
    "**/api/v1/procurement-search-profiles",
    async (route) => {
      if (route.request().method() === "GET") {
        await route.fulfill({
          json: {
            items: saved
              ? [currentProfile()]
              : [],
          },
        });
        return;
      }
      await route.fulfill({ status: 201, json: currentProfile() });
    },
  );
  await page.route(
    `**/api/v1/procurement-search-profiles/${profile.id}`,
    async (route) => {
      await route.fulfill({ json: currentProfile() });
    },
  );
  await page.route(
    `**/api/v1/procurement-search-profiles/${profile.id}/feedback`,
    async (route) => {
      if (route.request().method() === "GET") {
        await route.fulfill({
          json: {
            items: feedbackSaved
              ? [
                  {
                    id: "feedback-e2e-1",
                    profile_id: profile.id,
                    plan_version: 1,
                    folder_id: tender.folder_id,
                    verdict: "not_relevant",
                    reason: "wrong_sector",
                    note: null,
                    tender: {
                      title: tender.title,
                      cpvs: tender.cpv,
                    },
                    state: "current",
                    user_id: "owner-e2e",
                    created_at: "2026-07-23T10:03:00Z",
                    updated_at: "2026-07-23T10:03:00Z",
                  },
                ]
              : [],
            total: feedbackSaved ? 1 : 0,
            limit: 50,
            offset: 0,
          },
        });
        return;
      }
      feedbackSaved = true;
      await route.fulfill({
        status: 201,
        json: {
          id: "feedback-e2e-1",
          profile_id: profile.id,
          plan_version: 1,
          folder_id: tender.folder_id,
          verdict: "not_relevant",
          reason: "wrong_sector",
          note: null,
          tender: {
            title: tender.title,
            cpvs: tender.cpv,
          },
          state: "current",
          user_id: "owner-e2e",
          created_at: "2026-07-23T10:03:00Z",
          updated_at: "2026-07-23T10:03:00Z",
        },
      });
    },
  );
  await page.route(
    `**/api/v1/procurement-search-profiles/${profile.id}/feedback-digest`,
    async (route) => {
      await route.fulfill({
        json: {
          schema: "procurement-search-feedback-digest-v1",
          profile_id: profile.id,
          plan_version: profileVersion,
          digest_hash:
            "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
          feedback_state_hash:
            "abcdef0123456789abcdef0123456789abcdef0123456789abcdef0123456789",
          new_feedback_count: feedbackSaved ? 1 : 0,
          counts: {
            total: feedbackSaved ? 1 : 0,
            distinct_folders: feedbackSaved ? 1 : 0,
            relevant: 0,
            not_relevant: feedbackSaved ? 1 : 0,
          },
          reasons: {
            wrong_sector: feedbackSaved ? 1 : 0,
            amount: 0,
            region: 0,
            buyer: 0,
            other: 0,
          },
          exclusion_candidates: {
            terms: feedbackSaved
              ? [{ value: "limpieza", count: 1, relevant_count: 0, rejected_count: 1, delta: 1 }]
              : [],
            cpvs: [],
          },
          reinforcement_candidates: { terms: [], cpvs: [] },
          tokenizer_version: "spanish-procurement-stopwords-v1",
          taxonomy_version: "2008",
        },
      });
    },
  );
  await page.route(
    `**/api/v1/procurement-search-profiles/${profile.id}/replans`,
    async (route) => {
      await route.fulfill({
        status: 202,
        json: {
          artifact: replanArtifact,
          job: {
            id: "job-replan-1",
            status: "succeeded",
          },
        },
      });
    },
  );
  await page.route(
    `**/api/v1/procurement-search-profiles/${profile.id}/acceptances`,
    async (route) => {
      profileVersion = 2;
      await route.fulfill({ json: currentProfile() });
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
  await page
    .locator(".procurement-saved-searches")
    .getByRole("button", { name: "Activar vigilancia y avisos" })
    .click();
  await expect(
    page.locator(".procurement-saved-searches").getByRole("button", {
      name: "Pausar vigilancia",
    }),
  ).toBeVisible();
  await page
    .locator(".procurement-saved-searches")
    .getByRole("button", { name: "Ejecutar" })
    .click();
  await expect(page.getByText(tender.title)).toBeVisible();
  await expect(page.getByText("Nuevo", { exact: true })).toBeVisible();
  await page
    .getByRole("group", { name: `Valoración para ${tender.title}` })
    .getByRole("button", { name: "No relevante" })
    .click();
  await page.getByRole("button", { name: "Sector incorrecto" }).click();
  await expect(
    page.getByText("Lo tendremos en cuenta cuando pidas revisar el plan."),
  ).toBeVisible();
  await expect(
    page.getByText("1 feedback nuevos · 1 no relevantes · 0 relevantes"),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "Revisar el plan con este feedback" })
    .click();
  await expect(
    page.getByRole("heading", { name: "Revisa el plan antes de usarlo" }),
  ).toBeVisible();
  const diff = page.getByRole("region", { name: "Cambios respecto a v1" });
  await expect(diff).toBeVisible();
  await expect(page.getByText("Añadido · 2")).toBeVisible();
  await expect(diff.getByText("bomberos")).toBeVisible();
  await expect(diff.getByText("limpieza")).toBeVisible();
  await expect(page.getByText("Retirado · 1")).toBeVisible();
  await page.getByRole("button", { name: "Aceptar como v2" }).click();
  await expect(page.getByText("Plan aceptado · v2")).toBeVisible();
});
