import assert from "node:assert/strict";
import { test } from "node:test";
import { decodeOntologySnapshot } from "../src/recorded/snapshot";
import { fullMapLayout, relationshipSubset } from "../src/recorded/layout";
import { RecordedStore } from "../src/recorded/store";
import { fullMapFixture } from "./full-map-fixture";
import { mapCurve } from "../src/recorded/map-curves";
import { Vector3 } from "three";

test("full map preserves every ObjectType, including zero-instance types, and every DB instance", () => {
  const snapshot = decodeOntologySnapshot(fullMapFixture());
  assert.equal(snapshot.counts.objectTypes, 4);
  assert.equal(snapshot.graph.resources.length, 8);
  assert.equal(snapshot.graph.links.length, 8);
  assert.equal(snapshot.graph.resources.find((node) => node.objectType === "Signal")?.instanceCount, 0);
  assert.equal(snapshot.counts.instances, 4);
  assert.equal(snapshot.source.kind, "local-postgresql");
});

test("full map refuses incomplete accounting, absent types and fabricated endpoints", () => {
  const raw = fullMapFixture();
  assert.throws(() => decodeOntologySnapshot({ ...raw, source: { ...raw.source, readOnly: false } }), /read-only/);
  assert.throws(() => decodeOntologySnapshot({ ...raw, counts: { ...raw.counts, instances: 3 } }), /count/);
  assert.throws(() => decodeOntologySnapshot({ ...raw, nodes: raw.nodes.slice(1) }), /endpoint|count/);
  assert.throws(() => decodeOntologySnapshot({ ...raw, links: [{ ...raw.links[0], target: "missing" }, ...raw.links.slice(1)] }), /endpoint/);
  assert.throws(() => decodeOntologySnapshot({ ...raw, source: { ...raw.source, kind: "synthetic-mock" } }), /read-only/);
});

test("layers and type filters are presentation subsets, not input omissions", () => {
  const graph = decodeOntologySnapshot(fullMapFixture()).graph;
  assert.equal(relationshipSubset(graph, "all", "all").resources.length, 8);
  assert.equal(relationshipSubset(graph, "all", "catalog").resources.length, 4);
  assert.equal(relationshipSubset(graph, "all", "instances", "Resource").resources.length, 3);
  const layout = fullMapLayout(graph);
  assert.equal(layout.size, graph.resources.length);
  assert.deepEqual(layout, fullMapLayout(graph));
  assert.ok([...layout.values()].every((point) => point.every(Number.isFinite)));
});

test("recorded playback never changes the stored snapshot and retains per-axis semantics", () => {
  const snapshot = decodeOntologySnapshot(fullMapFixture());
  const store = new RecordedStore();
  store.snapshot = snapshot;
  store.graph = snapshot.graph;
  store.events = snapshot.events;
  store.setReplayEnabled(true);
  store.setReplay(0, 72);
  assert.equal(store.graph?.resources.find((node) => node.id === "db:one")?.presentationState, "stopped");
  store.setReplay(72, 72);
  assert.equal(store.graph?.resources.find((node) => node.id === "db:one")?.presentationState, "running");
  store.setReplayStateType("resource.availability_state");
  assert.equal(store.graph?.resources.find((node) => node.id === "db:one")?.presentationState, null);
  store.setReplayEnabled(false);
  assert.equal(store.graph, snapshot.graph);
  assert.equal(snapshot.graph.resources.find((node) => node.id === "db:one")?.storedState?.value, "running");
});

test("self-typed relationships have a visible loop rather than a zero-length edge", () => {
  const origin = new Vector3(2, 3, 4);
  const curve = mapCurve(origin, origin, "depends_on");
  assert.ok(curve.getLength() > 1);
  assert.ok(curve.getPoint(0).distanceTo(origin) < 0.001);
  assert.ok(curve.getPoint(1).distanceTo(origin) < 0.001);
});
