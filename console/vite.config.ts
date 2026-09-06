/// <reference types="vitest/config" />

import { defineConfig, loadEnv, type UserConfig } from "vite";
import preact from "@preact/preset-vite";
import { cssHotUpdateGuard } from "./src/vite-css-hmr-guard";

export function resolveViteCacheDir(env: Readonly<Record<string, string>>): string {
  return env.VITE_CACHE_DIR || "node_modules/.vite";
}

export const PREACT_PLUGIN_OPTIONS = { prefreshEnabled: false } as const;

/** Offline builds never read local deployment env files or expose process VITE values. */
export function offlineBuildOptions(mode: string): Pick<UserConfig, "envDir" | "envPrefix" | "define"> {
  return mode === "offline"
    ? {
      envDir: false,
      envPrefix: [],
      define: { "import.meta.env.VITE_REQUIRE_RUNTIME_CONFIG": JSON.stringify("1") },
    }
    : {};
}

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
  const offline = mode === "offline";
  const env = offline ? {} : loadEnv(mode, process.cwd(), "");
  return {
    ...offlineBuildOptions(mode),
    base: env.VITE_CONSOLE_BASE_PATH ?? "/",
    cacheDir: resolveViteCacheDir(env),
    plugins: [cssHotUpdateGuard(), preact(PREACT_PLUGIN_OPTIONS)],
    build: {
      outDir: offline ? "dist/offline" : "dist",
      emptyOutDir: true,
      sourcemap: !offline,
      assetsInlineLimit: 0,
      target: "es2022",
      manifest: true,
      // Mermaid renderers are lazy; check:entry owns the stricter initial budget.
      chunkSizeWarningLimit: 700,
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
      maxWorkers: 4,
    },
  };
});
