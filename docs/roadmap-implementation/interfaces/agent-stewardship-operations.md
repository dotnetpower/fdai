# Agent Operational Ownership Lifecycle implementation ledger

This delivery ledger preserves reviewable implementation scope, append-only transitions,
and resumable work while the roadmap owner remains focused on normative design.

## Implementation status

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| Startup binding and read-only projection | implemented | `services/operator-service/src/fdai_operator_service/`; `services/operator-service/tests/test_operator_operations_family.py`; `tests/integration/infra/test_operator_api_stewardship.py`; focused Operator and Terraform tests (15 passed) | The route and deployment bindings exist. Source wiring doesn't by itself prove a live deployment is ready. |
| Terraform binding completeness gates | implemented | `infra/production-gates.tf`; `infra/modules/operator-api/container-app/main.tf`; `tests/integration/infra/test_operator_api_stewardship.py` | Production configuration requires maintainers and every non-autonomous agent binding while keeping identities deployment-owned. |
| Guided registration and grounded durable draft | implemented | `console/src/routes/handover-editor.tsx`; `services/document-processing-worker/src/fdai_document_worker_service/handover.py`; focused console tests (21 passed); focused ingestion delivery tests (9 passed) | The SPA submits a governed upload and the worker stores a review-only draft. Neither effect changes the active map. |
| Idempotent draft governance PR delivery | implemented | `governance.py`; `stewardship_governance.py`; focused governance tests | Durable artifacts reach the configured publisher with complete tracked-YAML validation and content-addressed Saga receipts. |
| Signed merge intake and downstream ownership effects | implemented | signed intake; `stewardship_merge_effects.py`; focused merge and ownership tests | Core validates the merged map, notifies affected owners, advances only a digest-matched assignment, and publishes the replay-stable shadow IAM request. |
| Scheduled persisted identity health | implemented | `stewardship_identity_health.py`; Operator ownership projection; Core service Terraform | Transition-only health and expiring successful observations survive Graph failure and are projected only when revision matched and current. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-08-21 | implemented | Aligned the ingestion API's fallback Pantheon transport with the canonical `fdai.pantheon.objects` Event Bus topic. Terraform remains the naming authority, and the change does not alter stewardship resolution, notification ordering, RBAC, approval, or execution authority. | `current change`; ingestion composition defaults, Event Bus naming contract, and focused independent-service checks. | Retain the protected Event Bus migration and post-apply transport receipt tracked by the deployment naming owner. |
| 2026-08-18 | in-progress | Made the ingestion API composition that builds the stewardship webhook and repository handover intake resolve its execution venue through the shared contract instead of a private parser, so a venue-selected credential or endpoint cannot diverge from the other services. No stewardship lifecycle behavior changed. | `current change`; `services/document-ingestion-api/tests` passed with the other independent service suites at 874 focused cases and 1 skip; the venue gate reported OK across 6 source trees. | The unwired post-merge ownership effects and scheduled identity health below remain open. |
| 2026-08-13 | in-progress | Adopted the implementation ledger without reconstructing earlier provenance and corrected the lifecycle claim to distinguish startup, draft generation, signed merge intake, and unimplemented operational effects. | `current change`; source and focused checks listed in the scope table. | Wire governance PR publication, complete post-merge effects and scheduled identity health, then retain runtime evidence. |
| 2026-08-16 | in-progress | Composed the idempotent handover-artifact-to-`RemediationPrPublisher` path with a content-addressed key, review-only rendering, and fail-closed draft validation. | `pytest services/core-control-plane/tests/core/stewardship/test_governance.py` passed 9 focused tests, including retry reuse of one draft PR after an ambiguous transport failure and bounded warning rendering in the PR body. | Bind the service in production composition, complete post-merge ownership effects, and add scheduled identity health. |
| 2026-09-05 | implemented | Completed production composition for draft delivery, signed merge effects, affected-owner notification, matching assignment IAM requests, and scheduled identity health. | `current change`; focused Core and Operator checks; Core service Terraform validation. | Retain governed deployment and operational drill evidence. |

### Remaining work

- [x] Compose an idempotent handover-artifact-to-`RemediationPrPublisher` path and pass a focused test proving that retries reuse one draft PR for `config/agent-stewardship.yaml`.
- [x] Bind `StewardshipGovernanceService` into production composition so stored drafts reach the configured GitOps publisher with complete validation and content-addressed receipts.
- [x] Validate merged stewardship YAML, calculate affected owners, bind assignment proposal digests, and prove Saga audit, replay-stable IAM requests, and recipient notification.
- [x] Implement scheduled identity health with transition-only audit, revision-matched expiring success, Graph-failure preservation, and read-only Operator projection.
- [ ] Retain a deployment receipt and operational drill showing real startup bindings, one guided proposal and reviewed merge, notification delivery, audit closure, and stale-to-clean identity recovery before raising any row to `validated`.

The grounded T2 `HandoverInterpreter` remains an optional deployment binding. The deterministic
extractor and exact Graph resolution work without it, and the default interpreter holds for review
instead of guessing.
