---
title: Live and Audit Presentation Implementation
---
# Live and Audit Presentation Implementation

This ledger records the focused [presentation contract](../../roadmap/interfaces/live-audit-presentation.md).
Local browser evidence is separate from protected source delivery and deployment.

## Implementation status

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| Live progress, states, layout, and fullscreen | validated | `live-card-parity.spec.ts` 5 passed on standard 5273; focused Live/Tooltip tests and typecheck | Native and expanded views preserve details, tooltips, Escape and focus. Source cards do not fabricate progress. |
| Repeatable Sample stories | implemented | `operations.sample.test.ts`; declared resource/action checks; Sample replay browser case | Twelve initial stories and tier-specific stage timing remain synthetic-only. |
| Audit bounded record review | validated | `audit-workspace.spec.ts` 8 passed; authenticated 25-record inspection and paired geometry | 1232 x 620 desktop workspace, all 50 fixture rows retained, keyboard selection and bounded scroll verified. |
| Audit authoritative summary and record context | implemented | `test_operator_service_postgres.py` focused audit checks; `api.test.ts`; `audit.model.test.ts`; `audit-workspace.spec.ts` | The Operator API computes complete retained-query counts, retained startup chain evidence, current hash-link gaps, and kind-aware context. Synthetic browser evidence and a read-only local ledger projection do not replace exact-revision authenticated rendering. |
| Responsive and visual comparison | validated | Paired masked desktop captures and authenticated/Sample 993/390/320 English/Korean checks | Shared navigation and truthful data text can differ from the synthetic specimen. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-09-16 | implemented | Replaced unconditional Audit summary placeholders with server-owned counts and integrity observations, normalized retained source-observation and nested action records, and made non-action fields explicitly inapplicable. | `current change`; 20 focused Python cases, 22 Console tests, Console typecheck, strict mypy on 5 source files, and 9 desktop-first browser scenarios passed. | Retain authenticated standard-port evidence from the exact delivered revision; governed deployment evidence remains separate. |
| 2026-09-15 | validated | Completed the eight bounded Live/Audit UI refinements without changing the static mocks or operational authority. | Current change; focused unit/type checks, 5 Live and 8 Audit browser scenarios, paired local screenshots and measured geometry. | Protected delivery and deployed-revision evidence remain separate. |

### Remaining work

- [x] Complete card progress/state coverage, KPI/header alignment, fullscreen, repeatable Sample,
  Audit width/context/query alignment, and non-truncating record review using the checks above.
- [ ] Retain an authenticated standard-port rendering of the authoritative summary and
  source-observation context from the exact delivered revision.
- [ ] Retain equivalent exact-revision evidence in the governed deployment environment.
