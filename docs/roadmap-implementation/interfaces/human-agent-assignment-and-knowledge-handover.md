# Human-Agent Assignment and Knowledge Transfer implementation ledger

This delivery ledger preserves reviewable implementation scope, append-only transitions,
and resumable work while the roadmap owner remains focused on normative design.

## Implementation status

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| Stewardship v2 duties and coverage | implemented | `services/core-control-plane/src/fdai/core/stewardship/`; `services/core-control-plane/tests/core/stewardship/`; focused stewardship tests (71 passed) | The schema, deterministic migration, coverage, escalation, and notification primitives exist. Live directory coverage and deployment drills remain separate evidence. |
| Assignment case, independent review, and observation projection | implemented | `services/core-control-plane/src/fdai/core/human_assignment/`; `services/operator-service/src/fdai_operator_service/families/iam/assignments.py`; `console/src/routes/settings-iam-assignments.tsx`; focused human-assignment tests (43 passed) | Revisioned cases and the read-only API/console preserve role, duty, and authority separation. |
| Ownership proposal and matching-merge coordination | not-started | No assignment-aware stewardship governance service or handover draft publisher is composed. The signed intake in `services/document-ingestion-api/src/fdai_ingestion_api_service/adapters/stewardship.py` stores merge evidence only. | Until a digest-bound proposal and matching merge advance the case, ownership and IAM effects aren't an end-to-end workflow. |
| Governed human-access mutation capability | implemented | `services/core-control-plane/src/fdai/core/human_assignment/access_apply.py`; `services/core-control-plane/src/fdai/delivery/identity/entra_access.py`; `services/core-control-plane/src/fdai/delivery/identity/direct_api.py`; focused human-assignment tests (43 passed) | Allowlisted plan, apply, verify, and rollback mechanics exist in observation mode. They grant no console, requester, or target principal provider authority. |
| Human non-response supervision | implemented | `services/core-control-plane/src/fdai/core/hil_resume/escalation_supervisor.py`; `services/core-control-plane/src/fdai/runtime/bootstrap.py`; focused shadow-supervisor tests (10 passed) | The periodic worker is shadow-only; dispatch promotion and live rung-role evidence remain open. |
| Handover goals and fatigue controls | implemented | `services/core-control-plane/src/fdai/core/human_assignment/goals.py`; `services/core-control-plane/src/fdai/core/human_assignment/fatigue.py`; `services/core-control-plane/tests/core/human_assignment/test_goals.py` | Durable goal, invitation, evidence-reference, snooze, decline, and independent review mechanics exist. Agent gap production and localized Bragi rendering aren't bound. |
| Knowledge evidence and candidate lifecycle | in-progress | Existing document-ingestion chunk lineage and inert candidate contracts; focused ingestion tests | Goal-to-upload correlation, ACL-filtered retrieval evidence, agent candidate delivery, conflict review, and production deletion drills aren't complete. |
| Production promotion and operational proof | not-started | No retained promotion receipt, Azure permission probe, or production drill evidence is linked from this document. | IAM enforce, non-response dispatch, and proactive handover remain unavailable until their independent gates pass. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-08-13 | in-progress | Adopted the implementation ledger without reconstructing earlier provenance and separated implemented case, IAM, supervision, and goal mechanics from the missing ownership-to-IAM coordination. | `current change`; source and focused checks listed in the scope table. | Complete proposal and merge coordination, knowledge delivery, independent promotions, and operational evidence. |

### Remaining work

- [ ] Compose one digest-bound ownership proposal per approved case and pass focused tests proving only its matching signed merge advances the ownership effect.
- [ ] Publish one typed IAM apply request only after the matching ownership receipt, then prove allowlisted convergence and ownership-aware rollback without granting the ingestion or Operator services Graph write authority.
- [ ] Complete goal-to-upload binding, ACL-filtered retrieval, agent-owned gap and candidate events, localized Bragi rendering, conflict review, staleness, and deletion propagation.
- [ ] Retain separate promotion evidence for IAM mutation, non-response rung dispatch, and proactive handover; any exhausted approval must remain an audited no-op.
- [ ] Exercise add, reject, timeout, escalation, revoke, rollback, restart, provider outage, and disaster-recovery drills before marking the workflow `validated`.
