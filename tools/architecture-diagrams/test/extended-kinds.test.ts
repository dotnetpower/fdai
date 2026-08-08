import assert from "node:assert/strict";
import test from "node:test";

import { layoutDiagram } from "../src/layout/elk.js";
import { assertLayoutIntegrity } from "../src/layout/integrity.js";
import type { DiagramKind, DiagramSpec } from "../src/model/types.js";
import { validateDiagram } from "../src/model/validate.js";
import { renderSvg } from "../src/render/svg.js";

function base(kind: DiagramKind, nodes: DiagramSpec["nodes"], edges: DiagramSpec["edges"] = []): DiagramSpec {
  return validateDiagram({
    id: `${kind}-extended-sample`,
    version: 1,
    kind,
    locales: {
      en: { title: "Extended", description: "Extended", alt: "Extended diagram." },
      ko: { title: "확장", description: "확장", alt: "확장 다이어그램입니다." },
    },
    canvas: { width: 800, height: 520, direction: "RIGHT" },
    groups: [],
    nodes,
    edges,
  });
}

test("pie strategy produces distinct arc paths and themed slices", async () => {
  const spec = base("pie", [
    { id: "rules", kind: "process", shape: "pie-slice", value: 55, label: { en: "Rules", ko: "규칙" } },
    { id: "reuse", kind: "process", shape: "pie-slice", value: 30, label: { en: "Reuse", ko: "재사용" } },
    { id: "reasoning", kind: "process", shape: "pie-slice", value: 15, label: { en: "Reasoning", ko: "추론" } },
  ]);
  const layout = await layoutDiagram(spec);
  assert.equal(new Set([...layout.nodes.values()].map((node) => node.path)).size, 3);
  assertLayoutIntegrity(spec, layout);
  const svg = await renderSvg(spec, layout, "ko");
  assert.match(svg, /data-shape="pie-slice"/);
  assert.match(svg, /A[\d.]+ [\d.]+ 0 [01] 1/);
  assert.match(svg, /data-node-id="rules"[^>]+transform="translate\(48 112\)"/);
  assert.match(svg, /class="chart-leader"/);
});

test("coordinate strategy maps values onto chart axes", async () => {
  const spec = base("quadrant", [
    { id: "safe", kind: "process", shape: "circle", xValue: 20, yValue: 80, label: { en: "Safe", ko: "안전" } },
    { id: "risky", kind: "process", shape: "circle", xValue: 80, yValue: 20, label: { en: "Risky", ko: "위험" } },
  ]);
  const layout = await layoutDiagram(spec);
  assert.ok(layout.nodes.get("risky")!.x > layout.nodes.get("safe")!.x);
  assert.ok(layout.nodes.get("risky")!.y > layout.nodes.get("safe")!.y);
});

test("grid strategy creates stable Kanban columns", async () => {
  const spec = validateDiagram({
    ...base("block", [{ id: "placeholder", kind: "process", label: { en: "Placeholder", ko: "자리표시자" } }]),
    id: "kanban-extended-sample",
    kind: "kanban",
    groups: [
      { id: "queued", kind: "layer", presentation: "lane", label: { en: "Queued", ko: "대기" } },
      { id: "doing", kind: "layer", presentation: "lane", label: { en: "Doing", ko: "진행" } },
    ],
    nodes: [
      { id: "proposal", parent: "queued", kind: "process", label: { en: "Proposal", ko: "제안" } },
      { id: "validation", parent: "doing", kind: "process", label: { en: "Validation", ko: "검증" } },
    ],
  });
  const layout = await layoutDiagram(spec);
  assert.ok(layout.groups.get("doing")!.x > layout.groups.get("queued")!.x);
  assertLayoutIntegrity(spec, layout);
});

test("radar strategy scales points by value", async () => {
  const spec = base("radar", [
    { id: "safety", kind: "process", shape: "circle", value: 90, label: { en: "Safety", ko: "안전" } },
    { id: "speed", kind: "process", shape: "circle", value: 60, label: { en: "Speed", ko: "속도" } },
    { id: "cost", kind: "process", shape: "circle", value: 30, label: { en: "Cost", ko: "비용" } },
  ], [
    { id: "safety-speed", from: "safety", to: "speed", kind: "association" },
    { id: "speed-cost", from: "speed", to: "cost", kind: "association" },
    { id: "cost-safety", from: "cost", to: "safety", kind: "association" },
  ]);
  const layout = await layoutDiagram(spec);
  assert.equal(layout.edges.length, 3);
  assert.notDeepEqual(layout.nodes.get("safety"), layout.nodes.get("cost"));
});

test("Sankey weights change rendered connector width", async () => {
  const spec = base("sankey", [
    { id: "signals", kind: "process", label: { en: "Signals", ko: "신호" } },
    { id: "decisions", kind: "process", label: { en: "Decisions", ko: "결정" } },
  ], [
    { id: "signal-flow", from: "signals", to: "decisions", kind: "event", weight: 4 },
  ]);
  const layout = await layoutDiagram(spec);
  const svg = await renderSvg(spec, layout, "en");
  assert.match(svg, /data-edge-weight="4"/);
  assert.match(svg, /stroke-width="9.6"/);
});

test("specialized kinds reject missing chart data", () => {
  assert.throws(
    () => base("pie", [{ id: "slice", kind: "process", label: { en: "Slice", ko: "조각" } }]),
    /at least two positive node values/,
  );
  assert.throws(
    () => base("wardley", [{ id: "need", kind: "process", label: { en: "Need", ko: "요구" } }]),
    /requires xValue and yValue/,
  );
});
