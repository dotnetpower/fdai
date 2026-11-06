/// <reference types="vitest/config" />
import { fileURLToPath } from "node:url";
import { defineConfig } from "vite";
import preact from "@preact/preset-vite";

const fromNodeModules = (subpath: string): string =>
  fileURLToPath(new URL(`./node_modules/${subpath}`, import.meta.url));

export default defineConfig({
  plugins: [preact()],
  resolve: {
    alias: {
      "@azure/msal-browser": fromNodeModules("@azure/msal-browser"),
      "preact/jsx-runtime": fromNodeModules("preact/jsx-runtime"),
      "preact/hooks": fromNodeModules("preact/hooks"),
      "preact/compat": fromNodeModules("preact/compat"),
      preact: fromNodeModules("preact"),
    },
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
