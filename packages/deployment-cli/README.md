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

## Offline release preparation

Use `fdaictl offline prepare` with an independently trusted verifier, verification keys, a signed
kit, an offline target-bound profile, a positive cost ceiling, an exact source revision, and a new
private work directory. It snapshots the CLI toolchain, signed deployment bundle, and a complete
local runtime inventory without network calls or artifact execution.

The runtime inventory requires archives for all five services, Console, and deployment support,
with hashes, SBOMs, service provenance, and a binding to the exact deployment bundle bytes.
Registry references without local payloads do not qualify. Release staging accepts these prebuilt
inputs through `stage-offline-kit.sh --runtime-release <directory>`.

`prepared/preparation.json` reports `state=prepared`, `subscription_ready=false`, and the remaining
approval and independent-readback checkpoints. This is not an Azure installer, production trust
bootstrap, or a ready receipt. Existing public-artifact GitHub deployment commands reject offline
profiles before authentication or dispatch.
See [Disconnected Deployment](../../docs/roadmap/deployment/disconnected-deployment.md).

### Configure prebuilt Console files

The packaging host uses `npm --prefix console run build:offline` to build tenant-neutral files
without loading local env files or exposing process `VITE_*` values. Copy `console/dist/offline/`
into a private mode-`0700` installation directory. No Node.js rebuild runs on the installer host.

Create a mode-`0600` JSON file in a private directory with your actual public bindings:

```json
{
  "schema_version": "fdai.console-runtime.v1",
  "operator_api_base_url": "https://operator.example.com",
  "ingestion_api_base_url": "https://ingestion.example.com",
  "tenant_id": "00000000-0000-0000-0000-000000000000",
  "spa_client_id": "00000000-0000-0000-0000-000000000001",
  "api_scope": "api://00000000-0000-0000-0000-000000000002/access"
}
```

```bash
fdaictl offline configure-console --directory /private/console \
  --settings /private/console-settings.json --output json
```

The command replaces only the shipped placeholder and refuses a silent tenant change.
Runtime bindings always require Entra authentication; no bypass flag is accepted. Preserve the
generated hosting configuration so `fdai-config.js` is not cached. Entra registration, matching
API verifier/CORS settings, site publication, and authenticated readback remain separate steps.

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
