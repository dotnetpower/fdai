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
| Live trigger, plan renderer, pipeline binding, PR, and audit | in-progress | `services/core-control-plane/src/fdai/core/deploy_preflight/pre_publication_gate.py` and `services/core-control-plane/tests/core/deploy_preflight/test_pre_publication_gate.py` | The gated seam binds Huginn ingest and Forseti judgment in a focused integration test. No production composition binds a live trigger, plan renderer, PR, or audit path. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-08-14 | in-progress | Adopted the implementation ledger; earlier provenance was not reconstructed. Kept pure reassembly mechanics separate from the uncomposed delivery path. | current change; focused reassembly, proposal, and Norns tests listed in the scope table | Compose a live shadow path and retain PR plus audit evidence. |
| 2026-09-26 | in-progress | Gated the proposal seam: proposals reach Huginn only after the analyzer re-verifies the accumulated overrides, and the ingress event type `preflight_toggle_blocker` lets Forseti bind the toggle ActionType without trusting a payload-supplied ActionType. | `current change`; `services/core-control-plane/src/fdai/core/deploy_preflight/pre_publication_gate.py`; `uv run pytest tests/core/deploy_preflight -q` passed 98 tests. | Compose the gated seam at the runtime composition root with a live policy-finding trigger, PR publication, and audit evidence. |
| 2026-09-26 | in-progress | Recorded the remaining argument-carrying boundary: ingress drops `params` for this non-operator signal, so the composed live path still owes a governed way to hand the per-toggle arguments to the executor. | `current change`; `services/core-control-plane/src/fdai/core/deploy_preflight/reassembly_proposals.py` | Compose the gated seam with a live trigger and carry the per-toggle arguments through a governed path. |
| 2026-09-26 | in-progress | Confirmed in review that no consumer still reads the former `rule_violation` ingress envelope for this seam and that the documented anchors resolve. | `current change`; `bash scripts/quality/repository/check-doc-links.sh` reported 0 broken links. | Unchanged: compose the gated seam with a live trigger and carry the per-toggle arguments through a governed path. |
| 2026-10-01 | in-progress | Removed the stale open copy of the `ProposalSink` binding item that the inline-status migration copied from the owner; the ledger already records that binding as complete. | `current change`; this ledger's 2026-09-26 rows | Unchanged: compose the gated seam with a live trigger and carry the per-toggle arguments through a governed path. |

### Remaining work

- [ ] Bind live policy findings to a caller-owned plan renderer and prove the same analyzer re-verifies every generated override.
- [x] Bind the `ProposalSink` seam to Huginn ingest behind the pre-publication gate. The focused
  integration test in `tests/core/deploy_preflight/test_pre_publication_gate.py` proves that a
  blocked, escalated, stale, or scope-changed pass publishes no pipeline event and opens no PR,
  and that a cleared pass is judged as `remediate.apply-preflight-toggle` and held for a human.
- [ ] Compose that gated seam at the runtime composition root with a live policy-finding trigger, and retain the composed run evidence. Ingress drops `params` for a non-operator signal, so that work MUST also carry the per-toggle arguments to the executor through a governed path.
- [ ] Publish one shadow tfvars-override PR per toggle and retain its append-only audit intent, terminal outcome, and tested `pr_revert` rollback evidence.
