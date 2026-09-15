# Capability Licensing implementation ledger

This delivery ledger preserves reviewable implementation scope, append-only transitions,
and resumable work while the roadmap owner remains focused on normative design.

## Implementation status

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| Durable keyless Trial transition contract | implemented | `core/licensing/trial.py`; 12 focused Trial tests, Ruff and strict mypy pass. | Inert installation/deployment-bound record with immutable activation, exact 30-day UTC expiry, revision advancement, strict decoding and sticky clock-regression denial. It is not wired into entitlement and grants no capability access. |
| Keyless Trial persistent activation and execution enforcement | in-progress | Accepted owner contract; existing signed-token runtime remains unchanged. | Atomic initialization, authenticated persistence, cross-replica observations, all-path runtime enforcement, and installation-time binding remain open. |
| Canonical signed-token and entitlement domain | implemented | `services/core-control-plane/src/fdai/core/licensing/`; `services/core-control-plane/tests/core/licensing/test_licensing.py`; deployment CLI license tests | Strict canonical parsing, fixed expected-distribution binding, a consumer-enforced maximum 30-day UTC window, read-only degradation, issuer-workstation status, and current-time reevaluation pass focused tests. |
| Ed25519 trust and issuer custody | implemented | `services/core-control-plane/src/fdai/delivery/trust/`; packaged `license-signing-key.pub`; `scripts/deployment/release/issue-license.py`; focused trust and issuer tests | The dedicated owner-only private key remains ignored under `secrets/`; the integrity key is not reused. The issuer defaults to 30 days and rejects more than 30 days. |
| Runtime Trial and local issuer binding | implemented | `services/core-control-plane/src/fdai/runtime/licensing.py`; runtime licensing and bootstrap tests | The shipped runtime requires a token and fixes `fdai-upstream` as its expected identity; downstream composition can supply another fixed identity. Only a local Git checkout with the matching private key receives the issuer exception; deployed venue never reads it. |
| Shared Thor execution ceiling | implemented | `services/core-control-plane/src/fdai/core/executor/licensing_gate.py`; `test_licensing_gate.py`; `test_thor_execution_port.py` | PR-native, direct-API, and tool-call paths share one current-time gate across normal dispatch and human-approval resume. Denials stay terminal and secret-free when audit persistence fails, and mark that failure in the returned context. |
| Azure token delivery contract | implemented | independent Core Terraform `license` input; `azd-up.sh`; `test_capability_license_binding.py`; `test_contributor_deployment.py`; Terraform validation | Token values move file-to-Key-Vault and never enter Terraform. Each token uses its full-digest-derived secret name, interrupted tfvars generation is resumable, and the public path auto-issues only on the issuer workstation; otherwise it deploys Trial. No live Azure receipt exists. |
| Operator status and proactive renewal warning | not-started | Owner design only | Startup and denied-action logs exist, but no authenticated status projection, Console badge, or pre-expiry notification is implemented. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-09-14 | in-progress | Added the inert durable Trial record and transition model without weakening existing signed-token validation or automatically opening runtime capabilities. | Current change; 12 focused tests cover exact expiry, restart, clock rollback, malformed records and UTC bounds; Ruff and strict mypy pass. | Persist and independently re-read the record, bind every runtime path, add concurrency and restart acceptance, then implement separately versioned full entitlement activation. |
| 2026-09-09 | implemented | Moved Thor license-wrapper construction into the runtime licensing owner without changing the dynamic entitlement decision or any execution surface. This restored the runtime control-loop module to its enforced 800-line ceiling. | `current change`; `runtime/{licensing.py,control_loop.py}`; focused runtime licensing tests; strict mypy and file-size checks. | Retain the live Azure lifecycle evidence and projection work listed below. |
| 2026-09-09 | implemented | Completed 17 independent hardening rounds and corrected six Medium defects: cross-distribution acceptance, missing downstream distribution composition, issuer-only 30-day enforcement, active-secret overwrite during renewal, denial-audit exception escape, and stale tfvars recovery. Full token digests now isolate renewal secrets. No verified finding above Low remains. | [Issue #521](https://github.com/dotnetpower/fdai/issues/521); `current change`; combined licensing, all-path executor, trust, runtime, issuer, deployment CLI, contributor, and Terraform-contract regression passed 228 cases; the post-review contributor regression passed 9 cases; air-gap productization passed 6 cases; Ruff, strict mypy over 18 source files, shell syntax, both Core Terraform validations, and Core wheel public-key packaging passed. | Retain live Azure lifecycle evidence. Low limitations remain for wall-clock rollback, global mutation-capability granularity, copyable file-key custody, and absent proactive status projection. |
| 2026-09-09 | implemented | Activated required-license Trial behavior, added the cryptographically verified local issuer exception, capped repository issuance at 30 days, gated every shared Thor path at current time, and added file-to-Key-Vault public deployment delivery. | `current change`; focused licensing/runtime checks passed 82 cases; focused deployment/issuer checks passed 18 cases; Ruff, strict mypy, shell syntax, both Core Terraform validations, real local keypair smoke, and Core wheel public-key packaging passed. | Retain live Trial, active, expiry, and renewal evidence; add authenticated status and warning projection; bind protected deployment renewal. |
| 2026-08-24 | not-started | Adopted the delegated ledger; earlier provenance was not reconstructed. | current change; `docs/roadmap/fork-and-sequencing/capability-licensing.md`. | Assess bounded source and test evidence before raising any scope state. |

### Remaining work

- [ ] Add migration-owned atomic Trial initialization and observation with exact installation binding,
	compare-and-set revisions, missing-record denial, and concurrent replica/restart tests.
- [ ] Bind Trial resolution immediately before each existing execution gate without changing approval,
	promotion, RBAC, recovery or audit authority; prove expired Trial cannot grant new acting work.
- [ ] Deliver and read back initial Trial state through the source deployment scripts without a publisher
	key; retain first-use and expired-run evidence before calling keyless Trial operational.
- [ ] Retain one governed Azure sequence proving keyless Trial, active bound token, post-`not_after` denial without restart, renewed-token revision, and unchanged promotion/RBAC/risk/approval ceilings.
- [ ] Expose authenticated, secret-free license status and pre-expiry warning projections, with Console localization and no token or key material.
- [ ] Add protected-workflow issuance and renewal automation that verifies and materializes the existing versionless Key Vault license object, then retain an exact-plan apply receipt.
- [ ] Evaluate hardware-backed issuer custody if physical-device binding is required; the current file key proves possession and can be copied.
- [ ] Define and test a deterministic ActionType-to-license-capability mapping before offering selective acting licenses; the current Thor ceiling intentionally requires the single `operations.typed-mutation` capability.
- [ ] Add a trusted-time or rollback-detection design and a falsifying clock-regression test if the deployed threat model must resist host wall-clock rollback.
