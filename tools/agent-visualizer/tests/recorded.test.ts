import assert from "node:assert/strict";
import { test } from "node:test";
import { decodeRecordedPayload } from "../src/recorded/contract";
import { observedChanges, mergeChanges } from "../src/recorded/history";
import { layoutRelationships, relationshipSubset } from "../src/recorded/layout";
import { fixtureGraph } from "./recorded-fixture";
import { agentColor, agents } from "../src/agents";

test("recorded projection boundary preserves exact states, rejects missing endpoints, and strips extra capabilities", () => {
  const graph = fixtureGraph();
  assert.deepEqual(decodeRecordedPayload(graph), graph);
  const decoded = decodeRecordedPayload({ ...graph, token: "not-an-auth-token", context_capability: "test-only-placeholder" });
  assert.equal("token" in decoded, false);
  assert.equal("context_capability" in decoded, false);
  assert.throws(() => decodeRecordedPayload({ ...graph, resources: [] }), /root/);
  assert.throws(() => decodeRecordedPayload({ ...graph, links: [{ ...graph.links[0], target: "missing" }] }), /endpoint/);
  assert.throws(() => decodeRecordedPayload({ ...graph, cutoff: "bad" }), /timestamp/);
});

test("observed state changes require newer, consistent source facts and never reinterpret audit execution", () => {
  const first = fixtureGraph();
  const second = fixtureGraph("stopped", "2026-09-01T10:01:00Z");
  const changes = observedChanges(first, second, "2026-09-01T10:01:01Z");
  assert.equal(changes.length, 1);
  assert.equal(changes[0]!.before.value, "running");
  assert.equal(changes[0]!.after.value, "stopped");
  assert.equal(changes[0]!.axis, "operational");
  assert.equal(observedChanges(first, fixtureGraph("stopped"), "2026-09-01T10:01:01Z").length, 0);
  assert.equal(observedChanges(first, first, "2026-09-01T10:01:01Z").length, 0);
  assert.equal(observedChanges(second, first, "2026-09-01T10:01:01Z").length, 0);
  assert.equal(observedChanges(first, { ...second, root: "fixture-store" }, "2026-09-01T10:01:01Z").length, 0);
  assert.equal(mergeChanges(changes, changes).length, 1);
});

test("new incarnations, unknown facts, conflicts and property changes are not invented transitions", () => {
  const first = fixtureGraph();
  const second = fixtureGraph("stopped", "2026-09-01T10:01:00Z");
  const resource = second.resources[0]!;
  assert.equal(observedChanges(first, { ...second, resources: [{ ...resource, incarnation: "new-lifecycle" }, ...second.resources.slice(1)] }, second.cutoff).length, 0);
  for (const override of [{ value: null }, { source_path: "differentField" }, { conflicts: ["conflicting_evidence"] }, { freshness: "unknown" as const }]) {
    const changed = { ...resource, states: { ...resource.states!, operational: { ...resource.states!.operational, ...override } } };
    assert.equal(observedChanges(first, { ...second, resources: [changed, ...second.resources.slice(1)] }, second.cutoff).length, 0);
  }
});

test("relationship layouts contain only returned resources and retain coordinates on state refresh", () => {
  const graph = fixtureGraph();
  const layout = layoutRelationships(graph);
  assert.equal(layout.size, 3);
  assert.deepEqual(layout, layoutRelationships(graph));
  assert.deepEqual(layoutRelationships(fixtureGraph("stopped"), layout), layout);
  assert.equal(relationshipSubset(graph, "depends_on").resources.length, 2);
  assert.equal(relationshipSubset(graph, "attached_to").links.length, 1);
  assert.equal(relationshipSubset(graph, "none").resources.length, 1);
});

test("Loki retains red identity styling without changing its canonical family", () => {
  assert.equal(agentColor("Loki"), "#ff747d");
  assert.notEqual(agentColor("Loki"), agentColor("Thor"));
  assert.equal(agents.find((agent) => agent.id === "Loki")!.family, "act");
});
