# Operator Console - Narrator, DI Seams, and Session Model implementation ledger

This delivery ledger preserves reviewable implementation scope, append-only transitions,
and resumable work while the roadmap owner remains focused on normative design.

## Implementation status

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| Core narrator, answer-plan, and session contracts | implemented | `services/core-control-plane/src/fdai/core/conversation/`; focused conversation tests | Deterministic planning, narration boundaries, session records, and no-execution authority have focused coverage. |
| Working-context assembly and policy | implemented | `services/core-control-plane/src/fdai/core/working_context/`; `services/core-control-plane/tests/core/working_context/`; context-bridge tests | Budget tiers, validation, summarization planning, replay, governance, shadow comparison, and typed-fact trust boundaries are implemented. |
| Durable principal-scoped history and complete-history assembly | implemented | Conversation history providers; `services/core-control-plane/tests/persistence/test_postgres_user_context_latest.py`; `services/core-control-plane/tests/persistence/test_postgres_conversation_history_restart.py`; `services/core-control-plane/tests/persistence/test_postgres_conversation_images.py`; `services/core-control-plane/tests/persistence/test_conversation_search.py`; Operator conversation application | Restart reads, principal isolation, complete turn history, latest context, first questions, images, search, and working-context manifest assembly pass focused PostgreSQL tests. A governed long-session receipt remains open. |
| Independent-service narrator and model bindings | in-progress | `services/operator-service/src/fdai_operator_service/application/conversation/`; service-local narrator adapter; focused Operator tests | The application and adapter seams exist, but rolling latency routing, per-user pinning, and complete production projection/stream evidence remain open. |
| Cross-process agent introspection | implemented | `services/core-control-plane/src/fdai/delivery/agent_introspection_bus.py`; focused introspection and conversation tests | Bounded request/reply transport preserves Bragi's presentation-only authority and excludes executor identity. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-08-14 | in-progress | Adopted the implementation ledger; earlier provenance was not reconstructed. | `current change`; current conversation, working-context, history, Operator application, and introspection evidence listed in the scope table. | Close durable restart, independent narrator routing, and authenticated long-session evidence. |
| 2026-08-14 | implemented | Added live restart and principal-isolation coverage, then promoted durable history and complete-history assembly. | `current change`; the history/latest-context, image, and search suites passed 12 cases with zero skips against a disposable supported PostgreSQL database. | Close independent narrator routing and authenticated long-session evidence. |
| 2026-08-14 | implemented | Added a dedicated restart check that rebuilds the complete principal-scoped turn sequence into a working-context manifest without borrowing another principal's history. | `current change`; `test_postgres_conversation_history_restart.py` passed its focused live case with no skips; focused Ruff and mypy passed. | Retain governed long-session and authenticated JSON/SSE evidence. |

### Remaining work

- [x] Run principal-scoped PostgreSQL conversation history, image, latest-context, and search cases with no skips and retain restart evidence for complete-history assembly.
- [ ] Retain a governed long-session receipt proving bounded prompt assembly, newest-turn preservation, typed-fact trust, blocked-content omission, timeout degradation, and deterministic replay.
- [ ] Complete the independent-service rolling narrator and TTFT routing plus per-user preference projection tracked in Narrator Routing and Latency.
- [ ] Retain authenticated JSON and SSE receipts that bind one request, history revision, working-context manifest, model route, verification result, terminal answer, and durable turn.
