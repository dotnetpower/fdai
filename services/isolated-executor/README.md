# FDAI Isolated Executor

`fdai-isolated-executor-service` is the dedicated event-consumer boundary for validated execution
commands and effect receipts. Its service descriptor is the only one with
`executor_authority=True`; local operation remains in shadow mode, where commands are evaluated
and recorded without a managed-resource change.

## Responsibilities

- Consume versioned Executor commands and publish bounded shadow or effect receipts.
- Revalidate command identity, target scope, safety evidence, and execution mode before dispatch.
- Enforce stable idempotency and logical-target locking around every effect attempt.
- Keep provider calls behind service-owned HTTP and identity adapters.
- Record intent before an effect and close each attempt with a terminal audit outcome.

## Service Boundary

The service does not choose an action, evaluate control-loop policy, approve its own work, or serve
operator HTTP requests. Core proposes and authorizes work through the governed pipeline. Deployment
identity and promotion state determine whether a validated command can proceed beyond shadow mode;
an environment switch alone cannot grant authority.

## Layout

| Path | Purpose |
|------|---------|
| `src/fdai_executor_service/service.py`, `lifecycle.py` | Command handling and service lifecycle |
| `src/fdai_executor_service/effect_safety.py` | Pre-dispatch safety validation |
| `src/fdai_executor_service/effect_executor.py` | Provider effect dispatch and outcome mapping |
| `src/fdai_executor_service/lock.py` | Durable idempotency and logical-target locking |
| `src/fdai_executor_service/ports.py` | Service-owned transport and persistence ports |
| `src/fdai_executor_service/adapters/` | Event-bus, PostgreSQL, HTTP, and identity adapters |
| `tests/` | Service-owned unit, contract, integration, and smoke tests |
| `docker/Dockerfile` | Container image definition built from the repository root |

## Run Locally

The standard full-stack profile prepares PostgreSQL, Redpanda, and a local shadow environment with
no managed-resource identity. In that prepared environment, start the service with:

```bash
uv run fdai-isolated-executor-service
```

The local health endpoint is bound by the full-stack profile on port `8013`.

## Testing

Run the service-owned test groups from the repository root:

```bash
make service-test SERVICE=isolated-executor
```

The canonical group membership is defined in `tests/integration/service-suites.json`.

## Related Documentation

| To learn about | Read |
|----------------|------|
| Local prerequisites and services | [Development guide](../../DEVELOPING.md) |
| Service authority and cutover | [Service graduation and data ownership](../../docs/roadmap/architecture/service-graduation-and-ownership.md) |
| Identity and execution safeguards | [Security and identity](../../docs/roadmap/architecture/security-and-identity.md) |
| Shared Executor contracts | [Service contracts README](../../packages/service-contracts/README.md) |
