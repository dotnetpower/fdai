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
media-type hint select an eligible parser only. Production advertises image sources only when OCR
is configured.

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

Embedded images use bounded package-member extraction and the configured OCR provider. A modern
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
