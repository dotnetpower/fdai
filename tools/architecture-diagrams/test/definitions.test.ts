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
    "network",
    "conceptual-flow",
  ]);
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
