# Operator API Production Deployment implementation ledger

This delivery ledger preserves reviewable implementation scope, append-only transitions,
and resumable work while the roadmap owner remains focused on normative design.

## Implementation status

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| Independent service entrypoint and environment validation | implemented | `services/operator-service/src/fdai_operator_service/main.py`, `production.py`, `environment.py`, and composition tests | The service owns one factory and validates listener, Entra, RBAC, CORS, database, and semantic-transport combinations before provider use. |
| Entra authentication and bounded Operator authorization | implemented | `services/operator-service/src/fdai_operator_service/auth.py`, route-family authorization, and focused service tests | Human identity remains separate from the executor identity; wildcard CORS and partial semantic transport fail closed. |
| PostgreSQL read and family stores | implemented | `postgres.py`, `postgres_family_store.py`, and `test_operator_service_postgres.py` | DSN normalization, connection bounds, role binding, per-transaction statement timeout, and unavailable projections are implemented. |
| Kafka semantic transport and Live/Agents relay | implemented | `adapters/`, `streaming/`, `test_semantic_kafka_adapter.py`, `test_semantic_turn_bridge.py`, and `test_live_stream.py` | Local plaintext and deployed managed-identity transport remain explicit execution-venue choices. Live late subscribers receive only the process-local stage frames accepted during the preceding 60 seconds. |
| Independently deployed Operator service | validated | `.github/workflows/service-deploy.yml` and `config/independent-service-live-evidence-manifest.json` | Repository-safe live evidence covers the separately packaged service, migration branch, health, and rollback boundary. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-09-07 | implemented | Added capacity- and time-bounded recent-stage replay plus a fresh validated runtime-source marker for new Live subscribers without changing the durable History boundary. | `current change`; Live hub, Kafka relay, browser hook, and focused tests; Operator pytest passed 16 cases; Console Vitest passed 22 cases; Ruff, mypy, and Console typecheck passed. | Governed runtime validation remains separate; replay resets on Operator API restart and source readiness expires without a fresh Huginn observation. |
| 2026-08-14 | validated | Adopted the implementation ledger; earlier provenance was not reconstructed. Updated the reference from the retired co-hosted facade to the independent Operator service. | current change; focused Operator service checks and the independent-service live evidence manifest | Keep the environment contract, service tests, deployment workflow, and live evidence manifest synchronized as the service evolves. |

### Remaining work

- [x] No implementation work remains for the bounded production-composition scope documented here; focused service tests and `config/independent-service-live-evidence-manifest.json` provide the current implementation and operational evidence.
