---
title: Operator API Production Deployment
---
# Operator API Production Deployment

The upstream repo ships the console Operator API as the independent
[`fdai-operator-service`](../../../services/operator-service/) distribution. Local and deployed
profiles use the same public ASGI factory, `fdai_operator_service.main:create_app`, while explicit
environment values select the execution venue, Entra verifier, PostgreSQL stores, and Kafka
transport. This document covers the deployed production composition.

> **Scope**: this is a Tier B reference. The full dev/prod parity contract
> lives in [dev-and-deploy-parity.md](dev-and-deploy-parity.md); the
> deployment topology lives in [deployment.md](deployment.md).

## Implementation status

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| Independent service entrypoint and environment validation | implemented | `services/operator-service/src/fdai_operator_service/main.py`, `production.py`, `environment.py`, and composition tests | The service owns one factory and validates listener, Entra, RBAC, CORS, database, and semantic-transport combinations before provider use. |
| Entra authentication and bounded Operator authorization | implemented | `services/operator-service/src/fdai_operator_service/auth.py`, route-family authorization, and focused service tests | Human identity remains separate from the executor identity; wildcard CORS and partial semantic transport fail closed. |
| PostgreSQL read and family stores | implemented | `postgres.py`, `postgres_family_store.py`, and `test_operator_service_postgres.py` | DSN normalization, connection bounds, role binding, per-transaction statement timeout, and unavailable projections are implemented. |
| Kafka semantic transport and Live/Agents relay | implemented | `adapters/`, `streaming/`, `test_semantic_kafka_adapter.py`, `test_semantic_turn_bridge.py`, and `test_live_stream.py` | Local plaintext and deployed managed-identity transport remain explicit execution-venue choices. |
| Independently deployed Operator service | validated | `.github/workflows/service-deploy.yml` and `config/independent-service-live-evidence-manifest.json` | Repository-safe live evidence covers the separately packaged service, migration branch, health, and rollback boundary. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-08-14 | validated | Adopted the implementation ledger; earlier provenance was not reconstructed. Updated the reference from the retired co-hosted facade to the independent Operator service. | current change; focused Operator service checks and the independent-service live evidence manifest | Keep the environment contract, service tests, deployment workflow, and live evidence manifest synchronized as the service evolves. |

### Remaining work

- [x] No implementation work remains for the bounded production-composition scope documented here; focused service tests and `config/independent-service-live-evidence-manifest.json` provide the current implementation and operational evidence.

## Design at a glance

- **Service-owned factory.** The deployed process calls
  [`fdai_operator_service.main:create_app`](../../../services/operator-service/src/fdai_operator_service/main.py),
  which builds the service-owned runtime without importing the control-plane implementation.
  Cloud-resource mutation remains outside the API. Opt-in
  POST routes record proposals, approvals, or access requests but never hold
  the executor identity. The
  staging/prod tripwires (CORS `*` refused, dev-mode refused) apply
  identically.
- **Env-only composition.** Every value arrives through environment variables. The database DSN
  and webhook secret use Key Vault references; non-secret tenant, audience, group, and topic
  values are plain env injected by IaC. No config file or customer identifier is baked into the
  image.
- **Fail-fast on invalid config.** Missing or invalid required identity and transport values raise
  `OperatorServiceConfigurationError` before provider construction. Database omission is an
  explicit unavailable-projection state for profiles that don't configure PostgreSQL; deployed
  production supplies both the DSN and the exact `fdai_operator` role.
- **Fail-fast on database readiness.** Before user context, skills, streams, or other runtime
  services start, the Postgres read model executes a bounded `SELECT 1`. A connection failure
  aborts lifespan startup, so `/healthz` never presents an unconnected revision as ready.
- **Observable access failures.** Every `401` and `403` emits a structured warning with only the
  request path and exception class. Authorization headers, bearer tokens, principal ids, and
  exception text are never logged.
- **Kafka-backed Live and Agent observation.** The factory always registers the authenticated
  `/live/stream` and `/agents/stream` read routes. When the Kafka bootstrap endpoint is configured,
  one service-owned consumer group reads `aw.pipeline.stages`, validates stage and Pantheon runtime-state
  records, and fans accepted records into separate bounded process-local SSE sinks. The app
  lifespan starts and stops the relay and closes its independently owned Kafka
  consumer. Without Kafka configuration, the route remains connected with
  keepalives and reports `Awaiting source`; it never presents transport connectivity
  as runtime evidence. The console uses authenticated fetch streaming because the
  browser's native `EventSource` API cannot attach an `Authorization` header.
- **Durable Agents bootstrap.** The Agents page first loads the Postgres-backed
  incident roster, including server-derived involved agents, and then overlays
  newer stage events from `/agents/stream`. An audit-stage frame resolves a
  ticket only for a recorded remediation outcome; HIL, deny, and abstain remain
  active and completed stage owners return to idle.

## Environment contract

Required (fail-fast at startup):

| Variable | Purpose |
|----------|---------|
| `FDAI_DATABASE_URL` | Deployed production psycopg 3 DSN. Accepted schemes: `postgresql://`, `postgres://`, and `postgresql+psycopg://`. When omitted, database-backed projections are explicitly unavailable. |
| `FDAI_DATABASE_ROLE` | Must be `fdai_operator` whenever `FDAI_DATABASE_URL` is set. |
| `FDAI_ENTRA_TENANT_ID` | Consumed by [`EntraJwtVerifier.from_env`](../../../services/operator-service/src/fdai_operator_service/). |
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
| `FDAI_OPERATOR_API_CORS_ALLOW_ORIGINS` | empty (same-origin) | Comma-separated origin list. A bare `*` element is rejected unconditionally by this factory (regardless of `RUNTIME_ENV`) - a cross-origin deploy MUST list the console origins explicitly. |
| `FDAI_OPERATOR_DATABASE_STATEMENT_TIMEOUT_MS` | `20000` | Applied transaction-locally with `set_config('statement_timeout', ..., true)` on database operations. |
| `FDAI_OPERATOR_DATABASE_CONNECT_TIMEOUT_S` | `10` | Bounds the TCP and authentication handshake so an unavailable database fails promptly. |
| `FDAI_KAFKA_BOOTSTRAP_SERVERS` | empty | Starts the semantic transport and the shared Live/Agent observation relay. Uses the Event Hubs Kafka endpoint on `:9093`. An empty value leaves both SSE routes connected in `Awaiting source` without fabricating runtime evidence. |
| `KAFKA_TOPIC_EVENTS` | empty | With Kafka bootstrap, enables `POST /chat/action` for typed actions and the confirmed incident workflow. The value is the same raw ingress topic consumed by Huginn. |
| `FDAI_STAGE_TOPIC` | `aw.pipeline.stages` | Stage topic published by the worker and consumed by the Live and Agents relays. The worker and Operator API should use the same value. |
| `FDAI_INCIDENT_SLA_POLICY_JSON` | empty (disabled) | Strict JSON object with positive `acknowledge_seconds` and `resolve_seconds` values for every `sev1` through `sev5`; enables durable A2 SLA-breach monitoring. |
| `FDAI_INCIDENT_SLA_INTERVAL_SECONDS` | `60` | Positive SLA scan interval; used only when the policy JSON is present. |
| `FDAI_IAM_DIRECTORY_PROVIDER` | empty (directory search disabled) | Enables Owner-only human-directory search. The implemented value is `entra`; unsupported future provider names fail startup. |
| `FDAI_IAM_ENTRA_GRAPH_BASE_URL` | `https://graph.microsoft.com/v1.0` | Microsoft Graph base URL for sovereign-cloud or test overrides. Used only when the directory provider is `entra`. |
| `FDAI_NARRATOR_PROBE_INTERVAL_SECONDS` | `300` | Seconds between routed narrator latency probes. Minimum `30`; each periodic round adds one model-only sample per candidate. |
| `FDAI_WEB_SEARCH_ENABLED` | `false` | Enables controlled Azure Responses web search for eligible Chat T2 turns. Requires resolved web-search candidates and an allowed-domain list. |
| `FDAI_WEB_SEARCH_ALLOWED_DOMAINS` | empty | Comma-separated public source domains. Required when web search is enabled; at most 100 domains. Each entry also allows its DNS subdomains. |
| `FDAI_WEB_SEARCH_FOUNDRY_PROJECT_ENDPOINT` | empty | Optional Foundry project HTTPS endpoint. Configure together with `FDAI_WEB_SEARCH_FOUNDRY_AGENT_NAME` to use a prompt agent whose Web Search tool has the exact allowed-domain list. |
| `FDAI_WEB_SEARCH_FOUNDRY_AGENT_NAME` | empty | Optional Foundry prompt-agent name. Partial Foundry configuration fails startup. Runtime domain changes that don't match the provisioned agent fail closed. |
| `FDAI_WEB_SEARCH_FOUNDRY_MODEL_DEPLOYMENT` | resolved direct candidate | Sanitized model deployment referenced by the Foundry prompt agent and projected in Settings. Terraform supplies the deployment-owned value when Foundry search is enabled. |
| `FDAI_WEB_SEARCH_MAX_RESULTS` | `3` | Maximum citations retained from one search, from `1` through `10`. |
| `FDAI_WEB_SEARCH_BUDGET_MS` | `15000` | Per-search endpoint timeout in milliseconds. |
| `FDAI_WEB_SEARCH_PROBE_INTERVAL_SECONDS` | `300` | Seconds between web-search candidate model probes. Minimum `30`; probes don't invoke the search tool. |

Web search sends only the bounded operator query to Azure Responses. It never
sends the current screen snapshot or conversation history. Azure web search
uses Grounding with Bing, whose transfer can leave the deployment's compliance
and geography boundary and isn't covered by the Microsoft Data Protection
Addendum. Keep the feature disabled until the deployment owner accepts those
terms and configures a primary-source allowlist.

Terraform exposes the provider as `operator_api_iam_directory_provider`; its default is empty.
Set it to `entra` only after the Operator API managed identity has the required Graph consent.

The Entra directory adapter requests `https://graph.microsoft.com/.default`
through the Operator API's managed identity and needs Microsoft Graph application
permission `User.Read.All` with admin consent. The permission is read-only and
`GroupMember.Read.All` is also required to project configured FDAI role groups
and their person members. Both permissions are read-only, aren't sent to the
browser, and don't include group membership write access.

## Run it

```bash
uvicorn fdai_operator_service.main:create_app \
    --factory --host 0.0.0.0 --port 8000
```

The `app` factory is called once per worker; every env var above must be
in scope for the process. In a Container Apps revision the env is
projected from a `containerapp.secrets` entry that references the Key
Vault secret directly ([app-shape.instructions.md § Azure Mapping](../../../.github/instructions/app-shape.instructions.md#azure-mapping-draft---reconfirm-preview-services-at-adoption-time)).

## What lives where

- [`main.py`](../../../services/operator-service/src/fdai_operator_service/main.py) - public ASGI factory export and service entrypoint.
- [`production.py`](../../../services/operator-service/src/fdai_operator_service/production.py) - validated uvicorn lifecycle.
- [`environment.py`](../../../services/operator-service/src/fdai_operator_service/environment.py) - immutable environment validation.
- [`composition.py`](../../../services/operator-service/src/fdai_operator_service/composition.py) - Entra, PostgreSQL, route-family, semantic bus, relay, readiness, and lifecycle composition.
- [`postgres.py`](../../../services/operator-service/src/fdai_operator_service/postgres.py) and [`postgres_family_store.py`](../../../services/operator-service/src/fdai_operator_service/postgres_family_store.py) - authoritative read and family stores.
- [`adapters/live_stage_kafka.py`](../../../services/operator-service/src/fdai_operator_service/adapters/live_stage_kafka.py)
  - owns the Kafka consumer lifecycle and commit-after-processing behavior.
- [`streaming/live_stream.py`](../../../services/operator-service/src/fdai_operator_service/) and
  [`streaming/stage_frames.py`](../../../services/operator-service/src/fdai_operator_service/) and
  [`streaming/agent_frames.py`](../../../services/operator-service/src/fdai_operator_service/)
  - provide bounded SSE fan-out, validate untrusted stage/runtime records, and preserve the
  `event: stage` and agent `event: message` contracts expected by the browser.

## Testing

- `services/operator-service/tests/test_operator_service_composition.py` - environment and composition guards.
- `services/operator-service/tests/test_operator_service_postgres.py` - DSN, query, timeout, and row mapping contracts.
- `services/operator-service/tests/test_live_stream.py` - stage relay, malformed-frame rejection, and lifecycle behavior.
- `services/operator-service/tests/test_semantic_kafka_adapter.py` and `test_semantic_turn_bridge.py` - semantic transport, replay, lease, and lifecycle behavior.

## Related docs

| To learn about | Read |
|----------------|------|
| dev/prod parity contract | [dev-and-deploy-parity.md](dev-and-deploy-parity.md) |
| deployment topology | [deployment.md](deployment.md) |
| RBAC + identity flow | [../interfaces/user-rbac-and-identity.md](../interfaces/user-rbac-and-identity.md) |
| console read-only invariant | [../../../.github/instructions/app-shape.instructions.md](../../../.github/instructions/app-shape.instructions.md) |
