---
title: Governed Document Format Policy
---
# Governed Document Format Policy

This document defines which source formats FDAI accepts for governed document ingestion and how
the worker verifies, extracts, and reports them. It separates client guidance from authoritative
server-side content validation.

> This policy grants no trust or execution authority from a filename, extension, or browser media
> type. The worker verifies the actual byte signature before extraction.

## Design at a glance

The capability endpoint and upload boundary consume one shared allowlist. A filename extension and
media-type hint select an eligible parser only. Production advertises image sources only when an
optical character recognition (OCR) provider is ready.

## OCR provider control

Local Python OCR is the default provider. You can select Azure Document Intelligence from
**Settings > Integrations > Document OCR**. Saving a selection writes a revision-fenced policy and
a protected plan request. It doesn't run Terraform or grant apply authority.

The policy separates the active provider from the Azure resource lifecycle:

| Operator intent | Runtime provider | Azure resource |
|-----------------|------------------|----------------|
| Keep the current state | Preserve the last applied provider | Preserve the current resource state |
| Use local OCR | `local_python` | Retain an existing resource |
| Use Azure OCR | `azure_document_intelligence` | Provision or retain the resource |
| Remove Azure OCR | `local_python` | Plan explicit deprovisioning |

The Settings projection reports the effective provider only after deployment readback. A requested
provider doesn't become effective because a policy was saved or a plan was accepted.

## Local Korean OCR

The local provider uses Tesseract with pinned `kor+eng` language data. Rasterization and OCR run in
a spawned process with CPU, memory, elapsed-time, page-count, pixel-count, line-count, character,
and inter-process output limits. PDF pages are rasterized with `pypdfium2`; PNG, JPEG, and TIFF
frames use Pillow. Runtime language downloads aren't supported.

Provider readiness checks require both Korean and English language data. Missing data, parser
errors, timeouts, and output-bound violations produce an unavailable provider result without
placing document text in logs.

## Azure Document Intelligence lifecycle

Azure mode uses the `prebuilt-read` model through managed identity. The protected Terraform
workflow can provision a `FormRecognizer` account with local authentication disabled, diagnostics,
a private endpoint, and private DNS. The ingestion worker receives `Cognitive Services User` on
the selected resource.

The workflow is plan-only by default. The `document_ocr_action` input binds one of four explicit
operations to the protected deployment request: `preserve`, `use_local_retain`,
`use_azure_provision`, or `deprovision_use_local`. An apply still requires an exact protected plan
and separate approval. Later deployments preserve the previously applied resource and provider
unless an OCR action explicitly changes them.

For a Settings-originated request, the protected runner resolves `plan-ocr-<proposal>-<digest>`
coordinates against the authoritative PostgreSQL proposal outbox, which is the durable request
queue. It accepts the action only when the
proposal, current policy, plan-request state, environment, principal, idempotency key, and digest
agree. The runner then derives the Terraform action from the policy instead of trusting a
workflow-supplied provider value.

## Intake and processing matrix

| Source | Intake | Processing |
|--------|--------|------------|
| UTF-8 text, Markdown, RST, JSON, YAML, XML, CSV, Terraform, Rego | Accepted | Decode as bounded text with paragraph locators |
| PDF | Accepted | Parse native text in an isolated process; use OCR for blank or scanned pages |
| DOCX | Accepted | Extract paragraphs, headings, tables, and embedded raster images |
| PPTX | Accepted | Extract slide shapes, paragraphs, tables, notes, and embedded raster images |
| XLSX | Accepted | Extract sheet labels, cells, shared strings, and embedded raster images; never execute formulas |
| PNG, JPEG, TIFF | Accepted when OCR is configured | Require OCR; don't place image bytes in the index or audit |
| DOC, PPT, XLS, and other OLE binaries | Not accepted | Save a modern OOXML or PDF version in the source application |
| ZIP and other generic archives | Not accepted | Archive expansion isn't an upload format |

## Extraction and failure behavior

Embedded images use bounded package-member extraction and the effective OCR provider. A modern
Office document with usable native text can finish as `ready_with_warnings` when embedded-image OCR
is unavailable. An image-only document, scanned PDF, or image-only Office package cannot become
ready without cited OCR text. Empty extraction is a typed failure, not a searchable zero-content
document.

Malformed packages, extension/signature mismatches, encrypted files, unsupported image encodings,
and parser-budget violations produce distinct sanitized failure codes. FDAI doesn't attempt a
best-effort legacy conversion, execute a formula or macro, follow an external relationship, or
silently treat a binary file as text.

## Related docs

| To learn about | Read |
|----------------|------|
| End-to-end ingestion lifecycle | [Document ingestion](document-ingestion.md) |
| Agent processing ownership | [Document ingestion agent ownership](document-ingestion-agent-ownership.md) |
| Delivery status and remaining work | [Implementation ledger](../../roadmap-implementation/interfaces/document-ingestion-format-policy.md) |
