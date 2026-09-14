---
title: Alert Noise Governance Implementation Ledger
---
# Alert Noise Governance Implementation Ledger

This ledger tracks delivery of [Alert Noise Governance](../../roadmap/operations/alert-noise-governance.md).
The owner and its Korean translation describe the shadow-first implementation and its intended
operational boundaries. This English engineering ledger is the only implementation status source.
The current change is a baseline checkpoint, not final completion or operational adoption.

> **Evidence boundary:** The coordinating session supplied the focused-check results recorded below.
> This documentation-only handoff inspected source and test paths but ran no tests or checkers.
> Framework bindings and passing synthetic checks do not prove independently produced operational
> receipts, provider notification tests, Azure mutations, promotion, publication, or deployment.

## Implementation status

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| ANG-1: versioned evidence and read-only collection mechanics | implemented | [Shared contracts](../../../packages/service-contracts/src/fdai_service_contracts/alert_noise.py), [contract tests](../../../packages/service-contracts/tests/test_alert_noise.py), [Azure reader](../../../services/core-control-plane/src/fdai/delivery/azure/alert_noise_source.py), [source tests](../../../services/core-control-plane/tests/delivery/azure/test_alert_noise_source.py), [history tests](../../../services/core-control-plane/tests/delivery/azure/test_alert_noise_history.py) | Bounded native reads, private pseudonymous evidence, and explicit partial/unknown states exist. A private processing-rule record is not an inventory declaration. |
| ANG-1: complete operational evidence | in-progress | [Admitted supplement reader](../../../services/core-control-plane/src/fdai/delivery/alert_noise_evidence.py), [admission tests](../../../services/core-control-plane/tests/delivery/test_alert_noise_evidence.py) | Native collection does not prove directory membership, current ownership/incident state, complete reverse dependencies, historical rule revisions, or delivery/recipient outcomes. Exact-base independent supplements are required, not claimed produced. |
| ANG-2: deterministic assessment and scoped bilingual requests | implemented | [Assessment](../../../services/core-control-plane/src/fdai/core/detection/alert_noise/assessment.py), [assessment tests](../../../services/core-control-plane/tests/core/detection/alert_noise/test_assessment.py), [signed agent pipeline tests](../../../services/core-control-plane/tests/core/detection/alert_noise/test_pipeline.py), [Operator tests](../../../services/operator-service/tests/test_alert_quality.py), [Console model tests](../../../console/src/routes/alert-quality.model.test.ts) | Live-only scope discovery, retained reports, three inert treatment forms, and separate observed/unknown counts exist. Acceptance is not assessment completion, approval, or an effect. |
| ANG-2: Settings API, revision storage, and UI mechanics | implemented | [Preference store](../../../services/operator-service/src/fdai_operator_service/alert_quality_settings.py), [Settings tests](../../../services/operator-service/tests/test_alert_quality_settings.py), [PostgreSQL checks](../../../services/operator-service/tests/test_alert_quality_postgres.py), [Console Settings tests](../../../console/src/routes/alert-quality.settings.test.ts) | Human Owner authorization, immutable revision/audit records and concurrency preconditions exist. [Operator composition](../../../services/operator-service/src/fdai_operator_service/composition.py) binds the preference store; local PostgreSQL proves competing writers and new-connection replay, not deployment readiness. |
| ANG-3: registered actions and exact-plan Workflow/Process mechanics | implemented | [Routing catalog](../../../rule-catalog/action-types/ops.update-alert-routing.yaml), [catalog tests](../../../services/core-control-plane/tests/rule_catalog/test_alert_noise_catalog.py), [Workflow binding](../../../services/core-control-plane/src/fdai/core/detection/alert_noise/workflow.py), [Workflow tests](../../../services/core-control-plane/tests/core/detection/alert_noise/test_workflow.py), [runtime tests](../../../services/core-control-plane/tests/runtime/test_alert_noise_control.py) | Four actions and three workflows default to shadow. Existing orchestration, Var quorum, plan/target/version pins, retained mode, and canonical Process resume are reused, not replaced. |
| ANG-3: exact-file manual-PR execution mechanics | implemented | [Execution](../../../services/core-control-plane/src/fdai/core/detection/alert_noise/execution.py), [execution tests](../../../services/core-control-plane/tests/core/detection/alert_noise/test_execution.py), [authority tests](../../../services/core-control-plane/tests/delivery/test_alert_noise_authority.py), [fence tests](../../../services/core-control-plane/tests/delivery/test_alert_noise_fence.py), [PR tests](../../../services/core-control-plane/tests/delivery/test_alert_noise_pr.py) | Existing Terraform JSON only, actual observed Action Groups, immutable forward/rollback artifacts, current independent proofs, and `pr_manual` only. No new group, receiver rewrite, or direct Azure fallback. No actual publication is claimed. |
| ANG-3/4: independent effect and recovery framework | implemented | [Effect factory](../../../services/core-control-plane/src/fdai/runtime/alert_noise_effects.py), [runtime tests](../../../services/core-control-plane/tests/runtime/test_alert_noise_effects_runtime.py), [effect tests](../../../services/core-control-plane/tests/delivery/test_alert_noise_effects.py), [outcome tests](../../../services/core-control-plane/tests/core/detection/alert_noise/test_outcomes.py) | Opt-in callbacks and bounded reconciliation use canonical dispatch, closure, outcome, Process, and automation-hold stores. Effect admission and separate Workflow outcome admission remain distinct. Factory construction creates neither receipt nor recovery authority. |
| ANG-3/4: operational routing, effect closure, and recovery | in-progress | [Execution composition](../../../services/core-control-plane/src/fdai/runtime/alert_noise_execution.py), [effect reader](../../../services/core-control-plane/src/fdai/delivery/alert_noise_effect_reader.py), [operator runbook](../../runbooks/alert-noise-governance.md) | Independent authority, recipient, exclusion, effect, and recovery producers and their current admissions must be present in the selected environment. PostgreSQL/restart and live evidence remain open. |
| ANG-4: finite suppression planning and artifact mechanics | implemented | [Planner](../../../services/core-control-plane/src/fdai/core/detection/alert_noise/planning.py), [planning tests](../../../services/core-control-plane/tests/core/detection/alert_noise/test_planning.py), [JSON renderer](../../../services/core-control-plane/src/fdai/delivery/alert_noise_iac.py), [execution tests](../../../services/core-control-plane/tests/core/detection/alert_noise/test_execution.py) | One existing inert rule, exact target, bounded UTC interval, propagation budget, protected/automation exclusion, and independent collection checks. Provider activation, expiry, and post-expiry delivery are not established by synthetic checks. |
| ANG-5: threshold comparison and admitted evaluation | in-progress | [Same-bucket comparator](../../../services/core-control-plane/src/fdai/core/detection/alert_noise/evaluation.py), [evaluation reader](../../../services/core-control-plane/src/fdai/delivery/alert_noise_evidence.py), [evidence tests](../../../services/core-control-plane/tests/delivery/test_alert_noise_evidence.py) | Comparator and receipt-gated planning exist; JSON delivery supports one simple metric threshold only. Independent scenario labels, native conformance, recall/latency evidence, and remaining coverage are still required. This is not an implemented ANG-5 package. |
| ANG-5: evaluation-window/frequency changes and promotion | not-started | [Measurement and exit conditions](../../roadmap/operations/alert-noise-governance.md#9-delivery-sequence-and-exit-evidence) | Window/frequency changes remain guidance/held, not implemented. No provider notification test, timed pilot, or ActionType/Workflow promotion is claimed. |
| Baseline hardening and integration closure | in-progress | Focused baseline in the history row below; [alert core](../../../services/core-control-plane/src/fdai/core/detection/alert_noise/), [owning tests](../../../services/core-control-plane/tests/core/detection/alert_noise/) | Coverage is below the required floor. Ten verified hardening rounds, PostgreSQL integration, authenticated browser evidence, and exact-head CI remain open. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-09-14 | not-started | Established the design-only organization-scale alert-noise scope, authority boundaries, Azure semantic constraints, critique decisions, and five delivery packages. | `current change`; [design owner](../../roadmap/operations/alert-noise-governance.md), [Korean translation](../../roadmap/operations/alert-noise-governance-ko.md), and [design review decisions](../../roadmap/operations/alert-noise-governance.md#10-design-review-decisions). | Implement and verify ANG-1 through ANG-5; no source implementation, live Azure/model validation, publication, or deployment is claimed. |
| 2026-09-15 | in-progress | `current change`: recorded the shadow-first implementation baseline for private evidence, typed requests, four registered manual-PR actions, exact retained Workflow/Process binding, independent-proof readers, effect reconciliation, and Settings mechanics. Operational adoption remains gated. | Coordinating-session results: 1136 owning Python tests passed; strict mypy passed 69 source files; 246 Console tests and typecheck passed. Owning paths include [Core alert tests](../../../services/core-control-plane/tests/core/detection/alert_noise/), [runtime effect tests](../../../services/core-control-plane/tests/runtime/test_alert_noise_effects_runtime.py), [Operator Settings tests](../../../services/operator-service/tests/test_alert_quality_settings.py), and [Console request tests](../../../console/src/routes/alert-quality.requests.test.ts). Measured `fdai.core.detection.alert_noise` coverage: 82.08%, below the >=90% floor. | Finish coverage and ten evidence-backed hardening rounds; bind and verify Settings persistence, real PostgreSQL/restart behavior, independent operational receipts, authenticated browser behavior, and exact-head CI. No provider notification test, Azure mutation, promotion, publication, or deployment is claimed. |

### Remaining work

- [x] **Coverage gate:** The 243 focused Core checks passed with branch-enabled combined coverage
  of 91.24% using `--cov=fdai.core.detection.alert_noise --cov-branch --cov-fail-under=90`.
  The threshold comparator measured 100%. This does not replace exact-head integration CI.
- [x] **Ten hardening batches:** Rounds 1-10 below each have focused verification and their own
  local commit. Rounds 7-9 corrected reproduced Medium defects; other rounds honestly record
  coverage hardening. This count does not close the remaining integration or operational gaps.
- [ ] **ANG-1 evidence:** Supply independently admitted directory, current ownership/incident,
  complete reverse-dependency, historical revision, and delivery evidence bound to the exact native
  snapshot. Retain denial, partial, stale, conflicting, and privacy outcomes without fabricated
  recipients or inventory truth; resolve any required ontology declaration separately.
- [ ] **ANG-2 scale and projection:** Retain the complete design-scale evidence for at least 500
  synthetic principals, 20 teams, and 10000 events, including skew and bounded expansion. Add the
  missing team/audience-kind/period filters, baseline/guard metrics, approval/outcome detail, and
  benefit projections only when their authoritative source fields exist.
- [ ] **Settings composition:** Pass the Operator-owned `StateKvAlertQualityPreferenceStore` through
  the existing dependency factory, then prove human Owner CAS, audit, conflict, restart, unavailable
  behavior, and no promotion. Disabling new requests must not cancel accepted work or approved recovery.
- [ ] **PostgreSQL:** Retain service-owned database evidence for outbox claim isolation, preference
  concurrency, retained Process resume, actual dispatch generations, effect reconciliation, and
  automation holds across restart. Lazy constructors and in-memory doubles do not close this item.
- [ ] **ANG-3 authority and source fencing:** Demonstrate current Var service-owner plus distinct
  Owner quorum, revocation, target/dependency/source revalidation, tested rollback and dry-run, real
  replacement-recipient reachability, and independently admitted exclusive-writer protection through
  the existing GitOps sink. An environment map or advisory read-then-write check is not that proof.
- [ ] **Independent closure:** Bind actual effect and recovery producers plus separate canonical
  Workflow outcome admissions. Retain missing, late, conflicting, failed, and successful observation
  receipts with exact publication/bundle/Process lineage, and verify separately authorized recovery
  without treating PR publication or merge as an Azure effect.
- [ ] **ANG-4 operation:** Under separate authorization, retain provider conformance for suppression
  precedence, protected/automation exclusion, unaffected collection, propagation, absolute expiry,
  time-zone behavior, post-expiry observation, ambiguous acknowledgement, and recovery. No notification
  test or Azure mutation is requested by this checkpoint.
- [ ] **ANG-5:** Validate simple-metric threshold replay against independently labeled positive,
  negative, and missed-incident cases with pinned telemetry and recall/latency guards. Keep window
  and frequency changes held until their native semantics and exact-file delivery are implemented.
  Record any later pilot and promotion only with separately authorized independent evidence.
- [ ] **Browser:** Retain authenticated English/Korean standard Console evidence for scope selection,
  three forms, Settings Owner/conflict/unavailable states, stale authentication, unknown outcomes,
  responsive layout, and keyboard use. Passing Console unit tests and types are not browser proof.
- [ ] **Delivery gates:** The parent refreshes only reviewed Korean pairs and runs applicable
  documentation, route, runbook, and structural checks. Record exact-head required CI separately
  before any later publication claim; this handoff runs no checker, commit, or remote operation.

## Evidence boundary

### Verified critique and hardening rounds

Each row is one independently reviewed and executed local batch. A passing adversarial check
with no new defect is recorded as coverage hardening, not an invented finding. These synthetic
checks do not prove deployed Azure behavior or authorize promotion.

| Round | Scope and hypothesis | Finding / initial severity | Change and falsifying evidence | Remaining |
|-------|----------------------|----------------------------|--------------------------------|-----------|
| 1 | Noncanonical authority, time, copied records and half-specified treatment axes might cross the boundary. | No new defect; coverage hardening. | [Boundary tests](../../../services/core-control-plane/tests/core/detection/alert_noise/test_boundary_hardening.py): 22 passed. | Keep shared contract validation and no-authority flags; later runtime rounds remain open. |
| 2 | Lifecycle updates, resolved deliveries and overlapping people might inflate counts or manufacture flapping. | No new defect; coverage hardening. | [Measurement tests](../../../services/core-control-plane/tests/core/detection/alert_noise/test_measurement_hardening.py): 6 passed, including unknown denominators and small-cohort redaction. | Native missing history and identities remain unknown, never zero. |
| 3 | Fewer alerts might hide lost recall or a changed replay exposure. | No new defect; coverage hardening. | [Evaluation tests](../../../services/core-control-plane/tests/core/detection/alert_noise/test_evaluation_hardening.py): 10 passed across all supported aggregations, both operators, false negatives, unchanged benefit and wrong exposure. | Only exact same-bucket threshold replay is supported; broader semantics remain held. |
| 4 | Shared routing might omit outside dependencies, automation or responder coverage. | No new defect; coverage hardening. | [Planning tests](../../../services/core-control-plane/tests/core/detection/alert_noise/test_planning_hardening.py): 17 passed for protected/unknown/disabled targets, stale scope, automation, reverse dependencies, audiences and suppression precedence. | Incomplete dependency evidence remains a hold rather than a smaller claimed impact. |
| 5 | A finite suppression might outlive authorization or restore the detector instead of the processing object. | No new defect; coverage hardening. | [Suppression tests](../../../services/core-control-plane/tests/core/detection/alert_noise/test_suppression_hardening.py): 6 passed for exact rollback, propagation, expiry, independent collection and empty delivery graphs. | Provider expiry remains mandatory; cleanup never supplies the end time. |
| 6 | A duplicate, self-approved, wrong-scope or expired quorum might bypass a missing dispatch proof. | No new defect; coverage hardening. | [Admission tests](../../../services/core-control-plane/tests/core/detection/alert_noise/test_admission_hardening.py): 22 passed for exact human lanes and independently required current proofs; Ruff lint and format checks passed. | Trusted admission only grants eligibility, never plan authority. |
| 7 | Competing terminal results might update projections before detecting an identity conflict. | Medium: reproduced two failures, including identity loss after interrupted projection. | [Bridge tests](../../../services/operator-service/tests/test_alert_quality_bridge.py): 3 passed after insert-if-absent result reservation moved before projections; exact replay completes interrupted writes. Ruff and strict runtime mypy passed. | No known residual for this race; database-backed concurrency remains separately tracked. |
| 8 | Organization-scale admitted evidence might exceed a digest or record budget before assessment. | Medium: the complete 10000-event fixture failed at the unrelated query codec's 65536-byte ceiling. | [Scale admission](../../../services/core-control-plane/tests/delivery/test_alert_noise_scale.py) and [codec bounds](../../../packages/service-contracts/tests/test_alert_noise_content.py): 55 focused checks plus 114 authority/fence/effect regressions passed. A separate finite alert codec preserves existing small-record digests; 500 principals, 20 teams, overlapping role/group/direct paths and skew are retained without truncation. | No known residual for this size defect; independently produced operational receipts are still required. |
| 9 | An incomplete effective route might still produce a complete report. | Medium: four missing-group, missing-audience, partial-membership and historical-processing cases incorrectly returned complete. | [Assessment hardening](../../../services/core-control-plane/tests/core/detection/alert_noise/test_assessment_hardening.py) and existing assessment/measurement checks: 17 passed after propagating routing gaps to report coverage; Ruff and strict mypy passed. | No known residual for this completeness defect; unknown counts remain unknown. |
| 10 | A changed catalog, target, requester or terminal replay might replace an exact Process binding. | No new defect; coverage hardening. The shadow Process correctly waits rather than inventing completion. | [Workflow hardening](../../../services/core-control-plane/tests/core/detection/alert_noise/test_workflow_hardening.py): 14 passed, Ruff passed. The complete 243-test Core slice reached 91.24% branch-enabled combined coverage (>=90 gate). | Database, browser and operational proof gaps remain; this is not an all-Low or rollout claim. |
| 11 | Actual PostgreSQL might interpret the outbox namespace as driver placeholders or permit two lease owners. | High availability defect: two real database tests failed because a literal SQL percent sign was parsed as a placeholder; no alert request could be claimed. | [PostgreSQL checks](../../../services/operator-service/tests/test_alert_quality_postgres.py): all 4 passed with zero skips after parameterizing the namespace, including 16 competing claimers, stale-worker fencing, Settings CAS/restart, and competing terminal projections. | No known residual for this SQL defect. Database checks cover minimal state primitives, not provider, complete migration or deployment readiness. |
| 12 | Actual browser interaction might mix treatment axes, retry ambiguous writes or lose bounded layout. | No new functional defect; browser and coverage hardening. Routing incompleteness now uses the existing localized audience explanation. | [Browser checks](../../../console/tests/e2e/alert-quality.spec.ts): 10 passed; desktop three-axis requests and Settings, Korean 1440/993/390 geometry, missing/expired reports, conflict, unknown, anonymous and reduced-motion loading. TypeScript and 14 presentation tests passed. | [UI review](../../../console/alert-quality-hardening-review.md) records unmeasured accessibility/full-stack criteria; synthetic browser evidence is not Entra or Azure verification. |

Document, translation, link, and route checks establish documentation consistency only. The reported
focused baseline proves bounded implementation mechanics, not live delivery or safety in a tenant.
Operational adoption still requires real independently produced receipts and the open exits above.
Azure access, notification tests, model calls, promotion, publication, and deployment are not part
of this checkpoint; the ledger initiates none of them.
