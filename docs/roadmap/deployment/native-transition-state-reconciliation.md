---
title: Native transition state reconciliation
---
# Native transition state reconciliation

This design defines the bounded recovery for a legacy native transition whose Agent state used a
millisecond timestamp while the Hub completion retained the same instant at greater precision. It
does not permit general state repair or receipt rewriting.

> **Implementation ledger:** Delivery evidence is tracked in the
> [native transition state reconciliation implementation ledger](../../roadmap-implementation/deployment/native-transition-state-reconciliation.md).

## What this doc covers

The Hub completion timestamp is authoritative. The immutable transition receipt remains unchanged,
and only the Agent's durable current state can move to the full-precision canonical timestamp and
digest.

## Approval and validation

An authenticated operator submits
`fdai.lifecycle-native-transition-state-reconciliation-request.v1` to the reconciliation approval
route. Under the installation row lock, the Hub verifies the original completion audit and receipt,
installation, old and new Entity and scope digests, native approval, authoritative UID digest,
Agent identity, current state, and absence of an open Plan.

The local and Hub states must have identical canonical fields except `observed_at`. The positive
precision difference must be no more than one millisecond. Any other difference, altered receipt,
concurrent state, different retry, or missing audit blocks approval.

## Agent reconciliation

The Hub signs the exact source and authoritative replacement. Under the Agent state lock,
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
