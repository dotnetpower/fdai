# Deployment Preflight (feasibility and blocker collection) implementation ledger

This delivery ledger preserves reviewable implementation scope, append-only transitions,
and resumable work while the roadmap owner remains focused on normative design.

## Implementation status

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| Probe contracts, deterministic probes, analyzer, and report | implemented | `services/core-control-plane/src/fdai/core/deploy_preflight/`, `services/core-control-plane/src/fdai/shared/providers/feasibility_probe.py`, and focused deploy-preflight tests | Stable findings, fail-closed probe execution, verdicts, and shadow-versus-enforce behavior are tested. |
| Read-only Azure probes and protected-plan evidence | implemented | `scripts/deployment/azure/run_live_preflight.py`, `.github/workflows/deploy-dev.yml`, and `tests/integration/scripts/test_run_live_preflight.py` | The protected runner invokes the standalone script, requires all four live categories, sanitizes evidence, and binds its digest to the plan. |
| Terraform toggle, alternate-rendering fixture, and environment-profile primitives | implemented | `infra/modules/preflight-toggles/`; focused `terraform test -filter=tests/alternate_rendering.tftest.hcl`, `test_environment_profile.py`, and `test_reassembly_proposals.py` checks | The generic upstream root intentionally does not instantiate the fork-owned resource consumer. The durable profile refresh task is not composed. |
| Check publishing primitive | implemented | `services/core-control-plane/src/fdai/core/deploy_preflight/check_publish.py` and `test_check_publish.py` | The pure report publisher and in-memory adapter are tested; there is no GitHub Checks adapter. |
| Control-loop pre-PR gate and GitHub delivery | not-started | The planned boundaries in this document | No live path invokes the analyzer before a remediation PR or publishes the result to GitHub Checks. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-08-14 | in-progress | Adopted the implementation ledger; earlier provenance was not reconstructed. Corrected the protected-runner path to the current standalone preflight entrypoint. | current change; focused core preflight and live-script checks listed in the scope table | Compose the root toggle consumer, durable profile refresh, GitHub publisher, and control-loop gate. |
| 2026-08-24 | implemented | Resolved the root-consumer ownership conflict by keeping concrete resource rendering fork-owned and adding a reusable mock-provider plan fixture for the upstream disk toggle contract. | `current change`; `infra/modules/preflight-toggles/reference-disk-consumer/tests/alternate_rendering.tftest.hcl`; focused Terraform test passed 2 cases. | Each fork binds the validated pattern in its owned compute module. The durable profile refresh, GitHub publisher, and control-loop gate remain open. |

### Remaining work

- [x] Keep the generic upstream root free of fork-owned resource consumers and ship a reusable
	Terraform fixture proving that `attach_existing` removes the policy-denied managed-disk shape
	from the alternate plan. The focused fixture passes both renderings.
- [ ] Add a durable environment-profile refresh task with Inventory-delta invalidation and pass restart and expiry tests.
- [ ] Invoke the analyzer before remediation-PR publication, lower blocking findings to human review, and prove with an integration test that no PR opens on a blocked report.
- [ ] Publish the sanitized report through a GitHub Checks adapter and retain a focused contract test for redaction and failed delivery.
