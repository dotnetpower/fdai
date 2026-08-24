# Operational Readiness Review (dev-to-ops handoff gate) implementation ledger

This delivery ledger preserves reviewable implementation scope, append-only transitions,
and resumable work while the roadmap owner remains focused on normative design.

## Implementation status

### Migrated implementation notes

> **Implementation status**: The deterministic review and injected orchestration are implemented,
> but the upstream runtime doesn't invoke them automatically. See
> [Implementation status](operational-readiness.md#implementation-status) for the evidence and remaining integration work.

The repository implements the deterministic review and an injected application service. It doesn't
yet compose those pieces into the running control plane, so the current evidence supports
`implemented`, not an operationally `validated` handoff gate.

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| Ownership-transfer signal, report model, finding reduction, environment gate, and Best Practice checklist evaluation | implemented | [`core/readiness/`](../../../services/core-control-plane/src/fdai/core/readiness), [`test_coordinator.py`](../../../services/core-control-plane/tests/core/readiness/test_coordinator.py), and [`test_checklist.py`](../../../services/core-control-plane/tests/core/readiness/test_checklist.py) | The pure coordinator preserves grounded findings, fails safely on unknown severity, and separates the truthful decision from `blocks_handoff`. |
| Concurrent posture, preflight, and checklist orchestration with append-only audit and report delivery | implemented | [`composition/readiness.py`](../../../services/core-control-plane/src/fdai/composition/readiness.py), [`test_readiness_service.py`](../../../services/core-control-plane/tests/composition/test_readiness_service.py), and [`test_readiness_checklist_service.py`](../../../services/core-control-plane/tests/composition/test_readiness_checklist_service.py) | The service uses injected providers. Assessment and delivery failures are audited and propagated. |
| Architecture Review Board (ARB) artifact, owner, freshness, and expiry projection into checklist outcomes | implemented | [`composition/readiness_evidence.py`](../../../services/core-control-plane/src/fdai/composition/readiness_evidence.py) and [`test_readiness_evidence.py`](../../../services/core-control-plane/tests/composition/test_readiness_evidence.py) | Missing bindings remain `unknown`, and expired evidence becomes `failed`; neither is treated as a pass. |
| Automatic `ownership_transfer` ingest and production posture, checklist, and report-publisher bindings | not-started | Provider seams in [`shared/providers/readiness.py`](../../../services/core-control-plane/src/fdai/shared/providers/readiness.py) and the injected service above | The current runtime and bootstrap don't construct or register `OperationalReadinessService`; callers can only invoke it through their own composition. |
| Grounded shadow remediation proposal, distinct-approver boundary, and two-phase delivery audit | implemented | [`core/readiness/remediation.py`](../../../services/core-control-plane/src/fdai/core/readiness/remediation.py), [`composition/readiness.py`](../../../services/core-control-plane/src/fdai/composition/readiness.py), [`test_remediation.py`](../../../services/core-control-plane/tests/core/readiness/test_remediation.py), and [`test_readiness_remediation_service.py`](../../../services/core-control-plane/tests/composition/test_readiness_remediation_service.py) | Proposals stay shadow, cite a mapped lever or abstain, record approver identity, block self-approval, and never reach an executor. |
| `RemediationProposalPublisher` binding to the risk-gate and executor ingress | not-started | Provider seam in [`shared/providers/readiness.py`](../../../services/core-control-plane/src/fdai/shared/providers/readiness.py) | No composition root binds the seam, so no proposal reaches a live risk gate yet. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-08-13 | in-progress | Adopted the implementation ledger; earlier provenance wasn't reconstructed. Recorded the implemented deterministic and orchestration surfaces separately from the unbound runtime workflow. | Current change; `48 passed` from the five focused core and composition test files cited above. | Bind the event, providers, publisher, approval, and remediation path, then collect governed runtime evidence. |
| 2026-08-16 | in-progress | Added the deterministic remediation-proposal builder, the `RemediationProposalPublisher` seam, and the `propose_remediations` bridge that records approver identity, blocks self-approval, keeps proposals shadow, and two-phase audits delivery. | Current change; `86 passed` from `uv run pytest -q --no-cov services/core-control-plane/tests/core/readiness/ services/core-control-plane/tests/composition/test_readiness_remediation_service.py services/core-control-plane/tests/composition/test_readiness_service.py services/core-control-plane/tests/composition/test_readiness_checklist_service.py`. | Bind the proposal publisher to the risk-gate ingress, register `ownership_transfer` at event ingest, and collect a governed runtime receipt. |
| 2026-08-16 | in-progress | Hardened the remediation identity and the distinct-approver check: idempotency-key material is length-prefixed so a separator inside a field cannot collide two findings, and principals are compared after Unicode NFKC folding. | Current change; `88 passed` from `uv run pytest -q --no-cov services/core-control-plane/tests/core/readiness/ services/core-control-plane/tests/composition/test_readiness_remediation_service.py services/core-control-plane/tests/composition/test_readiness_service.py services/core-control-plane/tests/composition/test_readiness_checklist_service.py`. | Unchanged from the row above. |

### Remaining work

- [ ] Register and normalize `ownership_transfer` at event ingest, invoke the review through the
  accountable event-driven workflow, and add an integration test that proves replay-safe delivery.
- [ ] Bind production posture, checklist evidence, and report-publisher implementations at the
  composition root, then record a governed runtime receipt for one complete shadow review.
- [x] Emit grounded, shadow-only remediation proposals with a distinct-approver boundary, and add
  tests proving approver identity is recorded, self-approval is blocked, and the review service
  never executes a managed-resource change
  ([`test_remediation.py`](../../../services/core-control-plane/tests/core/readiness/test_remediation.py),
  [`test_readiness_remediation_service.py`](../../../services/core-control-plane/tests/composition/test_readiness_remediation_service.py)).
- [ ] Bind `RemediationProposalPublisher` to the risk-gate ingress at the composition root and
  record one governed receipt showing a proposal reaching the Var approval flow without the
  review service holding an executor identity.
- [ ] Keep enforcement disabled until frozen-scenario shadow evidence meets the configured
  false-positive threshold and the authoritative promotion registry records the transition.
