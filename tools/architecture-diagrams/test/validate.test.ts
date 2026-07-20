import assert from "node:assert/strict";
import test from "node:test";

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
