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

The local millisecond state and Hub full-precision state must have identical non-time fields. The
positive difference from the local `observed_at` to the immutable receipt's `completed_at` must be
no more than one millisecond. Installation, Entity, scope, UID inventory, execution identity, and
the exact completion audit must also match. Any other difference, altered digest, concurrent state,
different retry, or missing audit blocks approval.

## Agent reconciliation

The Hub signs the exact full-precision source and authoritative replacement. Under the Agent state lock,
`reconcile-native-transition-state` verifies that signature, the immutable receipt, scope, UID
inventory, current state, and absence of an unreported Plan or active journal. It retains the
original bytes in an immutable rollback record and atomically replaces only current state.

The Agent submits the signed replacement through its `Agent.Access` workload identity. The Hub
rejects identity or state drift, appends the canonical state and hash-chained audit, and returns the
committed state as readback. A failed submission restores the original bytes. An exact retry reuses
the committed Hub receipt.

## Related docs

| To learn about | Read |
|----------------|------|
| Hub-managed lifecycle | [Hub-managed lifecycle](hub-managed-lifecycle.md) |
| Operator procedure | [Hub deployment handoff](../../runbooks/hub-lifecycle-deployment-handoff.md) |
