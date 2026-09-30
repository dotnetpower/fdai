---
title: Agent Pantheon Implementation Plan
---

# Agent Pantheon Implementation Plan

This document coordinates the implementation of the fixed 15-agent pantheon. It keeps the
append-only delivery ledger, the W0-W8 dependency order, and the runtime composition contract in
one place. Agent roles and invariants live in [Agent Pantheon](agent-pantheon.md), while each
cross-agent workflow has an independent rollout record in
[Agent Workflow Shadow Rollout](agent-workflow-rollout.md).

> **Scope:** The plan is customer-agnostic and Azure-first. Forks configure provider and delivery
> bindings through the supported dependency-injection seams. They don't rename agents, change
> role bindings, or bypass shadow promotion.

## Implementation status

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| Ontology ContextIndex owner routing | implemented | `agents/_framework/ontology_index.py`; `test_ontology_context_index.py`; real in-memory EventBus phase-chain test | Huginn ingress, Muninn preparation/transition publication, Heimdall validation publication, and Saga audit/seal publication use existing owned topics. The wrapper rejects owner, topic, content, and phase drift and isolates ordinary judgment and learning. Mechanical handlers in this routing test are synthetic; durable source/lifecycle workers and production bootstrap remain open. |
| W0-W1 documentation, ontology, and framework scaffolding | implemented | [`test_framework_layout.py`](../../../services/core-control-plane/tests/agents/test_framework_layout.py), [`test_pantheon_doc_parity.py`](../../../services/core-control-plane/tests/agents/test_pantheon_doc_parity.py), [`test_topics.py`](../../../services/core-control-plane/tests/agents/test_topics.py) | The fixed registry, package boundary, documentation parity, and typed-topic foundation are executable and checked. |
| Bus and graph ownership separation | implemented | `_framework/{pantheon,topics}.py`; ontology alignment, topic, registry, doc-parity, and Console agent-contract tests | `AgentSpec.owns` now lists only producible event-bus objects. `Budget` and `SizingRecommendation` retain Njord and Freyr graph lifecycle ownership without inventing dead topics; embedded ActionRun attempt state and core RCA projections remain outside the bus registry. |
| Owned-topic producer completeness | implemented | [`test_registry.py`](../../../services/core-control-plane/tests/agents/test_registry.py) | AST-backed registry validation requires every `AgentSpec.publishes` topic to reach a concrete publish call and rejects producer evidence for undeclared topics. Literal calls, imported topic constants, and exact dynamic-topic comparisons are recognized without treating arbitrary string mentions as producers. |
| W2-W6 governance, pipeline, interface, specialist, handoff, and security mechanics | implemented | [`test_runtime_chain.py`](../../../services/core-control-plane/tests/agents/test_runtime_chain.py), [`test_thor_durable.py`](../../../services/core-control-plane/tests/agents/test_thor_durable.py), [`test_conversational_port.py`](../../../services/core-control-plane/tests/agents/test_conversational_port.py), [`test_prompt_deliberation.py`](../../../services/core-control-plane/tests/agents/test_prompt_deliberation.py) | Focused synthetic tests exercise the bounded mechanics, including T1 answer evaluation before optional T2 synthesis. They do not establish live operational validation. |
| Durable authority, recovery, handoff, and learning replay | implemented | [`test_runtime.py`](../../../services/core-control-plane/tests/agents/test_runtime.py), [`test_wave2_governance.py`](../../../services/core-control-plane/tests/agents/test_wave2_governance.py), [`test_wave3_pipeline.py`](../../../services/core-control-plane/tests/agents/test_wave3_pipeline.py), [`test_bootstrap_config.py`](../../../services/core-control-plane/tests/runtime/test_bootstrap_config.py) | StateStore-backed CAS, lease, checkpoint, outbox, and startup recovery paths have focused restart and concurrency evidence. Two bounded Low-severity cross-replica and operation-identity residuals remain open below. |
| Full-authority development approval and recovery | in-progress | `agents/{forseti,thor,var,vidar}.py`; `agents/_framework/*development_authority*.py`; [`test_development_authority.py`](../../../services/core-control-plane/tests/agents/test_development_authority.py) | Explicit composition carries one trusted-source-verified confirmation from Forseti through Var and Thor, with Vidar/restart revalidation and no fabricated identities. Roles, topics, and `PANTHEON_SPECS` are unchanged. No upstream authoritative binding source is implemented or deployed. |
| Durable Huginn ingress deduplication | implemented | `agents/{huginn.py,_framework/huginn_dedup.py}`; focused discovery and runtime tests | Production composition persists bounded key claims in at most 64 exact-capacity shards, exact normalized retry payloads, owner leases, and publication checkpoints before starting ingress consumers. Routine claims use non-authoritative revision CAS without duplicating each event in audit; recovery and migration remain audited. Startup idempotently migrates and compacts the legacy single-row journal. A crash after broker acceptance and before the checkpoint can still redeliver the same stable idempotency key under the event bus's at-least-once contract. |
| Loki ResilienceScore production | implemented | `agents/{loki.py,_framework/loki_resilience.py}`; focused Wave 5 and cross-vertical candidate tests | Loki validates Huginn-owned normalized score Events against the consumer's exact candidate contract, publishes `object.resilience-score`, and retains only a bounded read-only score projection. Candidates grant no judgment, approval, or execution authority. |
| Bragi session-object production | implemented | `agents/{bragi.py,_framework/bragi_publication.py}`; focused Bragi, conversational, Norns, runtime, and governance tests | The first in-process session publishes one content-free `Conversation`. Explicit methods accept only validated `UserPreferenceRecord` and consent-filtered `PostTurnReviewInput` values, publish their owned topics, and expose no judgment, approval, or execution path. Deployment-owned store and queue bindings remain separate. |
| W7 cross-agent shadow workflow mechanics | implemented | [`test_wave7_workflows.py`](../../../services/core-control-plane/tests/agents/test_wave7_workflows.py) | Workflows have executable synthetic shadow traces and no evidence here of a default enforce workflow. |
| W8 KPI, promotion, and degradation machinery | implemented | [`test_wave8_kpi_degradation.py`](../../../services/core-control-plane/tests/agents/test_wave8_kpi_degradation.py) | KPI reports distinguish measured values from unavailable evidence, promotion fails closed on missing evidence, and injected degradation drills cover the fixed pantheon. |
| W3 trace-continuity evidence handoff | implemented | `huginn.py`; `heimdall.py`; `test_trace_continuity_chain.py` | The sensing path preserves only bounded allowlisted continuity evidence and carries an observed reason into one Incident candidate without changing roles, topics, or action authority. |
| Operational activity attribution | implemented | `control_loop/_measurement.py`; `control_loop/_rca.py`; `agents/_framework/provider_adapters.py`; `delivery/{agent_activity,observation_campaign,startup_probe}.py`; Operator activity projection and focused tests | Mechanical actors remain distinct from accountable Pantheon owners. Periodic runtime snapshots preserve active handler state and publish independent agent records concurrently. Authenticated bus publishers alone populate `producer_principal`; unknown legacy custom sources remain audit evidence and do not become invented agent activity. |
| Terminal ActionRun effect-observation path | implemented | [`executed_action_observation.py`](../../../services/core-control-plane/src/fdai/delivery/executed_action_observation.py), [`wire_azure_operational_evidence.py`](../../../services/core-control-plane/src/fdai/composition/wire_azure_operational_evidence.py), [`test_executed_action_observation.py`](../../../services/core-control-plane/tests/delivery/test_executed_action_observation.py) | Heimdall consumes Thor's terminal ActionRun, restores exact pre-dispatch artifacts, and stores only verifier-accepted independent observations. Deployment-owned signed context and live closure evidence remain open. |
| O7 operational-promotion evidence measurement | implemented | [`operational_promotion.py`](../../../services/core-control-plane/src/fdai/core/measurement/operational_promotion.py), [`operational_promotion_evidence.py`](../../../services/core-control-plane/src/fdai/delivery/measurement/operational_promotion_evidence.py), [`test_operational_promotion_evidence.py`](../../../services/core-control-plane/tests/delivery/test_operational_promotion_evidence.py) | The runner consumes manifest-bound immutable batches and fails closed on missing causal, unit, recurrence, or policy-escape evidence. No runtime producer currently materializes the complete live batches. |
| Live operational KPI validation and actual enforce promotion | in-progress | [Operational Learning Ontology](../rules-and-detection/operational-learning-ontology.md), [Goals and Metrics](../architecture/goals-and-metrics.md) | Measurement and observation consumers exist, but no complete retained live-shadow cohort, operational promotion receipt, independent review, or actual pantheon enforce promotion is evidenced by this plan. |
| Observation-first learned and predicted output boundary | implemented | `agents/_framework/{advisory_verdicts,forseti_learned_outputs,thor_persistence,action_run_identity}.py`; `StateStoreActionRunStore.reserve_correlation`; `core/control_loop/_learned_reuse.py`; `runtime/{control_loop,bootstrap_pantheon}.py`; `test_learned_output_profile_boundary.py`; `test_learned_output_arbitration_gate.py`; `test_learned_output_durable_gate.py`; `test_learned_reuse_profile_boundary.py`; `test_bootstrap_pantheon_product_selection.py` | Without the `governed-execution` product add-on, forecasts, Freyr capacity arbitration, and T1 reuse of learned patterns produce ActionType-free advisory evidence that Thor ignores. A settled advisory arbitration holds later observed signals on its correlation from automatic execution, including after a Core restart or gate eviction, through Thor's durable non-action correlation claim. Selecting the add-on reopens the existing gates with one deliberate restriction: a forecast-derived action Verdict without an exact `mode: enforce` is capped at `shadow_only`. The selection comes only from the product profile; T2 proposals are outside this row. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-09-29 | implemented | Thor, Heimdall, Mimir, and Forseti now record the independent verifier's explicit rejection class and cite its rejection record while keeping their roles, owned objects, and topics. Thor's test-context dispatch hold sets the `ActionRun` outcome and `evidence_rejection_ref` on `object.action-run`; Heimdall excludes scoring in `ForecastOutcome` `1.2.0` on `object.forecast-outcome`; Mimir appends a `test_context.transition_refused` audit entry and publishes no `object.policy`; Forseti's held verdict carries `evidence_rejection_ref`. Only `unavailable` keeps each generic reason, issuance stays a bounded provider call, and no execution or promotion authority changes. | `current change`; `agents/_framework/{thor_execution,thor_action_run,thor_persistence,forseti_judgment}.py`; `tests/agents/test_operational_evidence_owner_records.py`; see the [independent operational evidence ledger](../../roadmap-implementation/rules-and-detection/independent-operational-evidence.md) | Purposes without a bound verifier readback still reach these agents only as `unavailable`. |
| 2026-09-28 | implemented | Closed the residual default-profile paths by which learned patterns and predictions became action proposals, gated on the existing `governed-execution` product add-on. The control-loop builder passes `RuntimeProductSelection.governed_execution` to the control loop, and Pantheon composition passes the control loop's value to Forseti, so no second selection input exists. Without the add-on, Forseti answers forecasts and capacity-fed arbitration with ActionType-free Verdicts and builds no decision options or kinetic proposals from a prediction, and the control loop stops T1 learned reuse before it builds an Action. Every settled advisory arbitration marks its correlation unresolved as the governed path does, publishes one Verdict under a per-correlation lock, and Thor holds the correlation durably with a terminal non-action claim in its ActionRun store, so a later Verdict on it is refused after a restart or gate eviction as a reused correlation is refused on the governed path; no ActionRun, approval, or executor call results. With the add-on, the existing gates run with one deliberate restriction: an action Verdict derived from a forecast without an exact `mode: enforce` is capped at `shadow_only`. Roles, topics, and `PANTHEON_SPECS` are unchanged. | `current change`; 50 cases in `test_learned_output_profile_boundary.py`, `test_learned_output_arbitration_gate.py`, `test_learned_output_durable_gate.py`, `test_learned_reuse_profile_boundary.py`, and `test_bootstrap_pantheon_product_selection.py`, a mutation check for each gate, the unresolved mark, the publication retry and lock, the durable hold, and both composition hand-offs, and the governed-path arbitration, decision-case, specialist, and T1 wire tests updated to select the add-on through the product profile; framework layout, Ruff, and strict mypy passed. | Review T2, anomaly-action, alert-noise, and other learned-evidence consumers. No live validation was performed. |
| 2026-09-27 | in-progress | Integrated a trusted-source-verified full-authority development envelope through the real Forseti, Var, Thor, and Vidar typed path while preserving fixed roles and topics. Original and effective quorum remain distinct, and replay identity includes the exact grant only for the selected profile. | `current change`; 723 focused authority, bus, replay, and adjacent cases passed; layout, Ruff, and strict typing checks passed. | Implement and bind the authoritative deployment source, then retain governed runtime receipts. No live validation was performed. |
| 2026-09-22 | validated | Repaired local Core startup and shutdown resource ownership. Runtime settings now reuse the one runtime-owned StateStore pool, Pantheon consumer shutdown grants bounded finalization after the first drain deadline, and destructive local broker reset holds every managed service lock so a disconnected live consumer cannot appear idle. Agent roles, topics, model policy, promotion state, and authority are unchanged. | `current change`; focused shared-store, ordered shutdown, delayed stream-close, consumer retry, broker reset fence, framework layout, Ruff, and strict typing checks; the managed restart reached 12/12 readiness with one lock-owned process pair per service and no repaired error signature after the new generation marker. | No work remains for this bounded lifecycle repair. Deployed runtime validation and promotion evidence remain separate. |
| 2026-09-21 | implemented | Added a closed ontology ContextIndex envelope and owner-specific runtime subscription wrapper, with Heimdall and Saga ContextIndex subscriptions and typed Huginn ingress. Corrected the domain-schema/transport-version distinction exposed by the real bus test. | `current change`; focused ContextIndex routing, framework layout, adjacent Rule-generation flow, and exact audit-before-seal checks. | Bind real source/vector validation, audited pointer admission, terminal replay, and runtime consumers. The fixed agent roles, hot-path model policy, package activation, and execution authority remain unchanged. |
| 2026-09-21 | implemented | Split Forseti's owner-authenticated cross-vertical intake, Odin arbitration, decision-case finalization, HIL fallback, kinetic proposal validation, and prospective-lineage publication into one focused private framework mixin. Forseti remains the Judge and sole publisher of its four owned object topics; it gains no approval or execution authority. | `current change`; `agents/{forseti.py,_framework/forseti_arbitration.py}`; 12-lens critique; 145 focused role/arbitration/quorum tests plus layout, parity, import, Ruff, and strict mypy gates. | Retain governed runtime evidence for timeout HIL closure, Odin outage, duplicate delivery, and prospective-lineage materialization. |
| 2026-09-21 | implemented | Split Thor's durable ActionRun codec, verdict validation, audit-gated execution phase, replay/publication lifecycle, effect closure support, and read-only conversation projection into focused private framework modules. Durable replay now rejects prospective lineage without its paired kinetic proposal. Thor remains the sole privileged executor and ActionRun publisher; AgentSpec, topics, quorum, approval, audit, rollback, effect-verification, and model policy are unchanged. | `current change`; `agents/{thor.py,_framework/thor_*.py}`; Thor durability, conversation, and framework-layout checks passed 203 cases; focused strict mypy passed. | Retain governed runtime evidence for degraded shadow, audit-before-I/O, restart replay, independent effect closure, and the existing live-promotion prerequisites. |
| 2026-09-20 | implemented | Made legacy pipeline tests inject their intended operator RBAC and ActionType semantics, retained unknown-principal denial and missing-catalog quorum two, and aligned the Bragi fixture with Conversation-before-Turn publication. Runtime code changed only by a comment compaction at the existing 800-line ceiling. | `current change`; 83 focused agent tests and 122 frozen replay tests passed; focused Ruff and strict mypy passed. | Retain protected CI evidence; no role, topic, approval, execution, or recovery authority changed. |
| 2026-09-20 | implemented | Split Huginn's bounded durable ingress journal across at most 64 deterministic shards and added revision-CAS migration that compacts the legacy single row. Routine claim and publication updates no longer duplicate authority-free delivery checkpoints into audit; recovery and migration remain audited. Exact total capacity, pending leases, normalized retry payloads, restart replay, collision rejection, and the broker acceptance/checkpoint boundary are unchanged. | `current change`; focused legacy migration, eviction, restart, lease, collision, checkpoint-audit, discovery, Ruff, and strict mypy checks. | Retain governed broker interruption and restart evidence; at-least-once redelivery remains possible across the broker-acceptance/checkpoint crash window. |
| 2026-09-20 | implemented | Made Huginn discovery health fail-visible. The snapshot reports projection binding and marks delivery-owned cursor, backpressure, and source-health signals `not_observed` instead of implying that absent observations are healthy. | `current change`; focused Huginn health contract and discovery suite. | Bind deployment-owned observations when available; no cursor, transport, or provider authority moved into Huginn. |
| 2026-09-20 | implemented | Reconciled the earlier ownership-correction and Loki rows: their Bragi and ResilienceScore source residuals are superseded by the later producer-completion rows above. | `current change`; append-only ledger ordering and focused producer evidence. | Deployed Bragi callbacks and governed runtime evidence remain; no source producer is still unimplemented. |
| 2026-09-20 | implemented | Removed Loki's raw `detected_at`/attribute timestamp fallback. ResilienceScore candidate cutoff now uses only Huginn-validated `occurred_at` or trusted `ingested_at`, so the real normalized producer path is reachable without accepting an unvalidated time source. | `current change`; focused source-time, ingestion-time fallback, raw-time rejection, and Huginn-to-Loki end-to-end checks. | Retain governed runtime score-refresh evidence; no durability claim is made for the bounded conversational projection. |
| 2026-09-20 | implemented | Added a bidirectional producer-completeness regression over all owned Pantheon topics. It would reject the removed dead claims and future ownership declarations without a concrete call path. | `current change`; complete registry invariant suite. | Extend the extractor only when a reviewed producer introduces a new call shape; do not add allowlisted dead topics. |
| 2026-09-20 | implemented | Added Bragi's missing `Conversation`, `UserPreference`, and `PostTurnReview` producer boundaries. Conversation publication is once per session and precedes its first Turn; preference payloads hash the principal and bind revision to a separate content digest; post-turn review reaches Norns only through the Bragi-owned topic. | `current change`; focused producer, privacy, idempotency, no-bus, Norns intake, conversational, runtime, governance, Ruff, mypy, import, and LOC checks. | Bind the deployed Operator preference store and non-blocking post-turn queue to the typed Bragi methods; retain restart and duplicate-delivery receipts. |
| 2026-09-20 | implemented | Added Loki's missing `object.resilience-score` producer from a strict Huginn-owned normalized Event. Boolean, non-finite, out-of-range, incomplete, or forged inputs produce no candidate; a valid candidate remains pending at Forseti until the other verticals arrive. The score participates in replay identity, so same-key score substitution closes to HIL instead of appearing duplicate. | `current change`; focused Loki producer, invalid-input, owner-authentication, score-substitution, Forseti pending-state, Wave 5, and cross-vertical checks. | Implement the separately declared Bragi session events and retain governed runtime score-refresh evidence. |
| 2026-09-20 | implemented | Removed four unproduced event-bus claims from `AgentSpec.owns`: embedded `ActionAttempt`, core RCA projection, and graph-only `Budget` and `SizingRecommendation`. The fixed 15 agents and global judge, approver, executor, auditor, and recovery roles are unchanged. | `current change`; Pantheon registry, topics, ontology alignment, doc parity, Console agent contract, and focused specialist checks. | Implement the separately declared Bragi session events and Loki `ResilienceScore` producer; retain graph materialization evidence separately from bus publication. |
| 2026-09-20 | implemented | Replaced process-only Huginn deduplication in production composition with a bounded StateStore CAS journal. Pending publication retains the original normalized Event and Change, active replica leases prevent concurrent takeover, startup restores completed keys, and idempotency-key payload substitution fails closed. | `current change`; focused publish-interruption, lease-expiry restart, live-claim collision, completed-key rehydration, payload-collision, discovery, runtime, Ruff, and mypy checks. | Retain governed broker interruption and restart evidence; at-least-once redelivery remains possible across the broker-acceptance/checkpoint crash window. |
| 2026-09-19 | implemented | Persisted Loki's proposal-level blast-radius reservations through revision-fenced StateStore updates and restored them before consumers start. Loki now reads Thor-owned safe terminal ActionRuns only to release an exact experiment, ActionType, and target reservation; failed, unknown, forged, or mismatched closure retains the reservation. Loki remains advisory and gains no judgment, approval, or execution authority. | `current change`; `loki_reservations.py`; Loki, runtime, subscription, restart, replay, and cross-replica focused checks; strict mypy and Ruff. | Retain a governed deployed chaos proposal, HIL, terminal ActionRun, and reservation-release trace; no Chaos enforce promotion is inferred. |
| 2026-09-19 | implemented | Removed ActionType-name heuristics from the shared irreversible-action decision. The catalog's `irreversible` field is now the only positive reversibility evidence; an unavailable catalog fails closed to quorum two. Forseti remains the judge, Var remains the approver, and Thor remains the sole executor. | `current change`; `action_semantics.py`; focused quorum and catalog regressions; framework layout, strict mypy, and Ruff. | Retain a deployed irreversible-action decision receipt with the pinned ActionType digest; no promotion state changes. |
| 2026-09-19 | implemented | Removed the example-principal fallback from Forseti's operator RBAC. An absent deployment policy now grants no operator action authority, while explicitly injected policies retain the same deny-and-security-event behavior. Agent roles, topics, model policy, and execution authority are unchanged. | `current change`; `forseti.py`; focused RBAC regressions; Wave 3 and framework layout checks; strict mypy and Ruff. | Retain deployed RBAC decision evidence with the existing live-shadow cohort; no enforce promotion is inferred. |
| 2026-09-17 | implemented | Restored Heimdall's explicit public export for the existing `ActionObservationHook` after integration exposed a strict-typing mismatch. Roles, topics, observation behavior, and authority are unchanged. | `current change`; `heimdall.py`; framework layout checks; targeted strict mypy. | No operational validation is inferred; retain the existing live effect-closure work. |
| 2026-09-16 | implemented | Preserved active handler state across periodic runtime snapshots and published the 15 independent agent records concurrently, so one slow Event Hubs round trip no longer serially extends every refresh. Roles, topics, judgment, and authority are unchanged. | `current change`; `delivery/agent_activity.py`; `runtime/bootstrap_pantheon.py`; focused agent activity, runtime shutdown, inventory, analyzer, and observation checks passed 260 cases; strict mypy and Ruff passed. | Retain deployed activity evidence. Initial full-inventory Rule evaluation and its current findings summary remain tracked by [issue #1199](https://github.com/dotnetpower/fdai/issues/1199). |
| 2026-09-15 | implemented | Repaired prediction-foundation CI registrations and moved Mimir context handling, Muninn Pattern reads, Heimdall history ingress, and Forseti readiness recording into focused framework helpers. Roles, owned topics, bounded waits, and authority are unchanged. | `current change`; [PR #1029](https://github.com/dotnetpower/fdai/pull/1029); 234 focused extraction tests, 316 admission-path tests, 55 structural regressions, three actual loopback PostgreSQL tests, strict mypy and Ruff. | Protected CI and merge remain pending; prediction follow-up work stays in issues #1021 through #1026. |
| 2026-09-15 | implemented | Reconciled Var's public pending-ticket types with protected main and moved its existing assignment-review binding into the focused assignment workflow helper after rebase. | `current change`; 125 focused layout, assignment, and Wave 3 tests; strict mypy, Ruff, and enforced LOC. | No approval, assignment, role, or authority behavior changed; resolve the recorded Low-severity residuals. |
| 2026-09-15 | implemented | Moved Var shadow-review records, bounded ticket eviction, and blocked-attempt deduplication into the focused ticket-identity helper after rebasing onto protected main. | `current change`; Wave 3, runtime, and quorum suites passed 193 tests; strict mypy, Ruff, agent-import, and enforced LOC passed with Var at 800 lines. | No approval behavior or authority changed; resolve the two recorded Low-severity residuals. |
| 2026-09-15 | implemented | Validated active durable ActionRun identity before lifecycle-rank suppression and before Thor can reserve idempotency or claim a resource. A peer generation sharing a correlation now fails before execution and cannot hide the canonical active run. | `current change`; active-row and cross-replica conflict regressions; provider lease helpers extracted under the LOC ceiling. | Resolve the two recorded Low-severity residuals. |
| 2026-09-15 | withdrawn | Withdrew reused-correlation generation replacement after independent review found decision, delivery-order, delete, and resource-claim races. Thor, Var, and durable adapters now bind each correlation to one immutable ActionRun identity and reject every distinct generation; exact same-generation replay remains idempotent. | `current change`; live and durable reuse rejection, legacy tombstone, released-claim, stale authority, and shadow partial-quorum restart regressions passed 300 tests. | Resolve the two recorded Low-severity residuals. |
| 2026-09-15 | implemented | Preserved the prior action idempotency generation in inactive Thor tombstones and CAS-replaced the row only for a distinct generation. Reused correlations now persist a new shadow HIL run without resurrecting the completed run. | `current change`; stale-generation suppression, tombstone replacement, and reused-correlation partial-quorum restart regressions passed. | Resolve the two recorded Low-severity residuals. |
| 2026-09-15 | implemented | Persisted Thor ActionRuns in production shadow mode whenever Var uses durable recovery, so an incomplete quorum and its exact matching run rehydrate together before the second approval. | `current change`; partial-quorum shadow restart plus runtime and bootstrap suites passed 137 tests; strict mypy and Ruff passed. | Resolve the two recorded Low-severity residuals. |
| 2026-09-15 | implemented | Bound Var approvals and Vidar rollbacks to one lifecycle-stable ActionRun digest, scoped their durable records by that identity, and made Thor reject stale authority messages before execution or claim release. | `current change`; authority identity, correlation-reuse, rollback, and full Agent suites; strict mypy, Ruff, agent-import, and LOC gates passed. | Persist matching Thor ActionRuns in shadow mode, then resolve the two recorded Low-severity residuals. |
| 2026-09-15 | implemented | Required Vidar to normalize a bounded non-whitespace rollback receipt before recording success, made the durable terminal codec reject blank/noncanonical receipts, and made Thor independently retain the resource claim for a blank succeeded payload. | `current change`; Wave 3, T2 recovery-chain, and Thor durability suites passed 161 tests; strict mypy and Ruff passed. | No source-level work remains for rollback receipt completeness; three Low-severity residuals remain open. |
| 2026-09-15 | implemented | Kept a saturated Norns recovery retryable by appending the inert fingerprint candidate before marking the fingerprint proposed. Capacity failure can no longer make an unpublished candidate appear delivered. | `current change`; focused saturation reproduction plus Norns durability, coverage, and runtime suites passed 162 tests; strict mypy and Ruff passed. | Resolve the three recorded Low-severity residuals without widening agent roles or authority. |
| 2026-09-15 | implemented | Consolidated the implemented T1/T2, Var, Vidar, Saga, Norns, and Bragi replay contracts in this focused runtime owner after the legacy Pantheon and project-structure documents reached their size ratchets. | `current change`; 1,372 campaign safety tests, 170 Cost Governance isolation tests with one environment-dependent PostgreSQL skip, strict mypy, Ruff, and structural/documentation gates. | Close the two recorded Low-severity residuals without widening agent roles or authority. |
| 2026-09-15 | implemented | Restored final CI compatibility without changing runtime behavior: moved verified execution-outcome classification to its focused module, bound the rubric test candidate to its trusted target, exercised Norns through `object.issue`, and renamed Var's locked private decision helper so the natural-language semantic detector does not misclassify canonical enum validation. | `current change`; focused ControlLoop package, rubric, and tier tests; Norns, Var, framework-layout, semantic-routing, Ruff, strict mypy, LOC, translation, and design checks. | The two recorded Low-severity residuals remain; no role, topic, approval, execution, or promotion authority changed. |
| 2026-09-14 | implemented | Removed an unrelated ActionRun fingerprint field from the activity-attribution change so durable and recovery identity remains unchanged. | `current change`; full mypy plus focused Thor durability and recovery regressions. | Retain deployed audit and activity evidence for the exact merged revision. |
| 2026-09-14 | implemented | Separated operational activity attribution into mechanical actor, accountable `owner_agent`, and authenticated `producer_principal`. Control-loop measurements map to Heimdall, RCA to Forseti, startup audit to Saga, observation campaigns to their declared owner, and Saga audit mirrors identify Saga without replacing the audited principal. | `current change`; service-contract, control-loop, provider-adapter, observation-campaign, startup-probe, pipeline, and Operator projection tests. | Retain deployed audit and activity evidence for the exact merged revision; no role, topic, or execution authority changed. |
| 2026-08-13 | in-progress | Replaced the broad W0-W8 completion claim with independently evidenced implementation areas. | current change | Gather live evidence and complete separately reviewed promotion before claiming validation or enforce operation. |
| 2026-08-14 | implemented | Made optional conversational T2 synthesis conditional on deterministic conflict evaluation over bounded T1 answer signals. | `current change`; 36 focused deliberation tests and framework-layout checks. | Retain governed runtime evidence for the no-escalation and conflict-escalation branches. |
| 2026-08-17 | implemented | Added a bounded Huginn-to-Heimdall continuity evidence handoff and retained the recognized observed reason on the Incident candidate. | `current change`; focused trace-to-Incident chain passed with forged action-like input excluded. | Retain the governed live scenario evidence tracked by issue #142. |
| 2026-08-23 | implemented | Added Heimdall's typed terminal ActionRun observation path with exact artifact restoration and independently verified Azure effect collection. | `current change`; executed-action observation, Azure collector, composition, runtime topic, and Pantheon parity checks. | Bind the deployment-owned signed-context issuer and retain a governed live closure receipt. |
| 2026-08-23 | implemented | Added the O7 immutable evidence consumer, manifest-bound causal and measurement-unit verifiers, durable receipt sink, and opt-in measurement job. | `current change`; operational-promotion source, runner, persistence, CLI, and Terraform checks. | Implement the governed live-batch producer and accumulate action-specific evidence before promotion review. |
| 2026-08-24 | implemented | Preserved every selected expected effect and its independent outcome in the operational hypothesis lineage without changing any agent role, topic, or authority. Singular-only stored records retain one-effect read compatibility, and ambiguous dual-field records fail closed. | `current change`; `hypothesis_lineage.py`; `ActionOption.yaml`; focused lineage and competency checks passed 15 cases. | Complete the remaining lineage producer, signed-context, and live-batch prerequisites. |
| 2026-08-25 | implemented | Made Thor recheck the live startup-readiness authority ceiling both when dispatching a Verdict and immediately after Human approval. A degraded, expired, or failed refresh now forces new and parked runs to shadow before executor I/O without changing AgentSpec, topics, judgment, approval, audit, or rollback ownership. | `current change`; Thor durable auto, approval, and authority-provider failure regressions; Pantheon layout and import gates. | Retain one deployed degraded-shadow ActionRun and prove the privileged executor was not invoked. |

### Remaining work

- [x] Reconcile one-to-many `expects` links with runtime expected-effect lineage and preserve one
  independent outcome per selected effect, as recorded in
  [Operational Learning Ontology](../rules-and-detection/operational-learning-ontology.md).
- [ ] Advance Saga audit and `object.issue` publication checkpoints through monotonic revision CAS,
  then retain a two-replica regression showing one audit append and one publication.
- [ ] Bind each issue operation id globally to one fingerprint and request digest, then retain a
  regression showing that reuse across fingerprints fails closed.
- [ ] Complete the remaining prerequisites: bind the deployment-owned signed-context issuer,
  preserve the remaining Forseti-owned causal lineage properties, construct the real runtime
  producer, and implement the governed live-batch producer.
- [ ] Demonstrate declared degradation behavior against operating dependencies, without widening
  any agent's role, topic ownership, model policy, or action authority.
- [ ] Complete [issue #1199](https://github.com/dotnetpower/fdai/issues/1199) by emitting durable
  baseline evaluation work from complete inventory, retaining Forseti judgment and Saga audit
  ownership, and materializing a current Rule findings summary without inferring zero from gaps.
- [ ] Run the declared KPI collectors against a retained live-shadow cohort on one pinned runtime,
  catalog, ActionType, workflow, and scenario-set revision.
- [ ] Retain authoritative outcome, recurrence, rollback, and zero-escape evidence with sample counts
  and confidence intervals for each promotion candidate.
- [ ] Complete an independent promotion review and record the authoritative promoted-set receipt
  before enabling or reporting pantheon enforce operation.
- [ ] Review T2 proposals grounded on retrieved case history, anomaly-action candidates,
  alert-noise learning, and every other learned-evidence consumer against the
  [learned and predicted output boundary](#learned-and-predicted-output-boundary), then close or
  record each path with a focused test. This is a follow-up hardening item for the closed
  [issue #1541](https://github.com/dotnetpower/fdai/issues/1541).

## Design at a glance

The waves describe dependency order, not separate sources of authority. Completed implementation
detail belongs to the current agent, workflow, ontology, and runtime owners. This document retains
only the coordination summary and the composition rules that connect those owners in a live
process.

| Wave | Bounded outcome | Current owner |
|------|-----------------|---------------|
| **W0** | Documentation and ontology foundations | [Agent Pantheon](agent-pantheon.md), [Agent Workflows](agent-workflows.md) |
| **W1** | Agent framework, fixed registry, topics, and two-port skeleton | [`agents/_framework/`](../../../services/core-control-plane/src/fdai/agents/_framework/) |
| **W2** | Saga, Mimir, Muninn, and Norns governance mechanics | [Agent Pantheon](agent-pantheon.md) |
| **W3** | Sensing, judgment, risk, rollback, and shadow execution chain | [Agent Pantheon](agent-pantheon.md) |
| **W4** | Deterministic-first conversation and arbitration | [Conversational Deliberation](conversational-deliberation.md) |
| **W5** | Cost, capacity, and resilience specialists | [Agent Pantheon](agent-pantheon.md) |
| **W6** | Audited handoff and security escalation | [Agent Pantheon](agent-pantheon.md) |
| **W7** | Independently promoted cross-agent workflows | [Agent Workflow Shadow Rollout](agent-workflow-rollout.md) |
| **W8** | KPI, promotion, and degradation evidence | [Agent Pantheon KPI and degradation policy](agent-pantheon.md#42-per-agent-kpi-success-and-degradation-signals) |

## 11. Wave 7 - Cross-agent workflows in shadow

The rollout order, per-workflow shadow gate, dependency, and anti-scope are owned by
[Agent Workflow Shadow Rollout](agent-workflow-rollout.md). Each workflow remains an independent
review, and no workflow reaches enforcement during this wave.

## Runtime composition contract

`PantheonRuntime` is the composition boundary for the fixed agent set. The implementation lives in
`services/core-control-plane/src/fdai/agents/_framework/runtime.py` and is assembled by
`services/core-control-plane/src/fdai/runtime/bootstrap_pantheon.py`.

### Durable authority and replay

These runtime contracts preserve the fixed role boundaries in [Agent Pantheon](agent-pantheon.md).
They provide restart and concurrency safety but do not grant judgment, approval, execution, audit,
recovery, or publication authority to a different agent.

#### Durable outbox rule

Every owner-local durable outbox follows the same retry contract: write a pending intent with the
stable idempotency key, publish the owned event, and only then mark the intent published. Startup
recovery republishes pending intents with the same idempotency key, so delivery is at-least-once and
consumers rely on their own idempotency fences instead of a best-effort broker acknowledgement.
Cancelled publish-to-mark windows are treated as replayable, not as proof that the work completed.
Terminal outbox rows compact into digest-only tombstones after the documented replay window for the
owning projection. The tombstone keeps the idempotency key, owner, topic, digest, and retention
deadline needed to suppress duplicate redelivery; it drops full payload bodies and mutable delivery
metadata.

#### Tier, approval, and command identity

- The authority ceiling evaluates an action at its actual originating T0, T1, or T2 tier. A
  fallback action cannot inherit T0 authority.
- Routing resolves nested `resource.type`, nested `resource.resource_type`, then the legacy flat
  form without guessing. T1 rejects malformed reuse identity, counter, confidence, and similarity
  evidence.
- T2 binds target, resource type, citations, and ActionType to trusted routing context. Exactly one
  cited routed rule authorizes the ActionType through `remediates` or `alternatives`, and that same
  rule flows through risk, human approval, and execution rendering. Catalog-declared
  `alternatives` are deterministic grounding evidence before semantic similarity.
- Mixed-model agreement requires distinct bounded canonical model identities. Different wrappers
  cannot let one model satisfy its own quorum.
- Var preserves the source ActionRun idempotency key and joins every normalized principal decision
  into an audited StateStore compare-and-swap (CAS) aggregate. Concurrent replicas derive quorum
  from the same immutable decision set.
- Var stores one final approval and its publication checkpoint before removing the ticket. Startup
  queries exact pending fields, finalizes terminal aggregates, and republishes stored final payloads
  before consumers start without asking a person to decide again.
- Thor stamps one lifecycle-stable ActionRun identity over correlation, action id and type, resource,
  action idempotency, parameters, quorum, initiator, rollback contract, verdict, and workflow
  lineage. Before any idempotency or resource claim, Thor atomically creates the initial durable
  ActionRun as a pending correlation claim. The first durable lifecycle publication promotes it to
  active; resource contention leaves it retryable but excludes it from restart recovery. Only the
  canonical identity is authoritative while pending, so a retry refreshes live non-identity fields
  such as shadow posture before promotion. Active rows and terminal tombstones preserve the
  canonical identity digest, so only an exact replay can recover the row. Duplicate dispatch reads
  only that correlation and never runs the cross-replica restart recovery sweep or changes an
  unrelated resource claim. A peer returns an exact active replay without caching the foreign run
  or its local mutex, and a pre-upgrade tombstone accepts only its matching non-empty idempotency
  generation as completed. Var scopes decision and final records by this identity, echoes it with
  explicit action fields, and Thor rejects a stale approval before execution. Thor and Var also
  claim the correlation for this identity; a different idempotency generation cannot reuse it.
- Restart never resurrects expired approval windows. Thor closes an approval that elapsed while the
  process was down with the same visible fail-closed expiry outcome it uses during live
  maintenance, so a resource is not held by a stale human-approval ticket.

#### Rollback claims and terminal replay

- Vidar claims the correlation and canonical rollback-command digest with an owner token and bounded
  lease before provider recovery. One stable effect-bearing field allowlist defines both executor
  input and digest, including parameters, action identity, workflow lineage, and rollback data while
  excluding regenerated delivery metadata such as `terminal_at`.
- A competing replica leaves a live lease unchanged and raises a retryable handler failure. After
  verified expiry, redrive closes the ambiguous claim as `execution_unknown`; revision CAS fences a
  late owner completion.
- In-process and durable replay validate the complete command digest. Terminal replay also validates
  schema, revision, owner tokens, lease, bounded identity, state, notes, and receipt. A successful
  rollback requires a normalized, non-whitespace, bounded `rollback_ref`. Thor independently
  validates the same receipt boundary before releasing its resource claim.
- Vidar scopes claim, terminal, and publication records by the same ActionRun identity and echoes it
  with action type, resource, and rollback contract. Thor ignores a stale or mismatched rollback
  without changing the current run or releasing its claim.

#### Parameter validation, idempotency, and safeguards

Correlation reuse is validated at execution. A retry with the same action identity remains
idempotent, but a different action under the same correlation becomes an auditable terminal
rejection rather than an ambiguous dispatch. Thor bounds verdict parameters before it creates or
persists an `ActionRun`; oversized, deeply nested, or non-schema fields are rejected before they
can become durable executor context, approval context, or audit material.

Executable non-shadow verdicts carry all seven safeguards on the wire: stop condition, tested
rollback, impact scope, dry-run, logical target lock, stable idempotency key, and two-phase audit.
Thor denies a Forseti-delivered `auto` or `hil` verdict with any missing safeguard before executor
I/O, regardless of idempotency-key shape or an attached kinetic proposal. Direct
`dispatch_verdict()` calls are an in-process test seam; a source-boundary test pins Thor's typed
port as the only production caller. Forseti emits those safeguards on executable rule and
arbitration verdicts; advisory verdicts keep typed stable idempotency keys without granting action
authority. Forseti's rule cache accepts only strictly newer, Mimir-authenticated rule revisions.

The `dry_run_evidence` safeguard field states where the dry-run safeguard comes from.
`upstream_receipt` cites a what-if or dry-run receipt carried by the triggering event.
`declared_obligation` is a deterministic obligation identity, not proof that a dry-run ran. Thor
counts each non-shadow dispatch that relies on an obligation as `dispatch:dry_run_obligation_only`.
Core executor paths that call `evaluate_pre_dispatch` compute their own dry-run receipt; a Thor
pre-flight simulation receipt remains planned work.

#### Impact scope and batch semantics

The current runtime does not expose `ActionAttempt`, `attempt_id`, or a typed per-attempt rollup
field. Batch semantics remain planned. Exit condition: a multi-target ActionType produces
independent attempt identities, per-target rollback isolation, a typed rollup field, and Saga
per-attempt plus rollup audit entries. Planned failure isolation keeps a failing attempt scoped to
its own target, preserves sibling successes, records the mixed outcome on the rollup `ActionRun`,
and writes both per-attempt and rollup audit entries. Partition keys preserve per-resource, not
cross-resource, ordering.

#### Rollback quorum and recovery decisions

Thor re-derives the irreversible-action quorum from ActionType semantics before leaving
`verdicted` for any executable state. Human approvals bind to the exact `ActionRun` identity, Var
producer evidence, approval idempotency key, approver set, and quorum evidence; when durable Var
readback is configured, Thor requires the current stored approval before it advances. Var also
re-derives quorum from ActionType semantics and treats unknown or catalog-missing actions as
requiring the irreversible minimum. Vidar admits rollback only for Thor-owned `ActionRun` messages
with matching identity and rollback evidence.

Forseti treats `auto` as an upper bound. Without governed reversible ActionType semantics, or when
the verdict requires quorum `>= 2`, the runtime caps the decision to human approval (`hil`). The
judgment table is injected and digest-stamped; Forseti records deterministic verdict keys from the
event identity and action instead of falling back to a bare correlation. Retired or revoked rules
also cap `auto` to `hil`. Arbitration decisions are accepted only from Odin, and per-domain
dispositions are honored before a resolved arbitration verdict is emitted. Resolved arbitration
verdicts carry the resulting autonomy ceiling and the action idempotency key Thor will enforce.

`execution_unknown` is a recovery decision, not a successful or failed action. Vidar closes it only
through the rollback contract or a visible `rollback_refused` state when the required durable
rollback preconditions are missing. Thor releases or fences the resource lock after failed or
refused rollback so the stuck run remains visible without holding the resource indefinitely.

#### Arbitration, narration, audit, and specialist replay

- Forseti persists pending arbitration context, cross-vertical candidate deadlines, completed
  candidate fences, and arbitration completion markers. After restart it can consume Odin's stored
  decision, close unresolved cases visibly, and avoid emitting a second completion for the same
  arbitration. Pending cross-vertical deadlines are scheduled by one bounded timer over ordered
  deadlines instead of one sleeping task per correlation.
- Bragi persists conversation, handoff, and turn outboxes with arrival-ordered turn reservations, so
  a slow responder or broker publish cannot reorder a session transcript after recovery.
- Bragi-owned handoff escalation and post-turn review publications use the same durable outbox
  rule as other owner-local publications: recovery republishes the same idempotency key and marks a
  row published only after broker publish returns.
- Saga's audit chain resumes from the durable head. It checkpoints mutation, publication, and
  completion before consumers start, so the local audit mirror does not fork a new chain after a
  restart. Both in-memory and provider-backed audit chains recompute entry hashes to detect field
  tampering and compare against a sealed head or expected length to detect truncation. Saga verifies
  incrementally from anchored checkpoints and serves correlation replay through an index rather than
  scanning the full chain.
- Odin stores the per-correlation arbitration decision fence. A redelivered arbitration request
  replays the original decision instead of asking Odin to rank the same case again.
- Forseti preserves per-domain arbitration lineage and freshness in each request. Stale domain
  signals are counted, excluded from the join, and never converted into a synthetic fresh
  arbitration input.
- Heimdall, Njord, and Freyr recover their observation, advisory, and forecast fences from the
  injected store before accepting replayed source events, so redelivery can complete unfinished
  publications without advancing duplicate windows or stale baselines.

#### Durable handoff and learning

- Saga claims each escalation in the runtime StateStore before external mutation. Typed handoff uses
  the additive `IdempotentIssueTrackerAdapter`, which binds one stable operation id to exact issue
  content. Legacy `IssueTrackerAdapter` implementations remain available for direct escalation.
- The shipped `StateStoreIssueTrackerAdapter` CAS-persists issue state and exact operation results
  and rehydrates its bounded live projection before consumers start. A live provider override
  provides equivalent provider-side durability; `InMemoryGithubIssueAdapter` remains test-only for
  typed runtime handoff.
- Saga checkpoints mutation, audit, publication, and completion. It records completion only after
  `object.issue` publication; a missing bus keeps prior checkpoints pending and raises a retryable
  failure. Closure stays outside the bounded occurrence-comment list and is validated before CAS.
- Saga handoff issue materialization recovers unpublished `object.issue` records on restart.
  Legacy handoff fallbacks deduplicate by the problem fingerprint before creating or commenting on
  an issue.
- Norns claims the handoff idempotency key, CAS-applies a pending operation to a durable fingerprint
  count, and retains each candidate until publication or deterministic hold marks it delivered.
  Startup queries exact pending fields one bounded item at a time. A blocked head pauses recovery,
  while the next successful flush continues with durable candidates behind it. Capacity is
  validated and the candidate is appended before its fingerprint enters the proposed set, so a
  saturated recovery remains retryable.

> **Current limitations:** Concurrent Saga replicas can append duplicate audit and issue-publication
> events after the single operation-bound external mutation. Downstream publication idempotency and
> Norns deduplication bound the effect. The shipped issue adapter also scopes operation-id binding to
> one fingerprint; Saga's separate durable handoff claim mitigates the shipped typed caller.

#### Bounded shared state

`StateStore` exposes one removal primitive: `delete_states_beyond(prefix, retain_newest)`. It drops
the oldest rows past a projection bound in the same order returned by `read_states`. It cannot name
one key, so it cannot erase an authoritative record or audit entry. Enforcement composition
requires explicit `thor_state_store`, `vidar_state_store`, `var_state_store`, and
`forseti_state_store` bindings. Production provides the durable Thor store in shadow and enforce
modes whenever Var recovery is durable, and it binds the optional governance and specialist stores
to the incident audit store: `forseti_state_store`, `bragi_state_store`, `odin_state_store`,
`proposal_rate_limit_state_store`, `heimdall_state_store`, `njord_state_store`, and
`freyr_state_store`. `ordered_poison_halt_state_store` remains opt-in until an operator clear
surface exists. Enforcement still requires every exact agent-owned binding before process-local approval or rollback state can be used. An inactive
Thor row retains its stable idempotency generation. The same generation remains suppressed, while a
different generation fails closed, including pre-campaign tombstones whose generation is unknown.
Active rows are validated before resource claim, lifecycle-rank suppression, or execution. Released
resource claims require the same correlation, idempotency key, and action fingerprint.
Long-lived agents page durable recovery state in bounded slices before they accept replayed work.
Per-key locks are reference-counted or reclaimed after terminal completion, so an evicted or
completed key cannot leave an unbounded process-local lock behind.
The in-process bus, testing bus, and local bus keep bounded retained envelopes and dead letters;
abandoned consumer groups expire rather than accumulating indefinitely. Maintenance ticks coalesce
when a prior tick is still running, so slow health work cannot create an unbounded backlog. Redrive
loads dead-letter batches through explicit caps and records any remaining backlog for the next
operator action instead of draining without a bound.

### Conversational action re-entry

Bragi uses a `proposal_sink` wired to `Huginn.ingest`, the sole writer of `object.event`, and never
publishes a mutation topic. The proposal carries the operator as `initiator_principal`, returns a
trackable correlation id, and renders typed pipeline progress without executing. Forseti and Thor
preserve the initiator, and Var enforces no-self-approval. Entry RBAC rejects action requests below
`Contributor`. Huginn accepts operator proposal fields only for
`event_type == "operator_request"` and treats `operator_initiated` as a strict Boolean, so an
external signal cannot spoof an operator action.
The initiator principal participates in idempotency material, and typed params carry only action
arguments plus digests or refs for conversational lineage, never raw question text or raw session
identifiers. Huginn bounds raw request shape and depth, rejects unsafe identity characters,
normalizes accepted source times to UTC with bounded skew, and records content-free rejection
counters for inputs it cannot trust. Raw operator requests keep strictly bounded fields and a
server-owned channel: `ingress` for authenticated service producers and `conversation` for Bragi's
in-process proposal entry point. Huginn never copies unowned authority fields such as
caller-supplied initiator, ActionType, or params from raw ingress, and Forseti's RBAC denies unknown
initiators before a verdict can form.

### Assembly and lifecycle

- `PantheonRuntime.build(provider, raw_event_topic)` instantiates the enabled agents, binds one
  `EventBusBridge`, and registers each declared subscription under an agent-specific consumer group.
- Raw ingress uses a distinct pantheon consumer group and enters through Huginn. It runs beside the
  primary control loop without stealing records or becoming its dependency.
- `run()` isolates consumer failures, restarts bounded transient failures, and keeps healthy sibling
  consumers running. Shutdown remains bounded.
- Startup binds the recovery-effect observer intake, restores ContextIndex recovery before replay,
  and fails closed if ContextIndex sealing cannot use durable Saga audit.
- The runtime is enabled and shadow by default. `FDAI_START_PANTHEON=0` disables it, and missing
  consumer composition causes an explicit skip rather than an in-memory substitute.
- Thor remains `enforce=False` unless a separately reviewed promotion enables enforcement. Enforce
  composition requires a durable Saga audit binding and durable in-flight ActionRun storage.
- During cross-vertical arbitration, constitutional hard constraints remove ineligible options
  before Odin ranks the remaining soft objectives.

### Learned and predicted output boundary

In the default observation-first profile, learned patterns and predictions remain advisory
evidence. The `governed-execution` add-on of the
[runtime deployment profile](../deployment/runtime-deployment-profiles.md#design-at-a-glance)
is the only selection. Core composition reads it once through
`RuntimeProductSelection.governed_execution`: the control-loop builder passes the value to the
control loop, and Pantheon composition passes the control loop's value to Forseti. Environment
names, fork markers, package presence, `FDAI_PANTHEON_ENFORCE`, and executor bindings never
select it. Selection grants no authority by itself: the unchanged risk gate, Var approval, Thor
lifecycle, safeguards, and promotion state still decide every outcome.

| Input | Default profile | `governed-execution` add-on selected |
|-------|-----------------|------------------------------------|
| Heimdall `object.forecast` | Forseti publishes an ActionType-free Verdict with reason `governed_execution_unselected`, `advisory_source: forecast`, and a `shadow_only` ceiling. It derives no rule match, arbitration, or ActionType from forecast fields. | The existing rule-match, arbitration, risk, and approval gates run with one deliberate restriction: when Forseti derives an action Verdict from a forecast that doesn't declare exactly `mode: enforce`, it caps that Verdict at `shadow_only` after every other ceiling and records `source_mode` on it. ActionType-free and arbitration Verdicts for a forecast carry no `source_mode`. |
| Freyr `object.capacity-forecast` in arbitration | Odin still weighs the objectives, but Forseti builds no DecisionCase options, planning record, or kinetic proposal. The settled Verdict names no ActionType and records the arbitration outcome as evidence. Every outcome still marks the correlation unresolved, as the governed path does without a DecisionCase, so a later observed signal on it is held from automatic execution: Thor's durable correlation claim refuses the gated Verdict in process and after a restart or gate eviction, and Thor drops it only when it runs without a durable store. | The existing DecisionCase, arbitration, kinetic-proposal, and human-review path runs. |
| T1 reuse of a learned pattern | The control loop writes `control_loop.t1_reuse_advisory` and stops before it builds an Action, so no execution authorization, risk gate, approval request, simulation, or dispatch runs. | The existing verification, risk gate, approval, and dispatch path runs. |

Thor ignores an ActionType-free Verdict with this reason in every profile, so no ActionRun,
approval, rollback, or executor call follows. For an advisory arbitration Verdict, Thor also
writes a terminal non-action correlation claim to its ActionRun store. Recovery never loads the
claim, but the existing correlation check refuses every later Verdict on that correlation, as it
refuses reuse of the ActionRun that the governed path records. The predicate reads no selection; Forseti emits the
reason only without the add-on. Deterministic judgment of observed signals is unchanged in both
profiles. The forecast `mode` cap is the one restriction the boundary adds to the selected
profile; it keeps an undeclared or shadow forecast shadow-first instead of trusting a missing
mode.

### Configurable and observable seams

| Seam | Contract |
|------|----------|
| `consumer_group_prefix` | Isolates consumer groups by environment. |
| `disabled_agents` | Removes optional agents from binding and subscription; Saga and Vidar cannot be disabled. |
| `governed_execution_selected` | Carries `RuntimeProductSelection.governed_execution` from the composed control loop to Forseti. The default keeps learned and predicted input advisory. |
| `saga` | Supplies append-only durable audit for enforce operation. |
| `thor_state_store` | Rehydrates non-terminal ActionRuns, preserves resource locks after restart, and holds advisory arbitration correlations with terminal non-action claims. |
| `vidar_state_store` | Persists rollback claims, owner leases, fencing revisions, and terminal receipts. |
| `var_state_store` | Persists approval decisions, final payloads, and publication checkpoints. |
| `forseti_state_store` | Persists judgment ceilings, arbitration context, cross-vertical candidate deadlines, and completion markers. Required for enforce composition. |
| `bragi_state_store` | Persists conversation, handoff, and turn outboxes so session recovery preserves arrival order and republishes pending conversational records. |
| `odin_state_store` | Persists arbitration decision fences and replays the original decision for a redelivered request. |
| `proposal_rate_limit_state_store` | Persists proposal budget windows and atomic reservations across replicas. |
| `ordered_poison_halt_state_store` | Optionally persists ordered-consumer poison halts. Production leaves it unbound until an operator clear surface exists. |
| `heimdall_state_store` | Persists observation windows, alert budgets, relay outboxes, and effect-observation replay fences. |
| `njord_state_store` | Persists cost sample fences, stale-sample guards, and advisory baselines. |
| `freyr_state_store` | Persists capacity sample fences, smoothing state, forecast outboxes, and cost evidence used by capacity graduation. |
| `muninn_state_store` | Backs Muninn projections, Saga issue state, and Norns handoff-learning recovery. |
| `payload_validator` | Rejects malformed publications at the provider boundary. |
| Consumer restart bounds | Apply exponential backoff and a finite restart cap without cancelling siblings. |
| `health()` | Reports bridge metrics, agent and consumer state, unavailable agents, continuity, and effective enforcement. |
| Shadow observer | Measures would-be decisions without consuming records from authoritative subscribers. |
| `ShadowDivergenceLedger` | Joins shadow and authoritative decisions by correlation id for promotion evidence. |
| `heimdall_action_observation_hook` | Restores exact terminal ActionRun artifacts and records only independently verified effect observations. |
| Heartbeat | Emits the bounded health snapshot at the configured cadence. |

### Event-bus invariants

- Topic ownership and partition keys come from the shared topic registry. Mutation topics require a
  non-empty resource key, and an invalid key fails closed before publication.
- Every owned-topic publication must carry non-empty `correlation_id` and `idempotency_key` at the
  publish boundary. Mutation topics also require `resource_id`. The in-memory bus and production
  bridge fail closed for unsafe mutation gaps and record shared-envelope gaps for other owned
  topics.
- Published envelopes carry producer, schema, correlation, and idempotency metadata. Consumer-side
  ownership checks dead-letter an impostor publisher before handler delivery.
- Distinct handlers of one agent on one topic fan out through distinct deterministic consumer
  groups; a single handler preserves its existing group id. Ordered poison halts all sibling
  consumers for the topic. Invalid owned records are dead-lettered once per broker record with the
  failing consumer identity.
- Handler retries and per-topic timeouts are bounded. Handlers can mark short cooperative
  cancellation-safe critical sections, so a wedged handler still times out while a durable commit
  window can finish.
- Observer callbacks and dead-letter writes are bounded. Ordered mutation streams halt when a dead
  letter cannot be written, so a later effect cannot overtake a failed earlier effect.
- DLQ redrive is an explicit operator action. DLQ write failure is counted and isolated from healthy
  consumers, except for ordered consumers where the halt preserves stream order.
- DLQ redrive is batch-bounded and preserves owner, schema, envelope, and partition validation on
  every record. A redrive batch that reaches its cap leaves the rest parked with observable backlog
  evidence instead of looping until empty.
- Proposal budgets reserve capacity, publish the proposal, and then commit the reservation. The
  durable limiter uses atomic CAS reservations across replicas and releases the reservation on
  failure or cancellation.
- `InMemoryBus` follows the same envelope, partition, timeout, and failure-isolation contract as the
  production bridge where local tests need parity. Options cover payload validation, bounded
  handler retries, duplicate-delivery simulation, and ordered poison halt for mutation topics.
- Remaining local-bus gaps are intentional: delivery stays sequential and in-process, with no
  concurrency across topics and no broker-level partition rebalancing.
- Local and test bus retention is finite. Old accepted envelopes, dead letters, and abandoned
  consumer-group state expire under explicit bounds; this keeps parity tests deterministic without
  pretending the local bus is a production broker.
- `LocalEventBus` keeps committed offsets across subscription restarts. Only explicit
  `reset_offsets()` replays committed records, so restart recovery and replay tests remain
  distinguishable.
- Agent publication uses the `PantheonBus` protocol, so runtime composition can replace delivery
  adapters without changing role or authority contracts.

### Rate-limit, health, and bounded backlogs

Runtime rate-limit enforcement uses a sliding window, not a fixed bucket, so boundary bursts do not
double the effective rate. Excess proposals enter a bounded queue; overflow is dropped with a
`rate_limit_exceeded` audit entry for Saga and Norns to learn why the agent burst.

Health and KPI snapshots distinguish measured values from unavailable evidence. Missing,
stale, incomplete, or degraded samples render `value: null` with an evidence state and degradation
facts; promotion gates treat that as failure, not as zero or success. Coverage claims are
measured-only: workflow 7 reports degradation facts for unavailable or stale measurements rather
than extrapolating from synthetic traces. Freyr capacity freshness follows the same rule: a gap in
fresh utilization evidence blocks automatic graduation and records the freshness gap instead of
reusing an old sample. Saga audit digests use strict canonical JSON over finite JSON-native values;
non-JSON values, NaN, Infinity, or process-specific renderings are held rather than hashed.

## Governance and rollback

The authoritative cross-wave rules are maintained in the repository instructions:

- Documentation and bilingual updates: [Coding Conventions](../../../.github/instructions/coding-conventions.instructions.md) and [Language Policy](../../../.github/instructions/language.instructions.md).
- Fixed agent roles and permissions: [Agent Pantheon Instructions](../../../.github/instructions/agent-pantheon.instructions.md).
- Fork customization: [Customer-Agnostic Scope](../../../.github/instructions/generic-scope.instructions.md).

Each bounded wave remains independently reversible. A newly composed stage starts in shadow, and a
rollback restores the prior binding without granting authority or rewriting historical evidence.

## Related docs

| To learn about | Read |
|----------------|------|
| Fixed roles, topics, actions, and degradation | [Agent Pantheon](agent-pantheon.md) |
| Cross-agent workflow definitions | [Agent Workflows](agent-workflows.md) |
| Per-workflow rollout order and evidence | [Agent Workflow Shadow Rollout](agent-workflow-rollout.md) |
| Runtime source ownership | [Project Structure](../architecture/project-structure.md) |
| KPI measurement and promotion evidence | [Goals and Metrics](../architecture/goals-and-metrics.md) |
| Supported downstream bindings | [Downstream Fork Guide](../fork-and-sequencing/downstream-fork-guide.md) |
