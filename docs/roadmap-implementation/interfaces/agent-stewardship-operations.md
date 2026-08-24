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
| Idempotent draft governance PR delivery | in-progress | [`governance.py`](../../../services/core-control-plane/src/fdai/core/stewardship/governance.py); [`test_governance.py`](../../../services/core-control-plane/tests/core/stewardship/test_governance.py) | `StewardshipGovernanceService` renders one shadow-labeled draft PR for `config/agent-stewardship.yaml` from a handover artifact and publishes it through `RemediationPrPublisher`. Retries reuse the content-addressed key, abstained and empty drafts never publish, and metadata carries no person value. Production composition and the ingestion worker binding are not wired. |
| Signed merge intake and downstream ownership effects | in-progress | `services/document-ingestion-api/src/fdai_ingestion_api_service/adapters/stewardship.py`; `services/document-ingestion-api/tests/test_ingestion_stewardship_webhook.py`; focused ingestion delivery tests (9 passed) | HMAC, repository, merge, changed-file, merged-content, and idempotent record checks exist. Resolver validation, affected-owner calculation, assignment digest matching, Saga audit, IAM trigger, and notification aren't composed. |
| Scheduled persisted identity health | in-progress | `services/core-control-plane/src/fdai/core/stewardship/directory.py`; `infra/modules/operator-api/container-app/main.tf` | Stale-OID evaluation and an interval setting exist, but no scheduled `StewardshipHealthMonitor` or `stewardship_health:*` snapshot and heartbeat composition was found. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-08-21 | implemented | Aligned the ingestion API's fallback Pantheon transport with the canonical `fdai.pantheon.objects` Event Bus topic. Terraform remains the naming authority, and the change does not alter stewardship resolution, notification ordering, RBAC, approval, or execution authority. | `current change`; ingestion composition defaults, Event Bus naming contract, and focused independent-service checks. | Retain the protected Event Bus migration and post-apply transport receipt tracked by the deployment naming owner. |
| 2026-08-18 | in-progress | Made the ingestion API composition that builds the stewardship webhook and repository handover intake resolve its execution venue through the shared contract instead of a private parser, so a venue-selected credential or endpoint cannot diverge from the other services. No stewardship lifecycle behavior changed. | `current change`; `services/document-ingestion-api/tests` passed with the other independent service suites at 874 focused cases and 1 skip; the venue gate reported OK across 6 source trees. | The unwired post-merge ownership effects and scheduled identity health below remain open. |
| 2026-08-13 | in-progress | Adopted the implementation ledger without reconstructing earlier provenance and corrected the lifecycle claim to distinguish startup, draft generation, signed merge intake, and unimplemented operational effects. | `current change`; source and focused checks listed in the scope table. | Wire governance PR publication, complete post-merge effects and scheduled identity health, then retain runtime evidence. |
| 2026-08-16 | in-progress | Composed the idempotent handover-artifact-to-`RemediationPrPublisher` path with a content-addressed key, review-only rendering, and fail-closed draft validation. | `pytest services/core-control-plane/tests/core/stewardship/test_governance.py` passed 9 focused tests, including retry reuse of one draft PR after an ambiguous transport failure and bounded warning rendering in the PR body. | Bind the service in production composition, complete post-merge ownership effects, and add scheduled identity health. |

### Remaining work

- [x] Compose an idempotent handover-artifact-to-`RemediationPrPublisher` path and pass a focused test proving that retries reuse one draft PR for `config/agent-stewardship.yaml`.
- [ ] Bind `StewardshipGovernanceService` into production composition so a stored handover draft reaches a real GitOps publisher, validate the rendered YAML through the core resolver before publication, store the returned PR reference and replay flag on the artifact, and retain the resulting draft-PR receipt.
- [ ] Validate merged stewardship YAML through the resolver, calculate affected owners, bind assignment proposal digests, and pass focused tests proving Saga audit, IAM-request publication, and recipient notification each occur once.
- [ ] Implement the scheduled identity-health monitor and retain tests proving transition-only audit, revision-matched heartbeat refresh, expiry, and Graph-failure behavior under `stewardship_health:current` and `stewardship_health:last_success`.
- [ ] Retain a deployment receipt and operational drill showing real startup bindings, one guided proposal and reviewed merge, notification delivery, audit closure, and stale-to-clean identity recovery before raising any row to `validated`.

The grounded T2 `HandoverInterpreter` remains an optional deployment binding. The deterministic
extractor and exact Graph resolution work without it, and the default interpreter holds for review
instead of guessing.
