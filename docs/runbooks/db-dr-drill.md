---
title: Deep DB-DR Restore Drill Runbook
---

# Deep DB-DR restore drill runbook

Operator runbook for the phase-3 Deep DB-DR drill. It turns the shipped
[`DbDrVerifier`](../../services/core-control-plane/src/fdai/core/verticals/resilience/db_dr_verifier.py)
and the delivery-owned
[`AzurePostgresRestoreAdapter`](../../services/core-control-plane/src/fdai/delivery/azure/db_dr_restore.py)
into a repeatable operational procedure. The drill runs against a
production PostgreSQL Flexible Server without ever touching production
data. The restore lands in a Terraform-owned **isolated resource group**,
and the drill deletes the temporary server when done.

## When to run

- **Baseline schedule**: once per calendar month.
- **After schema migration**: within 7 days of every migration that
  changes user-visible tables.
- **On restore-adapter change**: any commit under
  [`services/core-control-plane/src/fdai/delivery/azure/db_dr_restore.py`](../../services/core-control-plane/src/fdai/delivery/azure/db_dr_restore.py)
  is a re-run trigger.
- **On demand**: when incident response needs a fresh RPO/RTO figure.

## Preconditions

1. Source Azure PostgreSQL Flexible Server is in state `Ready`.
2. Source server has a non-empty PITR window - `az postgres flexible-server show`
   returns a `backup.earliestRestoreDate` older than the intended
   restore time.
3. Operator's Azure CLI profile is the deployment profile - `env -u
   AZURE_CONFIG_DIR` selects the default profile. Confirm the active
   subscription matches your fork's expected id (`az account show`
   returns the subscription you set as
   `FDAI_EXPECTED_SUBSCRIPTION_ID`).
4. Terraform has created the isolated target resource group and the dedicated DB-DR identity.
  That identity has Reader on the source server, PostgreSQL Flexible Management Service
  Contributor only on the target group, ACR pull, and read access to the state-store secret. It is
  not the executor.
5. `FDAI_DR_DRILL_INTEGRITY_TABLES` names 1-16 small, stable tables. The default checks
  `alembic_version`; add application tables only when their contents are stable across the selected
  restore offset.
6. The scheduled entry point is `python -m fdai.delivery.db_dr_drill_cli`. A complete dry run
  validates source, target, table, and secret bindings without requesting a token or changing
  Azure or PostgreSQL.

## Steps

1. **Pick a restore point.** Use a timestamp 30 minutes in the past to
   guarantee the PITR window covers it:

   ```bash
   RESTORE_TIME=$(date -u -d '-30 min' +%Y-%m-%dT%H:%M:%SZ)
   echo "Restore point: $RESTORE_TIME"
   ```

2. **Use the isolated resource group.** The automated job uses the dedicated group created by
  Terraform and creates a timestamped server inside it. For a manual procedure, create a separate
  group that doesn't match the source group:

   ```bash
   DRILL_RG="rg-fdai-dr-drill-$(date +%Y%m%d-%H%M)"
   az group create -n "$DRILL_RG" -l koreacentral \
     --tags workload=fdai purpose=dr-drill drill-ts=$(date +%Y-%m-%d)
   ```

3. **Trigger the PITR restore.** The target server name is a globally
   unique Azure identifier - include the timestamp so it does not
   clash with a previous drill:

   ```bash
   SRC_ID="/subscriptions/<sub>/resourceGroups/rg-fdai-dev-krc/providers/Microsoft.DBforPostgreSQL/flexibleServers/psql-fdai-dev-krc"
   TARGET="psql-aiop-drill-$(date +%m%d%H%M)"
   az postgres flexible-server restore \
     -g "$DRILL_RG" -n "$TARGET" \
     --source-server "$SRC_ID" \
     --restore-time "$RESTORE_TIME" \
     --no-wait
   ```

4. **Poll until the server is `Ready`.** Restore typically completes
   in 15-40 minutes for a small dev database. The
   [`AzurePostgresRestoreAdapter`](../../services/core-control-plane/src/fdai/delivery/azure/db_dr_restore.py)
   polls the exact server resource under a 45-minute default budget. A malformed, failed,
   canceled, or incomplete resource response fails closed and triggers partial-target cleanup. The
   operator equivalent is:

   ```bash
   while [[ "$(az postgres flexible-server show \
       -g "$DRILL_RG" -n "$TARGET" --query state -o tsv 2>/dev/null)" \
       != "Ready" ]]; do
     echo "still provisioning: $(date +%H:%M:%S)"; sleep 60
   done
   ```

5. **Integrity check (deterministic).** Connect to the restored server
   and compare row counts + checksums against the source snapshot at
   `$RESTORE_TIME`. Any mismatch fails the drill.

   The upstream
   [`DbDrVerifier`](../../services/core-control-plane/src/fdai/core/verticals/resilience/db_dr_verifier.py)
   consumes an
   [`IntegrityChecker`](../../services/core-control-plane/src/fdai/shared/providers/db_dr.py)
   Protocol seam; the operator equivalent is:

   ```bash
   psql "host=$TARGET.postgres.database.azure.com user=<admin> dbname=fdai sslmode=require" \
     -c "SELECT relname, n_live_tup FROM pg_stat_user_tables ORDER BY relname;"
   ```

   Compare against the same query recorded against the source at the
   restore point. Zero mismatches is the phase-3 exit gate.

6. **App-level smoke tests.** Point a representative read-only client
   at the restored server and run a bounded smoke suite - one query
   per user-facing table plus a session write to a smoke schema. Any
   error fails the drill.

  Include these user-context tables in every restore smoke suite:

  - `conversation_record` and `conversation_turn`
  - `user_preference` and `user_memory_fact`
  - `conversation_policy`
  - `briefing_subscription` and `briefing_run`
  - `workflow_definition` and `workflow_binding`
  - `user_context_projection_delete_queue`

  Verify foreign keys, unique constraints, and the atomic
  `conversation_record.next_turn_index` value as well as row counts.
  For the deletion queue, verify that a leased row can be reclaimed
  after `leased_until` and that completing the job removes it.

7. **Tear down.** Delete the temporary restored server. The adapter's `teardown` path is
  idempotent: a 404 is a legal "already gone" result. After an accepted delete, the adapter polls
  the exact server until it returns 404 before reporting cleanup success. Restore failure or
  cancellation also attempts to delete a partially created server. The Terraform-owned isolated
  group remains for the next drill:

   ```bash
   az postgres flexible-server delete -g "$DRILL_RG" -n "$TARGET" --yes
   ```

## Retention and backup residuals

The scheduler deletes inactive conversations and old briefing runs from
the live database after 90 days, and deletes expired memory facts when
their `expires_at` time arrives. The same transaction writes ontology
object ids to `user_context_projection_delete_queue`; the scheduler then
removes those metadata-only projections with isolated retries and bounded
backoff.

Point-in-time restore (PITR) can recover a database state from before a
privacy or retention deletion. Therefore, live-store deletion does not
mean that every retained backup copy is immediately erased. Production
keeps a 35-day geo-redundant PostgreSQL backup window, after which the
provider ages out the residual copy. Access to a restored server should
remain restricted to the drill operators, and the isolated restore should
be deleted as soon as verification is complete.

Before directing any scheduler or application process at a restored
server:

1. Confirm the chosen restore point and document whether it predates a
  user-context deletion.
2. Run the user-context smoke checks above without exposing raw turn or
  memory bodies in logs or evidence artifacts.
3. Run one bounded retention tick and drain the projection deletion queue.
4. Confirm that source rows and ontology metadata agree before the server
  is eligible for service.

## Success criteria

The drill passes only when all six conditions hold:

- Restore completed under the configured budget
  (upstream default 45 minutes).
- Integrity report contains zero mismatches.
- Smoke report has at least one check and every check passed.
- The final ARM resource id exactly matches the requested restored server, and
  its valid FQDN starts with the requested target server name.
- Restored-server deletion was accepted and an exact read returned 404.
- Every step wrote its audit entry. The drill is only done once the
  `start` / `verification_passed` / `teardown_succeeded` / `passed` events exist in the audit log. Every
  phase and teardown record carries the decision's unique `run_id` as its
  `correlation_id`, while `experiment_id` continues to identify the planned
  exercise. Phase idempotency keys must be unique inside that run.

`verification_passed` is an intermediate result. The final `passed` decision is written only after
`teardown_succeeded`. A teardown error produces `cleanup_failed`, preserves the primary verification
outcome for diagnosis, returns a nonzero CLI exit, and keeps the leaked resource as an owned
incident until cleanup is verified.

## Failure handling

- **Restore exceeds budget** -> the adapter returns a restore failure and attempts partial-server
  cleanup before the verifier records the terminal result.
- **Malformed successful response** -> an HTTP 200 read without a recognized state is a restore
  failure, not an implicit running state.
- **Integrity mismatch** -> the drill fails closed, retains the structured mismatch in audit, and
  still removes the restored server.
- **Smoke query fails** -> the drill records the bounded failed check and still removes the server.
- **Teardown failure** -> `cleanup_failed` preserves the primary outcome and returns a nonzero CLI
  exit. Page on-call and delete the named server manually; the isolated target group itself is
  intentionally retained.

## Cost note

The isolated Postgres server incurs the standard Flexible Server
compute + storage rate for the duration of the drill. On the
day-zero Burstable B1ms + 32 GB storage tier that is a small hourly
figure, but it adds up if teardown is skipped. Alerts on the workload
tag `purpose=dr-drill` catch stray restored servers.

## Related docs

- [phase-3-integrated-loop.md § Deep DB-DR (stateful - dedicated design)](../roadmap/phases/phase-3-integrated-loop.md)
- [security-and-identity.md](../roadmap/architecture/security-and-identity.md)
- [DbDrVerifier module docstring](../../services/core-control-plane/src/fdai/core/verticals/resilience/db_dr_verifier.py)
