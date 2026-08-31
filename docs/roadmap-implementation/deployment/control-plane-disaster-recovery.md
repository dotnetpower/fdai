# Control-Plane Disaster Recovery implementation ledger

This delivery ledger preserves reviewable implementation scope, append-only transitions,
and resumable work while the roadmap owner remains focused on normative design.

## Implementation status

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| Immutable recovery plan and legal transition reducer | implemented | `services/core-control-plane/src/fdai/core/verticals/resilience/recovery_plan.py` and `services/core-control-plane/tests/core/verticals/test_recovery_plan.py` | Version, approval separation, recovery epochs, legal edges, and halt behavior have focused tests. |
| Durable compare-and-set coordination and audit persistence | implemented | `services/core-control-plane/src/fdai/core/verticals/resilience/recovery_coordinator.py` and `services/core-control-plane/tests/core/verticals/test_recovery_coordinator.py` | Exact redelivery, write conflicts, revision checks, and atomic state-plus-audit writes are implemented. |
| Opt-in database restore drill and verifier | implemented | `services/core-control-plane/src/fdai/delivery/db_dr_drill_cli.py`, `delivery/azure/db_dr_restore.py`, `delivery/db_dr_postgres.py`, `infra/modules/compute/container-apps/dr_drill_job.tf`, and focused DR drill tests | The delivery-owned job composes Azure restore, bounded PostgreSQL integrity and smoke, teardown, and durable audit while Core remains provider-neutral. It defaults to dry-run and uses a dedicated non-executor identity. Source and tests don't prove a completed substrate-backed drill. |
| Provider-neutral regional shadow sequence | implemented | `services/core-control-plane/src/fdai/shared/providers/control_plane_recovery.py`, `services/core-control-plane/src/fdai/core/verticals/resilience/shadow_recovery.py`, and `services/core-control-plane/tests/core/verticals/test_recovery_plan_shadow.py` | The fake provider proves order, stale-epoch rejection, failure halt, single-writer behavior, bounded replay input, and failback prerequisites without applying effects. |
| Regional provider adapters and event-data continuity | not-started | `docs/runbooks/control-plane-failover.md` | No deployment provider binds provisioning, fencing, event replay, traffic shift, or failback, and no substrate event-continuity evidence exists. |
| Single-process scheduled execution | implemented | `infra/modules/compute/container-apps/*_job.tf`; `tests/integration/infra/test_scheduled_job_concurrency.py` | Every scheduled Container Apps Job pins `replica_completion_count` and `parallelism` to `1`, and every job declares exactly one trigger kind, so one tick runs in exactly one process. The focused check fails when a schedule block does not parse, when a value is relaxed, or when a job declares a second trigger. |
| Measured regional failover and failback | not-started | `docs/runbooks/control-plane-failover.md` | The repository contains no governed drill receipt proving approved RPO/RTO, stale-epoch fencing, event completeness, traffic shift, and failback. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-08-31 | implemented | Bound the opt-in database restore job to a complete delivery-owned Azure and PostgreSQL verifier path and separated its identity from the executor. Partial restore and cleanup failure stay explicit, and complete dry-run configuration makes no provider request. | `current change`; delivery adapters and CLI, root and compute Terraform, focused restore, integrity, CLI, verifier, and infrastructure checks. | Retain one governed substrate-backed DB-DR receipt with measured RPO/RTO and verified cleanup. |
| 2026-08-14 | in-progress | Adopted the implementation ledger; earlier provenance was not reconstructed. Separated tested recovery mechanics from regional deployment and operational evidence. | current change; focused recovery plan and coordinator tests listed in the scope table | Compose and exercise the regional provider path, then retain governed failover and failback evidence. |
| 2026-08-15 | implemented | Constrained scheduled execution to one process through reviewable Terraform configuration and added a focused concurrency check over every scheduled Job. | `current change`; `tests/integration/infra/test_scheduled_job_concurrency.py`; `pytest tests/integration/infra/test_scheduled_job_concurrency.py` (24 passed). | Cross-process experiment reservation, the composed regional path, and the governed drill receipt remain open. |
| 2026-08-24 | implemented | Added the provider-neutral regional action contract and a pure shadow orchestrator that halts on stale epochs, failed receipts, unsafe writer state, or missing failback prerequisites. | `current change`; `control_plane_recovery.py`; `shadow_recovery.py`; `test_recovery_plan_shadow.py`; `python -m pytest -q --no-cov services/core-control-plane/tests/core/verticals/test_recovery_plan_shadow.py` (10 passed). | Bind a deployment provider, prove substrate event continuity, and retain a governed failover and failback receipt. |

### Remaining work

- [x] Define provider-neutral regional actions and pass a focused fake-provider shadow sequence test for ordering, bounded replay, stale epochs, failure halt, single-writer behavior, and failback prerequisites.
- [ ] Bind provisioning, primary fencing, event recovery, traffic shift, and failback through a deployment provider, then retain a substrate-backed shadow receipt proving no second writer was enabled.
- [x] The deployed scheduler is constrained to one process per fire through reviewable Terraform configuration, and `tests/integration/infra/test_scheduled_job_concurrency.py` fails if any scheduled Job relaxes `replica_completion_count`, `parallelism`, or adds a second trigger.
- [ ] Prove cross-process experiment reservation before any scheduled tick runs in more than one process.
- [ ] Retain one repository-safe governed drill receipt that records approved and achieved RPO/RTO, event gaps, stale-epoch rejection, traffic shift, rollback or failback, and cleanup.
