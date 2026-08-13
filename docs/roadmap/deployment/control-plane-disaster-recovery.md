---
title: Control-Plane Disaster Recovery
---

# Control-Plane Disaster Recovery

This document defines how an FDAI deployment recovers from a regional outage without creating a
second executor, losing the event recovery boundary, or treating a backup as proof of recovery.
It owns the recovery profiles, state sequence, platform constraints, failback contract, and
evidence required before a deployment can claim control-plane disaster recovery.

> **Scope:** Upstream defines the reusable recovery contract. A downstream deployment supplies
> regions, numeric recovery point objective (RPO) and recovery time objective (RTO), identities,
> resource references, owners, approvals, and measured drill evidence.

## Implementation status

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| Immutable recovery plan and legal transition reducer | implemented | `services/core-control-plane/src/fdai/core/verticals/resilience/recovery_plan.py` and `services/core-control-plane/tests/core/verticals/test_recovery_plan.py` | Version, approval separation, recovery epochs, legal edges, and halt behavior have focused tests. |
| Durable compare-and-set coordination and audit persistence | implemented | `services/core-control-plane/src/fdai/core/verticals/resilience/recovery_coordinator.py` and `services/core-control-plane/tests/core/verticals/test_recovery_coordinator.py` | Exact redelivery, write conflicts, revision checks, and atomic state-plus-audit writes are implemented. |
| Opt-in database restore drill and verifier | implemented | `services/core-control-plane/src/fdai/core/verticals/resilience/db_dr_drill_cli.py`, `infra/modules/compute/container-apps/dr_drill_job.tf`, and focused DR drill tests | The Job defaults to dry-run and requires deployment-supplied inputs; source and tests do not prove a completed substrate-backed drill. |
| Regional provider actions and event-data continuity | in-progress | Provider seams and the activation sequence in this document | Alternate-region provisioning, fencing, bounded event replay, traffic shift, and failback are not composed into one live path. |
| Measured regional failover and failback | not-started | `docs/runbooks/control-plane-failover.md` | The repository contains no governed drill receipt proving approved RPO/RTO, stale-epoch fencing, event completeness, traffic shift, and failback. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-08-14 | in-progress | Adopted the implementation ledger; earlier provenance was not reconstructed. Separated tested recovery mechanics from regional deployment and operational evidence. | current change; focused recovery plan and coordinator tests listed in the scope table | Compose and exercise the regional provider path, then retain governed failover and failback evidence. |

### Remaining work

- [ ] Bind alternate-region provisioning, primary fencing, event recovery, traffic shift, and failback through provider adapters, and pass a focused end-to-end shadow test without enabling a second writer.
- [ ] Prove cross-process experiment reservation or constrain the deployed scheduler to one process with reviewable configuration and a focused concurrency check.
- [ ] Retain one repository-safe governed drill receipt that records approved and achieved RPO/RTO, event gaps, stale-epoch rejection, traffic shift, rollback or failback, and cleanup.

## Design at a glance

FDAI uses an active-passive regional model with exactly one write-authoritative recovery epoch.
The old epoch is fenced before the recovery runtime can consume events or execute actions. State
is restored and verified before event recovery starts, audit replay is judge-only, and traffic
changes only after dependency, identity, integrity, and canary checks pass.

The deployment selects one profile by measured objective:

| Profile | Standing secondary | Intended use | Promotion condition |
|---------|--------------------|--------------|---------------------|
| `restore` | Backup, image, Terraform state, and recovery configuration only | An RTO that permits regional reprovisioning and database restore | A drill proves the complete restore inside the approved RTO |
| `warm` | Secondary network, identities, event-bus metadata, registry replica, and disabled runtime | An RTO that the `restore` profile cannot meet | A drill proves fencing, state recovery, activation, and capacity inside the approved RTO |

Active-active execution is not supported. Read-only services may be multi-region, but Thor's
privileged executor and the event-consumption authority remain single-writer.

## Required plan inputs

A production recovery plan is immutable and versioned. It records:

- **Identity:** plan id, revision, deployment profile, primary region, recovery region, and scope.
- **Business objective:** approved RPO, RTO, maximum degraded duration, and outage scenarios.
- **Authority:** requester, reliability owner, operations owner, approver, executor identity, and
  break-glass policy. The requester cannot approve the same activation.
- **Safety:** stop conditions, rollback or state-forward recovery, maximum affected resources,
  kill-switch state, and the primary fencing method.
- **State sources:** Terraform state, image digest, database recovery source, audit checkpoint,
  event recovery source, secret strategy, and configuration digest.
- **Verification:** integrity checks, identity and private-network probes, replay bounds, canary,
  application smoke checks, and cleanup checks.
- **Failback:** target region, data reconciliation method, new recovery epoch, and acceptance gate.

Missing, expired, or conflicting inputs keep the plan in `draft`. Runtime environment, fork
status, or an incident severity cannot promote the plan by itself.

## Failure domains

| Failure | Recovery response | What does not change |
|---------|-------------------|----------------------|
| Container or host | Container Apps replaces the replica | Recovery epoch and regional authority |
| Availability zone | Zone-redundant services and replicas absorb the loss | No regional failover is declared |
| Azure region | Activate the approved regional recovery plan | Safety gate, approval separation, audit requirements |
| Logical data corruption | Restore to an isolated point before corruption and verify | A healthy region does not make corrupted state acceptable |
| Identity or policy loss | Hold activation until least-privilege probes pass | Credentials are never copied from logs or embedded config |
| Event-data loss | Recover from the declared durable source and mark any gap | Event Hubs metadata recovery is not event-data recovery |

## Azure service constraints

The CSP-neutral plan records capabilities. The Azure adapter and Terraform profile enforce these
current Azure constraints:

| Service | Recovery contract |
|---------|-------------------|
| Container Apps | A Container Apps environment is regional. Regional recovery requires another environment, its own virtual network, image availability, and an explicit traffic-routing mechanism. Local container storage is never a recovery source. |
| Event Hubs | Geo-disaster recovery replicates namespace metadata, not events. A primary offset cannot be reused in the secondary namespace. The plan declares Capture, application federation, producer replay, or an accepted data gap; it also recreates RBAC and validates private endpoints. |
| PostgreSQL Flexible Server | Same-region PITR creates a new server. Geo-redundant backup restores only the latest available copy in the paired region, is asynchronous, and is not remote PITR. A stricter RPO requires a measured replica or another approved data-continuity design. |
| Key Vault | Microsoft-managed regional failover may be delayed and read-only. A tighter RTO uses separate regional vaults with an approved synchronization and rotation process. Soft delete and purge protection remain required. |
| Azure Container Registry | Geo-replication requires Premium and is eventually consistent. Activation verifies the exact image digest in the recovery region before starting compute. A tag is not evidence. |
| Storage | Recovery artifacts use a replication profile that meets the approved region and residency rules. Blob availability alone does not prove the artifact digest or freshness. |
| Terraform backend | State, lock, provider versions, and the approved plan are available outside the failed application region. Recovery never edits state manually to make an apply succeed. |

Current platform references:

- [Event Hubs geo-disaster recovery](https://learn.microsoft.com/azure/event-hubs/event-hubs-geo-dr)
- [PostgreSQL Flexible Server backup and restore](https://learn.microsoft.com/azure/postgresql/backup-restore/concepts-backup-restore)
- [Container Apps reliability](https://learn.microsoft.com/azure/reliability/reliability-container-apps)
- [Key Vault reliability](https://learn.microsoft.com/azure/reliability/reliability-key-vault)
- [Azure Container Registry geo-replication](https://learn.microsoft.com/azure/container-registry/container-registry-geo-replication)

## Recovery state sequence

Every transition checks the expected plan revision and state. A losing or stale writer reloads the
canonical record instead of guessing which activation won.

```text
draft -> ready -> approved -> activating -> primary_fenced
      -> state_restored -> runtime_started -> audit_verified
      -> event_recovery_ready -> traffic_shifted -> service_verified
      -> active_recovery -> failback_ready -> failing_back
      -> primary_verified -> closed
```

`halted` is terminal for that plan revision. Any transition from `activating` through
`primary_verified` may halt when a stop condition fires. Recovery continues only through a new
revision and approval, never by relabeling the halted record.

### Activation sequence

1. **Confirm the incident and plan:** bind the outage start, plan revision, objectives, authority,
   and fresh evidence. A drill uses the same sequence but cannot receive production traffic.
2. **Fence the primary:** engage the kill switch, revoke or isolate the old executor path, and
   acquire a monotonically increasing recovery epoch. Secondary execution stays disabled until
   the fence is independently observed.
3. **Prepare dependencies:** validate Terraform state and image digest, provision or verify the
   recovery network, identities, private DNS, RBAC, Key Vault strategy, Event Hubs namespace, and
   observability path.
4. **Restore state:** restore PostgreSQL and immutable artifacts, then run schema, hash-chain,
   integrity, retention, and application smoke checks. A restore that cannot be verified halts.
5. **Start without authority:** start the runtime in recovery mode with consumers and privileged
   execution disabled. Readiness must prove state, event bus, identity, catalog, and audit writer.
6. **Verify audit replay:** replay restored decisions in judge-only mode. Replay never invokes an
   executor and must stop at the declared checkpoint without a hash or schema gap.
7. **Recover events:** select the declared event source and bounded time window. Preserve causal
   and per-resource ordering, retain original idempotency keys, and send ambiguity to human review.
8. **Shift authority and traffic:** enable the recovery epoch, consumers, and required routes only
   after canary and capacity checks pass. The stale epoch must remain unable to write.
9. **Verify service:** measure RPO and RTO, compare them with the approved objectives, confirm the
   impact scope, and record residual gaps. An objective breach is a failed recovery exercise.

## Event recovery contract

DLQ replay is not a complete regional recovery strategy. The recovery plan records:

- the authoritative source for events that were not committed before the outage;
- start and end timestamps, partition or causal keys, and the last durable audit checkpoint;
- the expected gap between the source and recovered audit state;
- original event ids and idempotency keys;
- ordering and deduplication validation before publication;
- the disposition of stale, malformed, missing, or conflicting records;
- completion evidence showing every accepted event reached a terminal audited outcome.

If the source cannot prove completeness, FDAI records the gap and holds affected actions for human
review. It never invents offsets, silently starts at the end, or treats an empty secondary topic as
successful recovery.

## Failback contract

Failback is a new governed recovery, not the reverse of failover commands.

1. Treat the active recovery region as the current source of truth.
2. Create a new plan revision when any target, objective, or procedure changes. Record a separate
   failback approval, then allocate a new epoch when `failing_back` starts.
3. Rebuild or resynchronize state from the active source. Never restart the stale primary store.
4. Validate identities, network, image digest, state integrity, event checkpoint, and capacity.
5. Fence the active recovery epoch before shifting consumers or privileged execution.
6. Shift traffic, run canary and smoke checks, and retain rollback to the prior active region until
   the verification window closes.
7. Re-establish the selected recovery profile and close only after cleanup and evidence retention.

## Evidence and promotion

Each activation and drill stores sanitized, immutable evidence:

- plan id and revision, recovery epoch, trigger, outage window, actor and approval references;
- approved and achieved RPO/RTO with measurement timestamps;
- primary-fence receipt and proof that the stale epoch could not write;
- Terraform plan digest, image digest, configuration digest, and provider versions;
- database restore point, integrity report, audit checkpoint and hash-chain result;
- event source, bounded replay window, counts, gaps, duplicates, and terminal outcomes;
- identity, RBAC, private DNS, secret, event-bus, readiness, canary, and capacity results;
- traffic shift, rollback or failback receipts, cleanup result, and residual risks.

Production remains blocked until the reliability owner approves numeric objectives and a complete
isolated restore plus regional failover/failback drill meets them. Three shadow or dry-run plans do
not substitute for one substrate-backed exercise.

## Implementation boundaries

- `core/` owns immutable plan validation and legal transitions. It does not call Azure.
- The durable coordinator verifies approval authenticity, expected revision/state, monotonic
   transition time, and compare-and-set ownership before it atomically persists the plan projection
   and audit row through `StateStore`. Exact redelivery returns the committed record; changed
   evidence is a conflict because the idempotency digest commits to evidence, approval, and epoch.
- Provider Protocols own fencing, state restore, event recovery, traffic shift, and probes.
- Azure adapters implement those Protocols through managed identity and bounded operations.
- Terraform renders the selected profile; deployment values remain outside upstream source.
- The Process journal and append-only audit chain are the durable transition authority.
- The console is read-only and reports unavailable or recovering state without enabling actions.

## Related docs

| To learn about | Read |
|----------------|------|
| Regional failover and failback procedure | [Control-plane failover runbook](../../runbooks/control-plane-failover.md) |
| Single-region deployment and release rollback | [Deployment](deployment.md) |
| Scheduled workload DR and database restore drills | [Phase 3 integrated loop](../phases/phase-3-integrated-loop.md) |
| Runtime startup and readiness gates | [Startup and lifecycle](../operations/startup-and-lifecycle.md) |
| Operational signals and runbook requirements | [Operating and verification](../operations/operating-and-verification.md) |
| Production architecture approval evidence | [Architecture Review Board packet](../architecture/architecture-review-board.md) |
