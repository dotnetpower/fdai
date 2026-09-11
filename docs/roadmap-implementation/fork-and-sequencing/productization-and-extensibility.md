# Productization and Extensibility Plan implementation ledger

This delivery ledger preserves reviewable implementation scope, append-only transitions,
and resumable work while the roadmap owner remains focused on normative design.

## Implementation status

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| Executable productization verification | implemented | `scripts/deployment/release/verify-productization.sh`; `tests/integration/scripts/test_verify_productization.py`; focused productization tests (`11 passed`) | The gate checks repository structure, one Alembic head, CLI wheel build, and required packaging and productization contracts. It does not install the built wheel or replace full release and live deployment evidence. |
| Deployment CLI package and project-environment command | implemented | `packages/deployment-cli/`; `tests/integration/scripts/test_deployment_cli_productization.py`; focused productization tests (`11 passed`) | Package metadata and the version command are verified through the project environment. This does not prove installation from the built wheel. |
| Signed deployment bundle construction and verification | in-progress | `docs/roadmap-implementation/deployment/installable-deployment-cli.md`; bundle builder and `fdaictl bundle verify` tests | Construction and verification are executable, but the protected publication workflow remains open. |
| Authenticated shipped-wheel installation | validated | `scripts/deployment/release/airgap-drill.sh`; `docs/roadmap-implementation/deployment/installable-deployment-cli.md` | The network-isolated air-gap drill installs the authenticated shipped wheel into a fresh virtual environment with `--no-index` and executes the installed `fdaictl`. This does not establish public publication or connected deployment authority. |
| Protected publication and public installation | not-started | `docs/roadmap-implementation/deployment/installable-deployment-cli.md` | No first public CLI publication or pinned public installation experience exists. |
| Governed connected deployment and live migration | implemented | `.github/workflows/deploy-dev.yml`; `docs/roadmap-implementation/deployment/installable-deployment-cli.md` | The protected exact-apply path includes convergence, migrations, and health checks. A retained governed deployment receipt and a live disposable-database migration result remain required before validation. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-08-24 | not-started | Adopted the delegated ledger; earlier provenance was not reconstructed. | current change; `docs/roadmap/fork-and-sequencing/productization-and-extensibility.md`. | Assess bounded source and test evidence before raising any scope state. |
| 2026-09-12 | implemented | Replaced the unassessed placeholder with bounded local productization-gate and installable-CLI evidence while keeping release publication and deployed installation open. | `current change`; focused productization and deployment CLI tests (`11 passed`). | Retain approval-gated signed release and clean deployed-installation evidence separately. |
| 2026-09-12 | in-progress | Corrected the combined release and installation scope by separating executable bundle work, validated isolated shipped-wheel installation, unimplemented public publication, and implemented-but-unvalidated connected deployment. | `current change`; `docs/roadmap-implementation/deployment/installable-deployment-cli.md`; `scripts/deployment/release/airgap-drill.sh`; `.github/workflows/deploy-dev.yml`. | Restore protected publication and public installation, then retain governed connected-deployment and live disposable-database migration receipts. |

### Remaining work

- [x] Assess bounded source and focused-test evidence and replace the unassessed scope with
  independently deliverable rows (`11 passed`).
- [x] Retain the successful network-isolated air-gap drill that installed and executed the
  authenticated shipped wheel from the offline kit.
- [ ] Restore the protected signed-bundle publication workflow and record a passing focused
  workflow check before raising signed bundle construction and verification to `implemented`.
- [ ] Publish the first approved CLI release and verify its pinned public installation before
  raising the public installation row above `not-started`.
- [ ] Retain a governed connected-deployment receipt and a successful live disposable-database
  migration result before raising the connected deployment row to `validated`.
