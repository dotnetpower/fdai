# Disconnected Deployment implementation ledger

This delivery ledger preserves reviewable implementation scope, append-only transitions,
and resumable work while the roadmap owner remains focused on normative design.

## Implementation status

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| Private Azure networking and VNet deploy host | implemented | `infra/`, `infra/bootstrap/`, `.github/workflows/deploy-dev.yml`, and focused infrastructure workflow tests | Private endpoints, DNS, the durable deploy host, protected plans, and exact apply are implemented independently of the offline CLI path. |
| Internal mirror and pinned-input controls | implemented | `infra/modules/preflight-toggles/` and `scripts/quality/ci/check-ci-contracts.py` | The repository exposes mirror inputs and rejects mutable or registry-bound base-image references. |
| Signed offline Python package | validated | `build-signed-python-package.sh`; package policy v3; focused tests; real build and pip cold install | One detached Ed25519 signature covers the 6.9 MB wheelhouse checksum list. No artifact profile, trust ceremony, nested signature, SBOM, provenance, or runtime receipt is required. |
| Optional deployment payload tools | implemented | Existing runtime, bundle, offline payload, and appliance helpers | These tools remain available to deployment owners but do not define Python package installation or completion. |
| Full-air-gap cloud operation | not-applicable | The full-air-gap boundary in this document | The deterministic core can run from static inputs, but live Azure evidence and cloud mutation are intentionally outside this profile. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-09-27 | validated | Replaced the complete offline kit as the installation package with a pip-style signed wheelhouse and made runtime payloads and appliances optional deployment-owner concerns. | `current change`; package policy v3, builder tests, 6.9 MB artifact, OpenSSL/checksum verification, and pip cold install. | No disconnected Python package work remains. |
| 2026-09-27 | implemented | Replaced appliance re-archiving with a bounded no-follow private copy of the exact verified input archive and retained independent verification of the copied bytes. | `current change`; appliance builder contract regression and live original-versus-embedded archive SHA comparison. | Deliver through protected CI, rebuild the appliance, and retain an image-entry-point Azure receipt from the exact local-coordinator kit bytes. |
| 2026-09-22 | implemented | Added an optional signed Rule activation profile to the exact-file-set offline kit and bound its id, source time, file digest, and kit digest into the private preparation receipt. | `current change`; focused offline-kit tests passed 5 cases; strict mypy, Ruff, and shell syntax passed. | Retain a complete signed-kit drill and approved artifact-offline deployment receipt before claiming operational validation. |
| 2026-08-14 | in-progress | Adopted the implementation ledger; earlier provenance was not reconstructed. Corrected the prior end-to-end support claim after the deployment CLI package was removed. | current change; infrastructure, release-script, package-metadata, and focused workflow evidence listed in the scope table | Restore the dedicated offline verifier and CLI, establish the trust root, and pass the air-gap drill. |
| 2026-09-09 | implemented | Reconciled the ledger with the restored independent CLI and added digest-bound runtime v2 assembly plus an explicit complete air-gap drill mode. | `current change`; runtime builder, release wrapper, complete-mode drill, focused runtime and productization checks | Run complete mode with eligible exact-revision artifacts, then retain governed signing, protected apply, state handoff, and readiness evidence. |
| 2026-09-09 | implemented | Corrected the complete staging order after real release preparation exposed that a prebuilt runtime inventory cannot know the exact deployment bundle produced by a later signing attempt. Descriptor mode now builds the signed bundle first and assembles runtime v2 against those exact bytes before outer kit signing; prebuilt mode remains supported. The same review restored the service-owned bundle-builder import path and rejects signing-key symlinks before Python revalidation. | `current change`; `stage-offline-kit.sh`, `airgap-drill.sh`, focused productization, bundle-builder import, and documentation checks | Produce eligible exact-revision image, Console, and support inputs and retain a passing complete drill. |
| 2026-09-09 | implemented | Preserved the original manifest digest while accepting the coherent Docker schema 2 media family emitted by the protected publisher inside the existing strict OCI Image Layout boundary. | `current change`; OCI archive validator plus positive Docker service/dependency and negative mixed, schema 1, and foreign-layer tests | Rebuild exact-revision runtime inputs and retain a passing complete drill. |
| 2026-09-12 | implemented | Added a single-image handoff that verifies and embeds the complete signed kit, installs the deployment CLI without network access, and starts the manual standalone Azure coordinator from the image entry point. | `current change`; appliance builder, entry point, and focused integration tests | Build from an approved base and retain one artifact-offline Azure deployment receipt. |

### Remaining work

- [x] The signed Python wheelhouse verifies and installs without network access.
- [ ] Prove the Azure deployment path separately, including exact plans, rollback, health, and
  cleanup. It is not a package completion criterion.
