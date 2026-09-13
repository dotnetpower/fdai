import assert from "node:assert/strict";
import { test } from "node:test";
import { createServer } from "node:http";
import { mkdtemp, writeFile, unlink, rmdir } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { privateSnapshotHandler } from "../private-snapshot-plugin";

test("private reader serves only its fixed GET route and never returns stale data after refresh failure", async () => {
  const directory = await mkdtemp(join(tmpdir(), "fdai-neural-route-"));
  const file = join(directory, "ontology.json");
  await writeFile(file, '{"source":"unit-test-only"}', { mode: 0o600 });
  let refreshes = 0;
  let fail = false;
  const handler = privateSnapshotHandler(file, async () => { refreshes++; if (fail) throw new Error("fixture"); });
  const server = createServer((request, response) => {
    void handler(request, response, () => { response.statusCode = 404; response.end(); });
  });
  await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
  const address = server.address();
  if (!address || typeof address === "string") throw new Error("Test server has no TCP address.");
  const origin = `http://127.0.0.1:${address.port}`;
  try {
    const get = await fetch(`${origin}/__neural/ontology`);
    assert.equal(get.status, 200);
    assert.equal(get.headers.get("cache-control"), "no-store");
    assert.deepEqual(await get.json(), { source: "unit-test-only" });
    assert.equal((await fetch(`${origin}/__neural/ontology`, { method: "POST" })).status, 405);
    assert.equal((await fetch(`${origin}/__neural/anything`)).status, 404);
    assert.equal(refreshes, 1);
    fail = true;
    assert.equal((await fetch(`${origin}/__neural/ontology`)).status, 503);
  } finally {
    await new Promise<void>((resolve, reject) => server.close((error) => error ? reject(error) : resolve()));
    await unlink(file);
    await rmdir(directory);
  }
});
