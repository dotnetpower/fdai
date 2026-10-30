# Diagnose database storage growth

Use aggregate PostgreSQL measurements to distinguish useful retained evidence from avoidable
storage and query costs. Table count alone does not establish wasted capacity.

> Scope: the commands on this page accept only the loopback development database on port 5432.
> Database tests use the separate validation cluster on port 5433. Nothing here authorizes
> production deletion, remote database access, or removal of audit and inventory evidence.

## What this guide covers

Inspect storage, apply approved disposable-state retention, and verify changes without confusing
logical deletion with physical disk reclamation. Preserve observation times, principal isolation,
rollback data, and deployment-owned retention policies.

## Measure before changing storage

With the existing local environment configured, run:

```bash
uv run python scripts/deployment/local/report-database-growth.py --json --details --no-sample
```

The report separates heap, indexes, and TOAST, PostgreSQL's out-of-line value storage. Live and
dead row counts are estimates. Index scan counts apply only since the reported statistics reset;
zero scans alone never justify dropping a unique, primary, or otherwise required index.

Omit `--no-sample` to save aggregate relation sizes for the next growth comparison. A changed
database or relation identity starts a new baseline. Samples contain metadata, not row contents
or connection values. Per-relation growth is reported in bytes per hour.

`--details` adds finite-time aggregate reads of binary payloads, expired cache rows, detached
legacy cache rows, and recorded retention policies. A partitioned parent's own size is not the
sum of its partitions; use the leaf-relation breakdown for physical capacity.
Missing tables are reported as `not_installed`. Insufficient read permission is explicit, sets
`details_complete` to false, and returns exit code 2 rather than presenting a missing measurement
as zero. The report never grants itself additional database privileges.

The detailed report also groups tracked state by fixed repository-owned families: Heimdall
episodes/readiness/publications, Saga recovery, baseline results/completions, control-loop
measurements, inventory, ontology, and Operator projections. Unknown keys appear only as `other`.
It reports stored-value bytes and the largest value without exposing keys, identifiers, or payloads.
These value sizes exclude heap/index/TOAST overhead and are not estimates of reclaimable disk.

Database insert/update/delete counters are cumulative since their statistics reset, not per-family
WAL attribution. I/O timing can be zero when `track_io_timing` is disabled; the report marks that
prerequisite rather than interpreting zero as free I/O. Capture runtime readiness and DB identity
with every comparison: a stopped process or a recreated database invalidates a normal-load trend.

## Bound disposable state by rows and bytes

The existing prefix-specific newest-N windows remain the minimum retained generations. Preview
their value storage and a proposed byte budget:

```bash
uv run python scripts/deployment/local/compact-local-database.py --max-prefix-bytes 67108864
```

The example budget is 64 MiB per supported prefix, not a product default. Value storage bytes
measure stored JSONB values; they exclude heap, indexes, TOAST page overhead, and free space.
The physical report remains authoritative for total disk capacity.

If a required newest-N window exceeds the budget, the command reports `blocked`, exits with
code 2, and performs no deletion. It never shrinks the required evidence window to fit.
After explicit local maintenance approval, add `--apply` to prune only the supported disposable
prefixes. Cleanup uses bounded transactions and rechecks both remaining rows and the byte budget
after concurrent writes. A remaining row backlog is explicit even when no byte budget was selected.
A later failure may leave earlier safe batches committed; retry only after reviewing the failure.

## Vacuum without an implicit rewrite

`--apply --vacuum` runs ordinary `VACUUM (ANALYZE)`. It makes deleted space reusable but does not
promise a smaller filesystem allocation. Schema migrations configure the high-churn `state_kv`
autovacuum and TOAST thresholds, so tuning does not depend on running a manual rewrite.

`--apply --vacuum-full` explicitly requests a table rewrite. It needs a maintenance window,
additional temporary disk space, and an exclusive table lock. Both paths retain connection,
statement, and lock deadlines.

## Diagnose checkpoint amplification

The fixed families `heimdall_buckets`, `saga_audit_checkpoint`, and
`saga_verdict_aggregate` separate recovery overhead from canonical history. A small latest
value does not rule out repeated large checkpoint rewrites or accumulated dead tuples.
Heimdall uses fixed reference buckets; PostgreSQL Saga uses a compact v3 head with indexed
canonical-ancestor recovery. Canonical audit rows remain intact, and restart restores the
same bounded 512-entry view rather than only the last entry.
The generated audit-header column adds per-record metadata storage. Include that column and its
index when comparing total audit size; a smaller checkpoint alone does not measure total cost.
Schemas without the ready header/index keep v2 writes. The header projection avoids loading raw
historical payloads during recovery and keeps the existing 512 KiB metadata-window admission.

Stop all old writers before compact-head cutover. Older readers cannot use v3 checkpoints.
Code rollback alone is insufficient: use a separately reviewed compatible checkpoint restore
while writers are stopped. Never remove canonical audit rows to make recovery or capacity pass.

## Explicitly recreate a disposable development database

Ordinary preparation and `--allow-recreate` preserve an under-limit database. After reviewing backup
and history requirements, stopping all local writers, and explicitly accepting data loss, use:

```bash
bash scripts/deployment/local/prepare-console-state.sh --recreate
```

This mode recreates the selected loopback `fdai` runtime database even below the normal size bound.
It preserves the active-connection guard, paired broker-reset marker, bounded private registration
preservation, and all five service migration branches. Missing size/connection accounting refuses
recreation. It does not terminate connections, select another database, change identity, or delete
unrelated Docker data. Tests still use the isolated port-5433 cluster, never this runtime database.

Rebuild size is not a storage-efficiency benchmark. Record initial schema, first complete inventory,
and matched steady workload separately. Complete authoritative initial inventory preparation before
starting the ordinary managed stack on an empty generation.

## Preserve contracts while optimizing queries

- State pages select and sort keys before fetching JSON bodies and obtain totals and page rows
  from one SQL snapshot. The existing offset API and exact totals remain compatible.
- Conversation lists aggregate only narrow key/time records, then fetch the first question and
  latest turn from their selected rows. Equal timestamps use stable key ordering. Principal
  scope, legacy conversation precedence, and cursor behavior are unchanged.
- Identical state writes already reuse the existing TOAST value while refreshing recency.
  Removing that timestamp update would change retention semantics. The regression test also
  preserves numeric representations such as `1` and `1.0`.

## Decisions that still need deployment evidence

The storage review has the following dispositions. Local implementation is not a completed
production migration or a claim that the running database is smaller.

| # | Review observation | Handling |
|---|----------------|----------|
| 1 | Repeated generation membership | Share immutable member/freshness pages and retain exact per-generation bindings without a replay chain. |
| 2 | Repeated snapshot properties | Share immutable staging bodies, preserve per-row observation metadata, and collect only unreferenced staging bodies. |
| 3 | Indefinite default retention | Preserve `retain` until the deployment supplies an approved policy and the existing archive/restore certification. |
| 4 | Expired rows in protected cache catalogs | Bounded expiry cleanup preserves active/rollback catalog bindings and immutable receipts. |
| 5 | Duplicate effective cache keys | Enforce exact-key uniqueness and preserve the reader's expiry/creation winner ordering. |
| 6 | Identical tracked-state writes | Withdraw unconditional no-op writes: existing TOAST reuse, timestamp refresh, and numeric-representation contracts are required. |
| 7 | Row-only capacity bounds | Add explicit byte-budget preview and refusal without shrinking required newest-N windows. |
| 8 | Generic JSON search | Add a selective principal/session index for the known hot conversation query; arbitrary JSON fields still need measured query-specific design. |
| 9 | Offset pages with exact counts | Sort keys before loading bodies and obtain count/page from one snapshot. Preserve the existing offset API rather than silently changing it to cursors. |
| 10 | Full utterance aggregation | Select first/last rows from narrow key/time records instead of building utterance arrays. |
| 11 | Unbounded retention deletion | Use 1,000-row transactions under one deadline and protect concurrently rewritten row versions. |
| 12 | Detached legacy cache | Measure retained data; retirement still requires a named approved rollback horizon and recovery evidence. |
| 13 | Binary bodies in PostgreSQL | Measure payload bytes; offload still requires selected storage, measured benefit, integrity/authorization parity, and rollback. |
| 14 | Manual-only vacuum tuning | Configure state/TOAST vacuum in a migration and separate ordinary vacuum from explicit full rewrites. |
| 15 | Undifferentiated growth reporting | Report heap/index/TOAST, estimated dead rows, relation growth, index usage, and explicit unavailable detail measurements. |

| Decision | Required evidence before applying it |
|----------|--------------------------------------|
| Finite inventory retention | Exact fact families, purpose, hot/warm/archive periods, applicable holds, verified restore coverage, and the existing non-shadow certification. Repository `retain` defaults remain unchanged. |
| Retire detached legacy cache data | Measured remaining data, an approved rollback horizon, exact maintenance scope, and tested recovery. Do not treat an upgrade as deletion permission. |
| Move binary payloads outside PostgreSQL | Measured payload/backup/replication cost, an independently selected storage backend, authorization and expiry parity, content/signature verification, atomic retrieval, and tested rollback. |

These are not completed data migrations. Reporting their costs is safe; silently inventing
retention periods, disabling immutable guards, or selecting a Blob account is not.

## Validate on the isolated database

```bash
python3 scripts/automation/with-local-test-database.py \
  uv run pytest -q --no-cov tests/integration/services/test_database_storage_efficiency.py
```

The focused checks verify multi-batch deletion bounds, filtered and escaped prefixes, exact empty
and offset-page totals, principal isolation, first/last timestamp ties, and conversation cursors.
Passing local checks does not prove production savings or a completed deployment.

## Related docs

| To learn about | Read |
|----------------|------|
| Inventory evidence and retention | [Continuous operational instance graph](../roadmap/architecture/continuous-operational-instance-graph.md) |
| Cache storage ownership | [Rule lookup ontology storage](../roadmap/architecture/rule-lookup-ontology-storage.md) |
