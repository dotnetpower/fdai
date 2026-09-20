# Continuous Operational Instance Graph Evidence

This companion records the source-to-store implementation audit and operational state-transition evidence for the continuous graph. The parent document owns collection, retention, and query semantics.

## Design at a glance

This focused owner preserves the detailed contract formerly embedded in [continuous-operational-instance-graph.md](continuous-operational-instance-graph.md).

## Source-to-store implementation audit

OI-01 records the exact code owner, runtime or storage binding, focused tests, state, and missing
binding for each stage in
[`config/continuous-operational-instance-graph-audit.json`](../../../config/continuous-operational-instance-graph-audit.json).
The checker rejects missing stages or evidence, unassigned work, implemented work with partial or
unbound bindings, and unnamed open gaps. It records synthetic, deployed-binding, and production-data
validation separately; normative ownership remains here and delivery status remains in the linked ledger.

| Stage | State | Audited result |
|-------|-------|----------------|
| Provider push ingress | implemented | Event Grid writes and deletes reach the raw Event Hub, then `_consume_resource_changes` normalizes them into canonical inventory events. |
| Resumable delta cursor | implemented | `forward_inventory_delta` advances the durable Activity Log cursor only after the final fence. |
| Complete reconciliation | implemented | `InventorySyncCoordinator.run` stages bounded ARG or ARM observations and accepts only a complete stream. |
| Normalized observation ingress | implemented | `PostgresInventoryDeltaProjector.__call__` validates typed observation semantics and dual-writes the Core-owned append-only observation journal before updating the existing overlay. |
| Snapshot promotion | implemented | `PostgresInventorySnapshotStore.promote` atomically advances the active generation and records exact Resource and Link counts under the promotion lock. Operator activity reads use those immutable summaries and fall back to bounded child-row aggregation only for mixed-version rows without counts. |
| Realtime overlay | implemented | PostgreSQL overlay rows replay normalized observations by effective time and content identity, merge only the declared property mask, preserve unobserved snapshot properties, and keep tombstone candidates pending until complete reconciliation. |
| Ontology projection | implemented | `InventoryOntologyProjector.apply` is the single writer for the inventory-owned Resource and Link subgraph. Reviewed nested operational fields are lifted with their observation metadata, while journal and projection watermarks plus pending tombstones independently lower source completeness. |
| Topology history | implemented | `InventoryTopologyHistoryPublisher.publish` appends complete baselines through the Core-owned bitemporal PostgreSQL store and migration. |
| Graph-first query | implemented | Ordinary exact-target current-state queries read the secured graph first, present verified partial read-only results with explicit guidance, and hold when no safe subset exists. |
| Bounded live read | implemented | One exact secured Resource may trigger at most one server-scoped provider read under fixed limits. Wider, malformed, or unresolved queries decline or hold. |
| Live evidence write-through | implemented | Verified live evidence enters the canonical typed partial-overlay ingress with a property mask and content-bound idempotency, and cannot delete unobserved properties or relationships. |
| Adaptive scheduling | implemented | Validated source policies and a pure reducer consume freshness, lag, demand, provider pressure, `Retry-After`, remaining budget, concurrency, circuit-open state, and recovery probes. PostgreSQL supplies durable due state, and the principal-safe health projection exposes the next bounded action. |
| Retention and holds | implemented | The archive purge coordinator blocks deletion until exact verification, restore sampling, and retention or legal-hold evaluation pass. Append-only PostgreSQL receipts preserve blocked, pending, failed, successful, and retry outcomes. |
| Typed rollup | implemented | Fact-specific policies separately aggregate gauges, counters, categorical state, relationship changes, and evidence health while preserving source and generation lineage, bitemporal ranges, missing intervals, observed zero, conflicts, completeness, and mergeable count and sum. Percentiles remain unavailable. |
| Archive lifecycle | in-progress | Content-addressed manifests, private Azure Blob I/O, principal-scoped reads, database-gated purge, and append-only lifecycle receipts are implemented. Container Apps and AKS schedule fixed `shadow` jobs. Non-shadow startup requires an exact persisted certification receipt before state or Blob access. The retained OI-16 receipt validates synthetic mechanics and deployed binding; recurring production-data retention remains unvalidated and separately authorized. |

Protected receipt readback resolves the storage account through an account-specific record in the
ops-owned Blob private DNS zone linked to the deploy runner VNet. Workload resolution remains in the
app-owned zone. This split grants neither public network access nor storage key authentication.

## Operational state-transition ledger

FDAI stores semantic state changes in a Core-owned append-only PostgreSQL ledger. Event Hubs
transports observations, OpenTelemetry reports diagnostics, and the ontology remains a rebuildable
current-state projection. None of those surfaces replaces the transition ledger.

Each atomic batch contains zero or more content-addressed transitions and at least one positive
coverage record. A transition binds `from_state`, `to_state`, effective time, recorded time,
evidence cutoff, source identity and revision, producer version, freshness, completeness,
conflicts, and evidence references. Replayed idempotency keys are no-ops only for identical content.
Coverage identity is global and content-addressed. A recovered batch can reference an identical
retained coverage record without inserting a second row, and replay verifies each expected child by
its content identity rather than requiring the child to have been first inserted by that batch.

The inventory path records operational and availability changes only with property-level evidence.
Provisioning remains current-state only until it carries equivalent provenance. Every interval is
`initial_state_only` or `snapshot_interval_only`; complete snapshots cannot prove that no intermediate
transition occurred, and only exact retained watermarks can raise that coverage.

## Related docs

| To learn about | Read |
|----------------|------|
| Parent design | [Continuous Operational Instance Graph](continuous-operational-instance-graph.md) |
| Delivery status and remaining work | [Implementation ledger](../../roadmap-implementation/architecture/continuous-operational-instance-graph-evidence.md) |
