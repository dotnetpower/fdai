# FDAI Document Processing Worker

`fdai-document-processing-worker` consumes governed document lifecycle work and owns the durable
processing transitions after upload. It inspects content, extracts bounded knowledge artifacts,
and publishes progress without exposing a public upload API.

## Responsibilities

- Consume versioned document events with stable delivery and idempotency identities.
- Claim processing stages durably before inspection, extraction, or handover.
- Run protection and malware checks before content extraction.
- Extract supported document structures and persist bounded knowledge chunks.
- Publish worker-owned lifecycle events and readiness evidence.

## Service Boundary

The worker does not grant upload access, serve operator HTTP requests, select control-loop actions,
or hold executor authority. It receives document work through shared contracts and keeps storage,
transport, inspection, and extraction implementations behind service-owned adapters.

## Layout

| Path | Purpose |
|------|---------|
| `src/fdai_document_worker_service/consumer.py`, `supervisor.py` | Event consumption and process supervision |
| `src/fdai_document_worker_service/processing.py`, `effects.py` | Inspection, extraction, and durable effects |
| `src/fdai_document_worker_service/state_machine.py` | Worker-owned document transitions |
| `src/fdai_document_worker_service/handover.py` | Bounded downstream handover |
| `src/fdai_document_worker_service/adapters/` | Storage, database, scanner, and event-bus adapters |
| `src/fdai_document_worker_service/composition.py`, `production.py` | Service composition and deployed bindings |
| `tests/` | Service-owned unit, contract, and smoke tests |
| `docker/Dockerfile` | Container image definition built from the repository root |

## Run Locally

The standard full-stack profile prepares PostgreSQL, Redpanda, document storage, inspection, and
the service environment. In a prepared environment, start the event-consumer loop with:

```bash
uv run fdai-document-processing-worker
```

The local health endpoint is bound by the full-stack profile on port `8012`.

## Testing

Run the service-owned test groups from the repository root:

```bash
make service-test SERVICE=document-processing-worker
```

The canonical group membership is defined in `tests/integration/service-suites.json`.

## Related Documentation

| To learn about | Read |
|----------------|------|
| Local prerequisites and services | [Development guide](../../DEVELOPING.md) |
| Document lifecycle and interfaces | [Document ingestion](../../docs/roadmap/interfaces/document-ingestion.md) |
| Service and data ownership | [Service graduation and data ownership](../../docs/roadmap/architecture/service-graduation-and-ownership.md) |
| Shared cross-service contracts | [Service contracts README](../../packages/service-contracts/README.md) |
