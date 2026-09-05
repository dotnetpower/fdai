# Human-Agent Assignment and Knowledge Transfer implementation ledger

This delivery ledger preserves reviewable implementation scope, append-only transitions,
and resumable work while the roadmap owner remains focused on normative design.

## Implementation status

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| Stewardship v2 duties and coverage | implemented | `services/core-control-plane/src/fdai/core/stewardship/`; `services/core-control-plane/tests/core/stewardship/`; focused stewardship tests (71 passed) | The schema, deterministic migration, coverage, escalation, and notification primitives exist. Live directory coverage and deployment drills remain separate evidence. |
| Assignment case, independent review, and observation projection | implemented | `services/core-control-plane/src/fdai/core/human_assignment/`; `services/operator-service/src/fdai_operator_service/families/iam/assignments.py`; `console/src/routes/settings-iam-assignments.tsx`; focused human-assignment tests (43 passed) | Revisioned cases and the read-only API/console preserve role, duty, and authority separation. |
| Ownership proposal and matching-merge coordination | in-progress | `ownership_coordination.py`; `test_ownership_coordination.py`; signed stewardship webhook | Digest-bound proposal and exact merge verification exist. Production GitOps publication, merge consumption, IAM convergence, and retained restart evidence remain open. |
| Governed human-access mutation capability | implemented | `services/core-control-plane/src/fdai/core/human_assignment/access_apply.py`; `services/core-control-plane/src/fdai/delivery/identity/entra_access.py`; `services/core-control-plane/src/fdai/delivery/identity/direct_api.py`; focused human-assignment tests (43 passed) | Allowlisted plan, apply, verify, and rollback mechanics exist in observation mode. They grant no console, requester, or target principal provider authority. |
| Human non-response supervision | implemented | `services/core-control-plane/src/fdai/core/hil_resume/escalation_supervisor.py`; `services/core-control-plane/src/fdai/runtime/bootstrap.py`; focused shadow-supervisor tests (10 passed) | The periodic worker is shadow-only; dispatch promotion and live rung-role evidence remain open. |
| Handover goals and fatigue controls | implemented | `services/core-control-plane/src/fdai/core/human_assignment/goals.py`; `services/core-control-plane/src/fdai/core/human_assignment/fatigue.py`; `services/core-control-plane/tests/core/human_assignment/test_goals.py` | Durable goal, invitation, evidence-reference, snooze, decline, and independent review mechanics exist. Agent gap production and localized Bragi rendering aren't bound. |
| Proactive web handover session | implemented | `families/iam/handover_runtime.py`; `console/src/handover-{api,invitation,model}.ts`; focused Operator and Console checks | Sign-in checks the current live ownership projection, creates one replay-safe invitation, enforces a two-session weekly budget, opens the mapped agent conversation, and exposes upload, snooze, and decline controls. Deployment receipts remain separate. |
| Knowledge evidence and candidate lifecycle | in-progress | Existing document-ingestion chunk lineage and inert candidate contracts; focused ingestion tests | Goal-to-upload correlation, ACL-filtered retrieval evidence, agent candidate delivery, conflict review, and production deletion drills aren't complete. |
| Web handover document association | implemented | `console/src/routes/document-ingestion.tsx`; Operator revisioned goal evidence command; focused Console and Operator checks | The existing governed upload consent and terminal admission path records one canonical document evidence candidate on the goal. Independent acceptance, agent retrieval, and candidate promotion remain separate work. |
| Production promotion and operational proof | not-started | No retained promotion receipt, Azure permission probe, or production drill evidence is linked from this document. | IAM enforce, non-response dispatch, and proactive handover remain unavailable until their independent gates pass. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-08-13 | in-progress | Adopted the implementation ledger without reconstructing earlier provenance and separated implemented case, IAM, supervision, and goal mechanics from the missing ownership-to-IAM coordination. | `current change`; source and focused checks listed in the scope table. | Complete proposal and merge coordination, knowledge delivery, independent promotions, and operational evidence. |
| 2026-09-05 | implemented | Added the server-owned proactive web handover slice: live ownership revalidation, replay-safe session and weekly invitation fences, revisioned goal commands, mapped-agent conversation routing, and governed document evidence association. Corrected the earlier ownership-coordination state to match existing source. | `current change`; `test_handover_runtime.py`, `test_operator_iam_family.py`, focused Console tests, Console typecheck, and Console build. | Retain deployment receipts, bind post-merge effects, and complete agent retrieval, conflict review, staleness, and deletion propagation. |

### Remaining work

- [x] Compose one digest-bound ownership proposal per approved case and pass focused tests proving only its matching signed merge advances the ownership effect.
- [ ] Publish one typed IAM apply request only after the matching ownership receipt, then prove allowlisted convergence and ownership-aware rollback without granting the ingestion or Operator services Graph write authority.
- [ ] Complete ACL-filtered agent retrieval, agent-owned gap and candidate events, localized Bragi rendering, conflict review, staleness, and deletion propagation; the governed web goal-to-upload association now has focused passing evidence.
- [ ] Retain separate promotion evidence for IAM mutation, non-response rung dispatch, and proactive handover; any exhausted approval must remain an audited no-op.
- [ ] Exercise add, reject, timeout, escalation, revoke, rollback, restart, provider outage, and disaster-recovery drills before marking the workflow `validated`.
