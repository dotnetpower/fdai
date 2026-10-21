---
title: Lifecycle Self-Upgrade Failure Analysis
---
# Lifecycle Self-Upgrade Failure Analysis

This analysis defines the failure and recovery boundaries for two-slot replacement of the
lifecycle agent, infrastructure agent, and Target Hub. It completes the design-analysis spike
under #1824; it does not implement or qualify a self-upgrade controller.

> **Scope:** A slot is one runnable component copy. Starting a candidate copy grants no write,
> signing, execution, or promotion authority. Existing Plan approval and local safeguards remain
> authoritative.

## Design at a glance

Keep the old slot as the rollback target while the candidate starts without write authority.
Transfer one fenced logical role only after exact artifact, compatibility, and health checks.
Commit success after independent effect readback and a second zero-change plan, not readiness alone.

| Component | Protected role | Independent observation |
|-----------|----------------|-------------------------|
| Lifecycle agent | Existing installation and namespace-scoped workload writer | Exact workload revisions, health, admission and postcondition records |
| Infrastructure agent | Existing exact-plan executor and Terraform state ownership | Exact plan/state lineage, claim, effect readback and recovery receipt |
| Target Hub | Catalog admission, Plan sequencing, signing and configuration decisions | Durable catalog floor, key epoch, Plan/import/audit history and serving identity |

The two copies never concurrently own the same authority-bearing role. A database pointer or
process health probe alone is not a fence at the write boundary.

## Current source boundaries

[ADR-0003 A20](../architecture/decisions/0003-hub-managed-lifecycle-and-operator-governance.md)
requires two slots but does not supply a working handoff controller.
[The lifecycle agent](../../../lifecycle/agent/src/fdai_lifecycle_agent/agent.py) already retains
prepared/applying/recovery state; its workload rollback is not component self-replacement.
[Hub migrations](../../../lifecycle/hub/src/fdai_lifecycle_hub/migrations.py) enforce schema
compatibility, while [the Hub store](../../../lifecycle/hub/src/fdai_lifecycle_hub/store.py)
retains Plan and configuration trust. These are inputs to the future controller, not proof of it.

No infrastructure-agent or Target-Hub self-upgrade result is inferred from workload-apply tests.

## Handoff and stop conditions

The future controller should retain one durable transition record bound to component, installation,
Plan/phase digest, source and target artifact digests, slot identities, sequence/fencing generation,
idempotency key, deadline, and rollback target. Only digests and lifecycle metadata leave the
installation; private keys, raw configuration and operational data do not.

Use these bounded phases:

1. **Stage:** verify exact artifacts and current signature, recall, audience and compatibility
   inputs. The old slot remains the writer.
2. **Start candidate:** prove candidate liveness and read compatibility without granting its
   authority-bearing role.
3. **Handoff:** atomically retain the new generation and make the old generation unable to write
   at the actual executor boundary. If that boundary cannot enforce the fence, hold the handoff.
4. **Verify effects:** observe the selected writer and expected effects independently. Readiness
   without correct state is failure or unknown.
5. **Commit or recover:** retain success and a zero-change plan, or execute only the already
   authorized recovery path against the preserved rollback target.

Total, phase, and no-progress deadlines come from the exact admitted Plan and its reviewed
component policy. A missing budget, insufficient remaining window, lost lock, identity drift,
changed source, expired authorization, failed dry-run or unverifiable rollback target holds before
handoff. No timeout grants authority, changes the target, or silently restarts the attempt.

## Failure analysis

| Failure point | Safe outcome | Required recovery evidence |
|---------------|--------------|----------------------------|
| Download, digest or signature fails | Keep the old slot; candidate never gains the role | Exact rejected input and unchanged active generation |
| Candidate health fails before handoff | Stop candidate; keep the old role owner | Candidate failure and independently observed old-slot health |
| Recall, key revocation, approval or window changes | Revalidate and hold new effects | Current source, key epoch and denial; old permission is not reused |
| Old process survives or a network partition hides it | Do not activate a second writer without an enforceable fence | Executor-side generation rejection or an explicit unknown/operator hold |
| Process stops during handoff | Recover from the retained generation, not from acknowledgement absence | Transition record plus independently observed actual role owner |
| Handoff acknowledgement is lost | Read back; never dispatch the same effect as a new attempt | Stable idempotency identity and the original claim/result |
| Candidate serves but has wrong state | Treat readiness as insufficient; preserve both state histories | Expected versus observed revisions, digests and postconditions |
| New binary cannot read retained schema or journal | Hold before handoff | Declared old/new reader compatibility and a tested recovery path |
| Migration prevents the old binary from reading | Do not call a binary switch a database rollback | Forward recovery or a separately approved verified-backup restoration |
| Storage, signing input or execution host is unavailable | Preserve pending/unknown state; no empty replacement store | Original durable head, availability failure and bounded retry decision |
| Rollback health also fails | Stop new work and escalate; retain the evidence | Both failure observations, retained lock/fence state and named recovery owner |
| Offline metadata is stale or lacks a recall | Do not infer current eligibility or fetch a hidden fallback | Exact imported metadata and explicit offline limitation/hold |

For a Target Hub, preserve these records across slot changes:

- Catalog floors and key epochs.
- Decisions for enrollment, public-key binding and scope.
- Configuration acceptance and activation receipts, Plan sequences and audit ancestry.

Transactions that serialize requests are not evidence that a long-lived serving-role fence exists.

## Data and rollback boundaries

Switching binaries does not reverse a persistent schema, erase an interrupted apply, reset an audit
chain, renew a Trial, or make an old key current again. Both slots use the authoritative retained
records instead of slot-local copies that can restore older permission.

The existing agent's interrupted-apply recovery finishes or rolls back that original workload
attempt before accepting new work. A future self-upgrade should preserve that priority. If an old
slot cannot understand retained state, do not delete or reinitialize it to make health pass.

Preserve [installation-bound entitlement and Trial continuity](hub-managed-lifecycle-entitlement.md).
Neither rollback nor a missing local record creates a new installation or a fresh Trial.

## Critique and revision

| Rejected assumption | Revised boundary |
|---------------------|------------------|
| Two healthy copies are high availability | Only one can hold the authority-bearing role; fencing is independently proven |
| A pointer flip proves the old writer stopped | The actual write boundary must reject the old generation |
| Binary rollback also restores the database | Compatibility is checked before handoff; irreversible data changes require explicit recovery |
| Missing acknowledgement means no effect | Observe the original attempt with its stable claim and idempotency key |
| A copied slot can bootstrap fresh licensing | Licensing state and its original anchor remain outside replaceable slots |

## Executable obligations

- [ ] Implement a component-specific controller and enforce its role fence at every write boundary.
- [ ] Fault-inject before and after every retained transition for all three component types.
- [ ] Prove restart, duplicate, partition, expired input, old-key, schema/journal and rollback cases.
- [ ] Retain exact connected-installation and offline Target-Hub effects, independent readback,
  history preservation and the second zero-change plan.

These are future implementation and qualification obligations. No such controller or drill was run
to publish this analysis.

## Related docs

| To learn about | Read |
|----------------|------|
| Normative lifecycle ownership | [Hub-Managed Lifecycle](hub-managed-lifecycle.md) |
| Licensing continuity | [Hub-managed entitlement](hub-managed-lifecycle-entitlement.md) |
| Design delivery and remaining work | [Implementation ledger](../../roadmap-implementation/deployment/hub-managed-lifecycle-self-upgrade.md) |
