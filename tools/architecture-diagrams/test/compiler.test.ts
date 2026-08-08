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
  assert.equal(canonicalTextArtifact("<svg>  \n  </svg>\t").toString(), "<svg>\n  </svg>\n");
});

test("resolves diagram CSS variable fallbacks for static PNG rendering", () => {
  assert.equal(
    resolveCssFallbacks(
      "fill: var(--fdai-diagram-canvas, #faf9f8); color: var(--fdai-diagram-text); stroke: var(--custom, #abcdef); outline: var(--unknown);",
    ),
    "fill: #f6f7f6; color: #20262d; stroke: #abcdef; outline: var(--unknown);",
  );
});

test("viewer bundle preserves readable UTF-8 Korean labels", async () => {
  const artifact = await buildViewerArtifact();
  const source = artifact.content.toString("utf8");

  assert.match(source, /인터랙티브 아키텍처 다이어그램/);
  assert.match(source, /--fdai-diagram-tone-policy-fill:\s*#17331d/);
  assert.match(source, /data-embedded/);
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

test("manifest preserves conceptual node presentation and localized content", async () => {
  const spec = parseDiagram(`
id: manifest-concept
version: 1
kind: conceptual-flow
locales:
  en: { title: Concept, description: Concept, alt: A conceptual node. }
  ko: { title: 개념, description: 개념, alt: 개념 노드입니다. }
canvas: { width: 640, height: 360, direction: RIGHT, profile: conceptual }
groups: []
nodes:
  - id: decision
    kind: decision
    shape: diamond
    tone: policy
    badge: 4
    label: { en: Decide, ko: 결정 }
    content:
      - { en: Evaluate policy, ko: 정책 평가 }
edges: []
`);
  const artifacts = await compileDiagram(spec);
  const manifestArtifact = artifacts.find(
    (artifact) => artifact.path === "manifest-concept.manifest.json",
  );
  assert.ok(manifestArtifact);
  const manifest = JSON.parse(manifestArtifact.content.toString("utf8")) as {
    nodes: Array<{
      shape?: string;
      tone?: string;
      badge?: number;
      content?: Array<Record<string, string>>;
    }>;
  };
  assert.deepEqual(manifest.nodes[0], {
    id: "decision",
    kind: "decision",
    shape: "diamond",
    tone: "policy",
    badge: 4,
    label: { en: "Decide", ko: "결정" },
    description: { en: "Decide", ko: "결정" },
    content: [{ en: "Evaluate policy", ko: "정책 평가" }],
  });
});

test("SVG-only diagrams omit PNG artifacts and manifest references", async () => {
  const spec = parseDiagram(`
id: svg-only
version: 1
kind: deployment
formats: [svg]
locales:
  en: { title: SVG, description: SVG, alt: SVG diagram. }
  ko: { title: SVG, description: SVG, alt: SVG diagram입니다. }
canvas: { width: 640, height: 360, direction: RIGHT }
groups: []
nodes:
  - id: service
    kind: service
    label: { en: Service, ko: Service }
edges: []
`);
  const artifacts = await compileDiagram(spec);
  assert.ok(artifacts.some((artifact) => artifact.path === "svg-only.en.svg"));
  assert.ok(artifacts.every((artifact) => !artifact.path.endsWith(".png")));
  const manifestArtifact = artifacts.find(
    (artifact) => artifact.path === "svg-only.manifest.json",
  );
  assert.ok(manifestArtifact);
  const manifest = JSON.parse(manifestArtifact.content.toString("utf8")) as {
    assets: {
      en: { svg: string; png?: string };
      ko: { svg: string; png?: string };
    };
  };
  assert.equal(manifest.assets.en.png, undefined);
  assert.equal(manifest.assets.ko.png, undefined);
});
