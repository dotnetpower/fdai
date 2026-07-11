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
data — the restore lands in an **isolated resource group** the drill
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
2. Source server has a non-empty PITR window — `az postgres flexible-server show`
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

## Steps

1. **Pick a restore point.** Use a timestamp 30 minutes in the past to
   guarantee the PITR window covers it:

   ```bash
   RESTORE_TIME=$(date -u -d '-30 min' +%Y-%m-%dT%H:%M:%SZ)
   echo "Restore point: $RESTORE_TIME"
   ```

2. **Create the isolated resource group.** Use a name that carries the
   drill timestamp so parallel drills do not collide:

   ```bash
   DRILL_RG="rg-fdai-dr-drill-$(date +%Y%m%d-%H%M)"
   az group create -n "$DRILL_RG" -l koreacentral \
     --tags workload=fdai purpose=dr-drill drill-ts=$(date +%Y-%m-%d)
   ```

3. **Trigger the PITR restore.** The target server name is a globally
   unique Azure identifier — include the timestamp so it does not
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
   polls the LRO endpoint under a 30-minute budget by default; the
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
   at the restored server and run a bounded smoke suite — one query
   per user-facing table plus a session write to a smoke schema. Any
   error fails the drill.

7. **Tear down.** Delete the isolated resource group; the adapter's
   ``teardown`` path is idempotent — a 404 is a legal "already gone":

   ```bash
   az group delete -n "$DRILL_RG" --yes --no-wait
   ```

## Success criteria

Drill passes iff all five hold:

- Restore completed under the configured budget
  (upstream default 30 minutes).
- Integrity report contains zero mismatches.
- Smoke report has at least one check and every check passed.
- Isolated resource group deletion returned 2xx (or 404 after retry).
- Every step wrote its audit entry — the drill is only "done" once the
  `restore_started` / `restore_ready` / `integrity_passed` /
  `smoke_passed` / `teardown_complete` events exist in the audit log.

## Failure handling

- **Restore exceeds budget** → adapter emits `restore_timeout`;
  operator captures the last LRO status URL and files an incident.
  Teardown is still attempted.
- **Integrity mismatch** → drill fails-closed. The mismatch report is
  the payload of the incident; do NOT delete the isolated resource
  group until an engineer confirms the sample (add a hold tag).
- **Smoke query fails** → same as integrity mismatch. Record the
  failing query + response.
- **Teardown 5xx** → retry with linear backoff (5 attempts, 30-second
  spacing). If teardown still fails, page on-call: an isolated
  resource group left behind costs money and needs manual cleanup.

## Cost note

The isolated Postgres server incurs the standard Flexible Server
compute + storage rate for the duration of the drill. On the
day-zero Burstable B1ms + 32 GB storage tier that is a small hourly
figure, but it adds up if teardown is skipped. Alerts on the workload
tag `purpose=dr-drill` catch stray drill resource groups older than
24 hours.

## Related docs

- [phase-3-integrated-loop.md § Deep DB-DR (stateful — dedicated design)](../roadmap/phases/phase-3-integrated-loop.md)
- [security-and-identity.md](../roadmap/security-and-identity.md)
- [DbDrVerifier module docstring](../../src/fdai/core/verticals/resilience/db_dr_verifier.py)
