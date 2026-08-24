# Provisioning Execution Profiles implementation ledger

This delivery ledger preserves reviewable implementation scope, append-only transitions,
and resumable work while the roadmap owner remains focused on normative design.

## Implementation status

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| Read-only inspection and profile initialization commands | not-started | Repository package metadata and the command contracts in this document | No dedicated CLI distribution or `fdaictl` project script currently exists. |
| Managed VM, private backend, and protected runner | implemented | `infra/bootstrap/`, `.github/workflows/deploy-dev.yml`, and focused bootstrap and workflow tests | The durable VNet host, workload identity, private state, protected plan, and exact-apply mechanics exist without the local CLI facade. |
| Offline-kit construction and verification | in-progress | `scripts/deployment/release/build-offline-kit.py` and `stage-offline-kit.sh` | Release scripts exist, but their imported `fdai.deployment_cli.offline_kit` implementation is absent. |
| Temporary public-access cleanup | not-started | The access preference contract in this document | No composed command proves bounded creation, automatic cleanup, incomplete-on-cleanup-failure behavior, and audit closure. |
| Pinned TUF root and rotation | not-started | `docs/runbooks/offline-trust-ceremony.md` | The first root ceremony, package resource, client bootstrap, and rotation evidence remain open. |
| Post-provision verification | in-progress | Protected workflow checks and `docs/roadmap/operations/operating-and-verification.md` | Runner-side convergence, migrations, health, and canary checks exist; the complete CLI-driven lifecycle and disconnected receipt do not. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-08-14 | in-progress | Adopted the implementation ledger; earlier provenance was not reconstructed. Corrected inspection, profile persistence, and offline verification from implemented to their evidence-backed current states. | current change; package metadata, bootstrap source, release scripts, and focused workflow checks listed in the scope table | Create the CLI package, restore offline verification, complete trust bootstrap, and validate the full lifecycle. |

### Remaining work

- [ ] Implement `provision inspect` and `provision init` in the dedicated CLI package and pass no-mutation, mode-`0600`/`0700`, overwrite, symlink, and stable-JSON tests.
- [ ] Restore offline-kit verification behind an injected release root and pass signature-before-parse, exact-file-set, no-follow digest, compatibility, and bounds tests.
- [ ] Implement temporary public-access creation and cleanup so cleanup failure leaves an incomplete audited operation, then pass CIDR, duration, authentication, rollback, and idempotency tests.
- [ ] Complete the TUF root ceremony and package bootstrap, then retain a governed inspect-to-plan-to-apply-to-cleanup-to-verification receipt.
