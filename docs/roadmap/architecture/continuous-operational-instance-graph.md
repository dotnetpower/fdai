---
title: Continuous Operational Instance Graph
---
# Continuous Operational Instance Graph

This document owns the runtime contract that keeps cloud resource instances, relationships, and observed state current in the FDAI ontology.
Collection is continuous and load-aware, while raw history moves through typed rollups and verified archives so the active data plane remains bounded.

> **Scope boundary:** This design covers provider observation, ontology instance projection, freshness, compaction, archive, and graph-first reads.
> It does not grant approval, mutation, or execution authority.
>
> **Provider boundary:** The contracts are cloud-provider-neutral (CSP-neutral). Azure Resource Graph, Activity Log, Monitor, and Resource Health are the implemented provider sources.

## Design at a glance

Continuous collection combines push events, resumable provider deltas, and adaptive reconciliation. It does not use a fixed six-hour scan as the normal freshness mechanism and does not run an
unbounded tight polling loop.

![Design at a glance. The main stages are Provider events and delta APIs, Durable observation ingress, Normalize and adjudicate, Current operational graph, Bitemporal observation history, Typed rollups, Verified archive, Verified semantic query, Evidence current and complete?, Evidence-backed result, Bounded live read.](../../diagrams/generated/fdai-roadmap-architecture-continuous-operational-instance-graph-01.en.svg)

## Non-negotiable invariants

- **Observed truth:** Only authenticated provider observations can enter the `observed` state lane.
  Questions, model output, intended state, dispatch receipts, and executor results cannot create an
  observed fact.
- **Deployment evidence:** Protected platform plan metadata is built by a focused repository
  module. Workflow YAML passes sealed inputs to it; neither the plan nor its receipt can establish
  an observed graph fact. Every status-overriding service-deployment run or action step executes
  only after the protected-source verifier succeeds; cleanup, failure reporting, or artifact
  retention never converts dispatch into observed evidence. The service workflow contract test
  pins that verifier-success predicate on final rollback failure reporting. Every Core image transition
  binds `FDAI_SOURCE_REVISION` to the exact protected commit. The fixed Heimdall recovery observer can
  enter only on first adoption through the explicit Core evidence transition; rebinding or unrelated environment drift remains ineligible.
- **Single writer:** Collectors append typed observations. They never mutate ontology instances
  directly. One projection owner adjudicates observations and atomically advances its current
  subgraph.
- **Graph first:** Ordinary questions read the current operational graph before any provider API.
  A live provider read is allowed only when required evidence is missing, stale, incomplete,
  conflicting, or explicitly requested under a bounded read policy.
- **Safe enrichment:** A live read can support the current answer and publishes a typed observation
  through the same ingress. A partial read cannot replace a complete generation or delete an
  unobserved object or relationship. Runtime environment bindings can participate in an in-memory,
  exact-identity relationship join, but their names and values are redacted before inventory
  snapshot or ontology persistence.
- **Time and provenance:** Every fact retains effective time, event time when available, recorded
  time, evidence cutoff, source identity, source revision, completeness, conflicts, and freshness
  policy.
- **No false absence:** Missing events, truncated reads, cursor lag, an open realtime overlay, and
  archive unavailability remain explicit unknown or incomplete evidence.
  A bounded query can return verified positive observations from the available scope, but it keeps
  the result incomplete and never treats the missing scope as proof that no other observation exists.
- **Read/write separation:** Provider observation and ontology projection are read-plane work.
  Managed-resource writeback remains in the governed action path and closes only after independent
  re-observation. The standalone deploy host's exact-registry `AcrPush` assignment remains a
  write-plane delivery permission. Image import and digest readback create no operational graph
  fact or observation authority.
- **Bounded retention:** Raw data is removed from hot or warm storage only after a rollup or archive
  manifest verifies complete source coverage and the applicable retention hold permits deletion.

## Continuous collection contract

### Source strategy

The collector uses the cheapest authoritative signal that can preserve the required freshness:

1. Push resource create, update, and delete events into the canonical event stream.
2. Drain resumable provider deltas from a durable cursor while lag or an incomplete overlay exists.
3. Run bounded reconciliation to detect missed events, repair relationships, and prove scope completeness.
4. Run exact live reads only when inventory lacks an evidence family or a verified query needs fresher evidence.

A collected property becomes a relationship only through a reviewed provider mapping. If that
mapping omits an observed connection target, an absent graph edge never proves an absent path.
Every reachable managed-service connection therefore needs its target type in the reviewed catalog.
Disabled resource-change and recovery accelerators do not require collection-policy entries and
contribute neither cursor prefixes nor stale-cursor deadlines to reconciliation.

Kubernetes fleet collection retains one source-state record per exact cluster binding. The record
uses a customer-safe scope digest, so one unavailable cluster lowers fleet completeness without
erasing another cluster's verified positive evidence or exposing its ARM identity.
The deployed Inventory Job accepts either the legacy binding or one bounded fleet JSON record,
never both, and the same read identity receives only AKS RBAC Reader on each exact cluster scope.
Lifecycle collection acquires an independent lease and resourceVersion cursor for each binding.
One cluster failure keeps fleet evidence incomplete but does not stop or erase another cluster's
accepted Event observations.

Runtime-call evidence requires two typed endpoint witnesses with the same hashed request identity
and exact caller and target Container App Resource IDs. Operator emits the caller witness only after
authenticated broker acceptance and records its observation time only after that acceptance. Core
emits the target witness as soon as that broker delivery
reaches the target boundary, before turn processing can reject it. Neither witness carries request
content or authority. Consumer cancellation always stops the associated progress publisher before
the delivery task exits, so no stale progress can survive the target boundary. An untrusted
telemetry envelope exposes no direct conversion to projection
input. Only the authenticated producer can perform that conversion after it verifies the exact
envelope digest and independent source context under a finite positive deadline. The Azure Monitor source accepts
only the matching structured Container Apps log schema. A non-empty platform-stamped Resource ID
must match the claimed endpoint exactly. Environment-integrated Container Apps rows can leave that
field empty; those rows remain eligible only when the platform-stamped app, revision, replica,
container name, and container ID all match one container returned by the exact claimed ARM replica
endpoint. Only those independently bound endpoint witnesses convert through the existing canonical
Resource ID mapping. The standalone channel edge never receives the caller
binding and uses a distinct durable outbox namespace, so it cannot claim an Operator API request
or join its own requests on the shared topic into a false Operator-to-Core edge. Orphaned,
malformed, or mismatched witnesses make the source incomplete. Repeated joined calls reduce to the
newest observation per exact endpoint pair before ARM replica verification and pair completeness
are evaluated. A newer
complete pair supersedes an older unpaired observation, while a newer unpaired observation remains
pending for a 60-second trailing guard and then makes the source incomplete. The source reads one
guard interval beyond the freshness window so cutoff boundaries do not split a retained pair.
Incomplete-source coverage accepts only the fixed row-count keys and
cannot carry provider identifiers or arbitrary source text. Exact replica verification uses at most four concurrent reads under one
30-second deadline, and freshness is evaluated only after those reads finish. The
inventory writer then rechecks both endpoint IDs against the complete active generation, principal
scope, freshness budget, and exact ontology release before it can project `runtime_calls`. The
verification receipt binds both endpoint Resource IDs and their active-generation Resource types.
Core inventory snapshot and real-time link constraints admit the reviewed `runtime_calls` type.
Rollback deletes only those rebuildable links before restoring the previous constraint.
The KQL and parsed endpoint witness value are isolated in a focused contract module; collection,
ARM verification, reduction, and authentication remain in the source adapter.
The independent-service runtime-call transition guard admits only the fixed API and channel-edge
namespace value for the matching Container App; swapped or arbitrary namespaces remain blocked.
Local
development, a disabled binding, and an empty witness query report this source unavailable instead
of fabricating an edge.
The platform's `enable_runtime_call_evidence` input controls this Inventory Job source independently
of the legacy Operator API module, so state migration cannot silently remove collection. Schema-valid
`plan-runtime-*` and `apply-runtime-*` requests target dedicated flag, workspace, and exact-image
transition resources and reject mixed targets. The transitions use bounded updaters with verified rollback to
enable the existing Inventory Job and, when an attested revision is selected, replace its stale
image without planning unrelated module dependencies. The binding updater also resolves the exact
Log Analytics customer ID and applies it with the runtime flag; rollback restores both prior values.
The post-plan scope guard rejects every other address, and post-apply verification independently
reads the flag, workspace digest, and image digest before the source is treated as enabled.
When the attested image digest changes, only the image updater's state-only replacement is allowed;
the updater itself performs the verified Azure update or rollback.
A degraded pending projection retains its failed activity and remains incomplete, but recovery no
longer blocks a fresh authoritative collection that can supersede it. An incomplete projection from
the current collection still fails the run. If that promoted full snapshot skipped a degraded base,
recovery rebinds it to the actual current manifest generation before projection; a missing manifest
generation still fails closed.
A fresh full snapshot whose declared state base never reached ontology can derive transitions from
the retained complete topology history. This fallback applies only to the exact incomplete-base
error with retained history; other generation mismatches remain blocked.
The plan's full JSON projection and value-free summary remain in a current-UID mode-0700 temporary
directory until bounded plan metadata is sealed, then both private files are removed.
PostgreSQL database-role observations remain a separate principal-safe projection with no Resource
or Link shape. The observation, sanitized evidence, and projection contracts each reject execution
or mutation authority at runtime rather than relying on type annotations alone. The projected
principal handle derives from opaque authenticated evidence references and scoped source context;
it never hashes the low-entropy role name. Current Operator and Console instance-detail responses
must carry explicit runtime-call and PostgreSQL-role source states; omission is invalid rather than
available or measured zero. The Operator persistence reader accepts runtime-call link metadata only
when its embedded inventory generation equals the exact selected snapshot. Unavailable source
reasons must be canonical machine tokens and cannot carry principal text, endpoints, or provider
details.
The Operator lifecycle can also publish durable Incident intervention requests through the focused outbox lifecycle facade and its retry-safe worker.
The adapter explicitly allowlists that logical topic and multiplexes it over the configured physical transport.
It creates no runtime-call witness, graph edge, provider observation, or execution authority.

Protected service deployment first consumes the platform-owned runtime-call binding. After an
Operator state migration disables the legacy platform module, that output can be absent while both
Container Apps remain deployed. In that case, the VNet runner reads the exact Operator app name
from independent service state into a mode-0600 transient file and reads the Core app name and
resource group from platform state. The transient name never enters the sanitized peer-state
manifest and is removed with the peer-state workspace. The runner
uses those names with the pinned subscription to read both exact Resource IDs from Azure. The same
closed validation then requires two distinct Container App IDs before either service receives the
binding. Both service roots require canonical unpadded ARM IDs with an exact subscription UUID,
resource-group segment, provider path, and terminal app segment. Partial, trailing-slash,
whitespace-padded, or same-endpoint pairs fail validation. A failed or ambiguous state or provider
read blocks the plan and never falls back to a constructed identity.

Continuous means collection always has a durable next action, not one never-ending process. Event consumers can remain active while safe-to-retry cursor and reconciliation tasks persist progress.
An explicitly requested one-shot Inventory execution can set
`FDAI_INVENTORY_OPERATOR_REQUESTED=1` to activate the adaptive scheduler's existing operator
priority. The request collects immediately only when the source is healthy and no collection is
active; provider pressure, backoff, throttling, circuit state, and every evidence gate still apply.
The persisted Job template leaves this input unset.

The current-graph checkpoint is bound to the active snapshot generation and exact scope set. A complete
provider snapshot covers same-scope observations from its generation and start time, so the contiguous checkpoint scans only those scopes.
Inactive-scope observations remain durable history and retention work. Reactivation requires a new complete reconciliation, while active-scope
post-snapshot observations keep the graph incomplete until projection catches up.
Checkpoint calculation is bounded by the journal high watermark observed by the same snapshot append.
Concurrent later journal writes can lower completeness, but cannot advance either global or active-scope
projection checkpoints beyond that append boundary.
PostgreSQL persistence keeps store coordination in `postgres_ontology.py` and isolates inventory
state-base completeness and object-ownership validation in `postgres_ontology_records.py`; this
shared record-validation boundary does not create another graph writer or authority surface.
Change-feed value parsing and replay-watermark decoding remain pure delivery helpers, so module
splits do not change cursor progress, completeness, or writer authority.

### Private-safe change acceleration

The private deployment profile polls Azure Resource Graph `resourcechanges` with a durable cursor
and tracks every enabled accelerator heartbeat even when positions are unchanged. Each bounded page is
ordered oldest first, boundary duplicates are idempotent, and the cursor advances only after every
accepted change enters observation ingress. Create and update rows trigger exact Resource Graph hydration for the
changed Resource ids. Delete rows become unconfirmed tombstones and wait for complete reconciliation
before proving absence. A tokenless truncated page advances through the same stable keyset cursor,
and the next poll waits until every published event id appears in the observation journal.
Snapshot-covered and ordering-rejected changes therefore release the producer fence without being
misrepresented as current overlay changes.
The configured page-size and page-count product cannot exceed the 1,000-id durable fence bound.
An empty provider page that still reports truncation also remains incomplete. The transport accepts
only the documented boolean and string forms of `resultTruncated` and rejects other values.
If the final bounded page still carries a continuation token, the feed returns the oldest collected
rows as incomplete and advances the stable keyset cursor after their ingestion fence clears.
The first poll persists its calculated lookback boundary as an initial cursor, so incomplete empty
or hydration retries cannot drift forward and skip changes. This anchor is committed before the
first provider query or publication, so a failed first attempt reuses the same boundary.
Snapshot-covered events still append a history-only observation so recent-change evidence remains
queryable while the newer snapshot remains authoritative for current state. The history-only path
does not bind resource incarnations, create pending tombstones, or mutate the current overlay.
A Resource absent from hydration retains the prior cursor and leaves source completeness false so a
later poll can observe either the Resource or its delete record. A returned Resource type outside
the reviewed mapping catalog is skipped without blocking later changes; malformed hydration still
fails the batch. Hydration that exceeds the bounded property payload also fails before publication
or cursor advancement rather than asserting a truncated full replacement.
After three unresolved hydration retries, the feed advances past the bounded page and records the
latest missing-change time as a durable coverage gap. Queries whose window intersects that gap
remain incomplete, while later windows can recover without permanently blocking the feed.

The read-only recent-change FunctionType queries the server-configured inventory scopes rather than
a model-supplied scope. It uses the same `FDAI_INVENTORY_SCOPES` parser as collection, with
`AZURE_SUBSCRIPTION_ID` only as the legacy single-scope fallback. It selects only ARG create,
update, and delete observations or
operation-bearing observations from the reviewed Event Grid Resource-change adapter, excludes
periodic snapshots and live refreshes, and
reports complete only after the fresh cursor and every exact event-id fence verify. The reader
fetches one row beyond the requested limit and reports `result_limit` rather than claiming that a
bounded subset is complete. Rows, cursor state, and journal fence evidence are read from one
read-only repeatable-read snapshot and are all bounded by the answer's `known_at` cutoff.

The change accelerator batches bursts for at most two seconds, applies per-resource ordering, and
publishes no relationship that the exact hydration and reviewed mapping catalog did not support.
When `FDAI_INVENTORY_RESOURCE_TYPES` restricts collection, the accelerator first resolves ARM type
and `kind` through the complete reviewed vocabulary, then applies the configured neutral-type
allowlist. Excluded types cannot enter and block the ingestion fence, and shared ARM types cannot be
misclassified by a prematurely filtered registry.
Azure Activity Log remains an audit and recovery source, while complete ARG and ARM reconciliation
continues to repair missed changes and collect child topology. Resource Graph change availability is
eventually consistent, so this path is near-real-time rather than an immediate provider guarantee.
AKS AgentPool size is owned by the bounded ARM child collection because Resource Graph does not
expose that child as an ordinary Resource. VM Scale Set size comes from its provider `sku.capacity`.
Both values reach the Console only after the inventory writer commits a new observation or complete
generation; the SSE watermark accelerates re-reading but does not create or estimate capacity.

After the observation journal and real-time overlay commit, its monotonic watermark becomes a
sanitized inventory invalidation. The Operator SSE route exposes only watermark, count, and
observation time under authenticated read access. It never exposes provider payloads or creates
graph facts. A visible Console receiving the invalidation re-reads its bounded selected-instance
projection. SSE reconnects from `Last-Event-ID`; polling remains the bounded fallback.

Observed model deployments use that same generation and invalidation path. The Operator projection
exposes only model name, model version, deployment SKU, and normalized TPM in an additive
`model_deployment` object. Console cards, tooltips, details, and screen context consume this
allowlist without receiving raw provider properties. A changed TPM becomes visible only after the
next accepted observation commits; invalidation accelerates the reread but does not provide an
immediate or strongly consistent provider guarantee.

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

When backlog, event lag, or overdue poll heartbeat grows, the scheduler consumes budget sooner. Each
accelerator reports degradation with redacted reason codes instead of hiding it in a combined count. HTTP `429`
and provider throttling reduce concurrency and honor `Retry-After`; persistent unavailability opens
the circuit and schedules a bounded probe instead of retrying continuously.
When no newer failed attempt exists, the scheduler uses the active snapshot completion age as the
last-attempt age and treats overlay rows, tombstones, or an open projection watermark as pending.
Change demand or maximum staleness therefore cannot be deferred because a failure time is absent.
The local long-running loop records typed source, projection, or pending-replay failure and retries after its
configured interval. A one-shot job also fails when source collection or the promoted ontology projection
fails, while retaining the authoritative inventory generation for bounded recovery on the next tick.

Validated configuration supplies deployment values. Repository defaults and tests define safe bounds, not a
claim that one interval fits every tenant or provider API.
The coordinator imports and explicitly re-exports immutable promoted-observation and relationship-coverage
records from a focused delivery module. Existing consumers keep the same delivery boundary, and the
separation changes neither single-writer ownership nor promotion authority.

### Convergence and deletion

Realtime deltas improve freshness but do not prove global completeness. A complete reconciliation
generation remains the authority that closes covered overlays and confirms deletion. Promotion is
atomic, and a partial or conflicting generation cannot replace the previous complete graph.

Resource and relationship updates are ordered per logical resource. Duplicate delivery is a no-op,
and a stale cursor or older event cannot move an instance backward. Tombstones retain their source,
effective time, generation, and archive lineage.

A complete provider generation may contain reviewed candidates that cannot become edges because an
endpoint is outside the active generation, its provider type is not modeled, or its exact reference
was not observed. These typed non-edges do not freeze newer Resource objects and independently
verified links. The ontology projection advances the same generation with
`relationship_complete=false` and preserves every classified reason. Relationship coverage bounds
relationship claims: it prevents a query from using the graph as complete relationship evidence,
while a snapshot whose object set admits no intra-set edge states nothing about relationships and
therefore keeps its own object coverage. An unclassified drop, invalid verification metadata,
partial source generation, conflict, or cardinality violation remains blocking and preserves the
previous graph.

An exact reviewed provider parent shadows generic Resource Group containment for the same child.
Snapshot promotion independently rejects more than one `contains` parent for any child before the
active pointer changes, and the ontology store revalidates LinkType cardinality before commit. The
bounded ARM compute source lists VM Scale Set VM children and each child's network interfaces under
the same page, child-collection, host, and generation fences as other ARM-only nested resources.
Child collection failure aborts the generation; template network configuration never fabricates an
instance identity. The
ontology projector holds a process-local lock and a PostgreSQL session advisory lock across graph
replacement and its manifest/status commit marker. Readers require the active snapshot, status, and
manifest generations and content digests to match. A crash or stale replica therefore yields
incomplete evidence until a safe-to-retry migration or commit closes the state; it never exposes a
mixed generation as complete. Legacy 1.2.0 manifests are rebuilt by the next exact projection
within the same release and written as 1.3.0; they cannot carry unverified ownership across a
release transition. When the ontology release changes, the projector first verifies the retained
manifest against its recorded release digest, then reprojects the complete active inventory under
the new release. The retained identities remain ownership evidence for atomic replacement, while
the old manifest digest cannot certify same-generation content under the new release. A separate
release-independent content digest keeps same-generation tamper detection active during that
transition.

The PostgreSQL projector commits graph replacement and the manifest and status markers in one
transaction after locking and rechecking the active inventory generation. Endpoint foreign keys
prevent a concurrent resource deletion from leaving an orphan relationship. A pending
relationship-reconciliation marker also lowers graph completeness until a complete full-scope
generation at or after that observation clears the marker. Resource-type subset scans cannot
promote the global snapshot or replace the global ontology projection.

## Retention, rollup, and archive

### Storage tiers

| Tier | Contents | Query behavior |
|------|----------|----------------|
| Hot | Current objects and links, freshness health, active overlays, and recent exact observations | Default operational query path. |
| Warm | Bitemporal raw observations, revisions, tombstones, and reconciliation receipts within the configured detailed-retention window | Used for bounded recent history, replay, and topology comparison. |
| Rollup | Typed hourly, daily, or policy-selected aggregates with source coverage and completeness | Used for long-range trends when exact events are not required. |
| Archive | Immutable compressed partitions plus content-addressed manifests, provenance, retention class, and restore metadata | Read only through an explicit historical retrieval path. |

### Bounded observation history

The runtime dual-writes an append-only normalized observation journal while the existing overlay
remains the current read path. A journal record carries one bounded fact or change hint and pins its
source schema and source revision. Partition lifecycle, archived retention, and incarnation
boundaries now use Core-owned typed lifecycle records. The production archive components remain
uncomposed until the dedicated scheduled Job binds them in a deployed revision.

Each record distinguishes these meanings:

- **Change hint:** A provider reports that a resource changed, but does not provide complete
  properties. The record uses an explicit property mask and cannot replace unobserved values.
- **Full observation:** An authoritative read returns the complete reviewed property set for one
  resource or relationship at its source revision.
- **Partial observation:** A bounded read returns only named properties. Projection merges only the
  declared mask and keeps the remaining values qualified by their earlier evidence.
- **Tombstone candidate:** A delete signal makes the exact target unavailable for action but does
  not prove scope-wide absence until an exact read or complete reconciliation confirms it.
- **Confirmed tombstone:** Re-observation or complete reconciliation confirms deletion and records
  the resource incarnation, effective time, source revision, and evidence reference.

The journal keeps provider event time, effective time, observation time, ingestion time, recorded
time, and evidence cutoff distinct. It also keeps source identity, source event id, cursor or
revision, scope, completeness, conflicts, property mask, content digest, and retention class.
Operation status such as a successful write remains change metadata and never becomes resource
operational state.

A resource id can be reused after deletion. Projection therefore assigns a resource incarnation
from an immutable provider identity, generation, or independently verified lifecycle boundary.
Object and relationship observations refer to the incarnation. Name matching, event order alone,
or an inferred recreation cannot join two lifecycles.

### Retention policy and partition lifecycle

A deployment-owned retention policy registry assigns each fact family its purpose, hot and warm
retention, archive class, hold behavior, deletion method, and review date. Repository defaults
define safe bounds only. They do not impose one tenant retention period.

| Fact family | Hot or warm treatment | Long-term treatment |
|-------------|-----------------------|---------------------|
| Change hints and superseded partial observations | Short exact replay window | Purge after a verified checkpoint and archive policy allow it. |
| Full object and relationship observations | Detailed replay window | Checkpoint, archive, or retain according to the registered purpose. |
| Confirmed tombstones and incarnation boundaries | Retain beyond ordinary deltas | Preserve enough lineage to prevent identity reuse and false absence. |
| State transitions and coverage | Retain by semantic and incident requirements | Typed rollup or archive without claiming unseen intermediate transitions. |
| Audit, approval, execution, and rollback evidence | Separate governed schedule | Never inherit inventory retention implicitly. |
| Manifests, coverage indexes, hold events, and purge receipts | Minimal durable metadata | Outlive the source partitions they describe. |

PostgreSQL journal and history tables use time-and-scope range partitions. A partition advances
through `open`, `sealed`, `checkpointed`, `archived`, `verified`, `purge_eligible`, and `purged`.
`held` and `correction_pending` block forward progress. Row deletion is not the normal lifecycle;
the purger detaches and drops an exact partition only after every gate passes.

A checkpoint is purge authority only when it binds:

- the first and last included journal watermark;
- scope, resource type, object, relationship, and property coverage;
- source, schema, ontology release, and projection digests;
- missing, quarantined, conflicted, and tombstoned record counts;
- the resulting current-graph digest and projection watermark.

The journal high watermark and projection high watermark appear on every current graph receipt.
When the journal is ahead, an unresolved partial observation exists, or a tombstone awaits
confirmation, the graph reports incomplete evidence. Neither a snapshot nor an archive manifest
can hide that gap.

Late observations are appended to a correction partition. They never rewrite an immutable
partition. The correction invalidates affected checkpoints, rollups, and archive coverage until a
new content-addressed correction manifest and replay receipt close the interval. Older events can
improve history but cannot move current state backward.

An active incident, investigation, approval, execution, rollback, legal hold, or replay lease pins
every referenced partition. Evidence references resolve back to partitions so retention cannot
remove an active case dependency. A release event is append-only and separately authorized.

### Capacity and failure behavior

Archive failure stops purge, but it cannot be allowed to fill PostgreSQL silently. Each deployment
sets warning, critical, and hard storage budgets plus maximum purge backlog and projection lag.
Crossing a threshold progressively:

1. reports storage pressure and projected exhaustion time;
2. increases archive and checkpoint priority;
3. reduces nonessential enrichment and reconciliation frequency within freshness limits;
4. applies source-specific admission budgets while preserving critical observations;
5. holds completeness-dependent queries and mutations when evidence can no longer be retained.

The system never deletes unverified data, samples required audit evidence, or reports a complete
graph to reduce pressure. Recovery requires a successful archive verification, restore sample,
partition purge, and fresh projection receipt.

### Operational closure gates

Bounded history is operationally complete only when one pinned deployment revision proves all of
these outcomes:

| Gate | Required evidence |
|------|-------------------|
| Deterministic replay | Duplicate, reordered, late, partial, delete, recreate, and restart cases produce the same current digest. |
| Bounded growth | Steady-state storage, WAL, index growth, and purge backlog remain within configured budgets at the measured change rate. |
| Safe compaction | No partition is purged before checkpoint coverage, archive verification, restore sampling, reference pinning, and hold evaluation pass. |
| Historical continuity | Warm history replays directly; older history restores through a principal-scoped archive path with explicit gaps. |
| Failure isolation | Archive, database, provider, and scheduler failures degrade freshness or completeness without losing accepted observations. |
| Schema evolution | N and N-1 readers replay retained observations and preserve original and transformed digests. |
| Disaster recovery | Database restore and archive-index rebuild recover the same coverage and projection watermarks. |
| Security and privacy | Redaction, encryption, key rotation, access review, residency, deletion, and legal-hold evidence match the deployment policy. |

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
| `hold` | Return no operational conclusion when identity, authority, conflicts, or missing evidence leave no verified subset that can be presented safely. |

Natural-language and model output can propose meaning only. Core verifies the principal, purpose,
scope, ontology release, ObjectType, LinkType direction, FunctionType, bounds, and refresh outcome
before graph, archive, or provider I/O.

Resource ObjectSet receipts carry source generation and source completeness independently from
query truncation. This applies even when the result has zero Resources, so incomplete coverage
cannot become a false proof of absence. Operator relationship projections also distinguish current,
stale, and future-cutoff evidence, and distinguish provider configuration observation from an
independently verified observation receipt.

A read-only conversation presents verified rows before explaining an incomplete source. An empty
partial result reports no match in the verified scope, then adds the exact limitation and recovery
step. It never claims complete inventory or global absence, and holds when no subset is safe.

## Source-to-store implementation audit

OI-01 records the exact code owner, runtime or storage binding, focused tests, state, and missing
binding for each stage in
[`config/continuous-operational-instance-graph-audit.json`](../../../config/continuous-operational-instance-graph-audit.json).
The architecture checker rejects a missing stage, missing evidence path, unassigned implemented
work, or an open stage that does not name its exact gap. It validates normative ownership in this
design and implementation status and remaining work in the linked delivery ledger.

| Stage | State | Audited result |
|-------|-------|----------------|
| Provider push ingress | implemented | Event Grid writes and deletes reach the raw Event Hub, then `_consume_resource_changes` normalizes them into canonical inventory events. |
| Resumable delta cursor | implemented | `forward_inventory_delta` advances the durable Activity Log cursor only after the final fence. |
| Complete reconciliation | implemented | `InventorySyncCoordinator.run` stages bounded ARG or ARM observations and accepts only a complete stream. |
| Normalized observation ingress | implemented | `PostgresInventoryDeltaProjector.__call__` validates typed observation semantics and dual-writes the Core-owned append-only observation journal before updating the existing overlay. |
| Snapshot promotion | implemented | `PostgresInventorySnapshotStore.promote` atomically advances the active generation under the promotion lock. |
| Realtime overlay | implemented | PostgreSQL overlay rows replay normalized observations by effective time and content identity, merge only the declared property mask, preserve unobserved snapshot properties, and keep tombstone candidates pending until complete reconciliation. |
| Ontology projection | implemented | `InventoryOntologyProjector.apply` is the single writer for the inventory-owned Resource and Link subgraph. Reviewed nested operational fields are lifted with their observation metadata, while journal and projection watermarks plus pending tombstones independently lower source completeness. |
| Topology history | implemented | `InventoryTopologyHistoryPublisher.publish` appends complete baselines through the Core-owned bitemporal PostgreSQL store and migration. |
| Graph-first query | implemented | Ordinary exact-target current-state queries read the secured graph first, present verified partial read-only results with explicit guidance, and hold when no safe subset exists. |
| Bounded live read | implemented | One exact secured Resource may trigger at most one server-scoped provider read under fixed limits. Wider, malformed, or unresolved queries decline or hold. |
| Live evidence write-through | implemented | Verified live evidence enters the canonical typed partial-overlay ingress with a property mask and content-bound idempotency, and cannot delete unobserved properties or relationships. |
| Adaptive scheduling | implemented | Validated source policies and a pure reducer consume freshness, lag, demand, provider pressure, `Retry-After`, remaining budget, concurrency, circuit-open state, and recovery probes. PostgreSQL supplies durable due state, and the principal-safe health projection exposes the next bounded action. |
| Retention and holds | implemented | The archive purge coordinator blocks deletion until exact verification, restore sampling, and retention or legal-hold evaluation pass. Append-only PostgreSQL receipts preserve blocked, pending, failed, successful, and retry outcomes. |
| Typed rollup | implemented | Fact-specific policies separately aggregate gauges, counters, categorical state, relationship changes, and evidence health while preserving source and generation lineage, bitemporal ranges, missing intervals, observed zero, conflicts, completeness, and mergeable count and sum. Percentiles remain unavailable. |
| Archive lifecycle | implemented | Content-addressed manifests, the private Azure Blob writer, principal-scoped verified reader, database-gated source purger, append-only verification, restore, coverage, hold, and purge receipts, and a dedicated fixed-shadow Container Apps Job are implemented. Protected certification binds separate GitHub API and registry credentials to exact-source attestation verification. OCI verification renders the workflow credential in process into a mode-0600 file inside a mode-0700 transient Docker config and removes the credential directory at exit without a Docker CLI dependency. Job resolution, exact OCI provenance verification, and ACR binding are separate protected steps; only the verified repository, revision, and digest cross the verification boundary. Certification normalizes the Terraform ACR output or verified deployed Job image to an Azure login host and can explicitly import the same digest without rebuilding. OI-12 binding prefers the inventory Job, history Job, archive URL, and resource-group root outputs. When the deployed state predates them, one bounded ARM enumeration reads only `Microsoft.App/jobs`, admits at most 64 resources, and requires exactly one container matching each reviewed inventory and history runtime contract. One fail-closed equality predicate must prove both exact runtimes report the same provider-observed group before a missing resource group is adopted. Inventory refresh validates the reviewed live Job and places only the stable start API's `containers` and `initContainers` fields in a mode-0600 request while changing the canonical container image. Container-level command, arguments, environment, resources, secret references, and volume mounts are preserved; Job-owned volumes remain inherited because the start schema does not admit them. The CLI image shortcut is excluded because it replaces command and environment. Pending snapshot recovery suppresses a relationship that lacks typed observation metadata, retains an `unverified_metadata` drop, and continues with the remaining verified snapshot instead of blocking every later refresh. Retained state-transition children are restored in the incoming digest-bearing order before equality verification, while missing, extra, duplicate, or individually invalid children remain rejected. Protected measurement waits up to 120 seconds for the active inventory and ontology projection generations to converge before each snapshot, retries only the typed generation-pending condition, and otherwise fails closed. Provider failure/recovery measurement selects failures only from the current active generation's source and observation kind, then requires a later successful snapshot with the exact failed source, observation kind, scopes, and resource types; retired sources cannot supply or suppress the current instance measurement. Any non-empty root output must match the selected ARM runtime; Job names never supply identity, and provider output is removed after the step. A protected plan preserves the prior archive data owner and adds the repository-bound deploy UAMI at a separate address; any retirement remains a separate destructive operation. |

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
| Delivery status and remaining work | [Implementation ledger](../../roadmap-implementation/architecture/continuous-operational-instance-graph.md) |
| Ontology authority and state lanes | [FDAI Operating Ontology](operating-ontology.md) |
| Runtime topology and service boundaries | [Project Structure](project-structure.md) |
| Semantic query planning | [Ontology Query Coverage Implementation Plan](../interfaces/ontology-query-coverage-implementation-plan.md) |
| Continuous semantic validation | [Continuous Semantic Assurance](../interfaces/continuous-semantic-assurance.md) |
| Observation and detection delivery | [Observability and Detection](../rules-and-detection/observability-and-detection.md) |
