# Control-Plane Disaster Recovery implementation ledger

This delivery ledger preserves reviewable implementation scope, append-only transitions,
and resumable work while the roadmap owner remains focused on normative design.

## Implementation status

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| Immutable recovery plan and legal transition reducer | implemented | `services/core-control-plane/src/fdai/core/verticals/resilience/recovery_plan.py` and `services/core-control-plane/tests/core/verticals/test_recovery_plan.py` | Version, approval separation, recovery epochs, legal edges, and halt behavior have focused tests. |
| Durable compare-and-set coordination and audit persistence | implemented | `services/core-control-plane/src/fdai/core/verticals/resilience/recovery_coordinator.py` and `services/core-control-plane/tests/core/verticals/test_recovery_coordinator.py` | Exact redelivery, write conflicts, revision checks, and atomic state-plus-audit writes are implemented. |
| Opt-in database restore drill and verifier | implemented | `services/core-control-plane/src/fdai/core/verticals/resilience/db_dr_drill_cli.py`, `infra/modules/compute/container-apps/dr_drill_job.tf`, and focused DR drill tests | The Job defaults to dry-run and requires deployment-supplied inputs; source and tests do not prove a completed substrate-backed drill. |
| Regional provider actions and event-data continuity | in-progress | Provider seams and the activation sequence in this document | Alternate-region provisioning, fencing, bounded event replay, traffic shift, and failback are not composed into one live path. |
| Single-process scheduled execution | implemented | `infra/modules/compute/container-apps/*_job.tf`; `tests/integration/infra/test_scheduled_job_concurrency.py` | Every scheduled Container Apps Job pins `replica_completion_count` and `parallelism` to `1`, and every job declares exactly one trigger kind, so one tick runs in exactly one process. The focused check fails when a schedule block does not parse, when a value is relaxed, or when a job declares a second trigger. |
| Measured regional failover and failback | not-started | `docs/runbooks/control-plane-failover.md` | The repository contains no governed drill receipt proving approved RPO/RTO, stale-epoch fencing, event completeness, traffic shift, and failback. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-08-14 | in-progress | Adopted the implementation ledger; earlier provenance was not reconstructed. Separated tested recovery mechanics from regional deployment and operational evidence. | current change; focused recovery plan and coordinator tests listed in the scope table | Compose and exercise the regional provider path, then retain governed failover and failback evidence. |
| 2026-08-15 | implemented | Constrained scheduled execution to one process through reviewable Terraform configuration and added a focused concurrency check over every scheduled Job. | `current change`; `tests/integration/infra/test_scheduled_job_concurrency.py`; `pytest tests/integration/infra/test_scheduled_job_concurrency.py` (24 passed). | Cross-process experiment reservation, the composed regional path, and the governed drill receipt remain open. |

### Remaining work

- [ ] Bind alternate-region provisioning, primary fencing, event recovery, traffic shift, and failback through provider adapters, and pass a focused end-to-end shadow test without enabling a second writer.
- [x] The deployed scheduler is constrained to one process per fire through reviewable Terraform configuration, and `tests/integration/infra/test_scheduled_job_concurrency.py` fails if any scheduled Job relaxes `replica_completion_count`, `parallelism`, or adds a second trigger.
- [ ] Prove cross-process experiment reservation before any scheduled tick runs in more than one process.
- [ ] Retain one repository-safe governed drill receipt that records approved and achieved RPO/RTO, event gaps, stale-epoch rejection, traffic shift, rollback or failback, and cleanup.
