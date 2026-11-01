# Ontology-Grounded ARB Delivery Plan implementation ledger

This ledger tracks the dependency-ordered delivery campaign and keeps observed implementation
evidence separate from the target sequence.

## Implementation status

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| ARB-1 Ontology truth | implemented | `core/operational_context/materializer.py`; `core/impact_analysis/change_assessment.py`; `agents/{huginn,forseti}.py`; focused context, impact, agent, and bootstrap tests | Planned-change assessment now preserves the requested release and derives authentication, freshness, release match, conflict, and truncation evidence from one exact verified snapshot. |
| ARB-2 Agent evidence loop | implemented | `core/architecture_review/{observation_loop,observation_trace,projection}.py`; `agents/_framework/runtime.py`; runtime composition and durable StateStore adapter; `services/core-control-plane/tests/core/architecture_review/` (`73 passed`) | The injected provider-neutral path composes context, evidence bundle, scenario, DecisionCase, ImpactEnvelope, recommendation, and derived ReviewCase under Forseti, and `build_owned_architecture_review_stage_records` emits distinct owned-topic records across all 12 ARB stages without synthesizing missing stages. |
| ARB-3 Decision authority | implemented | `core/architecture_review/{readiness,decision_receipt,projection}.py`; `delivery/architecture_review_decision_receipt.py`; Approval and Decision `1.1.0`; focused ARB tests | Provider-backed evidence body attestation, accepted blocker contracts, and an immutable receipt bind exact case, evidence, conditions, authority, approvals, and audit identity. Runtime production readiness now derives from the latest unambiguous validated receipt. Deployment-owned owner/evidence values and a governed receipt remain operational qualification. |
| ARB-4 Effect closure | implemented | `core/architecture_review/effect_closure.py`; `tests/core/architecture_review/test_effect_closure.py` (`5 passed`) | Links `Change -> DecisionCase -> ImpactEnvelope -> ActionRun -> ObservedOutcome` in control-only mode (`arb_execution_authority=False`), requires independent Heimdall observation within the declared window (rejecting executor self-scoring), keeps missing/incomplete/out-of-window observations pending, and emits a bounded Vidar recovery request when an effect fails or a stop condition/protected objective is violated. |
| ARB-5 Learning and rollout | not-started | Shared Muninn, Norns, Mimir, and promotion foundations | No ARB-specific retained cohort or promotion evidence exists. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-08-29 | in-progress | Started ARB-2 by binding the immutable ARB observation trace to owned runtime topics through a dedicated non-agent consumer group. The binding replays duplicate, reordered, and restarted delivery deterministically and retains terminal observer degradation evidence without direct agent calls or execution authority. | `current change`; `services/core-control-plane/src/fdai/core/architecture_review/{__init__,observation_trace}.py`, `services/core-control-plane/src/fdai/agents/_framework/runtime.py`, `services/core-control-plane/tests/core/architecture_review/test_observation_trace.py`, `services/core-control-plane/tests/agents/{test_runtime,test_njord_cost_governance}.py`; focused pytest, Ruff, strict mypy, and documentation guard checks. | Extend the remaining owned ARB stage records and derive the `ReviewCase` projection so the first observation-mode vertical slice can close end to end. |
| 2026-08-29 | in-progress | Recorded the new typed planned-change graph evidence receipt and accepted blocker contract checks while keeping exact context sourcing and immutable decision receipts open. | `current change`; `services/core-control-plane/src/fdai/core/impact_analysis/change_assessment.py`, `services/core-control-plane/src/fdai/core/architecture_review/readiness.py`; focused ARB impact and readiness checks in the preceding owner batches. | Finish ARB-1 exact context sourcing, then continue to ARB-2 through ARB-5 in order. |
| 2026-08-29 | in-progress | Completed ARB-1 exact snapshot sourcing and the provider-attestation portion of ARB-3 while preserving the dependency order and leaving decision authority closed. | `current change`; exact snapshot batch; injected evidence provider boundary; focused context, impact, agent, readiness, and CLI checks. | Complete ARB-2, then bind the immutable ARB-3 decision receipt before any authority-bearing transition. |
| 2026-08-29 | in-progress | Added the immutable ARB-3 receipt contract and receipt-bound projection with independent approval identity checks. The receipt records authority evidence but explicitly grants no execution authority. | `current change`; receipt and projection modules, versioned Approval and Decision declarations, and focused ARB contract tests. | Complete ARB-2, then derive ARB-3 production readiness from the immutable receipt. |
| 2026-08-24 | in-progress | Defined five dependency-ordered work packages and an observation-mode first vertical slice. | `current change`; owner document, paired translation, current source evidence, and focused documentation checks. | Deliver ARB-1 through ARB-5 in order and retain executable evidence at each exit. |
| 2026-10-18 | implemented | Completed the locally actionable ARB-3 receipt-readiness boundary. The runtime guard reads the projected immutable receipt and fails closed on absence, ambiguity, digest failure, review/evidence/revision drift, non-conformant outcome, ineffective time, or missing human approval. | `current change`; ARB readiness, ontology receipt adapter, runtime guard composition, and 32 focused tests; task-scoped Ruff and strict mypy passed. | Complete ARB-2's remaining owned-topic runtime composition before ARB-4 or ARB-5 can claim end-to-end evidence. Deployment bindings remain external. |
| 2026-10-18 | implemented | Composed the locally actionable ARB-2 provider-neutral path into the running Pantheon. A complete injected source pair and ontology store bind only Forseti; durable StateStore identity and projection status prevent cross-replica duplicate evaluation and downgrade interrupted projection to hold. | `current change`; complete source bundle, runtime/Forseti wiring, persistence adapter, and 194 focused observation, persistence, Forseti, runtime, layout, and composition-split tests; task-scoped Ruff and strict mypy passed. | Extend specialist-owned topic records and retain a governed provider-backed trace; those evidence sources remain deployment-owned. |
| 2026-11-02 | implemented | Completed ARB-2's distinct owned-topic stage records (`build_owned_architecture_review_stage_records` and stage inference for context, evidence bundle, scenario branch, DecisionCase, ImpactEnvelope, and recommendation with verified derived `ReviewCase` projection) and ARB-4's independent multi-effect closure and bounded Vidar recovery coordinator (`effect_closure.py`). | `current change`; `services/core-control-plane/src/fdai/core/architecture_review/{observation_trace,effect_closure}.py`; `services/core-control-plane/tests/core/architecture_review/` (`73 passed`); Ruff and strict mypy passed. | Complete ARB-5 with a pinned observation cohort and independently reviewed promotion evidence. |

### Remaining work

- [x] Complete ARB-1 with one exact planned-change context that fails closed on stale, mixed,
  incomplete, conflicting, unauthenticated, and truncated ontology evidence.
- [x] Complete ARB-2's owned-topic trace with distinct context, evidence-bundle, impact-envelope,
  recommendation, and projection records. The provider-neutral runtime path and derived projection
  are implemented without direct agent calls (`observation_trace.py`, `test_observation_trace.py`:
  `8 passed`).
- [x] Complete ARB-3 by deriving production readiness from the implemented immutable decision
  receipt; provider-verified evidence remains a required receipt input.
- [x] Complete ARB-4 with independent multi-effect closure and a recovery fixture
  (`effect_closure.py`, `test_effect_closure.py`: `5 passed`).
- [ ] Complete ARB-5 with a pinned observation cohort and independently reviewed promotion
  evidence showing zero policy escapes.
