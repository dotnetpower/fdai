# Disconnected Deployment implementation ledger

This delivery ledger preserves reviewable implementation scope, append-only transitions,
and resumable work while the roadmap owner remains focused on normative design.

## Implementation status

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| Private Azure networking and VNet deploy host | implemented | `infra/`, `infra/bootstrap/`, `.github/workflows/deploy-dev.yml`, and focused infrastructure workflow tests | Private endpoints, DNS, the durable deploy host, protected plans, and exact apply are implemented independently of the offline CLI path. |
| Internal mirror and pinned-input controls | implemented | `infra/modules/preflight-toggles/` and `scripts/quality/ci/check-ci-contracts.py` | The repository exposes mirror inputs and rejects mutable or registry-bound base-image references. |
| Offline kit staging and drill harness | in-progress | `scripts/deployment/release/stage-offline-kit.sh`, `build-offline-kit.py`, and `airgap-drill.sh` | The scripts are present, but the builder imports the absent `fdai.deployment_cli.offline_kit` module and the drill cannot complete. |
| Disconnected inspection, bundle verification, and planning commands | not-started | The target command sequence in this document | No current package registers `fdaictl`; the inspect, bundle, provision-plan, and license command paths are unavailable. |
| Pinned offline trust root and release integration | not-started | `docs/runbooks/offline-trust-ceremony.md` | No pinned root ships in a CLI wheel and kit staging is not a passing release workflow. |
| Full-air-gap cloud operation | not-applicable | The full-air-gap boundary in this document | The deterministic core can run from static inputs, but live Azure evidence and cloud mutation are intentionally outside this profile. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-08-14 | in-progress | Adopted the implementation ledger; earlier provenance was not reconstructed. Corrected the prior end-to-end support claim after the deployment CLI package was removed. | current change; infrastructure, release-script, package-metadata, and focused workflow evidence listed in the scope table | Restore the dedicated offline verifier and CLI, establish the trust root, and pass the air-gap drill. |

### Remaining work

- [ ] Implement and package offline-kit and deployment-bundle verification behind the dedicated CLI boundary, with tamper, symlink, extra-file, missing-file, digest, size, and compatibility tests.
- [ ] Establish and package the offline trust root through the governed ceremony, then prove inspection distinguishes verified, review, and rejected kits without a network call.
- [ ] Make `stage-offline-kit.sh` and `airgap-drill.sh` pass from a clean release checkout inside a namespace with no route or DNS.
- [ ] Prove the manual exact-plan approval and apply path from a private deploy host, including rollback, teardown, and post-provision verification receipts.
