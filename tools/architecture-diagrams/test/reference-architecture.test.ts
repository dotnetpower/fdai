import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

import { layoutDiagram } from "../src/layout/elk.js";
import { layoutIntegrityErrors } from "../src/layout/integrity.js";
import { parseDiagram } from "../src/model/validate.js";
import { renderSvg } from "../src/render/svg.js";

const referenceArchitectureUrl = new URL(
  "../../../docs/diagrams/fdai-reference-architecture.diagram.yaml",
  import.meta.url,
);

test("FDAI reference architecture renders every governed relationship", async () => {
  const source = await readFile(referenceArchitectureUrl, "utf8");
  const spec = parseDiagram(source);
  const layout = await layoutDiagram(spec);
  const svg = await renderSvg(spec, layout, "en");

  assert.equal(spec.kind, "context");
  assert.deepEqual(spec.formats, ["svg"]);
  assert.equal(layout.edges.length, spec.edges.length);
  assert.ok(layout.edges.every((edge) => (edge.sections?.length ?? 0) > 0));
  assert.deepEqual(layoutIntegrityErrors(spec, layout), []);
  assert.equal([...svg.matchAll(/data-edge-id=/g)].length, spec.edges.length);

  for (const groupId of [
    "connected-environment",
    "fdai-platform",
    "operator-surfaces",
    "agent-runtime",
    "governed-control",
    "models-and-tools",
    "knowledge-and-evidence",
    "azure-foundation",
    "governed-outcomes",
  ]) {
    assert.match(svg, new RegExp(`data-group-id="${groupId}"`));
  }

  for (const nodeId of [
    "typed-event-bus",
    "agent-pantheon",
    "trust-router",
    "safety-check",
    "privileged-executor",
    "human-approval",
    "evidence-store",
  ]) {
    assert.match(svg, new RegExp(`data-node-id="${nodeId}"`));
  }

  assert.equal(spec.nodes.filter((node) => node.kind === "agent").length, 0);
  assert.equal(
    spec.nodes.find((node) => node.id === "agent-pantheon")?.icon,
    "agent-pantheon",
  );
});
