import assert from "node:assert/strict";
import test from "node:test";

import {
  diagramDefinition,
  supportedDiagramKinds,
} from "../src/model/definitions.js";

test("registers every supported diagram kind", () => {
  assert.deepEqual(supportedDiagramKinds(), [
    "context",
    "container",
    "component",
    "deployment",
    "data-flow",
    "flowchart",
    "graph",
    "network",
    "conceptual-flow",
    "sequence",
    "swimlane",
    "state",
    "decision-tree",
    "domain",
    "entity-relationship",
    "timeline",
    "gantt",
  ]);
});

test("assigns specialized layout strategies to non-topology diagrams", () => {
  assert.equal(diagramDefinition("sequence").direction, "DOWN");
  assert.equal(diagramDefinition("swimlane").rootLayout, "row");
  assert.equal(diagramDefinition("state").edgeRouting, "POLYLINE");
  assert.equal(diagramDefinition("decision-tree").layoutStrategy, "tree");
  assert.equal(diagramDefinition("domain").requiredEdgeKind, "association");
  assert.equal(diagramDefinition("timeline").direction, "RIGHT");
  assert.equal(diagramDefinition("gantt").layoutStrategy, "gantt");
});

test("keeps deployment compound-edge handling isolated", () => {
  assert.equal(
    diagramDefinition("deployment").hierarchyHandling,
    "INCLUDE_CHILDREN",
  );
  for (const kind of supportedDiagramKinds().filter(
    (candidate) => candidate !== "deployment",
  )) {
    assert.equal(
      diagramDefinition(kind).hierarchyHandling,
      "SEPARATE_CHILDREN",
    );
  }
});
