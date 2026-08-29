# Document Ingestion and Drop Zone implementation ledger

This delivery ledger preserves reviewable implementation scope, append-only transitions,
and resumable work while the roadmap owner remains focused on normative design.

## Implementation status

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| Contracts, lifecycle, bounds, and local format extraction | implemented | `packages/service-contracts/src/fdai_service_contracts/document.py`; `services/core-control-plane/src/fdai/core/document_ingestion/`; local document providers; focused ingestion and provider tests | Bounded upload state, protection states, safe text, OOXML, strict PDF, chunking, and fail-closed transitions have focused coverage. |
| Independent upload API and processing worker | implemented | `services/document-ingestion-api/`; `services/document-processing-worker/`; service-owned tests | Separate ASGI and worker packages implement scoped upload, processing, health, storage, event, and handover boundaries. |
| ACL-filtered hybrid document retrieval | implemented | `services/document-ingestion-api/src/fdai_ingestion_api_service/adapters/postgres.py`; focused document-search tests | One common authorized relation filters governed chunks by collection and access descriptor before bounded semantic and lexical ranking. Deterministic reciprocal-rank fusion changes no document visibility or execution authority. |
| PostgreSQL, ADLS, pgvector, Event Hubs, embeddings, and ClamAV bindings | in-progress | Independent service adapters; `infra/modules/storage/adls-gen2/`; `infra/local/docker-compose.yml` | Delivery implementations and local/deployed configuration exist, but this ledger does not have one governed exact-topology receipt covering every binding and failure boundary. |
| Rights management, OCR, preview, and revocation | in-progress | [Implementation boundaries and rollout](../../roadmap/interfaces/document-ingestion.md#implementation-boundaries-and-rollout) | Detection and seams exist. Purview/RMS access, delegated authorization, OCR composition, preview, and revocation reconciliation remain provider work. |
| Resumable upload, connectors, and measured scale | not-started | [Connector and scale](../../roadmap/interfaces/document-ingestion.md#implementation-boundaries-and-rollout) | Block-resumable upload, connector delta sync, and measured capacity targets remain design work. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-08-29 | implemented | Added ACL-filtered hybrid PostgreSQL retrieval. Both ranking branches consume one collection- and access-filtered candidate relation, use bounded deterministic ranks, and return a normalized reciprocal-rank fusion score. | `current change`; document-search adapter and focused offline plus loopback PostgreSQL checks. | Bind a deployment-owned connector and ACL source, then retain governed corpus accuracy and latency evidence. |
| 2026-08-14 | in-progress | Adopted the implementation ledger; earlier provenance was not reconstructed. | `current change`; current contracts, core lifecycle, service packages, adapters, and focused checks listed in the scope table. | Close exact-topology, protection-provider, connector, and scale evidence. |

### Remaining work

- [ ] Retain one governed five-service local and deployed receipt for upload, scan, protection inspection, extraction, indexing, citation, deletion, restart, and failure recovery using the exact service identities and contracts.
- [ ] Implement and focused-test the selected Purview/RMS, delegated authorization, OCR, preview, and revocation-reconciliation providers without removing source protection.
- [ ] Implement block-resumable upload and connector delta synchronization with bounded idempotency, deletion propagation, backpressure, and restart tests.
- [ ] Record p50/p95 stage latency, queue delay, throughput, storage growth, and failure-rate baselines on a reviewed corpus before declaring capacity targets or wider format support.
