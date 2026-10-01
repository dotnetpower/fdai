# Deployment Preflight (feasibility and blocker collection) implementation ledger

This delivery ledger preserves reviewable implementation scope, append-only transitions,
and resumable work while the roadmap owner remains focused on normative design.

## Implementation status

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| Probe contracts, deterministic probes, analyzer, and report | implemented | `services/core-control-plane/src/fdai/core/deploy_preflight/`, `services/core-control-plane/src/fdai/shared/providers/feasibility_probe.py`, and focused deploy-preflight tests | Stable findings, fail-closed probe execution, verdicts, and shadow-versus-enforce behavior are tested. |
| Read-only Azure probes and protected-plan evidence | implemented | `scripts/deployment/azure/run_live_preflight.py`, `.github/workflows/deploy-dev.yml`, and `tests/integration/scripts/test_run_live_preflight.py` | The protected runner invokes the standalone script, requires all four live categories, sanitizes evidence, and binds its digest to the plan. |
| Terraform toggle, alternate-rendering fixture, and environment-profile primitives | implemented | `infra/modules/preflight-toggles/`; focused `terraform test -filter=tests/alternate_rendering.tftest.hcl`, `test_environment_profile.py`, and `test_reassembly_proposals.py` checks | The generic upstream root intentionally does not instantiate the fork-owned resource consumer. |
| Durable environment-profile refresh and Inventory-delta invalidation | implemented | `services/core-control-plane/src/fdai/delivery/deploy_preflight/environment_profile_refresh.py`, `delivery/inventory_delta.py`, `delivery/inventory_change_acceleration.py`, and focused `test_environment_profile_refresh.py` and `test_inventory_delta.py` | The recovery delta job invalidates the durable per-scope cache before advancing its cursor. Injected read-only builders can refresh under a bounded lease; tests prove restart, expiry, idempotency, and stale-write fencing. No live builder is bound, and a cached profile never grants deployment authority. |
| Check publishing and sanitized GitHub adapter | implemented | `services/core-control-plane/src/fdai/core/deploy_preflight/check_publish.py`, `services/core-control-plane/src/fdai/delivery/github/preflight_checks.py`, and focused tests | The adapter posts a bounded status on an existing PR head without exposing scope, findings, evidence, or metadata. It is not yet bound to a live PR flow. |
| Pre-publication verification gate | implemented | `services/core-control-plane/src/fdai/core/deploy_preflight/pre_publication_gate.py` and `test_pre_publication_gate.py` | The analyzer runs again before any remediation proposal is submitted; a blocking, stale, or scope-changed report withholds publication and submits nothing. |
| PR delivery refresh wrapper | implemented | `services/core-control-plane/src/fdai/delivery/deploy_preflight/pr_publication.py` and `services/core-control-plane/tests/delivery/test_preflight_pr_publication.py` | An injected read-only refresh must bind the exact patch digest, trusted scope, complete probe categories, and current non-blocking report before the existing PR publisher is called. |
| Control-loop pre-PR gate and GitHub delivery composition | in-progress | The deterministic gate and delivery adapters above | No live trigger or runtime binding supplies the exact-plan refresh, and no live path invokes the wrapper or posts a GitHub Check. |
| Check publishing primitive | implemented | `services/core-control-plane/src/fdai/core/deploy_preflight/check_publish.py` and `test_check_publish.py` | The pure report publisher and in-memory adapter are tested; there is no GitHub Checks adapter. |
| Control-loop pre-PR gate and GitHub delivery | not-started | The planned boundaries in this document | No live path invokes the analyzer before a remediation PR or publishes the result to GitHub Checks. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-08-14 | in-progress | Adopted the implementation ledger; earlier provenance was not reconstructed. Corrected the protected-runner path to the current standalone preflight entrypoint. | current change; focused core preflight and live-script checks listed in the scope table | Compose the root toggle consumer, durable profile refresh, GitHub publisher, and control-loop gate. |
| 2026-08-24 | implemented | Resolved the root-consumer ownership conflict by keeping concrete resource rendering fork-owned and adding a reusable mock-provider plan fixture for the upstream disk toggle contract. | `current change`; `infra/modules/preflight-toggles/reference-disk-consumer/tests/alternate_rendering.tftest.hcl`; focused Terraform test passed 2 cases. | Each fork binds the validated pattern in its owned compute module. The durable profile refresh, GitHub publisher, and control-loop gate remain open. |
| 2026-09-26 | in-progress | Added the deterministic pre-publication gate: the analyzer is re-run on the accumulated overrides before any remediation proposal is submitted, and a blocking, stale, scope-changed, or escalated pass is lowered to human review with nothing submitted. | `current change`; `services/core-control-plane/src/fdai/core/deploy_preflight/pre_publication_gate.py`; `uv run pytest tests/core/deploy_preflight -q` passed 98 tests. | Compose the gate on the live control-loop path, add the durable profile refresh, and add the GitHub Checks publisher. |
| 2026-09-26 | in-progress | Hardened the gate after review: a padded expected scope is normalized, a non-finite freshness window and a naive clock are rejected before any submission, and a hold record retains a bounded set of finding ids. | `current change`; `services/core-control-plane/tests/core/deploy_preflight/test_pre_publication_gate.py`; focused `uv run pytest tests/core/deploy_preflight -q` passed. | Unchanged: compose the gate on the live control-loop path, add the durable profile refresh, and add the GitHub Checks publisher. |
| 2026-09-26 | in-progress | Closed the verdict coverage gap found in review: a warning-only report and a clean shadow report both publish a shadow-first proposal, and both paths are now asserted. | `current change`; `services/core-control-plane/tests/core/deploy_preflight/test_pre_publication_gate.py`; focused `uv run pytest tests/core/deploy_preflight -q` passed 105 tests. | Unchanged: compose the gate on the live control-loop path, add the durable profile refresh, and add the GitHub Checks publisher. |
| 2026-09-26 | in-progress | Added a delivery-side pre-PR refresh wrapper and sanitized GitHub Checks adapter using existing provider seams, without granting either execution or approval authority. | `current change`; `services/core-control-plane/src/fdai/delivery/deploy_preflight/pr_publication.py`, `services/core-control-plane/src/fdai/delivery/github/preflight_checks.py`, and focused delivery tests (`uv run pytest -q --no-cov services/core-control-plane/tests/delivery/test_preflight_pr_publication.py services/core-control-plane/tests/delivery/test_github_preflight_checks.py`, 30 passed). | Compose a trusted live refresh and fence source-base drift, bind Checks after PR creation, carry governed toggle arguments, and add durable profile invalidation and operational evidence. |
| 2026-09-27 | implemented | Added a restartable, compare-and-set environment-profile refresh task and wired the recovery Inventory-delta cursor fence to invalidate its durable record before cursor advance. A fresh record is read from the shared store rather than trusting process-local cache state; a concurrent delta or expired lease cannot publish an old probe result. | `current change`; `services/core-control-plane/src/fdai/delivery/deploy_preflight/environment_profile_refresh.py`, `delivery/inventory_delta.py`, `delivery/inventory_change_acceleration.py`, `tests/delivery/test_environment_profile_refresh.py`; `uv run pytest -q --no-cov services/core-control-plane/tests/delivery/test_environment_profile_refresh.py services/core-control-plane/tests/delivery/test_inventory_delta.py` (45 passed). | Bind a trusted read-only profile builder and scheduled refresh at runtime; the control-loop PR gate, Checks delivery, and governed operational evidence remain separate. |

### Remaining work

- [x] Keep the generic upstream root free of fork-owned resource consumers and ship a reusable
  Terraform fixture proving that `attach_existing` removes the policy-denied managed-disk shape
  from the alternate plan. The focused fixture passes both renderings.
- [x] Add a durable environment-profile refresh task with Inventory-delta invalidation and pass restart and expiry tests. The focused profile and Inventory-delta checks cover cursor fencing and expired-lease recovery.
- [x] Invoke the analyzer again before remediation-PR publication and lower a blocking, stale, or
  scope-changed report to human review. `core/deploy_preflight/pre_publication_gate.py` and
  `tests/core/deploy_preflight/test_pre_publication_gate.py` prove that a withheld pass submits no
  proposal, so no PR opens on a blocked report.
- [ ] Compose that gate on the live control-loop path so the executor's remediation PR is published only behind it, and retain the composed run evidence.
- [x] Add a PR-publisher wrapper that withholds delivery on unavailable refresh, patch or scope drift,
  stale or incomplete evidence, or blocking findings, and prove no GitOps HTTP call occurs on a hold.
- [x] Add a sanitized GitHub Checks adapter for an existing PR head with focused redaction,
  advisory shadow, idempotency, and unavailable-delivery tests.
- [ ] Bind the PR refresh and Checks adapter to the live runtime using a trusted scope and
  re-render/re-plan callback; fence source-base drift between refresh and provider commit, carry
  per-toggle arguments through governed ingress, and record a composed run with fresh report
  and exact head revision.
- [x] Keep the generic upstream root free of fork-owned resource consumers and ship a reusable

- [ ] Add a durable environment-profile refresh task with Inventory-delta invalidation and pass restart and expiry tests.

- [ ] Invoke the analyzer before remediation-PR publication, lower blocking findings to human review, and prove with an integration test that no PR opens on a blocked report.

- [ ] Publish the sanitized report through a GitHub Checks adapter and retain a focused contract test for redaction and failed delivery.
