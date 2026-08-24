# Busy Conversation Input Modes implementation ledger

This delivery ledger preserves reviewable implementation scope, append-only transitions,
and resumable work while the roadmap owner remains focused on normative design.

## Implementation status

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| Core contracts and deterministic arbitration | implemented | `services/core-control-plane/src/fdai/core/conversation/busy_input.py`; `services/core-control-plane/tests/conversation/test_busy_input.py` | The bounded records, modes, dispositions, idempotency rules, overflow behavior, and turn-finish fallback have focused unit coverage. |
| In-memory store and coordinator | implemented | `services/core-control-plane/src/fdai/core/conversation/busy_input_store.py`; `services/core-control-plane/src/fdai/core/conversation/busy_input_coordinator.py`; `services/core-control-plane/tests/conversation/test_busy_input_store.py` | The protocol reference store, revision checks, exactly-once consumption, cancellation signal, and steer boundary are implemented for process-local composition. |
| PostgreSQL durability and concurrency | implemented | `alembic/versions/20260720_0041_busy_input.py`; `services/core-control-plane/src/fdai/delivery/persistence/postgres_busy_input.py`; focused live PostgreSQL tests (`7 passed`, no skips) | An isolated supported local database proves durable mode and active-turn state, idempotent submission, revision conflicts, exactly-once consume, expiry, restart reads, and concurrent turn-finish arbitration. Governed operational evidence remains separate. |
| Slack and Teams channel gateway | implemented | `services/core-control-plane/src/fdai/core/conversation/channel_gateway.py`; `services/core-control-plane/tests/conversation/test_channel_gateway.py` | Both channel adapters share coordinator submission and begin/finish semantics with bounded acknowledgements. |
| JSON and SSE active-turn integration | not-started | `services/core-control-plane/src/fdai/core/conversation/busy_input_coordinator.py` | Production use of the coordinator is currently limited to the channel gateway; the one-shot and stream turn executors do not consume its cancel or steer signals. |
| Operator API routes and materialization | in-progress | `services/operator-service/src/fdai_operator_service/families/conversation/manifest.py`; `services/operator-service/src/fdai_operator_service/families/conversation/factory.py`; `services/operator-service/tests/test_operator_conversation_family.py` | The generic read and proposal routes exist, but no production busy-input proposal consumer or authoritative projection materializer was found. |
| FDAI Console and client controls | not-started | `console/src` | No source client currently submits, inspects, changes mode, or cancels through the busy-input routes. |
| Metrics and operational evidence | in-progress | `services/core-control-plane/src/fdai/core/conversation/busy_input_coordinator.py` | Counter names and increment calls exist, but no production telemetry binding or governed runtime evidence proves emission, restart recovery, or race behavior. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-08-13 | in-progress | Adopted the implementation ledger; earlier provenance was not reconstructed. | Current change in this owner pair; focused core, channel, persistence, and Operator API checks listed in the scope table. | Connect the web turn executors, materialize the API boundary, add client controls, run live durability checks, and record governed operational evidence. |
| 2026-08-14 | implemented | Ran every focused busy-input persistence case against an isolated supported local PostgreSQL database and removed the database after the run. | `current change`; `services/core-control-plane/tests/persistence/test_busy_input.py`; `7 passed`, no skips. | Connect JSON and SSE turns, materialize Operator operations, add Console controls, and retain governed telemetry and runtime evidence. |

### Remaining work

- [x] Run every live case in `services/core-control-plane/tests/persistence/test_busy_input.py` against the supported local PostgreSQL service and record a passing durability and concurrency receipt with no skipped cases.
- [ ] Connect the JSON and SSE active-turn executors to `BusyInputCoordinator`, then add focused tests proving interrupt cleanup, bounded steer reruns, queue fallback, and no partial assistant history.
- [ ] Add a production consumer and authoritative projection materializer for the four Operator API operations, then prove principal scope, idempotency, revision conflicts, and not-found equivalence with focused route tests.
- [ ] Add FDAI Console client controls for submit, inspect, mode change, and conversational cancellation, with focused interaction and accessibility checks.
- [ ] Bind the coordinator counters to production telemetry and record governed restart, expiry, race-recovery, and channel parity evidence before promoting any row to `validated`.
