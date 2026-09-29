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
| Governance dispatchers | implemented | [`promotion.py`](../../../services/core-control-plane/src/fdai/delivery/promotion.py), [`gitops_pr/governance.py`](../../../services/core-control-plane/src/fdai/delivery/gitops_pr/governance.py), [`retirement.py`](../../../services/core-control-plane/src/fdai/rule_catalog/schema/retirement.py), and focused governance delivery tests | Promotion requires an authenticated exact distinct-approver attestation. Bare or forged review decisions are rejected. Retire and exemption documents use canonical paths and formats, reconcile PR terminal states, and project merged retirements into the active rule index. |
| Selected live probes | implemented | [`test_action_type_catalog.py`](../../../services/core-control-plane/tests/rule_catalog/test_action_type_catalog.py) | Referenced probes are loader-validated; actions without one retain their static blast bound. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-08-13 | in-progress | Adopted the implementation ledger without reconstructing earlier provenance. | Current source, tests, and consumer-status section listed in the scope table. | Complete the observable governance-dispatch exit condition below. |
| 2026-08-15 | in-progress | Added pure PR-native document writers for `governance.retire-rule` and `governance.grant-exemption`. | `current change`; `services/core-control-plane/src/fdai/delivery/gitops_pr/governance_writers.py`; `pytest services/core-control-plane/tests/delivery/test_governance_writers.py` (16 passed). | The `promote-action-type` dispatcher and the governed pull-request binding remain open. |
| 2026-08-27 | implemented | Bound the two pure writers to a write-once PR publisher with durable open-to-merge lifecycle evidence and added a promotion dispatcher that refuses missing or insufficient distinct-approver review. | `current change`; `gitops_pr/governance.py`, `promotion.py`, and focused governance delivery tests passed. | GitHub review and merge remain deployment-controlled; no local receipt claims a merged change. |
| 2026-08-27 | implemented | Bound exact review attestations, canonical governance paths, JSON exemption artifacts, concurrent retry reconciliation, and merged or closed PR lifecycle replay; added the retirement loader and projection. | `current change`; focused governance, GitOps, and governance-catalog tests passed. | Deployment-owned identity and merged catalog evidence remain external gates. |
| 2026-08-27 | implemented | Closed review findings by rejecting bare authority decisions, enforcing exact governance filenames and extensions, serializing and reconciling retries, requiring benchmark cohorts in O7 batches, rejecting non-finite probe deadlines, and aligning exemption output with the JSON loader. | `current change`; focused adversarial governance, GitOps, O7, probe, and catalog tests passed. | Retain deployment-owned authenticated review and terminal PR receipts. |
| 2026-08-27 | implemented | Bound the complete direct-request fingerprint and a durable one-time promotion nonce to the actual HIL/direct route. Retired rules are removed from quality and HIL rule maps, and PR lookup reuses merged or closed records. | `current change`; focused HIL, replay, concurrency, and runtime dispatch tests passed. | Deployment-owned attestation issuance and live PR receipts remain external. |
| 2026-08-27 | implemented | Rejected serialized parked-rule fallback during HIL resume, applied retirement projections before frozen measurement indexing, and percent-encoded every GitOps repository path segment and query value. | `current change`; focused HIL, scenario-replay, and GitOps adversarial tests passed. | Deployment-owned runtime and remote receipts remain external. |

### Remaining work

- [x] PR-native writers exist for `governance.retire-rule` and `governance.grant-exemption`,
  and `services/core-control-plane/tests/delivery/test_governance_writers.py` proves each rendered
  document is unapplied, requires a distinct approver, and refuses a subscription-wide exemption.
- [x] The `governance.promote-action-type` dispatcher rejects missing or insufficient
  distinct-approver review before delegating to the exact-receipt direct API writer.
- [x] Both PR-native writers are bound to the governed pull-request adapter, with durable
  replayable lifecycle evidence; merge and catalog activation remain human-controlled.
