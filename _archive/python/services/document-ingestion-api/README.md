# FDAI Document Ingestion API

`fdai-document-ingestion-api` is the authenticated HTTP boundary for governed document intake. It
owns upload sessions, API-side lifecycle transitions, metadata persistence, and durable event
publication while leaving content processing to the Document Processing Worker.

## Responsibilities

- Authorize upload, status, search, cancellation, and deletion requests.
- Create and advance upload sessions with revision and ownership checks.
- Bind direct-upload storage grants and service-owned object metadata.
- Write API-owned lifecycle and deletion events through the durable outbox.
- Expose health and readiness through the service application.

## Service Boundary

The API does not inspect, extract, or index uploaded content and has no control-loop decision or
executor authority. Processing work crosses the event boundary through versioned
`fdai-service-contracts` records. Storage, transport, and database implementations remain in this
service's adapters and composition root.

## Layout

| Path | Purpose |
|------|---------|
| `src/fdai_ingestion_api_service/application.py`, `http.py` | Application lifecycle and HTTP routes |
| `src/fdai_ingestion_api_service/auth.py`, `access.py` | Principal authentication and document access checks |
| `src/fdai_ingestion_api_service/ingestion.py`, `deletion.py` | Upload and deletion application services |
| `src/fdai_ingestion_api_service/state_machine.py` | API-owned document transitions |
| `src/fdai_ingestion_api_service/adapters/` | Database, object-store, and event-bus adapters |
| `src/fdai_ingestion_api_service/composition.py`, `production.py` | Service composition and deployed bindings |
| `tests/` | Service-owned contract and integration tests |
| `docker/Dockerfile` | Container image definition built from the repository root |

## Run Locally

The standard full-stack profile prepares PostgreSQL, Redpanda, document storage, and the service
environment before binding the API to port `8011`. In a prepared environment, start it with:

```bash
uv run fdai-document-ingestion-api
```

## Testing

Run the service-owned test groups from the repository root:

```bash
make service-test SERVICE=document-ingestion-api
```

The canonical group membership is defined in `tests/integration/service-suites.json`.

## Related Documentation

| To learn about | Read |
|----------------|------|
| Local prerequisites and services | [Development guide](../../DEVELOPING.md) |
| Document lifecycle and interfaces | [Document ingestion](../../docs/roadmap/interfaces/document-ingestion.md) |
| Service and data ownership | [Service graduation and data ownership](../../docs/roadmap/architecture/service-graduation-and-ownership.md) |
| Shared cross-service contracts | [Service contracts README](../../packages/service-contracts/README.md) |
