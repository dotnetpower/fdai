import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { readFile } from "node:fs/promises";
import test from "node:test";

const assets = new URL("../assets/", import.meta.url);

function sha256(value: Uint8Array): string {
  return createHash("sha256").update(value).digest("hex");
}

test("vendored Azure icon payloads match the provenance lock", async () => {
  const lock = JSON.parse(
    await readFile(new URL("azure/icons.lock.json", assets), "utf8"),
  );

  for (const [id, entry] of Object.entries(lock.icons)) {
    const typedEntry = entry as { file: string; sha256: string };
    const source = await readFile(new URL(`azure/${typedEntry.file}`, assets));
    const payload = source.at(-1) === 0x0a ? source.subarray(0, -1) : source;
    assert.equal(sha256(payload), typedEntry.sha256, id);
  }
});

test("the deterministic diagram font matches its provenance lock", async () => {
  const lock = JSON.parse(
    await readFile(new URL("fonts/font.lock.json", assets), "utf8"),
  );
  const font = await readFile(new URL(`fonts/${lock.subset}`, assets));
  assert.equal(sha256(font), lock.subsetSha256);
});
