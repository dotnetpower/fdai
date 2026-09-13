import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./tests/browser",
  fullyParallel: false,
  workers: 1,
  timeout: 30000,
  reporter: "list",
  use: {
    baseURL: "http://127.0.0.1:5573",
    viewport: { width: 1440, height: 900 },
    launchOptions: { args: ["--enable-unsafe-swiftshader"] },
    screenshot: "only-on-failure",
    trace: "retain-on-failure",
  },
  webServer: {
    command: "npm run dev",
    url: "http://127.0.0.1:5573",
    reuseExistingServer: !process.env.CI,
    timeout: 30000,
  },
});
