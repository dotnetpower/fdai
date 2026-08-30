# FDAI Deployment CLI

This package provides the installable `fdaictl` deployment surface. It validates local
configuration, verifies signed deployment artifacts, and prepares resumable subscription-genesis
work without granting runtime execution authority.

## Commands

Run `fdaictl --help` for the current command tree. Commands default to read-only behavior, produce
stable JSON with `--output json`, and keep secrets out of command arguments and output.

Use `fdaictl onboard guided --simulate` to rehearse the complete stage graph without Azure
authentication or mutation. The rehearsal writes a private hash-chained journal and resumes
completed stages without duplicating them.

Use `fdaictl provision bootstrap-reconcile` before the first foundation approval. It performs only
target-pinned Azure management-plane reads and writes a private expiring plan whose intent and
observations have separate digests. It never creates a resource, registers a provider, writes
Terraform state, or dispatches a workflow.

Terminal journal events use schema v3 and bind completed stages to receipt digests. The aggregate
genesis readiness receipt requires every foundation, application, migration, semantic, model,
inventory, rollback, second-run no-change, and system-verification evidence family.
Legacy v1 and v2 journals remain readable for audit but are replay-only; a new run is required
before additional stages can be recorded.

## Testing

```bash
uv run --project packages/deployment-cli python -m pytest \
  -c packages/deployment-cli/pyproject.toml -q packages/deployment-cli/tests
```
