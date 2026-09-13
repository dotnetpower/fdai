import { readFile, stat } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import type { IncomingMessage, ServerResponse } from "node:http";
import type { Plugin } from "vite";
import { execFile } from "node:child_process";
import { promisify } from "node:util";

export const DATABASE_SNAPSHOT_ROUTE = "/__neural/ontology";
const snapshotPath = fileURLToPath(new URL("../../.fdai/neural-view/ontology.json", import.meta.url));
const repoRoot = fileURLToPath(new URL("../../", import.meta.url));
const exporter = fileURLToPath(new URL("./scripts/export_database_map.py", import.meta.url));
const execute = promisify(execFile);
let refresh: Promise<void> | null = null;

function refreshLocalDatabase() {
  refresh ??= execute("uv", ["run", "--no-sync", "python", exporter], {
    cwd: repoRoot, timeout: 45000, maxBuffer: 64000,
  }).then(() => {}).finally(() => { refresh = null; });
  return refresh;
}

/** Serve only the fixed, pseudonymized private export, never a caller-supplied filesystem path. */
export function privateSnapshotHandler(path = snapshotPath, refreshSnapshot: () => Promise<void> = refreshLocalDatabase) {
  return async (request: IncomingMessage, response: ServerResponse, next: () => void) => {
    if (request.url?.split("?")[0] !== DATABASE_SNAPSHOT_ROUTE) { next(); return; }
    response.setHeader("Cache-Control", "no-store");
    response.setHeader("X-Content-Type-Options", "nosniff");
    response.setHeader("Content-Type", "application/json; charset=utf-8");
    if (request.method !== "GET") {
      response.statusCode = 405;
      response.end(JSON.stringify({ error: "read-only" }));
      return;
    }
    try {
      await refreshSnapshot();
      const metadata = await stat(path);
      if (!metadata.isFile() || metadata.size > 50_000_000) throw new Error("snapshot-size");
      const content = await readFile(path);
      response.end(content);
    } catch {
      response.statusCode = 503;
      response.end(JSON.stringify({ error: "local-ontology-export-unavailable", action: "npm run snapshot:db" }));
    }
  };
}

export function privateSnapshotPlugin(): Plugin {
  return {
    name: "neural-private-ontology-snapshot",
    configureServer(server) { server.middlewares.use(privateSnapshotHandler()); },
    configurePreviewServer(server) { server.middlewares.use(privateSnapshotHandler()); },
  };
}
