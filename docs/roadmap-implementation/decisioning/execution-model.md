# Execution Model implementation ledger

This delivery ledger preserves reviewable implementation scope, append-only transitions,
and resumable work while the roadmap owner remains focused on normative design.

## Implementation status

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| Risk table and never-raising authority ceiling | implemented | [`test_authority.py`](../../../services/core-control-plane/tests/core/risk_gate/test_authority.py), [`test_ceiling.py`](../../../services/core-control-plane/tests/core/risk_gate/test_ceiling.py) | The baseline, six contextual axes, degradation, and kill switch combine without raising authority. |
| Promotion, HIL resume, and executor selection | implemented | [`test_gate.py`](../../../services/core-control-plane/tests/core/risk_gate/test_gate.py), [`test_coordinator.py`](../../../services/core-control-plane/tests/core/hil_resume/test_coordinator.py) | Shadow-first promotion, approval resume, and typed path selection have focused coverage. |
| Seven safeguards across every execution path | in-progress | [`constitution-traceability.json`](../../../config/constitution-traceability.json), [Seven safeguards](../../roadmap/decisioning/execution-model.md#6-seven-safeguards-and-one-replay-extension) | Individual mechanics exist, but one shared contract does not yet prove equivalent guarantees across every path. |
| Live blast-probe Azure runtime binding | implemented | [`blast_probe.py`](../../../services/core-control-plane/src/fdai/delivery/azure/blast_probe.py), [`wire_azure_observability.py`](../../../services/core-control-plane/src/fdai/composition/wire_azure_observability.py), [`test_control_loop_authority.py`](../../../services/core-control-plane/tests/core/test_control_loop_authority.py) | Azure composition compiles reviewed probe manifests, measures the target before authority evaluation, and records the exact bounded reading. No governed production shadow receipt is cited here. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-08-14 | in-progress | Adopted the implementation ledger without reconstructing earlier provenance and separated tested mechanics from deployment evidence. | `current change`; current source, focused tests, and constitutional traceability listed in the scope table. | Close shared-safeguard and live-probe evidence gaps. |
| 2026-08-29 | implemented | Bound the Azure Monitor live blast probe through Azure composition and the control loop. Missing, timed-out, failed, active, or overloaded evidence can only lower authority, and the audit row retains the measured decision and scalar metrics for replay. | `current change`; Azure blast adapter and control-loop authority tests `30 passed`, task-scoped Ruff passed, and strict mypy passed for the standalone adapter. | Retain a governed no-mutation shadow receipt before raising this area to `validated`. |

### Remaining work

- [ ] Represent the seven safeguards and independent effect closure in one shared contract across
  PR-native, direct API, PR-manual, and tool-call execution, then retain path-parity tests.
- [x] Bind `AzureMonitorBlastProbe` through Azure composition and prove quiet, active, overloaded,
  unavailable, and failed outcomes in focused tests.
- [ ] Retain a governed shadow receipt where live evidence lowers authority with
  `winning_axis=live_blast` and no mutation.
- [ ] Retain governed end-to-end receipts for each executor path on one pinned ActionType and risk
  catalog revision before claiming operational validation.
