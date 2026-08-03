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
  const koSvg = await renderSvg(spec, layout, "ko");

  assert.equal(spec.version, 3);
  assert.equal(spec.kind, "context");
  assert.deepEqual(spec.formats, ["svg"]);
  assert.equal(layout.edges.length, spec.edges.length);
  assert.equal(spec.edges.length, 17);
  assert.ok(layout.edges.every((edge) => (edge.sections?.length ?? 0) > 0));
  assert.deepEqual(layoutIntegrityErrors(spec, layout), []);
  assert.equal([...svg.matchAll(/data-edge-id=/g)].length, spec.edges.length);
  assert.equal([...koSvg.matchAll(/data-edge-id=/g)].length, spec.edges.length);

  const dimensions = svg.match(/^<svg[^>]* width="(\d+)" height="(\d+)"/);
  assert.ok(dimensions);
  assert.ok(Number(dimensions[1]) / Number(dimensions[2]) >= 1.65);

  for (const groupId of [
    "connected-environment",
    "fdai-platform",
    "operator-surfaces",
    "headless-control-plane",
    "event-choreography",
    "governed-control",
    "governed-capabilities",
    "azure-foundation",
    "human-authority",
    "governed-outcomes",
  ]) {
    assert.match(svg, new RegExp(`data-group-id="${groupId}"`));
  }

  for (const nodeId of [
    "typed-event-bus",
    "agent-pantheon",
    "trust-router",
    "decision-tiers",
    "t2-quality-gate",
    "risk-authority-gate",
    "privileged-executor",
    "human-approval",
    "policy-query-engine",
    "evidence-store",
    "held-outcome",
    "governed-changes",
  ]) {
    assert.match(svg, new RegExp(`data-node-id="${nodeId}"`));
  }

  for (const groupId of ["event-choreography", "governed-control"]) {
    assert.equal(
      spec.groups.find((group) => group.id === groupId)?.parent,
      "headless-control-plane",
    );
  }
  for (const nodeId of [
    "microsoft-foundry",
    "azure-openai",
    "provider-tools",
    "policy-query-engine",
    "ontology-catalogs",
    "evidence-store",
  ]) {
    assert.equal(
      spec.nodes.find((node) => node.id === nodeId)?.parent,
      "governed-capabilities",
    );
  }
  assert.equal(
    spec.nodes.find((node) => node.id === "human-approval")?.parent,
    "human-authority",
  );
  assert.deepEqual(
    spec.groups.filter((group) => !group.parent).map((group) => group.id),
    ["connected-environment", "fdai-platform", "governed-outcomes", "human-authority"],
  );

  const edges = new Map(spec.edges.map((edge) => [edge.id, edge]));
  assert.deepEqual(
    [edges.get("decision-to-quality")?.from, edges.get("decision-to-quality")?.to],
    ["decision-tiers", "t2-quality-gate"],
  );
  assert.deepEqual(
    [edges.get("decision-to-risk")?.from, edges.get("decision-to-risk")?.to],
    ["decision-tiers", "risk-authority-gate"],
  );
  assert.deepEqual(
    [edges.get("quality-to-risk")?.from, edges.get("quality-to-risk")?.to],
    ["t2-quality-gate", "risk-authority-gate"],
  );
  assert.deepEqual(
    [edges.get("approval-to-runtime")?.from, edges.get("approval-to-runtime")?.to],
    ["human-approval", "event-choreography"],
  );
  assert.equal(
    spec.edges.some(
      (edge) =>
        edge.kind === "approval" &&
        edge.to.split(":", 1)[0] === "privileged-executor",
    ),
    false,
  );

  const approvalLanes = ["risk-to-approval", "approval-to-runtime"].map(
    (edgeId) => {
      const section = layout.edges.find((edge) => edge.id === edgeId)?.sections?.[0];
      assert.ok(section?.bendPoints?.length);
      return Math.min(...section.bendPoints.map((point) => point.y));
    },
  );
  assert.equal(Math.abs(approvalLanes[0]! - approvalLanes[1]!), 28);
  assert.deepEqual(
    [edges.get("executor-to-outcomes")?.from, edges.get("executor-to-outcomes")?.to],
    ["privileged-executor", "governed-changes"],
  );
  assert.equal(edges.get("executor-to-outcomes")?.route, "orthogonal-shortest");
  assert.deepEqual(
    [edges.get("risk-to-held")?.from, edges.get("risk-to-held")?.to],
    ["governed-control", "held-outcome"],
  );
  assert.equal(edges.has("executor-to-pr"), false);
  assert.equal(edges.has("executor-to-actions"), false);

  assert.equal(spec.nodes.filter((node) => node.kind === "agent").length, 0);
  assert.equal(
    spec.nodes.find((node) => node.id === "agent-pantheon")?.icon,
    "agent-pantheon",
  );
});
