import assert from "node:assert/strict";
import test from "node:test";

import { layoutDiagram } from "../src/layout/elk.js";
import { parseDiagram } from "../src/model/validate.js";

const source = `
id: bottom-route
version: 1
kind: container
locales:
  en: { title: Bottom route, description: Approval return, alt: Approval return }
  ko: { title: Bottom route, description: Approval return, alt: Approval return }
canvas: { width: 900, height: 500, direction: RIGHT }
groups:
  - id: control
    kind: system
    label: { en: Control, ko: Control }
  - id: human
    kind: layer
    label: { en: Human, ko: Human }
nodes:
  - id: executor
    parent: control
    kind: process
    label: { en: Executor, ko: Executor }
    ports:
      - { id: approval-in, side: SOUTH }
  - id: chatops
    parent: human
    kind: service
    label: { en: ChatOps, ko: ChatOps }
    ports:
      - { id: approval-out, side: SOUTH }
edges:
  - id: approval-return
    from: chatops:approval-out
    to: executor:approval-in
    kind: approval
    label: { en: approved decision, ko: approved decision }
`;

test("routes cross-group SOUTH ports through one short bottom lane", async () => {
  const spec = parseDiagram(source);
  const layout = await layoutDiagram(spec);
  const edge = layout.edges.find((candidate) => candidate.id === "approval-return");
  const section = edge?.sections?.[0];
  const sourceNode = layout.nodes.get("chatops");
  const targetNode = layout.nodes.get("executor");

  assert.ok(edge && section && sourceNode && targetNode);
  assert.equal(edge.container, undefined);
  assert.equal(section.bendPoints?.length, 2);
  assert.equal(section.startPoint.y, sourceNode.y + sourceNode.height);
  assert.equal(section.endPoint.y, targetNode.y + targetNode.height);
  assert.equal(section.bendPoints?.[0]?.x, section.startPoint.x);
  assert.equal(section.bendPoints?.[1]?.x, section.endPoint.x);
  assert.equal(section.bendPoints?.[0]?.y, section.bendPoints?.[1]?.y);
});
