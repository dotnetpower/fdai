---
title: Hierarchical Conversation Planning
---

# Hierarchical Conversation Planning

This design replaces the single-tool semantic turn plan with one bounded intent graph for simple,
compound, multilingual, and multimodal FDAI Console questions. The graph has no execution
authority. Deterministic validation binds each read goal to an available capability, and Bragi
renders only evidence and verified limitations.

> Scope: This path is read-first. A write request can produce a typed draft only. Existing safety,
> human approval, rollback, impact-scope, and audit gates remain authoritative.

## Design at a glance

![Design at a glance. The main stages are Text, screen, image, document, Bounded context resolver, T1 mini-model intent graph, Deterministic graph validator, Available capability binding, T2 reasoner retry, Read task DAG, Evidence ledger, Claim verification, Bragi presentation.](../../diagrams/generated/fdai-roadmap-interfaces-hierarchical-conversation-planning-01.en.svg)

The T1 mini-model interprets language and proposes a graph. It sees only capabilities available to
the current principal and deployment. The validator blocks unknown capabilities, cycles,
unresolved dependencies, invalid arguments, scope invention, and writes outside a confirmation
draft. T2 is never the first semantic planner. Core retries one frame or plan stage with T2 only
when the T1 model or provider is unavailable and the active typed policy permits that exact stage.
Schema, build, manifest, and frame-plan verification failures terminate as clarification,
unsupported, or held without T2. A valid T1 clarification, action draft, scope denial, or
evidence-execution hold also never spends T2 capacity. Golden campaign requests select the separate
`golden_campaign_no_t2` profile, so provider unavailability cannot trigger a campaign fallback.

The model-backed semantic judgment boundary interprets the whole bounded turn and may propose a canonical social intent such as `greeting` or `self_introduction`. Core validates that exact typed intent and returns
a direct response without a query or evidence read. Runtime code never infers the intent from keywords, phrase tables, regular expressions, token matching, or hard-coded utterances.
An operational request combined with social language remains an operational intent when the model
preserves that meaning. Invalid, unavailable, ambiguous, or low-confidence judgment fails closed
without lexical fallback, and no path gains execution authority.

## Implementation status

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| Semantic frame, verified plan, and intent graph | implemented | [`semantic_planning.py`](../../../services/core-control-plane/src/fdai/core/conversation/semantic_planning.py), [`semantic_planning_cascade.py`](../../../services/core-control-plane/src/fdai/core/conversation/semantic_planning_cascade.py), [`semantic_runtime.py`](../../../services/core-control-plane/src/fdai/core/conversation/semantic_runtime.py), focused semantic-planning tests | Whole-turn proposals are bounded, release-scoped, verified, and projected without execution authority. T1 is always attempted first. The default typed policy permits one same-stage T2 retry only for T1 unavailability; invalid frames, schemas, builds, and deterministic plan mismatches fail closed. |
| Model-backed social direct response | implemented | `semantic-judgment.v3.yaml`; [`semantic_judgment.py`](../../../services/core-control-plane/src/fdai/delivery/azure/llm/semantic_judgment.py); [`semantic_planning.py`](../../../services/core-control-plane/src/fdai/core/conversation/semantic_planning.py); [`semantic_turn.py`](../../../packages/service-contracts/src/fdai_service_contracts/semantic_turn.py); [`semantic_turn_processor.py`](../../../services/core-control-plane/src/fdai_core_service/semantic_turn_processor.py); focused model-routing, usage, redaction, and stream tests | The schema-validated semantic judgment model selects the canonical intent from the whole turn. Core validates only the enum and dispatches the typed response. Direct responses retain measured model usage and identity, while redacted request/response trace remains request-opt-in. Operator inspects no operator text and emits `done` alone. Model failure has no lexical fallback. |
| Structured causal investigation | implemented | `semantic_investigation.py`; `semantic_investigation_planning.py`; investigation query-node and presentation tests; focused investigation checks | A target-bound causal diagnosis carries exact source spans, typed entity roles, symptom direction, temporal cues, ordered LinkType sides, competing hypotheses, evidence standard, and answer shape. Core verifies those atoms and compiles entity resolution, multi-hop expansion, aligned windows, topology diff, symptom comparison, and support/refutation waves without a model-authored plan. Generic declared-scope causal evidence keeps the existing bounded plan. If fewer than two hypothesis results reach presentation, the target and symptom comparison remain visible with an explicit evidence limitation instead of a false complete diagnosis. |
| Production Core semantic runtime composition | implemented | [`wire_semantic_query.py`](../../../services/core-control-plane/src/fdai/composition/wire_semantic_query.py), [`semantic_query_model_targets.py`](../../../services/core-control-plane/src/fdai/composition/semantic_query_model_targets.py), [`bootstrap.py`](../../../services/core-control-plane/src/fdai/runtime/bootstrap.py), focused semantic-query composition tests | Azure T1 and T2 planning adapters are bound separately. Principal-scoped manifests, secured ObjectSets, read functions, and bounded DAG execution are composed when prerequisites are available. |
| Versioned cross-service semantic-turn contract | implemented | [`semantic_turn.py`](../../../packages/service-contracts/src/fdai_service_contracts/semantic_turn.py), [`operator-core-request/1.4.0.json`](../../../packages/service-contracts/src/fdai_service_contracts/schemas/operator-core-request/1.4.0.json), [`semantic_turn_processor.py`](../../../services/core-control-plane/src/fdai_core_service/semantic_turn_processor.py), [`test_semantic_turn_processor.py`](../../../services/core-control-plane/tests/test_semantic_turn_processor.py) | Request 1.4 adds the bounded `include_model_trace` opt-in while preserving N-1 decode. Projections bind identity, purpose, deadlines, digests, dispositions, evidence, and observational model metadata without granting execution authority. |
| Durable Operator bridge and Console projection | implemented | [`semantic_turn_runtime.py`](../../../services/operator-service/src/fdai_operator_service/families/conversation/semantic_turn_runtime.py), [`postgres_semantic_turn_store.py`](../../../services/operator-service/src/fdai_operator_service/postgres_semantic_turn_store.py), [`test_semantic_turn_bridge.py`](../../../services/operator-service/tests/test_semantic_turn_bridge.py) | The Operator owns durable acceptance, outbox claims, result projection, authenticated replay, typed holds, and `done` event adaptation. |
| Event transport and deployment configuration | implemented | [`semantic_kafka.py`](../../../services/operator-service/src/fdai_operator_service/adapters/semantic_kafka.py), [`main.tf`](../../../infra/main.tf), [`test_semantic_turn_topics.py`](../../../tests/integration/infra/test_semantic_turn_topics.py) | Logical request and projection topics share the governed physical event stream and are configured for both services. |
| Structural and epistemic coverage foundations | in-progress | [`epistemic_coverage.py`](../../../services/core-control-plane/src/fdai/core/conversation/epistemic_coverage.py), [`test_epistemic_coverage.py`](../../../services/core-control-plane/tests/conversation/test_epistemic_coverage.py) | Receipt and gate contracts exist, but complete descriptor generations, runtime question receipts, and L3/L4 certification are not delivered. |
| Complete temporal, metric, causal, and relationship query surface | in-progress | [`wire_semantic_query.py`](../../../services/core-control-plane/src/fdai/composition/wire_semantic_query.py), [Ontology Query Coverage Implementation Plan](ontology-query-coverage-implementation-plan.md) | ObjectSets, set operations, projection, aggregation, and selected read functions are bound; the remaining provider-backed query kinds are incomplete. |
| Multimodal semantic planning input | not-started | [Conversation Attachments](conversation-attachments.md) | The semantic-turn request currently carries bounded text and prior-turn context, not server-validated image or document evidence. |
| Governed production certification | not-started | This document's verification contract | No retained authenticated cross-service browser receipt or randomized assurance receipt currently proves production readiness. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-08-25 | implemented | Carried the actual semantic judgment deployment, measured provider token usage, call duration, and request-opt-in redacted model trace through direct greeting and self-introduction projections. Trace is bounded, removes credential and customer-identifier patterns, retains no hidden reasoning, and does not create query, evidence, verification, or execution authority. | `current change`; request 1.4 compatibility checks passed 128 cases; focused judgment, redaction, direct projection, Operator terminal, and Console badge checks passed; strict Python and TypeScript checks passed. | Restart the exact-source local stack and retain one authenticated greeting with token usage and model trace enabled, then repeat with trace disabled to prove no durable trace is emitted. |
| 2026-08-25 | implemented | Hardened model-backed social and action-posture routing after a diverse authenticated Command Deck campaign. Self-introduction now uses closed canonical facets, intrinsic identity and authority facets can reach the evidence-free direct response, and an accepted `advise_only` judgment cannot become an action draft in the frame stage. Missing material target, comparison, or time context is clarified instead of lexically inferred. The Core local input digest now includes the prompt catalog, so a healthy process with stale semantic instructions cannot pass source readiness. | `current change`; 32 distinct browser questions and 44 durable terminal attempts covered Korean, English, mixed language, colloquial wording, typos, social plus operational requests, ambiguity, direct action, and a two-turn follow-up. Direct responses carried 0/0 checks, zero evidence references, and no investigation lifecycle. Focused prompt, routing, posture, and launcher checks passed. | Carry the selected screen Resource and verified view facts through the typed semantic request so screen-relative status, relationship, summary, and follow-up questions do not degrade to clarification or unsupported. Retain the campaign as governed evidence after the separate Ontology instance graph presentation-direction failure is resolved. |
| 2026-08-25 | implemented | Withdrew the whole-utterance greeting and self-introduction classifier because it inferred intent from phrase lists and regular expressions. Semantic judgment prompt v3 now defines the two social meanings without example utterances, and Core branches only on the schema-validated canonical model intent. Operator no longer reads operator text or emits speculative acceptance and planning frames. | `current change`; shared contract passed 19 cases, focused model-routing passed 6 cases, terminal-derived Operator lifecycle passed 5 cases, and the active prompt contract passed. | Restart the current-source stack and retain authenticated greeting, self-introduction, mixed operational, and model-unavailable outcomes without lexical fallback. |
| 2026-08-25 | implemented | Added the typed `self_introduction` direct-response intent after a request for Bragi to introduce itself entered the ordinary investigation lifecycle. The shared whole-utterance classifier now recognizes bounded Korean and English identity requests, Core renders a localized identity and authority boundary, and Operator emits only `done`. A self-introduction request combined with operational work remains on normal planning. | `current change`; focused shared contract passed 17 cases, Core planning passed 9 cases, Core terminal projection passed 2 cases, Operator presentation and lifecycle passed 3 cases, and Console strict receipt parsing passed 53 cases. | Restart the local stack and retain an authenticated self-introduction with no transient investigation UI. |
| 2026-08-25 | implemented | Moved the exact greeting classifier to the shared service contract and stopped Operator and Console from presenting speculative investigation progress before Core's direct-response terminal projection. Operator emits only `done` for an exact greeting. Console shows `Preparing answer` only after an observed progress frame and does not impose the minimum preparation delay on a direct response. Compound operational requests retain the ordinary lifecycle. | `current change`; focused Core greeting boundary passed 23 cases, Operator direct and ordinary lifecycle passed 3 cases, and focused Console stream and visual checks passed 58 cases. | Restart Core, Operator, and Console, then retain an authenticated greeting with no transient investigation UI. |
| 2026-08-25 | implemented | Added a deterministic whole-utterance greeting preflight before manifest and model-backed semantic judgment. Unicode, case, whitespace, and boundary punctuation normalize before exact matching, while greeting-prefixed operational requests remain on the semantic planning path. | `current change`; `direct_response.py`; focused classifier and complete semantic tier-routing checks passed 378 cases; task-scoped Ruff and strict mypy passed. | Restart Core and retain an authenticated Console greeting that has no investigation, query, source-unavailable, or evidence projection. |
| 2026-08-22 | implemented | Replaced broad invalid-or-unavailable T2 fallback with typed escalation triggers and policies. Interactive Console planning permits only bounded T1-unavailable fallback, while `golden_campaign_no_t2` permits none. | `current change`; focused tier-routing, shared-contract, Core processor, Operator bridge, and Console campaign checks passed. | Run the authenticated readiness probe before any 560-turn golden campaign. |
| 2026-08-20 | implemented | Aligned the bounded Azure semantic adapter with the governed frame prompt after prompt v30 exceeded the former system-prompt character ceiling and made the entire runtime unavailable before planning. The adapter retains a fixed 32,768-character system-prompt limit and the existing total request-byte limit. | `current change`; real prompt-catalog composition and over-limit adapter regressions. | Core readiness now reports the semantic runtime bound. An authenticated target-bound answer remains open because the completed pre-restart replay was not repeated. |
| 2026-08-20 | implemented | Preserved the structured causal artifact when zero or one hypothesis result reaches presentation. The artifact keeps the verified target and symptom comparison, renders only the available hypothesis rows, and names the incomplete competing-evidence set as a limitation in English and Korean. | `current change`; focused investigation and Operator presentation checks. | Retain one authenticated target-bound slowdown answer and viewport evidence before claiming runtime validation. |
| 2026-08-20 | in-progress | Corrected the tracking owner for the structured-investigation rows below. Issue #242 is unrelated golden-question assurance work. Issue #244 owns authenticated causal diagnosis parity, including T1 frame rejection diagnostics and bounded T2 throttling behavior. | [Issue #244](https://github.com/dotnetpower/fdai/issues/244); authenticated typed-hold evidence. | Produce a complete authenticated target-bound diagnosis without weakening the typed hold. |
| 2026-08-20 | implemented | Versioned frame prompt v29 to keep a free-text name fragment beside its declared resource type. The model still proposes meaning only; Core verifies that the exact fragment occurs in the utterance and can only narrow the ObjectSet. | `current change`; [Issue #242](https://github.com/dotnetpower/fdai/issues/242); focused prompt and multi-filter grounding checks. | Retain the authenticated corrected filter before the causal comparison. |
| 2026-08-20 | implemented | Restored N-1 direct-call compatibility for the Azure frame adapter by defaulting only its newly added metric-concept input. Runtime composition continues to pass the reviewed metric registry explicitly. The widened investigation traversal keeps the scoped query-table verifier contract, and service-test ownership now includes the causal presentation regression. | `current change`; [Issue #242](https://github.com/dotnetpower/fdai/issues/242); focused adapter and verifier checks pass 27 cases. | Complete exact commit and integrated-range validation before live Console evidence. |
| 2026-08-20 | implemented | Corrected the structured-intent admission rule after exact commit validation found two generic visible-scope causal regressions. A causal frame requires structured intent only when its subjects include an exact target outside the supplied declaration names; generic declared-scope causal evidence continues through the existing verified plan. | `current change`; [Issue #242](https://github.com/dotnetpower/fdai/issues/242); 37 focused compatibility, target-bound, prompt, and service-suite checks passed. | Retain authenticated resource-filter and target-bound slowdown answers from the exact corrected source. |
| 2026-08-13 | in-progress | Reconciled the target architecture with the active Core runtime, Operator bridge, service contract, deployment configuration, and focused tests without reconstructing earlier provenance. | Current source and focused checks listed in the scope table. | Complete query coverage, multimodal transport, descriptor generations, runtime coverage receipts, and governed live certification remain open. |
| 2026-08-14 | implemented | Replaced immediate T2 semantic planning with a T1-first cascade whose only T2 trigger is an unavailable or deterministically invalid T1 frame or plan proposal. | `current change`; semantic planner and composition regressions verify T1 success, clarification, and evidence holds do not invoke T2, while bounded proposal failure can retry one stage. | Retain authenticated evidence that records tier selection and complete the existing governed live certification. |
| 2026-08-20 | implemented | Added verified investigation intent and a server-owned causal evidence compiler. An exact target resolves before ordered relationship expansion, every hypothesis depends on the observed symptom change, and ambiguous identity, incomplete scope, opposite symptom direction, stale windows, or missing evidence stops the affected branch with a typed reason. | `current change`; focused contract, planner, query-node, question-space, processor, and Operator presentation checks passed 97 cases; Ruff, formatting, and strict mypy passed. | Version the active frame prompt from the concurrent v22 base, then retain authenticated English and Korean slowdown answers at the three Console viewports. |

### Remaining work

- [ ] Complete release-derived descriptor generations and independently validated atomic activation for
    every readable ontology declaration and runtime availability state.
- [ ] Bind the remaining temporal, metric-series, evidence-join, causal, relationship-side, and
    provider-backed read capabilities through the secured query gateway.
- [ ] Carry authorized image and document evidence into semantic planning only after the attachment
    ingestion and custody paths produce bounded immutable references.
- [ ] Produce runtime epistemic receipts for the frozen bilingual question universe and connect them
    to the release gate without weakening structural coverage checks.
- [ ] Capture authenticated cross-service browser and randomized assurance receipts, then verify
    rollback and typed-hold behavior before reporting the path production-ready.
- [ ] Carry one authenticated selected screen Resource and its verified view-fact digest through
    Console, Operator, and Core, then pass status, relationship, summary, and contextual follow-up
    browser cases without broad-query substitution or lexical routing.
- [ ] Retain an authenticated causal investigation that resolves one service, traverses at least
    two ordered LinkType sides, compares aligned metric windows, and reports at least two supported,
    refuted, or unresolved hypotheses without execution authority.
- [ ] Remove temporary legacy natural-language routes only after replay demonstrates equivalent or
    better coverage and safety through the semantic graph path.

The structured intent graph is now the configured server planner for semantic-turn requests. Core
binds the Azure planning adapter, principal-manifest verification, deterministic intent-graph and
receipt production, and exact Console v2/v1 wire projections when its model, release, store, and
transport prerequisites are available. The Operator bridge converts the evidence-bound result to
the existing Console `done` frame; missing prerequisites remain a typed limitation. The default
Core compatibility path now accepts exact canonical commands only.
Natural-language aliases, keyword narration, and canonical-string read plans require explicit
temporary `legacy` mode. An async semantic runtime executes verified ordinary-language DAGs and
emits bounded graph and evidence projections. Durable descriptor indexing and additional temporal,
metric, and causal provider bindings remain explicit delivery work.

The cross-service cutover starts with additive `operator-core-request` and
`core-operator-projection` version 1.2 envelopes. A semantic request carries the authenticated
principal roles, bounded session and prior-turn context, purpose, deadline, idempotency identity,
and `execution_authority: false`. A terminal semantic result carries one typed disposition plus
exact release, principal-manifest, plan, execution-receipt, and evidence identities when the turn
is answered. The generic envelope remains compatible with version 1.0 consumers, but a semantic
payload is never translated into the older shape because that would discard its evidence contract.
The Operator outbox publisher, Core consumer, durable result projection, and Console `done` adapter
are composed when both publisher and result-source transports are bound. The Operator-side cutover
uses Terraform-provisioned `operator.semantic-turn.requests` and
`core.semantic-turn.projections` topics.
One semantic-aware adapter then owns projection, proposal, and stream routing, while a local Azure
narrator is excluded from `chat.stream`. PostgreSQL claims use the database clock, held retries use
a request-and-result-digest projection identity, and duplicate results validate request, principal,
and digest atomically. Live cross-service and randomized assurance receipts remain required before
this path can be reported production-ready.

Exact-release semantic candidates, verified semantic plans, bounded ObjectSets, secured query
receipts, typed function registration, `OntologyQueryPlan`, a deterministic verifier, and bounded
dependency-wave execution exist as ontology-platform foundations. Built-in nodes cover ObjectSets,
set algebra, ordering, projection, grouped aggregation, and read-only functions. They are not wired
to the conversation coordinator. Temporal, metric-series, evidence-join, and complete runtime
availability descriptors remain.

The target server path will persist a redacted graph and timestamped goal receipts rather than raw
provider payloads. It will execute validated read goals in bounded dependency waves, skip blocked
descendants, propagate cancellation, retain successful sibling evidence, and recheck action drafts
against the current capability manifest. Delivery and sequencing are tracked in
[Ontology Query Coverage Implementation Plan](ontology-query-coverage-implementation-plan.md).

The current compatibility path still includes catalog token matching and legacy single-tool
parsers. They are not the target natural-language architecture. Exact identifiers may continue to
resolve directly, but ordinary language must produce a typed semantic candidate from the active
ontology and capability manifest. No regex, phrase list, or question-specific alias may select the
capability, relationship path, or answer shape in the target state.

## Ontology query coverage contract

FDAI targets 100% **structural query coverage**, not a guarantee that every question has enough
evidence for a complete answer. Structural coverage means every declaration readable by the
current principal in the active ontology release is represented in the planner's query surface or
has a typed unavailable reason. The covered declarations are ObjectTypes, queryable Properties,
both query sides of LinkTypes, Interfaces, read-only FunctionTypes, and ActionTypes as draft-only
targets.

The release gate measures three separate outcomes:

- **Schema coverage**: Every readable active declaration has a content-addressed planner descriptor.
- **Question disposition**: Every accepted turn ends as a grounded answer, clarification, evidence
    hold, unsupported goal, or governed action draft.
- **Answer coverage**: The measured share of competency questions that reach a complete grounded
    answer. This value depends on deployed data and evidence and is never presented as 100% by design.

The release gate now also has a separate epistemic-closure foundation. A content-addressed
`QuestionUniverseReceipt` freezes one finite release and principal-scoped denominator.
`EpistemicQuestionRecord` requires a typed knowledge status, complete source-span and semantic-atom
interpretation, completeness evidence for evidence-bearing results, claim proof for answers, and
closed-population proof for verified empty results. The gate rejects missing cases, mismatched
transport dispositions, hidden-scope leaks, ungrounded claims, unresolved conflicts, unsafe
mutation survivors, and locale divergence. The existing structural fixture gate remains valid but
cannot report `production_ready` without a matching passed epistemic-coverage receipt. Question
generation, runtime receipt production, and L3/L4 live certification remain delivery work.
The graph now declares `resource_classified_as`, and the inventory ontology projector can emit one
verified classification per observed Resource from content-addressed ResourceType registry
mappings. Unmapped types make the projection incomplete. The production inventory job injects that
mapping; resource-to-Rule questions remain unavailable until the typed query function is composed.

Language coverage is not maintained by adding phrases. A model or embedding index may propose
object, relation, and function candidates. The deterministic verifier resolves each candidate to
the exact release, validates endpoint types and arguments, and either produces a
`VerifiedSemanticPlan` or asks for clarification. Similarity never proves a relationship or grants
query or action authority.

## Semantic decomposition and plan formation

Natural language is not sent directly to an object search. The planner first creates a bounded
meaning representation that separates what the operator wants from the objects and evidence that
may satisfy it. This record is candidate-only and contains no provider query, executable text, or
object claim.

Plan formation follows five stages:

1. **Decompose the request**: Extract the requested operation, subject constraints, measure,
    temporal scope, comparison, output shape, and evidence standard from the complete turn and its
    exact context.
2. **Ground the schema**: Resolve those roles to candidate ObjectTypes, Interfaces, Properties,
    LinkType sides, and FunctionTypes in the principal-scoped release-derived manifest.
3. **Build the intent graph**: Express independent and dependent goals without selecting concrete
    runtime objects that evidence has not established.
4. **Verify and compile**: Type-check every schema reference, relationship composition, temporal
    bound, argument, scope, and capability before compiling a bounded read task DAG.
5. **Execute and join evidence**: Resolve concrete objects through authoritative providers, follow
    typed links, run registered functions, align cutoffs, and verify claims before presentation.

For example, the question "Why have requests increased since last week?" may produce this meaning
representation:

```yaml
operation: explain_change
measure_concept: request.volume
subject_constraint: service
temporal_scope:
  current: {from: start_of_last_week, to: now}
  baseline: {before: start_of_last_week, equal_duration: true}
requested_result: ranked_causal_hypotheses
evidence_requirements:
  - complete_metric_windows
  - typed_service_identity
  - dependency_neighborhood
  - bounded_change_history
```

This example is a logical form, not a phrase rule. No individual word, including "why", selects
`explain_change`. The model proposes the operation from the whole turn, selected screen objects,
prior verified context, locale, and time reference. If "requests" could mean HTTP requests,
support requests, or deployment requests, or if the calendar boundary is unresolved, the verifier
returns a clarification before any operational read.

After schema grounding, the intent graph can bind goals such as detecting the metric change,
selecting affected Service objects, traversing to Workloads and Pods, retrieving Deployments and
configuration Changes near the change point, and comparing aligned metric windows. The task DAG may
run independent reads concurrently, but the causal join waits for their receipts. A deployment that
precedes the increase is a candidate explanation only; dependency, timing, mechanism, completeness,
and competing-change evidence determine whether it is supported, refuted, or unresolved.

## Intent graph contract

An intent graph records the operator request without reducing it to one tool. Every graph contains:

- **Goals**: One or more independently identifiable outcomes.
- **Dependencies**: Goal identifiers that must complete before a goal can run.
- **Intent**: The answer shape, such as status, diagnosis, comparison, or definition.
- **Capability**: One server-listed read capability, or no capability for presentation-only goals.
- **Arguments**: Schema-validated values supplied by the operator or server-owned context.
- **Evidence policy**: Required or preferred screen, operational, web, catalog, or model-knowledge evidence.
- **Confidence and alternatives**: Bounded values used to clarify ambiguity rather than guess.
- **Action posture**: `advise_only` for reads or `draft_only` for an explicit change request.

The graph is versioned and replayable. It never stores hidden reasoning. The observable reasoning
summary contains selected capabilities, evidence requirements, assumptions, unresolved ambiguity,
and dependency ordering.

## Context resolution

The planner receives a bounded context envelope assembled before model invocation:

- Current route, selected object, semantic screen facts, units, measurement window, and source age.
- Principal-scoped conversation history and operator locale.
- Validated image parts and immutable document evidence references.
- Runtime capabilities projected after route authorization and filtered by availability, enabled
    state, and authority. A draft still passes the submission route's current RBAC and safety gates.
- Explicit web-search availability and the approved-domain policy.

References such as `this value`, `here`, or `Bragi` resolve against typed context. Ambiguous
references produce one clarification goal. Internal agent `Bragi` and the mythological entity
Bragi use separate namespaces, so a mythology question does not become an agent request.

## Capability registry

One registry owns planner-visible descriptors while composition keeps resolver bindings behind
typed provider seams. A descriptor contains its stable name, purpose, side-effect class, argument
schema, owner, availability, enabled state, authority mode, and unavailable reason.

The planner never receives unavailable capabilities. Subscription health, inventory, screen reads,
web search, and agent-owned reads use the same contract. Language terms, resource aliases, and
service names remain catalog or ontology data rather than Python question patterns.

### Release-derived query manifest

One mechanical builder projects the active ontology release and runtime capability registry into a
principal-scoped query manifest. It does not hand the entire deployment graph or hidden fields to
the model. Search and describe return bounded descriptors only after role, purpose, availability,
enabled state, and authority filtering.

Each descriptor includes:

- **Object or interface shape**: Stable identity, properties, value types, units, supported
    predicates, and freshness requirements.
- **Relationship sides**: One semantic query name for each endpoint, endpoint types, cardinality,
    symmetry, causality, temporal ordering, and whether inverse traversal is allowed.
- **Function contract**: Input and output schema, operation class, evidence requirements, bounds,
    and side-effect class.
- **Action boundary**: Draft schema and required authority only. Mutation handlers and executor
    credentials are never planner-visible.

A release is structurally incomplete when a readable declaration cannot be projected. Adding a
new resource or relationship then expands the natural-language query surface without adding a
question pattern. New query-side metadata is versioned ontology data and passes the same release
and compatibility gates as the declaration it describes.

### Generic ontology query algebra

The planner composes a bounded `OntologyQueryPlan` instead of choosing one question-specific tool.
The closed algebra supports object or interface selection, typed property predicates, relationship-
side traversal, set union/intersection/subtraction, ordering, aggregation, projection, and calls to
registered read-only ontology functions. Raw SQL, KQL, Cypher, SPARQL, provider URLs, and executable
commands are not plan values.

For example, a question about resources beyond a VM's peered network compiles from exact screen
context into typed relationship sides: VM to attached interface, interface to subnet, subnet to
containing virtual network, peer network, then contained or attached resources. The model does not
invent those steps. The verifier accepts only compositions licensed by endpoint types and the
active release. If "connected" could mean attachment, network reachability, workload dependency,
or shared scope, the result is a clarification rather than a union of unrelated links.

Object and declaration embeddings are optional candidate indexes. They help resolve paraphrases
and omitted names, but the executor reads exact object identities and typed links. Instance
embeddings are never required for structural coverage and remain deployment-local when derived
from deployment data.

## Evidence policy

| Question type | Preferred path | Fallback |
|---|---|---|
| Current screen fact | Screen snapshot | Clarify when the datum is absent |
| Current operational state | Authoritative read capability | Partial answer with coverage gaps |
| Public or current external fact | Approved web search | Model knowledge when freshness is not required |
| Benchmark comparison | Screen metric plus comparable web evidence | Qualitative analysis without invented benchmarks |
| General knowledge | Web when available or explicitly requested | Calibrated model knowledge |
| Explicit change | Typed action draft | Hold when required arguments are missing |

Web results are untrusted evidence. Sanitization, approved domains, retrieval time, and claim
verification remain required. When search is unavailable, the answer labels model knowledge,
states freshness limits, and never fabricates citations. This fallback is allowed only when the
validated goal doesn't require fresh evidence. Raw chain-of-thought is not persisted or shown.
Bragi presents a concise conclusion, evidence, assumptions, comparison basis, limitations, and
uncertainty.

### Contextual operational joins

Follow-up diagnostics reuse only server-owned resource and event context from a verified durable
turn. Metric comparisons query equal bounded windows before and after the recorded event. Database,
pod, and capacity diagnostics use fixed KQL templates only after an exact resource has been selected;
otherwise the route asks for that resource. Error-rate and control-plane change joins report temporal
distance and never describe temporal alignment as proof of cause. Missing rows, missing limits,
truncation, or an unavailable provider remain explicit limits rather than positive findings.

Selected-incident questions preserve their analysis intent in the server evidence envelope. One
bounded audit and RCA projection renders the ordered timeline, cited hypothesis ranking, measured
impact, recorded response decision, consumed evidence references, unknowns, and investigation
progress. Timeline order is not causal proof. Similar incidents require a shared domain signal and
an explicit successful recovery receipt. Provider failure remains distinct from a verified empty
result. A response decision is read-only and grants no execution authority, and investigation
progress requires a durable run identifier.

For an incident-analysis turn, durable or exact screen-selected incident context overrides an
unrelated semantic plan. An unrelated deterministic tool, explicit public-web request, or concrete
action draft keeps its requested authority; context never substitutes for intent. Audit values are normalized and capped
before entering the evidence envelope; any cap sets `truncated`. Evidence references identify the
exact positive audit sequence or citation consumed. RCA confidence is displayed only as a finite
probability from `0` through `1`. Freshness follow-ups restore the server-generated freshness
receipt from the prior durable assistant turn. A browser-supplied freshness object never gains
server evidence authority.

### Temporal and causal questions

A current graph cannot answer "what changed" or "why did this stop today" by itself. These goals
bind to typed history and time-series functions. They first find a symptom change point, retrieve
the graph at bounded before/after cutoffs, compute a topology diff, gather changes in the affected
dependency neighborhood, and compare complete metric windows. Timeline order is supporting
evidence, not causal proof.

For a storage-write gap, the planner anchors the exact storage object and requested windows. The
executor may discover an upstream workload, the VM that runs it, both virtual networks, and a
removed peering through historical typed links. It can rank the peering change as a causal
hypothesis only when workload dependency, path-before/path-after, write-attempt, write-result, and
telemetry-completeness evidence support the same cutoff. Missing DNS, route, firewall, credential,
or application evidence remains a named alternative or limitation.

The current instance graph is a current-state projection, so historical topology and cross-resource
temporal joins remain delivery work. Until authoritative history bindings exist, these questions
return partial evidence or an explicit hold rather than reconstructing the past from the latest
graph.

## Task DAG compilation

The deterministic compiler converts validated read goals into bounded tasks. Independent tasks run
concurrently; dependent tasks wait for declared prerequisites. Each task carries a stable identity,
capability, validated arguments, deadline, evidence keys, authority, dependencies, correlation, and
UTC lifecycle timestamps. Browser persistence keeps bounded references and removes provider bodies.

A compound subscription diagnosis can fan out inventory, Resource Health, metric, and approved web
benchmark reads, then join them for time alignment and correlation. One unavailable branch produces
a partial result, not a false success or a whole-investigation failure. Unsupported goals remain
visible with an unavailable reason.

## Multimodal questions

Image attachments remain bounded validated input. A vision-capable model may extract text,
entities, time ranges, and requested comparisons into the same context envelope. Extraction does
not create evidence authority. Operational claims still require screen, tool, agent, document, or
web evidence, and low-confidence extraction asks for clarification.

## Answer and action boundaries

Bragi streams a presentation after evidence collection and verification. The answer envelope uses
one evidence mode: `screen_grounded`, `operational_grounded`, `web_grounded`, `mixed_grounded`,
`model_knowledge`, `partial`, or `held_for_review`.

A recommendation is not an executable action. An explicit change request produces a typed draft
that enters the existing safety and approval path. The planner cannot execute, approve, promote, or
change policy. The graph executor refuses every non-read goal even if called outside the normal
route, and the route rechecks draft availability immediately before returning confirmation data.

## Migration

1. Generate a content-addressed query manifest from every active ontology release and fail the
    coverage gate for an unprojected readable declaration.
2. Add semantic query sides to LinkTypes and load Interface declarations so new implementing types
    enter existing queries without planner changes.
3. Bind one generic ObjectSet query capability plus bounded topology, history, metric, and causal
    functions behind the existing secured query gateway.
4. Persist and replay the active intent graph with every completed turn, then compare selection,
    authority, clarification, latency, and answer quality on bilingual scenarios.
5. Build full inactive semantic generations, reuse unchanged declaration and object digests on
    incremental builds, validate independently, and atomically activate the new generation.
6. Remove catalog-token, regex, legacy single-tool, and question-specific routes after replay proves
    equivalent or better coverage. Exact object and catalog identifiers remain valid direct refs.

The compatibility period is temporary. Migration ends with one graph contract and one registry.

## Current gaps

| Area | Current state | Coverage impact |
|------|---------------|-----------------|
| Intent graph | Verified plans produce bounded graphs and task evidence, and Operator attaches both to the Console-compatible `done` frame. | A new authenticated live run must validate the visible browser path. |
| Semantic plans and ObjectSets | Exact-release candidates, principal-manifest verification, bounded predicates/traversal, secured receipts, and generic set/order/project/aggregate handlers form the production semantic-turn read surface. | Temporal and evidence-join extensions remain unavailable until their authoritative providers are bound. |
| Interfaces | Production loading validates and compiles the reviewed `Identifiable` Interface for all current ObjectTypes, and Interface selectors exist in the ObjectSet contract. | Additional capability Interfaces and production polymorphic ObjectSet query binding remain unwired. |
| Relationship sides | Every directed LinkType exposes deterministic outgoing and incoming endpoint-side query ids while stores preserve typed direction. | The generic verifier and natural-language planner do not yet consume those sides. |
| Semantic generations | Rule retrieval has complete generations and candidate-only ranking | Declaration and runtime-object coverage has not yet expanded to the full ontology. |
| Historical graph | Append-only bitemporal revision contracts, tombstones, late-evidence replay, `graph_at`, `topology_diff`, and typed handlers exist. | PostgreSQL reader/writer composition and inventory-promotion publishing remain. |
| Network and causal functions | Current peering, private-link target, and exact-resource next-hop projection plus metric concepts, aligned windows, and topology-aware temporal support/refutation foundations exist. | Production receipt issuers, provider metric bindings, and remaining Azure workload/service relationships remain incomplete. |

## Verification

The release gate covers simple and compound English and Korean questions, screen references,
general knowledge, MTTR benchmark comparison, multi-service diagnosis, text/image/document input,
web and agent outages, partial evidence, invalid graphs, stable replay, cancellation, and branch
isolation. The safety target is zero unsupported operational claims and zero unauthorized execution.

Structural coverage fixtures also enumerate every readable declaration in a frozen release. They
prove descriptor projection, both relationship sides, supported property operators, interface
expansion, function schema binding, role filtering, typed unavailable reasons, and the absence of a
question-pattern prerequisite. A new declaration that is invisible to this inventory blocks the
release.

Conversation Assurance measures intent resolution, completeness, grounding, calibration,
actionability, locale parity, cost, and latency on the same frozen cohort before activation.

## Related docs

| To learn about | Read |
|---|---|
| FDAI Console conversation boundary | [FDAI Console Conversations](operator-console.md) |
| Audited gaps, sequencing, cutover, and rollback | [Ontology Query Coverage Implementation Plan](ontology-query-coverage-implementation-plan.md) |
| Rule-specific semantic ranking and generations | [Rule Semantic Retrieval](../rules-and-detection/rule-semantic-retrieval.md) |
| Exact releases, ObjectSets, and typed functions | [FDAI Ontology Safety Infrastructure](../architecture/operating-ontology-platform.md) |
| Completed-answer evaluation | [Conversation Assurance](../decisioning/conversation-assurance.md) |
| Multimodal evidence custody | [Conversation Attachments](conversation-attachments.md) |
| Agent and control-loop boundaries | [Project Structure](../architecture/project-structure.md) |
