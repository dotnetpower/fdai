# Hyperscale Cell Architecture (Plan B) implementation ledger

This delivery ledger preserves reviewable implementation scope, append-only transitions,
and resumable work while the roadmap owner remains focused on normative design.

## Implementation status

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| Cell topology and deterministic routing | not-started | [Phase 4 scale plan](../../roadmap/phases/phase-4-scale.md#scalability-and-performance); no `CellRouter`, cell topology manifest, or per-cell infrastructure module exists in the current source | The minimum-cost deployment remains one logical cell. Crossing a measured hyperscale trigger is required before this topology is implemented. |
| CQRS audit ledger and asynchronous index plane | not-started | [Audit ledger CQRS](../../roadmap/architecture/hyperscale-cell-architecture.md#audit-ledger-cqrs-write-plane--index-plane); current audit persistence in `services/core-control-plane/src/fdai/delivery/persistence/postgres.py` | The current path retains its PostgreSQL audit contract. No `AuditLedger`, `AuditQueryStore`, partitioned audit topic, Merkle anchor, or audit-indexer implementation is present. |
| ADX telemetry tiering and cell-scoped degradation | not-started | [Indexing and query at scale](../../roadmap/architecture/hyperscale-cell-architecture.md#indexing-and-query-at-scale); [Phase 4 scale plan](../../roadmap/phases/phase-4-scale.md#runtime-scale-out-aks---deferred) | Existing telemetry provider seams and system-level degradation are prerequisites, not evidence of the Plan B ADX, per-cell, or sovereign runtime. |
| Policy fan-in and deployment profiles | not-started | [Fan-in design](../../roadmap/architecture/hyperscale-cell-architecture.md#fan-in-policy-driven-not-code); [Deployment profiles](../../roadmap/architecture/hyperscale-cell-architecture.md#deployment-profiles-standard-vs-sovereign) | No management-group `DeployIfNotExists` package, `deployment.profile` binding, sovereign AKS render, or profile-specific Terraform composition is implemented. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-08-14 | deferred | Adopted the implementation ledger without reconstructing earlier provenance and recorded Plan B as trigger-gated Phase 4 work. | `current change`; current source boundaries and the Phase 4 owner document cited in the scope table. | Measure a hyperscale trigger, approve the profile and cell boundary, then implement and validate the bounded work below. |

### Remaining work

- [ ] Record a reviewed capacity and governance receipt showing that at least one hyperscale trigger in this document is met on one pinned deployment revision.
- [ ] Implement `CellRouter`, the topology manifest, and one additional isolated cell, then prove deterministic assignment, per-cell degradation, replay, and unchanged authority in focused tests.
- [ ] Implement the partitioned audit write plane, Merkle anchoring, asynchronous indexer, and ADX or approved sovereign telemetry binding, then retain load, recovery, and tamper-evidence receipts.
- [ ] Add reviewed `standard` and `sovereign` deployment-profile bindings plus policy fan-in infrastructure, then retain protected plan and apply evidence for the selected profile.
