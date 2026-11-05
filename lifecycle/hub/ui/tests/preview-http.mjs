// Bounded loopback smoke check; HTTP evidence is not browser-rendering evidence.
// Run from the repository root: node lifecycle/hub/ui/tests/preview-http.mjs
import { spawn } from "node:child_process";
import { fileURLToPath } from "node:url";
import assert from "node:assert/strict";

const hubs = [
  { directory: new URL("../../../release-hub/ui/", import.meta.url), port: 5291, designs: ["edition"] },
  { directory: new URL("../", import.meta.url), port: 5290, designs: ["atlas", "timeline", "ledger"] },
];
const children = [];
const deadline = Date.now() + 20_000;
try {
  for (const hub of hubs) {
    const origin = `http://127.0.0.1:${hub.port}`;
    // Never adopt an unknown listener or steal an occupied port.
    const { createServer } = await import("node:net");
    const probe = createServer();
    await new Promise((resolve, reject) => { probe.once("error", reject); probe.listen(hub.port, "127.0.0.1", resolve); });
    await new Promise((resolve) => probe.close(resolve));
    const child = spawn("npm", ["run", "dev", "--", "--host", "127.0.0.1", "--port", String(hub.port), "--strictPort"], {
      cwd: fileURLToPath(hub.directory), stdio: ["ignore", "pipe", "pipe"], detached: true,
    });
    children.push(child);
    child.stdout.resume(); child.stderr.resume();
    let ready = false;
    while (!ready && Date.now() < deadline) {
      assert.equal(child.exitCode, null, "Preview server exited before readiness");
      try { ready = (await fetch(origin, { signal: AbortSignal.timeout(500) })).ok; }
      catch { ready = false; /* Startup is not ready; the shared deadline remains authoritative. */ }
      if (!ready) await new Promise((resolve) => setTimeout(resolve, 100));
    }
    assert.ok(ready, "Preview server startup deadline exceeded");
    for (const design of hub.designs) {
      const url = `${origin}/design-previews/${design}`;
      const response = await fetch(url, { signal: AbortSignal.timeout(2000) });
      assert.equal(response.status, 200);
      assert.match(await response.text(), /src\/design-previews\/entry.tsx/);
      console.log(JSON.stringify({ url, status: 200, evidence: "HTTP entry only" }));
    }
    for (const path of ["/src/design-previews/entry.tsx", "/src/design-previews/previews.tsx", "/brand/fdai-logo.png"]) {
      const response = await fetch(`${origin}${path}`, { signal: AbortSignal.timeout(2000) });
      assert.equal(response.status, 200, `Preview asset failed: ${path}`);
    }
    assert.equal(child.exitCode, null);
    console.log(JSON.stringify({ port: hub.port, aliveAfterRequests: true, lifetime: "this invocation only" }));
  }
} finally {
  // Only process groups created above are stopped. Operator processes are never touched.
  for (const child of children) {
    if (child.pid && child.exitCode === null) process.kill(-child.pid, "SIGTERM");
  }
}
