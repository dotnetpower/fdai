# Document Ingestion and Drop Zone implementation ledger

This delivery ledger preserves reviewable implementation scope, append-only transitions,
and resumable work while the roadmap owner remains focused on normative design.

## Implementation status

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| Contracts, lifecycle, and bounds | implemented | service contracts; ingestion API and worker lifecycle tests | Shared records, bounded lifecycle transitions, retention, and access controls remain owned here. Format eligibility and extraction behavior moved to the focused format-policy owner. |
| Independent upload API and processing worker | implemented | `services/document-ingestion-api/`; `services/document-processing-worker/`; service-owned tests | Separate ASGI and worker packages implement scoped upload, processing, health, storage, event, and handover boundaries. |
| Governed automated RCA read binding | implemented | `delivery/persistence/postgres_governed_document_read.py`; `delivery/governed_rca_context.py`; Core service Terraform; focused governed RCA tests | Core accepts a separate read-only DSN secret and exact collection, access-reference, and reader-group configuration. Search filters before ranking and rechecks current metadata and group authorization before evidence admission. This does not validate a deployed document read. |
| PostgreSQL, ADLS, pgvector, Event Hubs, embeddings, and ClamAV bindings | in-progress | Independent service adapters; `infra/modules/storage/adls-gen2/`; `infra/local/docker-compose.yml` | Delivery implementations and local/deployed configuration exist, but this ledger does not have one governed exact-topology receipt covering every binding and failure boundary. |
| Rights management, OCR, preview, and revocation | in-progress | [Implementation boundaries and rollout](../../roadmap/interfaces/document-ingestion.md#implementation-boundaries-and-rollout) | Detection and seams exist. Purview/RMS access, delegated authorization, OCR composition, preview, and revocation reconciliation remain provider work. |
| Resumable upload, connectors, and measured scale | not-started | [Connector and scale](../../roadmap/interfaces/document-ingestion.md#implementation-boundaries-and-rollout) | Block-resumable upload, connector delta sync, and measured capacity targets remain design work. |
| ACL-filtered hybrid document retrieval | implemented | `services/document-ingestion-api/src/fdai_ingestion_api_service/adapters/postgres.py`; focused document-search tests | One common authorized relation filters governed chunks by collection and access descriptor before bounded semantic and lexical ranking. Deterministic reciprocal-rank fusion changes no document visibility or execution authority. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-09-05 | implemented | Moved format eligibility, extraction behavior, and OCR-specific residual work to the focused governed document format policy without changing runtime behavior. | `current change`; [format policy](../../roadmap/interfaces/document-ingestion-format-policy.md) and its implementation ledger. | Continue the end-to-end lifecycle and capacity work below; track format-specific runtime evidence in the focused ledger. |
| 2026-09-04 | implemented | Added one enforced format allowlist and bounded extraction matrix for modern Office, PDF, text, and OCR-backed images. Embedded PDF and OOXML images retain cited OCR units or explicit warnings, formulas remain inert text, and legacy Office binaries are rejected with conversion guidance. | `current change`; shared contract plus explicit ingestion service suites (411 passed, including role-scoped loopback PostgreSQL), strict mypy, Ruff, Console type/build, and two focused browser scenarios. | Retain a deployed OCR receipt against a reviewed mixed-format corpus and record accuracy, latency, and failure-rate baselines. |
| 2026-09-04 | implemented | Bound the governed-document RCA consumer to automated Incident T2 through a fixed system principal, incident-review purpose, separate read-only DSN, exact collection/access configuration, and fail-closed startup pairing. | `current change`; focused governed context, automated T2, authorization, strict mypy, Ruff, and Core service Terraform checks. | Retain the deployed read receipt and the five-service operational receipt. |
| 2026-09-04 | implemented | Added the separate governed-document RCA evidence consumer. It uses collection-scoped search, rechecks current metadata and authorization, and binds revision, purpose, scope, cutoff, redaction, and citation evidence without opening the unscoped KnowledgeSource. | `current change`; focused governed-document adapter, RCA coordinator, and OperationalEvidenceBundle checks. | Bind the deployment-owned governed context provider and retain the five-service operational receipt. |
| 2026-08-14 | in-progress | Adopted the implementation ledger; earlier provenance was not reconstructed. | `current change`; current contracts, core lifecycle, service packages, adapters, and focused checks listed in the scope table. | Close exact-topology, protection-provider, connector, and scale evidence. |
| 2026-08-29 | implemented | Added ACL-filtered hybrid PostgreSQL retrieval. Both ranking branches consume one collection- and access-filtered candidate relation, use bounded deterministic ranks, and return a normalized reciprocal-rank fusion score. | `current change`; document-search adapter and focused offline plus loopback PostgreSQL checks. | Bind a deployment-owned connector and ACL source, then retain governed corpus accuracy and latency evidence. |


### Remaining work

- [ ] Retain one governed five-service local and deployed receipt for upload, scan, protection inspection, extraction, indexing, citation, deletion, restart, and failure recovery using the exact service identities and contracts.
- [ ] Implement and focused-test the selected Purview/RMS, delegated authorization, preview, and revocation-reconciliation providers without removing source protection.
- [ ] Implement block-resumable upload and connector delta synchronization with bounded idempotency, deletion propagation, backpressure, and restart tests.
- [ ] Record p50/p95 stage latency, queue delay, throughput, storage growth, and failure-rate baselines on a reviewed corpus before declaring capacity targets or wider format support.
