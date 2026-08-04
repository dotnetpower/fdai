---
title: Deep DB-DR Restore Drill Runbook
---

# Deep DB-DR restore drill runbook

Operator runbook for the phase-3 § Deep DB-DR drill. Turns the shipped
[`DbDrVerifier`](../../src/fdai/core/verticals/resilience/db_dr_verifier.py)
and its Azure adapter
([`AzureDbDrRestoreAdapter`](../../src/fdai/delivery/azure/db_dr_restore.py))
into a repeatable operational procedure. The drill runs against a
production PostgreSQL Flexible Server without ever touching production
data - the restore lands in an **isolated resource group** the drill
tears down when done.

## When to run

- **Baseline schedule**: once per calendar month.
- **After schema migration**: within 7 days of every migration that
  changes user-visible tables.
- **On restore-adapter change**: any commit under
  [`src/fdai/delivery/azure/db_dr_restore.py`](../../src/fdai/delivery/azure/db_dr_restore.py)
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
4. Isolated resource group name is available in the subscription and
   does NOT clash with the source's resource group. The drill script
   generates a fresh name each run.
5. The deployment entry point composes `DbDrVerifier` with its restore,
  integrity, smoke, and audit adapters, then passes `verifier.run` to
  the CLI. Calling the upstream `main()` without this explicit runner
  exits with code `2` before any Azure mutation.

  ```python
  from fdai.core.verticals.resilience.db_dr_drill_cli import main

  raise SystemExit(main(verifier.run))
  ```
6. The injected HTTP client uses the Azure Resource Manager HTTPS origin as its
  origin-only `base_url`. The adapter accepts LRO pointers only from that same
  origin or as root-relative paths. The source is a canonical PostgreSQL
  Flexible Server ARM id; target resource-group, server, and region values are
  valid Azure path segments; and the restore timestamp is timezone-aware.

## Steps

1. **Pick a restore point.** Use a timestamp 30 minutes in the past to
   guarantee the PITR window covers it:

   ```bash
   RESTORE_TIME=$(date -u -d '-30 min' +%Y-%m-%dT%H:%M:%SZ)
   echo "Restore point: $RESTORE_TIME"
   ```

2. **Create the isolated resource group for the manual procedure.** Use a name that carries the
  drill timestamp so parallel drills do not collide. The automated
  `AzureDbDrRestoreAdapter` performs this step with `If-None-Match: *`, accepts only a 201
  ownership result, and rejects an existing group rather than adopting it:

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
   [`AzureDbDrRestoreAdapter`](../../src/fdai/delivery/azure/db_dr_restore.py)
  polls the LRO endpoint under a 30-minute budget by default. The budget uses monotonic elapsed
  time and includes token and HTTP latency, not only configured sleep intervals. The
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
   [`DbDrVerifier`](../../src/fdai/core/verticals/resilience/db_dr_verifier.py)
   consumes an
   [`IntegrityChecker`](../../src/fdai/shared/providers/db_dr.py)
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

7. **Tear down.** Delete the isolated resource group. The adapter's
  ``teardown`` path is idempotent - a 404 is a legal "already gone". A 202 response must provide
  an LRO pointer; the adapter polls it and verifies that the target group returns 404 before
  reporting cleanup success. Restore failure or cancellation also removes a group that the
  adapter itself created:

   ```bash
   az group delete -n "$DRILL_RG" --yes --no-wait
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

Drill passes iff all five hold:

- Restore completed under the configured budget
  (upstream default 30 minutes).
- Integrity report contains zero mismatches.
- Smoke report has at least one check and every check passed.
- The final ARM resource id exactly matches the requested restored server, and
  its valid FQDN starts with the requested target server name.
- Isolated resource group deletion returned 2xx (or 404 after retry).
- Every step wrote its audit entry - the drill is only "done" once the
  `restore_started` / `restore_ready` / `integrity_passed` /
  `smoke_passed` / `teardown_complete` events exist in the audit log. Every
  phase and teardown record carries the decision's unique `run_id` as its
  `correlation_id`, while `experiment_id` continues to identify the planned
  exercise. Phase idempotency keys must be unique inside that run.

`verification_passed` is an intermediate result. The final `passed` decision is written only after
`teardown_succeeded`. A teardown error produces `cleanup_failed`, preserves the primary verification
outcome for diagnosis, returns a nonzero CLI exit, and keeps the leaked resource as an owned
incident until cleanup is verified.

## Failure handling

- **Restore exceeds budget** → adapter emits `restore_timeout`;
  operator captures the last LRO status URL and files an incident.
  Teardown is still attempted.
- **Malformed successful LRO response** -> an HTTP 200 poll without a recognized string status is
  a restore failure, not an implicit running state. Preserve the operation reference and stop.
- **Integrity mismatch** → drill fails-closed. The mismatch report is
  the payload of the incident; do NOT delete the isolated resource
  group until an engineer confirms the sample (add a hold tag).
- **Smoke query fails** → same as integrity mismatch. Record the
  failing query + response.
- **Teardown 408, 429, or 5xx** -> retry with a bounded linear delay (5 attempts, 30-second
  spacing by default). Other 4xx responses fail immediately. If teardown still fails, page on-call: an isolated
  resource group left behind costs money and needs manual cleanup.

## Cost note

The isolated Postgres server incurs the standard Flexible Server
compute + storage rate for the duration of the drill. On the
day-zero Burstable B1ms + 32 GB storage tier that is a small hourly
figure, but it adds up if teardown is skipped. Alerts on the workload
tag `purpose=dr-drill` catch stray drill resource groups older than
24 hours.

## Related docs

- [phase-3-integrated-loop.md § Deep DB-DR (stateful - dedicated design)](../roadmap/phases/phase-3-integrated-loop.md)
- [security-and-identity.md](../roadmap/architecture/security-and-identity.md)
- [DbDrVerifier module docstring](../../src/fdai/core/verticals/resilience/db_dr_verifier.py)
