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
  assert.ok(layout.height > layout.width);
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
  for (const groupId of [
    "container-apps-subnet",
    "private-endpoint-subnet",
    "private-service-backends",
  ]) {
    const children = spec.nodes
      .filter((node) => node.parent === groupId)
      .map((node) => layout.nodes.get(node.id)!);
    const centers = children.map((node) => node.y + node.height / 2);
    assert.ok(
      Math.max(...centers) - Math.min(...centers) <= 28,
      `${groupId} children must share one horizontal row`,
    );
    const group = layout.groups.get(groupId)!;
    assert.ok(group.width > group.height, `${groupId} must be wider than tall`);
  }
  const containerApps = layout.groups.get("container-apps-subnet")!;
  const privateEndpoints = layout.groups.get("private-endpoint-subnet")!;
  const privateServices = layout.groups.get("private-service-backends")!;
  assert.ok(containerApps.y + containerApps.height < privateEndpoints.y);
  assert.ok(privateEndpoints.y + privateEndpoints.height < privateServices.y);
  for (const [endpointId, serviceId] of [
    ["registry-pe", "container-registry"],
    ["event-hubs-pe", "event-hubs"],
    ["key-vault-pe", "key-vault"],
    ["openai-pe", "azure-openai"],
  ] as const) {
    const endpoint = layout.nodes.get(endpointId)!;
    const service = layout.nodes.get(serviceId)!;
    const endpointCenter = endpoint.x + endpoint.width / 2;
    const serviceCenter = service.x + service.width / 2;
    assert.ok(
      Math.abs(endpointCenter - serviceCenter) <= 96,
      `${endpointId} must align with ${serviceId}`,
    );
  }
  for (const edgeId of ["core-to-resource-graph", "core-to-git"]) {
    const edge = layout.edges.find((candidate) => candidate.id === edgeId);
    const section = edge?.sections?.[0];
    assert.ok(section?.bendPoints?.length === 3, `${edgeId} must use a right lane`);
    assert.ok(
      section.bendPoints[0]!.x > section.startPoint.x,
      `${edgeId} must leave through the right corridor`,
    );
  }
});
