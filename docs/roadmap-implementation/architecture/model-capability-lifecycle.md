# Model Capability Lifecycle implementation ledger

This delivery ledger tracks endpoint binding, model capability resolution, provisioning, bounded
recovery, and lifecycle reconciliation. Historical transitions recorded before this owner split
remain append-only in the LLM Strategy implementation ledger.

## Implementation status

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| Capability registry, endpoint binding, and provisioning assessment | implemented | `rule-catalog/llm-registry.yaml`; `rule_catalog/schema/llm_resolver.py`; `provisioning_assessment.py`; focused resolver tests | Capability mappings, explicit capacity units, endpoint provenance, mixed-publisher invariants, and fail-closed readiness are executable. |
| Escalation policy and same-publisher primary latency routing | implemented | `core/quality_gate/escalation_ladder.py`; `delivery/azure/llm/latency_routed_cross_check.py`; `composition/wire_llm.py`; focused routing tests | The ladder remains never-authoritative, and primary-pool latency selection cannot replace the independent secondary publisher. |
| T2 proposer failover, durable recovery evidence, and governed route selection | implemented | `core/tiers/t2_reasoning/recovery.py`; `runtime/t2_{recovery,route_registry}.py`; `ops.switch-t2-proposer-route`; focused runtime and pantheon-chain tests | Attempts reserve budget and persist sanitized evidence. Terminal exhaustion reaches human approval before a route change, and rollback is correlation-fenced. |
| Model lifecycle expiry review mechanics | implemented | `model_lifecycle_startup.py`; `model_lifecycle_review.py`; `resolved_models.py`; lifecycle proposal schema v3; focused lifecycle, Core binding, Operator binding, and Key Vault source tests | One async owner loads an immutable revision, verifies trusted PR proposal and decision digests, persists decisions, and exposes authority-free pre-binding holds. Core and Operator reject a supplied deployment digest mismatch before binding. |
| Weekly model reconciler and reviewed replacement flow | in-progress | `.github/workflows/model-lifecycle-reconcile.yml`; `scripts/deployment/azure/model_lifecycle_reconciler.py`; focused lifecycle and protected-workflow tests | The scheduled contract is sanitized, bounded, idempotent, and draft-only. A governed scheduled-run receipt remains open. |
| Governed operational lifecycle evidence | in-progress | Runtime recovery receipts, lifecycle proposals, and model measurements cited above | Mechanics exist; one exact-revision campaign covering expiry, recovery, route change, and rollback is not retained. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-08-24 | in-progress | Split model capability lifecycle ownership from LLM Strategy without reconstructing or moving earlier append-only history. | `current change`; this owner, the LLM Strategy ledger, registry, resolver, recovery, and reconciler paths above. | Complete the observable lifecycle and recovery exits below. |
| 2026-09-05 | implemented | Bound one async resolved-model startup revision to trusted PR lifecycle review and capability eligibility, added Core and Operator revision fences, and persisted digest-verified authority-free decisions before binding. | `current change`; focused lifecycle, configuration, Core composition, Operator narrator, and scheduled reconciler checks. | Retain the governed recovery campaign and one protected scheduled reconciler receipt. |

### Remaining work

- [ ] Retain a governed T2 recovery campaign proving bounded attempt budgets, durable receipt forwarding after restart, terminal exhaustion to human approval, an audited route switch, correlation-fenced rollback, and recovery without a new approval.
- [x] Bind the implemented expired-unmerged evaluator and direct Key Vault source adapter through an asynchronous startup owner. Add trusted pull-request lifecycle observation, proposal and decision digest verification, persistence, and pre-binding capability holds.
- [ ] Retain one protected scheduled reconciler run showing that deprecation, family drift, SKU drift, or capacity drift creates only a sanitized proposal and never changes the live mapping without review.
