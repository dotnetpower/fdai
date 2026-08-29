# Subscription Genesis Assurance implementation ledger

This delivery ledger tracks the controls that make a zero-to-ready run safe, complete, observable,
and recoverable.

## Implementation status

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| Foundation state and external control planes | in-progress | Existing bootstrap Terraform and protected workflows | Mechanisms exist, but secure enrollment, required state postconditions, directory automation, and state-migration receipts remain open. |
| Authority, concurrency, cancellation, and recovery | in-progress | Exact-plan claims; `fdai_deployment_cli.state`; focused journal, resume, and simulation tests | Hash-chained private journals and no-retry resume decisions are implemented locally. Subscription-wide leases, cancellation, clock assurance, quorum enforcement, and live rollback rehearsal remain open. |
| Database and semantic readiness | in-progress | Service migrations and catalog materializer | Enumerable manifests, atomic readiness markers, recovery-class checks, and independent runtime-principal readback remain open. |
| Model assurance | in-progress | Resolver and Terraform modules; deployment CLI capacity planner | Workload headroom, shared deployment aggregation, reserve, and existing allocation are local contracts. Terms, race-safe Azure reservation, quantitative probes, and live-call approval remain open. |
| Inventory completeness and progress | in-progress | Complete-generation coordinator; deployment CLI progress and closure contracts | Monotonic totals and independent full-subscription closure are tested. Durable provider events, child-source wiring, and large-scope live evidence remain open. |
| End-to-end operational closure | in-progress | Deterministic guided rehearsal, interruption tests, and successful network-isolated air-gap drill | Pre-login execution is validated locally. No governed zero-to-ready Azure receipt exists. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-08-29 | in-progress | Added the assurance contract after a 40-item adversarial review of the subscription genesis plan. | `current change`; critique resolution register, paired owner documents, and focused documentation checks | Implement the open controls and retain exact-revision new-subscription evidence. |
| 2026-08-29 | in-progress | Implemented the pre-login deployment CLI safety kernel and deterministic full-stage rehearsal. | `current change`; package tests passed 25 cases and productization tests passed 3 cases; Ruff and strict mypy passed | Harden the local kernel, then bind protected Azure and operator surfaces. |
| 2026-08-29 | implemented | Completed 75 focused hardening rounds, fixed every review finding above Low, and passed the shipped-wheel air-gap drill without network or DNS. | Campaign commits from `dd28b64d9`; final severity review reported no Medium-or-higher finding; 89 focused tests, Ruff, strict mypy, locked build, isolated install, and air-gap evidence | Collect subscription-backed state, quota, model, database, inventory, and readiness receipts after login. |
| 2026-08-29 | implemented | Extended the campaign through 93 focused hardening rounds and reconfirmed that only Low-or-lower concerns remain before Azure login. | `current change`; final severity review found no Medium-or-higher issue; 92 focused tests, Ruff, strict mypy, lock verification, source and wheel builds, and fresh plus `--skip-stage` air-gap drills passed | Collect subscription-backed state, quota, model, database, inventory, and readiness receipts after login. |
| 2026-08-29 | implemented | Completed hardening round 94 by making license-token FIFO rejection nonblocking after the stable-HEAD audit found the remaining hang risk. | `current change`; focused FIFO regression test and the final deployment CLI gate stack passed 93 tests | Collect subscription-backed state, quota, model, database, inventory, and readiness receipts after login. |
| 2026-08-29 | implemented | Completed hardening round 95 by making profile, plan-input, and journal FIFO rejection nonblocking. | `current change`; three focused FIFO regression tests and the final deployment CLI gate stack passed 96 tests | Collect subscription-backed state, quota, model, database, inventory, and readiness receipts after login. |
| 2026-08-29 | implemented | Completed hardening round 96 by bounding every deployment CLI trust-key input behind a nonblocking no-follow regular-file reader. | `current change`; focused FIFO, symlink, and oversize trust-key regression test and the final deployment CLI gate stack passed 97 tests | Complete the remaining release-script and artifact-reader hardening before login. |
| 2026-08-29 | implemented | Completed hardening round 97 by consolidating release utility key reads behind a bounded descriptor boundary with private-key ownership and mode checks. | `current change`; three focused release utility tests, Ruff, and strict mypy passed | Complete the remaining workdir, artifact-reader, journal-lock, and resumed-release hardening before login. |

### Remaining work

- [x] The pre-login safety kernel passed 97 recorded hardening rounds and the final review left only
  Low-or-lower concerns.
- [x] The local negative, interruption, artifact, packaging, and fresh plus resumed disconnected
  execution matrix passes without customer data or Azure mutation.
- [ ] Retain one governed empty-subscription run, one supported-upgrade run, one rollback/restore
  run, and one second-run no-change receipt.

## Critique resolution register

The review evaluated the revised plan rather than repeating the first eight findings. `Resolved in
design` means the normative owner now specifies the control; it does not claim implementation.

| ID | Critique | Resolution | Design state |
|----|----------|------------|--------------|
| G01 | The first runner cannot create itself. | Define the bounded local foundation executor and remote handoff. | Resolved in design |
| G02 | Local bootstrap state lacked file and lifetime controls. | Require `umask 077`, regular-file checks, strict modes, no secrets, and bounded deletion. | Resolved in design |
| G03 | "Reconstruct state" could infer ownership from names. | Require Terraform state migration plus exact lineage, address, id, serial, and count comparison. | Resolved in design |
| G04 | Random state-account names break resume. | Derive once, bind to the run, and reuse on resume. | Resolved in design |
| G05 | Blob versioning was best effort in current scripts. | Make versioning and the complete state-storage posture blocking postconditions. | Resolved in design |
| G06 | State locking and lease reachability were not verified. | Require the backend lease path and one run-level lease. | Resolved in design |
| G07 | Provider registrations were listed but not lifecycle-managed. | Add each registration to the manifest with apply and readback. | Resolved in design |
| G08 | Azure Policy, deny assignments, and management locks could invalidate adoption. | Classify them as conflicts unless separately designed and approved. | Resolved in design |
| G09 | RBAC propagation could race the next stage. | Require effective-role observation before dependent work. | Resolved in design |
| G10 | Runner registration tokens could cross Terraform state or command arguments. | Forbid those channels and require provider-hosted authorization plus protected input. | Resolved in design |
| G11 | GitHub repository settings were still manual and incomplete. | Compile idempotent settings from the manifest and report missing references without values. | Resolved in design |
| G12 | Database credentials depended on a workstation-to-GitHub secret flow. | Generate on the private host, store in the approved provider, and consume by reference. | Resolved in design |
| G13 | Entra app registrations, roles, groups, and redirect origins were outside readiness. | Add directory state to planning and independent readback. | Resolved in design |
| G14 | Artifact and tool downloads could use mutable `latest`. | Require signed or checksum-pinned tools, images, providers, and offline equivalents. | Resolved in design |
| G15 | Closed-network and sovereign-cloud behavior was underspecified. | Require cloud-specific endpoints and fail closed when parity is unavailable. | Resolved in design |
| G16 | VPN, hub, spoke, resolver, and endpoint CIDRs could overlap. | Add complete address and route overlap preflight. | Resolved in design |
| G17 | The plan had no subscription-and-environment mutual exclusion. | Add a run lease keyed by cloud, tenant, subscription, environment, and root. | Resolved in design |
| G18 | Idempotency keys lacked declared scope. | Require per-entry keys in the finite manifest under the run lease. | Resolved in design |
| G19 | Approval count ignored high-impact quorum policy. | Require at least one accountable approver and configured quorum for high-impact plans. | Resolved in design |
| G20 | Plan expiry and leases trusted an unspecified clock. | Require authenticated UTC and bounded skew. | Resolved in design |
| G21 | Cancellation semantics could interrupt an effect without closure. | Stop new work, bound in-flight closure, release leases, and use preapproved cleanup only. | Resolved in design |
| G22 | Rollback existed as text but not a prerequisite rehearsal. | Require a tested rollback and backup/restore point before destructive work. | Resolved in design |
| G23 | Cost exposure was not an approval input. | Add monthly cost, one-time validation budget, quota use, egress, and non-scale-to-zero reporting. | Resolved in design |
| G24 | PostgreSQL readiness omitted server parameters, locale, time zone, and extension versions. | Add them to the database manifest and readback gates. | Resolved in design |
| G25 | Migration ordering did not define transaction and cross-service failure behavior. | Record transaction, locks, deadlines, adoption, and rollback per migration branch. | Resolved in design |
| G26 | A migration principal could self-certify runtime access. | Require separate runtime-principal readback. | Resolved in design |
| G27 | "Every catalog entry" could activate collected reference material. | Classify runtime-required, reference-only, optional-disabled, and deployment-overlay entries. | Resolved in design |
| G28 | Default materialization could overwrite deployment-owned settings. | Require release digests and compare-and-set preservation. | Resolved in design |
| G29 | Runtime startup could observe mixed migration/catalog state. | Add one atomic readiness marker binding all heads, digests, roles, and time. | Resolved in design |
| G30 | The TPM formula ignored aggregate reuse and quota dimensions. | Add input/output/cache tokens, RPM, concurrency, SKU units, existing use, reserve, burst, and sharing rules. | Resolved in design |
| G31 | Quota could change between plan and apply. | Compare immediately before creation and force replan on drift. | Resolved in design |
| G32 | Publisher terms, content filters, responsible-AI policy, and preview limits were absent. | Add them as blocking model prerequisites. | Resolved in design |
| G33 | Live model probes incurred cost without separate authority. | Require explicit live-model approval and a cost/token budget. | Resolved in design |
| G34 | Quota increase handling could poll indefinitely or silently shrink. | Treat it as an external prerequisite with bounded status and no silent reduction. | Resolved in design |
| G35 | A full subscription could exceed memory, page, or child-resource limits. | Require staged spill, signed bounds, stable blockers, and a reviewed partition strategy. | Resolved in design |
| G36 | Count and scan denominators could diverge during resource churn. | Label estimates and use final coverage plus overlay closure for completeness. | Resolved in design |
| G37 | Private AKS and child sources could be omitted while claiming completion. | Require endpoint, certificate, audience, identity, and authorization closure per declared child source. | Resolved in design |
| G38 | Progress mixed completion percentage with duration prediction. | Separate exact work counts, estimated denominators, completion weights, and rate-qualified ETA. | Resolved in design |
| G39 | Progress events lacked tamper evidence, bounds, accessibility, and localization requirements. | Add schema version, chain digest, sequence, bounded retention/rendering, screen-reader, and locale contracts. | Resolved in design |
| G40 | Final readiness lacked operational alerts, negative tests, upgrade, teardown, and clean-subscription evidence. | Add operational closure and the complete end-to-end matrix. | Resolved in design |
