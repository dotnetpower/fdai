---
title: Ontology Query Coverage Implementation Plan
---

# Ontology Query Coverage Implementation Plan

This plan closes the implementation gap between FDAI's bounded conversation and ontology
foundations and the target non-keyword path for operator questions. It records the verified current
baseline, service and agent ownership, dependency-ordered work packages, cutover gates, and rollback
units for 100% structural query coverage.

> **Coverage boundary:** 100% means every readable declaration in one active ontology release has a
> principal-scoped query descriptor or a typed unavailable reason. It does not promise a complete or
> correct answer when identity, provider data, history, or evidence is missing.
>
> **Authority boundary:** Natural-language and embedding output remains candidate-only. Read plans
> have no execution authority. An explicit change request can create only a typed draft that re-enters
> the existing judgment, safety, human approval, execution, recovery, and audit path.
>
> **Randomized assurance status (2026-08-11):** The authenticated Console completed 100/100
> generated English and Korean turns, but the measured path used only the local Azure narrator.
> Intent recognition was 100%, answer success was 20%, and all 100 cards were unverified with
> evidence 0/0. Core now composes the semantic runtime when Azure model candidates, the exact
> ontology release, and the ontology instance store are available. The measured run predates that
> binding. The Operator Service now publishes semantic turns and consumes evidence-bound
> projections. A production-completion claim remains blocked until a new live cross-service and
> randomized run produces those receipts through the visible Console path. See
> [Ontology Query Randomized Assurance](ontology-query-randomized-assurance.md).
>
> **Cross-service contract status (2026-08-11):** Additive version 1.2 request and projection
> envelopes now define the bounded semantic turn, authenticated principal roles, deadline,
> idempotency identity, terminal disposition, and exact evidence digests. They do not activate
> production routing by themselves. Semantic payloads fail closed instead of being translated to
> the N-1 shape. Core now consumes configured semantic requests, persists canonical results,
> publishes terminal projections, and reports exact missing-provider reasons through startup
> readiness. Operator outbox publication, durable replay, and Console `done` projection are now
> composed. POST replay waits through the request deadline and persists a typed hold when no Core
> projection arrives. Operator persistence explicitly types JSONB text parameters so real psycopg
> claim and projection paths remain executable; receipt-backed live integration evidence remains
> the release gate.
>
> **Implementation status (2026-08-10):** Exact ontology releases, semantic candidates, bounded
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
> OQ-03 now includes an exact-release query DAG executor with bounded dependency waves, concurrency,
> timeout, cancellation, blocked-descendant handling, stable failure reasons, and task receipts.
> Built-in handlers now cover secured ObjectSet materialization, union, intersection, subtraction,
> ordering, projection, grouped aggregation, and exact-release query/derive/validate function
> invocation. A deterministic verifier checks the principal manifest, readable properties,
> LinkTypes, closed node arguments, dependency output kinds, function schemas, and registered
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
> preserves observed zero and reports an empty provider result as incomplete. Runtime semantic-turn
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
> a hand-authored fixture into cross-service or live proof. When catalog structure changes, every
> answered fixture must pin the newly computed release and principal-manifest digests before the
> gate can pass; stale deterministic receipts are never accepted by compatibility.
> The current `resource_classified_as` catalog revision refreshes those deterministic fixture
> digests in the same release change.
> The first epistemic-closure implementation slice now ships immutable finite
> `QuestionUniverseReceipt`, typed `EpistemicStatus`, proof-carrying `EpistemicQuestionRecord`, and a
> zero-threshold `EpistemicCoverageReceipt`. The existing coverage gate requires a matching passed
> epistemic receipt before external receipt sources can produce `production_ready=true`. This is a
> release-gate foundation only: generated question universes, runtime understanding/completeness/
> claim receipts, and provider-backed L3/L4 certification remain incomplete.
> OKQ-01 now has the catalog declaration, deterministic ResourceType mapping digests, fail-closed
> classification projection, and single-writer persistence tests for `resource_classified_as`.
> Production inventory-job injection is complete; the resource-to-Rule query function remains.

## Implementation status

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| Semantic wire and Core processing | implemented | `semantic_turn.py`, `semantic_turn_consumer.py`, `semantic_turn_processor.py`; focused semantic tests passed 88 cases | Version 1.2 requests are bounded to 90 seconds, results are idempotent, claims are recoverable, and Rule results remain candidate-only with no execution authority. |
| Operator persistence and Rule projection | implemented | `semantic_turn.py`, `semantic_turn_runtime.py`, `postgres_semantic_turn_store.py`, `test_semantic_turn_bridge.py`; focused semantic tests passed 88 cases and a rollback-only PostgreSQL transaction probe passed | A valid caller-supplied request UUID is preserved through the semantic envelope and correlation identity while the idempotency key remains separate. An omitted request UUID uses the retry-stable deterministic fallback. Outbox and result leases are recoverable, malformed ownership fails closed, replay ordering is timestamp-aware, and exact Rule reads are isolated by principal and query digest. `SemanticTurnBridge` remains gated on the authoritative store and semantic transport, while the local narrator's periodic refresh remains an independent Operator lifecycle service when that narrator is configured. |
| Historical topology persistence and publishing | implemented | `inventory_topology_history.py`, `postgres_topology_history.py`, `inventory_sync_cli.py`; focused inventory and topology tests passed 31 cases | Complete promoted observations append bitemporal revisions atomically. Historical and current derived writes are attempted independently, while incomplete observations cannot establish a complete historical baseline. |
| Temporal, metric, and evidence provider composition | implemented | `wire_semantic_query.py`, `bootstrap.py`, `bootstrap_bindings.py`, `test_wire_semantic_query.py`, `test_bootstrap_config.py`; focused composition and provider-selection tests passed 16 cases | One handler map controls verifier availability and execution. Production binds PostgreSQL history from the state-store DSN and binds metric/evidence handlers only for a reviewed registry plus a non-noop provider. |
| Governed production assurance | in-progress | [Ontology Query Randomized Assurance](ontology-query-randomized-assurance.md) and the verified baseline gap table below | Local checks prove fail-closed composition, but no governed live cross-service receipt proves production readiness. |
| Typed Console assurance runners | implemented | `console-routes.spec.ts`; `ontology-query-assurance.ts`; `ontology-query-assurance.spec.ts`; focused Console checks | One runner verifies publication, Core processing, exact projection read, and authenticated receipt rendering. The seeded 100-turn runner covers 50 English and 50 Korean prompts with a typed-only oracle. Neither implementation is live evidence until its retained artifact passes. |
| T1 clarification evaluation | implemented | `semantic_planning_models.py`; `semantic_planning_cascade.py`; focused tier-routing and prompt checks | Frame proposals classify missing user context with bounded `clarification_requirements`. A legitimate T1 clarification terminates without T2, while a request for server-bound principal scope or purpose is deterministically invalid and may retry only the frame stage once with T2. |
| Typed extension answer projection | implemented | `semantic_turn_processor.py`; focused Core processor tests | Verified `TopologyGraphAt`, `TopologyDiff`, `MetricWindow`, and `CausalEvidenceJoin` outputs render as bounded summaries with exact digests, completeness, counts, limitations, and `execution_authority=false`. Raw provider payloads remain excluded and evidence references continue through the existing receipt path. |
| Incident semantic evidence | in-progress | `core/incident/ontology_projection.py`; `core/ontology_platform/incident_queries.py`; focused Incident and semantic-composition checks (`63 passed`) | Canonical Incident state is queryable as an ObjectSet and `query.incident_evidence` preserves distinct canonical incident and audit correlation identities while returning an audit-backed profile, correlated records, explicit gaps, and no cause authority. The A3 answer contract and authenticated Console evidence remain open. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-08-13 | in-progress | Adopted the implementation ledger without reconstructing earlier provenance. | Current source, tests, and status evidence listed in the scope table. | Obtain the live assurance and provider-composition evidence listed below. |
| 2026-08-13 | implemented | Hardened Rule-search contracts, Core idempotency and claims, Operator retries and leases, exact persistence, replay, and ownership validation through more than ten adversarial review rounds. | `current change`; `pytest -q services/core-control-plane/tests/test_semantic_turn_processor.py services/operator-service/tests/test_semantic_turn_bridge.py services/operator-service/tests/test_operator_workflow_family.py tests/integration/test_semantic_turn_roundtrip.py` passed 88 cases; task-scoped Ruff passed; a rollback-only PostgreSQL transaction probe passed. | Production validation remains blocked on governed live receipts. |
| 2026-08-13 | implemented | Added deterministic inventory-promotion topology revision publishing and an append-only bitemporal PostgreSQL reader/writer with independent current and historical derived writes. | `current change`; focused inventory and topology tests passed 31 cases; task-scoped Ruff and mypy passed. | Bind the historical reader to the production semantic query runtime and obtain governed runtime evidence. |
| 2026-08-13 | implemented | Bound temporal topology, metric-series, and evidence-join capabilities into exact-release semantic runtime composition. Optional metric dependencies are atomic, and absent providers remain unavailable to both the verifier and executor. | `current change`; `wire_semantic_query.py`, `bootstrap.py`, `test_wire_semantic_query.py`, and `test_bootstrap_config.py`; focused checks passed 16 cases. | Record governed request-to-Console and randomized assurance receipts. |
| 2026-08-13 | implemented | Moved concrete semantic-query provider selection into the runtime binding helper so the process entry point stays within its reviewed composition fanout. | `current change`; `bootstrap.py`, `bootstrap_bindings.py`, and `test_bootstrap_config.py`; focused provider-selection tests passed 3 cases. | Record governed request-to-Console and randomized assurance receipts. |
| 2026-08-13 | in-progress | Added authenticated request-to-Console and deterministic bilingual randomized-assurance runners with typed receipt oracles and derived readiness counters. | `current change`; focused Console tests, assurance-oracle tests, typecheck, and Playwright discovery pass. | Execute both runners against the authenticated local stack and link the two passing retained evidence records. |
| 2026-08-13 | implemented | Preserved a valid caller-supplied request UUID across the Operator semantic envelope and correlation identity without conflating it with the idempotency key; retained the deterministic UUID fallback for callers that omit request identity. | `current change`; `semantic_turn.py`; `test_semantic_turn_bridge.py`; focused caller-identity and retry-stability tests pass. | Obtain the governed authenticated receipt for the exact request identity before running randomized assurance. |
| 2026-08-14 | implemented | Added additive `operator-core-request` 1.3.0 with a server-owned `bound_context`, so a Console incident conversation delivers its bound incident identity to Core instead of dropping it. Core appends the binding as the last `system` context turn, which the planner's bounded window cannot discard. | `current change`; `semantic_turn.py` (contract, Operator, Core), `contract_codecs.py`, `compatibility-manifest.json`; core processor 32, Operator bridge 42, contracts 76, and route targets 326 passed; independent-services and ontology-query-coverage gates passed; strict mypy passed. | The bound incident is still not answerable: the semantic query manifest exposes no incident ObjectSet or incident-evidence FunctionType, so an incident investigation resolves to clarification. |
| 2026-08-14 | implemented | Moved the semantic request publisher to the 1.3.0 producer codec. The envelope builder already validated 1.3.0, so the stale publisher silently rejected every bound turn and the Console request never reached Core. | `current change`; `semantic_kafka.py`; Operator adapter and bridge suites passed 51 cases; a restarted local stack answered a bound incident turn in 6.4 s and Core logged the three planning stages with no decode failure. | Incident competency remains the open gap. |
| 2026-08-14 | in-progress | Projected canonical Incident instances and added the exact-release, correlation-scoped `query.incident_evidence` FunctionType over the append-only audit source. The function exposes profile, correlated records, truncation, and evidence gaps while fixing `cause_claim_supported=false` and `execution_authority=false`. | Commit `285341732` plus `current change`; focused Incident, registry, adapter, and semantic-composition checks passed 62 cases; task-scoped Ruff and strict mypy passed. | Add the A3 answer contract and action-draft-only next safe step, then retain authenticated Console evidence. |
| 2026-08-14 | in-progress | Corrected the initial incident FunctionType contract so canonical `incident_id` and audit `correlation_id` remain distinct from the bound Console context through verified plan execution and evidence projection. | `current change`; the incident FunctionType tests and end-to-end semantic composition regression passed, bringing the focused slice to 63 cases. | Restart the local stack, verify the same authenticated incident turn, then retain governed evidence before changing the capability state. |
| 2026-08-14 | in-progress | Aligned semantic frame and plan prompt v2 with the distinct bound identities so the model preserves both `incident_id` and `correlation_id` in the verified Function node instead of producing an invalid partial argument set. | `current change`; the focused prompt registry contract passed 5 cases. | Restart the local stack and verify the same authenticated incident turn before changing the capability state. |
| 2026-08-14 | implemented | Completed the incident answer projection with localized readable content, replayable observed progress, exact collapsed technical output, explicit causal and evidence gaps, read-only evidence collection as the default next step, and verified incident identity preserved through regeneration. | `current change`; focused Core (`36 passed`), Operator (`46 passed`), cross-service (`1 passed`), and Console (`74 passed`) checks plus Console typecheck and task-scoped Ruff passed. An authenticated Browser Entra observation rendered the same verified three-record result after regeneration but wasn't retained as a governed artifact. | Retain the governed request-to-Console and Korean equivalent evidence before promoting this scope to `validated`. |
| 2026-08-14 | implemented | Made semantic regeneration retry-stable by preserving the original bounded history and verified request identity, binding the request identity to Operator idempotency, propagating the canonical locale, and retrying repeated Azure throttling or schema-invalid candidates within the adapter budget. | `current change`; focused Console stream, normalizer, session, and event checks passed 128 cases; the Azure semantic-planning adapter passed 5 cases; Console typecheck and task-scoped Ruff passed. A retained authenticated Korean Browser working-tree run passed both turns with one five-stage Core planning cycle. | Commit and centrally validate the bounded change, then retain an exact-source authenticated Browser artifact before promoting the incident answer row to `validated`. |
| 2026-08-14 | validated | Closed the bounded authenticated incident-answer evidence gap after central validation. | Source revisions `7f2b740b1` and `244d003ef` have central receipts; the retained post-validation Korean Browser artifact records matching request, incident-binding, and technical-output digests across regeneration, with five observed phases and no execution authority. | The full request-to-Console runner and bilingual randomized cohort remain open production-assurance work. |
| 2026-08-14 | in-progress | Reopened incident assurance because the current bounded action-draft and browser-readiness changes require a new governed artifact. | `current change`; focused semantic, Console, and browser-assurance checks. | Retain the replacement request-to-Console and bilingual randomized evidence before restoring `validated`. |
| 2026-08-15 | implemented | Kept local narrator refresh independent from semantic transport while preserving transport-gated `SemanticTurnBridge` activation. | `current change`; focused production composition and semantic bridge tests passed 2 cases; task-scoped Ruff passed. | Retain the governed request-to-Console and bilingual randomized evidence before changing production-assurance state. |
| 2026-08-15 | implemented | Added machine-readable clarification requirements and rejected T1 frame proposals that ask for principal scope or purpose already bound by Core. Semantic frame prompt v4 tells both tiers to treat those values as trusted server context. | `current change`; focused semantic planner checks passed 21 cases, prompt and Azure adapter checks passed 10 cases, and task-scoped Ruff and strict mypy passed. | Restart Core after central validation and rerun the governed request-to-Console assurance path. |
| 2026-08-15 | implemented | Added bounded projection for verified topology graph, topology diff, metric window, and causal join outputs. | `current change`; focused Core processor tests passed 43 cases, and task-scoped Ruff and strict mypy passed. | Retain authenticated temporal and causal answer evidence after the planner contract is active. |

### Remaining work

- [ ] Record one governed request-to-Console receipt that covers Operator publication, Core processing, exact Operator projection read, and authenticated Console rendering; rerun the bilingual randomized assurance cohort and link both passing evidence records.
- [x] Project canonical `Incident` instances into the current ontology store for bounded `ObjectSet` selection.
- [x] Register the read-only `query.incident_evidence` FunctionType over correlation-scoped audit evidence with explicit gaps and no cause authority.
- [ ] Constrain the incident answer to profile, correlated evidence, and explicit gaps, and represent the next safe step only as a candidate `SemanticOperation.ACTION_DRAFT`; retain the authenticated Console receipt.
- [x] Deliver the bound conversation context from the Console through Operator to Core as additive typed request state.
- [x] Compose the durable semantic index, historical topology reader, metric-series, and evidence-join providers with typed unavailable behavior and focused checks.

## Design at a glance

```mermaid
flowchart LR
    Q[Operator turn] --> F[SemanticProblemFrame candidate]
    R[Active ontology release] --> M[Principal-scoped query manifest]
    M --> F
    F --> V[Deterministic verifier]
    V --> P[Verified OntologyQueryPlan]
    P --> D[Bounded task DAG]
    D --> E[Authoritative evidence and receipts]
    E --> A[Verified answer or explicit limitation]
```

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
| Current topology | Azure projection consumes reviewed relationship mappings for containment, attachment, dependency, peering, and exact-resource routing candidates. A complete-generation verifier admits only links with both endpoints, independent verifier identity, immutable receipts, and canonical state-fact metadata. | Workload and service dependency coverage plus the production network-path issuer remain incomplete. |
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
| Randomized Console evidence and the current release blocker | [Ontology Query Randomized Assurance](ontology-query-randomized-assurance.md) |
| Target question planning and coverage contract | [Hierarchical Conversation Planning](hierarchical-conversation-planning.md) |
| Exact releases, ObjectSets, and typed functions | [FDAI Ontology Safety Infrastructure](../architecture/operating-ontology-platform.md) |
| Operating objects, relationships, identity, and time | [FDAI Operating Ontology](../architecture/operating-ontology.md) |
| Rule-specific semantic generations | [Rule Semantic Retrieval](../rules-and-detection/rule-semantic-retrieval.md) |
| Causal hypothesis evidence and closure | [Causal Incident Graph](../rules-and-detection/causal-incident-graph.md) |
| Console and narrator authority | [FDAI Console Conversations](operator-console.md) |
