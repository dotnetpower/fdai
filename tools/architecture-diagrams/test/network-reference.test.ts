import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

import { compileDiagram } from "../src/compiler.js";
import { layoutDiagram } from "../src/layout/elk.js";
import { layoutIntegrityErrors } from "../src/layout/integrity.js";
import { parseDiagram } from "../src/model/validate.js";
import { renderSvg } from "../src/render/svg.js";

function endpointId(endpoint: string): string {
  return endpoint.split(":", 1)[0] ?? endpoint;
}

function pointTouchesBoundary(
  point: { x: number; y: number },
  shape: { x: number; y: number; width: number; height: number },
): boolean {
  const epsilon = 0.01;
  const onVertical =
    (Math.abs(point.x - shape.x) <= epsilon ||
      Math.abs(point.x - (shape.x + shape.width)) <= epsilon) &&
    point.y >= shape.y - epsilon &&
    point.y <= shape.y + shape.height + epsilon;
  const onHorizontal =
    (Math.abs(point.y - shape.y) <= epsilon ||
      Math.abs(point.y - (shape.y + shape.height)) <= epsilon) &&
    point.x >= shape.x - epsilon &&
    point.x <= shape.x + shape.width + epsilon;
  return onVertical || onHorizontal;
}

const sourceUrl = new URL(
  "../../../docs/diagrams/azure-hub-spoke-network-reference.diagram.yaml",
  import.meta.url,
);

test("compiles the canonical hub-spoke network reference with complete semantics", async () => {
  const spec = parseDiagram(await readFile(sourceUrl, "utf8"));
  const layout = await layoutDiagram(spec);
  const svg = await renderSvg(spec, layout, "en");

  assert.equal(spec.kind, "network");
  assert.equal(spec.posture, "expected");
  assert.equal(spec.canvas.profile, "network-azure-reference");
  assert.equal(spec.canvas.networkPreset, "hub-spoke");
  assert.deepEqual(layoutIntegrityErrors(spec, layout), []);
  for (const edge of layout.edges) {
    const sourceEdge = spec.edges.find((candidate) => candidate.id === edge.id);
    const section = edge.sections?.[0];
    assert.ok(sourceEdge && section, `edge '${edge.id}' has a routed section`);
    const source = layout.nodes.get(endpointId(sourceEdge.from)) ??
      layout.groups.get(endpointId(sourceEdge.from));
    const target = layout.nodes.get(endpointId(sourceEdge.to)) ??
      layout.groups.get(endpointId(sourceEdge.to));
    assert.ok(source && target, `edge '${edge.id}' has positioned endpoints`);
    assert.ok(
      pointTouchesBoundary(section.startPoint, source),
      `edge '${edge.id}' starts on '${source.id}'`,
    );
    assert.ok(
      pointTouchesBoundary(section.endPoint, target),
      `edge '${edge.id}' ends on '${target.id}'`,
    );
  }
  assert.match(svg, /data-network-preset="hub-spoke"/);
  assert.match(svg, /data-annotation-id="routing-intent"/);
  assert.match(svg, /data-network-direction="bidirectional"/);
  assert.match(svg, /marker-start="url\(#arrow-start-dependency\)"/);
  assert.match(svg, /data-network-policy="inspect"/);
  assert.match(svg, /data-source-evidence="expected"/);
  for (const resourceId of [
    "bastion",
    "firewall",
    "virtual-hub",
    "hybrid-gateway",
    "external-gateway",
    "internal-gateway",
    "workload-vm",
    "data-vm",
    "private-endpoint",
    "expressroute-circuit",
  ]) {
    assert.match(svg, new RegExp(`data-node-id="${resourceId}"`));
    assert.match(
      svg,
      new RegExp(`data-node-id="${resourceId}"[^]*?<image[^>]+width="(?!0(?:\\.0+)?")`),
    );
  }

  const artifacts = await compileDiagram(spec);
  assert.ok(artifacts.some((artifact) => artifact.path.endsWith(".en.svg")));
  assert.ok(artifacts.some((artifact) => artifact.path.endsWith(".ko.svg")));
  assert.ok(artifacts.some((artifact) => artifact.path.endsWith(".en.png")));
  const manifestArtifact = artifacts.find((artifact) => artifact.path.endsWith(".manifest.json"));
  assert.ok(manifestArtifact);
  const manifest = JSON.parse(manifestArtifact.content.toString("utf8")) as {
    posture: string;
    networkPreset: string;
    annotations: Array<{ id: string }>;
    edges: Array<{ connectionKind?: string; sourceEvidence?: string }>;
  };
  assert.equal(manifest.posture, "expected");
  assert.equal(manifest.networkPreset, "hub-spoke");
  assert.equal(manifest.annotations[0]?.id, "routing-intent");
  assert.ok(manifest.edges.every((edge) => edge.connectionKind && edge.sourceEvidence === "expected"));
});
