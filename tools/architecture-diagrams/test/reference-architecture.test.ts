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

  assert.equal(spec.version, 10);
  assert.equal(spec.kind, "context");
  assert.deepEqual(spec.formats, ["svg"]);
  assert.equal(layout.edges.length, spec.edges.length);
  assert.equal(spec.edges.length, 16);
  assert.ok(layout.edges.every((edge) => (edge.sections?.length ?? 0) > 0));
  assert.deepEqual(layoutIntegrityErrors(spec, layout), []);
  assert.equal([...svg.matchAll(/data-edge-id=/g)].length, spec.edges.length);
  assert.equal([...koSvg.matchAll(/data-edge-id=/g)].length, spec.edges.length);

  const dimensions = svg.match(/^<svg[^>]* width="(\d+)" height="(\d+)"/);
  assert.ok(dimensions);
  assert.ok(Number(dimensions[1]) / Number(dimensions[2]) >= 1.65);
  const darkThemeBlocks = [
    ...svg.matchAll(/@media \(prefers-color-scheme: dark\) \{([\s\S]*?)\n\s*\}/g),
  ];
  assert.equal(darkThemeBlocks.length, 2);
  assert.ok(
    darkThemeBlocks.every((match) =>
      match[1]?.includes(':not([data-profile="azure-reference"])'),
    ),
  );

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
  assert.equal(
    spec.groups.find((group) => group.id === "governed-control")?.gap,
    64,
  );
  for (const groupId of [
    "connected-environment",
    "fdai-platform",
    "headless-control-plane",
  ]) {
    assert.equal(
      spec.groups.find((group) => group.id === groupId)?.presentation,
      "panel",
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
  const genericIconByNode = new Map([
    ["enterprise-connectors", "lucide-cable"],
    ["operator-cli", "lucide-terminal"],
    ["event-ingest", "lucide-inbox"],
    ["trust-router", "lucide-route"],
    ["decision-tiers", "lucide-git-branch"],
    ["t2-quality-gate", "lucide-badge-check"],
    ["risk-authority-gate", "lucide-shield-check"],
    ["privileged-executor", "lucide-play"],
    ["provider-tools", "lucide-wrench"],
    ["policy-query-engine", "lucide-search-check"],
    ["ontology-catalogs", "lucide-book-open"],
    ["held-outcome", "lucide-circle-pause"],
    ["governed-changes", "lucide-file-check"],
    ["audit-replay", "lucide-refresh-ccw"],
  ]);
  assert.equal(spec.nodes.filter((node) => !node.icon).length, 0);
  for (const [nodeId, icon] of genericIconByNode) {
    const node = spec.nodes.find((candidate) => candidate.id === nodeId);
    assert.equal(node?.icon, icon);
    assert.equal(node?.presentation, "icon");
  }
  for (const nodeId of genericIconByNode.keys()) {
    const start = svg.indexOf(`data-node-id="${nodeId}"`);
    const end = svg.indexOf('<g class="diagram-node', start + 1);
    assert.match(svg.slice(start, end >= 0 ? end : undefined), /<image /);
  }
  assert.deepEqual(
    spec.groups.filter((group) => !group.parent).map((group) => group.id),
    ["connected-environment", "fdai-platform", "governed-outcomes", "human-authority"],
  );

  const edges = new Map(spec.edges.map((edge) => [edge.id, edge]));
  assert.equal(edges.has("bus-to-agents"), false);
  assert.equal(edges.get("bus-to-ingest")?.route, "orthogonal-trunk");
  assert.equal(edges.get("bus-to-ingest")?.lane, 3);
  const busToIngest = layout.edges.find(
    (edge) => edge.id === "bus-to-ingest",
  )?.sections?.[0];
  const eventIngest = layout.nodes.get("event-ingest");
  const governedControl = layout.groups.get("governed-control");
  assert.ok(busToIngest?.bendPoints?.length);
  assert.ok(eventIngest);
  assert.ok(governedControl);
  const ingressTrunkY = busToIngest.bendPoints[0]!.y;
  assert.equal(busToIngest.bendPoints[1]!.y, ingressTrunkY);
  assert.ok(ingressTrunkY > governedControl.y + 32);
  assert.ok(ingressTrunkY < eventIngest.y - 12);
  assert.equal(
    busToIngest.endPoint.x,
    eventIngest.x + eventIngest.width / 2,
  );
  for (const edgeId of [
    "ingest-to-router",
    "router-to-decision",
    "decision-to-quality",
    "quality-to-risk",
    "risk-to-executor",
  ]) {
    const section = layout.edges.find((edge) => edge.id === edgeId)?.sections?.[0];
    assert.ok(section);
    assert.ok(Math.abs(section.endPoint.x - section.startPoint.x) >= 56);
  }
  assert.equal(edges.get("environment-to-runtime")?.route, "orthogonal-horizontal");
  assert.equal(edges.get("operators-to-runtime")?.route, "orthogonal");
  const ingressSections = ["environment-to-runtime", "operators-to-runtime"].map(
    (edgeId) => {
      const section = layout.edges.find((edge) => edge.id === edgeId)?.sections?.[0];
      assert.ok(section);
      return section;
    },
  );
  const eventChoreography = layout.groups.get("event-choreography");
  assert.ok(eventChoreography);
  assert.equal(ingressSections[0]!.endPoint.x, eventChoreography.x);
  assert.equal(ingressSections[1]!.endPoint.y, eventChoreography.y);
  assert.notDeepEqual(ingressSections[0]!.endPoint, ingressSections[1]!.endPoint);
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
    ["human-approval", "typed-event-bus"],
  );
  assert.equal(
    spec.edges.some(
      (edge) =>
        edge.kind === "approval" &&
        edge.to.split(":", 1)[0] === "privileged-executor",
    ),
    false,
  );

  assert.equal(edges.get("risk-to-approval")?.route, "orthogonal-outer");
  assert.equal(edges.get("approval-to-runtime")?.route, "orthogonal-right");
  const approvalCorridors = ["risk-to-approval", "approval-to-runtime"].map(
    (edgeId) => {
      const section = layout.edges.find((edge) => edge.id === edgeId)?.sections?.[0];
      assert.ok(section?.bendPoints?.length);
      return Math.max(...section.bendPoints.map((point) => point.x));
    },
  );
  assert.equal(Math.abs(approvalCorridors[0]! - approvalCorridors[1]!), 96);

  const directedSegments: Array<{
    edgeId: string;
    start: { x: number; y: number };
    end: { x: number; y: number };
  }> = [];
  for (const edge of layout.edges) {
    const container = edge.container ? layout.groups.get(edge.container) : undefined;
    const offsetX = container?.x ?? 0;
    const offsetY = container?.y ?? 0;
    for (const section of edge.sections ?? []) {
      const points = [
        section.startPoint,
        ...(section.bendPoints ?? []),
        section.endPoint,
      ].map((point) => ({ x: point.x + offsetX, y: point.y + offsetY }));
      for (let index = 1; index < points.length; index += 1) {
        const start = points[index - 1]!;
        const end = points[index]!;
        if (start.x === end.x || start.y === end.y) {
          directedSegments.push({ edgeId: edge.id, start, end });
        }
      }
    }
  }
  const opposingOverlaps: string[] = [];
  for (let leftIndex = 0; leftIndex < directedSegments.length; leftIndex += 1) {
    for (
      let rightIndex = leftIndex + 1;
      rightIndex < directedSegments.length;
      rightIndex += 1
    ) {
      const left = directedSegments[leftIndex]!;
      const right = directedSegments[rightIndex]!;
      if (left.edgeId === right.edgeId) continue;
      const vertical =
        left.start.x === left.end.x &&
        right.start.x === right.end.x &&
        left.start.x === right.start.x;
      const horizontal =
        left.start.y === left.end.y &&
        right.start.y === right.end.y &&
        left.start.y === right.start.y;
      if (!vertical && !horizontal) continue;
      const [leftStart, leftEnd, rightStart, rightEnd] = vertical
        ? [left.start.y, left.end.y, right.start.y, right.end.y]
        : [left.start.x, left.end.x, right.start.x, right.end.x];
      const overlap =
        Math.min(Math.max(leftStart, leftEnd), Math.max(rightStart, rightEnd)) -
        Math.max(Math.min(leftStart, leftEnd), Math.min(rightStart, rightEnd));
      const opposite =
        Math.sign(leftEnd - leftStart) !== Math.sign(rightEnd - rightStart);
      if (overlap > 0 && opposite) {
        opposingOverlaps.push(`${left.edgeId}<->${right.edgeId}`);
      }
    }
  }
  assert.deepEqual(opposingOverlaps, []);

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
