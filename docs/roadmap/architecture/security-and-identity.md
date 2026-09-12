---
title: Security and Identity
---
# Security and Identity

Autonomy requires execution privileges, which makes identity and safety the highest-risk surface. Least privilege and reversibility are non-negotiable. This file is authoritative for
the security model; it complements the control loop and safety invariants in
[architecture.instructions.md](../../../.github/instructions/architecture.instructions.md),
the topology in
[app-shape.instructions.md](../../../.github/instructions/app-shape.instructions.md),
and the code/CI gates in
[coding-conventions.instructions.md](../../../.github/instructions/coding-conventions.instructions.md).

## Implementation status

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| Workload identities and approval/execution separation | validated | `config/independent-service-live-evidence-manifest.json`; `infra/services/`; `shared/providers/workload_identity.py`; SD-08 and IS-09 evidence | Five-service deployment evidence proves distinct identities and makes the isolated Executor the sole eligible effect holder after cutover. |
| Executor safeguards and independent effect closure | in-progress | `packages/service-contracts/src/fdai_service_contracts/execution_safeguards.py`; `core/executor/{safeguards,safeguard_proofs,safeguard_lifecycle*,safeguard_hold_fenced_port,safeguard_pre_bundle,*_safeguard_dispatch,lock,lock_continuity,idempotency_reservation*,audit_intent,target_dispatch_fence*,safeguard_dispatch*,safeguard_evidence_lifecycle,post_release_closure*}.py`; isolated-Executor bundle resolver and validation; focused safeguard, producer, workflow, service-boundary, persistence, lifecycle, and migration tests | Core PR-native, PR-manual, direct-API, and tool-call producers now use one production coordinator, bind workflow approval to an immutable pre-bundle commitment, retain the finalized digest, and fail closed without durable evidence. The isolated Executor resolves and independently revalidates the bundle before effects. Governed cross-path effect evidence under #633 remains open. |
| Global kill switch and break-glass controls | implemented | `core/rbac/kill_switch_command.py`; `core/control_loop/_execution.py`; `core/conversation/_write_break_glass_tool.py`; focused RBAC and control-loop tests | Revision-safe state, fail-closed refresh, authority ceiling, time-bound activation, audit, and paging paths exist. A retained operational drill remains open. |
| Automation-hold recovery approval hardening | implemented | `core/workflow/{recovery_admission,automation_hold,recovery_coordinator*,recovery_effect_ingress,compensation}.py`; `delivery/persistence/{workflow_recovery,workflow_approval}.py`; `delivery/workflow_recovery_observation_handler.py`; `core/executor/safeguard_lifecycle*.py`; guarded in-memory and PostgreSQL state adapters; [Process Automation implementation status](../../roadmap-implementation/decisioning/process-automation.md#implementation-status); issues `#622`, `#630`, `#640`, `#652`, `#656`, and `#658` | Production compensation now closes a hold only through the guarded release, and the legacy verified-recovery call is removed. The complete admission gates every provider dispatch, one exclusive compare-and-set claim owns that dispatch, and the executor fence reads its expected lineage from the dispatch authorization bound to that exact Process step. The RiskGate hold exception reads the same proof instead of a step name, so only a canonical `recover_<attempt>` step with a current hold-scoped authorization crosses the hold. Independent effect observations enter through one versioned observer-path ingress that authenticates the observer principal, refuses executor-authored, provider-authored, synthetic, unfinal, uncontained, and stale evidence, and stays duplicate- and reorder-safe. That ingress reads only the Heimdall-owned `object.recovery-effect-observation` topic and authorizes only `Heimdall`, so an external observation crosses Huginn normalization and the Heimdall relay before it can reach the intake and the sole privileged executor owns no topic on the path. Recovery approval requests, finalized safeguard bundle retention, and independent effect observation all have production writers. FDAI-CONST-009 remains implemented. |
| Data protection and privacy evidence | in-progress | [Data Governance implementation status](data-governance.md#implementation-status); redaction and retention paths cited there; issue `#371` | Major boundaries now implement shared minimization and redaction, but deployment privacy approval and retained production evidence remain open. |
| Standing human authorization (A3-E) | in-progress | `config/constitution-traceability.json` requirement `FDAI-CONST-008`; [Escalation and Standing Authority](../decisioning/escalation-and-standing-authority.md); `core/standing_authority/{lease,provider_eligibility,promotion_candidate*,shadow_cohort_runner,effect_shadow_reversion,provider_acceptance*}.py`; `delivery/azure/{vm_start_shadow_fence,vm_power_state,vm_power_state_observation}.py`; completed issues `#331`, `#621`, `#629`, and `#631`; issue `#632` | The existing strict lease contract is unchanged. The new process-local acceptance model records before I/O, blocks every duplicate or ambiguous attempt, and remains `production_eligible=false`; it is not distributed atomicity or effect success. All A3-E contracts remain unwired and the selected ActionType remains ineligible. Provider-commit-fence eligibility is now derived from an empty adapter registry rather than declared by a candidate author, so every shipped ActionType classifies as `INELIGIBLE_CAPABILITY`. Zero eligible providers exist, and the #632 governed runtime cohort, independent review, and current human approval remain open. |
### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-09-13 | in-progress | Removed the caller-declared A3-E provider-eligibility claim surface. `provider_eligibility.py` derives commit-fence capability from an explicit adapter registry that is empty, the promotion-candidate builder no longer accepts an ineligible ActionType set, and the record constructor rejects a hand-declared partition. Every shipped ActionType therefore derives `INELIGIBLE_CAPABILITY` and every real candidate denies at creation. The module is pure, unwired, and grants no execution or promotion authority. | `current change`; `core/standing_authority/provider_eligibility.py`; `tests/core/standing_authority/test_provider_eligibility.py`; 242 focused standing-authority tests passed (18 new), including a catalog-wide check over all 49 shipped ActionTypes and static proofs that no authority path imports the module by submodule path or package re-export and no shipped module mutates the registry; an independent critique found and fixed a false-negative import guard plus a pre-existing vacuous scan root; Ruff, format, and strict mypy passed. | Zero eligible providers exist. A durable provider boundary with atomic lease and fencing-generation validation at effect commit, the #632 governed runtime cohort, independent review, explicit current human approval, and retained effect observations all remain open. |
| 2026-09-12 | in-progress | Added a process-local provider-acceptance ordering model with content-addressed identity, target-keyed one-shot preparation, exact readback, conservative ambiguity, cancellation handling, and no resubmission. The model explicitly grants no authority and is not a production provider fence. | `current change`; `provider_acceptance*.py`; focused deterministic concurrency tests. | Keep the strict lease requirement and ineligible outcome until a durable implementation and provider correlation are independently reviewed. |
| 2026-09-12 | in-progress | Added shadow-only one-VM provider-fence, independent power-state observation, and fail-closed shadow-reversion contracts for `ops.start-vm@1.0.0`. Every output remains content-addressed and no-authority; no provider mutation, registry write, runtime binding, or recovery dispatch was added. | `current change`; new standing-authority and Azure delivery modules; focused tests passed. | Resolve provider atomicity, add the reviewed semantic ActionType declaration, and retain governed runtime evidence before any A3-E eligibility claim. |
| 2026-09-11 | implemented | Bound recovery effect evidence to a composition-supplied trusted observer identity set in addition to the Heimdall-owned topic and executor/provider separation. A payload cannot nominate an untrusted observer that can release a hold. | `current change`; recovery observation ingress and production writer tests. | Retain governed runtime evidence on the exact deployed observer identity. |
| 2026-09-11 | implemented | Moved the independent recovery post-effect observation onto an accountable agent boundary. The intake previously subscribed the shared `object.event` ingress topic through a private consumer group and authorized `Huginn` as a producing principal, so a fully-formed payload published onto that topic reached the durable intake with no observer agent in the path. Heimdall, already the terminal effect observer, now owns the `RecoveryEffectObservation` object type and its derived `object.recovery-effect-observation` topic; an external observation enters only through `Huginn.ingest`, and Heimdall proves Huginn normalized it before republishing an allowlisted bounded record onto the topic it owns. The intake reads only that topic and authorizes only `Heimdall`. The relay proves provenance and shape, verifies no effect, and grants no authority, and no judge, approver, or executor authority changed. | `current change`; `pantheon.py`; `topics.py`; `heimdall.py`; `heimdall_huginn_projection.py`; `runtime_subscriptions.py`; `recovery_effect_ingress.py`; `workflow_recovery_observation_handler.py`; routing and production recovery-writer suites now drive the real Huginn ingest, Heimdall relay, pantheon bus, and dedicated observer subscription chain, with a negative control proving the intake never reads the shared ingress topic; 5,298 focused agent, workflow, delivery, and runtime checks passed with 3 database-gated skips; Ruff and strict mypy over 623 source files. | Live provider observation evidence still arrives with the deployment work tracked in `#633`. |
| 2026-09-11 | implemented | Closed the final reachability findings on the held-recovery path. The RiskGate hold exception now requires a current hold-scoped dispatch authorization for the exact target, Process, canonical `recover_<attempt>` step, and active hold revision instead of a `compensate_` step-name prefix, so a generic `recover_` string, a cross-Process lineage, a superseded revision, and an unreadable authorization all stay denied. The production compensation resume caller heals a released-but-unterminalized recovery before its own hold check, so a crashed replica's Process and Saga delivery are repaired after an arbitrary delay. Independent post-effect observations arrive through one versioned typed observer-path ingress that authenticates the observer principal, validates authority class, attempt binding, provider receipt, effect and envelope digests, evidence window, finality, and containment, and persists through `record_independent_observation`; a missing observer or intake binding is a named `observer_unavailable` readiness outcome instead of a silent unverified effect. | `current change`; `automation_hold.py`; `recovery_effect_ingress.py`; `compensation.py`; `recovery_coordinator.py`; `workflow_recovery.py`; `workflow_recovery_observation_handler.py`; `runtime_subscriptions.py`; Workflow, executor, control-loop, agent, delivery, and runtime focused checks passed 5,934 cases with 3 database-gated skips; Ruff and strict mypy passed over 2,428 sources. | Live provider observation evidence still arrives with the deployment work tracked in `#633`. |
| 2026-09-11 | implemented | Hardened the production held-recovery path after an independent review. No provider dispatch happens before the complete recovery admission proves current approval, quorum, absence of rejection, expiry, no-self-approval, executor separation, and a current decision-evidence admission. The pre-dispatch claim became an exclusive compare-and-set in-flight claim with a lease, so a concurrent recovery invokes the provider exactly once and the losing caller stays in doubt without reissuing a hold. The executor fence now takes its expected lineage from the durable dispatch authorization bound to that exact Process step rather than the current hold record, so a hold reissued, released, or re-released after that authorization denies dispatch, and finalized safeguard bundle retention requires an execution that named its own provider invocation and returned a lifecycle-bound receipt. Crash healing validates the persisted consumed claim and release binding and terminalizes at the consumption instant, while mismatched or revoked lineage still fails closed. The recovery approval request, finalized safeguard bundle retention, and independent effect observation now have production writers, so the path completes without seeded state and a missing writer stays a visible fail-closed state. | `current change`; `recovery_coordinator.py`; `automation_hold.py`; `workflow_recovery.py`; `safeguard_lifecycle_coordinator.py`; `control_loop_support.py`; 1,494 focused workflow, executor, runtime, persistence, and contract checks passed; Ruff and strict mypy over 2,426 source files. | Complete cross-path governed safeguard evidence under issue `#633`. |
| 2026-09-11 | implemented | Replaced the legacy verified-recovery hold release with the durable production recovery coordinator. A held Process now needs a distinct recovery attempt, separate immutable human approval, a finalized safeguard bundle, one fenced exactly-once claim, an independent authoritative post-effect observation, and consumption of the exact current successful completion claim through the approval-guarded release, and the executor rechecks hold state inside its own logical-target lock immediately before provider invocation. | `current change`; `recovery_coordinator.py`; `workflow_recovery.py`; `safeguard_lifecycle_coordinator.py`; 1377 focused workflow, executor, and runtime checks passed; Ruff and strict mypy over 2426 files. | Complete cross-path governed safeguard evidence under issue `#633`. |
| 2026-09-11 | implemented | Wired every Core execution path and Workflow action through the production safeguard coordinator. The runtime acquires one evidenced target lock, reserves idempotency, reads back audit intent, finalizes and persists the shared bundle, validates dispatch start, records terminal continuity, and closes or quarantines atomically. Isolated execution resolves the exact PostgreSQL bundle and revalidates it before dispatch. | `current change`; production coordinator, path adapters, runtime composition, isolated bundle resolver, migration dependency, and focused production wiring tests; 1,137 regression tests passed; final independent review found no Medium-or-higher issue. | Retain governed cross-path safeguard and independent effect evidence under #633. |
| 2026-09-11 | implemented | Made completion outbox entries verify their immutable content address when reconstructed. A forged entry can no longer enter Process or Saga delivery replay. | `current change`; `recovery_terminalization.py`; focused outbox tamper test. | Route production compensation through the guarded release primitive under #630. |
| 2026-09-11 | implemented | Made held-recovery approval and safeguard evidence verify their own content addresses when reconstructed from durable state. Tampered provenance is rejected before a recovery claim can consume it. | `current change`; `recovery_attempt.py`; focused tamper tests. | Route production compensation through the guarded release primitive under #630. |
| 2026-09-11 | implemented | Bound held-recovery terminalization to the current Process revision, exact effect claim and generation, release receipt, completion digest, and absence of a prior terminal commit. Any mismatch now blocks the transition. | `current change`; `recovery_terminalization.py`; focused terminal precondition tests passed 27 cases. | Route production compensation through the guarded release primitive under #630. |
| 2026-09-10 | implemented | Added a deterministic local synthetic A3-E shadow cohort with an exact manifest, complete denominator accounting, content-bound corpus and receipt, fixed local timeouts, registry before/after integrity, and a symlink-safe explicit artifact writer. It records development evidence only and grants no execution or promotion authority. | `current change`; `core/standing_authority/shadow_cohort_runner.py`; 174 focused standing-authority tests passed before the final two regression tests were rerun in a 40-test cohort slice; Ruff and strict mypy passed; independent TOCTOU and corpus-binding findings were fixed and re-review reached no Medium-or-higher findings. | #631 has no local implementation residual. #632 still requires separately authorized governed runtime evidence and independent promotion review. |
| 2026-09-10 | implemented | Added an inert, shadow-only A3-E promotion-candidate lifecycle. Exact authorization and lease revisions, reviewer allowlists, evidence requirements, authenticated creator/reviewer separation, content-bound revocation, deterministic denial, two-phase audit, append-only replay, and static non-import checks grant no execution or promotion authority and never mutate the authoritative registry. | `current change`; `core/standing_authority/promotion_candidate*.py`; 52 focused tests passed; Ruff, format, strict mypy, and all file-size bounds passed; independent critique findings for reviewer authorization and revocation digest binding were fixed, and re-review reached no Medium-or-higher findings. | #629 has no local implementation residual. Retain the bounded #631 shadow cohort before any separately authorized #632 promotion. |
| 2026-09-10 | implemented | Added an inert effect-spanning A3-E lease and provider commit-fence contract. Exact lifecycle revision, action, target, executor identity, source revision, bounded validity, fencing generation, stable provider idempotency, checkpoints, terminal release, and authoritative restart reconciliation remain no-authority records. Providers without atomic lease validation, fencing, idempotency, and status reconciliation stay ineligible, and no production authority path imports the lease. | `current change`; `core/standing_authority/lease.py`; `shared/providers/standing_authority.py`; 82 focused tests passed; Ruff, format, and strict mypy passed; the corrected static gate scanned 208 authority-path files; independent critique reached no Medium-or-higher findings. | #621 has no local implementation residual. Keep the lease inert through #629 review and #631 shadow evidence before separately authorized #632 promotion. |
| 2026-09-10 | implemented | Added exact post-release closure plans, strict records, and a Core-owned PostgreSQL transaction. Each stable reservation attempt locks the pre-release, reservation, and target-fence predecessors; atomically writes terminal or quarantine reservation state, append-only audit closure, current orchestration state, deterministic outbox, and exact fence state; and resolves quarantine only from exact-generation authoritative status or independent-verifier evidence. Duplicate replay verifies rather than repairs missing terminal evidence, and independent effect state stays pending. | `current change`; `post_release_closure*.py`; `postgres_post_release_closure.py`; Core service migration and ownership manifest; focused model, persistence, and migration suites passed; fresh pgvector/PostgreSQL 16 migration plus parallel closure, restart readback, quarantine reconciliation, and outbox-deduplication scenario passed; Ruff and strict mypy passed. | #694 has no local implementation residual. Implement the shared evidence lifecycle orchestrator under #681. |
| 2026-09-11 | implemented | Added the provider-neutral Core safeguard evidence lifecycle orchestrator. Enforces exact phase order: acquire lock, reserve, audit, fence, bundle, prepare, in-flight, dispatch (same lock handle), observation, pre-release continuity checkpoint, release-pending fence. Fail-closed prior-phase validation rejects wrong reservation state, wrong fence state, inactive lock, and authority-bearing bundles. Evidence conflict and duplicates stop before dispatch. Unknown sink, failed transport, or unproven continuity quarantine the target. Cancellation resolves the fence without dispatch. The result carries the finalized bundle digest and terminal evidence without granting approval, execution, promotion, sink-commit, or effect-verification authority. | `current change`; `safeguard_evidence_lifecycle.py`; `test_safeguard_evidence_lifecycle.py`; 21 focused tests covering complete order, every failure boundary, cancellation, quarantine paths, contention, evidence conflict, authority rejection, and terminal-shape validation; Ruff, format, and strict mypy passed. | #681 Core orchestrator is implemented. #694 post-release atomic closure store integration remains open. Real producers, isolated-Executor validation, and governed effect evidence remain under #627. |
| 2026-09-10 | implemented | Added a monotonic safeguard dispatch evidence lifecycle that persists the exact bundle, dispatch start, transport and authoritative-sink observation, and fresh pre-release lock-continuity checkpoint with strict codecs, compare-and-set storage, restart recovery, and no authority or effect-verification claim. | `current change`; `safeguard_dispatch*.py`; `postgres_safeguard_dispatch.py`; service migration; 86 focused model, persistence, and migration tests passed, one live PostgreSQL test skipped because its DSN was not configured; Ruff passed. | #693 has no local implementation residual. Complete post-release atomic closure under #694, then shared orchestration under #681. |
| 2026-09-10 | implemented | Added a target-unique, generation-fenced dispatch record immediately after reservation and before audit, bundle, or sink work. Exact-record CAS and readback preserve audit/bundle evidence, block every target mutation until resolution, retain quarantine across release, require fresh reconciliation evidence, and allow a new generation only after a later acquisition. | `current change`; `target_dispatch_fence.py`; strict codec; PostgreSQL store and migration; 18 local model/persistence checks, 64 migration inventory checks, and one live PostgreSQL contention/restart scenario passed; Ruff and strict mypy passed; independent critique reached no Medium-or-higher findings. | #692 has no residual work. Persist bundle, dispatch, and pre-release checkpoints under #693, then complete post-release closure under #694 before #681 orchestration. |
| 2026-09-10 | implemented | Implemented the production PostgreSQL evidenced resource lock. One dedicated session atomically acquires the advisory key and captures database/backend identity; every assessment rechecks the exact session and key with PostgreSQL time. Loss, substitution, malformed evidence, or cancellation makes the handle inert and records unknown release without unlocking another session. Checked unlock produces terminal no-authority release evidence, and only the quarantined-reconciliation strategy is production eligible. | `current change`; `postgres_resource_lock.py`; `resource_lock.py`; focused lock tests; 80 local checks and one live PostgreSQL session/readback/release/reacquisition scenario passed; Ruff and strict mypy passed; independent critique reached no Medium-or-higher findings. | #678 has no residual work. Implement the shared evidence lifecycle orchestrator under #681. |
| 2026-09-10 | implemented | Implemented the migration-owned append-only PostgreSQL audit-intent store. Atomic insert commits before a separate exact readback transaction; only matching digest and canonical content within the reservation lease produces appended or duplicate-same evidence, while drift returns conflict without a receipt. | `current change`; `postgres_audit_intent.py`; service migration and ownership manifest; 10 local contract/adapter checks, 64 migration inventory checks, and one live PostgreSQL concurrent append/restart scenario passed; Ruff and strict mypy passed; independent critique reached no Medium-or-higher findings. | #680 has no residual work. Complete the PostgreSQL evidenced lock provider under #678 before starting #681 orchestration. |
| 2026-09-10 | implemented | Implemented the dedicated migration-owned PostgreSQL reservation table and adapter. Atomic insert distinguishes the winner from duplicate-same and conflict; full-record compare-and-set and `SELECT ... FOR UPDATE` readback bind exact predecessor state. Runtime DDL and shared-keyspace fallback are absent. | `current change`; `postgres_idempotency_reservation.py`; service migration and ownership manifest; 23 local model/adapter checks, 64 migration inventory checks, and one live PostgreSQL race/restart/stale-CAS scenario passed; Ruff and strict mypy passed; independent critique reached no Medium-or-higher findings. | #679 has no residual work. Implement the audit-intent store under #680 and the evidenced lock provider under #678. |
| 2026-09-10 | implemented | Split the crash-safe reservation model, durable JSON codec, and lifecycle transitions behind the existing public facade. Serialization and transition semantics are unchanged; exact nested fields, digests, no-authority flags, state, chronology, ambiguous-outcome quarantine, and authoritative recovery evidence now have focused branch coverage. | `current change`; `core/executor/idempotency_reservation*.py`; `test_idempotency_reservation.py`; 55 focused tests and 97.36% combined branch coverage; Ruff and strict mypy passed. | No residual structural or coverage work remains in this batch. Shared evidence lifecycle orchestration remains under #681. |
| 2026-09-10 | in-progress | Added the exact durable JSON codec required by #679. Serialization emits enum values and UTC timestamps; parsing requires exact nested key sets and reconstructs the acquisition, identity, and record while rerunning every digest, no-authority, state, and chronology invariant. | `current change`; `core/executor/idempotency_reservation.py`; `test_idempotency_reservation.py`; 18 focused tests, Ruff, and strict mypy passed; independent critique reached no Medium-or-higher findings. | Implement the PostgreSQL table, atomic reserve/CAS/readback adapter, race and restart tests, and migration under #679. |
| 2026-09-10 | in-progress | Split the durable production implementation into a PostgreSQL evidenced lock provider, reservation store, audit-intent store, and shared lifecycle orchestrator. The graph keeps point-in-time lock readback, durable reservation, authoritative audit persistence, and execution ordering in separate accountable packages. | `current change`; issues `#678`, `#679`, `#680`, and `#681`; parent `#627`. | Complete #678 and #679, then #680, then #681 before creating per-path PR, direct-API, tool-call, and workflow integration packages. |
| 2026-09-10 | implemented | Defined a pre-effect audit intent that embeds the exact durable reservation transition receipt and a candidate-bound append/readback result. Success evidence requires persistence, exact authoritative readback, and timestamps after reservation readback but before lease expiry; API acknowledgement or a caller-computed digest is insufficient. | `current change`; `core/executor/audit_intent.py`; `test_audit_intent.py`; 7 focused tests, Ruff, and strict mypy passed; independent critique reached no Medium-or-higher findings. | #672 contract work is complete. Implement the durable audit store and restart/partial-write evidence under the future #627 provider package. |
| 2026-09-10 | implemented | Defined the crash-safe reservation identity, monotonic state machine, atomic reserve result, exact-predecessor CAS/readback receipt, and provider seam. An expired in-flight attempt becomes durable unknown-outcome quarantine, abandonment requires authoritative proof that dispatch never began, and recovery requires a later lock acquisition and higher attempt after proven non-acceptance. | `current change`; `core/executor/idempotency_reservation.py`; `test_idempotency_reservation.py`; 16 focused tests, Ruff, and strict mypy passed; independent critique reached no Medium-or-higher findings. | #671 contract work is complete. Implement the durable provider with restart and race evidence under the future #627 provider package; define authoritative audit-intent evidence next under #672. |
| 2026-09-10 | implemented | Defined reviewed ownership-through-commit strategies and a terminal no-authority receipt that embeds the exact policy, acquisition, and current ownership assessment. Dispatch, sink commit, and independent effect verification stay separate; ambiguous dispatch, unknown commit, and lost or unknown release require quarantine, and only authoritative irrevocable non-acceptance can clear it. | `current change`; `core/executor/lock_continuity.py`; `test_lock_continuity.py`; 17 focused tests, Ruff, and strict mypy passed; independent critique reached no Medium-or-higher findings. | #670 has no residual work. Define crash-safe reservation under #671 before implementing the PostgreSQL evidence provider and shared producer orchestration. |
| 2026-09-10 | implemented | Implemented the local test-only evidenced resource lock with a unique per-acquisition identity, exact registry holder readback, adapter-owned UTC time, bounded assessment validity, request-bound no-authority receipts, and cancellation-safe deactivation before release. An escaped old handle stays ineligible during a later acquisition, and the adapter cannot satisfy production readiness. | `current change`; `core/executor/lock.py`; `shared/providers/resource_lock.py`; `test_lock.py`; `test_resource_lock_receipt.py`; 65 focused tests, Ruff, and strict mypy passed; independent critique reached no Medium-or-higher findings. | No residual work remains for #674. Define production ownership-through-commit under #670 before implementing the PostgreSQL evidence provider. |
| 2026-09-10 | implemented | Completed #669 as the contract and migration-inventory boundary. The request/receipt binding, TTL, inert handle lifecycle, explicit production seam, and single-owner target state are now defined without claiming provider or path integration. | `current change`; commits `f25fdbe63` and `301c7a36b`; issue `#669`; 67 focused tests and zero Medium-or-higher independent critique findings. | Implement the local test-only provider under #674. Keep production provider and path migration under #627 behind #670-#672. |
| 2026-09-10 | in-progress | Added the canonical no-authority acquisition request, exact request-bound acquisition receipt, five-second maximum live-assessment validity, explicit `EvidenceResourceLock` and held-handle protocols, an inert-after-exit lifecycle guard, and a production resolver that never adapts or falls back to the legacy lock seam. The canonical executor lock-key helper now delegates to the shared provider contract. | `current change`; `shared/providers/resource_lock.py`; `core/executor/safeguards.py`; `test_resource_lock_receipt.py`; 67 combined resource-lock and finalizer tests, Ruff, and strict mypy passed; independent critique reached no Medium-or-higher findings. | Complete #669 by applying the single-owner inventory to composition, proving every mutation path rejects the legacy seam, and retaining the local provider only for non-production evidence. |
| 2026-09-10 | in-progress | Split #627 producer wiring into dependency-ordered lifecycle/migration, ownership-through-commit, crash-safe reservation, and authoritative audit-intent evidence blockers. The corrected graph prohibits caller-selected assessment time, legacy production fallback, duplicate target acquisition, unsafe redispatch from an expired in-flight reservation, and success claims from dispatch or sink commit. | `current change`; issues `#669`, `#670`, `#671`, and `#672`; independent design critique reached no Medium-or-higher findings. | Complete #669, then #670, #671, and #672 in dependency order before creating local/PostgreSQL provider and per-path producer integration children. |
| 2026-09-10 | implemented | Required the pure safeguard finalizer to consume current provider-attested lock ownership at the bundle recording time. The finalizer binds the exact historical receipt to the action, target, source revision, causal timeline, configured verifier and trust anchor, and emits a composite lock proof digest that preserves both the operation statement and live assessment for replay. | `current change`; `core/executor/safeguard_proofs.py`; `shared/providers/resource_lock.py`; `test_safeguard_proofs.py`; `test_resource_lock_receipt.py`; 52 combined focused tests, Ruff, and strict mypy passed; independent critique reached no Medium-or-higher findings. | #660 has no residual work. Produce the validated evidence from real Core and workflow execution paths under #627. |
| 2026-09-10 | implemented | Added no-authority resource-lock evidence that embeds the exact validated historical acquisition receipt in a current provider-attested fence/session ownership assessment. Canonical digests, exact runtime types, UTC time bounds, lease expiry, trust-anchor mismatch, and independently observed lock loss fail closed. | `current change`; `shared/providers/resource_lock.py`; `test_resource_lock_receipt.py`; 40 focused tests, Ruff, and strict mypy passed; independent critique reached no Medium-or-higher findings. | Keep #660 open until the safeguard finalizer requires this exact current assessment and rejects stale, lost, expired, wrong-verifier, wrong-trust-anchor, and fence-mismatched evidence. |
| 2026-09-10 | implemented | Added a pure Core finalizer that fixes the full-action digest at pre-dispatch evaluation, validates context-bound lock, durable idempotency-reservation, and persisted audit-intent proofs, and emits the #620 no-authority bundle. | `current change`; `safeguards.py`; `safeguard_proofs.py`; focused checks passed 63 cases; Ruff and strict mypy passed. | Connect real executor operation receipts and workflow pre-bundle commitments under #627. |
| 2026-09-10 | in-progress | Replaced the unsafe same-proposal recovery plan with bounded owners for action-bound approved dispatch, authoritative effect evidence, and claim-fenced terminalization. | `current change`; issues `#652`, `#656`, and `#658`; parent `#630`. | Complete those packages in order, then finish #640. |
| 2026-09-10 | in-progress | Added an approval-guarded atomic hold-release primitive that consumes one admitted recovery, increments the fence, and stores a content-addressed no-authority receipt with terminal audit. | `current change`; guarded hold and state-store code; 63 focused passing checks; Ruff and strict mypy. | Wire production compensation to the primitive under #630, then complete final execution-path fencing under #640. |
| 2026-09-10 | in-progress | Separated atomic hold release from final forward-dispatch fencing to preserve executor-owned logical-target lock boundaries and remove a dependency cycle. | `current change`; issues `#630` and `#640`. | Complete `#630`, then integrate its action-bound release receipt under `#640` after `#627` and `#628`. |
| 2026-09-10 | implemented | Added future-request-time and process and approval-revision digest substitution regressions before closing the pure recovery-admission boundary. | `current change`; `test_recovery_admission.py`; 21 focused recovery-admission tests and 46 combined approval, recovery, and compensation checks passed. | No residual work remains for issue `#622`; complete atomic admission consumption and exact hold release under issue `#630`. |
| 2026-09-10 | implemented | Bound separately approved recovery to the existing workflow approval and decision-evidence admission contracts without releasing a hold or granting authority. | `current change`; `recovery_admission.py`; `test_recovery_admission.py`; 45 focused passing checks; Ruff and strict mypy. | Complete atomic admission consumption and exact hold release under issue `#630`. |
| 2026-09-10 | implemented | Added the provider-neutral seven-safeguard proof bundle as an immutable content-addressed wire contract with canonical proof order and false-only authority and effect flags. Service-owned mismatch, freshness, dispatch, and effect decisions remain outside the package. | `current change`; `execution_safeguards.py`; `schemas/execution-safeguard-proof-bundle/1.0.0.json`; `test_execution_safeguards.py`; 4 focused tests, Ruff, and strict mypy passed. | Emit and validate the bundle under issues `#627` and `#628`, then retain the separately authorized governed evidence under issue `#633`. |
| 2026-09-10 | in-progress | Reconciled the P0 execution-safety residual graph. Completed issue `#331` now supplies A3-E lifecycle evidence, while provider-neutral safeguard, workflow, isolated-Executor, effect-spanning lease, inert promotion, local shadow cohort, governed promotion, admitted recovery, and cross-path effect evidence have separate bounded owners. | `current change`; parent issue `#81`; completed issue `#331`; issues `#620`-`#622` and `#627`-`#633`. | Complete the child packages in dependency order, then retain separately authorized governed runtime and independent effect evidence before changing constitutional status. |
| 2026-08-29 | in-progress | Reconciled the security ledger with the shared executor safeguard contract, the completed model-bound minimization receipt, and explicit issue handoff for the remaining live drill, privacy, and A3-E evidence. | `core/executor/safeguards.py`; `tests/core/executor/test_safeguard_contract.py`; [Data Governance implementation status](data-governance.md#implementation-status); issues `#81`, `#331`, `#371`, and `#372` | Extend equivalent safeguard and independent-effect receipts to workflow and isolated-Executor paths, then retain governed live evidence. |
| 2026-08-14 | in-progress | Adopted the implementation ledger without reconstructing earlier provenance and aligned security claims with the service cutover, safeguard implementation, kill switch, privacy, and A3-E evidence boundaries. | `current change`; deployment manifests, source, focused tests, and constitutional register cited above. | Close the shared safeguard contract, operational drills, privacy gate, and standing-authorization implementation. |

### Remaining work

- [x] Define the provider-neutral seven-safeguard proof bundle under issue `#620`. Evidence: `execution_safeguards.py`, its versioned JSON Schema, and 4 focused passing contract tests.
- [x] Define provider-attested historical acquisition and current live ownership evidence under issue `#664`. Evidence: `resource_lock.py`, `test_resource_lock_receipt.py`, 40 focused passing tests, Ruff, strict mypy, and zero Medium-or-higher independent critique findings.
- [x] Define the evidenced target-lock lifecycle, single-owner migration, inert-handle behavior, and production no-fallback dependency under issue `#669`. Evidence: commits `f25fdbe63` and `301c7a36b`, 67 focused tests, and zero Medium-or-higher independent critique findings.
- [x] Implement the local test-only evidenced provider with exact per-acquisition identity and production rejection under issue `#674`. Evidence: 65 focused tests, Ruff, strict mypy, and zero Medium-or-higher independent critique findings.
- [x] Define ownership-through-commit, sink fencing or authoritative reconciliation, and durable `outcome_unknown` quarantine under issue `#670`. Evidence: `lock_continuity.py`, 17 focused tests, Ruff, strict mypy, and zero Medium-or-higher independent critique findings.
- [x] Define crash-safe durable idempotency reservation and recovery evidence under issue `#671`. Evidence: `idempotency_reservation.py`, 16 focused tests, Ruff, strict mypy, and zero Medium-or-higher independent critique findings.
- [x] Define authoritative audit-intent append and readback evidence under issue `#672`. Evidence: `audit_intent.py`, 7 focused tests, Ruff, strict mypy, and zero Medium-or-higher independent critique findings.
- [x] Implement the production PostgreSQL evidenced resource lock under issue `#678`. Evidence: 80 local checks, one live PostgreSQL session/readback/release/reacquisition scenario, Ruff, strict mypy, and zero Medium-or-higher independent critique findings.
- [x] Implement the durable PostgreSQL reservation store under issue `#679`. Evidence: 23 local checks, 64 migration inventory checks, one live PostgreSQL race/restart/CAS scenario, Ruff, strict mypy, and zero Medium-or-higher independent critique findings.
- [x] Implement the durable PostgreSQL audit-intent store under issue `#680`. Evidence: 10 local checks, 64 migration inventory checks, one live PostgreSQL append race/restart scenario, Ruff, strict mypy, and zero Medium-or-higher independent critique findings.
- [x] Persist target-wide prepared dispatch fences under issue `#692`. Evidence: 18 local checks, 64 migration inventory checks, one live PostgreSQL contention/restart scenario, Ruff, strict mypy, and zero Medium-or-higher independent critique findings.
- [x] Persist safeguard, dispatch, and pre-release checkpoints under issue `#693`. Evidence: 86 focused model, persistence, and migration tests passed; one live PostgreSQL test remains skipped until its DSN is configured; Ruff passed.
- [x] Atomically close or quarantine post-release safeguard state under issue `#694`. Evidence: focused model, persistence, and migration suites passed; a fresh pgvector/PostgreSQL 16 migration and live parallel closure, restart, reconciliation, and outbox-deduplication scenario passed; Ruff and strict mypy passed.
- [x] Implement and wire the shared evidence lifecycle orchestrator and Core producers under issues `#681` and `#627`.
- [x] Revalidate safeguard-bound commands in the isolated Executor under issue `#628`.
- [ ] Emit the shared bundle from real Core and workflow execution after the #669-#672 prerequisites close under issue `#627`.
- [x] Require the pure full-action safeguard proof finalizer to consume the exact current `LiveLockOwnershipAssessment` under child issue `#660`. Evidence: 52 combined focused safeguard and resource-lock tests, Ruff, strict mypy, and zero Medium-or-higher independent critique findings.
- [ ] Revalidate the shared bundle in the isolated Executor without importing Core validators under issue `#628`.
- [ ] Retain separately authorized governed cross-path safeguard and independent effect evidence under issue `#633`.
- [x] Bind separately approved recovery through existing approval and decision-evidence contracts without mutating the hold under issue `#622`. Evidence: `recovery_admission.py`, `test_recovery_admission.py`, and 46 focused passing checks.
- [x] Implement the approval-guarded atomic release primitive and no-authority receipt. Evidence: 63 focused passing checks.
- [x] Route production compensation through that primitive and retain the exact release receipt under issue `#630`. Evidence: `recovery_coordinator.py` consumes `release_admitted` and stores the immutable release lookup; the legacy `release_verified` path is removed.
- [x] Complete the #630 production chain under #652, #656, and #658 without reusing a failed immutable proposal or weakening effect evidence. Evidence: 14 focused recovery call-site checks covering missing approval, wrong identity, stale hold, duplicate and restart delivery, in-doubt reconciliation, release-receipt recovery, and completion-outbox delivery.
- [x] Recheck the release receipt and absence of a newer hold inside each execution path's existing logical-target lock under issue `#640`; FDAI-CONST-009 remains implemented during this hardening. Evidence: `_HoldFencedDispatchPort` inside `SafeguardLifecycleCoordinator`, plus active-hold, reissued-hold, unreadable-hold, and matching-lineage executor tests.
- [ ] Retain governed kill-switch, break-glass, rollback, identity-recertification, and audit-anchor drill receipts on one pinned deployment revision. Tracked by issue `#372`.
- [ ] Complete the data-governance production gate before claiming privacy validation. Tracked by issue `#371`.
- [x] Define the inert effect-spanning lease and provider commit fence under issue `#621`. Evidence: 82 focused tests, Ruff, strict mypy, a static scan of 208 authority-path files, and zero Medium-or-higher independent critique findings.
- [x] Implement the inert promotion-candidate lifecycle under issue `#629`. Evidence: 52 focused tests, Ruff, strict mypy, bounded files, and zero Medium-or-higher findings after hardening reviewer authorization and revocation digest binding.
- [x] Retain the bounded local synthetic shadow cohort under issue `#631`. Evidence: canonical manifest/receipt, local timeout and registry-integrity checks, symlink-safe artifact output, focused tests, and zero Medium-or-higher findings after hardening.
- [ ] Complete separately authorized governed runtime evidence and promotion under issue `#632`; completed issues `#331`, `#621`, `#629`, and `#631` remain development evidence only.

## Severity Vocabulary

- **P0 blocker** - must be resolved and verified before any auto-execution is enabled; blocks
  promotion out of shadow mode.
- **P1** - required before a capability handles production (enforce mode) events.
- **P2** - hardening that may follow first enforce, tracked in Open Decisions with an owner.

## Execution Identity

This section governs the **non-human** executor identity. The **human** identity model -
who signs in to the console and ChatOps, what Entra groups exist, and how the console
delegates writes to a GitHub App - lives in
[user-rbac-and-identity.md](../interfaces/user-rbac-and-identity.md). Approval ≠ execution: humans
never hold the executor identity described below.

- The executor MUST authenticate through a **`WorkloadIdentity` interface** that exposes only
  "get a short-lived, audience-scoped OIDC token." This realizes the
  [Workload Identity contract](csp-neutrality.md#4-workload-identity-contract--oidc-token);
  concrete issuers (Managed Identity on Azure, IRSA on AWS, Workload Identity Federation on
  GCP, SPIFFE/SPIRE on any K8s) sit behind that interface, never in `core/`.
- On Azure the interface is backed by a **User-assigned Managed Identity**, scoped to an
  explicit **action whitelist**. No broad standing permissions.
- `DefaultAzureCredential()` (or any similarly named SDK entry point) is **prohibited in
  `core/`**; it appears only inside the Azure provider adapter behind the interface.
- **Per-vertical identities are provisioned alongside the aggregate router identity.** Terraform
  creates `id-<workload><suffix>-executor`, `-change`, `-resilience`, and `-finops` identities.
  Fork-owned policy modules bind the vertical action whitelists; see
  [Identity Mapping](#identity-mapping) below.
- human approval identities (HIL) are distinct from execution identities; approval and
  execution are never the same principal, and no identity may assume another domain's identity
  (cross-domain assumption is denied, not just unused).
- Execution identities are **non-interactive**: no interactive/console sign-in, no human
  credentials attached, and disabled for any use outside the event loop.
- Prefer **credential-free auth**: workload identity federation / OIDC token exchange so the
  executor holds no long-lived secret. Where a secret is unavoidable it is short-lived and
  auto-rotated (see Secrets and Config).

### Identity Mapping

This resolves the P0 Open Decision *"Executor-side identity mapping"*. The current Terraform
shape preserves one aggregate action-router identity and three vertical identities so delivery
adapters can select a principal by domain without changing `core/`.

| Identity | Current purpose | Azure role strategy | Scope |
|----------|-----------------|---------------------|-------|
| `id-<workload><suffix>-executor` | aggregate control-loop transport and action routing | upstream grants only platform roles needed by the runtime, such as topic-scoped Event Hubs access and Key Vault secret reads | resource or service scoped; never subscription-wide |
| `id-<workload><suffix>-change` | Change Safety delivery principal | fork-owned action whitelist or measured custom role | governed resource groups for Change Safety |
| `id-<workload><suffix>-resilience` | Resilience and recovery delivery principal | fork-owned action whitelist or measured custom role | governed recovery scopes |
| `id-<workload><suffix>-finops` | Cost Governance delivery principal | fork-owned action whitelist or measured custom role | governed cost-optimization scopes |

Execution authorization uses provider-neutral refs `identity/change`, `identity/resilience`, and
`identity/finops`. Terraform attaches the corresponding UAMIs and exposes only their client ids to
the delivery composition. The authorization result selects one ref; the Action and direct-API
request preserve it, and the delivery router chooses the matching `WorkloadIdentity`. An unknown
or unbound ref is refused rather than falling back to the aggregate executor identity.

Read-only inventory, ingestion, canary, and other service identities remain separate from this
executor set. Creating a vertical identity does not grant it resource permissions; those role
assignments are explicit fork deployment policy.

Rules that apply to every phase (MUST):

- **RG-scoped, never subscription-wide.** A new RG comes under governance only when the
  fork explicitly adds it to the assignment IaC - no automatic broadening.
- **Complementary Azure Policy `deny`** blocks any MI action outside its declared
  whitelist as a second line of defense, so a mis-assigned role cannot silently widen
  the surface.
- **Every action whitelist change is a governance PR** with `Justification:` and
  Owner-tier quorum on any change touching a Managed Identity role assignment
  ([user-rbac-and-identity.md](../interfaces/user-rbac-and-identity.md)).
- **Shadow log capture** records every action emitted by the
  executor MI in shadow mode records the exact Azure resource-provider operation it
  would call, so the Phase 2 Custom Role derivation is deterministic and auditable.

The delivery layer selects a vertical MI from the action domain; no core code change is needed.

## Authorization Model

Execution authorization resolves through the provider-neutral capability ontology and scoped
policy assignments described in
[Execution Authorization Ontology](../decisioning/execution-authorization-ontology.md). Action
approval never grants executor access. A missing permission holds the original action and may
create a separate exact-plan `AccessGrantRequest`; a distinct protected deployer applies an
approved grant, and fresh effective-access evidence is required before the action is re-evaluated.

- Map every action to the minimum role/permission needed; **deny by default**.
- Enforce least privilege mechanically, not by convention: the action whitelist is
  policy-as-code (OPA/Rego) evaluated at the risk gate, and privileged scopes are granted
  **just-in-time and time-bound**, expiring after the action window rather than standing open.
- Reconcile the org's account/identity standard with the cloud authorization path (e.g. an
  external IdP such as Keycloak ↔ Entra ↔ Managed Identity). Treat this mapping as a **P0
  blocker**; it is resolved only when the end-to-end path is provisioned, tested with a
  least-privilege probe, and access recertification is scheduled.
- **Access recertification**: role assignments are reviewed on a fixed cadence; unused or
  over-broad grants are revoked. Recertification outcomes are audited.
- Autonomous deployments must respect platform policy (e.g. Azure Policy `deny`); provide a
  **policy-exemption workflow** (requestable, time-boxed, audited, owner-approved) rather than
  bypassing controls.

## Secrets and Config

- Never hardcode secrets, connection strings, subscription/tenant IDs, or customer identifiers.
  Secret scanning (e.g. gitleaks) runs in CI and a positive finding blocks the merge
  ([coding-conventions.instructions.md](../../../.github/instructions/coding-conventions.instructions.md)).
- **The app reads only environment variables (or K8s Secret mounts).** It MUST NOT call a CSP
  secret SDK (`SecretClient`, `SecretsManagerClient`, `SecretManagerServiceClient`, ...); this
  realizes the [Secret contract](csp-neutrality.md#3-secret-contract--environment--k8s-secret).
  On Azure the injection layer is **Container Apps native secret + Key Vault reference**; on
  Kubernetes it is **External Secrets Operator** with a `SecretStore` CRD.
- Access secrets through an injected `SecretProvider` in `shared/providers/`, never a global
  read at import.
- **Lifecycle**: every secret has an owner, a defined rotation interval, and automated rotation;
  compromised or superseded material is revoked immediately. Prefer federated tokens so there
  is no secret to rotate.
- **Fail-closed**: if the secret injection layer or token issuer is unavailable at startup, the
  process fails fast - it does not fall back to a cached or embedded credential and never
  starts in a degraded state.
- Secrets MUST NOT appear in logs, audit entries, error messages, test fixtures, or LLM prompts.
- Keep the repo customer-agnostic
  ([generic-scope.instructions.md](../../../.github/instructions/generic-scope.instructions.md)).

## Data Protection

- **Classify** data handled by the control plane (event payloads, tool output, audit records,
  embeddings) and minimize it: store pointers/ids, not raw customer bytes or PII.
- Encrypt in transit (TLS) and at rest; keys are managed in the secret/key store, not in code.
- **LLM data handling**: T2 prompts are redacted of secrets and PII before leaving the trust
  boundary; enforce data-residency and no-retention terms for any external model vendor. A
  prompt that would require unredactable sensitive data is routed to HIL instead of sent.

## Network Boundaries

- The executor and core engine have **no public inbound endpoint**; ingress is the event bus
  only. Management/API surfaces sit behind private networking.
- **Egress is allow-listed** to required cloud control planes and model endpoints; default-deny
  outbound to contain exfiltration and injection-driven callbacks.
- Layer identities are not shared across the network boundary; the read-only console and
  ChatOps never hold the executor identity
  ([app-shape.instructions.md](../../../.github/instructions/app-shape.instructions.md)).

## Supply-Chain Integrity

- Dependencies are pinned via lockfile; CI installs from the lockfile only and a vulnerability
  scan blocks high-severity findings.
- The rule catalog and IaC are catalog-as-code behind **protected branches with signed
  commits/PR review**; no direct pushes to the enforce branch.
- Build artifacts (container images) are signed and their provenance/SBOM recorded; the
  executor pulls only verified, pinned digests, never mutable `latest` tags.

## Seven safeguards (every autonomous state-changing action)

1. **Stop-condition** - a defined halt state that aborts the action. Declared per-ActionType
   in `stop_conditions[]` and evaluated by the executor during and after apply.
2. **Rollback path** - a tested way to revert. The ontology `ActionType.rollback_contract`
   MUST be one of `pr_revert` / `scripted` / `pitr` / `snapshot_restore` /
   `state_forward_only`; **`none` is not a valid value**. Genuinely one-way mutations set
   `ActionType.irreversible: true` and are routed HIL+quorum by the risk-gate; rollback is
   still declared as the best-effort recovery.
3. **Blast-radius limit** - scope caps (non-prod first, batch size, rate) plus per-resource
   serialization so concurrent actions on one resource are mutually excluded. `ActionType.blast_radius.computation = graph_derived`
   makes the risk-gate compute the actual impacted set over the Resource → Resource graph
   (`contains` + reverse `depends_on`, depth 2) - the three-value enum is a bucket, not a cap.
4. **What-if or dry-run** - a successful, version-bound prediction receipt before mutation.
5. **Logical-target lock** - a held lock and causal ordering for every affected target; managed
  resource changes use the exact resource identity.
6. **Idempotency** - a stable key and duplicate suppression across delivery and retries.
7. **Audit lifecycle** - append-only intent persisted before the side effect, then terminal
  execution and outcome closure after it.

Missing any safeguard means the action is incomplete and must not ship. Each safeguard is
**testable**: shadow-mode tests prove no mutation, rollback tests prove prior state is restored,
and property-based tests assert that high-impact execution has current or standing human approval,
silence grants nothing, irreversible actions never use standing authorization, and retries are
no-ops. Pure A0 reads follow their bounded read authorization and evidence contracts rather than
mutation rollback, dry-run, and lock requirements. Independent effect verification gates every
success claim.

### Target-lock ownership migration

The evidenced target lock has one owner per mutation path. The migration keeps the legacy
resource-claim fence until the selected executor is readiness-gated on the evidenced provider.
It does not permit a temporary dual acquisition.

| Path | Current target-lock boundary | Required owner after migration |
|------|------------------------------|--------------------------------|
| Thor dispatch | Legacy target lock around the generic executor call plus a separate durable resource claim | Keep the durable claim. Remove the duplicate target lock only when the selected executor rejects a missing evidenced provider. |
| PR native/manual | Idempotency mutex, then an internal legacy target lock | The selected PR executor owns one evidenced target lock through publish and terminal persistence. |
| Direct API | Idempotency mutex, then an internal legacy target lock | The direct-API executor owns one evidenced target lock through provider commit continuity and terminal persistence. |
| Tool call | Idempotency mutex, then an internal legacy target lock | The tool-call executor owns one evidenced target lock through provider commit continuity and terminal persistence. |
| Workflow | Orchestrates the selected executor and does not define a separate `ExecutionPath` | The selected executor owns the target lock. Workflow passes the immutable pre-bundle commitment and never reacquires the target. |
| Isolated Executor | Shared-bundle revalidation remains open under #628 | The isolated executor must reject missing or stale evidenced ownership before dispatch and must not fall back to the legacy seam. |

### PostgreSQL continuity admission

An effect sink is unsupported for production until its composition supplies one reviewed
`EffectSinkContinuityPolicy`. The policy selects fenced and idempotent execution, complete
lock-session atomicity, or cancellation with durable unknown-outcome quarantine and authoritative
reconciliation. A generic Direct API or tool category is not a continuity strategy.

The PostgreSQL evidence provider follows these boundaries:

- One dedicated connection owns the exact advisory key for the complete acquisition context.
  Reconnect or connection substitution creates a new acquisition and cannot continue the old one.
- The acquisition binds the database identity, backend process ID, backend session discriminator,
  request digest, and owner-reference digest without storing the DSN or a capability-bearing token.
- `pg_locks` with `granted=true` is a point-in-time substrate observation. Provider-owned UTC time
  and the five-second contract maximum bound the assessment, but neither predicts future ownership.
- The provider checks the boolean advisory-unlock result. A connection loss, missing lock row, or
  unknown unlock result produces lost or unknown release evidence and durable target quarantine.
- A sink commit does not clear quarantine or claim operational success. The selected sink policy
  must provide stable sink idempotency or authoritative status reconciliation, and independent
  effect verification remains a separate terminal axis.

## Rate Limiting and Kill-Switch (DoS and containment)

- The event loop and executor enforce **rate/budget caps** (per-tier, per-resource, and global);
  exceeding a cap degrades to HIL, never to ungated auto-action. This also bounds cost and a
  runaway or event-flood (DoS) condition.
- A **global kill-switch** halts all auto-execution immediately and drops every path to
  shadow/HIL; it is operable without the executor identity. The risk gate realizes this via a
  `kill_switch` ceiling axis fed by `KillSwitch.is_engaged()`
  ([execution-model.md](../decisioning/execution-model.md) 2.6b). The production runtime reads
  the state from PostgreSQL before every authority decision; a read failure is treated as
  engaged. Owner and Break-Glass principals change it through `POST /system/kill-switch`, which
  uses revision compare-and-set and writes the audit entry in the same transaction.
- A **break-glass** procedure grants scoped emergency access under mandatory audit and
  post-incident review; break-glass use raises an alert and auto-expires.

## Shadow → Enforce Promotion

- New capabilities ship in **shadow mode**: judge and log only, no execution.
- Promotion to enforce is explicit, per-action, and gated on a **minimum shadow duration and
  sample size**, measured accuracy above threshold, and **zero policy-violation escapes** in
  shadow (metrics defined in [goals-and-metrics.md](goals-and-metrics.md)).
- Regressions demote back to shadow automatically; every promotion and demotion writes an
  audit entry.
- Working-context policy candidates use the same capability authority without gaining action
  capability. They install disabled, run bounded off-path comparisons, require an exact version,
  evidence window, and rollback target for promotion, and engage a per-policy kill switch on an
  invariant violation. See [Context Selection Policy](../decisioning/context-selection-policy.md).

## Human Approval Integrity

- Approval and execution are distinct principals; **no self-approval**, and high-blast-radius
  actions require **quorum (multi-approver)** rather than a single approver.
- Approvers authenticate with MFA/phishing-resistant credentials; each approval is bound to a
  specific action + idempotency key so it **cannot be replayed** against a different action.
- **Timeout is fail-closed**: an HIL item without current approval or a valid pre-existing standing
  approval ends as a no-op plus an audit entry. Silence never creates approval. A standing approval
  applies only through the bounded A3-E contract in
  [Escalation and Standing Authority](../decisioning/escalation-and-standing-authority.md).

## Auditability

- The audit store is append-only and is the trust basis for autonomy.
- **Tamper-evidence**: entries are hash-chained (each record commits to the previous) and
  periodically anchored/signed, so deletion or edits are detectable; storage is
  write-once/WORM where available.
- **Non-repudiation**: each entry records the authenticated actor identity (executor or
  approver) and mode (shadow/enforce) so an action cannot later be disowned.
- Every action links to: the triggering event, the tier that decided it, the rules/policies
  cited, the risk decision (auto/HIL), the approver (if HIL), the idempotency key, and the
  rollback reference.
- **Retention**: a defined immutable retention window with legal-hold support; records are not
  purgeable before the window elapses.
- Audit data is customer-agnostic in this repo; real environment records live only in a fork's
  runtime store, never committed here.

## Threat Model (STRIDE)

Browser-only evidence uses a separate credential-free runtime with no executor identity or host
filesystem mount. Exact HTTPS origin policies, per-connection DNS revalidation, restricted egress,
GET/HEAD interception, visual and text redaction, secret canaries, prompt-injection scanning,
content hashes, and append-only custody records form one fail-closed boundary. Browser content is
always untrusted and cannot approve or execute an action. See
[Browser evidence collection](../interfaces/browser-evidence.md).

Event payloads and tool output are **untrusted**; the deterministic verifier and policy
re-check are the authority, never model or event text.

| STRIDE | Threat | Mitigation |
|--------|--------|------------|
| **Spoofing** | Forged events / impersonated approver | Authenticated (signed) event source; MFA + action-bound approvals; federated identity |
| **Tampering** | Altered rules/IaC, injected artifacts | Signed commits, protected branches, signed/pinned artifacts + SBOM |
| **Repudiation** | Action later disowned | Hash-chained, actor-attributed append-only audit |
| **Info disclosure** | Secret/PII leak via logs or LLM prompts | Redaction, no-secret-in-prompt, encryption, egress allow-list |
| **DoS** | Event flood / runaway loop / budget burn | Rate/budget caps, circuit-break to HIL, kill-switch |
| **Elevation** | Over-broad or cross-domain action | Per-domain identities, JIT time-bound scopes, deny cross-assumption, no self-approval |
| **Prompt injection** | Malicious payload steers T2 | T2 treated as untrusted; verifier + policy re-check are authoritative |

## Open Decisions

| Priority | Decision | Owner | Target |
|----------|----------|-------|--------|
| ~~P0~~ | ~~Executor-side identity mapping~~ - **resolved** in [Identity Mapping](#identity-mapping) | - | - |
| ~~P0~~ | ~~Risk-classification policy (auto vs HIL) and initial policy approver~~ - **resolved** in [risk-classification.md](../decisioning/risk-classification.md) | - | - |
| P1 | Policy-exemption workflow owner and SLA | TBD | before production |
| P1 | Audit anchor cadence, WORM binding, and operational verification | TBD | before production |
| P1 | Kill-switch and break-glass runbook and drill schedule | TBD | before production |
| P2 | Compliance control mapping (MCSB / CIS / SOC 2) and evidence collection | TBD | post first enforce |
| P2 | Secret rotation intervals and federation coverage per identity | TBD | post first enforce |
