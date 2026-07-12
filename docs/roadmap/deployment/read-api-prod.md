---
title: Read-API Production Deployment
---
# Read-API Production Deployment

The upstream repo ships two ASGI entrypoints for the console read API:
the dev harness ([`src/fdai/delivery/read_api/dev/local.py`](../../../src/fdai/delivery/read_api/dev/local.py))
that boots an :class:`InMemoryConsoleReadModel` behind
:class:`UnsafeClaimsExtractor`, and the production entrypoint
([`src/fdai/delivery/read_api/prod.py`](../../../src/fdai/delivery/read_api/prod.py))
that composes real Entra JWT verification and a Postgres-backed read
model from environment only. This doc covers the production entrypoint.

> **Scope**: this is a Tier B reference. The full dev/prod parity contract
> lives in [dev-and-deploy-parity.md](dev-and-deploy-parity.md); the
> deployment topology lives in [deployment.md](deployment.md).

## Design at a glance

- **Same `build_app` glue.** The prod factory calls the shared
  [`build_app`](../../../src/fdai/delivery/read_api/main.py) with
  `dev_mode=False`, so the read-only invariant (no POST routes) and the
  staging/prod tripwires (CORS `*` refused, dev-mode refused) apply
  identically.
- **Env-only composition.** Every value the factory needs arrives via
  environment variables the fork's IaC populates from Key Vault
  references. No config file is required and no customer identifier is
  baked into the image.
- **Fail-fast on missing config.** Any missing required env raises
  :class:`ProdReadApiConfigError` (a `ValueError` subclass) at startup;
  a broken revision never binds a socket. A cold boot with an entirely
  unpopulated env yields ONE error that enumerates every missing slot,
  instead of eight sequential boot failures.

## Environment contract

Required (fail-fast at startup):

| Variable | Purpose |
|----------|---------|
| `FDAI_DATABASE_URL` | psycopg 3 DSN. Accepted schemes: `postgresql://`, `postgres://`, `postgresql+psycopg://`. Any other `+<driver>` suffix (`+asyncpg`, `+psycopg2`, ...) is rejected at boot with a `ProdReadApiConfigError`. Points at the `audit_log` + `state_kv` schema the writer already provisions via `alembic upgrade head`. |
| `FDAI_ENTRA_TENANT_ID` | Consumed by [`EntraJwtVerifier.from_env`](../../../src/fdai/delivery/read_api/entra_verifier.py). |
| `FDAI_API_AUDIENCE` | The `fdai-api` App ID URI (`api://<guid>`). |
| `FDAI_RBAC_READERS_GROUP_ID` | Entra group `objectId` mapped to the Reader role. |
| `FDAI_RBAC_CONTRIBUTORS_GROUP_ID` | Entra group `objectId` mapped to Contributor. |
| `FDAI_RBAC_APPROVERS_GROUP_ID` | Entra group `objectId` mapped to Approver. |
| `FDAI_RBAC_OWNERS_GROUP_ID` | Entra group `objectId` mapped to Owner. |
| `FDAI_RBAC_BREAK_GLASS_GROUP_ID` | Entra group `objectId` mapped to Break-Glass. |

Optional (defaults apply):

| Variable | Default | Purpose |
|----------|---------|---------|
| `FDAI_ENTRA_ISSUER` | `https://login.microsoftonline.com/<tenant>/v2.0` | Override for v1 tokens or sovereign clouds. |
| `FDAI_ENTRA_JWKS_URI` | tenant discovery endpoint | Override for air-gapped clouds. |
| `FDAI_READ_API_CORS_ALLOW_ORIGINS` | empty (same-origin) | Comma-separated origin list. A bare `*` element is rejected unconditionally by this factory (regardless of `RUNTIME_ENV`) - a cross-origin deploy MUST list the console origins explicitly. |
| `FDAI_READ_API_STATEMENT_TIMEOUT_MS` | `20000` | Applied via `SET LOCAL statement_timeout` on every read query. |
| `FDAI_READ_API_CONNECT_TIMEOUT_S` | `10` | Bounds the TCP + auth handshake so a dead DB fails fast. |

## Run it

```bash
uvicorn fdai.delivery.read_api.prod:app \
    --factory --host 0.0.0.0 --port 8000
```

The `app` factory is called once per worker; every env var above must be
in scope for the process. In a Container Apps revision the env is
projected from a `containerapp.secrets` entry that references the Key
Vault secret directly ([app-shape.instructions.md § Azure Mapping](../../../.github/instructions/app-shape.instructions.md#azure-mapping-draft---reconfirm-preview-services-at-adoption-time)).

## What lives where

- [`prod.py`](../../../src/fdai/delivery/read_api/prod.py) - the
  env-only composition root and the `app()` factory.
- [`postgres_read_model.py`](../../../src/fdai/delivery/read_api/postgres_read_model.py)
  - the concrete :class:`ConsoleReadModel` on top of `audit_log` +
    `state_kv`. Pure row-to-dataclass mappers + a bounded KPI
    aggregation live in the same module so they are unit-tested without
    a live DB.
- [`main.py`](../../../src/fdai/delivery/read_api/main.py) - shared
  `build_app` glue (route registration, `_authorize` gate, staging/prod
  tripwires).

## Testing

- `tests/delivery/read_api/test_prod.py` - env parsing + composition
  guards (no DB round-trip).
- `tests/delivery/read_api/test_postgres_read_model_units.py` - row
  mappers, cursor parsing, KPI aggregation (no DB round-trip).
- `tests/persistence/test_postgres_console_read_model.py` -
  end-to-end round-trip against a live Postgres. Skipped unless
  `FDAI_DATABASE_URL` is set; the local `docker-compose` dev stack
  (`bash scripts/dev-up.sh`) exposes it as
  `postgresql+psycopg://fdai:devonly@localhost:5432/fdai`.

## Related docs

| To learn about | Read |
|----------------|------|
| dev/prod parity contract | [dev-and-deploy-parity.md](dev-and-deploy-parity.md) |
| deployment topology | [deployment.md](deployment.md) |
| RBAC + identity flow | [../interfaces/user-rbac-and-identity.md](../interfaces/user-rbac-and-identity.md) |
| console read-only invariant | [../../../.github/instructions/app-shape.instructions.md](../../../.github/instructions/app-shape.instructions.md) |
