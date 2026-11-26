# FDAI Core Control Plane

`fdai-core-control-plane` runs FDAI's headless decision and coordination runtime. It owns the
control loop, the 15-agent Pantheon, service composition, and evidence-governed command publication
without serving the operator-facing HTTP API.

## Responsibilities

- Normalize and correlate events before routing them through T0 deterministic rules, T1
  lightweight similarity reuse, or T2 grounded model reasoning.
- Run policy, quality, safety, human approval, audit, recovery, and effect-verification stages.
- Host the fixed agent Pantheon and its typed event boundaries.
- Compose provider-neutral interfaces with local or deployed adapters.
- Publish versioned cross-service requests and consume bounded receipts through
  `fdai-service-contracts`.

## Service Boundary

The runtime entry point does not host the FDAI Console, Operator API, document upload API, or
isolated Executor process. Services exchange versioned records instead of importing another
service implementation. Effect authority remains a separately governed deployment concern: the
Isolated Executor is the target sole holder, and the current cutover state is recorded in the
service ownership design.

## Layout

| Path | Purpose |
|------|---------|
| `src/fdai_core_service/` | Service entry point, service codecs, and semantic-turn processing |
| `src/fdai/core/` | Control-loop decisions, safety gates, evidence handling, and domain logic |
| `src/fdai/agents/` | Fixed 15-agent Pantheon and typed collaboration boundaries |
| `src/fdai/runtime/` | Process lifecycle, supervision, and runtime bindings |
| `src/fdai/composition/` | Dependency-injection composition root |
| `src/fdai/delivery/` | Provider and transport adapters plus bounded service jobs |
| `tests/` | Service-owned unit, contract, and integration tests |
| `docker/Dockerfile` | Container image definition built from the repository root |

## Run Locally

Use the repository development setup to prepare PostgreSQL, Redpanda, service configuration, and
the local execution venue. After the required environment is loaded, start the service with:

```bash
uv run fdai-core-control-plane
```

The maintenance entry point `fdai-browser-evidence-cleanup` is packaged separately from the
long-running control-plane process.

## Testing

Run the service-owned test groups from the repository root:

```bash
make service-test SERVICE=core-control-plane
```

The canonical group membership is defined in `tests/integration/service-suites.json`.

## Related Documentation

| To learn about | Read |
|----------------|------|
| Local prerequisites and services | [Development guide](../../DEVELOPING.md) |
| Core subsystem layout | [Core README](src/fdai/core/README.md) |
| Agent roles and event boundaries | [Agent README](src/fdai/agents/README.md) |
| Service and data ownership | [Service graduation and data ownership](../../docs/roadmap/architecture/service-graduation-and-ownership.md) |
| Shared cross-service contracts | [Service contracts README](../../packages/service-contracts/README.md) |
