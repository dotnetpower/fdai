---
title: Assurance Twin (queryable, proactive, verifiable review)
---
# Assurance Twin (queryable, proactive, verifiable review)

FDAI's answer to the "architecture review agent" request is not a chatbot
bolted onto a document index. It is an **Assurance Twin**: a queryable,
ontology-grounded digital twin of the governed subscription that answers
questions deterministically, reviews changes before anyone asks, and proposes
(never executes) remediation. A model compiles natural language into typed graph
queries and explains the results; the answer itself is produced by the
deterministic engine over the twin, so it is grounded and verifiable by
construction, not by a model's say-so.

> **Scope**: customer-agnostic. The twin's schema, rules, and thresholds are
> generic; a fork supplies its own resource population through the `Inventory`
> seam and its own rule set. No customer values, tenant ids, or resource names
> live here
> ([generic-scope.instructions.md](../../../.github/instructions/generic-scope.instructions.md)).

> **Where it sits**: the twin is a **read-only projection** over the ontology
> graph. It never holds a privileged identity. Every mutation still flows
> through `risk-gate -> executor -> delivery`, preserving the read-only surface
> rule in
> [app-shape.instructions.md](../../../.github/instructions/app-shape.instructions.md).
> Answering a question is never an action.

## What this doc covers

This document specifies the review/assurance surface that covers the
architecture-review, Q&A, and assessment-report use cases without regressing the
deterministic-first, event-driven, risk-gated design. It reuses the ontology in
[llm-strategy.md](../architecture/llm-strategy.md#ontology-foundation), the tiered router and
quality gate in
[architecture.instructions.md](../../../.github/instructions/architecture.instructions.md),
the detection findings in
[observability-and-detection.md](../rules-and-detection/observability-and-detection.md), and the
deployment analyzer in [deployment-preflight.md](../deployment/deployment-preflight.md). It
adds one new subsystem, `core/assurance_twin/`, and one delivery intent; the rest
is composition of existing parts.

## Implementation status

The deterministic Twin core and its scalar and graph simulation primitives have focused tests.
The posture/review surface is a **partial implementation**. Heimdall's report and Forseti's
independent review writers can accept only complete, fresh, revision-pinned retained evidence
from an injected trusted source. They atomically stage their own read-only activity with the
durable `state_kv` row and Saga-attributed append-only audit lineage. Two supervised outbox relays
publish schema-validated, exact-revision advisory events. The authenticated Operator API and
Console continue to read the durable rows, not event tips. Production now binds Heimdall's posture
producer to the retained Inventory projection and the same deterministic T0/OPA generation used by
the control loop. Every Resource must have declared input-complete Rule coverage; an abstention,
missing property, pending relationship change, stale baseline, policy drift, or Inventory revision
change keeps posture unavailable. Inventory promotion and realtime graph locks remain held through
the source write and Heimdall confirmation. Durable first-seen ordering, source/target conflict
fencing, and baseline-capped freshness prevent delayed evidence from becoming current. Production
also binds Forseti's review producer to FDAI typed ActionType proposals: one exact proposal, its
completed what-if bound to the same proposal digest, and a reviewed declared ActionType effect
produce a scratch projection of the retained Inventory revision that the same T0/OPA generation
evaluates. Following the 2026-09-28 owner decision, Terraform is a local deployment tool and never
a governance or review input. No reviewed effect model or typed what-if producer ships yet, so every
submitted proposal stays explicitly unavailable in production. External review delivery and
governed runtime evidence remain open.

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| Projection, verified query, posture report, and publisher-neutral review core | implemented | [`core/assurance_twin/`](../../../services/core-control-plane/src/fdai/core/assurance_twin), [`tests/assurance_twin/`](../../../services/core-control-plane/tests/assurance_twin) | The in-memory projection, strict typed-query verifier, report fold, and review publisher glue pass focused checks. The default natural-language compiler returns `semantic_model_unavailable`; it does not infer meaning lexically. |
| Scalar Dynamic effect models, fidelity measurement, and bounded runtime coordination | implemented | [`effect_model.py`](../../../services/core-control-plane/src/fdai/core/assurance_twin/effect_model.py), [`fidelity.py`](../../../services/core-control-plane/src/fdai/core/assurance_twin/fidelity.py), [`runtime.py`](../../../services/core-control-plane/src/fdai/core/assurance_twin/runtime.py), and their focused tests | Active models stay immutable, challengers learn only from eligible outcomes, and divergence lowers the result to review. |
| Graph-wide Dynamic trajectories, propagation, invariants, episode closure, and model registry | implemented | [`graph_effect.py`](../../../services/core-control-plane/src/fdai/core/assurance_twin/graph_effect.py), [`graph_runtime.py`](../../../services/core-control-plane/src/fdai/core/assurance_twin/graph_runtime.py), [`graph_closure.py`](../../../services/core-control-plane/src/fdai/core/assurance_twin/graph_closure.py), and focused graph tests | The runtime persists prediction episodes before returning evidence and updates challenger slices only from complete independent observations. |
| Deep Security Assessment feed, deterministic analyzer, and catalog report | implemented | [`core/security/`](../../../services/core-control-plane/src/fdai/core/security), [`security_assessment.py`](../../../services/core-control-plane/src/fdai/core/reporting/datasources/security_assessment.py), [`test_assessment.py`](../../../services/core-control-plane/tests/core/security/test_assessment.py), and [`test_security_assessment_datasource.py`](../../../services/core-control-plane/tests/core/reporting/test_security_assessment_datasource.py) | This is a separate reporting subsystem, not the Twin-specific posture panel described below. |
| Retained Resource revision and writer admission contract | implemented | [`assurance_twin_inventory.py`](../../../services/core-control-plane/src/fdai/delivery/assurance_twin_inventory.py), [`assurance_twin_writers.py`](../../../services/core-control-plane/src/fdai/delivery/assurance_twin_writers.py), and focused source/publication tests | The snapshot and bounded Resource delta content share one canonical digest. A trusted source must supply complete, revision-matched rule evaluation (including a digest of an empty result); reviews also require a complete typed ActionType proposal readback bound to the same Inventory revision. The retired proposed-IaC readback is never admitted. This does not bind a relationship overlay. |
| Production Twin binding and ambient change-review delivery | in-progress | [`evaluation.py`](../../../services/core-control-plane/src/fdai/core/assurance_twin/evaluation.py), [`assurance_twin_posture_producer.py`](../../../services/core-control-plane/src/fdai/delivery/assurance_twin_posture_producer.py), [`assurance_twin_evidence_source.py`](../../../services/core-control-plane/src/fdai/delivery/assurance_twin_evidence_source.py), and runtime composition | Heimdall's production producer evaluates the exact retained Inventory revision with the immutable T0/OPA policy generation and records only per-Resource input-complete results. The request outbox remains content-free, and Inventory, Rule, policy, source, target, and freshness fences fail closed. Forseti's typed-proposal review producer is bound beside it; the governed runtime receipt remains open. |
| Forseti typed ActionType proposal review | implemented | [`typed_proposal.py`](../../../services/core-control-plane/src/fdai/core/assurance_twin/typed_proposal.py), [`proposal_effects.py`](../../../services/core-control-plane/src/fdai/core/assurance_twin/proposal_effects.py), [`assurance_twin_review_producer.py`](../../../services/core-control-plane/src/fdai/delivery/assurance_twin_review_producer.py), [`assurance_twin_proposal_intake.py`](../../../services/core-control-plane/src/fdai/delivery/assurance_twin_proposal_intake.py), [`test_assurance_twin_review_producer.py`](../../../services/core-control-plane/tests/delivery/test_assurance_twin_review_producer.py) | A durable content-addressed intake accepts one exact proposal and its what-if. The producer applies only a reviewed declared effect to the proposal's retained targets, evaluates them with the control loop T0/OPA generation, and requires an applying Rule input covering every changed leaf value. The review key is the proposal ref, so a newer revision supersedes the older review atomically and the Operator projection treats two usable reviews for one change handle as a conflict. An intake row is `reviewed` only after writer confirmation; a fence rejection retires the stale request, with at most three derivation attempts. Missing, stale, incomplete, failed, synthetic, or conflicting what-if results, unsupported ActionType versions, undeclared parameters, unassessed properties, and targets outside the retained revision settle unavailable. The shipped effect catalog is empty and no typed what-if producer submits yet. |
| Strict semantic compilation and abstention feedback | implemented | [`query.py`](../../../services/core-control-plane/src/fdai/core/assurance_twin/query.py), [`semantic_query.py`](../../../services/core-control-plane/src/fdai/core/assurance_twin/semantic_query.py), [`runtime/assurance_twin_query.py`](../../../services/core-control-plane/src/fdai/runtime/assurance_twin_query.py), and focused query/runtime tests (`50 passed`) | Injected compilers must bind the exact input digest, compiler revision, bounded limit, and evidence refs before a read-only plan survives verification. Abstentions emit content-free, no-authority gaps through an injected discovery sink. The runtime default remains explicit model unavailable. |
| T1 reuse, ChatOps intake, and governed runtime evidence | in-progress | [`chat.py`](../../../services/core-control-plane/src/fdai/core/assurance_twin/chat.py) and the shared semantic judgment contract | Message routing, T1 reuse, a concrete model provider, and an authenticated end-to-end receipt remain unvalidated. |
| Heimdall/Forseti local event publication | implemented | [`assurance_twin_writers.py`](../../../services/core-control-plane/src/fdai/delivery/assurance_twin_writers.py), [`assurance_twin_publication.py`](../../../services/core-control-plane/src/fdai/delivery/assurance_twin_publication.py), [`test_assurance_twin_publication.py`](../../../services/core-control-plane/tests/delivery/test_assurance_twin_publication.py) | Requests contain no findings. A source must return complete, fresh, conflict-free evidence at the requested revision before either writer persists it. Saga-attributed audit and the embedded outbox commit atomically with the exact row. Heimdall additionally holds the authoritative Inventory locks through atomic source/target confirmation; transient reads remain provisional, while confirmed drift revokes the outbox. Forseti's writer holds the same Rule-generation and Inventory fences for typed-proposal reviews. |
| Twin-specific operator panel and governed remediation proposal bridge | in-progress | [`posture_activity.py`](../../../services/core-control-plane/src/fdai/core/assurance_twin/posture_activity.py), [`assurance_twin_posture.py`](../../../services/core-control-plane/src/fdai/delivery/assurance_twin_posture.py), [`state_store_assurance_twin_posture.py`](../../../services/core-control-plane/src/fdai/delivery/persistence/state_store_assurance_twin_posture.py), [`assurance_twin_posture_projection.py`](../../../services/operator-service/src/fdai_operator_service/assurance_twin_posture_projection.py), and the [`assurance-twin` Console route](../../../console/src/routes/assurance-twin.tsx) | The recorder stores bounded, revision-fenced report and review bodies with provenance and an embedded pending outbox in the same audited transaction. Heimdall and Forseti have separate owner-checked activities; the shared observer-only operational activity schema is not misused to assign Forseti an observer role. A relay validates and acknowledges the exact retained revision; delayed and conflicting evidence cannot replace or publish a current row. Operator and Console render durable findings and gaps without recomputing authority. A trusted source, external Checks publisher, remediation bridge, and governed live receipt remain unbound. |

### Implementation history

The retained-row outbox and its Saga-attributed lineage live in
[`assurance_twin_outbox.py`](../../../services/core-control-plane/src/fdai/delivery/persistence/assurance_twin_outbox.py).
They use the existing atomic `StateStore` state-and-audit operations; no package schema or
migration is required. The writers require positive coverage and a bounded 30-minute
generation-to-expiry window. Forseti checks a retained review's verdict against its complete
finding set; it does not infer a verdict from a missing, stale, or conflicting source. Bus tips
carry `current: false` and `publication_complete: false`: a newer row can win after the relay's
last read, so the durable projection remains the only source of currentness. A relay pass pages
only rows whose existing nested `publication_outbox.published` value is false through the
`StateStore` dotted field filter, so it reads one bounded page instead of the retained history, and
a backlog is logged rather than raised. Row shapes stay identical to the previous release, so a
separately rolled-back Core or Operator reads them without digest mismatches.

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-09-28 | in-progress | Replaced the proposed-IaC review input with FDAI typed ActionType proposals after the owner decision that Terraform is a local deployment tool and never a governance input. Added the content-addressed proposal and what-if contracts, reviewed-effect scratch derivation with Rule-input coverage of every changed leaf value, a durable intake that stays `recorded` until writer confirmation, one current review per proposal with atomic supersession and a projection conflict guard, Forseti's production-bound review producer with Rule-generation and Inventory write fences and bounded re-derivation, and outbox relays whose pass cost is bounded by unpublished rows through a dotted `StateStore` field filter, with row shapes unchanged from the previous release. Retired proposed-IaC rows stay unavailable. | `current change`; `core/assurance_twin/{typed_proposal,proposal_effects,evaluation}.py`, `shared/providers/state_store.py`, `delivery/persistence/{postgres,assurance_twin_outbox}.py`, `delivery/assurance_twin_{review_producer,review_follow_up,proposal_intake,review_evidence}.py`, `delivery/persistence/state_store_assurance_twin_proposal_review.py`; focused typed-proposal, producer, lifecycle, ledger, source, publication, bootstrap, Operator projection, and Pantheon layout tests; Ruff and strict mypy. | Declare reviewed ActionType effect models and bind a typed what-if producer to the intake; then deliver external Checks and retain one governed source-to-rendering receipt. |
| 2026-09-27 | in-progress | Bound Heimdall's production posture producer to exact retained Inventory and immutable T0/OPA generations. Added per-Resource input completeness, durable monotonic source ordering, current-policy and current-Inventory fences, locked two-phase source/target confirmation, and restart-safe terminal recovery. | `current change`; focused evaluator, Inventory, source, writer, bootstrap, OPA drift, race, and retry checks; Ruff and strict mypy. | Bind Forseti's complete proposed-IaC producer and external Checks publisher, then retain one governed source-to-rendering receipt. |
| 2026-09-27 | implemented | Content-addressed the retained Resource generation and bounded overlay; writer admission now requires explicit complete rule findings and, for reviews, proposed-IaC evidence at the same revision. Kept production source and request producer unbound. | `current change`; `assurance_twin_inventory.py`, `assurance_twin_writers.py`, focused Inventory and publication tests. | Bind an accountable complete evaluator and proposed-change source, resolve pending relationships, publish content-free bus requests, and retain a governed runtime receipt. |
| 2026-09-27 | implemented | Added independent Heimdall report and Forseti review writers with exact-revision atomic state/outbox/audit and supervised replay relays. An unavailable or conflicting source cannot synthesize a review verdict. | `current change`; `assurance_twin_writers.py`, `assurance_twin_publication.py`, focused Core, Operator, and Console checks. | Bind trusted production evidence and retain a governed runtime receipt. |
| 2026-09-09 | in-progress | Linearized matching review replay against a concurrent conflict tombstone with a second revision and digest read. The confirmation remains read-only and appends no audit entry, while a conflict that lands between the two reads is returned as unavailable. | `current change`; focused persistence and delivery checks passed 45 tests, including a forced read-versus-tombstone interleaving, and Ruff passed. | Preserve the same read-only linearization when a trusted producer or transactional publisher is bound. |
| 2026-09-09 | in-progress | Made matching change-review redelivery a true read-only no-op and ordered the bounded recent-review projection by canonical evidence generation time instead of write recency. The read fails explicitly above its 1,000-row capacity rather than returning a misleading partial order. | `current change`; focused persistence and delivery checks passed 44 tests, and Ruff passed. | Bind a trusted producer and retain governed replay evidence; the recorder remains unbound. |
| 2026-09-08 | in-progress | Closed the final Medium-or-higher review findings across persistence, activity identity, schema ownership, Operator projection identity, and Console state presentation. Posture writes now converge on the newest generated evidence, activity keys bind privacy-safe report evidence, the schema prevents the `assurance-twin` producer from impersonating another activity kind, review lists bind durable keys to exact body identities, every posture scope is visible, and withheld rows no longer read as an empty ledger. | `current change`; focused Core, contract, Operator, and Console regressions cover delayed and concurrent posture writes, suppressed stale publication, cross-scope activity identity, producer impersonation, durable-key mismatch, multi-scope summaries, and withheld-state labels. | Bind the trusted producer and retain governed live evidence; these hardening changes don't make the unbound surface operationally validated. |
| 2026-09-06 | in-progress | Bound Assurance Twin ownership in the published `agent-operational-activity` `1.2.0` JSON Schema, not only in the Python and Console validators. A posture activity now validates only with Heimdall ownership, the `assurance-twin` producer, and no observation domain, so schema-only consumers cannot accept forged ownership. | `current change`; all 15 focused operational-activity contract tests passed, including a forged owner, producer, and domain rejection. | Preserve the same relationship in every future schema version and generated consumer. |
| 2026-09-06 | in-progress | Aligned the ledger's write boundary with the Operator projection enums. Unknown freshness, review verdict, or finding severity values now fail before persistence instead of creating a successful row that every reader must withhold as malformed. | `current change`; the focused persistence suite passed 33 cases, including zero-write regressions for all three enum classes. | Keep write and read enum sets synchronized when the projection contract evolves. |
| 2026-09-06 | in-progress | Preserved idempotent replay for pre-canonicalization review rows. Conflict comparison now normalizes a legacy row's timestamp only in comparison material, while the retained row and its recorded digest stay byte-compatible, so an equivalent offset cannot create a permanent false conflict tombstone. | `current change`; the focused persistence suite passed 32 cases, including a legacy `Z` row replayed by an equivalent offset. | Retire the compatibility path only after governed migration evidence proves no legacy rows remain. |
| 2026-09-06 | in-progress | Registered all three Assurance Twin read routes under the Operator Service `operational-state` data source. `/system/data-sources` now reports their authoritative PostgreSQL owner and unavailable reason, so the Console doesn't issue an ownerless read when that projection is not configured. | `current change`; Operator Service composition and its focused source-ownership test passed. | Bind a trusted producer and retain governed runtime evidence; source ownership only makes the existing read surface explainable. |
| 2026-09-06 | in-progress | Normalized every persisted posture and review `generated_at` value to canonical UTC before digesting or writing it. Equivalent offset timestamps now remain idempotent, and bounded review queries can retain newest-first lexical ordering without excluding a newer instant because it used a different offset. | `current change`; `state_store_assurance_twin_posture.py`; 31 focused persistence tests passed. | Bind a trusted producer and retain governed runtime evidence; canonical timestamp storage does not make the unbound recorder operationally validated. |
| 2026-09-02 | in-progress | Added the Heimdall-owned bounded posture/review activity tip (`agent.operational-activity` schema `1.2.0`, `assurance-twin.posture` kind), the durable `state_kv` posture-report and change-review ledger, the read-only `/assurance-twin/posture`, `/assurance-twin/reviews`, and `/assurance-twin/reviews/{review_id}` Operator API operations, and the localized read-only Console panel with drill-down review detail. | `current change`; 32 focused core, Operator API, and Console checks passed; the Console typecheck, build, and localization catalog-parity gates passed. | Bind the production `Inventory` source, wire ambient change events to a production publisher, and add a remediation-proposal bridge. |
| 2026-09-03 | in-progress | Hardened the same surface after an independent review found seven defects: bound the recorder to an accountable Heimdall trigger on its declared `object.event` subscription at the composition root; made a conflicting `review_key` redelivery fail closed with an explicit unavailable tip instead of split truth; persisted and projected bounded activity, correlation, and evidence-digest provenance for event-to-report replay; made the Operator API and Console withhold stale, unavailable, unknown, malformed, and digest-mismatched rows as explicit gaps instead of usable results; added the `agent-operational-activity` N/N-1 compatibility edge with regenerated Python/TypeScript artifacts and a schema-`1.2.0`-aware Console decoder; and preserved opaque review-key identity in Console routing. | `current change`; 110 focused core, Operator API, and Console checks passed, plus the service-compatibility focused gate, contract generation, project ruff and strict mypy, Console typecheck and build, and the catalog-parity/translation/roadmap-tracking gates. | No governed live runtime receipt exists: no upstream component publishes the ambient twin candidate events yet, and the production `Inventory` binding and remediation-proposal bridge remain not-started. |
| 2026-09-03 | in-progress | Corrected the same surface after a second independent review. Removed the ambient `object.event`/Huginn trigger and its Heimdall and composition-root bindings, because an attacker-influenced ingress attribute must never become authoritative Twin evidence; no replacement untrusted ingress was added, so the recorder is now unbound. Made a conflicting `review_key` redelivery write a durable conflict tombstone so the Operator API and Console always render that identity unavailable. Made `blocks_action` a strict present boolean, with a missing or string value rendered as `evidence_malformed` unavailable. Moved the review drill-down onto an exact query value (`/assurance-twin/review?review_key=`, Console `/assurance-twin?review=`) so an opaque key containing `/` round-trips byte for byte without normalisation. Reverted the `agent-operational-activity` compatibility-matrix edge, restoring the historical independent-service live receipts and local transition evidence to their pre-change values instead of relabelling them. | `current change`; focused core, Operator API, and Console checks passed with ruff, strict mypy, Console typecheck/build, and the catalog-parity/translation/roadmap-tracking/design gates. | No trusted producer exists, so no component writes these rows, the production `Inventory` binding and remediation-proposal bridge remain not-started, and no governed live runtime receipt exists. |
| 2026-09-03 | in-progress | Closed two more independent-review findings on the still-unbound surface. (1) A change-review activity tip cannot be atomically ordered with the ledger's CAS-based conflict tombstone: the durable write and the bus publish are separate, unordered async steps, so either a completed or an unavailable tip could reach a subscriber describing a row a concurrent redelivery had already durably superseded, with no way to retract an already-published stale tip. Rather than add a speculative lock or an unshipped transactional outbox, `record_change_review` now never calls `publisher.publish` for either outcome; the durable ledger, Operator API, and Console stay the sole source of truth for review state, and a conflict stays durably unavailable there regardless. Posture-report publication is unaffected: a posture write has no conflict tombstone, so a published completed tip only asserts "this report was recorded," which stays true even after a later report supersedes it. (2) The ledger's write path now enforces every write-side bound the Operator API's projection already enforces on read: a finding's `evidence_refs` and a report/review's `reason_codes` are each rejected above 200 entries or for a blank, over-512-character, or duplicate entry, and `evidence_source_revision` is rejected when blank or over 512 characters - all before persistence or publication, mirroring `_strict_string_list`/`_bounded_identity` in `assurance_twin_posture_projection.py` exactly. | `current change`; 278 focused core, delivery, persistence, and Operator API checks passed (229 core-control-plane + 49 operator-service), plus ruff check/format and mypy --strict (0 errors) on every touched file. | No trusted producer exists, so no component writes these rows; the production `Inventory` binding, the remediation-proposal bridge, and a change-review activity-publication design that survives the CAS/async-publish ordering hazard all remain open; no governed live runtime receipt exists. |
| 2026-08-31 | implemented | Added the strict semantic compiler coordinator and runtime composition seams. Verification requires exact question lineage, compiler revision, evidence citations, and result bounds; invalid plans become explicit ambiguity and publish only content-free no-authority discovery gaps. | `current change`; 50 focused query and runtime composition checks passed. | Bind a governed model compiler and discovery sink, then retain one authenticated runtime receipt. |
| 2026-08-14 | in-progress | Adopted the implementation ledger and separated tested Twin primitives from unbound delivery surfaces; earlier provenance wasn't reconstructed. | Current change; focused assurance-twin, security-assessment, and reporting tests cited in the scope table. | Bind production evidence and delivery surfaces, then collect governed runtime evidence. |
| 2026-08-21 | in-progress | Removed the lexical natural-language grammar from the default Twin compiler. Unbound compilation now returns `semantic_model_unavailable`, while the deterministic read-only verifier remains authoritative for every injected compiler. | `current change`; focused Assurance Twin checks passed 45 cases and the semantic-routing guard reports no migrate paths. | Bind a Twin-specific model projection and ChatOps intake before describing natural-language compilation as available. |

### Remaining work

- [ ] Bind an authoritative `Inventory` source to the projection and prove freshness, bounded delta
  handling, and deterministic replay in a focused integration test.
- [x] Implement the provider-neutral semantic compilation and discovery seams, with tests proving
  every accepted query is bounded, evidence-cited, exact-input-bound, and read-only while unsupported
  questions remain explicit unavailable or ambiguity outcomes.
- [ ] Bind a concrete governed model compiler and ChatOps intake, then retain an authenticated
  runtime receipt.
- [ ] Wire ambient change events to a production `IacReviewPublisher` and record a governed shadow
  receipt that links the change, finding, rule evidence, and published review.
- [x] Stage report and review publications with the exact durable revision and append-only audit
  in one transaction, then relay only validated pending revisions; focused restart, reorder, and
  conflict tests cover the repository-local path.
- [ ] Route abstained questions and remediation proposals through the discovery and normal risk-gated
  action paths, with tests proving the Twin never executes or raises authority.
- [ ] Bind a trusted retained-evidence source and production inventory/change ingress to the
  independently supervised Heimdall/Forseti writers. Content-free requests are not evidence;
  an attacker-influenced ambient ingress payload must not become authoritative Twin evidence.
- [ ] Declare reviewed ActionType property-effect models with governance review provenance and
  bind a typed-pipeline what-if producer that submits exact proposal and what-if pairs to the
  durable intake. Until both exist, every submitted proposal settles explicitly unavailable.
- [ ] Capture a governed runtime receipt for one complete inventory-to-report rendering. This
  requires the production `Inventory` binding and a trusted producer, so neither implementation nor
  validation is complete: no live receipt exists and none may be fabricated.

## Why not a chatbot

A retrieval-augmented chatbot answers the review use cases with five structural
defects. The twin inverts each one.

| Chatbot limitation | Consequence | Assurance Twin shift |
|--------------------|-------------|----------------------|
| **Reactive** - answers only when asked | reproduces the review-queue lead time (wait for a request, then wait for a human) | **Ambient** - reviews changes proactively on the change event, before a request exists |
| **Ungrounded** - vector similarity over prose | hallucinated verdicts reach a deploy | **Ontology-grounded** - answers are deterministic graph queries with a cited rule path |
| **Stateless** - reads documents, not the live estate | no real evidence for "why is this non-compliant" | **Stateful twin** - a live projection of the subscription kept fresh by inventory delta |
| **Inert** - returns information and stops | a human still fixes it by hand | **Action-bridging** - an answer can carry a shadow remediation-PR proposal |
| **Static** - the index goes stale | wrong answers after a policy change | **Self-improving** - unanswered / abstained questions feed the rule discovery loop |

## The five shifts

### 1. Ambient (reactive to proactive)

The current implementation stops before this production flow. A stable `sha256:` Resource
revision covers the active snapshot identity and content and the bounded realtime Resource
overlay (including observation times). `load_at_revision` re-reads and rejects later content.
A trusted, injected source must re-read that revision
and provide positive rule coverage, evaluated rule ids, a rule-set digest, and a digest of the
complete finding set. An empty finding set is clear only after that independent complete rule
assessment. Pending relationship overlays, absent evidence, revision drift, stale or
conflicting sources remain unavailable. None of these read-only records grants approval,
mutation, or execution authority.

Forseti reviews FDAI's own typed change proposals, never an IaC plan. The owner decision of
2026-09-28 is that Terraform is a local deployment tool and must not be used at the governance
level, so a Terraform plan, rendered template, or pull-request diff is never a Twin review input.
One review input binds an exact ActionType id and version, exact target Resource refs, a
canonical parameter digest, and one completed what-if or dry-run result bound to the same
content-addressed proposal digest. The what-if must be passed, complete, current, non-synthetic,
from the `simulation_engine` authority class, and must name exactly the proposal's targets.
A reviewed, declared effect model for that exact ActionType version maps the parameters onto
top-level target properties. Every parameter must be consumed or declared inert.

The twin reviews typed changes as they are proposed, not on request. A typed-pipeline producer
submits the proposal and what-if to a durable, content-addressed intake. Forseti's producer
applies the declared effect to a scratch projection of the proposal's targets in the retained
Inventory revision, and the control loop T0/OPA generation evaluates the changed targets with
complete receipts. The retained and predicted values of each written property are compared leaf
by leaf, and every leaf that actually changes must be covered by a declared input of at least one
applying Rule for that target. An input on a parent path covers its children; a child input never
covers its parent or siblings, and unchanged leaves need no coverage. Otherwise the change is
`effect_unassessed`. Forseti's writer then publishes a bounded read-only review through the
exact-revision outbox. A missing effect model, an absent, stale, incomplete, failed, or
conflicting what-if, a target outside the retained revision, an undeclared parameter, or an
unassessed property settles the proposal unavailable instead of `clear`.

The review key is the proposal ref, so the ledger keeps exactly one current review per proposal.
A newer revision supersedes the older review, its outbox, and its Saga lineage in one
compare-and-set; a delayed older revision never replaces it. The Operator projection also treats
two usable reviews for one change handle as a conflict gap. An intake row stays `recorded` until
the writer confirms that exact review. When a Rule-generation or Inventory revision change blocks
the writer's fenced commit, Forseti retires the stale request so the relay stops. It re-derives
while the what-if is fresh, within at most three derivation attempts, and otherwise settles the
proposal unavailable with `rule_generation_changed` or `inventory_revision_changed`. An external
Checks publisher can later render the retained review; it is delivery, not an input.

Example: a typed proposal would set `public_access: enabled` on one storage account. With a
reviewed effect model for that exact ActionType version and a completed what-if for that exact
proposal, Forseti publishes a `blocked` review that cites the violated public-access Rule for that
target before anyone asks. The review never approves, executes, or promotes the proposal.

### 2. Ontology-grounded (retrieval to graph query)

The twin is the ontology graph, not a prose index. Every governed resource is a
`Resource` ObjectType; relationships are the existing typed LinkTypes
(`contains`, `attached_to`, `depends_on`), and rule matches are `Finding`s (see
[llm-strategy.md](../architecture/llm-strategy.md#ontology-foundation)). "Why is this resource
non-compliant" is answered by a graph traversal that returns a concrete evidence
chain, for example:

```text
Resource:storage-x --attached_to--> Resource:subnet-y
subnet-y --contains(-1)--> vnet-z
Finding: storage-x violates rule:object-storage.private-endpoint.required
  evidence: rule path + evaluated property (publicNetworkAccess=Enabled)
```

The chain is deterministic and reproducible: the same twin state yields the same
answer regardless of who asks or how the question is phrased.

### 3. Verifiable (text-to-query, not text-to-answer)

This is the core mechanism. The model is used to **compile a natural-language
question into a typed ontology query** and, at the end, to **render the result
back into prose**. It is never the source of the fact.

![3. Verifiable (text-to-query, not text-to-answer). The main stages are NL question, model: compile / NL to typed ontology query, verifier: query is / well-typed and read-only, T0: execute query / over the twin (deterministic), Assurance Twin / ontology graph, grounded result set, model: explain / result + cite rule path, answer + provenance / + confidence + what-if, abstain: 'not known'.](../../diagrams/generated/fdai-roadmap-operations-assurance-twin-01.en.svg)

- **Compilation is verified**: the compiled query MUST be well-typed against the
  ontology schema and MUST be read-only; a query that fails the check is rejected,
  not executed. This is the same fail-closed posture as the T2 verifier.
- **Compilation evidence is exact**: runtime composition requires the compiler revision, exact
  question digest, bounded result limit, and at least one evidence reference. Invalid or injected
  output becomes an explicit ambiguity result and can emit only a content-free discovery gap.
- **Answers route through the tiers**: an exact rule/graph match resolves at
  **T0**; a fuzzy question near a known pattern uses **T1** similarity; only a
  genuinely novel or ambiguous question reaches **T2**, and T2 output clears the
  [quality gate](../../../.github/instructions/architecture.instructions.md#llm-quality-gate-required-for-t2)
  (mixed-model cross-check, verifier, grounding) before it is shown.
- **Grounding or abstain**: every answer cites the rules and graph nodes that
  justify it. An answer that cannot be grounded returns "not known", never a
  guess. Hallucination is closed off by construction, not by prompt tuning.

### 4. Action-bridging (inert to proposing)

An answer may carry a proposed fix, but the twin never executes. When a question
resolves to a fixable Finding, the twin can attach a **shadow remediation-PR
proposal** built from the rule's `remediates` ActionType. Acting on it is the
existing gated path: `risk-gate -> executor -> delivery`, with HIL for anything
high risk (see [risk-classification.md](../decisioning/risk-classification.md)). Chat and the
console remain read-only surfaces; a proposal is a link to a PR, never a button
that mutates.

Example: "fix the storage accounts missing a private endpoint" resolves to a set
of Findings; the twin opens one shadow remediation-PR per resource (batched under
the blast-radius cap), each with a rollback contract, and routes to HIL. Nothing
changes until a human approves.

### 5. Self-improving (static to living)

Questions are a discovery signal. A question the twin **abstains** on, or a
recurring question with no covering rule, is emitted as a candidate to the
autonomous rule discovery loop in
[architecture.instructions.md](../../../.github/instructions/architecture.instructions.md)
(the same loop that watches HIL patterns and overrides). The candidate carries
provenance and passes the standard quality gate before it can enter the catalog;
the twin never mutates the catalog directly. The knowledge surface therefore
tracks the estate instead of going stale.

The first design considered binding a model directly and using a lexical compiler when that model
was unavailable. That fallback would invent meaning and let presentation code become semantic
authority. The revised design exposes provider-neutral compiler and discovery seams, keeps the
default explicit unavailable, verifies every injected plan deterministically, and sends only a
question digest and abstention code to discovery. No raw question, decision, or mutation authority
crosses that handoff.

## Twin as simulator (what-if over the whole graph)

The per-action what-if verifier
([architecture.instructions.md](../../../.github/instructions/architecture.instructions.md#llm-quality-gate-required-for-t2))
predicts the effect of a single change. The twin generalizes it to the whole
graph: apply a proposed change to a **scratch projection** and evaluate the
consequences before anything touches the live estate. One simulation surface
serves all three verticals, which is why the twin simplifies rather than
complicates the design.

| Vertical | Simulation question | Answered by |
|----------|---------------------|-------------|
| **Change Safety** | what is the blast radius of this change? what breaks downstream? | traverse `attached_to` / `depends_on` from the changed `Resource`; report affected set + newly-violated rules |
| **Resilience (DR)** | does the estate meet target RPO/RTO? what fails over? | replay a region/zone-loss scenario against the twin; report resources without a recovery path and the projected RPO/RTO gap |
| **Cost Governance** | what is the cost delta of this change / this optimization? | apply the SKU/scale delta on the projection; report the projected unit-cost change |

- **Read-only and deterministic**: a simulation mutates only the scratch
  projection, never the live estate or the audit store. It is a T0-flavored pass:
  static graph evaluation resolves most of it; bounded read-only probes confirm
  the rest, exactly as [deployment-preflight.md](../deployment/deployment-preflight.md) does.
- **Shadow-first**: each simulation-derived finding ships in shadow mode and is
  promoted per the shadow-to-enforce rule only after its accuracy and
  false-positive rate are measured on the frozen scenario set
  ([goals-and-metrics.md](../architecture/goals-and-metrics.md)).
- **Fidelity-measured**: `core/assurance_twin/fidelity.py`
  (`SimulationFidelityLedger`) is the mechanism behind that promotion. It joins
  each **predicted** effect (cost delta, blast-radius count, RPO/RTO gap) with
  the **actual** observed outcome by a stable prediction id and accumulates
  per-predictor MAE, MAPE, and a within-tolerance rate. `is_reliable` turns
  those into a fail-closed promotion signal: a predictor below a minimum sample
  count or above a MAPE bar is not reliable, so the caller keeps it in (or demotes
  it back to) shadow. This stops an unmeasured what-if from acting as an oracle -
  a simulation that does not come true loses its enforce eligibility automatically.
- **Adaptive but promotion-gated**: `effect_model.py` evaluates no-op and action branches with a
  versioned active model while a separate challenger learns only from post-cutoff, scorable
  `ResponseOutcome` records. The scheduled growth job persists challenger revisions through
  optimistic concurrency. It never replaces the active key. Active/challenger divergence and
  evidence below `quasi_experimental` force review. `rca/temporal_causality.py` adds differenced,
  lagged correlation with optional confounder adjustment, reverse-direction checks, and multiple-
  testing correction; this observational path can reach only `predictive_precedence`, never an
  experimental causal grade.
  `runtime.py` loads active and challenger models for at most 32 current-state branches. Missing
  active models, low evidence, or divergence require review; the T1 caller remains abstained and
  sends the learned action through normal re-verification.

### Operational binding and guard

`FDAI_DYNAMIC_CONFIG_JSON` enables scalar Dynamic in a deployed core runtime. The strict object
contains ActionType-specific metric, objective, effect delta, uncertainty, divergence, and
freshness settings; exact active and challenger model records; and a causal-receipt digest
allowlist. Startup rejects partial fields, unknown fields, missing model pairs, conflicting durable
models, or a model whose receipt isn't allowlisted. Without this setting, Dynamic remains explicitly
unavailable and existing deterministic routing is unchanged.

The Azure adapter reads `operational_context.metric_values` from promoted inventory evidence and
builds one bounded action branch. The active and challenger models come from the durable StateStore
registry. A configured Dynamic simulation becomes a lower-only guard before T1 reuse enters the
safety check: unavailable requests, missing models, divergence, graph review reasons, invariant
failure, or missing Dynamic audit evidence route to human review. A prediction never approves an
action or raises its autonomy ceiling.

### Graph-wide temporal Dynamic

The existing action/metric model remains the first Dynamic layer. Graph-wide simulation extends it
with `OperationalStateTrajectory`, `GraphEffectModel`, `DynamicInvariant`, and
`TrajectoryOutcome`. A trajectory pins the ontology release, graph and inventory revisions,
evidence cutoff, horizon, normalized object/metric slices, intervention references, watermarks,
completeness, truncation, and a deterministic digest. It is not the conversation and execution
`TrajectoryEnvelope`, and neither record is evidence of provider state by itself.

Graph propagation follows only declared LinkType paths under fixed edge, depth, slice, and horizon
bounds. Deterministic topology effects run before verified active models. Interaction terms prevent
parallel action effects from being treated as a linear sum. A missing model, stale cutoff, cycle,
unavailable baseline, truncation, low causal grade, or active/challenger divergence requires review.
Challenger predictions never rank a branch.

Every graph simulation request carries a non-empty bounded invariant tuple. The simulator evaluates
each invariant over the active trajectory and returns the exact per-invariant result. A violation or
unscorable invariant adds a stable review reason and cannot raise authority. During execution, an
observed invariant violation cannot rewrite a running plan; it stops forward dispatch and re-enters
the existing typed recovery path.

The graph runtime records the predicted digest, exact trajectory, and challenger model references
in the StateStore trajectory ledger before returning simulation evidence. Heimdall's complete independent observation closes the episode
through `close_trajectory_outcome` as matched or mismatched. Identity mismatch, censoring,
incompleteness, and unscorable comparison leave it open and never update a model. Identical closure
replay is a no-op; conflicting replay fails closed. The off-path graph closure runner builds learning
observations only for complete comparable challenger slices and applies them through
`StateStoreGraphEffectModelRegistry`. Active graph models remain immutable until separate reviewed
promotion evidence applies. The scheduled growth job uses `MetricGraphTrajectoryOutcomeSource` to
observe due open episodes through the configured metric provider after the telemetry grace window.
It emits a closure command only when every predicted slice has independent finite evidence;
otherwise the episode remains open without a fabricated value.

`GET /dynamic-assurance` is a Reader-only durable projection over scalar and graph model
counts, sample and error summaries, and open or closed trajectory episodes. It exposes no model
registration, promotion, approval, or execution command.

## Assessment report (subscription posture, on demand)

The proactive per-change review composes into a full-estate report. Running every
applicable rule against the current twin produces a `PostureAssessmentReport` - a
generalization of the `DeploymentReadinessReport`
([deployment-preflight.md](../deployment/deployment-preflight.md)) from a single deploy to the
whole subscription. Each entry keeps the same three required parts - grounded
evidence (a cited rule), a severity, and a resolution mapped to a concrete lever -
so the report is actionable, not just a score. The console renders it through a
read-only `ReadPanel` route
([project-structure.md](../architecture/project-structure.md#injectable-seams)); it issues no
privileged calls.

### Deep security assessment

The security-scoped report keeps more context than a severity-only finding
list. Collectors normalize Azure Resource Graph properties, server parameters,
Defender assessments, WAF records, policy compliance, diagnostic settings, and
version/advisory matches into `SecurityControlObservation` values. Each
observation records the current and expected values, control status,
applicability, source and collection time, evidence references, remediation and
validation steps, priority and due interval, CVE applicability and patch state,
compliance mappings, and managed-service patch notes.

Applicability is a bounded enum (`applicable`, `not_applicable`, `unknown`) and
observation timestamps are timezone-aware. An `unknown` control is an evidence
gap, not an actionable recommendation. Recommendations are derived only from
failed or warning controls with grounded remediation text.

The assessment records which source supplied each fact:

| Source data | Information extracted |
|-------------|-----------------------|
| Azure Resource Graph resource properties | AKS version, private API, RBAC, network policy, Entra/local-account state, workload identity, image cleaner, add-ons, upgrade channels; MySQL network, backup, HA, encryption, and version |
| Azure Resource Graph `sku` and `kind` | AKS and MySQL service tier and resource kind |
| AKS node-pool resource properties | Node image version, secure boot, and virtual TPM |
| MySQL server parameters | Secure transport, allowed TLS versions, and audit logging |
| Azure Monitor diagnostic settings | Whether approved platform logs and metrics are routed to an evidence store |
| Defender for Cloud assessments | Runtime protection coverage and actionable unhealthy findings |
| Application Gateway WAF logs | Matched/blocked rules, attack details, resource, and event evidence |
| Security bulletins and advisory matches | CVE id, applicability, patch state, source URL, and managed-service backport note |
| Rule and compliance metadata | Expected value, rationale, remediation, validation, priority, due interval, and compliance controls |
| Report-feed timestamps and source errors | Evidence window, source availability, partial reads, and freshness gaps |

After an observed ARG or ARM inventory snapshot is promoted, the inventory job
reads only the active AKS, node-pool, and MySQL records under a bounded row cap,
runs the deterministic Azure analyzer, and writes timestamped control signals to
the durable report feed. Supplemental providers can add server parameters,
diagnostic-setting state, Defender coverage, and advisory matches. When they are
not configured, their controls and source coverage remain `unknown` or
`unavailable` instead of failing the control.

`build_security_assessment` remains a pure deterministic fold. It derives the
verdict and also reports:

- finding, rule, resource, resource-type, control, and evidence counts;
- pass, fail, warning, not-applicable, and unknown control counts;
- control pass rate, evidence coverage, and source coverage;
- category and resource-type distributions;
- positive controls and unknown controls;
- prioritized recommendations with due timestamps and validation steps;
- CVE applicability, patch status, and compliance mappings;
- available, partial, unavailable, and stale data-source counts.

A `clear` verdict describes the observed risk only. It does not imply that the
assessment is complete. `completion_status`, source coverage, stale sources,
unknown controls, and missing evidence stay visible so an unavailable provider
cannot turn into a false clean result.

The read-only `Security Assessment` catalog report renders these projections
through the existing Reports page. It uses KPI, control-status, chart, table,
group, tabs, and note widgets, so no new browser execution surface or
privileged identity is introduced.

## Module placement

The subsystem lives in `core/assurance_twin/` and imports only `shared/`
contracts and providers, like every other core subsystem
([project-structure.md](../architecture/project-structure.md#module-boundaries)). It holds no
cloud SDK and no privileged identity.

| Component | Responsibility |
|-----------|----------------|
| `projection` | Build immutable in-memory baselines and apply scratch diffs. A read-only retained Inventory snapshot and bounded realtime Resource overlay can supply one fresh projection; runtime composition and relationship-aware maintenance remain target bindings. |
| `query` | Verify and execute well-typed read-only queries with a deterministic pattern compiler. A model-backed compiler is a Protocol target. |
| `review` | Publish precomputed findings through `IacReviewPublisher`. Change-signal evaluation and a production publisher are target bindings. |
| `report` | assemble the `PostureAssessmentReport` from Findings |
| `chat` | Provide immutable grounded chat-session values and a persistence Protocol; no browser or delivery binding. |
| `graph_effect` / `graph_runtime` | Propagate bounded graph effects, evaluate required active-trajectory invariants, and return review-only simulation evidence. |
| `trajectory_ledger` | Persist predicted trajectory episodes and atomically close only complete comparable outcomes through StateStore. |
| `graph_closure` | Drain independent observations off-path, update challenger slices, and audit that active mutation and promotion did not occur. |
| `typed_proposal` | Define content-addressed typed ActionType proposals, what-if results, and the retained typed-proposal readback that Forseti's writer re-validates. |
| `proposal_effects` | Resolve an exact reviewed ActionType effect model and derive the predicted scratch change for the proposal's retained targets, or return an explicit unavailable reason. |
| `posture_activity` | Build Heimdall's existing bounded posture activity and Forseti's separate private, authority-free review activity. The delivery recorder stages each with its retained record and Saga-attributed append-only audit; two supervised relays publish revision-bound envelopes. An injected trusted source is still required to compute findings. |

`PostgresTwinInventorySource` loads the active observed, full-scope snapshot from the retained
Inventory database in a repeatable-read transaction. It rejects stale, incomplete, or superseded
coverage, limits baseline Resources and realtime deltas, and refuses pending relationship changes
that the Resource-only scratch projection cannot represent. Heimdall's production posture producer
reuses the control loop's immutable T0/OPA generation off the event-loop thread, requires every
Resource's declared Rule inputs and receipts, and holds Inventory promotion and realtime graph
locks through source persistence and writer confirmation. Forseti's review producer shares that
Inventory source and T0/OPA generation. It reviews only typed ActionType proposals from the durable
intake and only through reviewed effect models; an empty catalog keeps every proposal unavailable
rather than turning an unassessed change into a misleading `clear` verdict. An Inventory snapshot
id by itself is not the exact revision that either producer requires.

Target delivery adds one intent to the existing `chatops` adapter (question in, grounded answer
out) and reuses the `gitops-pr` adapter for proposals and Checks API reviews. The current
repository has only the `IacReviewPublisher` Protocol and test double, not a production publisher
or ChatOps binding. Adding them doesn't introduce a new privileged surface.

## Safety posture

- **Read-only twin, gated execution**: the twin and every answer are read-only;
  the only path to a mutation is a proposal that enters `risk-gate -> executor`,
  with the seven safeguards (stop-condition, rollback, blast-radius limit, dry-run, resource lock,
  idempotency, audit entry) enforced there, not in the twin.
- **Fail closed**: an ungroundable answer abstains; a mis-typed or non-read-only
  compiled query is rejected; a stale twin (`Inventory` freshness beyond
  `freshness_ttl`) refuses to answer estate-state questions rather than answer
  from ghost data, mirroring `RequiresInventoryFresh`
  ([llm-strategy.md](../architecture/llm-strategy.md)).
- **Untrusted input**: question text and change payloads are untrusted and may
  carry prompt injection; the verifier and the read-only query contract are the
  authority, never the model's free text (threat model in
  [security-and-identity.md](../architecture/security-and-identity.md)).
- **Audited**: every proposal, review, and simulation-derived finding writes an
  audit entry with its grounding; a read-only question that produces no proposal
  is logged but is not an action.

## Phasing

The twin lands incrementally on top of the existing phases; it introduces no new
tier and no new autonomy that the risk gate does not already govern.

| Phase | What lands | Gate |
|-------|------------|------|
| **P2** ([phase-2-quality-and-t1.md](../phases/phase-2-quality-and-t1.md)) | twin projection from inventory; verified text-to-query; grounded answers via the quality gate; abstain-to-discovery feedback | answers are grounded or abstain; zero ungrounded answers on the scenario set |
| **P3** ([phase-3-integrated-loop.md](../phases/phase-3-integrated-loop.md)) | ambient per-change review; whole-graph simulation for Change/DR/FinOps; shadow remediation-PR proposals; `PostureAssessmentReport` panel | each simulation finding measured shadow-first before enforce |

## Next steps

| To learn about | Read |
|----------------|------|
| the ontology the twin queries | [llm-strategy.md](../architecture/llm-strategy.md#ontology-foundation) |
| the tiers and quality gate answers route through | [architecture.instructions.md](../../../.github/instructions/architecture.instructions.md#llm-quality-gate-required-for-t2) |
| the deploy analyzer the report generalizes | [deployment-preflight.md](../deployment/deployment-preflight.md) |
| detection findings the review consumes | [observability-and-detection.md](../rules-and-detection/observability-and-detection.md) |
| where the subsystem sits in the repo | [project-structure.md](../architecture/project-structure.md#module-boundaries) |
| how proposals are risk-classified | [risk-classification.md](../decisioning/risk-classification.md) |
