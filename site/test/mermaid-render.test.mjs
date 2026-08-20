import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const config = await readFile(new URL("../astro.config.mjs", import.meta.url), "utf8");

test("site uses the FDAI diagram viewer without a Mermaid runtime", () => {
  assert.match(config, /DIAGRAM_VIEWER_SCRIPT/);
  assert.match(config, /remarkFdaiDiagrams/);
  assert.doesNotMatch(config, /remarkMermaid/);
  assert.doesNotMatch(config, /cdn\.jsdelivr\.net\/npm\/mermaid/);
  assert.doesNotMatch(config, /pre\.mermaid/);
});
