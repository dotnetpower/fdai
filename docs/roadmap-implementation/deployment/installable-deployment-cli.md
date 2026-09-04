# Installable Deployment CLI implementation ledger

This delivery ledger preserves reviewable implementation scope, append-only transitions,
and resumable work while the roadmap owner remains focused on normative design.

## Implementation status

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| Dedicated `fdaictl` distribution and command entrypoint | implemented | `packages/deployment-cli`; focused package and productization tests | The `fdai-deployment-cli` wheel registers `fdaictl`, provides deterministic local commands, and seals target-pinned read-only bootstrap reconciliation. Protected Azure dispatch remains incomplete. |
| Core deployment preflight primitives | implemented | `services/core-control-plane/src/fdai/core/deploy_preflight/` and focused preflight tests | The analyzer, report, Azure live script, toggle primitives, and reassembly logic exist independently of a deployment CLI facade. |
| Protected runner plan and exact-apply workflow | implemented | `.github/workflows/deploy-dev.yml` and focused deployment workflow tests | The runner owns protected planning, evidence binding, claim/receipt guards, convergence, migrations, and health checks; there is no packaged local CLI client. |
| Bounded RCA reader prerequisite selection | implemented | `DeploymentSelection`; `deploy-dev.yml`; `enforce_plan_scope.py`; focused CLI and workflow checks | The request-bound mode uses no additional workflow input and permits only the dedicated RCA reader identity and Monitoring Reader role before split Core deployment. |
| Signed deployment bundle release path | in-progress | Bundle builder and `fdaictl bundle verify`; focused signature, SBOM, compatibility, extraction, and tamper tests | Construction and verification are executable. Restoring the protected publication workflow remains open. |
| Offline kit and disconnected planning | validated | Locked release tooling, offline-kit verifier, shipped-wheel installation, and successful network-isolated air-gap drill | The drill verified no egress or DNS, exact artifacts, mirror-only Terraform init, Terraform validation and 20 tests, license inspection, and the operator plan path. |
| Published install and teardown experience | not-started | The target installation and teardown contracts in this document | No first public CLI publication, pinned offline root package, or `deploy teardown` command is available. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-09-04 | implemented | Corrected status validation for the request-bound RCA mode so `plan-rca-*` and `apply-rca-*` remove the complete reviewed mode prefix before comparing the embedded target/context binding. | `current change`; focused status and deployment CLI checks. | Retain the exact plan metadata and apply receipt. |
| 2026-09-04 | implemented | Added an exclusive `--deploy-rca-reader-identity` selection that derives `plan-rca-*` and `apply-rca-*` request ids while preserving the 25-input GitHub workflow ceiling. | `current change`; deployment CLI, request validation, plan-scope, and workflow checks passed 239 cases; Ruff and strict mypy passed. | Retain the exact plan, apply, output, and split Core consumption receipts. |
| 2026-09-03 | implemented | Made a selected Core runtime revision independent of isolated Executor deployment and derived plan-time image promotion from that sealed revision. | `current change`; `fdai_deployment_cli.github_actions`, deployment request validation, and focused CLI/workflow tests | Retain one protected plan and exact apply receipt using a runtime revision without Executor deployment. |
| 2026-08-14 | in-progress | Adopted the implementation ledger; earlier provenance was not reconstructed. Corrected prior claims that the removed deployment CLI package and its commands were currently available. | current change; package metadata, release scripts, protected workflows, and focused workflow checks listed in the scope table | Create the dedicated CLI distribution, restore verification behind that boundary, and prove installation plus disconnected use. |
| 2026-08-19 | deferred | Removed the manual deployment-bundle workflow because it invoked the unavailable `fdaictl bundle verify` command and had no successful run evidence. | issue #222; current workflow inventory and focused CI contract tests | Add the dedicated CLI verifier first, then restore a protected release workflow with clean-checkout evidence. |
| 2026-08-19 | deferred | Removed the retired workflow-only test from productization validation so the release check no longer requires a path that the deferred workflow removed. | current change; `scripts/deployment/release/verify-productization.sh`; focused productization and structural-gate tests passed 55 cases | Restore the workflow test only with an executable CLI verifier and protected release workflow. |
| 2026-08-29 | implemented | Added the independent `fdai-deployment-cli` wheel with the `fdaictl` entry point, secure profile and journal contracts, signed artifact verification, and no-mutation genesis rehearsal. | `current change`; focused package and productization tests passed 28 cases; Ruff and strict mypy passed | Complete protected plan/apply adapters, publish the wheel, and retain the disconnected drill. |
| 2026-08-29 | validated | Hardened the pre-login CLI and release path through 75 focused rounds and completed the shipped-wheel air-gap drill without network or DNS. | Campaign commits from `dd28b64d9`; 89 focused tests, Ruff, strict mypy, locked wheel build, isolated install, Terraform validation, 20 Terraform tests, and successful `airgap-drill.sh` | Complete protected Azure dispatch and publish the first signed release. |
| 2026-08-30 | implemented | Added target-pinned bootstrap reconciliation before the first runner or private backend exists. The command distinguishes not-found from unreadable state, checks global storage-name availability and private keyless posture, and separates deterministic intent from expiring observations without mutating Azure. Journal schema v3 now binds every completed stage to a receipt digest, legacy journals are replay-only, and the aggregate readiness contract requires foundation through system-verification evidence, complete inventory closure, and a zero-change second run. Thirteen hardening rounds closed every Medium finding. | `current change`; `bootstrap_plan.py`; `bootstrap_reconcile.py`; `private_output.py`; `readiness.py`; focused bootstrap, plan-input, journal, readiness, simulation, and workflow tests; final independent severity audit found no Medium-or-higher issue | Add the separately approved foundation apply and remote-state handoff before enabling protected application planning. |

### Remaining work

- [x] The dedicated CLI distribution, source invocation, isolated wheel, deterministic `version`,
  target-aware inspection, private profile handling, and local security boundaries pass focused tests.
- [ ] Implement the remaining `security audit` checks and pass deterministic text and JSON tests.
- [ ] Wire the existing preflight and protected workflow contracts into `deploy preflight`, `plan`, `status`, and `apply`, and pass wrong-target, fail-stop, exact-plan, expiry, and redaction tests.
- [ ] Bind `bootstrap-reconcile` to an approved foundation apply that revalidates its exact target,
  intent digest, observation freshness, and conflict-free state before any provider or resource
  mutation.
- [x] Bundle and offline-kit verification are in the dedicated package, and the shipped-wheel
  network-free air-gap drill completed successfully.
- [ ] Restore the protected signed-bundle publication workflow after its clean-checkout tests pass.
- [ ] Publish the first pinned CLI release with the offline trust root and prove install, upgrade, rollback, internal-mirror delivery, and guarded teardown with reviewable receipts.
- [ ] Retain a bounded RCA reader identity plan and exact apply, then prove the split Core plan consumes the resulting platform output.
