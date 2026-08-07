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
