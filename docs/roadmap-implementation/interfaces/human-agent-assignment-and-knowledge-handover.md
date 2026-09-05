# Human-Agent Assignment and Knowledge Transfer implementation ledger

This delivery ledger preserves reviewable implementation scope, append-only transitions,
and resumable work while the roadmap owner remains focused on normative design.

## Implementation status

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| Stewardship v2 duties and coverage | implemented | `services/core-control-plane/src/fdai/core/stewardship/`; `services/core-control-plane/tests/core/stewardship/`; focused stewardship tests (71 passed) | The schema, deterministic migration, coverage, escalation, and notification primitives exist. Live directory coverage and deployment drills remain separate evidence. |
| Assignment case, independent review, and observation projection | implemented | `services/core-control-plane/src/fdai/core/human_assignment/`; `services/operator-service/src/fdai_operator_service/families/iam/assignments.py`; `console/src/routes/settings-iam-assignments.tsx`; focused human-assignment tests (43 passed) | Revisioned cases and the read-only API/console preserve role, duty, and authority separation. |
| Ownership proposal and matching-merge coordination | implemented | `ownership_coordination.py`; `stewardship_merge_effects.py`; signed stewardship webhook; focused coordination tests | Production composition consumes a signed merge, verifies the proposal digest, records the ownership effect, notifies affected owners, publishes a replay-stable shadow IAM request, and retains one Saga receipt. |
| Governed human-access mutation capability | implemented | `services/core-control-plane/src/fdai/core/human_assignment/access_apply.py`; `services/core-control-plane/src/fdai/delivery/identity/entra_access.py`; `services/core-control-plane/src/fdai/delivery/identity/direct_api.py`; focused human-assignment tests (43 passed) | Allowlisted plan, apply, verify, and rollback mechanics exist in observation mode. They grant no console, requester, or target principal provider authority. |
| Human non-response supervision | implemented | `services/core-control-plane/src/fdai/core/hil_resume/escalation_supervisor.py`; `services/core-control-plane/src/fdai/runtime/bootstrap.py`; focused shadow-supervisor tests (10 passed) | The periodic worker is shadow-only; dispatch promotion and live rung-role evidence remain open. |
| Handover goals and fatigue controls | implemented | `services/core-control-plane/src/fdai/core/human_assignment/goals.py`; `services/core-control-plane/src/fdai/core/human_assignment/fatigue.py`; `services/core-control-plane/tests/core/human_assignment/test_goals.py` | Durable goal, invitation, evidence-reference, snooze, decline, and independent review mechanics exist. Agent gap production and localized Bragi rendering aren't bound. |
| Proactive web handover session | implemented | `handover_runtime.py`; `handover_binding.py`; `console/src/handover-{api,invitation,model}.ts`; focused Operator and Console checks | Sign-in checks the current live ownership projection, creates one replay-safe invitation, and enforces a two-session weekly budget. A fail-closed activity guard suppresses invitations while incident or human-approval work is active, and the server durably binds principal, goal, session, and agent. |
| Knowledge evidence and candidate lifecycle | implemented | `knowledge_handover.py`; `handover_knowledge_lifecycle.py`; existing document chunk lineage; focused lifecycle and retrieval tests | Goal-bound retrieval fails closed across principal or source ACL boundaries. Agent gaps, evidence, review-only candidates, conflicts, and stale withdrawals use content-free events. |
| Web handover document association | implemented | `console/src/routes/document-ingestion.tsx`; `PostgresHandoverEvidenceVerifier`; Operator revisioned goal evidence command; focused Console and Operator checks | Goal evidence becomes reviewable only after authoritative document metadata verifies the same uploader, canonical ids, admitted state, active availability, and source digest. A later read marks the goal stale when deletion, revocation, or replacement removes that admission. |
| Production promotion and operational proof | not-started | No retained promotion receipt, Azure permission probe, or production drill evidence is linked from this document. | IAM enforce, non-response dispatch, and proactive handover remain unavailable until their independent gates pass. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-08-13 | in-progress | Adopted the implementation ledger without reconstructing earlier provenance and separated implemented case, IAM, supervision, and goal mechanics from the missing ownership-to-IAM coordination. | `current change`; source and focused checks listed in the scope table. | Complete proposal and merge coordination, knowledge delivery, independent promotions, and operational evidence. |
| 2026-09-05 | implemented | Added the server-owned proactive web handover slice: live ownership revalidation, replay-safe session and weekly invitation fences, revisioned goal commands, mapped-agent conversation routing, and governed document evidence association. Corrected the earlier ownership-coordination state to match existing source. | `current change`; `test_handover_runtime.py`, `test_operator_iam_family.py`, focused Console tests, Console typecheck, and Console build. | Retain deployment receipts, bind post-merge effects, and complete agent retrieval, conflict review, staleness, and deletion propagation. |
| 2026-09-05 | implemented | Hardened handover turns so the server verifies and durably binds principal, goal, session, and agent before semantic persistence. Goal evidence now requires a least-privilege authoritative document verification result. | `current change`; focused Operator tests, Console payload tests, and service migration inventory tests passed. | Retain deployment receipts and complete the remaining lifecycle work. |
| 2026-09-05 | implemented | Added fail-closed incident and approval suppression plus read-time evidence revalidation that marks affected goals stale after document deletion, revocation, or replacement. | `current change`; focused Operator tests passed. | Complete agent-authored gaps, ACL-filtered retrieval, and candidate promotion. |
| 2026-09-05 | implemented | Bound signed merge effects, scheduled identity health, agent-owned gaps, ACL-filtered retrieval, review-only candidates, conflict events, and stale evidence withdrawal. | `current change`; focused Core and Operator checks; Core service Terraform validation. | Retain governed deployment and independent promotion evidence. |

### Remaining work

- [x] Compose one digest-bound ownership proposal per approved case and pass focused tests proving only its matching signed merge advances the ownership effect.
- [x] Publish one typed shadow IAM apply request only after the matching ownership receipt without granting the ingestion or Operator services Graph write authority.
- [x] Complete ACL-filtered agent retrieval, agent-owned gap and review-only candidate events, localized Bragi rendering, conflict fencing, and read-time staleness/deletion propagation.
- [ ] Retain separate promotion evidence for IAM mutation, non-response rung dispatch, and proactive handover; any exhausted approval must remain an audited no-op.
- [ ] Exercise add, reject, timeout, escalation, revoke, rollback, restart, provider outage, and disaster-recovery drills before marking the workflow `validated`.
