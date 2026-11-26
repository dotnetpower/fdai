import { defineConfig } from "@playwright/test";
import { fileURLToPath } from "node:url";
import base from "./playwright.config";

// Test-owned loopback servers only. Occupied ports fail rather than reusing or stopping
// an operator's process. Playwright owns these children for this one bounded invocation.
export default defineConfig(base, {
  testMatch: "design-previews.spec.ts",
  globalTimeout: 180_000,
  metadata: { previewRuntime: true },
  webServer: [
    {
      command: "npm run dev -- --host 127.0.0.1 --port 5291 --strictPort",
      cwd: fileURLToPath(new URL("../../release-hub/ui/", import.meta.url)),
      url: "http://127.0.0.1:5291/design-previews/edition",
      reuseExistingServer: false,
      timeout: 30_000,
    },
    {
      command: "npm run dev -- --host 127.0.0.1 --port 5290 --strictPort",
      cwd: fileURLToPath(new URL("./", import.meta.url)),
      url: "http://127.0.0.1:5290/design-previews/atlas",
      reuseExistingServer: false,
      timeout: 30_000,
    },
  ],
});
