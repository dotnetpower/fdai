# Risk Classification (automatic execution vs human approval vs denial) implementation ledger

This delivery ledger preserves reviewable implementation scope, append-only transitions,
and resumable work while the roadmap owner remains focused on normative design.

## Implementation status

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| Table loading, ordering, and first-match evaluation | implemented | [`risk_table.py`](../../../services/core-control-plane/src/fdai/core/risk_gate/risk_table.py), [`test_risk_table.py`](../../../services/core-control-plane/tests/core/risk_gate/test_risk_table.py) | The loader validates the catalog and applies the ordered fail-closed decision table in focused tests. |
| Feature extraction and environment classification | implemented | [`feature.py`](../../../services/core-control-plane/src/fdai/core/risk_gate/feature.py), [`test_control_loop_authority.py`](../../../services/core-control-plane/tests/core/test_control_loop_authority.py) | Typed features are extracted, and missing or unknown environment tags resolve to production risk. |
| Unified authority decision and never-raising ceiling | implemented | [`authority.py`](../../../services/core-control-plane/src/fdai/core/risk_gate/authority.py), [`test_authority.py`](../../../services/core-control-plane/tests/core/risk_gate/test_authority.py) | The table baseline and contextual ceilings combine without raising authority. |
| Existing control-loop audit projection | implemented | [`_helpers.py`](../../../services/core-control-plane/src/fdai/core/control_loop/_helpers.py), [`test_control_loop_authority.py`](../../../services/core-control-plane/tests/core/test_control_loop_authority.py) | Audit data includes the matched rule, final decision, quorum, and resolved ceiling. |
| Approval and change-governance enforcement | in-progress | [`check-risk-table-change.py`](../../../scripts/quality/architecture/check-risk-table-change.py), [`test_check_risk_table_change.py`](../../../tests/integration/scripts/test_check_risk_table_change.py), [Change Process](../../roadmap/decisioning/risk-classification.md#change-process), [CODEOWNERS](../../../.github/CODEOWNERS) | A commit gate now enforces the metadata half of the contract - a strictly increasing version, unchanged Owner-tier ownership, a written justification on every rule, and a fail-close default that stays last - and classifies the change direction so a loosening edit cannot hide behind a patch bump. The two-person quorum and Owner-tier review half is branch protection on the deployment's fork and stays unproven from a local checkout. |
| Replay-complete feature and catalog metadata | implemented | [`authority.py`](../../../services/core-control-plane/src/fdai/core/risk_gate/authority.py), [`test_authority.py`](../../../services/core-control-plane/tests/core/risk_gate/test_authority.py) | The authority audit payload serializes the exact feature vector and the risk-table catalog version, and focused checks replay a recorded payload against its own catalog version after the table changes. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-08-13 | in-progress | Adopted an evidence-bounded implementation ledger without reconstructing earlier delivery history. | `current change`; current source and focused checks listed in the scope table; risk-focused checks passed 113 cases and readiness coordinator checks passed 33 cases. | Prove governance enforcement, add replay-complete metadata, and retain governed runtime evidence. |
| 2026-08-14 | implemented | Serialized the exact feature vector and the risk-table catalog version into the authority audit payload so a historical decision replays against the revision that classified it. | `current change`; [`authority.py`](../../../services/core-control-plane/src/fdai/core/risk_gate/authority.py), [`test_authority.py`](../../../services/core-control-plane/tests/core/risk_gate/test_authority.py); focused authority, evaluator, and control-loop authority checks passed 43 cases. | Prove governance enforcement and retain governed runtime receipts. |
| 2026-08-14 | implemented | Added the remaining ceiling inputs - role, graph count, live-probe reading, and the two fail-safe flags - to the same audit payload so a replay reconstructs the six-axis ceiling without re-querying a probe or re-reading control-plane health. | `current change`; [`authority.py`](../../../services/core-control-plane/src/fdai/core/risk_gate/authority.py), [`test_authority.py`](../../../services/core-control-plane/tests/core/risk_gate/test_authority.py); focused risk-gate, runbook, workflow, skills, and control-loop authority checks passed 438 cases. | Prove governance enforcement and retain governed runtime receipts. |
| 2026-08-14 | in-progress | Enforced the metadata half of the change contract with a commit gate and made loosening edits legible in the version string. | `current change`; [`check-risk-table-change.py`](../../../scripts/quality/architecture/check-risk-table-change.py), [`test_check_risk_table_change.py`](../../../tests/integration/scripts/test_check_risk_table_change.py); focused gate checks passed 26 cases, and the gate was exercised against the shipped table for the unchanged, loosening-without-bump, loosening-patch-bump, and loosening-minor-bump cases. | Approval quorum and Owner-tier review stay branch protection on the deployment's fork; retain governed runtime receipts. |

### Remaining work

- [x] A commit gate enforces the metadata contract on every risk-table change - increasing
  version, unchanged owner group, a written justification per rule, a single fail-close default
  that stays last - and refuses a loosening change that only bumps the patch version.
- [ ] Prove the two-person approval quorum and the Owner-tier review for loosening changes. That
  evidence lives in the deployment's branch protection, not in this repository.
- [x] The authority audit payload serializes the exact feature vector and the catalog version, and a focused check replays a recorded payload against its own version after a tightening table change.
- [ ] Retain governed runtime receipts for risk decisions on one pinned revision before promoting any scope row to `validated`.
