---
title: Ontology Query Coverage Implementation Plan
---
# Ontology Query Coverage Implementation Plan

This plan closes the implementation gap between FDAI's bounded conversation and ontology foundations and the target non-keyword path for operator questions. It records the verified current baseline, service and agent ownership, dependency-ordered work packages, cutover gates, and rollback units for 100% structural query coverage.

Governed cloud-reference queries use source-spanned scalar applicability and preserve source dates; the [lifecycle owner](cloud-resource-knowledge-lifecycle.md) defines as-of and live-current behavior.
The [structured retrieval owner](cloud-resource-knowledge-structured-rag.md) defines v1.2 query/utterance binding, unavailable outcomes and legacy compatibility; terms never expand applicability or access. Frame-model schemas omit the server-bound query field.
Coverage-inventory regeneration follows question-bank source changes, including navigation and trace-label catalogs, and refreshes source digests, not measured coverage. A merged Console catalog change requires rebuilding the question bank before its dependent semantic inventory; source-only repairs preserve the 400-question cohort and its existing validation gaps.
The instance-candidate Function binds server principal scope, object read sets, the original release, query, result digest, and bounded accounting. Default bootstrap uses the same declaration as semantic composition and injects controlled-identity workers into Pantheon. Authenticated enrollment drives supervised off-path preparation, audited cold-cache restoration, and source-change withdrawal/rebuild; it never performs query-path embedding builds. Missing model identity keeps the binding unavailable and real semantic qualification remains required. Exact-ID reads retain current graph authorization. Core's dedicated bilingual terminal projection verifies the candidate bindings and displays only identities, types, and revisions, without arbitrary property bags. It reports a partial, non-exhaustive result: an empty candidate list never proves absence. Authenticated live Console evidence remains separate.
Capability preparation preserves all selected canonical property tokens, including ObjectTypes with more than 32 properties. A complete projection over the existing 32 KiB budget fails explicitly before semantic judgment instead of silently dropping its tail.

> **Coverage boundary:** 100% means every readable declaration in one active ontology release has a principal-scoped query descriptor or a typed unavailable reason. It does not promise a complete or correct answer when identity, provider data, history, or evidence is missing.
>
> **Authority boundary:** Natural-language and embedding output remains candidate-only. Read plans have no execution authority. A schema-validated `quoted` or `hypothetical` discourse mode terminates before frame selection, so only a `direct` judgment can enter operational query or draft planning. An explicit change request can create only a typed draft that re-enters the existing judgment, safety, human approval, execution, recovery, and audit path.
>
> **Randomized assurance status (2026-08-11):** The authenticated Console completed 100/100 generated English and Korean turns, but the measured path used only the local Azure narrator. Intent recognition was 100%, answer success was 20%, and all 100 cards were unverified with evidence 0/0. Core now composes the semantic runtime when Azure model candidates, the exact ontology release, and the ontology instance store are available. The measured run predates that binding. The Operator Service now publishes semantic turns and consumes evidence-bound projections. A production-completion claim remains blocked until a new live cross-service and randomized run produces those receipts through the visible Console path. See [Ontology Query Randomized Assurance](ontology-query-randomized-assurance.md).
>
> **Cross-service contract status (2026-08-11):** Additive version 1.2 request and projection envelopes now define the bounded semantic turn, authenticated principal roles, deadline,
> idempotency identity, terminal disposition, and exact evidence digests. They do not activate production routing by themselves. Semantic payloads fail closed instead of being translated to
> the N-1 shape. Core now consumes configured semantic requests, persists canonical results,
> publishes terminal projections, and reports exact missing-provider reasons through startup
> readiness. Operator outbox publication, durable replay, and Console `done` projection are now
> composed. A locally verified answered projection may also emit cumulative receipt-bound
> `confirmed` segments with distinct replay cursors; mismatched terminal verification, evidence,
> receipt, revision, sequence, or text retracts them. POST replay waits through the request deadline and persists a typed hold when no Core
> projection arrives. Operator persistence explicitly types JSONB text parameters so real psycopg
> claim and projection paths remain executable; receipt-backed live integration evidence remains
> the release gate.
>
> **Failure isolation:** A model-identity failure lowers semantic model capability without stopping
> the semantic transport consumer. Core checks the configured model audience before each ordinary
> semantic turn and returns `semantic_model_identity_unavailable` within a bounded preflight when
> authentication is unavailable. Operator accepts only one authoritative terminal result per
> request, records timeout holds at the actual fallback time, and ignores a later competing
> projection. This behavior does not add lexical or regular-expression routing: natural-language
> intent still requires schema-validated model judgment. If preflight returns malformed structured
> output, Core makes one schema-repair attempt with the validation reason before returning the typed
> unavailable outcome.
>
> **Operational preflight judgment:** For reviewed shapes covering F1-F4, current Resource
> collections, and one exact Resource current-state request, compact T1
> preflight can provide provenance-bound candidate meaning and avoid a second serial judgment call.
> Core accepts it only for an explicit, context-independent request with at least 0.75 confidence,
> exact current-utterance spans, supported one-hour canonicalization, a family-specific target and
> facet shape, and the ordinary principal manifest. Any mismatch retains full semantic judgment.
> A Resource collection proposal can carry one source-grounded subtype or category filter and one
> current-state filter without canonical operands. Core binds those phrases through the current
> ontology value domains and inventory-state catalog. An absent or ambiguous binding retains full
> judgment or returns a typed clarification; it never broadens the request to an unfiltered Resource
> collection, and the preflight model cannot invent a query operand. A state-only collection such
> as `Show resources that are currently not running.` uses
> the same inventory-state grounding and deterministic current-state frame without requiring a
> subtype filter. Exact Azure Resource Manager
> identities remain `Resource.id equals` predicates instead of being reduced to the final name
> segment. Accepted collection judgments use a deterministic frame, and any remaining model planner
> receives only the descriptors required by that operational family. Subscription identity and
> Service Health reads build deterministic frames and server plans from their exact no-input
> FunctionTypes instead of invoking a frame model with the full principal manifest. Localized
> Service Health answers map reviewed event category, active status, severity, and completeness
> values to display labels while preserving the provider advisory title verbatim.
> Generic product labels such as APIM, Application Gateway, backend, or GPT are not exact identities.
> They produce a localized request for the exact resource name or ID before frame-model or provider
> I/O. A sole `resource_identity` unresolved term with a typed subject or resource-identity
> requirement remains internal and is not shown as interface copy.
> When an exact-resource live-refresh provider declines a broader Resource set, the typed hold
> preserves the original graph freshness, completeness, conflict, or synthetic-evidence reasons.
> The decline never becomes a successful refresh or a generic provider-success claim.
>
> **Operational Resource visibility:** Every Resource collection applies one server-owned visibility
> rule after deterministic or model planning. It excludes `authorization.role-assignment` from
> operator-selectable Resource results while preserving that object for IAM relationship evidence.
> An explicit IAM or RBAC question uses its dedicated evidence path. When model judgment classifies a
> request for members of one
> exact named resource group, Core builds the verified `Resource.parent_id` frame before model frame
> proposal. It compiles the exact group name into a bounded `parent_id contains` predicate. It does not
> substitute the resource-group object itself or reinterpret the group noun as
> `Resource.type=resource-group`. A `query.resource_current_state` judgment carrying a
> `resource_group` target is rejected as an incompatible typed combination and retried before
> planning. In contrast, a `resource_group` target with explicit collection, list, and name-filter facets selects Resource Group objects by grounded name and type with relationships disabled; it cannot become a child-resource membership query.
>
> **Historical baseline (2026-08-10, not current routing):** Exact ontology releases, semantic candidates, bounded
> ObjectSets, secured query receipts, typed function registration, current inventory projection,
> metric providers, and causal-analysis primitives exist. The production path still uses regex and
> token routing plus an optional serial two-to-three-command read plan. A server-side intent graph,
> principal-scoped release-derived query manifest, `OntologyQueryPlan`, durable semantic index,
> historical topology, and cross-resource temporal provider composition now exist. Production
> turn-completion wiring, durable semantic-index activation publication, and governed
> cross-service and randomized assurance receipts remain incomplete.
> The OQ-01 implementation-free SDK models for the semantic problem frame, query DAG, intent graph,
> task receipt, and structural coverage receipt now ship. Producer and consumer projection wiring
> remains part of OQ-04 and OQ-05.
> OQ-02 now includes a content-addressed principal-scoped manifest builder that filters functions by
> role and purpose and accounts for every supplied release declaration. Every directed LinkType now
> projects deterministic outgoing and incoming endpoint query-side identifiers. The production
> catalog loads the reviewed `Identifiable` Interface, validates explicit bindings for all current
> ObjectTypes, compiles the polymorphic catalog, and includes the declaration in the exact runtime
> release. Wiring this manifest into the narrator and generic query surface remains.
> The reviewable 400-question materialization tracks 11 source files by SHA-256. Regeneration after
> a source update can refresh provenance digests and localized wording, but it does not by itself
> raise runtime coverage or assurance.
> OQ-03 now includes an exact-release query DAG executor with bounded dependency waves, concurrency,
> timeout, cancellation, blocked-descendant handling, stable failure reasons, and task receipts.
> Built-in handlers now cover secured ObjectSet materialization, union, intersection, subtraction,
> ordering, projection, grouped aggregation, and exact-release query/derive/validate function
> invocation. A deterministic verifier checks the principal manifest, readable properties,
> LinkTypes, closed node arguments, dependency output kinds and aggregate fields propagated through
> ObjectSet, Project, Order, and set-operation dependencies,
> function schemas, and registered
> extension schemas before I/O. Temporal, metric-series, and evidence-join handlers now share the
> verifier and executor handler map. Production composition binds PostgreSQL topology history from
> a non-empty state-store DSN and binds metric/evidence handlers only when both a reviewed registry
> and a non-noop provider are available; otherwise, those capabilities remain typed unavailable.
> OQ-07 now projects current connected VNet peering records in the observed direction and private
> endpoint attachments to their exact private-link service targets. Reverse peering still requires
> an independent remote-VNet observation. It also projects `routes_to` only from explicit ARM
> resource next-hop ids; IPs, prefixes, and hostnames never become ontology edges. Snapshot and
> real-time constraints accept the reviewed peering/routing vocabulary. Provider relationship
> extraction now consumes a reviewed mapping catalog that pins property paths, allowed provider
> types, endpoint orientation, source-schema digest, and evidence policy. Only independently
> verified links whose endpoints occur in one complete inventory generation enter the active graph;
> missing endpoints, ambiguous orientation, stale mappings, duplicate or conflicting observations,
> and partial generations remain absent with stable dropped reasons. Workload/service mappings and
> the production network-path issuer remain.
> OQ-04 now has a schema-constrained model seam that proposes a semantic frame and typed node DAG
> from the whole bounded turn and candidate descriptors. Core rebuilds all digests and authority
> fields, verifies the exact principal manifest, and returns a verified plan, one clarification,
> action-draft handoff, unsupported result, or unavailable result. The compatibility coordinator
> can run this path in shadow and records only disposition and content digests. The Azure adapter now
> issues two bounded JSON-object calls through workload identity, validates both proposal schemas,
> and tries resolved candidates in order. Core composition binds that adapter to the exact release,
> current instance store, principal-scoped manifest, deterministic verifier, and request-role-specific
> secured executor when every prerequisite is available. Live cross-service hardening aligns the
> frame proposal's evidence-requirement identifiers with the shared wire contract before Core
> rebuilds the frame digest. Input-free stage and validation diagnostics preserve failure
> attribution without retaining operator text or provider details.
> OQ-05 now deterministically derives an eight-goal intent graph, binds executor receipts to those
> goals, and projects the internal exact-plan contracts to the Console v2/v1 wire shapes. The
> Console accepts explicit cancellation receipts. Executing the semantic plan and attaching these
> projections to the production turn-completion stream remain.
> OQ-06 now restores a service-owned concrete in-memory semantic index with atomic stage, activate,
> stale-generation, typed search, and rollback behavior. A full ontology generation builder emits
> every principal-manifest declaration plus eligible deployment-local object projections, reuses
> unchanged document instances by digest on incremental builds, independently recomputes coverage
> and document roots, and refuses activation until that validation receipt is bound. The durable
> PostgreSQL adapter, scheduled publisher process, and production descriptor-selector binding remain.
> OQ-08 now includes append-only bitemporal topology contracts, a Core-owned migration for retained
> provider generations, object/link revisions and tombstones, deterministic `graph_at` and
> `topology_diff`, late-evidence replay by `known_at`, incomplete-history semantics, and typed query
> handlers with verifier schemas. The PostgreSQL reader/writer binding and inventory-promotion
> revision publisher remain.
> OQ-09 now includes an exact reviewed metric-concept registry without phrase aliases, authoritative
> metric windows, equal-duration comparison that distinguishes zero from missing data, bounded
> metric-series and evidence-join handlers, and topology-aware temporal support/refutation that
> retains competing explanations. Production metric provider bindings and reviewed catalog data
> now include a reviewed alias-free catalog and a concrete `MetricProvider` window adapter that
> preserves observed zero, reports an empty provider result as incomplete, and converts an explicit
> provider failure into an unavailable incomplete window. The causal join remains unresolved and
> grants no execution authority when either metric window is incomplete. Runtime semantic-turn
> composition currently exposes only ObjectSet and pure set/order/project/aggregate handlers.
> Metric-series and evidence-join handlers remain unavailable until their authoritative providers
> are explicitly bound.
> OQ-05 now also includes an async server-side semantic turn runtime that terminates every accepted
> ordinary-language turn as answer, clarification, hold, unsupported, action draft, or cancellation;
> it executes only verified query DAGs and emits exact Console graph/evidence projections.
> OQ-10 changes the synchronous compatibility coordinator default to exact canonical commands only.
> Natural-language aliases, keyword narration, and canonical-string read plans run only when tests
> or an explicit temporary caller select `legacy`; ordinary language belongs to the semantic runtime.
> OQ-11 adds an executable fast gate over all shipped principal manifests and a bilingual competency
> cohort. It requires complete structural accounting, 100% terminal disposition, zero legacy
> ordinary-language routes, zero unsupported claims, and zero unauthorized executions. Answer
> counts remain reported by cohort rather than asserted as universally complete.
> The committed competency cohort uses `receipt_source=deterministic_fixture`. The gate receipt
> keeps local structural validation in `passed` and reports `production_ready=false` whenever any
> question uses deterministic fixture evidence. A caller that claims production completion must
> set `require_production_ready=True` and supply externally produced `cross_service_e2e` or
> `live_assurance` receipts. This keeps the ordinary fast gate runnable in local CI without turning
> a hand-authored fixture into cross-service or live proof. Resource-state meaning requires matching
> distinct T1/T2 judgments and exact source-value type binding, without utterance regex. Catalog changes require pinned release
> and principal-manifest digests; stale deterministic receipts are never accepted by compatibility.
> The `resource_classified_as` and `Forecast`/`Pattern` catalog revisions each refreshed those
> deterministic fixture digests in the same release change.
> Every structural release refresh, including the current validation repair, pins the four answered
> deterministic fixtures to the exact release and Reader principal-manifest digests in the same change.
> The route reuses the App Shape contract and retains `production_ready=false`.
> The first epistemic-closure implementation slice now ships immutable finite
> `QuestionUniverseReceipt`, typed `EpistemicStatus`, proof-carrying `EpistemicQuestionRecord`, and a
> zero-threshold `EpistemicCoverageReceipt`. The existing coverage gate requires a matching passed
> epistemic receipt before external receipt sources can produce `production_ready=true`. This is a
> release-gate foundation only: generated question universes, runtime understanding/completeness/
> claim receipts, and provider-backed L3/L4 certification remain incomplete.
> OKQ-01 now has the catalog declaration, deterministic ResourceType mapping digests, fail-closed
> classification projection, and single-writer persistence tests for `resource_classified_as`.
> Production inventory-job injection is complete; the resource-to-Rule query function remains.
## Design at a glance

![Design at a glance. The main stages are Operator turn, SemanticProblemFrame candidate, Active ontology release, Principal-scoped query manifest, Deterministic verifier, Verified OntologyQueryPlan, Bounded task DAG, Authoritative evidence and receipts, Verified answer or explicit limitation.](../../diagrams/generated/fdai-roadmap-interfaces-ontology-query-coverage-implementation-plan-01.en.svg)

The model decomposes language and proposes a meaning representation. The verifier owns schema
identity, relationship composition, time bounds, scope, purpose, and capability checks. Concrete
objects are selected only by authoritative reads after plan verification.

## Verified baseline and gaps

| Area | Verified current implementation | Gap that blocks the target |
|------|---------------------------------|----------------------------|
| Conversation routing | The default compatibility coordinator accepts exact canonical commands only. Configured semantic topics route ordinary language through the Operator outbox, Core Azure planner and verified DAG, durable projection, and Console `done` frame. | Live cross-service receipts and a descriptor index for manifests beyond the complete-manifest bound remain. `legacy` exists only as an explicit temporary compatibility mode. |
| Cross-service semantic wire | Version 1.2 request and projection envelopes carry bounded semantic input and evidence-bound terminal output without execution authority. Operator and Core use Terraform-provisioned request/projection topics, durable replay, and bounded retry. | Production readiness remains evidence-gated; semantic records never downgrade to N-1. |
| Console intent graph | Core derives a bounded graph and receipt evidence from verified plans, and Operator streams them through the Console-compatible terminal frame. | A new authenticated randomized run must verify the visible browser path against live evidence. |
| Semantic interpretation | The Azure OpenAI adapter proposes a `SemanticProblemFrame` and typed DAG as two strict bounded JSON objects through bearer-token authentication and resolved-candidate fallback. Core supplies identity, validates the Pydantic schemas, verifies the principal manifest, executes with the exact request role, and Operator streams the deterministic evidence-bound answer. | The complete-manifest selector holds when the descriptor bound is exceeded. |
| Object queries | `OntologyQueryPlan` now composes secured ObjectSets, set algebra, ordering, projection, grouped aggregation, and typed read-only functions over immutable content-addressed tables. | Temporal snapshots, metric series, and evidence joins still require registered extension handlers. |
| Query manifest | A principal-scoped content-addressed builder projects ObjectTypes and filtered properties, both LinkType endpoint sides, Interfaces, read-only functions, and draft-only ActionTypes. | The production narrator does not yet consume the manifest, and complete operator/evidence availability descriptors remain. |
| Interfaces | Production catalog loading validates `Identifiable`, its provenance, and explicit bindings for all current ObjectTypes; runtime composition compiles it and pins it in the exact release. | Additional capability Interfaces and production ObjectSet query binding remain. |
| Relationships | Every directed LinkType projects deterministic `<name>.outgoing` and `<name>.incoming` machine query ids with endpoint, cardinality, causal, transitive, and temporal metadata. | The generic plan verifier and planner binding that consume these sides remain. |
| Semantic generations | A concrete service-owned atomic in-memory index and off-path full/incremental ontology generation publisher cover declarations and eligible deployment-local objects with independent validation. | The durable PostgreSQL adapter, scheduled publisher process, and production semantic descriptor selector remain. |
| Current topology | Azure projection consumes reviewed relationship mappings for containment, attachment, dependency, peering, and exact-resource routing candidates. A complete-generation verifier admits only links with both endpoints, independent verifier identity, immutable receipts, and canonical state-fact metadata. A mapping declares the target types it accepts, so an undeclared managed-service connection target yields no link even when the provider recorded one. | Workload and service dependency coverage plus the production network-path issuer remain incomplete. |
| Historical topology | Bitemporal append-only revision contracts, migration, retained generation refs, tombstones, `graph_at`, `topology_diff`, late-evidence replay, and typed query handlers exist. | PostgreSQL reader/writer composition and inventory-promotion publishing remain. |
| Metrics and causality | An exact metric-concept registry, complete/incomplete windows, aligned comparison, and topology-aware temporal support/refutation handlers exist. | Production provider bindings and reviewed metric catalog entries remain. |

## Ownership and service boundaries

| Responsibility | Accountable owner | Runtime placement |
|----------------|-------------------|-------------------|
| Natural-language decomposition and clarification | Bragi | Core agent runtime; Operator Service is the authenticated relay and projection host. |
| Ontology and query-manifest lifecycle | Mimir | Core mechanical builder and catalog lifecycle. |
| Current and historical context materialization | Muninn | Core projection workers and owned persistence adapters. |
| Evidence observation and completeness | Heimdall | Core read-only provider bindings and typed observations. |
| Correlated audit and replay evidence | Saga | Append-only audit path. |
| External query authentication, scope, streaming, and display projection | Operator Service | Independent service using versioned shared contracts only. |
| Query and receipt wire contracts | Shared service-contract SDK | No service implementation or provider access. |

Authority-bearing transitions remain event-bus messages. Read-only query execution may use a
purpose-bound immutable projection, but one service never imports another service's implementation.
No new agent is introduced.

## Target contracts

### Semantic problem frame

`SemanticProblemFrame` separates language interpretation from object retrieval. It carries:

- operation class, such as select, compare, explain change, validate, or draft action;
- subject constraints without an invented runtime identity;
- measure and unit concepts;
- temporal and comparison windows pinned to trusted time;
- requested answer shape and evidence requirements;
- unresolved concepts and competing interpretations.

The preceding `SemanticJudgmentProposal` can additionally preserve explicit prohibited operations
as exact current-utterance spans. The hardened candidate accepts only supplied intent, canonical
identity, and reviewed FunctionType measure names, and corrects only a unique current-turn span.
This candidate remains a shadow pack; active v8 pins schema `1.0.0` without the additive field,
while shadow v14 pins `1.1.0`.

It contains no provider query, raw SQL/KQL, object claim, or execution authority.

### Ontology query plan

A verified `OntologyQueryPlan` is a closed DAG over these operations:

- object or interface selection and exact context anchors;
- typed property predicates and projections;
- reviewed LinkType-side traversal;
- set union, intersection, and subtraction;
- ordering, grouping, and bounded aggregation;
- registered read-only query, derive, and validate functions;
- temporal snapshot, diff, metric-window, and evidence-join nodes.

Every node pins the active release, purpose, role, scope, limits, dependencies, and expected receipt
shape. The plan cannot contain executable provider text or a mutation handler.

### Composite read-only instance paths

A current relationship answer can combine ontology declarations with runtime instances only through
one verified composite node. The node binds the exact release, authenticated principal-scope digest,
singleton purpose, current graph cutoff, every secured graph receipt, the path definition, and the
final result digest. Its authority is `server_ontology_instance_path`, and
`execution_authority=false` is fixed.

The composite node accepts declaration evidence only from `server_ontology_manifest` and instance
evidence only from `server_inventory_graph`. It validates those inputs rather than treating multiple
authorities as interchangeable. Global answer verification resolves the authority of terminal output
nodes after each dependency has passed its own authority check. Unrelated mixed authorities,
unverified derivations, missing principal scope, release drift, generation drift, redacted path
identity, incomplete evidence, and path-limit overflow keep the answer held.

An instance path preserves each concrete root-to-target lineage. It does not return a cross-product
of independently selected endpoints. An empty root or hop cannot answer a request to trace current
ownership, so the node holds with no identity claim. Schema-only LinkType evidence continues to
describe possible relationships and cannot prove a current service, workload, resource, or owning
Agent instance.

## Work packages

| ID | Work package | Depends on | Exit evidence |
|----|--------------|------------|---------------|
| OQ-00 | Freeze the current implementation baseline, correct status claims, inventory every regex/token route, and add bilingual competency cohorts for exact, ambiguous, unsupported, temporal, causal, and action questions. | None | Machine-readable baseline and replay fixtures identify every compatibility path. |
| OQ-01 | Add versioned shared contracts for `SemanticProblemFrame`, `OntologyQueryPlan`, intent goals, clarification, task receipts, and structural coverage receipts. | OQ-00 | N/N-1 codec tests reject unknown authority, unbounded plans, cycles, and stale refs. |
| OQ-02 | Extend ontology catalog data with LinkType query sides and reviewed Interface declarations; generate a complete principal-scoped manifest from the exact release. | OQ-01 | Every readable ObjectType, Property, LinkType side, Interface, FunctionType, and draft-only ActionType has one descriptor or unavailable reason. |
| OQ-03 | Implement the generic plan verifier and executor over ObjectSets, set operations, ordering, aggregation, projection, and typed function nodes. | OQ-01, OQ-02 | Property tests prove bounds, type safety, purpose narrowing, ACL closure, truncation, cancellation, and stable receipts. |
| OQ-04 | Replace string-command `ReadPlanNarrator` planning with Bragi-owned schema-constrained decomposition, manifest search/describe, deterministic verification, and durable clarification. Run it in shadow beside the compatibility path. | OQ-02, OQ-03 | English/Korean turns produce replay-stable verified plans or one bounded clarification without invoking an unverified read. |
| OQ-05 | Implement the server-side intent graph and dependency-wave task executor with bounded concurrency, cancellation, blocked descendants, conflict detection, one evidence ledger, and claim verification. | OQ-03, OQ-04 | Operator Service streams the same versioned graph and receipts that the Console already validates; partial branches cannot become complete answers. |
| OQ-06 | Restore a concrete semantic-index adapter and off-path generation publisher in the owning service, then expand generation documents from Rules to declarations and eligible deployment-local object projections. | OQ-02 | Full initial generation, digest-reusing incremental generation, independent validation, atomic activation, stale degradation, and rollback tests pass. |
| OQ-07 | Complete current Azure topology projection for VNet peering, routes, private endpoints, network membership, workload placement, and service dependencies; bind the network-path receipt issuer. | OQ-02, OQ-03 | VM-to-service and service-to-data-store path fixtures preserve direction, reciprocal peering evidence, completeness, and unknown absence. |
| OQ-08 | Add append-only topology relationship revisions and retained provider-generation references, plus bounded `graph_at` and `topology_diff` functions. Keep the current graph as the fast current-state projection. | OQ-03, OQ-07 | Before/after peering fixtures reconstruct exact retained graphs, tombstones, late evidence, and incomplete history without rewriting decisions. |
| OQ-09 | Add a reviewed metric-semantic registry and bounded functions for metric series, change points, aligned windows, cross-resource temporal correlation, and causal support/refutation. | OQ-03, OQ-05, OQ-08 | Request-growth and storage-write-loss scenarios distinguish zero from missing data, correlate changes without asserting chronology as cause, and cite competing explanations. |
| OQ-10 | Shadow-replay the new path against every compatibility route, promote by measured cohort, then remove regex, keyword narrator, phrase-based answer intent, and canonical-string read planning from ordinary language. Preserve an explicit exact-command surface separately. | OQ-05, OQ-06, OQ-09 | New path meets or improves cohort quality and latency, legacy ordinary-language routing share is zero, and exact technical commands remain deterministic. |
| OQ-11 | Enforce continuous structural and epistemic coverage gates on every ontology release and capability change. | OQ-10 | Structural coverage, finite question-universe accounting, and terminal epistemic disposition are 100%; unsupported or ungrounded claims, hidden-scope leaks, unsafe mutation survivors, locale divergence, and unauthorized executions are zero; answer coverage is reported by cohort, not asserted. |

## Parallel lanes and merge points

- **Lane A - contracts and manifest:** OQ-01 -> OQ-02.
- **Lane B - query kernel:** OQ-03 after the OQ-01 contract freeze; it joins OQ-02 before release.
- **Lane C - semantic projection:** OQ-06 begins after descriptor identity from OQ-02 is stable.
- **Lane D - operational evidence:** OQ-07 -> OQ-08 -> OQ-09, parallel to OQ-04/OQ-05 after OQ-03.
- **Lane E - conversation cutover:** OQ-04 -> OQ-05 -> OQ-10, joining OQ-06 and OQ-09 at cutover.

Each lane runs only focused tests. OQ-10 is the first integration point that compares complete
end-to-end behavior. OQ-11 is the release gate.

## Competency scenarios

### Request volume increased since last week

The expected plan decomposes the request into `explain_change`, a request-volume measure, service
subject constraints, equal baseline/current windows, and causal-evidence requirements. It then
resolves the metric concept, finds affected services, traverses to workloads and pods, retrieves
changes around the change point, compares complete windows, and ranks supported/refuted/unresolved
hypotheses. "Requests" or the calendar boundary remains a clarification when context cannot resolve
it.

### Storage writes stopped after a network change

The expected plan anchors the storage object and write-success series, discovers upstream workload
and VM dependencies from the retained pre-change graph, compares network paths before and after the
change, retrieves the peering revision and write-attempt evidence, and tests DNS, route, firewall,
credential, and application alternatives. A missing current edge never proves that an old path did
not exist or that the peering change caused the symptom.

## Migration, rollout, and rollback

- **Additive contracts first:** New fields and tables land without changing the current read path.
- **Shadow comparison:** New plans execute read-only beside compatibility routing and cannot alter the
  visible answer until cohort gates pass.
- **Atomic generations:** Semantic generations stage and validate before pointer activation; rollback
  reactivates a retained compatible generation.
- **Separate temporal storage:** Historical relationship revisions never turn the current instance
  store into an implicit latest-wins bitemporal authority.
- **Capability switches:** Availability, enabled state, and authority remain independent. Disabling
  semantic planning returns to exact commands and typed unavailable results, not keyword guessing.
- **Legacy removal last:** Regex and token paths are deleted only after replay evidence and one stable
  rollback release. Re-enabling them is not the long-term rollback mechanism.

## Verification and measures

| Measure | Release expectation |
|---------|---------------------|
| Structural schema coverage | 100% of readable active declarations represented or typed unavailable. |
| Question disposition | 100% of accepted turns terminate as answer, clarification, hold, unsupported, or draft. |
| Finite question-universe disposition | 100% of generated cases close with a typed epistemic status or reviewed exclusion. |
| Interpretation and claim proof | 100% source-span and semantic-atom coverage for non-cancelled turns; every answer carries claim proof. |
| Empty and negative proof | Every verified empty or negative result carries closed-population proof. |
| Unsupported operational claims | Exactly 0. |
| Ungrounded claims, unresolved conflicts, hidden-scope leaks, unsafe mutation survivors, and locale divergence | Exactly 0. |
| Unauthorized execution from conversation | Exactly 0. |
| Exact identity and stale-revision errors | Exactly 0. |
| Answer coverage | Measured separately by question, language, domain, provider, and evidence cohort. |
| Clarification quality | Correctly asks only when material competing interpretations remain. |
| Full vs incremental generation parity | Identical ordered document digests and retrieval cohort outcomes. |
| Historical replay | Same cutoff resolves the same retained graph and evidence receipts. |

## Twenty-round hardening record

The first three landed slices were reviewed through 20 independent critique lenses covering
contract digests, bounds, DAGs, concurrency, authority, serialization, error handling, cancellation,
redaction, replay time, manifest accounting, stale releases, ObjectSets, receipts, performance,
service boundaries, Operator projection, narrator authority, degradation, and docs-code parity.

Verified Medium-or-higher findings were resolved as follows:

- principal-scoped manifests now remove properties outside the caller role or purpose;
- declarations absent from the exact release are rejected rather than silently ignored;
- execution rechecks both ontology release and query-manifest digest;
- manifest hashing has an explicit 8 MiB ceiling instead of the small per-record JSON ceiling;
- cancellation is observed before and during handler execution, including semaphore wait;
- the node deadline covers queueing and handler execution together;
- authorization denial, unavailable handlers, invalid handler results, timeout, cancellation, and
  unexpected provider failures produce stable typed receipts without provider details;
- focused tests cover concurrent waves, blocked descendants, stale authority, cancellation races,
  total deadlines, property filtering, declaration mismatch, and digest stability.

Rejected findings included handler-internal fan-out, impossible DAG cycles after contract
validation, timezone-naive receipt acceptance, and candidate-limit truncation. These were either
outside the executor boundary or already fail-closed by the existing contract. No reproducible
Medium-or-higher finding remains in the landed contract, manifest, and executor slices.

Residual Low observations are code duplication between terminal receipt builders, multiple bounded
graph projection passes, and clearer diagnostics for developer-only adapters. Additional semantic
Interfaces, production planner binding, semantic generation, topology history, and temporal joins
remain planned capabilities, not hidden hardening defects.

The OQ-04/OQ-05 foundation received an additional 25-lens adversarial review covering authority,
model trust, digest binding, structural coverage, role and purpose, descriptor mutation, input
bounds, prompt injection, clarification, action drafts, verifier bypass, graph/receipt mapping,
cancellation, Console parity, replay, redaction, compatibility routing, service boundaries, agent
ownership, concurrency, tests, and docs. One reproducible Medium finding was fixed: a release
declaration whose runtime metadata was omitted can no longer disappear from structural coverage;
manifest construction now fails closed. The proposed descriptor-mutation finding was rejected
because the selector is checked as an exact manifest subset and deep-copied before model exposure,
and the test proves the source manifest remains unchanged. The owning bilingual designs already
document the new seams. No reproducible Medium-or-higher finding remains in this shadow-only slice.

After OQ-06 through OQ-11 landed, the complete program received another 25-lens review covering
8,500-row generation parity, activation and rollback, embedding bounds, Interface ACLs, LinkType
sides, query typing, cutover escape paths, total disposition, evidence truncation, cancellation,
bitemporal time, tombstones, migrations and grants, `routes_to`, zero-vs-missing metrics, causal
refutation, provider identity, continuous-gate honesty, boundaries, docs, and test blind spots. Two
reproducible Medium findings were fixed: Interface properties now receive the same role/purpose
filtering as ObjectType properties, and goal receipts preserve both an existing terminal reason and
evidence-reference truncation. Focused regressions prove both fixes. No reproducible
Medium-or-higher finding remains in the implemented ontology-query program; remaining production
provider and durable adapter bindings are explicit delivery gaps and fail closed.

## Related docs

| To learn about | Read |
|----------------|------|
| Delivery status and remaining work | [Implementation ledger](../../roadmap-implementation/interfaces/ontology-query-coverage-implementation-plan.md) |
| Randomized Console evidence and the current release blocker | [Ontology Query Randomized Assurance](ontology-query-randomized-assurance.md) |
| Target question planning and coverage contract | [Hierarchical Conversation Planning](hierarchical-conversation-planning.md) |
| Exact releases, ObjectSets, and typed functions | [FDAI Ontology Safety Infrastructure](../architecture/operating-ontology-platform.md) |
| Operating objects, relationships, identity, and time | [FDAI Operating Ontology](../architecture/operating-ontology.md) |
| Rule-specific semantic generations | [Rule Semantic Retrieval](../rules-and-detection/rule-semantic-retrieval.md) |
| Causal hypothesis evidence and closure | [Causal Incident Graph](../rules-and-detection/causal-incident-graph.md) |
| Console and narrator authority | [FDAI Console Conversations](operator-console.md) |
