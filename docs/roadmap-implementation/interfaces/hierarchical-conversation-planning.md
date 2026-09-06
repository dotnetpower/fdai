# Hierarchical Conversation Planning implementation ledger

This delivery ledger preserves reviewable implementation scope, append-only transitions,
and resumable work while the roadmap owner remains focused on normative design.

## Implementation status

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| Compact conversation preflight | implemented | `conversation-preflight.v2.yaml`; [`conversation_preflight.py`](../../../services/core-control-plane/src/fdai/core/conversation/conversation_preflight.py); 177 focused conversation, prompt-registry, and adapter tests | Exact F1-F4 requests can supply provenance-bound candidate meaning and skip one full-judgment call only after confidence, source-span, time, family-shape, and identity checks. Other meanings retain full judgment. |
| Semantic frame, verified plan, and intent graph | implemented | [`semantic_planning.py`](../../../services/core-control-plane/src/fdai/core/conversation/semantic_planning.py), [`semantic_planning_cascade.py`](../../../services/core-control-plane/src/fdai/core/conversation/semantic_planning_cascade.py), [`semantic_runtime.py`](../../../services/core-control-plane/src/fdai/core/conversation/semantic_runtime.py), focused semantic-planning tests | Whole-turn proposals are bounded, release-scoped, verified, and projected without execution authority. T1 is always attempted first. The default typed policy permits one same-stage T2 retry only for T1 unavailability; invalid frames, schemas, builds, and deterministic plan mismatches fail closed. |
| Structured causal investigation | implemented | `semantic_investigation.py`; `semantic_investigation_planning.py`; investigation query-node and presentation tests; focused investigation checks | A target-bound causal diagnosis carries exact source spans, typed entity roles, symptom direction, temporal cues, ordered LinkType sides, competing hypotheses, evidence standard, and answer shape. Core verifies those atoms and compiles entity resolution, multi-hop expansion, aligned windows, topology diff, symptom comparison, and support/refutation waves without a model-authored plan. Generic declared-scope causal evidence keeps the existing bounded plan. If fewer than two hypothesis results reach presentation, the target and symptom comparison remain visible with an explicit evidence limitation instead of a false complete diagnosis. |
| Production Core semantic runtime composition | implemented | [`wire_semantic_query.py`](../../../services/core-control-plane/src/fdai/composition/wire_semantic_query.py), [`semantic_query_model_targets.py`](../../../services/core-control-plane/src/fdai/composition/semantic_query_model_targets.py), [`bootstrap.py`](../../../services/core-control-plane/src/fdai/runtime/bootstrap.py), focused semantic-query composition tests | Azure T1 and T2 planning adapters are bound separately. Principal-scoped manifests, secured ObjectSets, read functions, and bounded DAG execution are composed when prerequisites are available. |
| Versioned cross-service semantic-turn contract | implemented | [`semantic_turn.py`](../../../packages/service-contracts/src/fdai_service_contracts/semantic_turn.py), [`semantic_turn_processor.py`](../../../services/core-control-plane/src/fdai_core_service/semantic_turn_processor.py), [`test_semantic_turn_processor.py`](../../../services/core-control-plane/tests/test_semantic_turn_processor.py) | Version 1.2 requests and projections bind identity, purpose, deadlines, digests, dispositions, and evidence without granting execution authority. |
| Durable Operator bridge and Console projection | implemented | [`semantic_turn_runtime.py`](../../../services/operator-service/src/fdai_operator_service/families/conversation/semantic_turn_runtime.py), [`postgres_semantic_turn_store.py`](../../../services/operator-service/src/fdai_operator_service/postgres_semantic_turn_store.py), [`test_semantic_turn_bridge.py`](../../../services/operator-service/tests/test_semantic_turn_bridge.py) | The Operator owns durable acceptance, outbox claims, result projection, authenticated replay, typed holds, and `done` event adaptation. |
| Event transport and deployment configuration | implemented | [`semantic_kafka.py`](../../../services/operator-service/src/fdai_operator_service/adapters/semantic_kafka.py), [`main.tf`](../../../infra/main.tf), [`test_semantic_turn_topics.py`](../../../tests/integration/infra/test_semantic_turn_topics.py) | Logical request and projection topics share the governed physical event stream and are configured for both services. |
| Structural and epistemic coverage foundations | in-progress | [`epistemic_coverage.py`](../../../services/core-control-plane/src/fdai/core/conversation/epistemic_coverage.py), [`test_epistemic_coverage.py`](../../../services/core-control-plane/tests/conversation/test_epistemic_coverage.py) | Receipt and gate contracts exist, but complete descriptor generations, runtime question receipts, and L3/L4 certification are not delivered. |
| Complete temporal, metric, causal, and relationship query surface | in-progress | [`wire_semantic_query.py`](../../../services/core-control-plane/src/fdai/composition/wire_semantic_query.py), [Ontology Query Coverage Implementation Plan](../../roadmap/interfaces/ontology-query-coverage-implementation-plan.md) | ObjectSets, set operations, projection, aggregation, and selected read functions are bound; the remaining provider-backed query kinds are incomplete. |
| Multimodal semantic planning input | not-started | [Conversation Attachments](../../roadmap/interfaces/conversation-attachments.md) | The semantic-turn request currently carries bounded text and prior-turn context, not server-validated image or document evidence. |
| Governed production certification | not-started | This document's verification contract | No retained authenticated cross-service browser receipt or randomized assurance receipt currently proves production readiness. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-09-07 | implemented | Added the bounded operational-family preflight proposal and verified reuse path without widening capability or execution authority. | `current change`; 177 focused tests, targeted Ruff, and strict mypy passed. | Retain standard-stack F1-F4 answer-token TTFT and evidence receipts. |
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
[Ontology Query Coverage Implementation Plan](../../roadmap/interfaces/ontology-query-coverage-implementation-plan.md).

The current compatibility path still includes catalog token matching and legacy single-tool
parsers. They are not the target natural-language architecture. Exact identifiers may continue to
resolve directly, but ordinary language must produce a typed semantic candidate from the active
ontology and capability manifest. No regex, phrase list, or question-specific alias may select the
capability, relationship path, or answer shape in the target state.
