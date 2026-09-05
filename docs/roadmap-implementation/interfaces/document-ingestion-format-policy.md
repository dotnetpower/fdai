# Governed Document Format Policy implementation ledger

This delivery ledger preserves reviewable implementation scope, append-only transitions, and
resumable work while the roadmap owner remains focused on normative design.

## Implementation status

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| Shared intake classification | implemented | `fdai_service_contracts/document_formats.py`; format-contract tests | Stable format ids, extensions, and media-type hints are shared across services; hints grant no trust. |
| Native and OCR extraction | implemented | `local_ocr.py`; parser-parity, PDF-isolation, and local Korean OCR tests; OCR-enabled worker image smoke | Text, PDF, OOXML, and process-isolated Korean and English OCR paths retain bounded extraction and typed failures. |
| Capability-driven Console guidance | implemented | document ingestion route and focused Console tests | Picker filters and labels follow server capabilities; server validation remains authoritative. |
| Revisioned OCR provider policy | implemented | `document_ocr.py`; Operator IAM routes and PostgreSQL adapter; 142 focused Python tests | Owner policy and plan requests bind environment, revision, digest, idempotency key, and `execution_authority: false`; `plan-requested` is durable. |
| OCR Settings experience | implemented | `document-ocr-settings.tsx`; bilingual integration catalogs; 35 focused Console tests; typecheck and production build | Operators can select local or Azure OCR, retry a failed plan request, retain Azure while switching local, or request explicit removal. |
| Terraform-owned Document Intelligence | implemented | `infra/modules/document-intelligence`; root private endpoint, DNS, RBAC; `document_ocr_proposal.py`; protected workflow action resolution; Terraform module and deployment workflow tests | Plan-only is the default. The runner derives the action from exact outbox records, and provider and resource state are preserved unless one policy-bound OCR action changes them. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-09-05 | implemented | Split the governed format policy from the legacy ingestion owner without changing runtime behavior. | `current change`; focused Python document and deployment checks passed 206 cases; focused Console tests passed 8 cases; Console typecheck passed. | Retain governed runtime evidence for OCR-enabled image intake and warning states. |
| 2026-09-04 | implemented | Added local Korean OCR, revisioned provider controls, durable protected-plan requests, exact outbox-to-workflow binding, Terraform-owned private Document Intelligence, and explicit retain/provision/deprovision actions. | `current change`; 195 focused Python tests, 2327 Console tests, 11 Terraform tests, Console production build, and containerized Korean PNG/TIFF/PDF OCR smoke passed. | Retain authenticated deployed plan, apply, projection-readback, and end-to-end document receipts. |

### Remaining work

- [ ] Retain an authenticated runtime receipt proving supported image intake, OCR-unavailable
  rejection, and `ready_with_warnings` behavior against the advertised capability set.
- [ ] Run one protected `use_azure_provision` plan and approved apply, then retain the exact plan,
  apply, private-endpoint readiness, managed-identity OCR, and Settings projection readback receipts.
- [ ] Run `use_local_retain` and `deprovision_use_local` in separate protected plans, then retain
  evidence that local OCR becomes effective before Azure resource removal.
