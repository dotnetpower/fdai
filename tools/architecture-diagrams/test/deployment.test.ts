import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

import { layoutDiagram } from "../src/layout/elk.js";
import { parseDiagram } from "../src/model/validate.js";
import { renderSvg } from "../src/render/svg.js";

const deploymentUrl = new URL(
  "../../../docs/diagrams/fdai-azure-deployment-topology.diagram.yaml",
  import.meta.url,
);

test("deployment topology routes every compound edge in a landscape layout", async () => {
  const spec = parseDiagram(await readFile(deploymentUrl, "utf8"));
  const layout = await layoutDiagram(spec);
  const svg = await renderSvg(spec, layout, "en");

  assert.ok(layout.width > layout.height);
  assert.equal(layout.edges.length, spec.edges.length);
  assert.ok(layout.edges.every((edge) => (edge.sections?.length ?? 0) > 0));
  assert.equal([...svg.matchAll(/data-edge-id=/g)].length, spec.edges.length);
  assert.match(svg, /data-group-id="fdai-vnet"/);
  assert.match(svg, /data-group-id="container-apps-subnet"/);
  assert.match(svg, /data-group-id="private-endpoint-subnet"/);
  assert.match(svg, /data-group-id="postgres-subnet"/);
});
