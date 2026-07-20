import assert from "node:assert/strict";
import test from "node:test";

import {
  assertLayoutIntegrity,
  layoutIntegrityErrors,
} from "../src/layout/integrity.js";
import type { DiagramLayout } from "../src/layout/elk.js";
import type { DiagramSpec } from "../src/model/types.js";

const spec = {
  id: "integrity",
  version: 1,
  kind: "container",
  locales: {
    en: { title: "Integrity", description: "Check", alt: "Check" },
    ko: { title: "Integrity", description: "Check", alt: "Check" },
  },
  canvas: { width: 800, height: 480, direction: "RIGHT" },
  groups: [
    { id: "group", kind: "system", label: { en: "Group", ko: "Group" } },
  ],
  nodes: [
    { id: "a", parent: "group", kind: "process", label: { en: "A", ko: "A" } },
    { id: "b", parent: "group", kind: "process", label: { en: "B", ko: "B" } },
  ],
  edges: [],
} satisfies DiagramSpec;

function layout(): DiagramLayout {
  return {
    width: 400,
    height: 240,
    groups: new Map([
      ["group", { id: "group", x: 0, y: 0, width: 400, height: 240, depth: 1 }],
    ]),
    nodes: new Map([
      ["a", { id: "a", x: 30, y: 60, width: 120, height: 100, depth: 2 }],
      ["b", { id: "b", x: 190, y: 60, width: 120, height: 100, depth: 2 }],
    ]),
    edges: [],
  };
}

test("accepts separated nodes contained by their parent", () => {
  assert.doesNotThrow(() => assertLayoutIntegrity(spec, layout()));
});

test("reports node overlap and parent escape", () => {
  const invalid = layout();
  invalid.nodes.set("b", {
    id: "b",
    x: 100,
    y: 180,
    width: 320,
    height: 100,
    depth: 2,
  });
  assert.deepEqual(layoutIntegrityErrors(spec, invalid), [
    "Node 'b' escapes parent 'group'",
  ]);
});

test("reports an edge label that overlaps a node", () => {
  const invalid = layout();
  invalid.edges.push({
    id: "edge",
    sources: ["a"],
    targets: ["b"],
    labels: [{ id: "label", x: 40, y: 70, width: 80, height: 24 }],
  });
  assert.deepEqual(layoutIntegrityErrors(spec, invalid), [
    "Edge 'edge' label overlaps node 'a'",
  ]);
});

test("rejects a diagonal that crosses an unrelated node", () => {
  const diagonalSpec: DiagramSpec = {
    ...spec,
    nodes: [
      ...spec.nodes,
      {
        id: "c",
        parent: "group",
        kind: "process",
        label: { en: "C", ko: "C" },
      },
    ],
    edges: [
      {
        id: "diagonal",
        from: "a",
        to: "b",
        kind: "request",
        route: "diagonal",
      },
    ],
  };
  const invalid = layout();
  invalid.nodes.set("c", {
    id: "c",
    x: 155,
    y: 95,
    width: 30,
    height: 30,
    depth: 2,
  });
  invalid.edges.push({
    id: "diagonal",
    sources: ["a"],
    targets: ["b"],
    sections: [
      {
        id: "diagonal-section",
        startPoint: { x: 150, y: 110 },
        endPoint: { x: 190, y: 110 },
      },
    ],
  });
  assert.ok(
    layoutIntegrityErrors(diagonalSpec, invalid).includes(
      "Diagonal edge 'diagonal' crosses node 'c'",
    ),
  );
});
