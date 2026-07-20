---
title: Read-API Production Deployment
---
# Read-API Production Deployment

The upstream repo ships two ASGI entrypoints for the console read API:
the local facade ([`src/fdai/delivery/read_api/dev/local.py`](../../../src/fdai/delivery/read_api/dev/local.py))
that requires Entra or an explicit Azure CLI principal plus authoritative Azure views by default,
and permits `UnsafeClaimsExtractor` plus synthetic views only under pytest's
`test_fixtures=True`; and the production facade
([`src/fdai/delivery/read_api/prod.py`](../../../src/fdai/delivery/read_api/prod.py))
that composes real Entra JWT verification and a Postgres-backed read
model from environment only. This doc covers the production entrypoint.

> **Scope**: this is a Tier B reference. The full dev/prod parity contract
> lives in [dev-and-deploy-parity.md](dev-and-deploy-parity.md); the
> deployment topology lives in [deployment.md](deployment.md).

## Design at a glance

- **Same `build_app` glue.** The prod factory calls the shared
  [`build_app`](../../../src/fdai/delivery/read_api/main.py) with
  `dev_mode=False`, so cloud-resource mutation remains outside the API. Opt-in
  POST routes record proposals, approvals, or access requests but never hold
  the executor identity. The
  staging/prod tripwires (CORS `*` refused, dev-mode refused) apply
  identically.
- **Env-only composition.** Every value arrives through environment variables. The database DSN
  and webhook secret use Key Vault references; non-secret tenant, audience, group, and topic
  values are plain env injected by IaC. No config file or customer identifier is baked into the
  image.
- **Fail-fast on missing config.** Any missing required env raises
  :class:`ProdReadApiConfigError` (a `ValueError` subclass) at startup;
  a broken revision never binds a socket. A cold boot with an entirely
  unpopulated env yields ONE error that enumerates every missing slot,
  instead of eight sequential boot failures.
- **Kafka-backed Live observation.** When the Kafka bootstrap endpoint is
  configured, the factory registers `/live/stream` and `/agents/stream`.
  Separate consumer groups read the shared `aw.pipeline.stages` topic and fan
  validated stage records into process-local SSE sinks. The app lifespan starts
  and stops both relays and closes the shared EventBus transport. These SSE GET
  routes use the same Entra bearer authorization as snapshot GET routes. The
  console consumes them with authenticated fetch streaming because the browser's
  native `EventSource` API cannot attach an `Authorization` header.
- **Durable Agents bootstrap.** The Agents page first loads the Postgres-backed
  incident roster, including server-derived involved agents, and then overlays
  newer stage events from `/agents/stream`. An audit-stage frame resolves a
  ticket only for a recorded remediation outcome; HIL, deny, and abstain remain
  active and completed stage owners return to idle.

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
| `FDAI_KAFKA_BOOTSTRAP_SERVERS` | empty | Enables the production Live and Agents SSE relays. Uses the Event Hubs Kafka endpoint on `:9093`; an empty value leaves both optional routes unregistered. |
| `KAFKA_TOPIC_EVENTS` | empty | With Kafka bootstrap, enables `POST /chat/action` for typed actions and the confirmed incident workflow. The value is the same raw ingress topic consumed by Huginn. |
| `FDAI_STAGE_TOPIC` | `aw.pipeline.stages` | Stage topic published by the worker and consumed by the Live and Agents relays. The worker and read API should use the same value. |
| `FDAI_INCIDENT_SLA_POLICY_JSON` | empty (disabled) | Strict JSON object with positive `acknowledge_seconds` and `resolve_seconds` values for every `sev1` through `sev5`; enables durable A2 SLA-breach monitoring. |
| `FDAI_INCIDENT_SLA_INTERVAL_SECONDS` | `60` | Positive SLA scan interval; used only when the policy JSON is present. |
| `FDAI_IAM_DIRECTORY_PROVIDER` | empty (directory search disabled) | Enables Owner-only human-directory search. The implemented value is `entra`; unsupported future provider names fail startup. |
| `FDAI_IAM_ENTRA_GRAPH_BASE_URL` | `https://graph.microsoft.com/v1.0` | Microsoft Graph base URL for sovereign-cloud or test overrides. Used only when the directory provider is `entra`. |
| `FDAI_NARRATOR_PROBE_INTERVAL_SECONDS` | `300` | Seconds between routed narrator latency probes. Minimum `30`; each periodic round adds one model-only sample per candidate. |
| `FDAI_WEB_SEARCH_ENABLED` | `false` | Enables controlled Azure Responses web search for eligible Chat T2 turns. Requires resolved narrator candidates and an allowed-domain list. |
| `FDAI_WEB_SEARCH_ALLOWED_DOMAINS` | empty | Comma-separated public source hosts. Required when web search is enabled; at most 100 exact hosts. |
| `FDAI_WEB_SEARCH_MAX_RESULTS` | `3` | Maximum citations retained from one search, from `1` through `10`. |
| `FDAI_WEB_SEARCH_BUDGET_MS` | `15000` | Per-search endpoint timeout in milliseconds. |
| `FDAI_WEB_SEARCH_PROBE_INTERVAL_SECONDS` | `300` | Seconds between web-search candidate model probes. Minimum `30`; probes don't invoke the search tool. |

Web search sends only the bounded operator query to Azure Responses. It never
sends the current screen snapshot or conversation history. Azure web search
uses Grounding with Bing, whose transfer can leave the deployment's compliance
and geography boundary and isn't covered by the Microsoft Data Protection
Addendum. Keep the feature disabled until the deployment owner accepts those
terms and configures a primary-source allowlist.

Terraform exposes the provider as `read_api_iam_directory_provider`; its default is empty.
Set it to `entra` only after the read API managed identity has the required Graph consent.

The Entra directory adapter requests `https://graph.microsoft.com/.default`
through the read API's managed identity and needs Microsoft Graph application
permission `User.Read.All` with admin consent. The permission is read-only and
`GroupMember.Read.All` is also required to project configured FDAI role groups
and their person members. Both permissions are read-only, aren't sent to the
browser, and don't include group membership write access.

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

- [`prod.py`](../../../src/fdai/delivery/read_api/prod.py) - the stable import facade and
  `app()` factory.
- [`production/config.py`](../../../src/fdai/delivery/read_api/production/config.py) and
  [`production/factory.py`](../../../src/fdai/delivery/read_api/production/factory.py) - the
  actual owners of environment validation and Postgres/Entra/provider composition.
- [`postgres_read_model.py`](../../../src/fdai/delivery/read_api/postgres_read_model.py)
  - the concrete :class:`ConsoleReadModel` on top of `audit_log` +
    `state_kv`. Pure row-to-dataclass mappers + a bounded KPI
    aggregation live in the same module so they are unit-tested without
    a live DB.
- [`main.py`](../../../src/fdai/delivery/read_api/main.py) - shared
  `build_app` glue (route registration, `_authorize` gate, staging/prod
  tripwires).
- [`streaming/live_stage_broadcaster.py`](../../../src/fdai/delivery/read_api/streaming/live_stage_broadcaster.py)
  - validates stage records from Kafka and preserves the raw `event: stage`
  SSE contract expected by the browser.

## Testing

- `tests/delivery/read_api/test_prod.py` - env parsing + composition
  guards (no DB round-trip).
- `tests/delivery/read_api/streaming/test_live_stage_broadcaster.py` - raw
  stage relay, malformed-frame rejection, and lifecycle behavior.
- `tests/delivery/read_api/test_postgres_read_model_units.py` - row
  mappers, cursor parsing, KPI aggregation (no DB round-trip).
- `tests/persistence/test_postgres_console_read_model.py` -
  end-to-end round-trip against a live Postgres. Skipped unless
  `FDAI_DATABASE_URL` is set; the local `docker-compose` dev stack
  (`bash scripts/deployment/local/dev-up.sh`) exposes it as
  `postgresql+psycopg://fdai:devonly@localhost:5432/fdai`.

## Related docs

| To learn about | Read |
|----------------|------|
| dev/prod parity contract | [dev-and-deploy-parity.md](dev-and-deploy-parity.md) |
| deployment topology | [deployment.md](deployment.md) |
| RBAC + identity flow | [../interfaces/user-rbac-and-identity.md](../interfaces/user-rbac-and-identity.md) |
| console read-only invariant | [../../../.github/instructions/app-shape.instructions.md](../../../.github/instructions/app-shape.instructions.md) |
