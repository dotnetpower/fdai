# Access-Scoped Conversation Search implementation ledger

This delivery ledger preserves reviewable implementation scope, append-only transitions,
and resumable work while the roadmap owner remains focused on normative design.

## Implementation status

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| Bounded query contracts and Unicode matching | implemented | `services/core-control-plane/src/fdai/shared/providers/conversation_search.py`; `services/core-control-plane/src/fdai/shared/providers/conversation_search_text.py`; `services/core-control-plane/tests/providers/test_conversation_search.py` | The shared contracts enforce query, result, context, snippet, and measurement bounds. Focused provider tests cover English, Korean, phrase, prefix, and metadata matching. |
| Principal-scoped in-memory search, context, lineage, measurements, and deletion | implemented | `services/core-control-plane/src/fdai/shared/providers/testing/conversation_search.py`; `services/core-control-plane/tests/providers/test_conversation_search.py` | Focused tests exercise principal and allowlist isolation before measurements, authorized neighbors and lineage, deterministic corpus caps, and deletion visibility. |
| PostgreSQL projection, indexing, retention, and rebuild | implemented | `alembic/versions/20260720_0038_conversation_search.py`; `services/core-control-plane/src/fdai/delivery/persistence/postgres_conversation_search.py`; `services/core-control-plane/src/fdai/delivery/conversation_search_rebuild_cli.py`; focused CLI and live PostgreSQL tests (`10 passed`, no skips) | The migration, adapter, and headless rebuild entry point preserve the source turns while rebuilding the derived index under the configured session statement timeout. Governed restart evidence remains open. |
| Reader-floor narrator search tool | implemented | `services/core-control-plane/src/fdai/core/conversation/_system_conversation_search_tool.py`; `services/core-control-plane/tests/conversation/test_search_conversations_tool.py` | Focused tests prove principal-scoped results, bounded validation errors, evidence references, and explicit `trusted: false` output for a Reader principal. |
| Operator API search, context, and lineage routes | implemented | `services/operator-service/src/fdai_operator_service/families/conversation/conversation_search.py`; `services/operator-service/src/fdai_operator_service/postgres_family_store.py`; `service-migrations/branches/operator-service/versions/20260814_operator_conversation_search_read.py`; focused API and live PostgreSQL tests (`11 passed`, no skips) | The Operator resolves the authenticated principal, validates bounded filters, reads the source tables through its SELECT-only role, returns identical missing and out-of-scope 404 envelopes, and omits internal query duration. |
| Console search and context panel | implemented | `console/src/routes/conversation-search.tsx`; `console/src/routes/conversation-search.model.ts`; `console/src/routes/conversation-search.test.ts`; `console/src/routes/conversation-search.test.tsx`; `console/src/user-context-client.test.ts`; focused route, model, and decoder tests plus Console typecheck | The panel compiles bounded filters, renders safe text segments, rejects malformed highlights, distinguishes empty and unavailable states, and prevents stale or duplicate context requests from replacing current results. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-08-13 | in-progress | Adopted the implementation ledger without reconstructing earlier provenance. | `current change`; core provider and narrator checks passed 6 cases; the Operator conversation-family check passed 7 cases; Console decoder and panel checks passed 19 cases; PostgreSQL checks passed 1 non-live case and skipped 2 live cases because `FDAI_DATABASE_URL` was unset. | Complete the PostgreSQL, Operator API, Console, and governed runtime evidence below. |
| 2026-08-14 | implemented | Added the headless conversation-search projection rebuild command with bounded JSON metrics and fail-closed configuration and error handling, then exercised the complete PostgreSQL search suite against the supported local database. | `current change`; `services/core-control-plane/src/fdai/delivery/conversation_search_rebuild_cli.py`; `services/core-control-plane/tests/delivery/test_conversation_search_rebuild_cli.py`; CLI tests `6 passed`; live PostgreSQL tests `3 passed`, no skips. | Materialize the Operator projections, close the Console route coverage, and retain governed runtime evidence. |
| 2026-08-14 | implemented | Applied the configured statement timeout to the autocommit rebuild session before concurrent reindex so a blocked rebuild cannot wait without the server-owned bound. | `current change`; PostgreSQL search adapter and focused timeout-order plus live PostgreSQL tests `4 passed`, no skips. | Operator and Console projection work plus governed runtime evidence remain open. |
| 2026-08-14 | implemented | Materialized search, context, and lineage behind the Operator API with authenticated principal scoping, bounded wire projections, SELECT-only database access, and timing omission. | `current change`; Operator materializer, family adapter, PostgreSQL store, service-owned grant migration, focused API tests `10 passed`, and restricted-role live PostgreSQL test `1 passed`, no skips. | Add the focused Console interaction suite and retain governed cross-surface runtime evidence. |
| 2026-08-14 | implemented | Added a focused Console route model and interaction suite for filter compilation, safe highlights, exact context toggling, empty and unavailable states, and decoder failure without synthesized content. | `current change`; Conversation Search route, route model, focused tests `5 passed`, and Console typecheck. | Retain one governed PostgreSQL-to-Operator-to-Console-to-narrator runtime receipt. |
| 2026-08-14 | implemented | Bound the Console route to directly tested filter, highlight, context, and optional-source decisions. | `current change`; focused route and decoder tests passed 22 cases, Console typecheck passed, and catalog parity passed. | Materialize the Operator projections and retain governed runtime evidence. |
| 2026-08-14 | implemented | Prevented stale search generations and duplicate same-generation context requests from overwriting or amplifying Console state. | `current change`; focused route and decoder tests passed 22 cases, Console typecheck passed, and catalog parity passed. | Materialize the Operator projections and retain governed runtime evidence. |

### Remaining work

- [x] Record a passing live PostgreSQL focused check for migration, principal isolation, bilingual
  search, context, lineage, retention deletion, and concurrent rebuild with
  `FDAI_DATABASE_URL` configured.
- [x] Add the documented `fdai.delivery.conversation_search_rebuild_cli` headless entry point and
  focused success and failure-preservation checks.
- [x] Materialize the three search projections behind the Operator API and add focused API tests
  that prove server-resolved scope, indistinguishable out-of-scope 404 responses, bounded payloads,
  and omission of internal query duration.
- [x] Add a focused Console route test that covers form filters, safe highlights, context loading,
  empty and unavailable results, and decoder failure without synthesized content.
- [ ] Record governed runtime evidence for the PostgreSQL, Operator API, Console, and narrator paths
  before promoting any scope row to `validated`.
