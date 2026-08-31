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

After the approved foundation and runner are available, use `fdaictl deploy plan` to dispatch the
protected plan-only workflow. Read its request-bound status and sanitized plan id/digest with
`fdaictl deploy status`, then use `fdaictl deploy apply` with the plan id, digest, and
`--plan-expires-at` value from the sanitized `deploy status` plan metadata for the exact reviewed
plan.
`fdaictl onboard guided` composes the same plan/apply transport and requires
`--approve-application` before it can dispatch apply. Verification-only resume never reruns
Terraform apply.

Terminal journal events use schema v3 and bind completed stages to receipt digests. The aggregate
genesis readiness receipt requires every foundation, application, migration, semantic, model,
inventory, rollback, second-run no-change, and system-verification evidence family. Database and
semantic readback additionally requires all five service migration heads, the required PostgreSQL
extensions, passing runtime-role checks, exact ontology/catalog/default/role-manifest digests,
shadow-only defaults, and an independent observer.
Legacy v1 and v2 journals remain readable for audit but are replay-only; a new run is required
before additional stages can be recorded.

## Testing

```bash
uv run --project packages/deployment-cli python -m pytest \
  -c packages/deployment-cli/pyproject.toml -q packages/deployment-cli/tests
```
