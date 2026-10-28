---
title: Native transition state reconciliation
---
# Native transition state reconciliation

This design defines the bounded recovery for a legacy native transition whose durable Agent state
used a millisecond timestamp and digest while its immutable transition receipt retained the
full-precision timestamp. The Hub completion audit binds a regenerated full-precision state and
transition-receipt digest. This recovery does not permit general state repair or receipt rewriting.

> **Implementation ledger:** Delivery evidence is tracked in the
> [native transition state reconciliation implementation ledger](../../roadmap-implementation/deployment/native-transition-state-reconciliation.md).

## What this doc covers

The immutable transition receipt's `completed_at` is authoritative for the state observation time.
The Hub completion receipt's `completed_at` records the later Hub commit time. The immutable
receipt remains unchanged, and only the Agent's durable current state can move to the
full-precision canonical timestamp and digest.

## Approval and validation

An authenticated operator submits
`fdai.lifecycle-native-transition-state-reconciliation-request.v1` to the reconciliation approval
route. Under the installation row lock, the Hub verifies the original completion audit and receipt,
installation, old and new Entity and scope digests, native approval, authoritative UID digest,
Agent identity, current state, and absence of an open Plan.

Validation uses two independent canonical forms:

- The immutable receipt's stored fields must reproduce its original `record_digest`. Its embedded
  state digest must reproduce the millisecond `observed_at` state.
- The Hub completion receipt must reproduce its own `receipt_digest`. Its state digest uses the
  immutable receipt's full-precision `completed_at`, and its transition-receipt digest must
  reproduce the same receipt fields with only that full-precision state digest substituted.
- A legacy reported-state source retains the stored `available_artifact_digests` sequence,
  including order and duplicates, and must reproduce its own digest from those exact canonical
  bytes. Parsing this source never normalizes its sequence or replaces its digest.

The local millisecond state and Hub full-precision source must have identical non-artifact fields
and equivalent artifact multisets. Artifact order can differ, but each digest must have the same
duplicate count. The positive difference from the local `observed_at` to the immutable receipt's
`completed_at` must be no more than one millisecond. Installation, Entity, scope, UID inventory,
execution identity, and the exact completion audit must also match. Any other difference, altered
digest, concurrent state, different retry, or missing audit blocks approval.

The authoritative replacement preserves the source's semantic artifact inventory while
deterministically sorting and deduplicating `available_artifact_digests`. Its contract remains
strict: an unsorted or duplicate target is invalid. The Hub computes a new target digest without
changing the signed legacy source or its stored digest.

### Expired unconsumed approval renewal

An approval that expires before the Agent changes local state can be renewed without weakening
the evidence checks. The Agent prepares a renewal request that names the exact expired approval
digest and carries the same immutable transition receipt, Hub completion receipt, native approval,
and legacy reported state. It refuses renewal when a local reconciliation pending, rollback, or
completion record shows that an attempt already started. Only `request_id`, `requested_at`, and
`expires_at` can change.

Under the installation row lock, the Hub requires all of these conditions:

- The superseded approval is present in the hash-chained audit, has expired, and was approved by
  the same operator.
- No reconciliation completion receipt or completion audit exists for the superseded approval or
  its transition receipt.
- The authenticated Agent principal in the retained completion receipt, installation, Entity and
  scope digests, authoritative UID digest, native approval, and every other authority-bearing
  field are unchanged.
- The current Hub state still equals the superseded approval's source state, and no Plan is open.
- The superseded approval has no other renewal. An exact retry of the same renewal request is safe
  to retry (idempotent), while a different child request is a conflict.

The Hub records `supersedes_approval_digest` in the new approval audit and signs a new bounded
approval. If that approval also expires unconsumed, a later renewal must supersede the latest
approval rather than branch from an earlier one.

**Critique and revision:** Extending an active approval would silently widen existing authority.
Treating the same transition receipt as sufficient would miss changed Hub state, Agent evidence,
operator identity, or a completion whose response was lost. Renewal therefore creates a new
signed decision only after expiry and repeats current-state, no-Plan, identity, scope, UID, and
completion checks under the installation lock. It never changes or re-signs the old approval.

## Agent reconciliation

The Hub signs the exact full-precision legacy source and the strict authoritative replacement.
Under the Agent state lock, `reconcile-native-transition-state` verifies that signature, the
immutable receipt, artifact inventory equivalence, scope, UID inventory, current state, and absence
of an unreported Plan or active journal. It retains the original bytes in an immutable rollback
record and atomically replaces only current state.

The Agent submits the signed replacement through its `Agent.Access` workload identity. The Hub
rejects identity or state drift, appends the canonical state and hash-chained audit, and returns the
committed state as readback. A failed submission restores the original bytes. An exact retry reuses
the committed Hub receipt.

## Related docs

| To learn about | Read |
|----------------|------|
| Hub-managed lifecycle | [Hub-managed lifecycle](hub-managed-lifecycle.md) |
| Operator procedure | [Hub deployment handoff](../../runbooks/hub-lifecycle-deployment-handoff.md) |
