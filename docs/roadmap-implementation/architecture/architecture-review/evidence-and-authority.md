# ARB Evidence and Authority implementation ledger

This ledger tracks production evidence attestation and decision authority separately from the
structural manifest checker.

## Implementation status

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| Manifest structure validation | implemented | `core/architecture_review/readiness.py`; `scripts/governance/check-arb-readiness.py`; focused tests | Required fields, key sets, digest shape, timestamps, expiry, and missing bindings are checked. |
| External evidence body and digest verification | not-started | [Owner design](../../../roadmap/architecture/architecture-review/evidence-and-authority.md#evidence-bindings) | The current checker validates metadata syntax but does not retrieve or attest the evidence body. |
| Risk and exception contract | in-progress | `core/architecture_review/readiness.py`; `tests/core/architecture_review/test_readiness.py`; `config/architecture-review.yaml`; owner design | Accepted critical and high blockers now require a typed risk or exception record, a registered owner slot, and a current review or effective interval. Provider-backed evidence attestation and live compensating-control status remain open. |
| Immutable decision receipt | not-started | `core/architecture_review/projection.py`; generic Process events | Current `Decision` projection does not bind case, evidence, conditions, and approval receipt identities. |
| Production owner and evidence bindings | in-progress | `config/architecture-review.yaml` | Upstream intentionally leaves fork-owned bindings empty and production blocked. |
| Five-pillar machine-checkable coverage | in-progress | `rule-catalog/best-practices/`; WAF catalog tests | Reliability and Operational Excellence are cataloged; Security, Cost Optimization, and Performance Efficiency are not equivalent yet. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-08-29 | in-progress | Hardened the manifest checker so accepted critical and high blockers need a complete current risk or exception contract before ARB can treat them as accepted. | `current change`; `services/core-control-plane/src/fdai/core/architecture_review/readiness.py`, `services/core-control-plane/tests/core/architecture_review/test_readiness.py`; `./.venv/bin/pytest -q --no-cov services/core-control-plane/tests/core/architecture_review/test_readiness.py services/core-control-plane/tests/core/architecture_review/test_projection.py tests/integration/scripts/test_check_arb_readiness.py` | Add provider-backed evidence attestation, immutable decision receipts, and machine-checkable pillar coverage. |
| 2026-08-24 | in-progress | Split evidence and authority into a focused owner and distinguished syntax validation from production attestation. | `current change`; owner document, paired translation, current checker, and focused documentation checks. | Add provider-backed attestation, complete risk records, and receipt-derived readiness. |

### Remaining work

- [ ] Add an injected evidence provider that verifies body digest, scope, revision, freshness, and
  approver authorization for every production binding.
- [x] Reject accepted critical or high blockers without a complete, current risk or exception
  record and a registered accountable owner. Evidence: `services/core-control-plane/src/fdai/core/architecture_review/readiness.py`;
  `services/core-control-plane/tests/core/architecture_review/test_readiness.py`.
- [ ] Version `Decision` to bind the exact case, evidence set, conditions, authority basis, and
  approval receipt identities.
- [ ] Derive production readiness from the immutable decision receipt and prove that manifest or
  workflow-context edits cannot create authority.
- [ ] Add machine-checkable Security, Cost Optimization, and Performance Efficiency control
  coverage with focused catalog tests.
