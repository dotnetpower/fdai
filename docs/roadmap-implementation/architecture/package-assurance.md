# Package Assurance implementation ledger

This delivery ledger tracks the machine policy, focused gates, and bounded runtime tooling that
implement the package assurance design.

## Implementation status

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| Minimum boundary policy | implemented | `config/package-assurance.json`; `check-package-assurance.py`; focused policy tests | Unlisted packages use the workspace default. Only published contracts, distributed artifacts, distributed evidence, artifact profiles, and constitutional runtime invariants remain in the global package gate. |
| Dependency owner binding | not-applicable | Distribution manifests, `uv.lock`, package manager, cold imports, image builds, and service dependency checks | The package gate no longer owns a second root-mirror registry or textual range-equality rule. |
| Compatibility scope | implemented | `fdai-service-contracts` compatibility manifest and owner tests; optional package rollback tests | The global minimum requires contract versioning only. N/N-1, translators, immutable schemas, and rollback windows are owner-selected when an actual consumer needs them. |
| Artifact profiles | implemented | Minimum package policy; existing connected, offline-kit, and appliance verifiers | Connected delivery requires declared closure, digest, and provenance. Offline adds a signed root and no public fallback; appliance adds a digest-pinned container. Compatibility and SBOM are recommended unless an owner promotes them into its own contract. |
| Linked lifecycle evidence | not-applicable | Capability Bundle Lifecycle owner and #355 | Lifecycle transition sets and linked receipt completeness are capability claims, not global package classification. |
| Multi-target review envelope | not-applicable | Cost Governance campaign/review workflow and focused tests | Review decomposition and independent target decisions remain owned by the protected workflow, not package assurance. |
| Optional readiness | not-applicable | ADR-0002 and capability composition tests | Availability, enablement, lifecycle, identity, and authority remain independent runtime axes. |
| Extension facades | not-applicable | Independent-service, import-boundary, and protected-path checks | Core isolation and composition ownership remain enforced without duplicating those rules in package policy. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-09-27 | implemented | Kept managed-host compatibility owner-scoped: complete deployment kits pin the exact Python ABI while interpreting glibc as a minimum same-family floor instead of a repository-wide exact-host rule. | `current change`; offline-kit compatibility verifier, newer/older/different-libc regressions, release-Python gate, deployment owner docs. | Rebuild and independently verify the owner artifact; no global package compatibility gate is added. |
| 2026-09-27 | implemented | Applied the minimum signed-root policy to deployment CLI `0.1.1` without restoring a global key-count rule: one dedicated development artifact signer covers kit and bundle roles while channel admission and separate framework/license trust remain owner gates. | `current change`; package-pinned roots, release-channel guard, trust-separation and shared-key tests, deployment owner docs. | Production TUF ceremony and Azure convergence remain deployment-owner evidence, not package-policy work. |
| 2026-09-27 | implemented | Replaced five fixed levels and the exhaustive dependency/review/lifecycle policy with boundary-triggered minimum controls. Internal packages now need no global entry; compatibility, SBOM, lifecycle, review, readiness, and facade rules return to their actual owners. | `current change`; package assurance policy/checker, focused policy tests, owning English/Korean design, and directly affected package/repository guidance. | No package-policy implementation remains. Operational lifecycle, campaign, review, release, and deployment evidence continue under their existing owner issues. |
| 2026-09-26 | implemented | Added tiered package assurance, source-bound root test mirrors, profile-bound signed roots, linked lifecycle evidence, bounded multi-target review envelopes, optional readiness, and facade rules. | `current change`; package assurance checker and focused policy, deployment-root, review batch, workflow, architecture, documentation, and localization checks. | Retain separately authorized operational lifecycle evidence under #355 and Cost Governance campaign/review evidence under #903/#904. No Azure deployment, artifact publication, activation, or promotion is part of this change. |

### Remaining work

- [x] The minimum package-policy implementation is complete in the current change. Operational
  receipts under #355, #903, and #904 remain owned by those capabilities and are not package-policy
  completion criteria.
