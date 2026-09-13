import { defineConfig } from "vite";
import { privateSnapshotPlugin } from "./private-snapshot-plugin";

export default defineConfig({
  base: "./",
  plugins: [privateSnapshotPlugin()],
  server: { port: 5573, strictPort: true },
  build: {
    rollupOptions: {
      output: { manualChunks: { three: ["three"] } },
    },
  },
});
