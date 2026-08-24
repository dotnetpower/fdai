# Programmatic Tool Pipelines implementation ledger

This delivery ledger preserves reviewable implementation scope, append-only transitions,
and resumable work while the roadmap owner remains focused on normative design.

## Implementation status

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| Immutable contracts and service orchestration | implemented | [`models.py`](../../../services/core-control-plane/src/fdai/core/programmatic_pipeline/models.py), [`service.py`](../../../services/core-control-plane/src/fdai/core/programmatic_pipeline/service.py), [`test_service.py`](../../../services/core-control-plane/tests/core/programmatic_pipeline/test_service.py) | Frozen contracts, digest binding, bounded terminal results, and idempotent aggregate reuse are implemented and covered by focused checks. |
| Source policy and generated client boundary | implemented | [`validator.py`](../../../services/core-control-plane/src/fdai/core/python_task/validator.py), [`client.py`](../../../services/core-control-plane/src/fdai/core/programmatic_pipeline/client.py), [`test_programmatic_pipeline_validator.py`](../../../services/core-control-plane/tests/core/python_task/test_programmatic_pipeline_validator.py) | Focused checks cover allowed data imports and reject filesystem, process, network, dynamic-code, introspection, and recursive-pipeline escape surfaces. |
| Capability authority and parent broker | implemented | [`capability.py`](../../../services/core-control-plane/src/fdai/core/programmatic_pipeline/capability.py), [`broker.py`](../../../services/core-control-plane/src/fdai/core/programmatic_pipeline/broker.py), [`test_capability_and_broker.py`](../../../services/core-control-plane/tests/core/programmatic_pipeline/test_capability_and_broker.py) | Authorization, one-time call consumption, registered-tool dispatch, byte limits, and bounded receipts pass focused checks. |
| Provider protocol and Azure-compatible adapter | implemented | [`programmatic_pipeline.py`](../../../services/core-control-plane/src/fdai/shared/providers/programmatic_pipeline.py), [`programmatic_pipeline.py`](../../../services/core-control-plane/src/fdai/delivery/azure/programmatic_pipeline.py), [`test_programmatic_pipeline.py`](../../../services/core-control-plane/tests/delivery/azure/test_programmatic_pipeline.py) | The provider-neutral protocol and strict managed-submission adapter are implemented and tested with an injected client. This is not a live Azure execution receipt. |
| Local isolated runner | not-started | [Runner adapters](../../roadmap/interfaces/programmatic-tool-pipelines.md#runner-adapters) | The documented Unix-socket, process-group, resource-limit, and bubblewrap runner has no concrete production implementation. Tests use in-memory runner fakes. |
| PostgreSQL persistence | implemented | [`20260720_0046_programmatic_pipeline.py`](../../../alembic/versions/20260720_0046_programmatic_pipeline.py), [`postgres_programmatic_pipeline.py`](../../../services/core-control-plane/src/fdai/delivery/persistence/postgres_programmatic_pipeline.py), [`test_postgres_programmatic_pipeline.py`](../../../services/core-control-plane/tests/persistence/test_postgres_programmatic_pipeline.py) | The schema, store, codecs, call receipt persistence, and aggregate result persistence pass three focused cases with zero skips against a disposable supported PostgreSQL database. |
| Deterministic benchmark | implemented | [`benchmark.py`](../../../services/core-control-plane/src/fdai/core/programmatic_pipeline/benchmark.py), [`test_benchmark.py`](../../../services/core-control-plane/tests/core/programmatic_pipeline/test_benchmark.py) | The fixed 20-call regression fixture checks the documented context and latency thresholds. It is not production performance evidence. |
| Production composition and operator submission | not-started | [`service.py`](../../../services/core-control-plane/src/fdai/core/programmatic_pipeline/service.py), [Operator surface](../../roadmap/interfaces/programmatic-tool-pipelines.md#operator-surface) | The service is exported but has no production composition caller, authenticated Operator API route, or console submission surface. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-08-13 | in-progress | Adopted an evidence-bounded implementation ledger without reconstructing earlier delivery history. | `current change`; current source listed in the scope table; component-focused checks passed 25 cases, while the PostgreSQL check passed 2 cases and skipped the live-database case because `FDAI_DATABASE_URL` was unset. | Implement the local runner and production composition, pass live persistence checks, and retain governed end-to-end evidence. |
| 2026-08-14 | implemented | Promoted PostgreSQL persistence after proving call and aggregate result round trips against a live database. | `current change`; `test_postgres_programmatic_pipeline.py` passed three cases with zero skips against a disposable supported database. | Implement the local runner and production composition, then retain governed end-to-end evidence. |

### Remaining work

- [ ] Implement the local `ProgrammaticPipelineRunner` with the documented Unix-socket broker, process-group termination, CPU and address-space limits, bubblewrap isolation, and cleanup checks for every terminal path.
- [ ] Bind `ProgrammaticPipelineService` in the production composition root and pass an end-to-end focused check that executes a reviewed pipeline through the registered `ToolExecutor` without bypassing access, redaction, or audit behavior.
- [x] Pass the PostgreSQL pipeline persistence test against the supported live-database fixture and retain the focused result before raising persistence to `implemented`.
- [ ] Add an authenticated Operator API submission path only with reviewed-source digest binding and tests proving that capability tokens, runner transport details, and credentials never cross the API boundary.
- [ ] Retain governed runtime receipts for a pinned revision that prove per-call and aggregate audit persistence, duplicate suppression, failure cleanup, and bounded output before raising any scope row to `validated`.
