import type { RecordedFact, RecordedGraph, RecordedResource } from "../src/recorded/contract";

export function fixtureFact(value: string | null, at = "2026-09-01T10:00:00Z"): RecordedFact {
  return { value, observed_at: at, recorded_at: at, source_path: "powerState",
    freshness: "fresh", completeness: 1, conflicts: [], reason: null };
}
export function fixtureGraph(value = "running", at = "2026-09-01T10:00:00Z"): RecordedGraph {
  const resources: RecordedResource[] = [
    { id: "fixture-vm", name: "Fixture VM", resourceType: "compute.vm", incarnation: null,
      states: { operational: fixtureFact(value, at), provisioning: fixtureFact("Succeeded"), availability: fixtureFact(null) } },
    { id: "fixture-store", name: "Fixture store", resourceType: "object-storage", incarnation: null, states: null },
    { id: "fixture-net", name: "Fixture network", resourceType: "network.subnet", incarnation: null, states: null },
  ];
  return { kind: "graph", root: "fixture-vm", generation: `fixture-generation-${at}`, cutoff: at, complete: false,
    reasons: ["resource_limit"], resources,
    links: [
      { source: "fixture-vm", target: "fixture-store", type: "depends_on", evidence: { status: "available", verification: "configuration_observed", cutoff: at, complete: true } },
      { source: "fixture-vm", target: "fixture-net", type: "attached_to", evidence: { status: "available", verification: "configuration_observed", cutoff: at, complete: true } },
    ] };
}
