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
| Complete reconciliation | implemented | `InventorySyncCoordinator.run` stages bounded ARG or ARM observations and accepts only a complete stream. Provider, source/enrichment and existing 1 MiB durable-chunk guards preflight JSON-shaped records before copying, normalization or whole-string encoding, without truncation; [normalized-record allocation preflight](../interfaces/azure-resource-discovery-commands.md#normalized-record-allocation-preflight) preserves exact encoder accounting and names the remaining allocation limits. |
| Normalized observation ingress | implemented | `PostgresInventoryDeltaProjector.__call__` validates typed observation semantics and dual-writes the Core-owned append-only observation journal before updating the existing overlay. |
| Snapshot promotion | implemented | `PostgresInventorySnapshotStore.promote` atomically advances the active generation and records exact Resource and Link counts under the promotion lock. Operator activity reads use those immutable summaries and fall back to bounded child-row aggregation only for mixed-version rows without counts. |
| Realtime overlay | implemented | PostgreSQL overlay rows replay normalized observations by effective time and content identity, merge only the declared property mask, preserve unobserved snapshot properties, and keep tombstone candidates pending until complete reconciliation. |
| Ontology projection | implemented | `InventoryOntologyProjector.apply` is the single writer for the inventory-owned Resource and Link subgraph. Reviewed nested operational fields are lifted with their observation metadata, while journal and projection watermarks plus pending tombstones independently lower source completeness. |
| Topology history | implemented | `InventoryTopologyHistoryPublisher.publish` appends complete baselines through the Core-owned bitemporal PostgreSQL store and migration. |
| Graph-first query | implemented | Ordinary exact-target current-state queries read the secured graph first, present verified partial read-only results with explicit guidance, and hold when no safe subset exists. |
| Bounded live read | implemented | One exact secured Resource may trigger at most one server-scoped provider read under fixed limits. Wider, malformed, or unresolved queries decline or hold. Exact-revision certification stores its authority-free receipt through a task-owned private endpoint address with normal hostname verification and no shared DNS mutation. A delayed best-effort SSL shutdown cannot erase an already verified handshake, and PostgreSQL TLS is proven through its negotiated protocol plus `pg_stat_ssl`. |
| Live evidence write-through | implemented | Verified live evidence enters the canonical typed partial-overlay ingress with a property mask and content-bound idempotency, and cannot delete unobserved properties or relationships. |
| Adaptive scheduling | implemented | Validated source policies and a pure reducer consume freshness, lag, demand, provider pressure, `Retry-After`, remaining budget, concurrency, circuit-open state, and recovery probes. PostgreSQL supplies durable due state, and the principal-safe health projection exposes the next bounded action. |
| Retention and holds | implemented | The archive purge coordinator blocks deletion until exact verification, restore sampling, and retention or legal-hold evaluation pass. Append-only PostgreSQL receipts preserve blocked, pending, failed, successful, and retry outcomes. |
| Typed rollup | implemented | Fact-specific policies separately aggregate gauges, counters, categorical state, relationship changes, and evidence health while preserving source and generation lineage, bitemporal ranges, missing intervals, observed zero, conflicts, completeness, and mergeable count and sum. Percentiles remain unavailable. |
| Archive lifecycle | in-progress | Content-addressed manifests, private Azure Blob I/O, principal-scoped reads, database-gated purge, and append-only lifecycle receipts are implemented. Container Apps and AKS schedule fixed `shadow` jobs. Non-shadow startup requires an exact persisted certification receipt before state or Blob access. The retained OI-16 receipt validates synthetic mechanics and deployed binding; recurring production-data retention remains unvalidated and separately authorized. |

Protected receipt readback resolves the storage account through an account-specific record in the
ops-owned Blob private DNS zone linked to the deploy runner VNet. Workload resolution remains in the
app-owned zone. This split grants neither public network access nor storage key authentication.

## Projection allocation admission

The pure inventory projection admits at most 2,000,000 expanded values (including containers and
mapping keys) and 16,777,216 string
characters before copying properties, adjudicating observations, or building graph objects.
Repeated references count for each occurrence because normalization expands them; a cycle or
excessive input depth is held with an explicit error. Existing resource/link count and
canonical-value checks still apply. Dense containers can pass the existing byte allowances yet
exceed this normalization-work limit.

These are explicit work counters, not a weighted shallow-size estimator, encoded JSON size,
peak allocation, or process RSS. They do not replace the collection's 16 MiB normalized-generation
allowance or its 1 MiB durable chunk limit. Failure returns no partial projection and grants no
source, promotion, or execution authority; snapshot and derived graph ownership remain separate.

The authoritative [retained-concept assessment](../../roadmap-implementation/interfaces/azure-resource-discovery-commands.md#retained-concept-assessment-2111)
completes the three-disposition spike classification (`already present`, `superseded`, or
`a reproducible residual`). The snapshot store also enforces a 1 MiB pre-copy byte ceiling on
canonical JSON mappings, a 4 MiB cumulative UTF-8 wire bound per `jsonb_to_recordset` SQL batch,
pre-seal projection allocation admission, and locked durable candidate identity and interval checks
during promotion. Independent-issuer and whole-interval visibility attestation, restart-durable
shared request/byte and cooldown admission, within-generation equivalent read reuse, and deployed
peak-RSS qualification remain open reproducible residuals tracked in #2329, #1393, and findings 04,
13, 14, 17, and 31.

## Collection authentication configuration

ARG/ARM effective collection configuration now includes a secret-free digest of the existing
adapter's configured authentication mode and selector. Existing PostgreSQL prepared-candidate and
unfinished-chunk readers refuse reuse under a changed configured client/backend selector, while
identical effective inputs retain their original attempt. This is configuration continuity, not
authenticated principal identity or permission. Unknown injected identity adapters remain unbound.
The [scoped correction and critique](../interfaces/azure-resource-discovery-commands.md#scoped-correction-configured-authentication-selector-continuity)
defines the included selectors and excluded credentials. Durable shared admission, whole-interval
identity proof and actual installation consumption remain unqualified under #2329 and #1393.

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

## Conversation consumers

Conversation turns read this graph only through typed projections and never write to it. The Operator
relays each model-call activity with closed stage, deployment, and duration codes beside its text so the
Console renders it in its own language. Core builds the result-handle store for answered lists only when
`conversation.result_handles.enabled` is on and its database and key inputs exist. Neither changes the
ledger, a coverage record, or any authority.

## Related docs

| To learn about | Read |
|----------------|------|
| Parent design | [Continuous Operational Instance Graph](continuous-operational-instance-graph.md) |
| Delivery status and remaining work | [Implementation ledger](../../roadmap-implementation/architecture/continuous-operational-instance-graph-evidence.md) |
