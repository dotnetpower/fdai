# Installable Deployment CLI implementation ledger

This delivery ledger preserves reviewable implementation scope, append-only transitions,
and resumable work while the roadmap owner remains focused on normative design.

## Implementation status

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| Dedicated `fdaictl` distribution and command entrypoint | implemented | `packages/deployment-cli`; focused package and productization tests | The `fdai-deployment-cli` wheel registers `fdaictl` and provides deterministic local commands. Protected Azure dispatch remains incomplete. |
| Core deployment preflight primitives | implemented | `services/core-control-plane/src/fdai/core/deploy_preflight/` and focused preflight tests | The analyzer, report, Azure live script, toggle primitives, and reassembly logic exist independently of a deployment CLI facade. |
| Protected runner plan and exact-apply workflow | implemented | `.github/workflows/deploy-dev.yml` and focused deployment workflow tests | The runner owns protected planning, evidence binding, claim/receipt guards, convergence, migrations, and health checks; there is no packaged local CLI client. |
| Signed deployment bundle release path | not-started | `scripts/deployment/release/build-deployment-bundle.py` and issue #222 | Bundle construction remains available, but the non-runnable workflow was removed. Restore the release path only after `fdaictl bundle verify` exists and clean-checkout tests pass. |
| Offline kit and disconnected planning | in-progress | `fdai_deployment_cli.offline_kit`; release scripts; focused signature, exact-file-set, compatibility, and tamper tests | Packaging derives the host platform and resolves hashed binary wheels with the exact CLI build Python. The drill installs only those wheels with `--no-index`; a governed network-free run remains open. |
| Published install and teardown experience | not-started | The target installation and teardown contracts in this document | No first public CLI publication, pinned offline root package, or `deploy teardown` command is available. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-08-14 | in-progress | Adopted the implementation ledger; earlier provenance was not reconstructed. Corrected prior claims that the removed deployment CLI package and its commands were currently available. | current change; package metadata, release scripts, protected workflows, and focused workflow checks listed in the scope table | Create the dedicated CLI distribution, restore verification behind that boundary, and prove installation plus disconnected use. |
| 2026-08-19 | deferred | Removed the manual deployment-bundle workflow because it invoked the unavailable `fdaictl bundle verify` command and had no successful run evidence. | issue #222; current workflow inventory and focused CI contract tests | Add the dedicated CLI verifier first, then restore a protected release workflow with clean-checkout evidence. |
| 2026-08-19 | deferred | Removed the retired workflow-only test from productization validation so the release check no longer requires a path that the deferred workflow removed. | current change; `scripts/deployment/release/verify-productization.sh`; focused productization and structural-gate tests passed 55 cases | Restore the workflow test only with an executable CLI verifier and protected release workflow. |
| 2026-08-29 | implemented | Added the independent `fdai-deployment-cli` wheel with the `fdaictl` entry point, secure profile and journal contracts, signed artifact verification, and no-mutation genesis rehearsal. | `current change`; focused package and productization tests passed 28 cases; Ruff and strict mypy passed | Complete protected plan/apply adapters, publish the wheel, and retain the disconnected drill. |

### Remaining work

- [ ] Add a dedicated lightweight CLI distribution with an `fdaictl` project script, then pass source-install and isolated-wheel tests for deterministic `version`, `doctor`, and `security audit` output.
- [ ] Wire the existing preflight and protected workflow contracts into `deploy preflight`, `plan`, `status`, and `apply`, and pass wrong-target, fail-stop, exact-plan, expiry, and redaction tests.
- [ ] Move bundle and offline-kit verification into the dedicated CLI package, restore their release workflows only after clean-checkout tests pass, and run the network-free air-gap drill successfully.
- [ ] Publish the first pinned CLI release with the offline trust root and prove install, upgrade, rollback, internal-mirror delivery, and guarded teardown with reviewable receipts.
