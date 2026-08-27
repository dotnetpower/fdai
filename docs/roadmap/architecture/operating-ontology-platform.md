---
title: FDAI Ontology Safety Infrastructure
---
# FDAI Ontology Safety Infrastructure

This document extends the operating ontology into a typed infrastructure layer for FDAI's agents. It adds object polymorphism,
bounded object sets, semantic action effects, typed functions, authority-aware writeback, exact schema pinning, and generated SDK surfaces. Agents still own every runtime transition; these primitives constrain their inputs, plans, and effect verification.

> **Authority boundary:** Observed provider state remains a projection. An action can request a provider, Git, ledger, or FDAI-owned state change, but it cannot make an external fact true by
> editing the ontology graph.
>
> **Safety boundary:** Functions plan, query, derive, or validate. Only Thor executes an approved
> `MutationPlan`, and every external effect closes through independent reconciliation.
>
> **Implementation status (2026-08-08):** K0 contract identity is implemented for canonical
> releases, ActionBuilder output, and in-memory ontology writes. K1 semantic interface compilation
> and bounded ObjectSet queries are implemented. K2-K5 core primitives now cover mutation plans,
> stale revision checks, typed functions, projection bindings, reconciliation, scoped SDK
> generation, and a read-only manifest. PostgreSQL object/link writes persist exact type versions
> and release digests, and production ActionBuilder composition uses the full loaded release.
> PostgreSQL also stores each exact object/link release manifest in `ontology_release`. Startup
> persists the active manifest and loads every registered manifest before decoding prior rows.
> Missing releases, manifest/digest mismatches, and declaration/version mismatches fail closed.
> Persisted 1.2.0 inventory manifests take a bounded rebuild path on the next exact projection and
> become 1.3.0; they are not silently treated as current evidence.
> The existing Reader-gated `GET /ontology/graph` projection exposes the release digest,
> proposal-only write surface, and `mutation_authority: false`; it adds no mutation route.
> Pre-migration rows remain explicitly unpinned because their original release digest cannot be
> reconstructed honestly. The next successful write creates a new, fully revalidated current-state
> revision and pins that new revision to the then-active release.
> Semantic Interface declarations now use the shared contract and contribute to the canonical
> runtime release. Production catalog loading validates `Identifiable`, `Ownable`, `Operable`,
> `Observable`, `Recoverable`, `ObjectiveBound`, and `CostBearing`, including provenance,
> inheritance, LinkType and ActionType references, and conservative explicit ObjectType bindings.
> Composition compiles the polymorphic catalog into the exact release.
> Base-only catalog projection excludes optional vertical assets. Tests that cover Cost Governance
> properties explicitly install and enable one digest-bound package before building the projection.
> Bitemporal topology foundations retain provider-generation identity, event and record time,
> complete snapshots, deltas, and tombstones. Pure `graph_at` and `topology_diff` functions preserve
> pinned `known_at` replay when late evidence arrives. Every replay batch must carry one consistent
> ontology release binding, and dangling links or missing or mixed releases lower completeness.
> The reviewed `runtime_calls` LinkType is included in the inventory topology projection contract,
> so authenticated caller-to-target edges retain exact Resource endpoints in current and historical
> views.
> Typed query handlers and verifier schemas expose these functions without provider text. A
> Core-owned migration creates append-only history tables with insert/read-only runtime grants.
> PostgreSQL reader/writer composition and inventory-promotion publishing remain.
> Metric semantics resolve exact reviewed concept ids to provider metrics, units, and aggregations
> without phrase aliases. Equal-duration windows distinguish observed zero from missing data.
> Bounded causal joins require complete metric and topology evidence, reuse the leakage-safe
> temporal analyzer, retain falsifiers and competing explanations, and grant no execution authority.
> Production provider bindings and catalog entries remain.
> Canonical releases now include typed function declarations. The function registry checks the
> caller agent, role, and purpose, derives replay-stable seeds for declared stochastic functions,
> and emits content-addressed invocation receipts pinned to the exact release.
> M5 adds the deterministic `query.network_path_segments` and `query.pod_telemetry_path`
> FunctionTypes plus the `routes_to` and reciprocal `peered_with` declarations. A bounded
> composition-owned issuer records secured ObjectSet results, and Function handlers resolve the
> exact dependency digest before invocation. The contextual callbacks bind caller role, singleton
> purpose, ontology release, and projected result digest to `FunctionInvocationContext`; an
> unissued or self-minted receipt is rejected. Evaluation time equals the receipt's
> trusted observation cutoff. Link effective, evidence, and recorded times cannot exceed that
> cutoff, and freshness is capped at one year before timestamp arithmetic. Reciprocal peering needs
> distinct direction-bound observation and verification receipt lineage; reusing one lineage for
> both directions leaves the segment unverified. Inventory projection also rejects link endpoint
> types that conflict with the observed `ResourceRecord.type`. Incomplete graphs return
> `query_incomplete`, and only relevant network links consume the segment bound. The FunctionType
> artifact digest is derived from module source, so behavior changes produce a new declaration
> identity. The function has no network, credential, provider, mutation, or execution path.
> Reconciliation now has a durable `StateStoreReconciliationLedger` in addition to the in-memory
> reference ledger. It stores every attempt under one reconciliation aggregate and uses atomic
> create or revision compare-and-set to commit a terminal outcome and its proposal-only outbox
> recommendation together. Strict replay validation rejects malformed or inconsistent durable
> state, and focused tests cover restart replay, concurrent delivery, conflict detection, and an
> unscorable-attempt-to-terminal transition. Each reconciliation stores at most eight attempts and
> reserves the final slot for terminal closure. A 16 MiB canonical aggregate ceiling rejects
> oversized durable state before a state or audit write. Production composition wires the worker
> and materializes immutable multi-effect lineage only after terminal independent reconciliation.
> Cross-source state adjudication compares one provider projection with independent telemetry while
> preserving each source's scope, cutoff, freshness, completeness, and provenance. It returns
> separate agreement, missing-telemetry, stale-projection, stale-telemetry, conflict, and censorship
> outcomes. Contested values are withheld rather than averaged, and every result fixes mutation and
> execution authority to false.
> K6-K8 target graph-wide Dynamic evidence: immutable operational state trajectories,
> dependency-scoped effect propagation, time-bounded invariants, and independently observed
> trajectory outcomes. Existing action/metric Dynamic simulation remains implemented; graph-wide
> propagation and failure-attribution wiring remain delivery work until their exit criteria pass.
>
> **Hardening status (2026-08-01):** Ten adversarial rounds covered release identity, persistence,
> interface compatibility, ObjectSet closure, mutation safety, function authority, projection,
> reconciliation, generated SDK syntax, and manifest disclosure. Verified Medium-or-higher core
> findings are fixed. PostgreSQL and runtime integration findings are also fixed; residual findings
> are Low. Round 12 rejected retroactive release assignment for legacy reads. Round 13 confirmed
> that a successful update creates and pins a newly validated current-state revision.

## Declaration workbench product boundary

The workbench uses object-centric inspection to connect an exact declaration to properties,
directional relationships, actions, dependents, evidence health, impact, and release compatibility.
`/ontology` registry search and Catalog topology remain the broad exploration surfaces. It excludes
visual schema editing, arbitrary release upload, raw instance tables, personalization, and kernel
icon metadata. Changes remain catalog-as-code pull requests; the Console never calculates
redaction, compatibility, completeness, or authority.

## Operational competency gates

The workbench is complete only when it answers these bounded operational questions honestly:

| Competency | Operator question | Required projection evidence |
|------------|-------------------|------------------------------|
| C1 - Identity and access | What exact declaration is this, and what may this principal see? | Release digest, declaration version and provenance, role/purpose filtering, and redaction reasons. |
| C2 - Relationships | How does this type connect to other types? | Recorded incoming, outgoing, or self direction, cardinality, causal/temporal flags, and provenance. |
| C3 - Dependents | Which catalog declarations depend on this type? | Deterministic topology references, a result bound, and explicit truncation. |
| C4 - Impact scope | Which active Resources are reachable from this exact target? | Active snapshot generation and cutoff, stored direction, depth/edge bounds, completeness, and edge verification state. |
| C5 - Evidence health | Is runtime evidence available, current, complete, conflicting, or synthetic? | Sanitized source alias, generation, cutoffs, freshness, conflicts, drop reasons, and nullable counts when unavailable. |
| C6 - Governed actions | Which actions are semantically bound to this declaration? | Exact ObjectType or InterfaceType target evidence and the complete ActionType safety contract, with no execute control. |
| C7 - Change safety | What changed between two retained releases? | Exact release digests, declaration-ref additions/changes/removals, compatibility verdict, migration requirement, and deterministic diff digest. |

## Implementation status

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| K0 exact release identity and persistence | implemented | [`release.py`](../../../services/core-control-plane/src/fdai/shared/ontology/release.py), [`postgres_ontology.py`](../../../services/core-control-plane/src/fdai/delivery/persistence/postgres_ontology.py), [`inventory_ontology.py`](../../../services/core-control-plane/src/fdai/runtime/inventory_ontology.py), [`20260813_0081_ontology_release_registry.py`](../../../alembic/versions/20260813_0081_ontology_release_registry.py), [`20260817_0085_historical_ontology_release.py`](../../../alembic/versions/20260817_0085_historical_ontology_release.py), and focused persistence/runtime tests. | Exact identity, pinned writes, restart-safe manifest loading, release-bound inventory projection evidence, and an exact historical object/link release backfill exist. Unregistered releases still fail closed. Pre-migration rows and historical inventory manifests remain honestly unpinned. Operational Live evidence is pending. |
| Versioned provider relationship materialization | implemented | `delivery/provider_schema_relationship_generation.py`; `delivery/provider_schema_relationship_review.py`; `delivery/provider_schema_relationship_ledger.py`; `core/ontology_platform/direction_shadow`; focused generation and direction-shadow tests | Provider-schema and REST evidence, recomputed review digest, every semantic mapping field, provider type@version identity, mapping revision, projection manifest, explicit direction/cardinality/link metadata, changed-subset invalidation, serialized rollback, replay, and exact-release comparison are bounded and content addressed. Candidate promotion remains proposal-only; graph and migration authority are false. |
| Inventory state-fact freshness and classification parity | implemented | `inventory_projection.py`; `inventory_ontology.py`; scheduled and local inventory composition; focused projection and wiring checks | Observed state facts declare the configured routine reconciliation guarantee instead of a shorter fixed shelf life. Scheduled and local projectors both receive reviewed ResourceType mapping digests. Exact-revision runtime evidence remains open. |
| OI-12 aggregate certification receipt | implemented | `operational_instance_certification*.py`; focused certification checks (`24 passed`); private local receipt `sha256:cc0581c6b0e139b2eaab5847e508fde6b9c4736d27bbd23a7e55fb248c906ead` | The exact-release PostgreSQL collector measured all seven axes, and the bounded local exercise persisted and restored one real mode-0600 rollup artifact through append-only archive evidence. The receipt reports measurement coverage rather than a pass verdict and fixes all authority fields to false. Protected deployed measurements and certification remain open. |
| Exact-release declaration workbench projections | implemented | `delivery/ontology_{declaration,dependents,evidence_health,release_diff}_projection.py`; local authoritative catalog materializer; Operator operations family; focused projection and route checks | ObjectType, LinkType, and ActionType details preserve exact release identity. Dependents come only from catalog topology, evidence health never fabricates zero, and retained release comparison stays at declaration-ref granularity with no mutation authority. Dedicated InterfaceType and FunctionType views remain deferred under the measured P2 entry conditions. |
| K1-K5 bounded semantic query and function infrastructure | in-progress | [`semantic_planning_frame.py`](../../../services/core-control-plane/src/fdai/core/conversation/semantic_planning_frame.py), [`operational_functions.py`](../../../services/core-control-plane/src/fdai/core/ontology_platform/operational_functions.py), [`incident_queries.py`](../../../services/core-control-plane/src/fdai/core/ontology_platform/incident_queries.py), [`kubernetes_api_inventory.py`](../../../services/core-control-plane/src/fdai/delivery/kubernetes_api_inventory.py), [`kubernetes_inventory.py`](../../../services/core-control-plane/src/fdai/delivery/kubernetes_inventory.py), [`test_inventory_sync.py`](../../../services/core-control-plane/tests/delivery/test_inventory_sync.py), and [`test_wire_pod_telemetry.py`](../../../services/core-control-plane/tests/composition/test_wire_pod_telemetry.py) | Core primitives, bounded incident evidence, UID-grounded Kubernetes API collection, atomic runtime enrichment, and issued Pod composition checks exist. The Incident query may expose a root cause only from grounded evidence. Kubernetes links remain independently verified and grant no execution authority. Authenticated incident and Kubernetes live evidence remain open. |
| Kubernetes workload evidence queries | validated | Rollout, Pod recovery, and Resource event-history FunctionTypes; live and durable readers; leased lifecycle collector; PostgreSQL cursor and observation store; focused and authenticated receipts | Exact targets still require one secured Resource and matching immutable UID and cluster. The durable source now preserves opaque resume progress, typed observations, explicit gaps, and bounded query coverage without Event messages or ontology writes. The local merged migration head, sequence-5 live cursor, complete 60-second durable read, HTTP 200 Event source, and exact UID live rows validate the implemented path. Deployed retention and cause/recovery joins remain separate evidence work. |
| Exact-target health evidence FunctionType | validated | `semantic_health_planning.py`; `resource_health_assessment_queries.py`; `query_source_handlers.py`; production semantic composition, focused checks, and authenticated Console receipt | A source-derived deterministic FunctionType joins exact current state, bounded activity, and reviewed metric windows. Its derived state can only report evidence sufficiency, lifecycle, unresolved readiness and application health, stability, resource pressure, freshness, and gaps. It cannot assert external truth, hide incomplete evidence, or grant execution authority. The post-restart same-question run completed all seven nodes and retained every unavailable source as a gap. |
| Exact-target error/activity correlation FunctionType | validated | `semantic_error_activity_planning.py`; `resource_error_activity_correlation_queries.py`; production semantic composition, focused checks, and authenticated Console receipt | A source-derived deterministic FunctionType joins two contiguous equal-duration request-error windows with exact-target Activity Log evidence. The derived state distinguishes increase, decrease, unchanged, and unavailable; it also distinguishes verified zero activity from unavailable activity. Same-window co-occurrence remains non-causal, incomplete evidence keeps correlation unproven, and every row fixes `execution_authority=false`. |
| Exact-target metric-series FunctionType | validated | `resource_metric_queries.py`; `semantic_resource_metric_planning.py`; `wire_semantic_query.py`; focused checks; authenticated standard-port Console receipt | `query.resource_metric_series` accepted one secured exact Resource, one reviewed metric concept, and one bounded window. It returned 20/20 ordered endpoint and min/max envelope observations from 1085 source samples with complete evidence and `display_truncated=false`. The FunctionType used no network or credentials, fixed `execution_authority=false`, and remained separate from the validated aggregate FunctionType. |
| Dependency-wave investigation query nodes | implemented | `query_source_handlers.py`; `query_metric_handlers.py`; `query_verification.py`; focused investigation query-node tests | An exact secured ObjectSet result can supply the root of one endpoint-checked multi-hop traversal. Equal-duration metric comparison distinguishes missing evidence from zero, and an investigation evidence join cannot support a hypothesis unless the requested symptom direction is observed. Ambiguous or incomplete roots stop before provider or graph I/O. |
| Exact-release principal manifest function | implemented | [`manifest_queries.py`](../../../services/core-control-plane/src/fdai/core/ontology_platform/manifest_queries.py), [`query_source_handlers.py`](../../../services/core-control-plane/src/fdai/core/ontology_platform/query_source_handlers.py), and focused manifest and composition checks (`42 passed`) | `query.manifest` lists bounded readable declaration summaries by role, purpose, and requested kind. Unbound declarations lower completeness, invocation receipts remain exact-release evidence, and every row fixes `execution_authority=false`. |
| Continuous question-space capability bridge | implemented | [Continuous Question Space](../interfaces/continuous-question-space.md); `declaration_queries.py`; `release_diff_queries.py`; `evidence_health_queries.py`; `inventory_impact_queries.py`; focused capability and composition checks | Four source-derived FunctionTypes enter the exact release. Only handlers with exact retained providers or a server-owned target are planner-visible; unavailable functions remain typed accounting and grant no authority. |
| Catalog projection and exact-generation Rule retrieval | implemented | [`catalog_queries.py`](../../../services/core-control-plane/src/fdai/core/ontology_platform/catalog_queries.py), [`test_catalog_queries.py`](../../../services/core-control-plane/tests/core/ontology_platform/test_catalog_queries.py), commit `e4d9483a5` | `catalog.search_rules` returns bounded ranked candidates with an exact-generation receipt and grants no judgment or action authority. Control-objective instances are not yet materialized by startup projection. |
| Historical topology, metric semantics, and reconciliation | in-progress | [`topology_history.py`](../../../services/core-control-plane/src/fdai/core/ontology_platform/topology_history.py), [`metric_semantics.py`](../../../services/core-control-plane/src/fdai/core/ontology_platform/metric_semantics.py), [`reconciliation_state_store.py`](../../../services/core-control-plane/src/fdai/core/ontology_platform/reconciliation_state_store.py) | Contracts and pure or durable foundations exist; production composition and publishers remain incomplete. |
| Capability Interfaces and scoped SDK artifacts | implemented | `interface-types/`; `interface-implementations/`; `sdk_codegen.py`; `ontology_sdk_artifact.py`; focused catalog, ObjectSet, SDK, and artifact checks | Six capability Interfaces use exact conservative bindings. SDK artifacts are content-addressed, scope metadata is explicit, writes remain proposal-only, and breaking removals require a migration reference. |
| Evidence-bound scenario branch | implemented | `scenario_branch.py`; `evidence_read.py`; focused evidence and scenario checks | Copy-on-write overlays validate against one exact base and evidence-bundle digest in memory. Results fix production write, mutation, and execution authority to false and require governed promotion outside this API. |
| K6-K8 graph-wide Dynamic evidence | in-progress | [Dynamic model maturity](#dynamic-model-maturity) | Action and metric simulation exists; graph propagation, trajectory closure, and failure attribution remain open. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-08-27 | validated | Applied the merged Kubernetes lifecycle schema to a rebuilt isolated validation database and retained five consecutive authenticated seed/watch checkpoints. A PostgreSQL integration test also proves lease reuse, duplicate observation idempotency, and stale sequence rejection. | `current change`; migration contracts (`60 passed`); lifecycle PostgreSQL integration (`1 passed`); live cursor sequence 5 and complete 60-second durable read | Preserve a deployed retained window before claiming production validation; join replacement and recovery evidence under issue #291. |
| 2026-08-27 | in-progress | Added typed Kubernetes lifecycle observations, a leased opaque cursor, bounded bookmark watches, atomic PostgreSQL append and cursor progress, and an exact-scope durable Resource Event reader. Provider message text is never persisted and the collector has no ontology write path. | `current change`; lifecycle/Event cohort (`76 passed`); service-migration contracts (`60 passed`); Ruff, formatter, and strict mypy passed; authenticated Event API and exact UID read succeeded | Apply the migration after resolving the validation schema fingerprint and competing untracked migration head, then accumulate enough uninterrupted coverage to validate historical absence. |
| 2026-08-27 | implemented | Replaced per-id ontology store reads with bounded exact-id batch queries and early result-limit closure. A 512-id contextual selection now uses at most four indexed store queries instead of hundreds of new database connections. | `current change`; ObjectSet, predicate, and PostgreSQL instance-store checks (`31 passed`, `4 skipped` because `FDAI_DATABASE_URL` was unset); Ruff and strict mypy. | Retain deployed database latency and connection-pressure evidence separately; no remote database was queried. |
| 2026-08-27 | implemented | Kept exact-id batches object-only so they do not inherit relationship completeness, and carried the opaque selection token as a scalar Function input so the object-valued result remains dependency-only. | `current change`; contextual Function, ObjectSet, dependency-input, and semantic-planning checks (`123 passed`); Ruff and strict mypy. PostgreSQL runtime evidence remains environment-gated. | Retain deployed database latency and connection-pressure evidence separately; no remote database was queried. |
| 2026-08-27 | implemented | Scoped incomplete-output holding to contextual resource plans so ordinary bounded queries still return explicit truncated results. | `current change`; focused contextual and non-contextual semantic runtime checks (`108 passed`); Ruff and strict mypy. | Retain authenticated runtime presentation evidence separately. |
| 2026-08-27 | implemented | Recomputed each server-resolved screen or resource-group selection digest at the Operator boundary before emitting the semantic request. A mismatched registered identity now fails before cross-service transport. | `current change`; focused exact-screen, tampered-digest, and 512-id Operator envelope checks (`3 passed`); Ruff and strict mypy. | Retain authenticated runtime transport evidence separately. |
| 2026-08-27 | implemented | Changed Resource Event answer projection to retain the newest bounded rows and disclose display truncation. The bilingual answer reports eight displayed rows out of the source total and keeps those latest rows in chronological order. | `current change`; focused Resource Event answer checks (`3 passed`); Ruff and formatter passed | Retain one authenticated answer with Event rows after runtime source access is restored. Durable Event history remains open. |
| 2026-08-27 | implemented | Added pure authority-free projections for positive Forecast episodes and balanced Pattern candidates, preserving exact source identity and no mutation or execution authority. | `current change`; `core/ontology_platform/detection_projection.py`; focused producer checks (`11 passed`). | Keep relationship restoration deferred until exact objective and outcome endpoint producers exist. |
| 2026-08-27 | implemented | Added a distinct-provider adjudication helper alongside the existing projected-state-versus-telemetry shadow reducer. Both paths withhold contested values and retain explicit conflict evidence without authority increase. | `current change`; `observation_adjudication.py`; focused adjudication and shadow checks (`37 passed`). | Keep any non-read-path conflict carrier behind a separate authority design. |
| 2026-08-27 | implemented | Added idempotent persistence methods for source-derived Forecast and Pattern ontology objects over the existing instance-store seam. | `current change`; `detection_projection.py`; focused projection checks (`4 passed`). | Bind production composition before claiming deployed evidence. |
| 2026-08-27 | implemented | Tightened distinct-provider adjudication to reject absent or whitespace-only provider identities before any comparison. | `current change`; provider identity regression checks (`38 passed`). | Keep non-read-path conflict carriage deferred. |
| 2026-08-27 | implemented | Bound principal-scoped operational evidence reads to receipt-verified Context metadata. The existing bounded read response now preserves the requesting principal and rejects mismatched or incomplete Context evidence without mutation or execution authority. | `current change`; focused operational-context and scenario-branch checks (`14 passed`). | Retain authenticated runtime evidence separately. |
| 2026-08-27 | implemented | Hardened the same read path with authenticated principal-scope receipt binding, digest verification, exact object type/revision/temporal/path checks, and canonical JSON validation. Detection projections gained atomic create, producer attestation, active-episode, and sealed-cohort validation. | `current change`; focused Context, gateway, detection, and store checks. | Retain authenticated deployed receipts and production composition evidence. |
| 2026-08-27 | implemented | Added a PostgreSQL-backed atomic-create concurrency regression for ontology projection identities. | `current change`; `tests/persistence/test_postgres_ontology_instance.py` and focused store checks. | Retain a successful local PostgreSQL receipt. |
| 2026-08-27 | implemented | Closed the remaining Context response boundary gaps. Presentation now authenticates receipt issuance, matches each path link's complete observation and verification metadata instead of endpoint triples alone, and applies the configured byte ceiling to the bundle plus Context metadata. | `current change`; `console_projection.py`, `evidence_read.py`, and focused operational-context and scenario checks (`17 passed`). | Retain one authenticated runtime response separately; no live or deployed evidence was produced. |
| 2026-08-27 | implemented | Added bounded versioned provider relationship materialization and exact-release direction-shadow checks. The existing Kubernetes API inventory is sufficient as the authoritative topology adapter; lifecycle observations remain a distinct Event source and are not reused as topology. | `current change`; `delivery/provider_schema_relationship_generation.py`; focused generation and direction-shadow tests (`22 passed`); Ruff, formatter, and strict mypy. | Capture complete release-bound real-generation evidence and governed review; no live or remote generation was fabricated. |
| 2026-08-27 | implemented | Hardened provider relationship materialization after independent review by validating all reviewed semantic fields, recomputing review digests and candidate endpoints, preserving type@version identities and exact-release replay mode, and serializing ledger record/rollback with unique staging files. | `current change`; generation, review, ledger, and direction-shadow modules; focused adversarial tests (`35 passed`); Ruff, formatter, and strict mypy. | Capture complete release-bound real-generation evidence and governed review; no live or remote generation was fabricated. |
| 2026-08-27 | implemented | Closed the remaining review gaps by propagating unresolved and source-less ARM references into incomplete generations, globally sorting candidate version unions, and enforcing proposal-only authority literals at runtime. | `current change`; generation, direction-shadow, promotion, and focused adversarial tests (`38 passed`); Ruff, formatter, and strict mypy. | Capture complete release-bound real-generation evidence and governed review; no live or remote generation was fabricated. |
| 2026-08-27 | implemented | Made the Event Function reject an exact identity predicate that resolves to zero or multiple Resources. The provider receives no request and the result stays incomplete as `target_resolution_not_exact`; complete broad-scope empty results retain their existing meaning. | `current change`; focused Resource Event FunctionType regression checks | Restore the runtime Kubernetes Event source and retain one authenticated exact-target provider receipt. Durable history remains required before zero rows can prove historical absence. |
| 2026-08-27 | implemented | Bound one source-grounded exact target into the Event plan and projected Event rows and limitations through a dedicated bilingual read-only answer. Ambiguous same-name Resources remain incomplete unless reviewed type scope also narrows them; no name creates authority or bypasses the secured ObjectSet. | `current change`; focused Event vertical cohort (`287 passed`), Ruff, formatter, and strict mypy. Authenticated candidate selection plus exact-target follow-up completed the two-node Function plan with 8/8 evidence checks and rendered `source_unavailable`, source incompleteness, and no execution authority. | Restore the runtime Kubernetes Event source, retain one successful identity-aware provider receipt, and add durable history before treating provider TTL as retained coverage. |
| 2026-08-27 | implemented | Narrowed exact-child Kubernetes Event reads through an additive identity-aware reader capability. The Function derives only `cluster_ref` and `uid` from the secured projection, freezes both map levels, and preserves legacy DI readers. The Kubernetes adapter accepts a child selector only when the immutable UID reproduces the exact Resource id. | `current change`; focused FunctionType, legacy reader, composite propagation, selector, forged identity, Azure, and Kubernetes checks (`27 passed`); Ruff, formatter, and strict mypy passed. | Retain authenticated exact-child Console evidence and add durable history before treating provider TTL as retained coverage. |
| 2026-08-26 | implemented | Bound `resource_event.kubernetes` through the existing exact-release Resource event-history FunctionType. One family router keeps Azure and Kubernetes reads independent, while the Kubernetes adapter enforces exact endpoint, CA, authentication, cluster, UID, lookback, raw-byte, item, continuation, and timestamp bounds. Deleted-object events remain queryable only through the exact selected cluster. | `current change`; Resource event FunctionType, Kubernetes and composite readers, runtime composition, shared UID identity helper, focused adapter, router, semantic-planning, composition, and runtime checks; exact typed duration alignment, mixed-scope retention, encoded-response rejection, and raw 256 KiB bounds are covered. Authenticated exact-cluster Console execution selected `server_resource_event_history` and completed its ObjectSet and Function nodes with 8/8 evidence checks in 6.8 seconds with no execution authority. Its zero rows did not prove historical absence; the hardened adapter reports `source_retention_unverified`. | Add durable history before treating provider TTL as retained coverage, then join replacement and impact evidence before any Pod cause or recovery claim. |
| 2026-08-26 | implemented | Replaced the generic verified-row count for exact-target current state with a bilingual evidence-bound answer. The projection now emits normalized provisioning and runtime status, canonical state-fact time, a deterministic exact-target lifecycle assessment, and an explicit `exact_target_only` scope. The answer separates the named target from related nodes, workloads, and resources: it can report that no abnormal provider lifecycle state was observed for the target while refusing to turn unqueried related resources into a false zero-abnormality claim. | `current change`; exact current-state adapter and terminal renderer; focused adapter and processor cohort (`97 passed`); broader processor, assurance, and Azure delivery cohort (`944 passed`); Ruff, formatter, and strict mypy passed; authenticated Console returned `Succeeded`, `Running`, 4/4 supported claims, 8/8 evidence checks, an open five-event investigation timeline, and the explicit related-resource limitation in 7.0 seconds. | Add a cluster-scoped runtime topology capability before claiming the health or absence of abnormal nodes and workloads. The current local runtime inventory covers `aks-fdai-sre-lab-krc`, not `aks-fdai-chaos`. |
| 2026-08-26 | implemented | Resolved a stated exact Resource identity for every output family instead of only exact current state. A frame that named a single grounded runtime identifier still reported `resource_identity` unresolved for event-history and health-list families, so the turn asked the operator for a target the utterance already named and no repetition could satisfy it. The resolution is server-owned and fails closed: it applies only when `resource_identity` is the sole clarification requirement and unresolved term, the subject is Resource-only, and exactly one grounded identifier is present. | `current change`; `semantic_target_candidate_planning.py`; six focused cases pinning the resolution and the four hold conditions (unnamed target, two stated targets, an extra unresolved term, a broader requirement, and a non-Resource subject); conversation cohort (`1100 passed`); Ruff, formatter, and strict mypy passed; the live event-history and health-list turns stopped asking for an already-named cluster. | Both families now reach an honest `semantic_request_unsupported` because no verified capability serves Kubernetes node and workload readiness or a joined Resource Health plus Pod restart history read. Add those capabilities before either question can answer. |
| 2026-08-26 | implemented | Marked every object-valued FunctionType input as `x-fdai-dependency-only`. These inputs carry gateway-secured ObjectSet results and derived evidence bundles, but only `query.vm_process_cpu_evidence` declared the marker, so the plan verifier accepted a proposed plan that supplied a model-authored literal in place of secured evidence. A resource event-history turn reproduced this as an opaque `capability_failed` receipt; it now fails closed during plan verification instead. | `current change`; new `test_function_dependency_inputs.py` contract guard over every operational FunctionType; focused ontology-platform and persistence cohort (`12 passed`); Ruff, formatter, and strict mypy passed; the live event-history turn moved from `capability_failed` to an honest clarification. | Bind a server-owned deterministic plan for resource event history so the turn answers instead of asking for a target that the utterance already names. |
| 2026-08-26 | implemented | Separated relationship coverage from object coverage when reducing inventory projection state into a secured ObjectSet receipt. A Resource snapshot inherited the whole generation's relationship coverage, so classified non-edges elsewhere held every exact single-resource current-state answer as `authoritative_evidence_unavailable`. Relationship coverage now gates a snapshot only when its object set admits an intra-set edge; object coverage still gates every snapshot, and traversal keeps the strict rule. | `current change`; `postgres_ontology.py`; four focused coverage-reducer cases including the object-gap and relationship-gap mutations; the authenticated Console answered the exact-cluster current-state question as `Verified` with 3/3 supported claims and 6/6 evidence in 11.7 s. | Report the returned current-state fields in the rendered answer instead of the generic verified-row count. |
| 2026-08-25 | implemented | Extended `query.kubernetes_pod_recovery_evidence` to join issued exact-Pod, ReplicaSet-owner, and Deployment-owner receipts with a reviewed 30-minute `pod.restart.history` window. The five-node server plan verifies all dependency identities and ownership-link evidence, while recovery requires a positive bounded delta plus fully ready and available owner replicas. Dependency-only inputs reject static model arguments. | `current change`; focused metric, verifier, reducer, receipt authentication, semantic planner, and production-composition cohort (`49 passed`); semantic routing regression (`370 passed`); Ruff, formatter, and strict mypy passed. | Add retained Kubernetes event/change, replacement-UID, impact, and new-cutoff evidence, then verify the recovery turn through the authenticated Console. |
| 2026-08-25 | implemented | Added a stable secured-query limitation for source-incomplete, non-truncated ObjectSet results. This keeps zero-row target candidate reads executable and evidence-bearing without converting incomplete graph coverage into absence. | `current change`; `query_source_handlers.py`; focused rollout and incomplete-source cohort (`19 passed`); authenticated targetless Console turn completed verification with `source_incomplete` and no execution authority. | Retain exact-target rollout and independent recovery evidence from a complete Kubernetes generation. |
| 2026-08-25 | implemented | Bound the rollout reducer through `query.kubernetes_rollout_evidence` and a server-owned exact-target plan. Core performs two explicit non-transitive `kubernetes_owned_by` hops, authenticates all three issued secured results, preserves immediate dependency identity across receipt lineage, and invokes no model-authored plan or provider API. | `current change`; focused reducer, receipt-authority, traversal, planner, and production-composition checks passed 15 cases; task-scoped Ruff and strict mypy passed. | Restart Core and retain authenticated targetless candidate selection plus exact-target rollout evidence. Recovery-effect verification remains separate and open. |
| 2026-08-25 | implemented | Corrected the OI-12 scope state from the unsupported label `validated locally` to `implemented`. Focused checks and a private local exercise prove implementation but do not replace the open protected deployed measurements. | Existing OI-12 source, 24 focused checks, and the private local receipt cited in the scope row. | Retain protected deployed measurements before raising the bounded scope to `validated`. |
| 2026-08-25 | implemented | Added a pure Kubernetes Deployment rollout evidence reducer over typed observed-state metadata. It preserves replica counts and Pod blockage signals, rejects cross-target Pods, lowers stale and conflicting evidence, and fixes both cause and execution authority to false. | `current change`; `kubernetes_rollout_evidence.py`; focused reducer checks passed 5 cases. | Bind the reducer through an issued exact-release FunctionType and the structured investigation plan, then retain authenticated question and recovery evidence. |
| 2026-08-22 | validated | Validated the source-derived exact-target metric-series FunctionType through the authenticated semantic path after normalizing the remaining non-causal T1 frame variants. | `current change`; four focused aggregate/series isolation checks, Ruff, and strict mypy passed; the authenticated Console completed 2/2 nodes and 8/8 evidence checks, reported 20 returned and total rows, and retained `sampling_strategy=min_max_envelope_v1`, `source_sample_count=1085`, and `display_truncated=false`. | Broader production metric-provider assurance remains open outside this exact-target FunctionType validation. |
| 2026-08-22 | implemented | Added a source-derived exact-target metric-series FunctionType and bound it atomically with the existing metric registry and provider. The bounded table is a presentation input only and cannot assert a provider fact when the source window or target identity is incomplete. | `current change`; focused metric, semantic-planning, composition, prompt, and presentation checks passed 43 cases. | Retain authenticated Console evidence after restarting the standard local services; broader production metric-provider evidence remains open. |
| 2026-08-21 | validated | Added an exact-target error/activity correlation query profile and FunctionType so a bounded operational comparison reaches the existing Azure metric and Activity Log providers instead of stopping at generic evidence unavailability. The five-node plan is server-owned, model plans cannot substitute another output, and the reducer never promotes co-occurrence to cause. | `current change`; 218 focused tests, static gate stack, and authenticated same-question Console receipt with 5/5 nodes, 11/11 evidence checks, six sources, 5.8 seconds, and `execution_authority=false`. | Add an authoritative `request.errors` provider route for Container Apps. The current direct Metrics catalog does not map `http.server.request.error.count`; the runtime therefore reports the metric unavailable while preserving verified Activity Log zero. |
| 2026-08-21 | validated | Added the exact-target health evidence FunctionType and server-owned query profile after a broad ObjectSet answer substituted for the requested health judgment. The reducer preserves observed lifecycle separately, marks readiness and application health unproven without their own evidence, and treats zero requests and CPU samples as bounded facts rather than a healthy verdict. | `current change`; focused function schema, dataclass dependency normalization, seven-node plan verification, fail-closed reduction, and presentation checks; authenticated same-question Console receipt completed 7/7 nodes and 13/13 evidence checks in 6.7 seconds. | Process restart, runtime log, memory, dependency, and successful-work sources remain explicit gaps until authoritative readers are bound. |
| 2026-08-20 | implemented | Bound observed-state freshness to the configured routine inventory cadence and restored ResourceType mapping digests in the local authoritative refresh. A slow advancing scan now emits evidence-free shard heartbeats, while the final fence remains the only completeness claim. | [Issue #139](https://github.com/dotnetpower/fdai/issues/139); current projection, runtime, adapter, local-refresh, and focused regression checks. | Retain one exact-revision live projection showing current freshness metadata and classification links after a provider change. |
| 2026-08-19 | implemented | Added the four read-only question-space FunctionType contracts and kept provider- or anchor-dependent handlers unavailable to the planner until exact composition exists. | [Issue #233](https://github.com/dotnetpower/fdai/issues/233); [Continuous Question Space](../interfaces/continuous-question-space.md); focused ontology-platform and composition checks. | Retain exact-source live evidence before changing any capability from unavailable to bound. |
| 2026-08-20 | implemented | Added dependency-bound relationship traversal, reviewed metric comparison, stable branch holds, and symptom-gated causal joins to the closed query algebra. Production composition reuses the secured ObjectSet gateway, reviewed metric registry, topology history, and existing bounded executor. | `current change`; focused investigation gate passed 97 cases; Ruff, formatting, and strict mypy passed. | Retain authenticated evidence over authoritative service topology and metric providers before changing the row to `validated`. |
| 2026-08-19 | implemented | Added the catalog-owned `unclassified-resource` target and exact identity-completeness receipt for provider-native rows outside reviewed mappings. Classification remains a reviewed Resource-to-ResourceType edge, while unsupported native type text stays inert evidence and grants no semantic or execution authority. | [Issue #217](https://github.com/dotnetpower/fdai/issues/217); focused provider, Azure, ontology, catalog, and query-domain checks pass 259 cases; Ruff and strict mypy pass. | Refresh inventory and retain the release-bound manifest and parity evidence. |
| 2026-08-19 | implemented | Added role- and purpose-filtered declaration details, topology-backed dependents, sanitized ObjectType evidence health, and declaration-ref release compatibility as separate no-authority projections. The local authenticated Console rendered both unavailable `Decision` evidence and available aggregate `Resource` evidence without exposing raw provider payloads or resource ids. | [Issue #223](https://github.com/dotnetpower/fdai/issues/223); `current change`; focused Core delivery, materializer, Operator and Console checks plus Console production build. | Retain a governed Browser artifact and principal-scoped Context receipt. Do not add dedicated InterfaceType or FunctionType views until the P2 entry conditions are measured. |
| 2026-08-19 | implemented | Integrated the ontology enhancement plan's product boundary, C1-C7 competency gates, delivery dependencies, and stop conditions into the existing platform, wire-contract, and code-map owners. | [Issue #223](https://github.com/dotnetpower/fdai/issues/223); `current change`; paired documentation, route-contract, and roadmap tracking gates. | Keep governed Browser retention and the principal-scoped Context receipt as separate validation evidence. |
| 2026-08-13 | in-progress | Adopted the implementation ledger without reconstructing earlier provenance. | Current source and tests listed in the scope table. | Complete the observable exit conditions below. |
| 2026-08-13 | implemented | Added exact-generation, read-only `catalog.search_rules` candidate retrieval with bounded ranking and content-addressed receipts. | Commit `e4d9483a5`; focused `test_catalog_queries.py` reports 2 passed. | Compose objective-aware retrieval and validate it without granting evaluation or execution authority. |
| 2026-08-13 | implemented | Registered the three objective vocabulary types as `Identifiable` implementations after centralized graph validation exposed the omission. | Focused `test_shipped_ontology_catalog_loads_as_one_graph` reports 1 passed. | Keep interface implementation coverage synchronized with every new object type. |
| 2026-08-24 | implemented | Added six competency-driven capability Interfaces, deterministic scoped SDK publication, evidence-bound copy-on-write scenarios, and terminal reconciliation lineage. | `current change`; focused interface, SDK, evidence, scenario, reconciliation, and runtime checks; at least ten adversarial hardening lenses left no verified unresolved finding above Low. | Retain deployment evidence separately; this batch adds no direct graph merge or executor surface. |
| 2026-08-24 | implemented | Repeated twelve adversarial lenses against the current runtime and corrected three Medium integrity gaps: missing per-effect metrics no longer score lineage, projection-before-claim interruption replays without another graph write, and one fresh Resource cannot hide missing freshness metadata on another returned Resource. | `current change`; focused lineage (`2 passed`), continuous worker (`8 passed`), and graph refresh (`5 passed`) checks. | Run the final Python 3.12, Ruff, strict typecheck, SDK compile, documentation, translation, audit, diff, and diagnostics gates. |
| 2026-08-24 | implemented | Completed the final local ontology gate stack and repeated thirteen adversarial lenses with no unresolved Critical, High, or Medium finding. | `current change`; Python 3.12 focused ontology checks (`260 passed`, `23 skipped` only because `FDAI_DATABASE_URL` was unset), Operator checks (`87 passed`), Console model checks (`17 passed`), TypeScript SDK compile, Ruff (`29 files`), strict mypy (`15 source files`), translation, design-impact, machine audit, scoped roadmap, diff, and zero editor diagnostics. | Retain external telemetry, authenticated Browser, PostgreSQL integration, deployment, and Azure certification as separate evidence; the repository-wide roadmap checker remains blocked only by the unrelated untracked FinOps owner ledger. |
| 2026-08-24 | implemented | Corrected ObjectSet link-redaction accounting so retained typed observation metadata is not reported as removed. The receipt now derives link counts from the exact source-to-projection property difference. | `current change`; `query_gateway.py` and focused query-gateway tests; 111 ontology, catalog, facade, and service-contract checks passed; Ruff and strict mypy passed. | Keep authenticated runtime and provider evidence as separate validation work. The corrected receipt remains read-only evidence. |
| 2026-08-13 | implemented | Added a durable exact-release manifest registry and loaded registered releases before PostgreSQL row decoding. | Current change; focused `test_postgres_ontology_catalog.py` reports 2 passed and `test_ontology_release_registry_migration.py` reports 1 passed. | Record authenticated Live evidence after migration and Core restart. |
| 2026-08-13 | in-progress | Added reviewed Kubernetes Service relationship mappings and a bounded projector that emits candidate links for independent generation verification. | `current change`; focused `test_kubernetes_relationships.py` reports 6 passed and the provider mapping contract reports 6 passed. | Bind the projector to a production inventory source and retain exact-release composition evidence. |
| 2026-08-13 | in-progress | Proved the issued Pod telemetry function through production semantic-query composition with a release-pinned Interface spanning Resource and Observation evidence. | `current change`; focused `test_wire_pod_telemetry.py` reports 2 passed for verified and synthetic-unverified paths. | Execute the same composition over retained production inventory and preserve authenticated assurance receipts. |
| 2026-08-14 | implemented | Required the inventory ontology projector to retain one exact release digest across its result, durable manifest, and availability status. The inventory job now shares the same catalog digest with topology-history publishing. | `current change`; focused `test_inventory_ontology.py` reports 9 passed. | Refresh production inventory and preserve the resulting release-bound projection evidence. Historical unbound manifests remain unmodified. |
| 2026-08-14 | in-progress | Extended direction-shadow comparison to preserve an explicitly unknown historical release and force `review_required` without granting migration authority. | `current change`; focused direction-shadow suite reports 8 passed; retained receipt `sha256:ad64c267b6f0c6ac5a1a037067f926aa5613f1fe5a84702877eb607e368736f6` replays identically. | Review the measured differences and capture complete verified aligned-generation evidence before migration. |
| 2026-08-14 | implemented | Composed the reviewed Kubernetes relationship projector into promoted inventory observations and injected the shipped mapping catalog in both scheduled and local inventory jobs. | `current change`; focused inventory composition and caller checks report 3 passed. | Bind an authoritative Kubernetes inventory source and retain complete-generation Pod evidence. |
| 2026-08-24 | implemented | Bound a credential-free, TLS-verified Kubernetes API source as sequential pre-promotion enrichment. The source keeps one exact cluster identity, immutable UID ownership, namespace scope, scheduling, and bounded pagination; the single writer stages added resources and verified links atomically. | `current change`; focused Azure, Kubernetes, inventory, catalog, and composition checks passed 260 cases; Ruff passed; strict mypy passed for 10 source files. | Retain a complete live Kubernetes generation and exact-release Pod telemetry receipt before changing this path to `validated`. |
| 2026-08-14 | implemented | Added exact-release Incident ObjectSet and audit-evidence querying plus deterministic answer projection that rejects cause-bearing results and exposes only evidence gaps and a candidate-only action draft next step. | Commits `285341732` and `43fa6ab13` plus `current change`; focused Incident and composition checks passed 62 cases, and the processor suite passed 34 cases; task-scoped Ruff and strict mypy passed. | Restart the local stack and retain authenticated Console evidence for the visible incident conversation. |
| 2026-08-14 | in-progress | Corrected the incident FunctionType identity contract so canonical `incident_id` and audit `correlation_id` remain distinct through verified plan execution and evidence projection. | `current change`; focused Incident and composition checks passed 63 cases with an end-to-end distinct-identity regression. | Restart the local stack and verify the visible authenticated incident conversation before changing the capability state. |
| 2026-08-14 | in-progress | Aligned semantic prompt v2 with the FunctionType identity contract so a bound incident plan carries both canonical and audit correlation identities without conflation. | `current change`; the focused prompt registry contract passed 5 cases. | Restart the local stack and verify the visible authenticated incident conversation before changing the capability state. |
| 2026-08-14 | implemented | Versioned the semantic frame and plan prompts to v2 after authenticated Browser evidence showed the model still treated incident answer fields as unresolved and the plan prompt omitted function nodes. The v2 prompts select the exact bound Incident function, preserve no-cause limitations, and permit only the reviewed function-node envelope. | `current change`; focused prompt registry checks passed 5 cases. | Restart Core with prompt v2 and rerun the authenticated incident conversation. |
| 2026-08-14 | implemented | Versioned the semantic frame and plan prompts to v3 after the next authenticated Browser run exposed a plan envelope missing the distinct audit correlation identity. The v3 prompts preserve canonical `incident_id` and audit `correlation_id` separately while retaining the v2 no-cause and candidate-only authority limits. | `current change`; focused distinct-identity processor and prompt checks passed 7 cases. | Restart Core with prompt v3 and rerun the authenticated incident conversation. |
| 2026-08-14 | implemented | Completed the authenticated Browser rerun against prompt v3. The visible answer preserved distinct Incident and audit correlation identities, reported causal analysis as unavailable, exposed bounded evidence gaps, and returned only a candidate `action_draft` with no execution authority. | Local Console `/agent-activity` at 02:28:52 KST; verification completed against one evidence reference; Core recorded all five semantic planning stages with no plan rejection. | Retain A1-A3 in shadow mode and use the captured turn as local evidence; causal analysis remains separate future work. |
| 2026-08-14 | in-progress | Reopened the incident semantic evidence path after the current prompt and assurance changes replaced the retained v3 runtime claim. | `current change`; focused prompt, Console assurance, and ontology-query checks. | Rerun the authenticated incident path and retain a new governed artifact before restoring validation. |
| 2026-08-15 | implemented | Versioned the semantic frame prompt to v4 and added typed clarification requirements. Principal scope and purpose are trusted server-bound inputs, so a T1 proposal that requests either is deterministically rejected before one bounded T2 frame retry. Legitimate missing user context remains a T1 clarification with no T2 call. | `current change`; focused tier-routing, planner, prompt, and Azure adapter checks passed 31 cases; task-scoped Ruff and strict mypy passed. | Restart Core after central validation and retain replacement authenticated assurance evidence. |
| 2026-08-15 | implemented | Versioned the semantic frame prompt to v5 and the plan prompt to v4. The frame treats visible/current objects as the principal-scoped collection, rejects schema-relationship over-selection for instance operations, and preserves explicit comparison baselines. The plan maps collection, filter, aggregate, topology, metric, and causal operations to the closed verified node grammar and uses the server-bound evaluation time for current cutoffs. | `current change`; focused prompt registry and Azure adapter checks passed 10 cases. | Restart Core after central validation and rerun the strict bilingual answer-coverage probe; keep unsupported exact identities as clarification or hold. |
| 2026-08-15 | implemented | Added `query.manifest` as a deterministic exact-release FunctionType and reused generic function receipts plus `QueryTable` projection for schema inventory answers. | `current change`; focused manifest, handler, composition, relationship, semantic composition, and prompt checks passed 42 cases; task-scoped Ruff and strict mypy passed. | Retain clean bilingual 14-cell and seeded 100-case Browser evidence before changing production assurance. |
| 2026-08-15 | implemented | Moved direct ObjectSet aggregate-field rejection into deterministic plan verification so invalid T1 candidates can retry only the plan stage before I/O. | `current change`; focused verifier and tier-routing checks passed 16 cases; task-scoped Ruff and strict mypy passed. | Rerun the held Korean aggregation cell before the clean 14-cell and seeded 100-case Browser gates. |
| 2026-08-15 | implemented | Extended aggregate-field verification through Project, Order, and set-operation outputs and kept flat dotted projection fields readable by downstream table handlers. | `current change`; focused verifier, handler, and tier-routing checks passed 24 cases; task-scoped Ruff and strict mypy passed. | Rerun the held Korean aggregation cell before the clean 14-cell and seeded 100-case Browser gates. |
| 2026-08-15 | implemented | Named the capabilities a verified plan selected in the `plan_verify` stage record, and extended the local plain-log context allowlist to render `stage`, `plan_nodes`, and `failure_type`. Which function a turn planned was previously undiagnosable from a local run. | `current change`; focused planner checks passed 14 cases and the local service log runner passed 11 cases; task-scoped Ruff and strict mypy passed. | Use the field to determine which capability an incident-bound turn actually plans. |
| 2026-08-15 | implemented | Projected the verified query outputs themselves into the general presentation artifact. The artifact carries per-node results and a bounded row table instead of only the output-node count, and cells are rendered as bounded printable text with positional column keys because an ontology field name is not a valid Console column key. | `current change`; focused Operator semantic bridge checks passed 48 cases; task-scoped Ruff and strict mypy passed. | Confirm the rendered result on the authenticated local Console. |
| 2026-08-15 | implemented | Made a turn anchored to an incident fail closed when the verified plan did not read that incident's own audit evidence. Local `plan_nodes` evidence showed an incident-bound turn planning `query.manifest`, which previously answered generically and read as an answer about the incident. The turn now holds with `incident_evidence_not_planned` or `incident_evidence_mismatched_binding`. | `current change`; focused processor checks passed 46 cases including a bound-but-unplanned hold, a cross-incident hold, and an unbound answered control; task-scoped Ruff and strict mypy passed. | Seed the bound incident goal deterministically so the planner no longer has to select it or copy its identifiers. |
| 2026-08-15 | implemented | Narrowed the previous row's hold to the cross-incident case only. The Console carries the incident binding on every turn of an incident conversation, including questions that are not about the incident, so `incident_evidence_not_planned` held legitimate unrelated questions. Reading a different incident's evidence than the bound one remains a hold. | `current change`; focused processor checks passed 46 cases, now asserting that a bound turn with no incident evidence answers and that a cross-incident read holds; task-scoped Ruff and strict mypy passed. | The "always read the bound incident" guarantee needs the deterministic goal seed; only then can an absent incident read be treated as a defect. |
| 2026-08-15 | implemented | Stopped the incident answer from reporting an empty correlation as a successful reading and stopped raw gap keys reaching operator prose. An answer with no correlated record now says so, a missing profile is stated instead of reported as status `unknown`, and any unmapped gap key is humanized because Markdown renders its underscores as emphasis. | `current change`; focused processor checks passed 47 cases including an empty-correlation answer, and Operator bridge checks passed 48 cases; task-scoped Ruff and strict mypy passed. | Render the correlated evidence timeline the function already returns. |
| 2026-08-17 | implemented | Stated the whole record count in the incident timeline instead of the carried slice. `correlated_evidence` is capped at twenty upstream while `verified_records` holds the real total, so a thirty-four record incident showed `Audit records 34` in the overview and `latest 10 of 20` in the timeline on the same card, understating the evidence it had counted one block earlier. The timeline now bounds its title by the verified total. | `current change`; Operator checks passed 353 cases with 1 skipped and Core incident and processor checks passed 400 with 1 skipped; reverting the bound reproduced `latest 10 of 20` against the expected `latest 10 of 34` before the source was restored; task-scoped Ruff and strict mypy passed. | Confirm the rendered timeline on the authenticated local Console. |
| 2026-08-17 | validated | Confirmed on the authenticated local Console that the incident answer renders the profile, the recorded-activity table with actors and audit references, the named limitations, and the read-only next steps, replacing the bare verified-output count. The timeline title carried no truncation suffix because the observed incident holds six records and the block showed all six, so the live session exercised the untruncated path only. | `current change`; authenticated Browser Entra session at `/incidents` against local Core and Operator on commit `61e826092`; the card reported `Audit records 6`, six activity rows, three limitations, and two read-only steps. | Observe a truncated timeline once a local incident exceeds twenty records; the truncated title is covered by a focused mutation-verified test until then. |
| 2026-08-17 | implemented | Taught the authenticated incident presentation gate about the recorded-activity timeline. The gate still pinned the three blocks that shipped before the timeline existed, so it asserted a presentation the product no longer produces and would have passed only if the timeline were removed. It now derives the expected blocks from the correlated evidence the same terminal carries. | `current change`; `console/tests/live-e2e/semantic-answer-presentation.spec.ts`; the live Console answer observed today renders `overview`, `records`, `limitations`, and `findings`; Console typecheck passed. | Run the gate against an authenticated external stack to convert this from a corrected expectation into a fresh receipt. |
| 2026-08-17 | implemented | Pinned the Korean incident presentation at the unit level. English already pinned the four-block order, but Korean order and titles rested only on the authenticated gate, which skips without an external stack, so a Korean-only regression could ship unobserved. | `current change`; `test_incident_presentation_keeps_the_same_blocks_in_korean`; Operator `362 passed, 1 skipped`; replacing the localized timeline title fails only the Korean test. | None for bilingual incident presentation coverage. |
| 2026-08-17 | implemented | Replaced the Incident semantic query's no-cause design boundary with a recorded-RCA boundary. T0 now records a bounded finding-severity impact row without inventing a baseline or threshold. The query returns a root-cause assessment only from a recorded grounded hypothesis with matching citations, carries the recorded impact and citation rows, and renders all three in the bilingual answer and Console artifact. Missing or incomplete evidence remains an explicit limitation, and the read path keeps `execution_authority=false`. | `current change`; focused Core query `3 passed`, semantic processor `61 passed`, Operator presentation `64 passed`, Console parser `9 passed`, T0 producer `1 passed`; Ruff, strict mypy, and Console typecheck passed. | Retain authenticated Browser evidence for both a recorded-RCA result and an honestly unavailable result. |
| 2026-08-17 | implemented | Added deterministic RCA projection for the closed notification terminal failures `route_unresolved`, `trust_mismatch`, and `escalated_to_hil`. The projection uses the exact `notification.route` audit row as its citation and derives one route-outcome impact row without appending or rewriting audit history. Successful delivery and unknown outcomes remain non-causal. | `current change`; focused Incident, semantic processor, and Operator presentation checks passed 133 cases; Ruff and strict mypy passed. | Restart Core and retain authenticated Browser evidence for the existing route-unresolved incident. |
| 2026-08-17 | implemented | Backfilled the exact historical object/link release that earlier PostgreSQL rows already pin. The migration derives it only from the content-verified predecessor registry manifest and two exact old declaration references, then verifies the reconstructed digest before insert. Missing, altered, or unrelated releases remain startup-blocking instead of being reinterpreted as the current release. | `current change`; [`20260817_0085_historical_ontology_release.py`](../../../alembic/versions/20260817_0085_historical_ontology_release.py), `service-migrations/**`, and focused registry, migration-chain, and service-inventory tests report 2, 179, and 46 passed; task-scoped Ruff and format checks passed. | Apply the migration, restart Core, and retain authenticated healthy-startup evidence before changing K0 to `validated`. |
| 2026-08-17 | implemented | Moved the bitemporal `topology_at` cutoff-order invariant into deterministic query-plan verification. A candidate whose event cutoff exceeds its knowledge cutoff can retry only the bounded plan stage and cannot reach the PostgreSQL history reader or execution handler. Valid empty or incomplete retained history continues to materialize with `complete=false`. | `current change`; focused query-verifier and semantic tier-routing checks passed 41 cases; task-scoped Ruff and strict mypy passed. | Retain a strict bilingual temporal-comparison answer with complete authoritative evidence before changing assurance status. |
| 2026-08-18 | implemented | Removed query-engine vocabulary from the operator-facing answer. The heading, the disposition summaries, and the held-transport fallback state what the result is instead of naming the ontology query, the overview labels each output by what it holds instead of by its plan node id, and declaration digests and authority flags stay in technical details unless a row carries nothing else. | `current change`; `semantic_turn_processor.py`, `semantic_turn_presentation.py`, `semantic_turn_runtime.py`, `test_semantic_turn_bridge.py`, `test_semantic_turn_roundtrip.py`; 394 operator-service and 62 processor cases passed; task-scoped Ruff, format, and strict mypy passed. | Evidence receipts and exact rows keep their internal identifiers, which is where an auditor reads them. |
| 2026-08-18 | withdrawn | Declaring `Resource.status` and `Resource.location` was implemented and then withdrawn. Any declaration edit moves the ontology release digest, which moves the promoted surface's `manifest_digest`, which moves the `validation_subject_digest` the stored held-out retrieval receipt was issued against. Recomputing the manifest digest is deterministic; reissuing the receipt is not, because its cohort metrics come from an evaluation run over the new generation. | Full suites on the withdrawn revision: 5 failed with `validation receipt subject mismatch` in `test_discovery_catalog_search.py` and `test_rule_generation_documents.py`; the same suites passed 1490 cases on its parent. | A declaration change needs a design pass that plans the surface revalidation run before the catalog edit, not after. |

### Remaining work

- [x] Expose exact-release declaration details, topology-backed dependents, honest evidence-health
  availability, and declaration-ref release comparison through the read-only Operator and Console
  workbench. Focused checks for [Issue #223](https://github.com/dotnetpower/fdai/issues/223) pass.
- [ ] Retain a governed Browser artifact for the workbench and one authenticated principal-scoped
  Context receipt before raising the workbench from `implemented` to `validated`.
- [ ] Materialize the reviewed control-objective and binding vocabulary in the bounded startup
  projection, then prove exact release identity and zero authority fields in focused tests.
- [ ] Bind PostgreSQL historical topology, production metric providers, and inventory-promotion
  publishing, then retain replay and completeness receipts from the focused integration checks.
- [ ] Refresh inventory after the release-binding change and retain the new projection manifest and
  status as exact-release evidence; don't assign releases retroactively to historical manifests.
- [x] Bind the reviewed Kubernetes relationship projector through production and local inventory
  composition and verify independently checked links when Kubernetes records are supplied.
- [x] Add the bounded authoritative Kubernetes API inventory source and bind it through the
  existing single-writer promotion path.
- [x] Bind the Kubernetes rollout reducer through an issued exact-release FunctionType and a
  server-owned structured investigation plan. Focused checks prove stale, conflicting,
  incomplete, and cross-target evidence cannot produce a cause or recovery-success claim.
- [ ] Retain authenticated targetless candidate selection plus exact-target rollout and Pod recovery evidence from the Console. Pod recovery additionally requires independent event/change, replica, and replacement-UID evidence at a new cutoff.
- [ ] Retain complete live-generation projection receipts for Pod telemetry composition.
- [ ] Compose the reconciliation coordinator and publish its proposal-only outbox recommendation
  through the event bus with restart, duplicate-delivery, and terminal-closure evidence.
- [ ] Exit K6-K8 only after deterministic graph propagation, time-bounded trajectory invariants,
  independent outcome closure, and failure-attribution tests all pass on one pinned release.

## Catalog-owned instance projection

Core runtime startup now projects Rule, PolicyArtifact, ResourceClass, ResourceType, SignalType,
Property, and ActionType instances into one catalog-owned subgraph. Its taxonomy slice retains 11
classes, 77 memberships, and 11 bounded specialization links over all 77 neutral ResourceTypes.
The pure builder rejects semantic or identity defects; atomic identical replay remains a no-op.

The canonical release also declares `ControlObjective`, `RuleObjectiveBinding`, and
`EquivalenceValidationReceipt`, with `objective_bound_by`, `binding_targets_rule`, and
`binding_validated_by` relationships. Catalog loaders verify exact objective, Rule, policy
implementation, and required-evidence signatures before accepting a binding. These declarations
and candidate records are release vocabulary only: the current startup projector does not
materialize them into the runtime subgraph, and no semantic query, binding, or receipt grants
policy, promotion, approval, or execution authority. Deterministic equivalence execution and
reviewed receipt issuance remain separate delivery work.

This projection makes catalog relationships queryable but doesn't change their authority. Git
catalog-as-code remains authoritative, and the instance graph remains a read model. If OPA or the
ontology store is unavailable in an optional local profile, projection remains unavailable rather
than substituting synthetic state. Deployed profiles continue to require OPA for T0 evaluation.

The independently scheduled inventory process checks each mapped ResourceType target against the
current instance graph before it builds classification links. A target absent during rolling
catalog startup becomes the stable non-blocking drop `unseeded_resource_type`; the authoritative
Resource objects and other verified links in the complete generation still replace the owned
subgraph. A present endpoint with the wrong type and every other instance validation error continue
to fail the generation.

The reviewed `unclassified-resource` target is the only exception to provider-specific type
mapping. It is catalog-owned, carries no provider mapping or query terms, and receives a
classification link only after the complete provider identity set reconciles with the final-fence
coverage receipt. Runtime discovery never creates a new ResourceType declaration.

The shared property-semantics registry gives every canonical property one content-addressed
identity for meaning, unit, value kind, and bounds. Catalog projection validates each reference
against that registry and preserves finite numeric values without float coercion, so services and
replays cannot silently reinterpret the same property.

## Pod telemetry path runtime

`evaluate_pod_telemetry_path` is a pure A0 read over a `SecuredObjectSetQueryResult` and an immutable
mapping of state-evidence subjects to `StateFactMetadata`. It follows only the reviewed physical
links `kubernetes_selects`, `kubernetes_exposes_endpoints`, and
`observation_targets_resource`. Traversal is already bounded and purpose checked by the secured
ObjectSet gateway; the evaluator performs no provider, Kubernetes, network, registry, or store I/O.

The result contains four ordered segments: Pod selected by Service, Service exposing Endpoints,
Observation targeting the Pod, and the Observation sample. Segment evidence is verified only when
its state fact is complete, current at the supplied cutoff, non-synthetic, and conflict free.
The Pod, selected Service, and exposed Endpoints must all carry identities in the expected cluster
scope; a cross-cluster Service or Endpoints record makes the affected segment unverified even when
its relationship evidence is otherwise current and complete.
Incomplete graph receipts cannot prove absence, so unresolved segments remain `unverified` rather
than becoming `missing`. The exact secured graph receipt digest and all retained evidence refs are
returned for replay.

The delivery layer now includes a pure candidate projector for reviewed Service label-selector and
same-name Endpoints relationships. It emits no active graph link on partial input, missing targets,
or duplicate candidates. A separate complete-generation verifier must attach immutable observation
metadata before inventory projection can expose either relationship. Production Kubernetes
inventory binding and retained composition receipts remain open.

Focused production-composition checks use an exact-release Interface that spans Resource and
Observation evidence, then invoke the issued Pod function through its secured dependency digest.
They prove that complete evidence returns four verified segments and that a synthetic sample stays
unverified with `claimed_health: false` and `execution_authority: false`.

The source-derived FunctionType is part of the exact runtime release and is registered in the
production semantic function registry. Its wrapper accepts only a composition-issued secured
query result and derives typed relationship and sample state evidence from that graph. It does not
derive a health value, produce Finding or Forecast objects, grant action authority, or alter any
existing Kubernetes delivery module.

## Design at a glance

The infrastructure separates semantic declarations, authority-specific state, and agent-owned
kinetic execution. A graph write, function result, generated SDK call, or `MutationPlan` remains
proposal or context until the accountable agents complete judgment, authorization, execution, and
independent effect verification.

![Design at a glance. The main stages are Authority sources, ProjectionBinding, Observed object graph, ObjectSet query, Decision context, MutationPlan, Risk and approval, ActionRun, Provider, Git, ledger, or FDAI store, ReconciliationReceipt, ObservedOutcome.](../../diagrams/generated/fdai-roadmap-architecture-operating-ontology-platform-01.en.svg)

## Exact type identity

Every declaration belongs to one immutable `OntologyRelease`. Runtime records pin the exact
declaration that interpreted them:

```yaml
type_ref:
  name: Resource
  version: 2.1.0
  catalog_digest: sha256:<digest>
```

`Action`, `ActionRun`, ontology objects, ontology links, audit records, and generated plans retain
an exact reference. Compatibility checking returns `compatible`, `migration_required`, or
`incompatible`. A release cannot replace a declaration in place when existing records would be
reinterpreted.

Cross-service semantic records use `OntologyReleaseRef`, a compact envelope containing the
contract `schema_version` and exact release `digest` without copying the declaration set. Legacy
discovery and explanation records may omit the envelope while they migrate. Decision-critical
`evaluate` and `action_draft` consumers require it, and any supplied mismatch is rejected before
semantic-index or provider I/O.

## Proof-carrying semantic interpretation

Lexical matching, embeddings, and models can produce a `SemanticInterpretationCandidate`. The
candidate pins its target type, ontology release, semantic catalog, normalized arguments, input,
unresolved terms, source, and content digest, but it always has `candidate_only` authority.

A candidate becomes a `VerifiedSemanticPlan` only when every term is resolved, its target matches
the exact active release, its operation class matches a typed function or ActionType, and it cites
an exact catalog record, promoted language surface, or operator-confirmation turn. The verified
plan remains `execution_authority: false`. Query, derive, and validate plans can target only typed
functions; an action interpretation can create only an ActionType-bound draft that re-enters the
normal judgment, approval, execution, recovery, and audit path.

Candidate and plan arguments are stored as canonical JSON rather than mutable nested containers.
Verification recomputes candidate integrity before producing a plan. Exact-catalog verification
pins the catalog digest directly and requires it to match the active semantic catalog supplied by
composition. Promoted surfaces and operator confirmations require an injected evidence validator
for the immutable promotion or conversation-turn reference.

The Operator API declares `inventory.select_resources` as a read-only ontology query function.
Production semantic candidates and the `/ontology/graph` manifest use the same release digest and
function reference. A candidate from another release is rejected before provider I/O.

## Semantic interfaces and object sets

`OntologyInterfaceType` is distinct from the existing `ActionInterface` safety flags. A semantic
interface declares properties, required links, supported actions, and inherited interfaces.
Object types can implement multiple interfaces. Initial kernel interfaces are `Operable`,
`Ownable`, `Observable`, `ObjectiveBound`, `Recoverable`, and `CostBearing`.

An `ObjectSetDefinition` selects objects by concrete type or semantic interface. It supports typed
property predicates, named-link traversal, deterministic ordering, an `as_of` cutoff, freshness,
purpose, and a hard result limit. It does not accept free-form Cypher, SPARQL, SQL, or model text.
Every materialization records the release digest, cutoff, source watermarks, truncation reason,
and redaction summary.

The current instance-store contract has no historical observation API. The secured gateway
therefore accepts `as_of` only at the trusted evaluation cutoff, with an explicitly configured
skew of at most five seconds. It rejects past or future cutoffs outside that envelope as
unsupported and records `current_state_only`, the cutoff, and the accepted skew without claiming
historical completeness. Each secured receipt binds the exact ontology release, caller role,
singleton purpose, canonical projected-result digest, completeness and truncation state, and a
content-free redaction summary. Returned graph properties are recursively immutable, and the
semantic query boundary revalidates the result-receipt binding before use.

LinkType declarations do not yet define property ACLs. Secured projections consequently strip all
link properties and count the removed fields in the receipt. They preserve only the typed
endpoints and exact type reference. Redacted object aliases are allocated outside the complete
source identity set, and the projector validates unique object identities and visible-endpoint
closure before returning the graph.

Property predicates support `equals`, `not_equals`, `in`, `exists`, `absent`, `at_least`,
`at_most`, and `contains`. Single-value operators use `equals`, `in` uses a non-empty `values`
tuple, single-value operands cannot be null, and presence operators accept no operand. The store
receives only `equals` predicates for indexed pushdown. Both direct queries and traversals apply
every predicate again to the bounded candidate graph and remove links whose endpoints were
filtered out. Predicate operands are canonical JSON with finite numbers, at most 32 nesting
levels, and at most 64 KiB of encoded data.
One definition accepts at most 32 predicates, one `in` predicate accepts at most 1000 values, and
one traversal accepts at most 1000 roots and 64 named link types. Root ids without a traversal and
traversals without a named link type are rejected before store I/O.

Materialization distinguishes `result_limit`, `candidate_limit`, and `traversal_limit`. A
`candidate_limit` means memory filtering saw only the first 1000 store candidates, so an empty or
short result is incomplete evidence rather than a complete absence claim. A `traversal_limit`
means graph expansion reached its object ceiling. The in-memory and PostgreSQL stores both apply
the requested object limit to initial roots as well as reached objects.
Exact-id predicates use fixed batches of at most 128 ids through one indexed store query per batch.
The reader stops after it has enough matching objects to prove `result_limit`.

## Semantic actions and mutation plans

`ActionType` retains its stop conditions, rollback, impact scope, execution path, promotion gate,
and autonomy ceilings. Version 2 adds these semantic fields:

- **Target:** An exact ObjectType or InterfaceType reference plus one-or-set cardinality.
- **Parameters:** Primitive, enum, struct, object-reference, or object-set inputs with validation
  and redaction metadata.
- **Read set:** Object sets and properties required to plan and verify the action.
- **Submission criteria:** Deterministic criterion or `validate` function references.
- **Planner:** Declarative effect rules or one signed `plan` function.
- **Effects:** Expected internal writes, catalog pull requests, provider commands, notifications,
  or schedules.
- **Postconditions:** Independent observations that close the action outcome.
- **Transaction policy:** Internal atomicity or external saga semantics, lock scope, and maximum
  affected object count.

Planning produces an immutable `MutationPlan`. It contains exact target revisions, the computed
write set, commands, impact evidence, rollback or compensation steps, expected effects, and a
digest. Semantic plans preserve the signed planner FunctionType identity in `planner_ref` and bind
an upstream selected operational plan separately in `operational_plan_ref` when that lineage
exists. Approval and execution revalidate the digest and current revisions. A stale plan returns
to planning or human review and never executes with widened scope.

## Typed ontology functions

An `OntologyFunctionType` has one of four kinds:

| Kind | Output | Authority |
|------|--------|-----------|
| `query` | `ObjectSetDefinition` or bounded data | Read only. |
| `derive` | Typed scalar or struct | Read only. |
| `validate` | Typed criterion result with evidence | Can lower eligibility only. |
| `plan` | Immutable `MutationPlan` | Proposal only. |

Functions declare exact input and output schemas, read sets, determinism class, artifact digest,
publisher, resource ceilings, and network policy. A function never receives executor identity and
never invokes a provider mutation directly.

The registry keeps existing one-argument callbacks through an explicit adapter. A function that
needs authenticated read context registers separately and receives an immutable
`FunctionInvocationContext` with the exact authorized role and attenuated purpose. Arguments are
canonicalized for the input digest and deep-copied before callback execution, so nested callback
mutation cannot alter caller-owned input or invocation evidence.

Query-plan handlers fail closed without expanding the receipt contract. A stable `TypeError`,
`ValueError`, or `RuntimeError` produces a failed `capability_failed` receipt, and dependent nodes
remain skipped. The runtime emits `ontology_query_node_failed` with only the allowlisted
`node_kind` and `failure_type` fields. It doesn't record the exception text, arguments, node
identifier, provider payload, or operator data for these stable failures.

The diagnostic runtime registers 22 Kubernetes reducers as exact-release `derive` functions. Live
providers invoke the registry as Heimdall under the `diagnostic-evaluation` purpose and preserve
the canonical function arguments with each invocation receipt. The observer accepts a finding only
when the active release, caller, invocation identity, input digest, and output digest all match.
These receipts are read-only provenance; they do not turn a diagnostic function into an action.

The network competency runtime declares `query.network_path_segments` as an exact-release
deterministic `query` function. Its input is one purpose-bound `SecuredObjectSetQueryResult` plus
explicit source, target, evaluation time, depth, and segment ceilings. It never calls an inventory
provider. Registration requires a trusted `NetworkQueryReceiptVerifier` and an opaque
composition-owned verification context. The contextual callback checks that the receipt role,
singleton purpose, exact release, and result digest match `FunctionInvocationContext`, then asks the
verifier to authenticate the same tuple. Production ObjectSet handlers issue bounded receipts and
Function handlers resolve the exact dependency digest; self-minted receipts remain unavailable.
An omitted `evaluated_at` uses the issued receipt observation cutoff, while an explicit value must
equal it exactly. Link
effective, evidence, and recorded times stay at or before that cutoff, and freshness ceilings above
one year or overflowing timestamp arithmetic remain unverified. `attached_to` may be traversed
inversely for a query while retaining its stored direction, `contains` and `routes_to` follow stored
direction, and `peered_with` requires both directed records with distinct observation and
verification receipt lineage. Only a complete path whose every segment has fresh independent
verification reports `reachability_verified: true`; every other result uses `null`, never `false`.
An incomplete graph returns `query_incomplete`, and unrelated graph links don't consume the
network-segment limit.

## Authority-aware writeback and projection

Each ObjectType declares one authority class and write policy:

| Authority class | Examples | Write policy |
|-----------------|----------|--------------|
| `catalog_owned` | Rule, ActionType, policy | Reviewed Git pull request. |
| `fdai_owned` | Workflow draft, approval | Atomic state transaction plus outbox. |
| `provider_observed` | Cloud resource, topology | Provider command followed by independent observation. |
| `ledger_owned` | DecisionCase, ActionRun | Append only. |
| `derived` | Forecast, pattern projection | Owning-agent projection. |

For `provider_observed` objects, a successful API receipt is not a state update. Reconciliation
compares the intended effect with fresh evidence and emits a `ReconciliationReceipt` with
`matched`, `mismatched`, `timed_out`, or `unscorable`. Only the authoritative projection updates
observed state.

The reconciliation coordinator binds the exact release, ActionType, immutable plan, authenticated
observer context, and independently observed records before closing an attempt. A terminal outcome
and its proposal-only next-step event commit atomically; neither the receipt nor its outbox entry
updates provider-observed state or grants execution authority.

Authority comes from a trusted `AuthenticatedObservationContext` supplied separately from the
untrusted observation envelope. The context binds distinct observer, executor, and source
credential lineages to a signed, content-addressed verification receipt. Envelope authority claims
never grant authority. Every recommendation is proposal-only and carries `grants_authority: false`.

| Receipt status | Terminal | Proposal-only next step | Persistence |
|----------------|----------|-------------------------|-------------|
| `matched` | Yes | `close_matched` | Atomically commit terminal outcome and outbox recommendation. |
| `mismatched` | Yes | `request_vidar_recovery` | Atomically commit terminal outcome and outbox recommendation. |
| `timed_out` | Yes | `request_vidar_recovery` | Atomically commit terminal outcome and outbox recommendation. |
| `unscorable` | No | `hold_unscorable` | Record only the observation attempt; a later authenticated observation may retry the terminal identity. |

Observed inventory relationships may carry immutable state-fact and verification metadata. The
projection preserves that envelope without treating it as permission, suppresses relationship
claims for incomplete observations, and lets stale, synthetic, conflicting, or unverified evidence
lower downstream autonomy.

`ProjectionBinding` makes source-to-ontology mapping reviewable. It declares source identity,
type targets, identity and property mappings, watermark behavior, freshness, deletion semantics,
conflict policy, and batch limits. A source cannot silently overwrite another authority.

## Dynamic state and graph effects

The platform separates three layers that must not grant authority to one another:

| Layer | Question | Output authority |
|-------|----------|------------------|
| **Semantic** | What exists, what does it mean, and which relationships are valid? | Type, unit, identity, cardinality, and compatibility only. |
| **Kinetic** | What registered operation may change an exact target under which safety contract? | Proposal-only `MutationPlan`; judgment, approval, and execution remain external. |
| **Dynamic** | How may state evolve over time under an intervention or external event, and how well did that prediction match reality? | Read-only prediction, invariant, propagation, and fidelity evidence only. |

`OperationalStateTrajectory` is distinct from the existing governed conversation and execution
`TrajectoryEnvelope`. It pins an ontology release, baseline graph revision, inventory generation,
event-time cutoff, horizon, affected object revisions, predicted or observed state slices,
intervention references, source watermarks, completeness, truncation, and one replay-stable digest.
It stores normalized values and opaque evidence references, never raw cloud payloads. A predicted
trajectory cannot assert provider truth; an observed trajectory requires authoritative provider
or telemetry receipts.

`GraphEffectModel` extends the current action-and-metric effect model without replacing it. It
declares a source object or interface, an ActionType or external-event trigger, one bounded LinkType
path, a target object or interface and metric, propagation lag, response function, uncertainty,
context conditions, evidence grade, learning cutoff, and active or challenger status. The simulator
applies deterministic topology effects first, then verified active models. Challenger output is
reported only as divergence evidence and never ranks or selects a branch.

`DynamicInvariant` describes a machine-evaluable bound that must hold over the complete trajectory,
such as an SLO, RTO, RPO, capacity floor, cost envelope, data-integrity predicate, or affected-set
ceiling. A predicted violation removes the branch before arbitration. An observed violation during
execution stops forward dispatch and re-enters the existing typed recovery path; it does not let a
simulator alter a running plan.

`TrajectoryOutcome` compares predicted and independently observed state slices by object, metric,
and time window. Its terminal status is `matched`, `mismatched`, `intervention_censored`,
`incomplete`, or `unscorable`. Only complete, post-cutoff, independently observed outcomes update a
challenger model. Active models remain immutable until a separate reviewed promotion applies an
exact evidence receipt.

Conversation or internal-processing failures may open an off-path adequacy review only after a
deterministic attribution step preserves the exact verification reason, route, evidence manifest,
ontology release, graph revision, freshness, and completeness. Context, provider, routing,
rendering, policy, semantic, kinetic, and Dynamic failures remain distinct. Only reproduced
semantic, projection, rule, or Dynamic gaps create inert ontology or model-review candidates.

## Query, security, and SDK surfaces

Security applies at object, property, link, object-set, action-discovery, action-submission, and
function invocation boundaries. A visible link cannot reveal an otherwise hidden endpoint.

An ontology release can generate scoped Python and TypeScript SDKs plus OpenAPI metadata. The
generator includes only approved types and capabilities. Write methods submit typed action
proposals; they never call an executor. The publication adapter writes immutable content-addressed
artifacts with explicit scope, purpose, role ceiling, release, and artifact digests. Existing bytes
must replay exactly, and declaration removals require an explicit migration reference.

## Delivery sequence

| Slice | Deliverable | Exit criteria |
|-------|-------------|---------------|
| P0-A | Exact declaration detail projection. | ObjectType, LinkType, and ActionType responses preserve one release, deterministic revision, completeness, redaction, and `mutation_authority=false`. |
| P0-B | ObjectType workbench and clean detail routes. | Direct navigation, refresh, and keyboard paths work; `Decision` properties, lifecycle absence, provenance, and relationships render without horizontal page overflow at 1440 x 900, 993 x 641, and 390 x 844. |
| P0-C | Governed action navigation. | Related actions require exact semantic target evidence; legacy unbound actions lower completeness and are never inferred by name or description. |
| P1-A | Deterministic dependents and evidence health. | Dependents come only from Catalog topology; unavailable runtime evidence carries nullable counts rather than measured zero. |
| P1-B | Active-inventory impact scope. | Traversal is bounded, snapshot-pinned, stored-direction, visibly unverified where applicable, and grants no execution or mutation authority. |
| P1-C | Retained-release comparison. | Additions, changes, and removals are deterministic; missing historical field schemas require review and never grant restore or migration authority. |
| P2 | Dedicated InterfaceType and FunctionType details. | Entry requires more than one meaningful active declaration plus an authoritative usage source; otherwise registry identity and topology nodes remain sufficient. |

P0-A through P0-C pass together before P1 is complete. Revise any slice that needs a new kernel
field, similarity links, raw provider payloads, mutation/executor credentials, or browser-calculated
authority or compatibility. Runtime Context remains a separate receipt-bound projection.

| Wave | Deliverable | Exit criteria |
|------|-------------|---------------|
| K0 | Exact `OntologyTypeRef` and `OntologyRelease` pinning. | Action, graph, audit, and replay tests preserve exact versions and digests. |
| K1 | Interfaces and bounded object sets. | Concrete expansion, ACL, cutoff, truncation, and query fixtures pass. |
| K2 | Semantic ActionType v2 and `MutationPlan`. | Plan digest, stale revision, impact, rollback, and shadow no-mutation tests pass. |
| K3 | Typed functions and authority-aware reconciliation. | Functions cannot mutate; every external effect reaches one typed closure. |
| K4 | Projection bindings and schema migrations. | Snapshot/delta parity, watermark recovery, conflict, and migration fixtures pass. |
| K5 | Generated SDKs and ontology application surfaces. | Python/TypeScript compile tests and proposal-only write tests pass. |
| K6 | Operational state trajectories and deterministic graph propagation. | Identical release, graph, cutoff, models, and interventions produce one digest; stale, truncated, cyclic, or unmodeled paths require review. |
| K7 | Dynamic invariants and trajectory outcome closure. | No invariant-violating branch reaches arbitration; provider acceptance cannot close an outcome; incomplete observations remain unscorable. |
| K8 | Failure attribution and governed Dynamic learning. | Exact verification reasons survive intake; non-ontology failures create no ontology proposal; only challengers learn and no learned artifact raises authority without review. |

New fields begin optional for decoding but are required for newly built runtime records. Legacy
decoding is removed only after retained audit and instance fixtures replay under exact releases.

## Verification matrix

| Concern | Required proof |
|---------|----------------|
| Replay | A historical record resolves the same declaration and plan digest. |
| Authority | A graph write cannot grant permission or assert external state. |
| Query safety | Every object set is bounded, purpose checked, and explicit about truncation. |
| Action safety | Stop, rollback, impact, dry-run, lock, idempotency, and audit remain mandatory. |
| Function safety | Query and planning code has no executor identity or direct mutation path. |
| Network path safety | Directed storage, reciprocal peering, per-segment evidence, cycle detection, and depth/segment ceilings are receipt-bound; absence never becomes an unreachable claim. |
| Reconciliation | Provider acceptance and observed convergence remain distinct states. |
| Dynamic replay | The same bounded inputs produce the same predicted trajectory and invariant verdict. |
| Dynamic authority | Prediction, model agreement, or model promotion evidence cannot approve or execute an action. |
| Dynamic closure | Only complete independent observations score trajectory fidelity or update a challenger. |
| Pod telemetry | A purpose-scoped secured graph plus state evidence yields deterministic verified, unverified, stale, and missing segments without provider I/O or health inference. |
| Pod diagnosis | One exact secured Pod UID can join bounded lifecycle and content-free log evidence; zero rows, incomplete sources, and scope conflicts remain explicit and cannot grant cause or execution authority. |
| Historical topology | PostgreSQL replay retains the exact ontology release and source receipt bindings for each selected revision batch; dangling active links lower completeness. |
| Projection reload | The inventory status marker and manifest share a content digest, so a restart never exposes a mixed generation. |

## Related docs

| To learn about | Read |
|----------------|------|
| Declaration kinds and runtime State/Context boundaries | [Operating Ontology Metamodel](operating-ontology-metamodel.md) |
| Existing semantic and authority model | [FDAI Operating Ontology](operating-ontology.md) |
| Existing ActionType safety contract | [Action Ontology](../decisioning/action-ontology.md) |
| Runtime execution authority | [Execution Model](../decisioning/execution-model.md) |
| Repository and dependency boundaries | [Project Structure](project-structure.md) |
