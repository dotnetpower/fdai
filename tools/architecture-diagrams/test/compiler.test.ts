import assert from "node:assert/strict";
import test from "node:test";

import { resolveCssFallbacks } from "../src/compiler.js";

test("resolves diagram CSS variable fallbacks for static PNG rendering", () => {
  assert.equal(
    resolveCssFallbacks(
      "fill: var(--fdai-diagram-canvas, #faf9f8); color: var(--fdai-diagram-text, #323130);",
    ),
    "fill: #faf9f8; color: #323130;",
  );
});
