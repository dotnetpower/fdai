import { defineConfig } from "vite";
import { fileURLToPath } from "node:url";
import { privateSnapshotPlugin } from "./private-snapshot-plugin";

export default defineConfig({
  base: "./",
  plugins: [privateSnapshotPlugin()],
  server: {
    port: 5573,
    strictPort: true,
    fs: { allow: [
      fileURLToPath(new URL(".", import.meta.url)),
      fileURLToPath(new URL("../../site/scripts/og-nebula-bg.png", import.meta.url)),
    ] },
  },
  build: {
    rollupOptions: {
      output: { manualChunks: { three: ["three"] } },
    },
  },
});
