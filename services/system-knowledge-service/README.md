# FDAI System Knowledge Service

`fdai-system-knowledge-service` is an independently packaged, read-only Teams mention endpoint for
questions about FDAI design, implementation status, verification evidence, and known limitations.
It supports a Bot Framework application or a team-scoped Outgoing Webhook, uses a release-bound
catalog, and has no operational provider or execution authority.

## Responsibilities

- Verify a Bot Framework JWT or Teams Outgoing Webhook HMAC before reading the question.
- Search reviewed English and Korean aliases deterministically.
- Present designed behavior, implemented evidence, limitations, and source citations.
- Preserve retry and ambiguous-send state in SQLite locally and Blob CAS when deployed.
- Expose independent liveness and readiness.

## Service Boundary

The service does not import Core or Operator Service implementations. It does not read customer
documents, Azure resources, Incidents, or conversation history. The runtime image contains a
compiled catalog but no repository source or Git credential.

## Layout

| Path | Purpose |
|------|---------|
| `src/fdai_system_knowledge_service/catalog.py` | Release catalog compilation and loading |
| `src/fdai_system_knowledge_service/search.py` | Deterministic bilingual retrieval |
| `src/fdai_system_knowledge_service/teams_{auth,ingress,outgoing_webhook,publisher}.py` | Teams authentication, mention parsing, synchronous webhook response, and Bot publishing |
| `src/fdai_system_knowledge_service/ledger.py`, `blob_ledger.py` | Local SQLite and deployed Managed Identity Blob CAS claims |
| `src/fdai_system_knowledge_service/runtime.py` | Query, rendering, delivery, and failure coordination |
| `src/fdai_system_knowledge_service/application.py` | Health and Teams HTTP routes |
| `tests/` | Service-owned contract and behavior tests |
| `teams-app/manifest.template.json` | Mention-only Teams application package template |
| `docker/Dockerfile` | Non-root service image |

## Build the catalog

Run the compiler from the repository root after a cited source changes:

```bash
uv run fdai-system-knowledge-build-catalog \
  --repo-root . \
  --protected-main-ref refs/remotes/origin/main \
  --output services/system-knowledge-service/src/fdai_system_knowledge_service/data/catalog.json
```

## Run locally

Provide the deployment-owned Teams identifiers, select `bot_framework` or `outgoing_webhook` with
`FDAI_SYSTEM_KNOWLEDGE_TEAMS_TRANSPORT`, and start the service:

```bash
uv run fdai-system-knowledge-service
```

The default listener is `127.0.0.1:8015`.

## Testing

```bash
uv run pytest -q --no-cov services/system-knowledge-service/tests \
  packages/service-contracts/tests/test_system_knowledge.py
```

## Related documentation

| To learn about | Read |
|----------------|------|
| Design and trust boundary | [System Knowledge Service](../../docs/roadmap/interfaces/system-knowledge-service.md) |
| Delivery state | [Implementation ledger](../../docs/roadmap-implementation/interfaces/system-knowledge-service.md) |
| General operational channel runtime | [Production A3 channel runtime](../../docs/roadmap/interfaces/production-a3-channel-runtime.md) |
