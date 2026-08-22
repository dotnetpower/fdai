# FDAI Operator Service

`fdai-operator-service` provides the authenticated, non-privileged HTTP boundary used by the FDAI
Console and operator clients. It serves authoritative projections and submits typed requests into
the governed control loop without receiving executor identity or directly changing managed
resources.

## Responsibilities

- Authenticate operator and workload principals and apply server-owned role checks.
- Serve bounded read projections, operational requests, conversation history, and live streams.
- Persist and bridge versioned semantic-turn requests and results between Operator and Core.
- Run the separately packaged Slack and Teams channel-edge entry point.
- Render operator-facing reports, with PDF support available as an optional package extra.

## Service Boundary

The service does not own control-loop decisions, policy evaluation, approval decisions, or effect
execution. Requests that can lead to an action re-enter the typed Core pipeline and its safety
checks. The Console and channel adapters never receive the isolated Executor identity.

## Layout

| Path | Purpose |
|------|---------|
| `src/fdai_operator_service/application.py`, `routes.py` | ASGI application and HTTP routes |
| `src/fdai_operator_service/auth.py`, `family_authorization.py` | Authentication and family-scoped authorization |
| `src/fdai_operator_service/families/` | Conversation, identity, operations, and workflow API families |
| `src/fdai_operator_service/families/conversation/channel_edge/` | Slack and Teams edge runtime |
| `src/fdai_operator_service/postgres*.py` | Service-owned durable projections and stores |
| `src/fdai_operator_service/reporting/` | Optional report rendering |
| `tests/` | Service-owned unit, contract, and integration tests |
| `docker/Dockerfile` | Container image definition built from the repository root |

## Run Locally

The standard full-stack profile prepares browser authentication, PostgreSQL, Redpanda, and the
service environment before binding the Operator API to port `8010`. In a prepared environment, use
the packaged entry points:

```bash
uv run fdai-operator-service
uv run fdai-operator-channel-edge
```

The channel edge is a separate process in the same distribution, not a sixth FDAI service.

## Testing

Run the service-owned test groups from the repository root:

```bash
make service-test SERVICE=operator-service
```

The canonical group membership is defined in `tests/integration/service-suites.json`.

## Related Documentation

| To learn about | Read |
|----------------|------|
| Local prerequisites and services | [Development guide](../../DEVELOPING.md) |
| Console and API integration | [Console README](../../console/README.md) |
| Operator request safety | [Console operations](../../docs/roadmap/interfaces/console-operations.md) |
| Service and data ownership | [Service graduation and data ownership](../../docs/roadmap/architecture/service-graduation-and-ownership.md) |
| Shared cross-service contracts | [Service contracts README](../../packages/service-contracts/README.md) |
