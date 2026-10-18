/// <reference types="vitest/config" />
import { defineConfig } from "vite";
import preact from "@preact/preset-vite";

export default defineConfig({
  plugins: [preact()],
  resolve: { dedupe: ["@azure/msal-browser"] },
  publicDir: "../../hub/ui/public",
  server: {
    host: "127.0.0.1",
    port: 5291,
    strictPort: true,
    proxy: { "/v1": "http://127.0.0.1:8091", "/healthz": "http://127.0.0.1:8091", "/auth": "http://127.0.0.1:8091" },
    fs: { allow: ["../../.."] },
  },
  build: { target: "es2022" },
  test: { environment: "node", pool: "forks" },
});
