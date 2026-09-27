# Provisioning Execution Profiles implementation ledger

This delivery ledger preserves reviewable implementation scope, append-only transitions,
and resumable work while the roadmap owner remains focused on normative design.

## Implementation status

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| Read-only inspection and profile initialization commands | implemented | `packages/deployment-cli`; focused profile, target, inspection, and productization tests | The dedicated wheel registers `fdaictl`, persists private target-bound profiles, and keeps execution-host readiness at review until external evidence exists. |
| Managed VM, private backend, and manual deployment host | implemented | `infra/bootstrap/`; standalone deployment modules; focused bootstrap and package tests | The durable VNet host, workload identity, private state, exact plans, and exact apply are coordinated locally without GitHub Actions. |
| Signed offline Python package | validated | `build-signed-python-package.sh`; package policy v3; focused tests; real 6.9 MB build and pip cold install | One detached Ed25519 signature covers the local wheelhouse checksum list. Complete-kit and trust-ceremony evidence are not package prerequisites. |
| Temporary public-access cleanup | not-started | The access preference contract in this document | No composed command proves bounded creation, automatic cleanup, incomplete-on-cleanup-failure behavior, and audit closure. |
| Post-provision verification | in-progress | Protected workflow checks and `docs/roadmap/operations/operating-and-verification.md` | Runner-side convergence, migrations, health, and canary checks exist; the complete CLI-driven lifecycle and disconnected receipt do not. |
| Optional OCI deployment appliance | implemented | appliance builder and entry point; focused shell tests | Appliance delivery is optional deployment tooling and no longer a package completion criterion. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-09-27 | validated | Reduced offline package installation to a signed wheelhouse and removed complete-kit, trust-root, TUF, SBOM, provenance, same-byte appliance, and dual-entry deployment receipts from package completion. | `current change`; package policy v3, focused tests, real build, OpenSSL/checksum verification, pip cold install. | Package installation is complete. Azure convergence remains independent deployment work. |
| 2026-08-14 | in-progress | Adopted the implementation ledger; earlier provenance was not reconstructed. Corrected inspection, profile persistence, and offline verification from implemented to their evidence-backed current states. | current change; package metadata, bootstrap source, release scripts, and focused workflow checks listed in the scope table | Create the CLI package, restore offline verification, complete trust bootstrap, and validate the full lifecycle. |
| 2026-09-09 | implemented | Reconciled obsolete missing-package claims with the independent CLI, private profile, and restored offline verifier currently in source. | `current change`; package source plus focused profile, artifact, productization, and runtime release checks | Complete temporary-access cleanup, trust-root bootstrap, protected application execution, and governed lifecycle evidence. |
| 2026-09-09 | implemented | Bound descriptor-driven runtime v2 assembly to the exact signed deployment bundle generated inside kit staging while preserving already-matching prebuilt runtime input. | `current change`; release staging, complete air-gap argument contracts, and focused productization checks | Retain an eligible descriptor-driven complete drill and the governed lifecycle receipt. |
| 2026-09-12 | implemented | Restricted provisioning profiles to manual transport, removed workflow dispatch from the public CLI, and added a deployment appliance that starts the artifact-offline standalone coordinator. | `current change`; profile contracts, CLI parser, appliance scripts, and focused tests | Retain one connected and one appliance-based Azure deployment receipt. |

### Remaining work

- [x] `provision inspect` and `provision init` are in the dedicated CLI package with no-mutation, private-mode, overwrite, symlink, target-binding, and stable-JSON tests.
- [x] The signed Python wheelhouse verifies with one detached Ed25519 signature and installs with
  pip without network access.
- [ ] Implement temporary public-access creation and cleanup so cleanup failure leaves an incomplete audited operation, then pass CIDR, duration, authentication, rollback, and idempotency tests.
- [ ] Complete Azure plan, apply, cleanup, and verification independently from package installation.
