---
title: Recorded Resource State
---
# Recorded Resource State

This document owns the shared read model for Resource state shown by Dashboard v2 and
Ontology Instances. It preserves recorded values and their evidence instead of creating another
browser-side operational verdict.

> **Authority boundary:** Reading a record does not prove current health or authorize a change.
> The inventory job performs the reviewed provider read and single-writer projection. Console and
> conversational consumers do not perform a provider write, model invocation, or state mutation.

## Design at a glance

The existing instance reader supplies Resource properties from one immutable active inventory
generation. The Operator Service projects these properties into three independent recorded-state
axes. Both Console screens consume the same versioned shape.

| Axis | Recorded fields | Not inferred |
|------|-----------------|--------------|
| Operational | Explicit service, power, phase, readiness, running, attachment, access, or link state, including retained nested `runningStatus`, `powerState.code`, `diskState`, `snapshotAccessState`, and `virtualNetworkLinkState`. | Provisioning success does not become running. Enabled, Online, Active, Attached, and Completed keep their recorded meaning. |
| Provisioning | Explicit `provisioningState`. | Successful creation does not establish availability. |
| Availability | Explicit availability evidence. | Running and Succeeded do not establish healthy service. |

## Recorded fact contract

The additive resource `states` object has `schema_version: "1.0.0"` and `operational`,
`provisioning`, and `availability` facts. Existing `status` remains for older consumers.
Each fact carries:

- `value` and `source_path`, nullable when no state was recorded.
- `observed_at` and `recorded_at`, without substituting an inventory read time for effective time.
- `freshness: fresh | stale | unknown` and nullable `completeness`.
- Bounded `conflicts` and a nullable machine-readable `reason`.

Stale or conflicting values remain visible as recorded values with qualifications. Missing metadata
remains unknown; it never becomes an invented observation receipt. A missing value is not automatically
not-applicable. The display projection is not a replacement for the existing decision-critical
ontology query verifier or its receipts.

For active snapshots created before property-level metadata was recorded, the read model qualifies a
retained value from the immutable Resource `last_seen` timestamp and the snapshot completion cutoff.
It preserves `last_seen` as effective time and never substitutes the later cutoff for that time.
Malformed or reversed timestamps remain unknown.

Operational applicability is explicit and conservative. Every canonical ResourceType has one
reviewed outcome:

| Outcome | Meaning |
|---------|---------|
| `state_source_not_recorded` | The type has an explicit provider or Kubernetes state contract, but the selected generation contains no usable value. This includes service, power, readiness, database, broker, disk, snapshot-access, and private-DNS-link states. |
| `provider_operational_state_not_exposed` | The resource can have operational concerns, but its current provider inventory contract exposes no per-resource operational state and has no reviewed alternate source in this projection. |
| `state_not_applicable` | The reviewed type or axis has no single applicable state. This includes Application Insights operational and availability state and Log Analytics operational state. |
| `resource_type_unclassified` | The provider type has no reviewed canonical ResourceType mapping. |
| `state_applicability_unknown` | A downstream custom type has not been reviewed. Canonical types do not use this fallback. |

Exact values always win over the missing-value classification. Missing metadata, stale evidence, and
conflicts continue to qualify the retained value without changing its source, observation time,
recording time, freshness, or completeness.

## Batch query and consistency

`GET /ontology/instances/states` is a read-only route in the existing authenticated operations family.
It accepts bounded `limit`, optional `search`, and a continuation `cursor`.

| Property | Contract |
|----------|----------|
| Page size | At most 500 Resources in deterministic resource-id order. No per-resource API fan-out. |
| Exclusions | Authorization role assignments, subscription containers, and resource-group containers are not operational roster items. |
| Identity | Every page preserves `source_kind`, `source_generation`, `source_cutoff`, `ontology_generation`, `ontology_manifest_digest`, and `ontology_release_digest`. |
| Count | `total_count` describes the same-generation query, not an inferred tenant-wide total. |
| Continuation | The cursor binds generation, query and authenticated principal context. It is a selector, never authority. Invalid or changed context is rejected. |
| Completion | `next_cursor` is explicit; `complete` is true only on the last page. An empty page cannot carry a continuing cursor. |
| Generation fence | The active inventory generation, committed inventory-owned ontology generation, and ontology release must agree before and after each page read. A mismatch returns a bounded conflict. |
| Change during traversal | A replaced inventory or ontology manifest requires a new read. Pages from different generations cannot be merged. |

Dashboard loads bounded pages, rejects duplicate records and changing totals/cutoffs/releases, and
caps accumulation at 20,000 records under a total deadline. Reaching that bound is explicit partial
coverage. A transport or schema failure is not converted into an empty inventory or a graph fallback.
Display filters and local pages operate on this received set; the server query remains the authority.

## Unified state ingestion and readers

Resource discovery establishes identity and configuration. A separate reviewed state enricher may
add only a typed state value and canonical state-fact metadata before the generation is promoted.
It cannot replace identity, configuration, topology, or inventory observation time.

The promoted Resource fact is written to both the current `ontology_resource` Resource and the
Operator-readable inventory projection under one generation fence. Core conversational functions
read the ontology instance. Operator instance and batch-state reads use the service-approved
projection of the same fact because the Operator role has no direct Core-table access.

State transition recording is independent of relationship completeness. A complete object
observation can advance operational or availability state history even when an unrelated topology
edge remains unresolved. Relationship history still requires complete relationship evidence.

The first reviewed alternate source is Azure Resource Health for `log-workspace` availability:

- `log-workspace` has no single operational running state. Its operational axis is not applicable,
  while its availability axis uses the exact ARM Resource Health status.
- `application-insights` has no direct Resource Health status. Its operational and availability
  axes are not applicable. The backing Log Analytics workspace remains a separate related Resource;
  its health is never copied onto Application Insights.
- A failed, unauthorized, malformed, partial, or stale state read records the exact source
  limitation and never substitutes `provisioningState`, existence, or a previous unqualified value.

## Presentation and compatibility

- Dashboard v2 uses the shared state query, not the legacy `inventory/graph` status string.
- Ontology directory and exploration records expose the same additive `states` field from the
  ontology-owned current Resource state.
- The shared Console fact view shows source values, timing, freshness, completeness, and reasons.
- Missing values render as Not recorded, Unavailable, Not applicable, or Applicability unknown
  from the machine reason. Legacy generations can still identify an unbound source explicitly.
- Dashboard labels the source as `inventory_snapshot_resource`, groups Unknown records by their
  machine reason, and refreshes on the shared interval, browser resume, and inventory invalidation.
- State colors organize recorded values; they do not assert a current operational success.
- The original Dashboard and older instance clients retain their existing routes and fields.
- Resource inspection and selection do not grant approval or execution authority.

## Rejected alternatives

Reading raw provider properties in each browser view duplicates normalization and loses source
semantics. Re-querying Azure or invoking a model to rediscover already stored facts adds latency
without repairing the read contract. Replacing every unknown with healthy, running, or
not-applicable hides missing evidence. Per-resource requests are not a substitute for bounded batch
reads.

## Related docs

| Topic | Document |
|-------|----------|
| Implementation evidence and remaining work | [Implementation ledger](../../roadmap-implementation/interfaces/recorded-resource-state.md) |
| Console read and request boundaries | [Console Operations](console-operations.md) |
| Graph-first observed evidence | [Continuous operational instance graph](../architecture/continuous-operational-instance-graph.md) |
