import { defineConfig } from "@playwright/test";
import path from "node:path";

const suppliedUrl = process.env.FDAI_SITE_TEST_BASE_URL;
const baseURL = suppliedUrl ?? "http://127.0.0.1:4322/fdai/";
const target = new URL(baseURL);
if (target.protocol !== "http:" || !["127.0.0.1", "localhost"].includes(target.hostname)) {
  throw new Error("Documentation UI tests require an explicit loopback HTTP server.");
}

const evidence = path.resolve(import.meta.dirname, "../.fdai/site-ui-tests");

export default defineConfig({
  testDir: "./test/ui",
  timeout: 45_000,
  expect: { timeout: 10_000 },
  globalTimeout: 600_000,
  workers: 1,
  retries: 0,
  outputDir: path.join(evidence, "results"),
  reporter: [["line"], ["json", { outputFile: path.join(evidence, "results.json") }]],
  use: {
    baseURL,
    browserName: "chromium",
    contextOptions: { reducedMotion: "reduce" },
    navigationTimeout: 20_000,
    actionTimeout: 10_000,
    screenshot: "only-on-failure",
    trace: "retain-on-failure",
  },
  projects: [
    { name: "desktop", use: { viewport: { width: 1440, height: 900 } } },
    { name: "constrained", use: { viewport: { width: 993, height: 641 } } },
    { name: "mobile", use: { viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true } },
    { name: "reflow", use: { viewport: { width: 320, height: 844 }, isMobile: true, hasTouch: true } },
  ],
  webServer: suppliedUrl ? undefined : {
    command: "npm run preview -- --host 127.0.0.1 --port 4322",
    url: baseURL,
    reuseExistingServer: false,
    timeout: 25_000,
  },
});
