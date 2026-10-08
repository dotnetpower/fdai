# FDAI Lifecycle

This directory holds the components of the
[Hub-managed lifecycle](../docs/roadmap/deployment/hub-managed-lifecycle.md), the third FDAI
installation path. A Lifecycle Hub decides which Release each installation should run, and a
lifecycle agent beside each installation verifies and applies that decision.

These components aren't installation services. Each one is a standalone distribution with its own
tests, so the five-service set under `services/` stays unchanged.

## Layout

| Path | Purpose | Story |
|------|---------|-------|
| [hub/](hub/README.md) | Lifecycle Hub: computes, signs, and serves Lifecycle Plans, and records execution reports | #1949 |
| `agent/` | Lifecycle agent: polls the Hub, verifies Plans, and reports dry-run results | #1951 |
| `tests/` | Hub-agent lifecycle loop, end to end on loopback | #1952 |

Shared Plan, Release, and constraint checks stay in
[packages/deployment-cli/](../packages/deployment-cli) until the `lifecycle-contracts` extraction in
Lifecycle I1.

## Testing

The root `pyproject.toml` collects `lifecycle/` tests. Run one component's tests from the repository
root:

```bash
uv run --no-sync pytest lifecycle/hub/tests -q
```

### Lifecycle loop

`lifecycle/tests/` runs the Hub-agent loop end to end on loopback (#1952). Each scenario uses the
Hub command line to enroll and approve the sample installation, manage its `core` Entity, and
compute a Plan. It then runs the agent's `poll-once` against the Hub API over HTTP and reads the
result back with `show`. Keys are generated for each test, and no key material is committed. The
test removes Azure credential variables from its environment.

| Scenario | Expected result |
|----------|-----------------|
| Signed Release and configuration package | The agent reports `dry_run_computed`. The Hub records the Plan, its constraint results, and the report |
| Unsigned Release | The agent rejects the Plan with `release_signature_missing`, and the Hub records the reason |
| Plan for another installation | A misrouted network path serves another installation's Plan. The agent rejects it with `plan_audience_mismatch`, and the Hub records the reason |
| Replayed sequence | After the agent admits sequence 2, a network path serves sequence 1 again. The agent rejects it with `plan_sequence_stale`, and the Hub records the reason |
| Outside every maintenance window | The Hub issues no Plan and records `maintenance_window_unavailable` |

Run the scenarios with one command from the repository root:

```bash
uv run --no-sync pytest -c pyproject.toml lifecycle/tests -q
```

The command runs every scenario on SQLite. To also run them on PostgreSQL, set `FDAI_DATABASE_URL`
to the loopback database from `infra/local/docker-compose.yml`. CI runs the SQLite scenarios in the
regression shards and the PostgreSQL scenarios in the database integration job.

The Hub and the agent compare the reported-state digest as an opaque value that the installation
supplies. Neither one derives it from the snapshot content yet.
