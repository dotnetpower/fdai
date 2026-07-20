import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const root = new URL("../", import.meta.url);

test("architecture pages keep localized static fallbacks", async () => {
  const [english, korean] = await Promise.all([
    readFile(new URL("src/content/docs/architecture.md", root), "utf8"),
    readFile(new URL("src/content/docs/ko/architecture.md", root), "utf8"),
  ]);

  assert.match(english, /diagrams\/generated\/fdai-system-overview\.manifest\.json/);
  assert.match(english, /fdai-system-overview\.en\.svg/);
  assert.match(english, /locale="en"/);
  assert.match(korean, /diagrams\/generated\/fdai-system-overview\.ko\.svg/);
  assert.match(korean, /locale="ko"/);
});

test("generated viewer and bilingual manifest are present", async () => {
  const [viewer, manifestSource] = await Promise.all([
    readFile(new URL("public/diagrams/architecture-diagram.js", root), "utf8"),
    readFile(
      new URL(
        "public/diagrams/generated/fdai-system-overview.manifest.json",
        root,
      ),
      "utf8",
    ),
  ]);
  const manifest = JSON.parse(manifestSource);

  assert.match(viewer, /fdai-architecture-diagram/);
  assert.equal(manifest.assets.en.svg, "fdai-system-overview.en.svg");
  assert.equal(manifest.assets.ko.svg, "fdai-system-overview.ko.svg");
  assert.ok(manifest.nodes.length > 10);
});
