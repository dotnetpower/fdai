import { defineConfig, devices } from "@playwright/test";
import { acquirePlaywrightPortLease } from "./scripts/playwright-port-pool";

const portLease = acquirePlaywrightPortLease();
const port = portLease.frontendPort;
const baseURL = `http://127.0.0.1:${port}`;

export default defineConfig({
  testDir: "./tests/e2e",
  testMatch: "**/*.spec.ts",
  fullyParallel: true,
  forbidOnly: Boolean(process.env.CI),
  retries: process.env.CI ? 1 : 0,
  ...(process.env.CI ? { workers: 1 } : {}),
  reporter: process.env.CI ? "github" : "list",
  outputDir: `test-results/slot-${portLease.slot}`,
  use: {
    baseURL,
    trace: "on-first-retry",
    screenshot: "only-on-failure",
    video: "retain-on-failure",
  },
  webServer: {
    command:
      `VITE_DEV_MODE=1 VITE_LOCAL_LOGIN_PROMPT=0 ` +
      `VITE_OPERATOR_API_BASE_URL=${baseURL}/api npm run dev -- ` +
      `--host 127.0.0.1 --port ${port} --strictPort`,
    wait: { stdout: /ready in/ },
    stdout: "ignore",
    stderr: "pipe",
    timeout: 60_000,
  },
  projects: [
    { name: "desktop-chromium", use: { ...devices["Desktop Chrome"] } },
    { name: "mobile-chromium", use: { ...devices["Pixel 7"] } },
  ],
});
