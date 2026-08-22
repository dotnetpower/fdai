---
title: Continuous Operational Instance Graph
---
# Continuous Operational Instance Graph

This document owns the runtime contract that keeps cloud resource instances, relationships, and
observed state current in the FDAI ontology. Collection is continuous and load-aware, while raw
history moves through typed rollups and verified archives so the active data plane remains bounded.

> **Scope boundary:** This design covers provider observation, ontology instance projection,
> freshness, compaction, archive, and graph-first reads. It does not grant approval, mutation, or
> execution authority.
>
> **Provider boundary:** The contracts are cloud-provider-neutral (CSP-neutral). Azure Resource
> Graph, Activity Log, Monitor, and Resource Health are the implemented provider sources.

## Design at a glance

Continuous collection combines push events, resumable provider deltas, and adaptive reconciliation.
It does not use a fixed six-hour scan as the normal freshness mechanism and does not run an
unbounded tight polling loop.

![Design at a glance. The main stages are Provider events and delta APIs, Durable observation ingress, Normalize and adjudicate, Current operational graph, Bitemporal observation history, Typed rollups, Verified archive, Verified semantic query, Evidence current and complete?, Evidence-backed result, Bounded live read.](../../diagrams/generated/fdai-roadmap-architecture-continuous-operational-instance-graph-01.en.svg)

## Non-negotiable invariants

- **Observed truth:** Only authenticated provider observations can enter the `observed` state lane.
  Questions, model output, intended state, dispatch receipts, and executor results cannot create an
  observed fact.
- **Single writer:** Collectors append typed observations. They never mutate ontology instances
  directly. One projection owner adjudicates observations and atomically advances its current
  subgraph.
- **Graph first:** Ordinary questions read the current operational graph before any provider API.
  A live provider read is allowed only when required evidence is missing, stale, incomplete,
  conflicting, or explicitly requested under a bounded read policy.
- **Safe enrichment:** A live read can support the current answer and publishes a typed observation
  through the same ingress. A partial read cannot replace a complete generation or delete an
  unobserved object or relationship.
- **Time and provenance:** Every fact retains effective time, event time when available, recorded
  time, evidence cutoff, source identity, source revision, completeness, conflicts, and freshness
  policy.
- **No false absence:** Missing events, truncated reads, cursor lag, an open realtime overlay, and
  archive unavailability remain explicit unknown or incomplete evidence.
- **Read/write separation:** Provider observation and ontology projection are read-plane work.
  Managed-resource writeback remains in the governed action path and closes only after independent
  re-observation.
- **Bounded retention:** Raw data is removed from hot or warm storage only after a rollup or archive
  manifest verifies complete source coverage and the applicable retention hold permits deletion.

## Continuous collection contract

### Source strategy

The collector uses the cheapest authoritative signal that can preserve the required freshness:

1. Push resource create, update, and delete events into the canonical event stream.
2. Drain resumable provider deltas from a durable cursor while lag or an incomplete overlay exists.
3. Run bounded reconciliation to detect missed events, repair relationships, and prove scope
   completeness.
4. Run exact live reads only for evidence families that the inventory source cannot provide or when
   a verified query needs fresher evidence than the graph currently carries.

Continuous means that collection always has a durable next action. It does not require one
never-ending process. Event consumers can remain active while cursor and reconciliation workers run
as safe-to-retry one-shot tasks that persist progress before yielding or scaling to zero.

### Load-aware scheduling

Each source has a validated policy rather than one global interval. The policy includes:

- target freshness and maximum tolerated staleness;
- minimum and maximum poll intervals;
- request and byte budgets per window;
- global, scope, resource-type, and endpoint concurrency limits;
- cursor page, object, relationship, time, and no-progress bounds;
- priority for changed, stale, critical, and operator-requested targets;
- bounded jitter, exponential backoff, and a circuit-breaker threshold;
- provider `Retry-After`, quota, and remaining-budget observations.

When backlog or event lag grows, the scheduler consumes available budget more frequently. When the
graph is current and churn is low, it increases the interval without exceeding the maximum
staleness objective. HTTP `429` and provider throttling reduce concurrency and honor `Retry-After`.
Persistent unavailability opens the circuit, marks freshness unavailable, and schedules a bounded
probe instead of retrying continuously.

Configuration supplies deployment values. Repository defaults and tests define safe bounds, not a
claim that one interval fits every tenant or provider API.

### Convergence and deletion

Realtime deltas improve freshness but do not prove global completeness. A complete reconciliation
generation remains the authority that closes covered overlays and confirms deletion. Promotion is
atomic, and a partial or conflicting generation cannot replace the previous complete graph.

Resource and relationship updates are ordered per logical resource. Duplicate delivery is a no-op,
and a stale cursor or older event cannot move an instance backward. Tombstones retain their source,
effective time, generation, and archive lineage.

## Retention, rollup, and archive

### Storage tiers

| Tier | Contents | Query behavior |
|------|----------|----------------|
| Hot | Current objects and links, freshness health, active overlays, and recent exact observations | Default operational query path. |
| Warm | Bitemporal raw observations, revisions, tombstones, and reconciliation receipts within the configured detailed-retention window | Used for bounded recent history, replay, and topology comparison. |
| Rollup | Typed hourly, daily, or policy-selected aggregates with source coverage and completeness | Used for long-range trends when exact events are not required. |
| Archive | Immutable compressed partitions plus content-addressed manifests, provenance, retention class, and restore metadata | Read only through an explicit historical retrieval path. |

### Rollup rules

Rollups are semantic-policy driven. A gauge, counter, categorical state, relationship change, and
evidence-health fact do not share one generic aggregation rule. Each eligible property or metric
declares its allowed windows and mergeable statistics.

Every rollup preserves source count, covered interval, missing intervals, observed zero, conflict
count, completeness, source partition digests, and the aggregation policy revision. Percentiles use
a mergeable reviewed sketch or remain unavailable. Averages without count and sum are not accepted,
and an incomplete source interval never becomes a complete aggregate.

### Archive and purge

Archive partitions are immutable and content addressed. A manifest records the covered source
partitions, time range, object and relationship counts, schema and ontology releases, encryption and
compression profile, destination class, creation receipt, and verification result without storing
deployment secrets in the repository.

Hot or warm deletion is eligible only after manifest verification, restore sampling, retention and
legal-hold evaluation, and a durable purge receipt. Purge is safe to retry. Failure leaves source
data intact and reports storage pressure; it never silently narrows history.

The hot graph keeps an archive index and coverage summaries so a query can distinguish archived
history from absent history. Archive restoration is explicit, bounded, principal scoped, and does
not silently delay an ordinary current-state query.

## Graph-first query and live enrichment

The verified query plan carries an evidence requirement and freshness budget. A deterministic
refresh policy reduces graph evidence to one of these outcomes:

| Outcome | Behavior |
|---------|----------|
| `use_graph` | Execute against current complete graph evidence. |
| `refresh_then_query` | Perform one bounded provider read, publish its observation, and query the reconciled result when the deadline allows. |
| `use_live_evidence` | Use a verified live receipt for this answer while asynchronous projection catches up. |
| `query_archive` | Retrieve an explicit bounded historical partition and preserve archive lineage. |
| `hold` | Return unavailable, stale, incomplete, conflicting, or deadline-exceeded evidence without substitution. |

Natural-language and model output can propose meaning only. Core verifies the principal, purpose,
scope, ontology release, ObjectType, LinkType direction, FunctionType, bounds, and refresh outcome
before graph, archive, or provider I/O.

## Source-to-store implementation audit

OI-01 records the exact code owner, runtime or storage binding, focused tests, state, and missing
binding for each stage in
[`config/continuous-operational-instance-graph-audit.json`](../../../config/continuous-operational-instance-graph-audit.json).
The architecture checker rejects a missing stage, missing evidence path, unassigned implemented
work, or an open stage that does not name its exact gap.

| Stage | State | Audited result |
|-------|-------|----------------|
| Provider push ingress | implemented | Event Grid writes and deletes reach the raw Event Hub, then `_consume_resource_changes` normalizes them into canonical inventory events. |
| Resumable delta cursor | implemented | `forward_inventory_delta` advances the durable Activity Log cursor only after the final fence. |
| Complete reconciliation | implemented | `InventorySyncCoordinator.run` stages bounded ARG or ARM observations and accepts only a complete stream. |
| Normalized observation ingress | implemented | `PostgresInventoryDeltaProjector.__call__` is the durable normalized change writer used by the Huginn discovery path. |
| Snapshot promotion | implemented | `PostgresInventorySnapshotStore.promote` atomically advances the active generation under the promotion lock. |
| Realtime overlay | implemented | PostgreSQL overlay rows are ordered per resource, merged with the active snapshot, and cleared only when a complete snapshot covers them. |
| Ontology projection | implemented | `InventoryOntologyProjector.apply` is the single writer for the inventory-owned Resource and Link subgraph. |
| Topology history | implemented | `InventoryTopologyHistoryPublisher.publish` appends complete baselines through the Core-owned bitemporal PostgreSQL store and migration. |
| Graph-first query | in-progress | Secured ObjectSet queries read the current graph, but no policy selects the five documented freshness outcomes. |
| Bounded live read | in-progress | A resource-state shadow read exists, but ordinary semantic queries do not select it through a graph evidence refresh policy. |
| Live evidence write-through | not-started | No owner republishes a successful bounded live read through canonical observation ingress and the realtime overlay. |
| Adaptive scheduling | in-progress | Durable age, change demand, abandonment, and failure backoff are implemented; freshness, lag, quota, `Retry-After`, endpoint concurrency, and circuit recovery are not inputs. |
| Retention and holds | not-started | No operational-graph retention policy, hold registry, deletion gate, or durable purge receipt exists. |
| Typed rollup | not-started | No semantic rollup policy or store preserves coverage, missing intervals, observed zero, conflicts, and mergeable statistics. |
| Archive lifecycle | not-started | No immutable partition, verified manifest, restore sampler, hot archive index, hold check, or safe-to-retry purge path exists. |

## Implementation status

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| Push events and durable delta overlay | implemented | `delivery/azure/activity_log.py`; realtime inventory projector and focused tests | Resource changes can update a bounded overlay. Deployment evidence remains separate. |
| Complete inventory promotion and ontology projection | implemented | `delivery/inventory_sync.py`; `runtime/inventory_ontology.py`; focused inventory and projection tests | Complete generations replace the owned subgraph atomically. The existing routine cadence is not the target continuous policy. |
| Bitemporal topology history | implemented | `core/ontology_platform/topology_history.py`; PostgreSQL topology history adapter and focused tests | Current production retention, rollup, archive, and restore evidence remains open. |
| Adaptive continuous scheduling | in-progress | Durable due-state, cursor, early reconciliation, backoff, and bounded scan foundations | Fixed routine reconciliation remains in configuration and no measured adaptive freshness controller proves the revised contract. |
| Typed rollup and archive lifecycle | not-started | This design contract | No source-coverage-bound rollup, archive manifest, restore verification, or purge receipt is proven. |
| Graph-first conditional live enrichment | in-progress | Semantic runtime, Azure read investigation, freshness metadata, and shadow comparison | The pieces exist, but one deterministic refresh policy and observation write-through path are not complete end to end. |
| Operational and semantic certification | not-started | This document's OI work packages | Structural catalog tests and transport readiness do not prove continuously refreshed instances or question-to-instance resolution. |
| Source-to-store implementation audit | implemented | `config/continuous-operational-instance-graph-audit.json`; `check-continuous-operational-instance-graph-audit.py`; focused audit tests (`3 passed`) | OI-01 fixes the exact owner, binding, focused tests, state, and missing binding for 15 stages without claiming runtime validation. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-08-22 | in-progress | Adopted the continuous operational instance graph contract. It replaces fixed six-hour freshness as the target with event-driven and adaptive bounded collection, and adds typed rollup, verified archive, restore, and purge requirements. | `current change`; paired design document and focused documentation gates. | Complete OI-01 through OI-12 with focused implementation and operational evidence. |
| 2026-08-22 | implemented | Completed OI-01 with a machine-readable 15-stage source-to-store audit and a deterministic checker for owner, binding, test, state, and missing-gap evidence. | `current change`; audit record, checker, and focused audit tests (`3 passed`). | Start OI-02 with validated source-policy declarations; leave adaptive control, rollup, archive, and live write-through to their owning later packages. |

### Remaining work

- [x] `OI-01` records a source-to-store implementation audit and identifies the exact owner, tests,
  and missing binding for every collection, projection, query, retention, and archive stage. The
  focused audit checker passes 3 tests.
- [ ] `OI-02` defines validated source policies, freshness objectives, budgets, priority, and
  throttling inputs without hard-coded tenant values.
- [ ] `OI-03` implements adaptive due calculation and proves healthy, lagging, changing, `429`,
  timeout, circuit-open, and recovery transitions with a pure deterministic test matrix.
- [ ] `OI-04` proves event, delta, complete snapshot, duplicate, reorder, tombstone, and concurrent
  promotion convergence without losing objects or relationships.
- [ ] `OI-05` exposes principal-safe collection health for cursor lag, overlay state, freshness,
  coverage, provider pressure, and the next scheduled action.
- [ ] `OI-06` implements semantic-policy-driven rollups and proves zero, missing, partial, conflict,
  and merge behavior for every supported statistic.
- [ ] `OI-07` implements archive manifests, verification, restore sampling, retention holds, and
  safe-to-retry purge receipts; source deletion remains blocked on any failed gate.
- [ ] `OI-08` implements the pure graph evidence refresh policy and proves every `use_graph`,
  `refresh_then_query`, `use_live_evidence`, `query_archive`, and `hold` transition.
- [ ] `OI-09` routes bounded live evidence back through observation ingress and proves that partial
  enrichment cannot replace a complete generation or widen authority.
- [ ] `OI-10` proves representative questions select the expected instances, paths, functions,
  freshness outcomes, and archive behavior without answer-text matching.
- [ ] `OI-11` runs the 35 logical canonical expectations in English and Korean only after OI-01
  through OI-10 pass, retaining typed no-authority receipts.
- [ ] `OI-12` runs wording regression and deployed Azure certification only after the canonical
  competency matrix passes; it measures freshness, API pressure, lag, storage growth, rollup
  coverage, archive restore, and provider failure behavior.

## Related docs

| To learn about | Read |
|----------------|------|
| Ontology authority and state lanes | [FDAI Operating Ontology](operating-ontology.md) |
| Runtime topology and service boundaries | [Project Structure](project-structure.md) |
| Semantic query planning | [Ontology Query Coverage Implementation Plan](../interfaces/ontology-query-coverage-implementation-plan.md) |
| Observation and detection delivery | [Observability and Detection](../rules-and-detection/observability-and-detection.md) |
