import { defineConfig, devices } from "@playwright/test";
export default defineConfig({
  testDir: "./tests/e2e",
  fullyParallel: false,
  workers: 1,
  retries: 0,
  expect: { timeout: 10000 },
  reporter: "list",
  use: {
    baseURL: "http://127.0.0.1:3000",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  webServer: [
    {
      command: "bash scripts/run-auth-e2e-api.sh",
      url: "http://127.0.0.1:5001/health/live",
      reuseExistingServer: false,
      timeout: 120000,
      gracefulShutdown: { signal: "SIGTERM", timeout: 10000 },
    },
    {
      command: "ORACLE_API_ORIGIN=http://127.0.0.1:5001 npm run dev",
      url: "http://127.0.0.1:3000",
      reuseExistingServer: false,
      timeout: 120000,
    },
  ],
  projects: [
    {
      name: "desktop",
      use: {
        ...devices["Desktop Chrome"],
        viewport: { width: 1440, height: 900 },
      },
    },
    {
      name: "mobile",
      use: {
        ...devices["Desktop Chrome"],
        viewport: { width: 390, height: 844 },
        isMobile: true,
        hasTouch: true,
      },
    },
  ],
});
