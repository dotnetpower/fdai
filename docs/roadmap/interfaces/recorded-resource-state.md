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

The instance directory and detail merge ordered realtime changes over one active generation.
Recorded-state pages remain immutable and generation-fenced. The Operator Service projects their
Resource properties into three independent baseline axes that both Console screens consume.
Resource types with a reviewed data-plane source can add a fourth `serving` axis without replacing
operational, provisioning, or availability evidence.
The explicit `summary=count` mode returns only the active immutable ARG directory count, source
generation, and cutoff. It does not wait for ontology projection alignment. Resource rows, state
facts, pagination, and detail continue to require the strict inventory-to-ontology generation fence.

Kubernetes identity and diagnostic facts remain a separate allowlisted detail object. They do not
become an operational, availability, or provisioning state axis, and missing diagnostic facts do
not become a state value.
Fleet source availability is also separate from Resource state. The instance detail retains
several same-name sources only when distinct opaque `scope_digest` values qualify them.
Provider-native type coverage is another separate active-generation evidence object. It reports
reconciled mapped and unmapped counts, bounded unknown type names, capture method, and provider
identity completeness without becoming an operational, provisioning, or availability value.
Broad language query categories do not alter exact Resource types or state applicability.
`search-service` remains independently addressable and does not join the generic `database` group.
Any category change must preserve the exact bilingual group-membership contract and pass an
independent semantic review.
Every current instance-detail response includes explicit `runtime_call_graph` and
`postgres_role_evidence` source states. The Console decoder rejects either missing source instead
of presenting omission as availability or measured zero. The Operator reader also rejects a
runtime-call link whose embedded inventory generation differs from the selected snapshot.
Unavailable source reasons use canonical machine tokens only, so principal text and provider
details cannot cross the read boundary.
During schema rollout, a legacy Kubernetes record without every versioned identity field remains a
Resource row. Exact Kubernetes identity and diagnostics stay withheld until a complete versioned
observation replaces it.
Diagnostic arrays retain the collector's maximum sequence of 384 records. This bound applies to the
separate Kubernetes detail and does not widen any recorded-state fact.
That separate detail retains the reviewed rollout, storage, policy, and ephemeral-container facts
that the inventory collector actually produced.
For NetworkPolicy, `selector_matches_all: true` records an explicitly empty `podSelector`. Missing
selector data remains unavailable and does not receive the same meaning.
The persisted AKS assessment receipt is another separate read detail, not a Resource state axis.
Operator joins it only when its immutable target and source identities match the current generation;
otherwise Console renders the receipt as unavailable.
Its gaps, conflicts, and evidence references use visible section headings. They are not hidden in
native title attributes or interpreted as recorded Resource state.

| Axis | Recorded fields | Not inferred |
|------|-----------------|--------------|
| Operational | Explicit service, power, phase, readiness, running, attachment, access, link, or Static Web App default-environment state, including retained nested `runningStatus`, `powerState.code`, `diskState`, `snapshotAccessState`, and `virtualNetworkLinkState`. | Provisioning success does not become running. Enabled, Online, Active, Attached, Completed, and Ready keep their recorded meaning. |
| Provisioning | Explicit `provisioningState`. | Successful creation does not establish availability. |
| Availability | Explicit availability evidence. | Running and Succeeded do not establish healthy service. |
| Serving | Optional exact data-plane success evidence for a reviewed endpoint or deployment. | Resource existence, endpoint configuration, provisioning success, a parent-resource health value, and an unsuccessful or absent request do not establish serving. |

## Recorded fact contract

The additive resource `states` object has `schema_version: "1.0.0"` and `operational`,
`provisioning`, and `availability` facts. A reviewed type may also include an additive `serving`
fact. Existing `status` remains for older consumers.
Each fact carries:

- `value` and `source_path`, nullable when no state was recorded.
- `source_identity` and `authority`, nullable for legacy or missing metadata and otherwise limited
  to the reviewed provider or telemetry source.
- `observed_at` and `recorded_at`, without substituting an inventory read time for effective time.
- `freshness: fresh | stale | unknown` and nullable `completeness`.
- Bounded `conflicts` and a nullable machine-readable `reason`.

Stale or conflicting values remain visible as recorded values with qualifications. Missing metadata
remains unknown; it never becomes an invented observation receipt. A missing value is not automatically
not-applicable. The display projection is not a replacement for the existing decision-critical
ontology query verifier or its receipts.

Freshness measures the age of the evidence cutoff, not the age of the state transition. A current
provider read can therefore confirm a state whose effective time is older without rewriting that
effective time. A retained fact keeps its earlier evidence cutoff and becomes stale when that
confirmation exceeds the declared ceiling.

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
Only a typed inventory or ontology generation transition restarts the entire bounded traversal,
discarding every accumulated page. Initial loading uses bounded exponential delays within one
45-second total deadline. A later manual, periodic, or stream-triggered refresh keeps the last
complete view visible. Manual refresh shows bounded progress and disables duplicate requests;
a generation transition labels the refresh as delayed rather than replacing evidence with an error.
Display filters and local pages operate on this received set; the server query remains the authority. The shared Console decoder recognizes only an `OperatorApiError` with status `409` and the exact `inventory_generation_changed` or `ontology_generation_changed` code as a generation transition; every other failure remains terminal for that load.
A classified source-gate `503` for this route renders unavailable. A generic service or proxy
`503` remains a visible error; it is not evidence that the projection is absent.
Validation evidence for this client behavior binds to the exact Console and upstream revisions.
An integration that changes routing or loading inputs requires the owning unit, build, and browser
checks to run again before their evidence is reused.

## Unified state ingestion and readers

Resource discovery establishes identity and configuration. A separate reviewed state enricher may
add only a typed state value and canonical state-fact metadata before the generation is promoted.
It cannot replace identity, configuration, topology, or inventory observation time.

Every full refresh preserves authoritative subscription and Resource Group scope before bounded
vendor properties are truncated. This applies equally to ARG rows, direct ARM child collections,
Resource Changes hydration, and Activity Log deltas. The local authoritative refresh and the
long-running collector compose the same ordered runtime-call, Resource Health, Static Web App, and
Kubernetes enrichment pipeline. An unavailable or unsupported source records its limitation and
never derives health from provisioning state.
An Activity Log row is omitted before state projection when either its identity-derived type or its
normalized supplied type is outside the reviewed ResourceType vocabulary. When both are reviewed,
the supplied type must match the exact provider or built-in scope shape encoded by its ARM ID.
Omitted rows advance the provider cursor without creating a reconciliation marker; a mapped
contradiction fails before the final cursor fence.
Provider collection paths that end at a type without its resource-name segment are not Resource
identities and cannot contribute a state observation.

The promoted Resource fact is written to both the current `ontology_resource` Resource and the
Operator-readable inventory projection under one generation fence. Core conversational functions
read the ontology instance. Operator instance and batch-state reads use the service-approved
projection of the same fact because the Operator role has no direct Core-table access.
Catalog evidence health joins inventory completion time, projection status, and projection manifest
only when both projection records name the active inventory generation. A mismatch is explicit
unavailable evidence; it never combines timestamps or counts from different generations.

State transition recording is independent of relationship completeness. A complete object
observation can advance operational or availability state history even when an unrelated topology
edge remains unresolved. Relationship history still requires complete relationship evidence.

Impact Scope and Ontology Instances reuse the relationship-evidence envelope from the same active
inventory generation. Each edge keeps evidence availability separate from its verification class,
and `runtime_calls` preserves the stored caller-to-target direction. Missing, stale, incomplete, or
legacy evidence remains visibly unverified and never changes a recorded Resource state.
The operational activity projection maps a `cross_source_conflict:<field>` evidence token to the
machine-safe `cross_source_conflict_<field>` reason code. The read result and state evidence retain
the original token, so presentation normalization cannot rewrite the underlying conflict record.

The observer appends the promoted generation to the normalized journal before publishing history.
If history publication fails, ontology projection does not advance. The next reconciliation replays
that pending active generation under the same coordinator lock before collecting or promoting a new
generation, so a transient history failure cannot create a permanent transition gap.
The browser invalidation stream does not publish from those pre-projection journal rows. The
ontology projector writes one monotonic invalidation marker in the same transaction as the Resource
subgraph, manifest, status, and active-scope checkpoint. Operator emits one sanitized event only
from that committed marker. Its cursor remains greater than legacy journal-watermark event ids, so
an already connected browser cannot silently miss the first post-upgrade projection.

The reviewed alternate availability source is Azure Resource Health. The shared contract declares
the exact ResourceTypes whose ARM type is supported:

- Compute and runtime coverage includes App Service plans, Azure Cache for Redis, Functions, virtual
  machines, VM scale sets, Web Apps, and AKS clusters.
- Data and platform coverage includes alert rules, API Management, Event Hubs, Azure AI service
  accounts, Log Analytics and metrics workspaces, MySQL, PostgreSQL, Azure SQL, Cosmos DB, Redis
  Enterprise, Key Vault, Service Bus, Storage accounts, managed Grafana, Prometheus rule groups,
  and managed search services.
- Network coverage includes Application Gateway, DNS Resolver and inbound endpoints, DNS zones,
  Azure Firewall, Bastion hosts, Load Balancer, NAT Gateway, and Virtual Network Gateway.
- `log-workspace` and several platform types have no single operational running state. Their
  operational axis remains not applicable or not exposed, while availability uses the exact ARM
  Resource Health status.
- `application-insights` has no direct Resource Health status. Its operational and availability
  axes are not applicable. The backing Log Analytics workspace remains a separate related Resource;
  its health is never copied onto Application Insights.
- The reviewed alternate operational source for `static-web-app` is the exact
  `Microsoft.Web/staticSites/builds/default` child resource. The inventory promotion enricher reads
  API version `2023-12-01` and records the documented `BuildStatus` enumeration as
  `staticSiteEnvironmentStatus`, including deployment, ready, failed, deleting, and detached states.
  Preview environments never override the default environment.
- Static Web App state metadata keeps the provider `lastUpdatedOn` value as effective time, falling
  back to `createdTimeUtc` only when needed. The collection completion remains the recorded time and
  evidence cutoff. A successful HTTP response or parent-resource existence never implies `Ready`.
- A model deployment can carry an optional `servingState` from the
  `model.response.200.count` concept, which maps to the exact `AzureOpenAIRequests` metric scoped
  by `ModelDeploymentName` and `StatusCode=200`. One or more
  successful requests in the bounded window records `Serving` with telemetry authority and the
  latest successful metric timestamp. An empty window records no positive state. It does not become
  unavailable, degraded, or healthy, and a retained earlier fact ages normally.
- Model serving collection is passive and bounded. It does not invoke a model, send prompt content,
  consume inference tokens, copy a parent account's Resource Health value, or turn
  `provisioningState` into serving evidence. Exact target validation, concurrency, target count,
  response size, per-call timeout, and a total deadline bound the read. Missing facts retain one of
  `model_serving_not_observed`, `model_serving_source_unavailable`,
  `model_serving_response_invalid`, `model_serving_target_limit`, or
  `model_serving_target_unresolved`.
- The serving lookback and freshness ceiling match the full reconciliation interval. The
  lookback is capped at six hours for a downstream profile with a longer interval. The one-minute
  metric point cap and total deadline are derived from that window, target count, concurrency, and
  per-request timeout. Completed targets survive a deadline; an unqueried target-limit remainder or
  unresolved target makes source coverage explicitly unavailable with a partial reason rather than
  fully available.
- A retained Serving fact keeps its original timestamp only while its evidence cutoff remains
  inside the declared freshness ceiling. After that bound, the current missing-state reason
  replaces the value instead of carrying Serving indefinitely.
- Baseline source states remain in `derived_source_states`. The new model-serving source uses the
  additive `additive_source_states` metadata field, which an N-1 Operator ignores. Upgraded readers
  merge both fields and ignore future bounded source names they do not yet present.
- VM scale-set child collection requests `instanceView` and retains only the exact power-state code.
  VM Run Command hydration retains only `instanceView.executionState`. Status messages, command
  output, command error text, and other unreviewed instance-view fields do not enter inventory.
  Direct ARM children enter only when their exact scale-set parent is present in the primary
  generation, and their returned ARM ids must name one direct child of that parent.
- A failed, unauthorized, malformed, partial, or stale state read records the exact source
  limitation and never substitutes `provisioningState`, existence, or a previous unqualified value.
- Every canonical ResourceType has a reviewed availability outcome: an exact Resource Health
  source, not applicable, or no availability fact exposed by the current provider contract.
  Downstream custom types remain explicitly unreviewed.
- When a Resource Health target has no retained prior fact, its missing availability value carries
  exactly one allowlisted per-resource reason such as `resource_health_not_modeled`; provider response text
  never crosses the read boundary. A retained verified value remains authoritative over the newer
  failed read while source-level partial coverage records that failure.
- Promotion accepts an unavailable-only enrichment only when it names the exact
  `availabilityState` axis with an allowlisted reason. It requires provider metadata only when an
  actual state fact is present.
- Exact reads are bounded to the first 200 targets in stable Resource identity order with concurrency
  eight. Remaining targets retain a prior qualified fact or carry
  `resource_health_target_limit`; source coverage reports the bounded remainder instead of
  abandoning the entire generation.
- One shared service contract, `fdai_service_contracts.recorded_resource_state`, defines the
  reviewed ResourceType path allowlist for both Core ontology projection and Operator reads. Each
  projection applies that allowlist to root and supported nested property owners before inspecting
  stored values, including the legacy top-level `status` field. Only canonical metadata paired with
  a present allowlisted value is retained, and flat metadata remains limited to the supported
  `status` and `state` sibling form. A legacy `status`, `provisioningState`, malformed metadata, or
  unexpected property therefore cannot override a not-applicable or provider-not-exposed outcome.

## Presentation and compatibility

- Dashboard v2 uses the shared state query, not the legacy `inventory/graph` status string.
- Dashboard v2 presents returned scope and snapshot counts in one quiet summary surface, keeps the
  Resource landscape as the primary workspace, aligns evidence coverage beneath it, and reserves
  the secondary rail for Check first highlights or the selected Resource Inspector. This hierarchy
  changes presentation only; every count retains its filtered recorded-state destination.
- Ontology directory and exploration records expose the same additive `states` field from the
  ontology-owned current Resource state.
- `/ontology` opens on the observed Resource instance workspace and requests the declaration graph
  only after an operator enters a definition or topology reference view. The labeled disclosure
  preserves existing reference and declaration deep links without changing recorded-state or graph
  authority.
- The Ontology Instances graph reserves its reviewed viewport height even when a result contains
  only a few nodes, so recorded-state details do not collapse the inspection surface. Direction
  backgrounds cover that complete surface even when the bounded SVG layout is shorter.
- A bounded directory states its visible limit compactly in the search toolbar and confirms that
  search reaches the full generation. It does not use a separate warning-shaped row.
- Selected-instance refresh state shares that toolbar and exposes exact timing or failure detail
  through an accessible tooltip. Coverage and legend details remain available through native
  disclosures instead of occupying the graph's default first viewport.
- An `llm-model-deployment` record may also expose one additive `model_deployment` object. The
  Operator projection allows only model name, model version, deployment SKU, and normalized TPM;
  raw provider properties, tags, rate-limit evidence paths, and credentials stay server-side.
  Inventory uses a bounded read-only ARM deployment list beneath each observed Cognitive Services
  account because ARG does not reliably enumerate this ResourceType. It preserves the verified
  parent relationship and never creates a deployment.
- The shared Console fact view shows source values, timing, freshness, completeness, and reasons.
- Missing values render as Not recorded, Not provided, Unclassified, Not applicable, or
  Applicability unknown from the machine reason. `Not provided` describes the evidence contract,
  not resource availability. Legacy generations can still identify an unbound source explicitly.
- Dashboard counts Not provided and Not applicable separately from genuine Unknown records.
  Tooltips render each recorded axis with its own observation time and use the latest exact axis
  timestamp only for a compact summary. A null fact never discards its machine reason. A legacy
  resource without recorded axes is never treated as Serving from its generic status, and the
  selected Serving lens returns to Operational when a refreshed projection no longer has that axis.
- Compact ontology graph nodes use an exact operational value first. When operation is not
  applicable or the provider exposes no operational state, an exact availability value or useful
  availability evidence gap leads, followed by an exact provisioning value. A missing applicable
  operational value remains visible and cannot be hidden by availability. The selected axis stays
  in the label, and provisioning success never becomes operational success or health.
- A Static Web App with an exact default-environment fact shows that exact operational value, such
  as `Operational: Ready`, `Operational: Deploying`, or `Operational: Failed`. If that reviewed
  source has no recorded value, the label is Not recorded. Not provided is reserved for
  ResourceTypes with no reviewed operational source.
- Dashboard labels the source as `inventory_snapshot_resource`, groups Unknown records by their
  machine reason, and refreshes on the shared interval, browser resume, and inventory invalidation.
- State colors organize recorded values; they do not assert a current operational success.
- A `Succeeded` model deployment state reports provisioning completion only. It does not establish
  inference health, successful requests, quota headroom, or caller authorization. A fresh
  `Serving` fact proves only that the exact deployment processed at least one successful request in
  the bounded metric window. It is not an all-clear verdict or an SLO evaluation.
- The original Dashboard and older instance clients retain their existing routes and fields.
- Resource inspection and selection do not grant approval or execution authority.
- Runtime screen evidence requires a current authenticated 5273 Browser Entra session. An expired
  capture or test-authenticated replacement does not validate the standard operator screen.
- Static Web App runtime validation checks every target in the active generation. Each target must
  show its exact default-environment operational value and freshness qualification, without falling
  back to Not provided when the reviewed source fact is present.
- After a frontend or Operator API replacement, runtime validation rechecks the selected axis label
  on the standard page so a useful availability or provisioning fact cannot regress behind an
  inapplicable operational axis.
- Expanded Resource Health validation compares target, value, and metadata counts by ResourceType.
  Provider-unmodeled targets stay explicit and require an independent operational fact before a
  compact node can show operation.
- Local data-path validation requires one stable active generation, complete provider-type
  accounting, zero missing inventory-to-ontology Resources or state values, and explicit
  unavailable reasons. Authenticated browser validation remains a separate presentation check.
- Runtime primary-state validation includes configuration Resources with no operational or
  availability source. These nodes show exact provisioning when present and retain explicit
  evidence-gap labeling only when every recorded axis lacks a useful exact fact.
- A state-ingestion hardening completion claim records each bounded review round and requires an
  independent follow-up across static gates and live-discovered boundary fixes with no unresolved
  Critical, High, or Medium finding.

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
