/// <reference types="vitest/config" />

import { defineConfig, loadEnv } from "vite";
import preact from "@preact/preset-vite";

// Console SPA build config.
//
// - `outDir: "dist"` produces static artifacts under `console/dist/`
//   (excluded from git via `.gitignore`). The build output is what
//   `infra/modules/console/` uploads to Azure Static Web Apps.
// - `base` - the console is served from an origin root by default.
//   Override with `VITE_CONSOLE_BASE_PATH` at build time when mounting
//   under a subpath.
// - `assetsInlineLimit: 0` - never inline assets, so the CSP header the
//   fork attaches at Static Web App level is not disturbed by base64
//   data URIs the console never asked for.
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "");
  return {
    base: env.VITE_CONSOLE_BASE_PATH ?? "/",
    plugins: [preact()],
    build: {
      outDir: "dist",
      emptyOutDir: true,
      sourcemap: true,
      assetsInlineLimit: 0,
      target: "es2022",
      manifest: true,
    },
    server: {
      port: 5273,
      strictPort: true,
    },
    test: {
      // Backend stream tests normally take 3-4 seconds; retain a bounded
      // allowance and avoid saturating shared runners after the Python suite.
      testTimeout: 15_000,
      pool: "forks",
      poolOptions: {
        forks: {
          minForks: 1,
          maxForks: 4,
        },
      },
    },
  };
});
