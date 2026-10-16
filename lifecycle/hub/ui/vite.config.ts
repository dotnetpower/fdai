/// <reference types="vitest/config" />

import { defineConfig } from "vite";
import preact from "@preact/preset-vite";

const hubApiUrl = process.env.FDAI_HUB_API_URL ?? "http://127.0.0.1:8090";

// The Hub operator UI: a small read-only SPA the Hub serves as static assets from
// `ui/dist` (see `fdai_lifecycle_hub.api.DEFAULT_UI_DIST`). `npm run dev` proxies
// `/v1` and `/healthz` to a Hub API running locally on 8090 (`fdai-lifecycle-hub serve`).
export default defineConfig({
  plugins: [preact()],
  build: {
    outDir: "dist",
    emptyOutDir: true,
    target: "es2022",
  },
  server: {
    port: 5290,
    strictPort: true,
    proxy: {
      "/v1": hubApiUrl,
      "/healthz": hubApiUrl,
      "/auth": hubApiUrl,
    },
  },
  test: {
    environment: "node",
    pool: "forks",
  },
});
