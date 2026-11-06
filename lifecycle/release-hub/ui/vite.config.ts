/// <reference types="vitest/config" />
import { fileURLToPath } from "node:url";
import { defineConfig } from "vite";
import preact from "@preact/preset-vite";

const fromNodeModules = (subpath: string): string =>
  fileURLToPath(new URL(`./node_modules/${subpath}`, import.meta.url));

export default defineConfig({
  plugins: [preact()],
  resolve: {
    alias: [
      { find: "@azure/msal-browser", replacement: fromNodeModules("@azure/msal-browser") },
      { find: /^preact\/jsx-(?:dev-)?runtime$/, replacement: fromNodeModules("preact/jsx-runtime") },
      { find: "preact/hooks", replacement: fromNodeModules("preact/hooks") },
      { find: "preact/compat", replacement: fromNodeModules("preact/compat") },
      { find: /^preact$/, replacement: fromNodeModules("preact") },
    ],
    dedupe: ["@azure/msal-browser", "preact"],
  },
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
