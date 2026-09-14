# Human-Agent Assignment Implementation Plan implementation ledger

This delivery ledger preserves reviewable implementation scope, append-only transitions,
and resumable work while the roadmap owner remains focused on normative design.

## Implementation status

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| Packages 1-3: duties, assignment core, API, and console | implemented | `services/core-control-plane/src/fdai/core/stewardship/`; `services/core-control-plane/src/fdai/core/human_assignment/`; `services/operator-service/src/fdai_operator_service/families/iam/assignments.py`; `console/src/routes/settings-iam-assignments.tsx`; focused human-assignment tests (43 passed) | These packages establish observation-only intent and projection without provider mutation. |
| Package 4: ownership PR coordination | implemented | `assignment_transport.py`; `assignment_workflow.py`; `assignment_outcome_consumer.py`; `ownership_coordination.py`; `test_assignment_workflow.py`; `test_assignment_receipt_postgres.py` | Immutable Operator requests now pass the fixed-agent review/seal chain to a canonical Core case and one review-only PR. Matching merge records ownership only; deployed identity, App, notification, IAM, and operational evidence remain independent. |
| Package 5: human-access provider capability | implemented | `services/core-control-plane/src/fdai/core/human_assignment/access_apply.py`; `services/core-control-plane/src/fdai/delivery/identity/entra_access.py`; `services/core-control-plane/src/fdai/delivery/identity/direct_api.py`; focused human-assignment tests (43 passed) | Observation-only allowlist, convergence, and rollback mechanics exist, but Package 4 doesn't yet trigger them from an assignment case. |
| Package 6: non-response supervisor | implemented | `services/core-control-plane/src/fdai/core/hil_resume/escalation_supervisor.py`; `services/core-control-plane/src/fdai/runtime/bootstrap.py`; focused shadow-supervisor tests (10 passed) | Periodic shadow observation exists; production rung dispatch isn't promoted. |
| Package 7: handover goal core and commands | implemented | `goals.py`; `handover_runtime.py`; `handover.py`; `handover_knowledge_lifecycle.py`; focused Core, Operator, and Console checks | Durable invitations include live ownership revalidation, weekly fatigue fencing, localized rendering, server-bound agent routing, snooze, decline, busy-work suppression, and agent-owned gap production. |
| Package 8: knowledge evidence delivery | in-progress | document contracts; `knowledge_handover.py`; `handover_knowledge_lifecycle.py`; `postgres_handover_goals.py`; real service-role and bounded-scan tests | Upload binding, ACL retrieval, typed read-only observation, and inert event production exist. Accountable candidate consumers, conflict/deletion closure, and governed provider evidence are not proved by those producer primitives. |
| Package 9: production rollout | in-progress | `services/core-control-plane/src/fdai/core/human_assignment/production_controls.py`; `services/core-control-plane/src/fdai/runtime/human_assignment_reconciliation.py`; `services/core-control-plane/src/fdai/delivery/runtime_settings.py` | Capability axes and observation-only reconciliation exist. Enforce promotion, Azure permission probes, dashboards, alerts, automatic repair, and production drills aren't complete. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-09-14 | implemented | Completed the first safety hardening slice and corrected stale direct-main and missing-producer descriptions. Goal command/replay authorization and bounded reconciliation now have executable regressions. | `current change`; five focused test files passed 115 cases; changed-source Ruff and strict mypy passed. | Complete the typed producer/consumer and effect lifecycle work in #946 without treating source delivery as #458 operational validation. |
| 2026-09-01 | in-progress | Implemented the Package 4 coordination core: one idempotent shadow ownership draft, exact merge correlation, ownership receipt, and typed shadow IAM request. | `current change`; `ownership_coordination.py`; `test_ownership_coordination.py`; focused ownership and access-apply tests passed. | Bind production GitOps and signed merge consumption, then retain restart and delivery evidence before marking Package 4 implemented. |
| 2026-09-05 | implemented | Completed the production-composed web portion of Package 7 and the goal-to-upload portion of Package 8 with live ownership revalidation, bounded proactive invitations, revisioned commands, mapped-agent conversations, and governed document receipts. | `current change`; focused Operator and Console tests, Console typecheck, and Console build. | Complete agent-authored gaps, server retrieval, post-merge effects, lifecycle propagation, and governed deployment evidence. |
| 2026-09-05 | implemented | Hardened Package 7 and 8 boundaries with server-owned conversation binding and least-privilege authoritative document verification. | `current change`; focused Operator, Console, and service migration inventory tests passed. | Complete the remaining production and knowledge-lifecycle evidence. |
| 2026-09-05 | implemented | Added server-owned busy-work suppression and read-time evidence staleness propagation. | `current change`; focused Operator tests passed. | Complete agent-authored gaps, agent retrieval, and candidate promotion. |
| 2026-08-13 | in-progress | Adopted the implementation ledger without reconstructing earlier provenance and corrected Package 4 and Package 5 dependency claims. | `current change`; source and focused checks listed in the scope table. | Implement Package 4, finish Packages 8-9, and collect promotion and operational evidence. |
| 2026-09-05 | implemented | Completed Package 4 production composition and the local Package 8 lifecycle with signed merge effects, identity health, agent-owned gaps, ACL-bound retrieval, review-only candidates, conflicts, and stale withdrawals. | `current change`; focused Core and Operator checks; Core service Terraform validation. | Retain governed deployment, promotion, restart, outage, rollback, and disaster-recovery evidence. |
| 2026-09-05 | implemented | Completed Package 4 production composition and Package 8 local lifecycle without joining ownership, IAM, review, or execution authority. | `current change`; focused Core and Operator checks; Core service Terraform validation. | Retain governed deployment, promotion, restart, outage, rollback, and disaster-recovery evidence. |


### Remaining work

- [x] Complete S2 immutable receipt/outbox, agent-owned command chain, canonical result projection,
  and approved-case PR initiation with actual PostgreSQL service-role evidence.
- [ ] Complete S3 governed IAM/replacement coverage and catalog-backed current HIL eligibility.
- [ ] Complete S4 required-slot/backup acceptance, session budgets, accountable knowledge consumers,
  and honest Console convergence/recovery views. Historical checked producer items below do not
  constitute end-to-end acceptance of this remaining work.

- [x] Compose Package 4 with the production GitOps publisher and signed merge record consumer, and retain restart-safe local evidence that only the matching merge advances its assignment case.
- [x] Publish the typed shadow IAM apply request only from that matching receipt and prove no ownership, review, IAM, or executor authority collapses across the event boundary.
- [x] Complete agent-owned handover gap production, review-only candidate delivery, ACL-filtered agent retrieval, conflict fencing, and staleness/deletion propagation.
- [ ] Run and retain the Package 9 Azure permission probes, non-production mutation and rollback drills, shadow comparisons, dashboards, alerts, and restart and outage recovery evidence.
- [ ] Promote IAM mutation, non-response dispatch, and proactive handover independently only after their rollout thresholds pass; preserve audited no-op behavior on exhaustion or insufficient evidence.
- [x] Implement Package 4 with one idempotent, digest-bound stewardship proposal and a signed matching-merge receipt that advances only its assignment case.

- [x] Complete agent-owned handover gap production, localized Bragi rendering, goal-to-upload binding, review-only candidate delivery, ACL retrieval, conflict review, staleness, and deletion propagation.

### Subsequent implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-09-14 | implemented | Connected immutable Operator requests through Huginn/Forseti/Var/Saga/Muninn to one review-only ownership PR; introduced exact case command receipts, SQL ownership guards, Core effect reads, and a content-free knowledge observation port. Completed 13 distinct S2 critique/hardening rounds. | `current change`; [review record](../../internals/handover-lifecycle-hardening-20260914.md); 355 focused tests passed, one unrelated optional PDF test skipped;14 real PostgreSQL tests;36 source modules pass strict mypy; lint passes. | S3-S6 and external deployment/promotion gates remain open under #946/#458; no live authority was granted. |
