import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

import { compileDiagram } from "../src/compiler.js";
import { layoutDiagram } from "../src/layout/elk.js";
import { parseDiagram } from "../src/model/validate.js";
import { renderSvg } from "../src/render/svg.js";

const source = `
id: conceptual-flow-sample
version: 1
kind: conceptual-flow
locales:
  en: { title: Conceptual flow, description: A governed feedback loop, alt: Input flows through a policy decision and returns as feedback. }
  ko: { title: 개념 흐름, description: 통제된 피드백 루프, alt: 입력이 정책 결정을 거쳐 피드백으로 돌아옵니다. }
canvas: { width: 960, height: 540, direction: RIGHT, profile: conceptual }
groups:
  - id: decision-lane
    kind: layer
    presentation: lane
    label: { en: Decision flow, ko: 결정 흐름 }
nodes:
  - id: input
    parent: decision-lane
    kind: external
    shape: terminator
    tone: input
    badge: 1
    label: { en: Natural-language input, ko: 자연어 입력 }
    content:
      - { en: Intent and context, ko: 의도와 컨텍스트 }
  - id: policy
    parent: decision-lane
    kind: decision
    shape: diamond
    tone: policy
    badge: 2
    label: { en: Policy decision, ko: 정책 결정 }
edges:
  - id: decide
    from: input
    to: policy
    kind: request
  - id: improve
    from: policy
    to: input
    kind: feedback
    route: curve
    label: { en: Improve, ko: 개선 }
legend:
  - tone: input
    label: { en: Input, ko: 입력 }
  - kind: feedback
    label: { en: Feedback loop, ko: 피드백 루프 }
`;

const canonicalUrl = new URL(
  "../../../docs/diagrams/fdai-conceptual-control-loop.diagram.yaml",
  import.meta.url,
);

test("renders conceptual shapes, content, tones, and feedback semantics", async () => {
  const spec = parseDiagram(source);
  const layout = await layoutDiagram(spec);
  const svg = await renderSvg(spec, layout, "ko");

  assert.match(svg, /data-profile="conceptual"/);
  assert.match(svg, /data-shape="terminator" data-tone="input"/);
  assert.match(svg, /data-shape="diamond" data-tone="policy"/);
  assert.match(svg, /class="node-body"/);
  assert.match(svg, /class="node-accent"/);
  assert.match(svg, /class="group-accent"/);
  assert.match(svg, /의도와 컨텍스트/);
  assert.match(svg, /class="node-badge"/);
  assert.match(svg, /class="diagram-edge edge-feedback"/);
  assert.match(svg, /class="legend-swatch"/);
});

test("compiles the canonical conceptual control loop in both locales", async () => {
  const spec = parseDiagram(await readFile(canonicalUrl, "utf8"));
  const layout = await layoutDiagram(spec);
  const governedFlowHeights = spec.nodes
    .filter((node) => node.parent === "governed-flow")
    .map((node) => layout.nodes.get(node.id)?.height);
  assert.equal(new Set(governedFlowHeights).size, 1);
  const artifacts = await compileDiagram(spec);
  const paths = artifacts.map((artifact) => artifact.path);

  assert.deepEqual(paths, [
    "fdai-conceptual-control-loop.en.svg",
    "fdai-conceptual-control-loop.en.png",
    "fdai-conceptual-control-loop.ko.svg",
    "fdai-conceptual-control-loop.ko.png",
    "fdai-conceptual-control-loop.manifest.json",
  ]);
  const koreanSvg = artifacts.find(
    (artifact) => artifact.path === "fdai-conceptual-control-loop.ko.svg",
  );
  assert.match(koreanSvg!.content.toString("utf8"), /통제형 자동화 아키텍처/);
  assert.match(koreanSvg!.content.toString("utf8"), /class="node-icon-backplate"/);
});
