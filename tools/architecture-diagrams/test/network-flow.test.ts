import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

import { layoutDiagram } from "../src/layout/elk.js";
import { layoutIntegrityErrors } from "../src/layout/integrity.js";
import { parseDiagram } from "../src/model/validate.js";
import { renderSvg } from "../src/render/svg.js";

const networkFlowUrl = new URL(
  "../../../docs/diagrams/fdai-azure-resource-network-flow.diagram.yaml",
  import.meta.url,
);

test("Azure resource network flow routes every compound edge", async () => {
  const spec = parseDiagram(await readFile(networkFlowUrl, "utf8"));
  const layout = await layoutDiagram(spec);
  const svg = await renderSvg(spec, layout, "en");

  assert.equal(spec.kind, "deployment");
  assert.ok(layout.width > layout.height);
  assert.equal(layout.edges.length, spec.edges.length);
  assert.ok(layout.edges.every((edge) => (edge.sections?.length ?? 0) > 0));
  assert.deepEqual(layoutIntegrityErrors(spec, layout), []);
  const explicitRoutes = new Set(
    spec.edges
      .filter((edge) => edge.route === "orthogonal")
      .map((edge) => edge.id),
  );
  for (const edge of layout.edges.filter((candidate) => explicitRoutes.has(candidate.id))) {
    const bends = (edge.sections ?? []).reduce(
      (total, section) => total + (section.bendPoints?.length ?? 0),
      0,
    );
    assert.ok(bends <= 2, `${edge.id} has ${bends} bends`);
  }
  assert.equal([...svg.matchAll(/data-edge-id=/g)].length, spec.edges.length);
  assert.match(svg, /data-group-id="fdai-vnet"/);
  assert.match(svg, /data-group-id="container-apps-subnet"/);
  assert.match(svg, /data-group-id="private-endpoint-subnet"/);
  assert.match(svg, /data-group-id="postgres-subnet"/);
  assert.match(svg, /data-node-id="operator-console"/);
  assert.match(svg, /data-node-id="operator-cli"/);
  for (const edgeId of ["core-to-resource-graph", "core-to-git"]) {
    const edge = layout.edges.find((candidate) => candidate.id === edgeId);
    const section = edge?.sections?.[0];
    assert.ok(section?.bendPoints?.length === 4, `${edgeId} must use an upper lane`);
    assert.ok(
      section.bendPoints[1]!.y < section.startPoint.y,
      `${edgeId} must rise before crossing the diagram`,
    );
    assert.ok(
      section.bendPoints.every(
        (point) => point.y <= Math.max(section.startPoint.y, section.endPoint.y),
      ),
      `${edgeId} must not route below its endpoints`,
    );
  }
});
