# Action Ontology Lifecycle implementation ledger

This delivery ledger preserves reviewable implementation scope, append-only transitions,
and resumable work while the roadmap owner remains focused on normative design.

## Implementation status

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| Catalog lifecycle and inert defaults | implemented | [`test_action_type_catalog.py`](../../../services/core-control-plane/tests/rule_catalog/test_action_type_catalog.py) | Shipped declarations validate lifecycle constraints and default to shadow. |
| Rule-violation remediation consumer | implemented | [`test_unified_control_loop.py`](../../../services/core-control-plane/tests/pipeline/test_unified_control_loop.py) | The typed control loop routes remediation through ActionBuilder, RiskGate, and Executor. |
| Operator-request proposal consumer | implemented | [`bragi.py`](../../../services/core-control-plane/src/fdai/agents/bragi.py), [`test_chat_to_pipeline_e2e.py`](../../../services/core-control-plane/tests/agents/test_chat_to_pipeline_e2e.py) | Bragi publishes a typed proposal to canonical ingress and never calls an executor directly. |
| Governance dispatchers | in-progress | [`override_writer.py`](../../../services/core-control-plane/src/fdai/core/risk_gate/override_writer.py), [`governance_writers.py`](../../../services/core-control-plane/src/fdai/delivery/gitops_pr/governance_writers.py), [`test_governance_writers.py`](../../../services/core-control-plane/tests/delivery/test_governance_writers.py) | The override writer is live. `retire-rule` and `grant-exemption` now have pure PR-native document writers that render nothing applied and reject self-approval, unbounded input, and subscription-wide exemptions. `promote-action-type` declares `execution_path: direct_api`, so its dispatcher is a separate design decision, and it stays inert. |
| Selected live probes | implemented | [`test_action_type_catalog.py`](../../../services/core-control-plane/tests/rule_catalog/test_action_type_catalog.py) | Referenced probes are loader-validated; actions without one retain their static blast bound. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-08-13 | in-progress | Adopted the implementation ledger without reconstructing earlier provenance. | Current source, tests, and consumer-status section listed in the scope table. | Complete the observable governance-dispatch exit condition below. |
| 2026-08-15 | in-progress | Added pure PR-native document writers for `governance.retire-rule` and `governance.grant-exemption`. | `current change`; `services/core-control-plane/src/fdai/delivery/gitops_pr/governance_writers.py`; `pytest services/core-control-plane/tests/delivery/test_governance_writers.py` (16 passed). | The `promote-action-type` dispatcher and the governed pull-request binding remain open. |

### Remaining work

- [x] PR-native writers exist for `governance.retire-rule` and `governance.grant-exemption`,
  and `services/core-control-plane/tests/delivery/test_governance_writers.py` proves each rendered
  document is unapplied, requires a distinct approver, and refuses a subscription-wide exemption.
- [ ] Decide and implement the `governance.promote-action-type` dispatcher for its declared
  `direct_api` execution path, then retain focused evidence that it stays inert without an
  approved, distinct-approver transition.
- [ ] Bind both PR-native writers to the governed pull-request adapter and retain one replayable
  open-to-merge receipt.
