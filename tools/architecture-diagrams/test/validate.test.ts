import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import {
  NETWORK_BOUNDARY_ROLES,
  NETWORK_CONNECTION_KINDS,
  NETWORK_LAYOUT_PRESETS,
} from "@fdai/network-topology-contracts";

import { parseDiagram, validateDiagram } from "../src/model/validate.js";

const minimalDiagram = `
id: sample
version: 1
kind: container
locales:
  en:
    title: Sample
    description: Sample diagram
    alt: A source sends an event to a processor.
  ko:
    title: Sample
    description: Sample diagram
    alt: Source가 processor로 event를 보냅니다.
canvas:
  width: 960
  height: 540
  direction: RIGHT
groups:
  - id: control-plane
    kind: system
    label: { en: Control plane, ko: Control plane }
nodes:
  - id: source
    kind: external
    label: { en: Source, ko: Source }
  - id: processor
    parent: control-plane
    kind: process
    label: { en: Processor, ko: Processor }
edges:
  - id: source-to-processor
    from: source
    to: processor
    kind: event
`;

test("parses a bilingual diagram specification", () => {
  const diagram = parseDiagram(minimalDiagram);
  assert.equal(diagram.id, "sample");
  assert.equal(diagram.nodes.length, 2);
});

test("parses optional semantic presentation settings", () => {
  const diagram = parseDiagram(minimalDiagram);
  diagram.canvas.profile = "azure-reference";
  diagram.groups[0]!.presentation = "boundary";
  diagram.nodes[1]!.icon = "key-vault";
  diagram.nodes[1]!.presentation = "icon";
  diagram.edges[0]!.step = 1;

  assert.doesNotThrow(() => validateDiagram(diagram));
});

test("parses the authored network profile without changing generic element kinds", () => {
  const diagram = parseDiagram(minimalDiagram);
  diagram.kind = "network";
  diagram.posture = "expected";
  diagram.canvas.profile = "network-azure-reference";
  diagram.canvas.networkPreset = "hub-spoke";
  diagram.groups[0]!.networkRole = "hub";
  diagram.groups[0]!.addressPrefixes = ["<address-prefix>"];
  diagram.nodes[0]!.networkRole = "external";
  diagram.nodes[1]!.securityFacts = [{ en: "Inspected", ko: "검사됨" }];
  diagram.edges[0]!.connectionKind = "traffic";
  diagram.edges[0]!.direction = "forward";
  diagram.edges[0]!.trafficClass = "internet";
  diagram.edges[0]!.policy = "inspect";
  diagram.edges[0]!.protocol = "HTTPS";
  diagram.edges[0]!.port = "443";
  diagram.edges[0]!.sourceEvidence = "expected";
  diagram.annotations = [{
    id: "routing-intent",
    title: { en: "Routing intent", ko: "라우팅 의도" },
    body: [{ en: "Internet traffic is inspected.", ko: "인터넷 트래픽을 검사합니다." }],
    tone: "policy",
    placement: "top-left",
    anchor: "control-plane",
  }];

  assert.doesNotThrow(() => validateDiagram(diagram));
});

test("requires expected posture for authored network semantics", () => {
  const diagram = parseDiagram(minimalDiagram);
  diagram.kind = "network";
  assert.throws(
    () => validateDiagram(diagram),
    /Authored network diagrams require posture 'expected'/,
  );
});

test("keeps the authored schema aligned with shared network vocabulary", () => {
  const schema = JSON.parse(readFileSync(
    new URL("../schema/diagram.schema.json", import.meta.url),
    "utf8",
  )) as {
    definitions: Record<string, { enum: string[] }>;
    properties: { canvas: { properties: { networkPreset: { enum: string[] } } } };
  };
  assert.deepEqual(schema.definitions.networkBoundaryRole!.enum, NETWORK_BOUNDARY_ROLES);
  assert.deepEqual(schema.definitions.networkConnectionKind!.enum, NETWORK_CONNECTION_KINDS);
  assert.deepEqual(schema.properties.canvas.properties.networkPreset.enum, NETWORK_LAYOUT_PRESETS);
});

test("rejects duplicate element identifiers", () => {
  const diagram = parseDiagram(minimalDiagram);
  diagram.nodes[1]!.id = "source";
  assert.throws(() => validateDiagram(diagram), /Duplicate diagram element id: source/);
});

test("rejects an edge with an unknown endpoint", () => {
  const diagram = parseDiagram(minimalDiagram);
  diagram.edges[0]!.to = "missing";
  assert.throws(() => validateDiagram(diagram), /Unknown edge endpoint 'missing'/);
});

test("rejects an unknown group alignment reference", () => {
  const diagram = parseDiagram(minimalDiagram);
  diagram.groups[0]!.alignWith = "missing";
  assert.throws(
    () => validateDiagram(diagram),
    /Unknown alignment group 'missing' on 'control-plane'/,
  );
});

test("allows an edge to target a group boundary", () => {
  const diagram = parseDiagram(minimalDiagram);
  diagram.edges[0]!.to = "control-plane";
  assert.doesNotThrow(() => validateDiagram(diagram));
});

test("rejects an edge with an unknown node port", () => {
  const diagram = parseDiagram(minimalDiagram);
  diagram.edges[0]!.to = "processor:missing";
  assert.throws(
    () => validateDiagram(diagram),
    /Unknown edge port 'processor:missing'/,
  );
});

test("requires both display locales", () => {
  const diagram = parseDiagram(minimalDiagram) as unknown as Record<string, unknown>;
  const locales = diagram.locales as Record<string, unknown>;
  delete locales.ko;
  assert.throws(() => validateDiagram(diagram), /must have required property 'ko'/);
});

test("requires an asset for icon presentation", () => {
  const diagram = parseDiagram(minimalDiagram);
  diagram.nodes[1]!.presentation = "icon";
  assert.throws(
    () => validateDiagram(diagram),
    /Icon presentation requires an icon on 'processor'/,
  );
});
