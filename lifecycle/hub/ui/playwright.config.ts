import { defineConfig } from "@playwright/test";
import { tmpdir } from "node:os";
import { join } from "node:path";

export default defineConfig({
  testDir: "./tests/browser",
  timeout: 30_000,
  workers: 1,
  outputDir: join(tmpdir(), `fdai-hub-browser-${process.pid}`),
  use: { headless: true, browserName: "chromium" },
});
