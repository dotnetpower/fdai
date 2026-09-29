# Workflow Control-Loop Integration implementation ledger

This delivery ledger preserves reviewable implementation scope, append-only transitions,
and resumable work while the roadmap owner remains focused on normative design.

## Implementation status

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| Shadow and typed enforce orchestration | implemented | [`test_orchestrator.py`](../../../services/core-control-plane/tests/core/workflow/test_orchestrator.py), [`test_coordinator.py`](../../../services/core-control-plane/tests/core/workflow/test_coordinator.py), [`test_postgres_workflow_dispatch_replicas.py`](../../../services/core-control-plane/tests/persistence/test_postgres_workflow_dispatch_replicas.py) | Shadow cannot mutate, and enforce proposals re-enter typed ingress with attempt-scoped identity. PostgreSQL replica contention, duplicate delivery, expired claims, a crash before or after publication, and restart redelivery retain one forward dispatch record per Process step attempt. Only the current claimant publishes, and a crash after publication republishes the same attempt-scoped idempotency key. |
| Durable journal, projection, and approval | implemented | [`test_projection.py`](../../../services/core-control-plane/tests/core/workflow/test_projection.py), [`test_workflow_approval.py`](../../../services/core-control-plane/tests/delivery/persistence/test_workflow_approval.py) | Revisioned Process state, retryable projection, quorum, timeout, and no-self-approval have focused coverage. |
| Compensation and durable target hold | implemented | [`test_automation_hold.py`](../../../services/core-control-plane/tests/core/workflow/test_automation_hold.py), [`test_orchestrator.py`](../../../services/core-control-plane/tests/core/workflow/test_orchestrator.py), [`test_control_loop_authority.py`](../../../services/core-control-plane/tests/core/test_control_loop_authority.py), [`test_gate.py`](../../../services/core-control-plane/tests/core/risk_gate/test_gate.py) | Incomplete recovery creates a restart-safe, duplicate-safe hold that denies ordinary forward dispatch. Only matching verified recovery can release it. |
| Guard evaluation | implemented | [Guard evaluation](../../roadmap/decisioning/workflow-control-loop-integration.md#42-guard-evaluation-seam), [`test_guard_fail_closed.py`](../../../services/core-control-plane/tests/core/workflow/test_guard_fail_closed.py) | The runtime binds `ChangeWindowWorkflowGuardEvaluator` over the architecture-review gate. Missing, stale, malformed, and unavailable evidence all block the step and record a bounded `guard_error`. |
| Governed Python, schedule, command, and shell paths | in-progress | [Governed tasks and schedules](../../roadmap/decisioning/workflow-control-loop-integration.md#45-governed-python-tasks-and-cron-schedules) | Validation and bounded sandbox mechanics exist, but live executor and production scale-out evidence remain incomplete. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-09-14 | implemented | Aligned the local workflow example with the paired Azure CLI authentication confirmation required by the Operator boundary. | `current change`; `tools.console`; focused launcher environment tests. | No workflow authority changed. |
| 2026-08-14 | in-progress | Adopted the implementation ledger without reconstructing earlier provenance. | `current change`; current source and focused tests listed in the scope table. | Complete policy binding and production concurrency evidence. |
| 2026-08-14 | implemented | Recorded the validated FDAI-CONST-009 control-loop boundary: incomplete compensation issues a durable hold, ordinary dispatch is denied, and matching recovery remains Human approval-gated until verified release. | `228f0779e`; focused hold, compensation, control-loop, and risk-gate checks passed 10 tests; centralized validation passed. | Complete the unrelated guard binding, distributed dispatch evidence, and governed task work below. |
| 2026-08-14 | implemented | Made bound guard evaluation fail closed: a stale evaluation clock, a raising or unavailable evaluator, and a non-boolean result each block the step and record a bounded `guard_error` in the `workflow.step` audit row. | `current change`; `workflow_step_executor.py` and `test_guard_fail_closed.py`; focused workflow checks passed 101 cases; task-scoped Ruff and strict mypy passed. | Complete the multi-replica dispatch evidence and governed Python-task executor work below. |
| 2026-09-29 | implemented | Retained multi-replica workflow dispatch evidence. Each enforce action step now writes an attempt-scoped dispatch claim lease, publishes only while that claim is current, and records the single `ACTION_DISPATCHED` record with the returned reference after publication. A claim without a dispatch record blocks retry in Core and in the Operator retry-admission mirror, the dispatch record payload keeps its existing shape and links the claim only through `causation_id`, and concurrent duplicate transitions replay idempotently in PostgreSQL. | `current change`; `services/core-control-plane/src/fdai/core/workflow/dispatch_claim.py`, `step_helpers.py`, `workflow_step_executor.py`, `workflow_retry.py`, `services/core-control-plane/src/fdai/delivery/persistence/postgres_process_runtime.py`, `services/core-control-plane/src/fdai/shared/providers/process_runtime.py`, `services/operator-service/src/fdai_operator_service/process_retry_admission.py`, and the workflow, process-runtime, replica, and retry-admission tests. With the loopback validation database, the Core workflow, delivery persistence, process-runtime, replica, and alert-noise workflow suites passed 891 tests, and `services/operator-service/tests/test_process_transition_projection.py` passed 10 tests. Also with that database, `pytest -p no:randomly tests/persistence/test_postgres_workflow_dispatch_replicas.py tests/persistence/test_postgres_process_runtime.py` passed 5 tests, and three randomized reruns of the replica harness passed 3 tests each. The harness covers concurrent duplicate delivery, a crash after claim, a crash after publication before recording, lease takeover, one dispatch record, and one terminal outcome per attempt. | Complete the governed Python-task live executor and retain sandbox, outcome, and recovery receipts without granting the Operator API executor identity. |

### Remaining work

- [x] The concrete `ChangeWindowWorkflowGuardEvaluator` binding is tested end to end, and missing,
  stale, malformed, and unavailable evidence each block the step fail-closed.
- [x] Retain multi-replica locking and duplicate-delivery evidence proving one forward dispatch per
  Process step and attempt; `test_postgres_workflow_dispatch_replicas.py` covers duplicate
  delivery, a crash after claim, a crash after publication, lease takeover, restart redelivery, one
  dispatch record, and one terminal outcome per attempt on loopback PostgreSQL.
- [ ] Complete the governed Python-task live executor and retain sandbox, outcome, and recovery
  receipts without granting the Operator API executor identity.
