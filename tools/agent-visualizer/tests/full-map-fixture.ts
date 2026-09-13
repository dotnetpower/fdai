/** Isolated test data only; the application never imports this module. */
export function fullMapFixture() {
  const catalog = [
    ["Resource", 2, 0, 0], ["Conversation", 1, 120, 90], ["Principal", 1, 240, 0], ["Signal", 0, 100, 180],
  ].map(([name, count, x, y]) => ({
    id: `catalog:ot:${name}`, label: String(name), kind: "object_type", objectType: String(name),
    group: "ObjectTypes", detail: `Fixture declaration ${name}`, x, y, community: 1, degree: 2, instanceCount: count,
  }));
  const instances = [
    ["one", "Resource"], ["two", "Resource"], ["conversation", "Conversation"], ["principal", "Principal"],
  ].map(([id, type]) => ({
    id: `db:${id}`, label: `${type} / fixture-${id}`, kind: "instance", objectType: type,
    resourceType: null, typeNode: `catalog:ot:${type}`, revision: 1,
    state: { value: type === "Resource" ? "running" : null, lane: "stored",
      effectiveAt: null, recordedAt: null, synthetic: null },
  }));
  return {
    version: 2,
    source: { kind: "local-postgresql", capturedAt: "2026-09-01T12:00:00Z", readOnly: true,
      isolation: "repeatable-read", privacy: "pseudonymized-identities-no-bodies", catalogDigest: "fixture-catalog",
      catalogComplete: true, databaseReadComplete: true },
    counts: { objectTypes: 4, catalogNodes: 4, catalogLinks: 2, instances: 4, storedLinks: 2,
      resolvedStoredLinks: 2, unresolvedStoredLinks: 0, history: 2, historyForCurrentInstances: 2,
      byType: { Resource: 2, Conversation: 1, Principal: 1 } },
    nodes: [...catalog, ...instances],
    links: [
      { id: "catalog:depends", source: "catalog:ot:Resource", target: "catalog:ot:Resource", type: "depends_on", kind: "link_type", origin: "catalog" },
      { id: "catalog:belongs", source: "catalog:ot:Conversation", target: "catalog:ot:Principal", type: "conversation_belongs_to", kind: "link_type", origin: "catalog" },
      { id: "db:depends", source: "db:one", target: "db:two", type: "depends_on", kind: "instance_link", origin: "database" },
      { id: "db:belongs", source: "db:conversation", target: "db:principal", type: "conversation_belongs_to", kind: "instance_link", origin: "database" },
      ...instances.map((node) => ({ id: `classification:${node.id}`, source: node.id, target: node.typeNode, type: "instance_of", kind: "classification", origin: "classification" })),
    ],
    history: [
      { id: "transition:one", subject: "db:one", stateType: "resource.operational_state", before: "running", after: "stopped",
        lane: "observed", authority: "provider", effectiveAt: "2026-09-01T10:00:00Z", recordedAt: "2026-09-01T10:00:01Z",
        synthetic: false, completeness: 1, conflicts: 0 },
      { id: "transition:two", subject: "db:one", stateType: "resource.operational_state", before: "stopped", after: "running",
        lane: "observed", authority: "provider", effectiveAt: "2026-09-01T11:00:00Z", recordedAt: "2026-09-01T11:00:01Z",
        synthetic: false, completeness: 1, conflicts: 0 },
    ],
  };
}
