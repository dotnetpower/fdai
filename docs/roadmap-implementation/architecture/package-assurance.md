# Package Assurance implementation ledger

This delivery ledger tracks the machine policy, focused gates, and bounded runtime tooling that
implement the package assurance design.

## Implementation status

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| Minimal signed-package inventory | implemented | `config/package-assurance.json`; `check-package-assurance.py`; focused policy tests | The global gate lists one distributed Python package and one detached Ed25519 signature format. It has no boundary, profile, lifecycle, compatibility, evidence, or authority matrix. |
| Pip-installable offline wheelhouse | validated | `build-signed-python-package.sh`; focused builder tests; real 6.9 MB package build and cold installation | One signature covers `SHA256SUMS`; standard OpenSSL, `sha256sum`, and pip commands verify and install the package without network access. |
| Deployment and runtime assurance | not-applicable | Deployment owner documents and runtime checks | Azure identity, Terraform plans, service images, SBOMs, provenance, readiness, and recovery are not package-installation requirements. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-10-02 | implemented | The signed control-package builder now rejects release environments unless the repository interpreter is CPython 3.12, matching the managed-host interpreter before any dependency wheel download begins. | `current change`; focused `test_signed_python_package.py` guard regression; package assurance design update. | None for the control-package interpreter contract. |
| 2026-09-28 | implemented | Constitution Article 1 now defines deployment distribution: a key holder's contributor source deployment builds everything from the checkout, and a signed offline package installs every resource on an Azure VM without internet access. Every other installation gate is superseded. `fdai-up.sh --source <checkout> --signing-key <key>` builds and deploys in one command. | `current change`; constitution check; wrapper tests in `test_deployment_cli_productization.py` | Remove superseded gate text and code checks that this owner still carries. Retain one live contributor deployment receipt. |
| 2026-09-27 | validated | Replaced boundary/profile assurance with a pip-style offline wheelhouse containing one requirements file, one checksum list, and one detached private-key signature. | `current change`; policy schema v3, focused checker/builder tests, OpenSSL signature verification, checksum verification, pip cold install, and `fdaictl 0.1.1` readback. | No package-specific implementation remains. Deployment payload simplification continues only under deployment owners. |
| 2026-09-27 | implemented | Closed derived deployment transport over the required signed profile root so materialization cannot reduce an offline artifact from root-bound to legacy-only verification. | `current change`; transport archive construction and round-trip package-root verification regression. | Rebuild the owner artifact and verify the managed-host round trip; no additional global package constraint is introduced. |
| 2026-09-27 | implemented | Kept managed-host compatibility owner-scoped: complete deployment kits pin the exact Python ABI while interpreting glibc as a minimum same-family floor instead of a repository-wide exact-host rule. | `current change`; offline-kit compatibility verifier, newer/older/different-libc regressions, release-Python gate, deployment owner docs. | Rebuild and independently verify the owner artifact; no global package compatibility gate is added. |
| 2026-09-27 | implemented | Applied the minimum signed-root policy to deployment CLI `0.1.1` without restoring a global key-count rule: one dedicated development artifact signer covers kit and bundle roles while channel admission and separate framework/license trust remain owner gates. | `current change`; package-pinned roots, release-channel guard, trust-separation and shared-key tests, deployment owner docs. | Production TUF ceremony and Azure convergence remain deployment-owner evidence, not package-policy work. |
| 2026-09-27 | implemented | Replaced five fixed levels and the exhaustive dependency/review/lifecycle policy with boundary-triggered minimum controls. Internal packages now need no global entry; compatibility, SBOM, lifecycle, review, readiness, and facade rules return to their actual owners. | `current change`; package assurance policy/checker, focused policy tests, owning English/Korean design, and directly affected package/repository guidance. | No package-policy implementation remains. Operational lifecycle, campaign, review, release, and deployment evidence continue under their existing owner issues. |
| 2026-09-26 | implemented | Added tiered package assurance, source-bound root test mirrors, profile-bound signed roots, linked lifecycle evidence, bounded multi-target review envelopes, optional readiness, and facade rules. | `current change`; package assurance checker and focused policy, deployment-root, review batch, workflow, architecture, documentation, and localization checks. | Retain separately authorized operational lifecycle evidence under #355 and Cost Governance campaign/review evidence under #903/#904. No Azure deployment, artifact publication, activation, or promotion is part of this change. |

### Remaining work

- [x] The signed wheelhouse builds, verifies, and installs with standard local tools. No Azure,
  runtime, lifecycle, review, compatibility, SBOM, provenance, or deployment receipt is a package
  completion criterion.
