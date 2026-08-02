import assert from "node:assert/strict";
import test from "node:test";

import {
  canonicalTextArtifact,
  compileDiagram,
  resolveCssFallbacks,
} from "../src/compiler.js";
import { parseDiagram } from "../src/model/validate.js";
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

test("manifest preserves optional edge sequence steps", async () => {
  const spec = parseDiagram(`
id: manifest-step
version: 1
kind: data-flow
locales:
  en: { title: Step, description: Step, alt: Source to target. }
  ko: { title: Step, description: Step, alt: Source에서 target으로 이동합니다. }
canvas: { width: 640, height: 360, direction: RIGHT }
groups: []
nodes:
  - id: source
    kind: external
    label: { en: Source, ko: Source }
  - id: target
    kind: service
    label: { en: Target, ko: Target }
edges:
  - id: flow
    from: source
    to: target
    kind: event
    step: 2
`);
  const artifacts = await compileDiagram(spec);
  const manifestArtifact = artifacts.find(
    (artifact) => artifact.path === "manifest-step.manifest.json",
  );
  assert.ok(manifestArtifact);
  const manifest = JSON.parse(manifestArtifact.content.toString("utf8")) as {
    edges: Array<{ step?: number }>;
  };
  assert.equal(manifest.edges[0]?.step, 2);
});
