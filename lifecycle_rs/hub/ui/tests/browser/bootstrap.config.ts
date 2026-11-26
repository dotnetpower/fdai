import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: ".",
  testMatch: ["bootstrap.spec.ts", "bootstrap-session.integration.spec.ts"],
  timeout: 20_000,
  workers: 1,
  outputDir: "../../../../../.fdai/validation/bootstrap-browser",
  reporter: "line",
  use: { headless: true, browserName: "chromium", viewport: { width: 1440, height: 900 } },
});
