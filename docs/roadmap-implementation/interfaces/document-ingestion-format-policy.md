# Governed Document Format Policy implementation ledger

This delivery ledger preserves reviewable implementation scope, append-only transitions, and
resumable work while the roadmap owner remains focused on normative design.

## Implementation status

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| Shared intake classification | implemented | `fdai_service_contracts/document_formats.py`; format-contract tests | Stable format ids, extensions, and media-type hints are shared across services; hints grant no trust. |
| Native and OCR extraction | implemented | document worker processing adapters; parser-parity and PDF-isolation tests | Text, PDF, OOXML, and OCR paths retain bounded extraction and typed failures. |
| Capability-driven Console guidance | implemented | document ingestion route and focused Console tests | Picker filters and labels follow server capabilities; server validation remains authoritative. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-09-05 | implemented | Split the governed format policy from the legacy ingestion owner without changing runtime behavior. | `current change`; focused Python document and deployment checks passed 206 cases; focused Console tests passed 8 cases; Console typecheck passed. | Retain governed runtime evidence for OCR-enabled image intake and warning states. |

### Remaining work

- [ ] Retain an authenticated runtime receipt proving supported image intake, OCR-unavailable
  rejection, and `ready_with_warnings` behavior against the advertised capability set.
