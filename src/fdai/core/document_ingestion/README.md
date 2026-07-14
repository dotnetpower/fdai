# `core/document_ingestion`

This subsystem owns document upload-session metadata and the fail-closed processing lifecycle. It
never receives the executor identity: object storage, scanning, protection inspection, extraction,
artifact storage, indexing, access checks, and activity delivery enter through async provider seams.

## Files

| File | Responsibility |
|------|----------------|
| `state_machine.py` | Pure allowed lifecycle transitions from upload through deletion. |
| `service.py` | Authorize and create/resume/complete/cancel upload sessions without proxying source bytes. |
| `worker.py` | Run mandatory malware, protection, extraction, indexing, availability, and lineage-aware deletion stages. |

## Safety behavior

- A scanner or protection-provider failure holds the document; it never skips the stage.
- Content is unavailable until indexing commits successfully.
- Rights-managed, encrypted, unknown, or infected content is held before extraction.
- Activity records contain ids, hashes, policy references, and outcomes, never source text.
- Deletion removes retrieval and derived artifacts before marking the version deleted.

## Testing

The deterministic contract and adapters are covered under
[tests/core/document_ingestion](../../../../tests/core/document_ingestion/). The HTTP boundary tests
are under [tests/delivery/ingestion_gateway](../../../../tests/delivery/ingestion_gateway/).
