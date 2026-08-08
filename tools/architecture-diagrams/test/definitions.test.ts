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
    "class-diagram",
    "user-journey",
    "pie",
    "quadrant",
    "requirement",
    "git-graph",
    "c4-context",
    "c4-container",
    "c4-component",
    "c4-deployment",
    "mindmap",
    "sankey",
    "xy-chart",
    "block",
    "packet",
    "kanban",
    "architecture",
    "radar",
    "venn",
    "wardley",
    "cynefin",
    "railroad",
    "ishikawa",
    "event-modeling",
    "tree-view",
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
  assert.equal(diagramDefinition("pie").layoutStrategy, "radial");
  assert.equal(diagramDefinition("quadrant").layoutStrategy, "coordinate");
  assert.equal(diagramDefinition("kanban").layoutStrategy, "grid");
  assert.equal(diagramDefinition("sankey").layoutStrategy, "layered");
});

test("keeps compound-edge handling isolated to deployment views", () => {
  const compoundKinds = new Set(["deployment", "c4-deployment", "architecture"]);
  for (const kind of supportedDiagramKinds()) {
    assert.equal(
      diagramDefinition(kind).hierarchyHandling,
      compoundKinds.has(kind) ? "INCLUDE_CHILDREN" : "SEPARATE_CHILDREN",
    );
  }
});
