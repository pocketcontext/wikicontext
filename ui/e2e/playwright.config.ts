import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: ".",
  testMatch: "*.spec.ts",
  workers: 1,
  fullyParallel: false,
  timeout: 45_000,
  expect: { timeout: 10_000 },
  reporter: "list",
  outputDir: process.env.WIKICONTEXT_TEST_OUTPUT,
  use: {
    baseURL: process.env.WIKICONTEXT_TEST_URL,
    browserName: "chromium",
    headless: true,
  },
});
