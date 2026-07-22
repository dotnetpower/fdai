import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const config = await readFile(new URL("../astro.config.mjs", import.meta.url), "utf8");

test("initial and theme-triggered Mermaid renders are serialized", () => {
  assert.match(config, /if \(rendering\) \{\s*rerenderRequested = true;/);
  assert.match(config, /do \{[\s\S]*await mermaid\.run\([\s\S]*while \(rerenderRequested\)/);
  assert.match(config, /renderAll\(\)\.catch\(\(error\) => console\.error/);
});
