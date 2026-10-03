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

test("reports a specification edge without a drawn path", () => {
  const invalidSpec: DiagramSpec = {
    ...spec,
    edges: [{ id: "missing", from: "a", to: "b", kind: "request" }],
  };
  assert.deepEqual(layoutIntegrityErrors(invalidSpec, layout()), [
    "Edge 'missing' has no drawn path",
  ]);
});

test("reports a fallback edge that crosses an unrelated node", () => {
  const fallbackSpec: DiagramSpec = {
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
    edges: [{ id: "fallback", from: "a", to: "b", kind: "request" }],
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
    id: "fallback",
    sources: ["a"],
    targets: ["b"],
    sections: [
      {
        id: "fallback-missing-edge-route",
        startPoint: { x: 150, y: 110 },
        endPoint: { x: 190, y: 110 },
      },
    ],
  });
  assert.ok(
    layoutIntegrityErrors(fallbackSpec, invalid).includes(
      "Fallback edge 'fallback' crosses node 'c'",
    ),
  );
});

test("reports long overlaps between unrelated fallback edges", () => {
  const overlapSpec: DiagramSpec = {
    ...spec,
    nodes: [
      { id: "a", kind: "process", label: { en: "A", ko: "A" } },
      { id: "b", kind: "process", label: { en: "B", ko: "B" } },
      { id: "c", kind: "process", label: { en: "C", ko: "C" } },
      { id: "d", kind: "process", label: { en: "D", ko: "D" } },
    ],
    edges: [
      { id: "first", from: "a", to: "b", kind: "request" },
      { id: "second", from: "c", to: "d", kind: "request" },
    ],
  };
  const invalid: DiagramLayout = {
    width: 400,
    height: 240,
    groups: new Map(),
    nodes: new Map([
      ["a", { id: "a", x: 0, y: 0, width: 40, height: 40, depth: 1 }],
      ["b", { id: "b", x: 360, y: 0, width: 40, height: 40, depth: 1 }],
      ["c", { id: "c", x: 0, y: 80, width: 40, height: 40, depth: 1 }],
      ["d", { id: "d", x: 360, y: 80, width: 40, height: 40, depth: 1 }],
    ]),
    edges: [
      {
        id: "first",
        sources: ["a"],
        targets: ["b"],
        sections: [
          {
            id: "first-missing-edge-route",
            startPoint: { x: 40, y: 60 },
            endPoint: { x: 360, y: 60 },
          },
        ],
      },
      {
        id: "second",
        sources: ["c"],
        targets: ["d"],
        sections: [
          {
            id: "second-missing-edge-route",
            startPoint: { x: 80, y: 60 },
            endPoint: { x: 320, y: 60 },
          },
        ],
      },
    ],
  };
  assert.ok(
    layoutIntegrityErrors(overlapSpec, invalid).includes(
      "Fallback edges 'first' and 'second' overlap for 240px",
    ),
  );
});

test("reports visually overlapping fallback lanes within stroke tolerance", () => {
  const overlapSpec: DiagramSpec = {
    ...spec,
    nodes: [
      { id: "a", kind: "process", label: { en: "A", ko: "A" } },
      { id: "b", kind: "process", label: { en: "B", ko: "B" } },
      { id: "c", kind: "process", label: { en: "C", ko: "C" } },
      { id: "d", kind: "process", label: { en: "D", ko: "D" } },
    ],
    edges: [
      { id: "first", from: "a", to: "b", kind: "request" },
      { id: "second", from: "c", to: "d", kind: "request" },
    ],
  };
  const invalid: DiagramLayout = {
    width: 400,
    height: 240,
    groups: new Map(),
    nodes: new Map([
      ["a", { id: "a", x: 0, y: 0, width: 40, height: 40, depth: 1 }],
      ["b", { id: "b", x: 360, y: 0, width: 40, height: 40, depth: 1 }],
      ["c", { id: "c", x: 0, y: 80, width: 40, height: 40, depth: 1 }],
      ["d", { id: "d", x: 360, y: 80, width: 40, height: 40, depth: 1 }],
    ]),
    edges: [
      {
        id: "first",
        sources: ["a"],
        targets: ["b"],
        sections: [
          {
            id: "first-missing-edge-route",
            startPoint: { x: 40, y: 60 },
            endPoint: { x: 360, y: 60 },
          },
        ],
      },
      {
        id: "second",
        sources: ["c"],
        targets: ["d"],
        sections: [
          {
            id: "second-missing-edge-route",
            startPoint: { x: 80, y: 61 },
            endPoint: { x: 320, y: 61 },
          },
        ],
      },
    ],
  };
  assert.ok(
    layoutIntegrityErrors(overlapSpec, invalid).includes(
      "Fallback edges 'first' and 'second' overlap for 240px",
    ),
  );
});

test("reports fallback edges that re-enter their own endpoint after the stub", () => {
  const endpointSpec: DiagramSpec = {
    ...spec,
    groups: [],
    nodes: [
      { id: "a", kind: "process", label: { en: "A", ko: "A" } },
      { id: "b", kind: "process", label: { en: "B", ko: "B" } },
    ],
    edges: [{ id: "fallback", from: "a", to: "b", kind: "request" }],
  };
  const invalid: DiagramLayout = {
    width: 200,
    height: 120,
    groups: new Map(),
    nodes: new Map([
      ["a", { id: "a", x: 0, y: 0, width: 40, height: 40, depth: 1 }],
      ["b", { id: "b", x: 100, y: 0, width: 40, height: 40, depth: 1 }],
    ]),
    edges: [
      {
        id: "fallback",
        sources: ["a"],
        targets: ["b"],
        sections: [
          {
            id: "fallback-missing-edge-route",
            startPoint: { x: 40, y: 20 },
            bendPoints: [
              { x: 60, y: 20 },
              { x: 120, y: 20 },
            ],
            endPoint: { x: 100, y: 20 },
          },
        ],
      },
    ],
  };
  assert.ok(
    layoutIntegrityErrors(endpointSpec, invalid).includes(
      "Fallback edge 'fallback' crosses node 'b'",
    ),
  );
});

test("reports fallback edge labels placed far from their route", () => {
  const labelSpec: DiagramSpec = {
    ...spec,
    groups: [],
    nodes: [
      { id: "a", kind: "process", label: { en: "A", ko: "A" } },
      { id: "b", kind: "process", label: { en: "B", ko: "B" } },
    ],
    edges: [
      {
        id: "fallback",
        from: "a",
        to: "b",
        kind: "request",
        label: { en: "Far", ko: "Far" },
      },
    ],
  };
  const invalid: DiagramLayout = {
    width: 320,
    height: 200,
    groups: new Map(),
    nodes: new Map([
      ["a", { id: "a", x: 0, y: 0, width: 40, height: 40, depth: 1 }],
      ["b", { id: "b", x: 200, y: 0, width: 40, height: 40, depth: 1 }],
    ]),
    edges: [
      {
        id: "fallback",
        sources: ["a"],
        targets: ["b"],
        labels: [{ id: "fallback-label", x: 160, y: 160, width: 40, height: 20 }],
        sections: [
          {
            id: "fallback-missing-edge-route",
            startPoint: { x: 40, y: 20 },
            endPoint: { x: 200, y: 20 },
          },
        ],
      },
    ],
  };
  assert.ok(
    layoutIntegrityErrors(labelSpec, invalid).some((error) =>
      error.startsWith("Edge 'fallback' label is "),
    ),
  );
});

test("reports overlapping edge labels", () => {
  const invalid = layout();
  invalid.edges.push(
    {
      id: "first",
      sources: ["a"],
      targets: ["b"],
      labels: [{ id: "first-label", x: 150, y: 20, width: 80, height: 24 }],
    },
    {
      id: "second",
      sources: ["b"],
      targets: ["a"],
      labels: [{ id: "second-label", x: 190, y: 20, width: 80, height: 24 }],
    },
  );
  assert.deepEqual(layoutIntegrityErrors(spec, invalid), [
    "Edge labels 'first' and 'second' overlap",
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

test("rejects proper crossings between unrelated network edges", () => {
  const networkSpec: DiagramSpec = {
    ...spec,
    kind: "network",
    posture: "expected",
    nodes: [
      { id: "a", kind: "process", label: { en: "A", ko: "A" } },
      { id: "b", kind: "process", label: { en: "B", ko: "B" } },
      { id: "c", kind: "process", label: { en: "C", ko: "C" } },
      { id: "d", kind: "process", label: { en: "D", ko: "D" } },
    ],
    edges: [
      { id: "a-b", from: "a", to: "b", kind: "request", route: "orthogonal" },
      { id: "c-d", from: "c", to: "d", kind: "request", route: "orthogonal" },
    ],
  };
  const crossing: DiagramLayout = {
    width: 400,
    height: 240,
    groups: new Map(),
    nodes: new Map([
      ["a", { id: "a", x: 0, y: 80, width: 40, height: 40, depth: 1 }],
      ["b", { id: "b", x: 360, y: 80, width: 40, height: 40, depth: 1 }],
      ["c", { id: "c", x: 180, y: 0, width: 40, height: 40, depth: 1 }],
      ["d", { id: "d", x: 180, y: 200, width: 40, height: 40, depth: 1 }],
    ]),
    edges: [
      {
        id: "a-b",
        sources: ["a"],
        targets: ["b"],
        sections: [{ id: "a-b-section", startPoint: { x: 40, y: 100 }, endPoint: { x: 360, y: 100 } }],
      },
      {
        id: "c-d",
        sources: ["c"],
        targets: ["d"],
        sections: [{ id: "c-d-section", startPoint: { x: 200, y: 40 }, endPoint: { x: 200, y: 200 } }],
      },
    ],
  };

  assert.ok(layoutIntegrityErrors(networkSpec, crossing).includes(
    "Network edges 'a-b' and 'c-d' cross",
  ));
});
