# Workflow Control-Loop Integration implementation ledger

This delivery ledger preserves reviewable implementation scope, append-only transitions,
and resumable work while the roadmap owner remains focused on normative design.

## Implementation status

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| Shadow and typed enforce orchestration | implemented | [`test_orchestrator.py`](../../../services/core-control-plane/tests/core/workflow/test_orchestrator.py), [`test_coordinator.py`](../../../services/core-control-plane/tests/core/workflow/test_coordinator.py) | Shadow cannot mutate, and enforce proposals re-enter typed ingress with attempt-scoped identity. |
| Durable journal, projection, and approval | implemented | [`test_projection.py`](../../../services/core-control-plane/tests/core/workflow/test_projection.py), [`test_workflow_approval.py`](../../../services/core-control-plane/tests/delivery/persistence/test_workflow_approval.py) | Revisioned Process state, retryable projection, quorum, timeout, and no-self-approval have focused coverage. |
| Compensation and durable target hold | implemented | [`test_automation_hold.py`](../../../services/core-control-plane/tests/core/workflow/test_automation_hold.py), [`test_orchestrator.py`](../../../services/core-control-plane/tests/core/workflow/test_orchestrator.py), [`test_control_loop_authority.py`](../../../services/core-control-plane/tests/core/test_control_loop_authority.py), [`test_gate.py`](../../../services/core-control-plane/tests/core/risk_gate/test_gate.py) | Incomplete recovery creates a restart-safe, duplicate-safe hold that denies ordinary forward dispatch. Only matching verified recovery can release it. |
| Guard evaluation | implemented | [Guard evaluation](../../roadmap/decisioning/workflow-control-loop-integration.md#42-guard-evaluation-seam), [`test_guard_fail_closed.py`](../../../services/core-control-plane/tests/core/workflow/test_guard_fail_closed.py) | The runtime binds `ChangeWindowWorkflowGuardEvaluator` over the architecture-review gate. Missing, stale, malformed, and unavailable evidence all block the step and record a bounded `guard_error`. |
| Governed Python, schedule, command, and shell paths | in-progress | [Governed tasks and schedules](../../roadmap/decisioning/workflow-control-loop-integration.md#45-governed-python-tasks-and-cron-schedules) | Validation and bounded sandbox mechanics exist, but live executor and production scale-out evidence remain incomplete. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-08-14 | in-progress | Adopted the implementation ledger without reconstructing earlier provenance. | `current change`; current source and focused tests listed in the scope table. | Complete policy binding and production concurrency evidence. |
| 2026-08-14 | implemented | Recorded the validated FDAI-CONST-009 control-loop boundary: incomplete compensation issues a durable hold, ordinary dispatch is denied, and matching recovery remains Human approval-gated until verified release. | `228f0779e`; focused hold, compensation, control-loop, and risk-gate checks passed 10 tests; centralized validation passed. | Complete the unrelated guard binding, distributed dispatch evidence, and governed task work below. |
| 2026-08-14 | implemented | Made bound guard evaluation fail closed: a stale evaluation clock, a raising or unavailable evaluator, and a non-boolean result each block the step and record a bounded `guard_error` in the `workflow.step` audit row. | `current change`; `workflow_step_executor.py` and `test_guard_fail_closed.py`; focused workflow checks passed 101 cases; task-scoped Ruff and strict mypy passed. | Complete the multi-replica dispatch evidence and governed Python-task executor work below. |

### Remaining work

- [x] The concrete `ChangeWindowWorkflowGuardEvaluator` binding is tested end to end, and missing,
  stale, malformed, and unavailable evidence each block the step fail-closed.
- [ ] Retain multi-replica locking and duplicate-delivery evidence proving one forward dispatch per
  Process step and attempt.
- [ ] Complete the governed Python-task live executor and retain sandbox, outcome, and recovery
  receipts without granting the Operator API executor identity.
