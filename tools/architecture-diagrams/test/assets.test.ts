import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { readFile } from "node:fs/promises";
import test from "node:test";

const assets = new URL("../assets/", import.meta.url);

function sha256(value: Uint8Array): string {
  return createHash("sha256").update(value).digest("hex");
}

async function assertLockedIcons(catalog: string): Promise<void> {
  const lock = JSON.parse(
    await readFile(new URL(`${catalog}/icons.lock.json`, assets), "utf8"),
  );

  for (const [id, entry] of Object.entries(lock.icons)) {
    const typedEntry = entry as {
      file: string;
      mediaType?: string;
      sha256: string;
      source?: string;
      sourcePage?: string;
    };
    const source = await readFile(new URL(`${catalog}/${typedEntry.file}`, assets));
    const payload = source.at(-1) === 0x0a ? source.subarray(0, -1) : source;
    assert.equal(sha256(payload), typedEntry.sha256, id);
    assert.equal(
      typedEntry.mediaType ?? "image/svg+xml",
      typedEntry.file.endsWith(".png") ? "image/png" : "image/svg+xml",
      id,
    );
    if (typedEntry.file.endsWith(".svg")) {
      const svg = source.toString("utf8");
      assert.doesNotMatch(svg, /<(?:script|foreignObject)\b/iu, id);
      assert.doesNotMatch(
        svg,
        /\bsrc\s*=|\bhref\s*=\s*["'](?!#)/iu,
        id,
      );
    }
    if (catalog === "brands") {
      assert.match(typedEntry.source ?? "", /^https:\/\//u, `${id} source`);
      assert.match(
        typedEntry.sourcePage ?? "",
        /^https:\/\//u,
        `${id} sourcePage`,
      );
    }
  }
}

test("vendored Azure icon payloads match the provenance lock", async () => {
  await assertLockedIcons("azure");
});

test("vendored brand icon payloads match the provenance lock", async () => {
  await assertLockedIcons("brands");
});

test("the deterministic diagram font matches its provenance lock", async () => {
  const lock = JSON.parse(
    await readFile(new URL("fonts/font.lock.json", assets), "utf8"),
  );
  const font = await readFile(new URL(`fonts/${lock.subset}`, assets));
  assert.equal(sha256(font), lock.subsetSha256);
});

test("the fixed pantheon manifest resolves 15 safe agent icons", async () => {
  const iconDirectory = new URL(
    "../../../console/public/agent-icons/",
    import.meta.url,
  );
  const manifest = JSON.parse(
    await readFile(new URL("manifest.json", iconDirectory), "utf8"),
  ) as {
    agents: Array<{ name: string; file: string }>;
  };

  assert.equal(manifest.agents.length, 15);
  assert.equal(new Set(manifest.agents.map((agent) => agent.name)).size, 15);
  for (const agent of manifest.agents) {
    const source = await readFile(new URL(agent.file, iconDirectory), "utf8");
    assert.match(source, /^<svg [^>]*viewBox="0 0 24 24"/);
    assert.doesNotMatch(source, /<(?:script|foreignObject)\b|\b(?:href|src)\s*=/iu);
  }
});
