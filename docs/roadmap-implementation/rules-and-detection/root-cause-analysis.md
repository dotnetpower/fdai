# Root-Cause Analysis implementation ledger

This delivery ledger preserves reviewable implementation scope, append-only transitions,
and resumable work while the roadmap owner remains focused on normative design.

## Implementation status

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| T0, T1, and T2 hypothesis contracts and grounding | implemented | `services/core-control-plane/src/fdai/core/rca/`; focused RCA tests | T0 rule causes, stale-safe T1 reuse, deterministic causal chains, and grounded T2 parsing are implemented. |
| Knowledge evidence and provider binding | implemented | `core/rca/knowledge_evidence.py`; `shared/providers/knowledge.py`; `delivery/pgvector/knowledge.py`; `delivery/azure/llm/rca_model.py`; `runtime/bootstrap.py`; focused provider, adapter, and runtime tests | The runtime attaches the configured pgvector source after Azure LLM finalization as well as in telemetry-only mode. Re-ingestion atomically replaces a document's chunks and an empty replacement deletes them, so stale revisions do not remain searchable. Missing bindings never fabricate evidence. |
| Read-only operator projection | implemented | `services/operator-service/src/fdai_operator_service/rca_projection.py`; focused projection tests | Audit hypotheses, citations, structured causal chains, and linked response plans are projected without action authority. |
| Governed operational RCA accuracy | in-progress | [Observability and Detection](observability-and-detection.md#implementation-status) | No retained exact-revision cohort proves live cause accuracy, abstention, and downstream outcome closure across the tier mix. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-08-28 | implemented | Moved durable KnowledgeSource attachment after model finalization so Azure LLM mode no longer leaves RCA on the default empty source when a knowledge DSN is configured. The same guarded call preserves telemetry-only and local model behavior. Both in-memory and pgvector sources now treat re-ingestion as complete replacement, preserve the prior revision when embedding fails, remove obsolete chunks, and accept an empty replacement as deletion under a per-document transaction lock. | `current change`; `runtime/bootstrap.py`; `shared/providers/knowledge.py`; `delivery/pgvector/knowledge.py`; focused bootstrap and runtime configuration checks passed 42 cases; focused KnowledgeSource and SQL lifecycle checks passed 21 cases with one live-database parity case environment-gated; Ruff and strict mypy passed. | Retain a governed RCA cohort over deployment-owned indexed documents and bind source connectors to the replacement contract. |
| 2026-08-21 | in-progress | Moved the existing RCA tier, grounding, causal-chain, knowledge, and projection contracts into a focused owner document without changing runtime behavior or authority. | `current change`; document-size, translation, route, and link checks. | Retain a governed operational cohort with authoritative cause and outcome review. |

### Remaining work

- [ ] Retain an exact-revision operational cohort that measures supported causes, abstentions,
  stale reuse rejection, citation validity, and independently verified outcomes for T0, T1, and T2.
