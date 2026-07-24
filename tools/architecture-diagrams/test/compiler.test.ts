import assert from "node:assert/strict";
import test from "node:test";

import { canonicalTextArtifact, resolveCssFallbacks } from "../src/compiler.js";
import { buildViewerArtifact } from "../src/viewer/build.js";

test("canonical text artifacts end with exactly one newline", () => {
  assert.equal(canonicalTextArtifact("<svg></svg>").toString(), "<svg></svg>\n");
  assert.equal(canonicalTextArtifact("<svg></svg>\n\n").toString(), "<svg></svg>\n");
});

test("resolves diagram CSS variable fallbacks for static PNG rendering", () => {
  assert.equal(
    resolveCssFallbacks(
      "fill: var(--fdai-diagram-canvas, #faf9f8); color: var(--fdai-diagram-text, #323130);",
    ),
    "fill: #faf9f8; color: #323130;",
  );
});

test("viewer bundle preserves readable UTF-8 Korean labels", async () => {
  const artifact = await buildViewerArtifact();
  const source = artifact.content.toString("utf8");

  assert.match(source, /인터랙티브 아키텍처 다이어그램/);
  assert.doesNotMatch(source, /\\u(?:11|31|[a-dA-D])[0-9a-fA-F]{2}/);
});
