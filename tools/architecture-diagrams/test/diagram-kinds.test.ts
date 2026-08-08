import assert from "node:assert/strict";
import test from "node:test";

import { layoutDiagram } from "../src/layout/elk.js";
import type { DiagramKind, EdgeKind } from "../src/model/types.js";
import { validateDiagram } from "../src/model/validate.js";

function linearSpec(kind: DiagramKind, edgeKind: EdgeKind) {
  return validateDiagram({
    id: `${kind}-sample`,
    version: 1,
    kind,
    locales: {
      en: { title: "Sample", description: "Sample", alt: "Two connected nodes." },
      ko: { title: "예제", description: "예제", alt: "두 노드가 연결됩니다." },
    },
    canvas: { width: 800, height: 480, direction: "RIGHT" },
    groups: [],
    nodes: [
      { id: "first", kind: "process", label: { en: "First", ko: "첫 번째" } },
      { id: "second", kind: "process", label: { en: "Second", ko: "두 번째" } },
    ],
    edges: [{ id: "flow", from: "first", to: "second", kind: edgeKind }],
  });
}

test("sequence strategy lays interactions out from top to bottom", async () => {
  const layout = await layoutDiagram(linearSpec("sequence", "sequence"));
  assert.ok(layout.nodes.get("second")!.y > layout.nodes.get("first")!.y);
});

test("state, domain, and timeline strategies preserve their primary axis", async () => {
  for (const [kind, edgeKind] of [
    ["state", "transition"],
    ["domain", "association"],
    ["entity-relationship", "association"],
    ["timeline", "timeline"],
  ] as const) {
    const layout = await layoutDiagram(linearSpec(kind, edgeKind));
    assert.ok(layout.nodes.get("second")!.x > layout.nodes.get("first")!.x);
  }
});

test("decision tree strategy places branches below their decision", async () => {
  const spec = linearSpec("decision-tree", "request");
  const layout = await layoutDiagram(spec);
  assert.ok(layout.nodes.get("second")!.y > layout.nodes.get("first")!.y);
});

test("swimlane strategy places lanes side by side and work top to bottom", async () => {
  const spec = validateDiagram({
    id: "swimlane-sample",
    version: 1,
    kind: "swimlane",
    locales: {
      en: { title: "Swimlane", description: "Swimlane", alt: "Two lanes." },
      ko: { title: "스윔레인", description: "스윔레인", alt: "두 개의 레인입니다." },
    },
    canvas: { width: 900, height: 540, direction: "RIGHT" },
    groups: [
      { id: "operator", kind: "layer", presentation: "lane", label: { en: "Operator", ko: "운영자" } },
      { id: "system", kind: "layer", presentation: "lane", label: { en: "System", ko: "시스템" } },
    ],
    nodes: [
      { id: "request", parent: "operator", kind: "process", label: { en: "Request", ko: "요청" } },
      { id: "review", parent: "operator", kind: "process", label: { en: "Review", ko: "검토" } },
      { id: "execute", parent: "system", kind: "process", label: { en: "Execute", ko: "실행" } },
    ],
    edges: [
      { id: "request-review", from: "request", to: "review", kind: "sequence" },
      { id: "review-execute", from: "review", to: "execute", kind: "approval" },
    ],
  });
  const layout = await layoutDiagram(spec);

  assert.ok(layout.groups.get("system")!.x > layout.groups.get("operator")!.x);
  assert.ok(layout.nodes.get("review")!.y > layout.nodes.get("request")!.y);
});

test("kind contracts reject missing semantic primitives", () => {
  const sequence = linearSpec("sequence", "sequence");
  sequence.edges[0]!.kind = "request";
  assert.throws(
    () => validateDiagram(sequence),
    /requires an edge of kind 'sequence'/,
  );

  const swimlane = { ...sequence, kind: "swimlane", edges: [] };
  assert.throws(
    () => validateDiagram(swimlane),
    /requires a 'lane' group/,
  );
});
