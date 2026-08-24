# Human-Agent Assignment Implementation Plan implementation ledger

This delivery ledger preserves reviewable implementation scope, append-only transitions,
and resumable work while the roadmap owner remains focused on normative design.

## Implementation status

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| Packages 1-3: duties, assignment core, API, and console | implemented | `services/core-control-plane/src/fdai/core/stewardship/`; `services/core-control-plane/src/fdai/core/human_assignment/`; `services/operator-service/src/fdai_operator_service/families/iam/assignments.py`; `console/src/routes/settings-iam-assignments.tsx`; focused human-assignment tests (43 passed) | These packages establish observation-only intent and projection without provider mutation. |
| Package 4: ownership PR coordination | not-started | No `StewardshipGovernanceService` or equivalent assignment-aware publisher exists; the current signed webhook records merge evidence without case or candidate-digest correlation. | This missing dependency prevents the assignment workflow from proving ownership convergence or emitting its IAM prerequisite. |
| Package 5: human-access provider capability | implemented | `services/core-control-plane/src/fdai/core/human_assignment/access_apply.py`; `services/core-control-plane/src/fdai/delivery/identity/entra_access.py`; `services/core-control-plane/src/fdai/delivery/identity/direct_api.py`; focused human-assignment tests (43 passed) | Observation-only allowlist, convergence, and rollback mechanics exist, but Package 4 doesn't yet trigger them from an assignment case. |
| Package 6: non-response supervisor | implemented | `services/core-control-plane/src/fdai/core/hil_resume/escalation_supervisor.py`; `services/core-control-plane/src/fdai/runtime/bootstrap.py`; focused shadow-supervisor tests (10 passed) | Periodic shadow observation exists; production rung dispatch isn't promoted. |
| Package 7: handover goal core and commands | implemented | `services/core-control-plane/src/fdai/core/human_assignment/goals.py`; `services/operator-service/src/fdai_operator_service/families/iam/handover.py`; focused human-assignment tests (43 passed) | Durable invitations and response commands exist. Agent gap production and localized Bragi rendering remain unbound. |
| Package 8: knowledge evidence delivery | in-progress | `packages/service-contracts/src/fdai_service_contracts/document.py`; existing ingestion chunk-lineage tests | Optional goal references and deterministic evidence metadata exist; goal-to-upload correlation, candidate delivery, ACL retrieval, review, and deletion drills remain open. |
| Package 9: production rollout | in-progress | `services/core-control-plane/src/fdai/core/human_assignment/production_controls.py`; `services/core-control-plane/src/fdai/runtime/human_assignment_reconciliation.py`; `services/core-control-plane/src/fdai/delivery/runtime_settings.py` | Capability axes and observation-only reconciliation exist. Enforce promotion, Azure permission probes, dashboards, alerts, automatic repair, and production drills aren't complete. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-08-13 | in-progress | Adopted the implementation ledger without reconstructing earlier provenance and corrected Package 4 and Package 5 dependency claims. | `current change`; source and focused checks listed in the scope table. | Implement Package 4, finish Packages 8-9, and collect promotion and operational evidence. |

### Remaining work

- [ ] Implement Package 4 with one idempotent, digest-bound stewardship proposal and a signed matching-merge receipt that advances only its assignment case.
- [ ] Publish the typed IAM apply request only from that matching receipt and prove no ownership, review, IAM, or executor authority collapses across the event boundary.
- [ ] Complete agent-owned handover gap production, localized Bragi rendering, goal-to-upload binding, candidate delivery, ACL retrieval, conflict review, staleness, and deletion propagation.
- [ ] Run and retain the Package 9 Azure permission probes, non-production mutation and rollback drills, shadow comparisons, dashboards, alerts, and restart and outage recovery evidence.
- [ ] Promote IAM mutation, non-response dispatch, and proactive handover independently only after their rollout thresholds pass; preserve audited no-op behavior on exhaustion or insufficient evidence.
