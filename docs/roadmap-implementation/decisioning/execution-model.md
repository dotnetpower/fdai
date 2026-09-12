# Execution Model implementation ledger

This delivery ledger preserves reviewable implementation scope, append-only transitions,
and resumable work while the roadmap owner remains focused on normative design.

## Implementation status

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| Risk table and never-raising authority ceiling | implemented | [`test_authority.py`](../../../services/core-control-plane/tests/core/risk_gate/test_authority.py), [`test_ceiling.py`](../../../services/core-control-plane/tests/core/risk_gate/test_ceiling.py) | The baseline, six contextual axes, degradation, and kill switch combine without raising authority. |
| Promotion, HIL resume, and executor selection | implemented | [`test_gate.py`](../../../services/core-control-plane/tests/core/risk_gate/test_gate.py), [`test_coordinator.py`](../../../services/core-control-plane/tests/core/hil_resume/test_coordinator.py) | Shadow-first promotion, approval resume, and typed path selection have focused coverage. |
| Seven safeguards across every execution path | implemented | [`safeguard_lifecycle_coordinator.py`](../../../services/core-control-plane/src/fdai/core/executor/safeguard_lifecycle_coordinator.py), [`test_safeguard_lifecycle_coordinator.py`](../../../services/core-control-plane/tests/core/executor/test_safeguard_lifecycle_coordinator.py), [`test_safeguard_evidence_lifecycle.py`](../../../services/core-control-plane/tests/core/executor/test_safeguard_evidence_lifecycle.py), [Seven safeguards](../../roadmap/decisioning/execution-model.md#6-seven-safeguards-and-one-replay-extension) | PR-native, PR-manual, direct-API, and tool-call paths share one lifecycle that retains one evidenced target lock through dispatch, persists no-authority evidence, and quarantines uncertain outcomes. Governed cross-path runtime evidence remains separate from implementation completion. |
| Live blast-probe Azure runtime binding | implemented | [`blast_probe.py`](../../../services/core-control-plane/src/fdai/delivery/azure/blast_probe.py), [`wire_azure_observability.py`](../../../services/core-control-plane/src/fdai/composition/wire_azure_observability.py), [`test_control_loop_authority.py`](../../../services/core-control-plane/tests/core/test_control_loop_authority.py) | Azure composition compiles reviewed probe manifests, measures the target before authority evaluation, and records the exact bounded reading. No governed production shadow receipt is cited here. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-08-14 | in-progress | Adopted the implementation ledger without reconstructing earlier provenance and separated tested mechanics from deployment evidence. | `current change`; current source, focused tests, and constitutional traceability listed in the scope table. | Close shared-safeguard and live-probe evidence gaps. |
| 2026-08-29 | implemented | Bound the Azure Monitor live blast probe through Azure composition and the control loop. Missing, timed-out, failed, active, or overloaded evidence can only lower authority, and the audit row retains the measured decision and scalar metrics for replay. | `current change`; Azure blast adapter and control-loop authority tests `30 passed`, task-scoped Ruff passed, and strict mypy passed for the standalone adapter. | Retain a governed no-mutation shadow receipt before raising this area to `validated`. |
| 2026-09-12 | implemented | Reconciled the merged shared safeguard lifecycle, ordered every transition after authoritative store time, moved the combined hold and lock-ownership check to the immediate provider boundary, preserved no-dispatch versus attempted-dispatch and terminal replay outcomes, and recovered ambiguous writes by exact readback or idempotent retry. The isolated Executor now reacquires the shared logical-target lock, rechecks durable hold and workflow-authorization state immediately before provider I/O, and serializes hold issuance on that lock. Safeguard-bound command identity includes the complete Action, path, bundle, source revision, attempt, issue time, and deadline; expired historical deliveries attempt non-mutating provider recovery before bundle-freshness refusal; and a durable pre-cutover shadow receipt remains replayable without redispatch. | PR #796; `safeguard_evidence_lifecycle.py`; `safeguard_hold_fenced_port.py`; `automation_hold.py`; path dispatch adapters; `safeguard_lifecycle_{coordinator,closure,denial}.py`; Core/isolated-Executor client, hold-fence, consumer, and persistence tests; focused lifecycle, compatibility, and wiring checks in the current change. | Retain governed cross-path safeguard and independent-effect receipts under #633 before claiming operational validation or promoting v1.1 as the default producer contract. |
| 2026-09-13 | implemented | Corrected restart recovery under an advancing clock: a durable no-dispatch transition that postdates its candidate acquisition requires orderly release and at most one fresh sequential acquisition. Reopening preserves causal-time checks; missing release evidence, release failure, cancellation, or a still-stale second acquisition stops without dispatch. | `current change`; `safeguard_lifecycle_preparation.py`; `safeguard_lifecycle_coordinator.py`; 25 preparation tests including advancing-clock, foreign-fence, retry-bound, and release-failure cases; strict mypy and Ruff. | Retain the separately governed cross-path runtime evidence under #633. |
| 2026-09-13 | implemented | Preserved full-Action fingerprint binding and corrected frozen cross-objective replay to use the event-anchored clock. Refreshed only derived case, receipt, and aggregate digest pins for the reviewed scenarios and their versioned mirrors. A clean upstream comparison passed while the prior task snapshot failed, disproving the earlier assumption that the 18 digest failures were unrelated. Semantic outcome and authority assertions remain unchanged. | `current change`; 122 July/September replay tests and 4 October corpus checks passed; safety-core coverage passed with 8,539 tests, one optional TypeScript-tool skip, and 90.94% branch coverage. | Governed operational evidence remains under #633; synthetic replay grants no execution or promotion authority. |

### Remaining work

- [x] Represent the seven safeguards and independent effect closure in one shared contract across
  PR-native, direct API, PR-manual, and tool-call execution, then retain path-parity tests.
- [x] Bind `AzureMonitorBlastProbe` through Azure composition and prove quiet, active, overloaded,
  unavailable, and failed outcomes in focused tests.
- [ ] Retain a governed shadow receipt where live evidence lowers authority with
  `winning_axis=live_blast` and no mutation.
- [ ] Retain governed end-to-end receipts for each executor path on one pinned ActionType and risk
  catalog revision before claiming operational validation.
