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

Shared Plan, Release, and constraint checks stay in
[packages/deployment-cli/](../packages/deployment-cli) until the `lifecycle-contracts` extraction in
Lifecycle I1.

## Testing

The root `pyproject.toml` collects `lifecycle/` tests. Run one component's tests from the repository
root:

```bash
uv run --no-sync pytest lifecycle/hub/tests -q
```
