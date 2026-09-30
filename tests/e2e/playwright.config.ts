import { defineConfig, devices } from "@playwright/test";

/**
 * E2E tests run against a full stack in MOCK mode (see scripts/e2e.sh).
 * They never touch the real Cardmarket.
 */
const baseURL = process.env.E2E_BASE_URL ?? "http://localhost:3100";

export default defineConfig({
  testDir: "./specs",
  timeout: 90_000,
  expect: { timeout: 30_000 },
  fullyParallel: false,
  workers: 1,
  retries: process.env.CI ? 1 : 0,
  reporter: [["list"], ["html", { open: "never" }]],
  globalSetup: "./global-setup.ts",
  use: {
    baseURL,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    locale: "it-IT",
    timezoneId: "Europe/Rome",
  },
  projects: [
    { name: "mobile", use: { ...devices["Pixel 7"], storageState: ".auth/admin.json" } },
    {
      name: "desktop",
      use: { ...devices["Desktop Chrome"], storageState: ".auth/admin.json" },
      testIgnore: /session\.spec\.ts/, // stateful scenario: run once
    },
  ],
});
