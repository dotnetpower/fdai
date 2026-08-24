# Preflight Active Plan Reassembly (policy blocker to re-rendered terraform) implementation ledger

This delivery ledger preserves reviewable implementation scope, append-only transitions,
and resumable work while the roadmap owner remains focused on normative design.

## Implementation status

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| Bounded convergence and fail-closed stop conditions | implemented | `services/core-control-plane/src/fdai/core/deploy_preflight/reassemble.py` and focused reassembly tests | Manual blockers, repeated toggles, regressions, iteration caps, and raised reanalysis all stop without applying a partial result. |
| One proposal per applied toggle | implemented | `services/core-control-plane/src/fdai/core/deploy_preflight/reassembly_proposals.py` and `test_reassembly_proposals.py` | Cleared outcomes produce deterministic, idempotent proposal envelopes; escalated outcomes submit none. |
| ActionType, data-only toggle modules, and reference consumer | implemented | `rule-catalog/action-types/remediate.apply-preflight-toggle.yaml` and `infra/modules/preflight-toggles/` | These artifacts define the governed action and one reference Terraform consumption pattern. |
| Recurring manual-blocker learning primitive | implemented | `services/core-control-plane/src/fdai/agents/_framework/norns_deployment_learning.py` and `services/core-control-plane/tests/agents/test_norns_preflight.py` | Norns emits an inert candidate from caller-supplied observations; it does not create or promote a toggle. |
| Live trigger, plan renderer, pipeline binding, PR, and audit | not-started | The composition boundary in this document | No production composition invokes the loop and binds its `ProposalSink` to Huginn and the PR/audit path. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-08-14 | in-progress | Adopted the implementation ledger; earlier provenance was not reconstructed. Kept pure reassembly mechanics separate from the uncomposed delivery path. | current change; focused reassembly, proposal, and Norns tests listed in the scope table | Compose a live shadow path and retain PR plus audit evidence. |

### Remaining work

- [ ] Bind live policy findings to a caller-owned plan renderer and prove the same analyzer re-verifies every generated override.
- [ ] Bind `ProposalSink` through Huginn to the governed pipeline and pass an integration test proving blocked or escalated outcomes open no PR.
- [ ] Publish one shadow tfvars-override PR per toggle and retain its append-only audit intent, terminal outcome, and tested `pr_revert` rollback evidence.
