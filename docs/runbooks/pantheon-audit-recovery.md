---
title: Recover a legacy Pantheon audit checkpoint
---
# Recover a legacy Pantheon audit checkpoint

Use this runbook when Saga repeatedly reports `AuditChainError` after an upgrade and its durable
checkpoint still uses schema `1.0.0`. Recovery verifies the existing history without deleting
records, resetting the chain, replaying actions, or changing execution authority.

> **Scope:** This is an explicitly reviewed database repair. Use the Core service-owned database
> environment for the selected execution venue. Never copy an Azure database connection into a
> local runtime or put a connection string on the command line.

## What this doc covers

Normal startup migrates only a complete history of at most 512 audit rows. A larger history is
held for review, not treated as an empty chain. The explicit recovery command supports up to
50,000 Saga records and 64 MiB of source JSON with a 30-second total deadline.

## Establish the cause

1. Confirm the Core process, actual broker progress, and the local service-owned database.
2. Inspect dead-letter queue (DLQ) metadata for the failing agent, topic, and exception type.
   A listening port or a running consumer does not prove that Saga accepts events.
   Plain local logs retain the handler's safe `agent`, `error_type`, and `failure_code` tokens,
   but exclude raw exception text, consumer identity, and payloads.
3. Confirm that `pantheon/saga/audit-chain/verified-head` uses schema `1.0.0`.
4. Distinguish missing activity from missing findings. Observation activity, source timeouts,
   held evidence, and evaluated targets with no finding are different outcomes. Don't create
   synthetic Incidents or increase agent activity just to make a screen appear busy.

## Review and apply recovery

Stop every old Saga writer before applying the migration. Current revision-fenced writers can
remain running: the command locks the checkpoint row and the existing shared audit-append lock
in their normal order. Old writers that append and update their head in separate transactions
are not safe to leave running.

With the selected Core environment already bound, run:

```bash
uv run python scripts/automation/migrate-pantheon-audit-chain.py
```

The default is a dry-run. Review `source_count`, `detached_count`, `length`, `retained_count`,
and the returned digests. The checkpoint selects the existing chain; the command follows its
unique descendants to preserve appends newer than a stale legacy checkpoint. Every source
entry, payload digest, and ancestry link is verified. A missing ancestor, corrupted record,
or fork on the selected chain blocks recovery.

Other independently rooted histories remain unchanged in the append-only audit log. If the
review identifies such histories, explicitly acknowledge their preservation. Substitute the
reviewed `plan_digest` into:

```bash
uv run python scripts/automation/migrate-pantheon-audit-chain.py \
  --apply-plan <plan-digest> \
  --legacy-writers-quiesced \
  --preserve-detached-histories
```

Without detached histories, the last flag is unnecessary. A changed checkpoint or Saga history
invalidates the plan. Repeat the dry-run and review the new result instead of bypassing it.
The checkpoint and `audit.chain.migrated` receipt commit in one transaction. Failure rolls both
back. Existing audit records are never rewritten or removed.

## Verify the effect

The running revision-fenced adapter reads the new checkpoint on its next Saga event. Confirm a
new `audit.record`, schema `2.0.0`, and a growing journal revision from independent database reads.
Check that new Saga handler failures and DLQ additions stop. A successful migration command is
not proof that these runtime effects occurred.

The retained journal contains at most 512 verified entries; complete history remains in the
audit log. Historical DLQ entries remain for a separately reviewed replay. Recovery does not
replay approvals, execution requests, or other authority-bearing messages.

Inspect Incident eligibility separately: automatic creation still requires correlated,
sufficient evidence and the configured severity threshold. No findings can legitimately mean
no new Incident. An Entra sign-in requirement also remains intact during browser validation.

## Diagnose a remaining raw-input collision

If Saga's checkpoint is repaired but activity remains quiet, inspect the raw ingress DLQ too.
An old pending Huginn request can reject a producer retry when only the wrapper's `ingested_at`
receipt time changed. New request fingerprints exclude that overwritten top-level clock, not
the provider's event time, nested timestamps, content, or authority fields. Exact original
requests upgrade old fingerprints through audited revision checks.

For an old pending request, retain the original source message and prove its complete legacy
request digest before any reviewed replay. An inventory-only recovery preserves its original
bytes and observation time, `incident_correlation: none`, and observation mode. Publishing it
does not prove that Huginn completed it; independently observe the retained claim and new Saga
records. Don't reset digests, mark pending claims published, or recreate an unavailable original
from a newer observation. Missing originals stay held for a separately approved recovery.

An already-admitted inventory outbox is a different recovery source. Standard Huginn
maintenance reacquires its expired lease, reapplies the original projection, and redrives the
retained Event and Change through typed publication before recording completion. It processes
at most eight inventory claims per tick and preserves their digest, source clocks and publication
markers. This does not reconstruct raw input or replay operator, approval or execution requests.
Verify both outbox completion and downstream Saga records independently.

## Related docs

| To learn about | Read |
|---|---|
| Saga ownership and event boundaries | [Agent Pantheon](../roadmap/agents/agent-pantheon.md) |
| Local and deployed source parity | [Development and deployment parity](../roadmap/deployment/dev-and-deploy-parity.md) |
