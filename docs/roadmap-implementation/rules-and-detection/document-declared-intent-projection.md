# Approved Document Intent Projection implementation ledger

This ledger separates the bounded private Core SDK path from full G02 upload and ordinary
product-query integration.

## Implementation status

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| Private governed-envelope approval and projection | implemented | Current change; `runtime/document_intent.py`, owned handler, PostgreSQL adapters and Core migration; `test_document_intent_postgres.py` | Explicit typed JSON BusinessService add/update only. Exact Var approval, Saga audit, atomic CAS, independent readback and recovery are connected without common observation writes. |
| Current source-aware private graph read | implemented | `postgres_document_intent_reader.py`; actual service-role PostgreSQL tests | Current directory role and source ACL are checked before/after reads. No Owner bypass or retained-result fallback. |
| Ingestion API/worker and protected review UI | not-started | #2256 G02; #2268 | Command input is a governed normalized envelope, not an uploaded raw file. |
| Common graph/query manifest and cache join | not-started | [Owning boundary](../../roadmap/rules-and-detection/document-declared-intent-projection.md#current-authorized-queries-and-remaining-integration) | Private rows never enter common graph or ordinary answers. Full G02 remains open. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-10-19 | implemented | Added the private intent namespace, exact-diff authorization, owned pub/sub, atomic source/approval/release/revision checks, immutable event outbox, independent readback and Vidar rollback. | Current change; actual PostgreSQL flow and framework layout: 28 passed; strict mypy: six new source files passed. Provider and directory inputs are synthetic, not operational qualification. | Final scoped criticism/static/translation checks and local checkpoint; upload/UI, generic query/cache join, and operational qualification remain separate. |

### Remaining work

- [ ] Connect actual Ingestion API/worker completion to the authenticated command boundary and
  retain raw-upload-to-private-query evidence.
- [ ] Add protected exact-diff review UI without disclosing source properties on general topics.
- [ ] Adjudicate common graph/query-manifest exposure and current source-aware cached-result
  admission before private rows can enter ordinary conversation or Console results.
- [ ] Retain target-specific deployment and operational evidence separately; local tests do not
  establish live corpus, model/provider effects, elapsed observation, or promotion.
