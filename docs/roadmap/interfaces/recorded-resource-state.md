---
title: Recorded Resource State
---
# Recorded Resource State

This document owns the shared read model for Resource state shown by Dashboard v2 and
Ontology Instances. It preserves recorded values and their evidence instead of creating another
browser-side operational verdict.

> **Authority boundary:** Reading a record does not prove current health or authorize a change.
> No provider query, model invocation, state write, or new persistence owner is introduced.

## Design at a glance

The existing instance reader supplies Resource properties from one immutable active inventory
generation. The Operator Service projects these properties into three independent recorded-state
axes. Both Console screens consume the same versioned shape.

| Axis | Recorded fields | Not inferred |
|------|-----------------|--------------|
| Operational | Explicit service, power, phase, readiness, or running state, including retained nested `runningStatus` and `powerState.code`. | Provisioning success does not become running. Enabled, Online, and Active keep their recorded meaning. |
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

## Batch query and consistency

`GET /ontology/instances/states` is a read-only route in the existing authenticated operations family.
It accepts bounded `limit`, optional `search`, and a continuation `cursor`.

| Property | Contract |
|----------|----------|
| Page size | At most 500 Resources in deterministic resource-id order. No per-resource API fan-out. |
| Exclusions | Authorization role assignments, subscription containers, and resource-group containers are not operational roster items. |
| Identity | Every page preserves `source_generation`, `source_cutoff`, and `ontology_release_digest`. |
| Count | `total_count` describes the same-generation query, not an inferred tenant-wide total. |
| Continuation | The cursor binds generation, query and authenticated principal context. It is a selector, never authority. Invalid or changed context is rejected. |
| Completion | `next_cursor` is explicit; `complete` is true only on the last page. An empty page cannot carry a continuing cursor. |
| Change during traversal | A replaced active generation requires a new read. Pages from different generations cannot be merged. |

Dashboard loads bounded pages, rejects duplicate records and changing totals/cutoffs/releases, and
caps accumulation at 20,000 records under a total deadline. Reaching that bound is explicit partial
coverage. A transport or schema failure is not converted into an empty inventory or a graph fallback.
Display filters and local pages operate on this received set; the server query remains the authority.

## Presentation and compatibility

- Dashboard v2 uses the shared state query, not the legacy `inventory/graph` status string.
- Ontology directory and exploration records expose the same additive `states` field.
- The shared Console fact view shows source values, timing, freshness, completeness, and reasons.
- State colors organize recorded values; they do not assert a current operational success.
- The original Dashboard and older instance clients retain their existing routes and fields.
- Resource inspection and selection do not grant approval or execution authority.

## Rejected alternatives

Reading raw provider properties in each browser view duplicates normalization and loses source
semantics. Re-querying Azure or invoking a model to rediscover already stored facts adds latency
without repairing the read contract. Replacing every unknown with healthy or not-applicable hides
missing evidence. Per-resource requests are not a substitute for bounded batch reads.

## Related docs

| Topic | Document |
|-------|----------|
| Implementation evidence and remaining work | [Implementation ledger](../../roadmap-implementation/interfaces/recorded-resource-state.md) |
| Console read and request boundaries | [Console Operations](console-operations.md) |
| Graph-first observed evidence | [Continuous operational instance graph](../architecture/continuous-operational-instance-graph.md) |
