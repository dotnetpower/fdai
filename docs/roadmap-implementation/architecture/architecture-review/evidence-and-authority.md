# ARB Evidence and Authority implementation ledger

This ledger tracks production evidence attestation and decision authority separately from the
structural manifest checker.

## Implementation status

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| Manifest structure validation | implemented | `core/architecture_review/readiness.py`; `scripts/governance/check-arb-readiness.py`; focused tests | Required fields, key sets, digest shape, timestamps, expiry, and missing bindings are checked. |
| External evidence body and digest verification | implemented | [Owner design](../../../roadmap/architecture/architecture-review/evidence-and-authority.md#evidence-bindings); `core/architecture_review/readiness.py`; focused readiness and CLI contract tests | The injected provider boundary retrieves a bounded body and authenticated attestation. Runtime readiness verifies URI, digest, scope, revision, observation freshness, approver authorization, and non-synthetic status. No production provider is bound upstream. |
| Risk and exception contract | in-progress | `core/architecture_review/readiness.py`; `tests/core/architecture_review/test_readiness.py`; `config/architecture-review.yaml`; owner design | Accepted critical and high blockers require a typed risk or exception record, a registered owner slot, and a current review or effective interval. Provider-backed evidence attestation is enforced; live compensating-control status remains open. |
| Immutable decision receipt | implemented | `core/architecture_review/decision_receipt.py`; `core/architecture_review/projection.py`; `Decision` and `Approval` ObjectType `1.1.0`; focused receipt, projection, and catalog tests | The content-addressed receipt binds exact case, change, impact, target, context, evidence, graph, catalog, conditions, authority, approval, audit, and effective-time identity while carrying `execution_authority=false`. Projection rejects mismatched evidence or unrecorded and identity-mismatched approvals before writing. Receipt-derived production readiness remains open. |
| Production owner and evidence bindings | in-progress | `config/architecture-review.yaml` | Upstream intentionally leaves fork-owned bindings empty and production blocked. |
| Five-pillar machine-checkable definition coverage | implemented | `core/architecture_review/pillar_coverage.py`; `tests/core/architecture_review/test_pillar_coverage.py`; generated WAF assessment catalog; focused pytest | All five pillars have exact unique definition accounting for 59 controls and 186 evidence requirements, including Security, Cost Optimization, and Performance Efficiency. This does not establish workload satisfaction, compliance, production readiness, or authority. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-08-29 | in-progress | Hardened the manifest checker so accepted critical and high blockers need a complete current risk or exception contract before ARB can treat them as accepted. | `current change`; `services/core-control-plane/src/fdai/core/architecture_review/readiness.py`, `services/core-control-plane/tests/core/architecture_review/test_readiness.py`; `./.venv/bin/pytest -q --no-cov services/core-control-plane/tests/core/architecture_review/test_readiness.py services/core-control-plane/tests/core/architecture_review/test_projection.py tests/integration/scripts/test_check_arb_readiness.py` | Add provider-backed evidence attestation, immutable decision receipts, and machine-checkable pillar coverage. |
| 2026-08-29 | implemented | Added an injected production evidence provider contract, fork-safe `Container` binding, and fail-closed attestation evaluation. Metadata-only readiness cannot pass; exact body digest, URI, scope, revision, freshness, approver authorization, observation order, and non-synthetic status must match. | `current change`; `services/core-control-plane/src/fdai/core/architecture_review/readiness.py`; composition and workflow wiring; focused readiness, projection, workflow, and CLI contract tests (`31 passed`); targeted Ruff and strict mypy checks. | Bind a governed provider in a deployment, validate live compensating controls, and implement immutable decision receipts. |
| 2026-08-29 | implemented | Added the content-addressed ARB decision receipt and versioned `Decision` and `Approval` to bind exact evidence and independently recorded approval identity. Tampering changes identity or fails digest validation; missing, unapproved, or mismatched approval objects fail before projection. | `current change`; `core/architecture_review/decision_receipt.py`; `core/architecture_review/projection.py`; versioned ontology declarations; focused receipt, readiness, projection, workflow, catalog, provenance, and CLI tests (`64 passed`); regenerated and revalidated the promoted Korean semantic surface receipt after the ontology release digest changed; targeted Ruff and strict mypy checks. | Derive production readiness and ReviewCase status from the immutable receipt instead of mutable manifest status. |
| 2026-08-24 | in-progress | Split evidence and authority into a focused owner and distinguished syntax validation from production attestation. | `current change`; owner document, paired translation, current checker, and focused documentation checks. | Add provider-backed attestation, complete risk records, and receipt-derived readiness. |
| 2026-09-26 | implemented | Added read-only five-pillar WAF definition accounting against pinned framework, BestPractice, and generated assessment catalogs; missing, duplicate, ambiguous, and stale identities fail closed. | `current change`; `services/core-control-plane/src/fdai/core/architecture_review/pillar_coverage.py`; `services/core-control-plane/tests/core/architecture_review/test_pillar_coverage.py`; `uv run --no-sync pytest -q --no-cov services/core-control-plane/tests/core/architecture_review/test_pillar_coverage.py services/core-control-plane/tests/rule_catalog/test_framework_assessment_catalog.py` (12 passed); targeted Ruff and strict mypy. | Workload-specific evidence and approval, production provider bindings, and receipt-derived readiness remain outside definition coverage. |

### Remaining work

- [x] Add an injected evidence provider that verifies URI, bounded body digest, scope, revision,
  freshness, approver authorization, observation order, and non-synthetic status for every
  production binding (`31 passed` focused checks).
- [x] Reject accepted critical or high blockers without a complete, current risk or exception
  record and a registered accountable owner. Evidence: `services/core-control-plane/src/fdai/core/architecture_review/readiness.py`;
  `services/core-control-plane/tests/core/architecture_review/test_readiness.py`.
- [x] Version `Decision` and `Approval` to bind the exact case, evidence set, conditions, authority
  basis, independently recorded approver identities, and approval receipt identities.
- [ ] Derive production readiness from the immutable decision receipt and prove that manifest or
  workflow-context edits cannot create authority.
- [x] Add machine-checkable Security, Cost Optimization, and Performance Efficiency control
  definition coverage with focused catalog tests. Evidence:
  `services/core-control-plane/src/fdai/core/architecture_review/pillar_coverage.py`;
  `services/core-control-plane/tests/core/architecture_review/test_pillar_coverage.py` and
  `services/core-control-plane/tests/rule_catalog/test_framework_assessment_catalog.py`
  (`12 passed` focused tests).
