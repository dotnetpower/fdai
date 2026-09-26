# Scheduled Result Continuations implementation ledger

This delivery ledger preserves reviewable implementation scope, append-only transitions,
and resumable work while the roadmap owner remains focused on normative design.

## Implementation status

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| Anchor contracts, authorization, typed-fact projection, and lifecycle | implemented | `services/core-control-plane/src/fdai/shared/providers/scheduled_continuation.py`; `services/core-control-plane/src/fdai/core/scheduler/continuation.py`; `services/core-control-plane/tests/core/scheduler/test_continuation.py` | Focused tests cover owner and scope checks, idempotent creation, expiry, audit, and no instruction authority. |
| PostgreSQL anchor persistence | implemented | `services/core-control-plane/src/fdai/delivery/persistence/postgres_scheduled_continuation.py`; `services/core-control-plane/tests/persistence/test_scheduled_continuation.py` | The adapter accepts the standard SQLAlchemy psycopg DSN. Row codecs, restart reads, idempotent create and audit retry, concurrent compare-and-set expiry, and winner-only expiry audit pass three focused cases, including two live cases with zero skips against a disposable supported PostgreSQL database. |
| Configuration review campaign | implemented | `services/core-control-plane/src/fdai/core/detection/configuration_review.py`; focused configuration-review tests | The bounded three-run reducer, audit/state transitions, resume, blueprint proposal, and materialization guards exist without granting schedule authority. |
| Operator routes and Console projection | in-progress | `services/operator-service/src/fdai_operator_service/families/conversation/manifest.py`; `console/src/routes/scheduled-continuations.tsx`; focused route and Console tests | Read and command surfaces exist, but no governed authenticated end-to-end continuation receipt is retained. |
| Slack and Teams delivery parity | in-progress | [Channel behavior](../../roadmap/interfaces/scheduled-result-continuations.md#channel-behavior) | Contracts and adapters are described; external channel and durable-ledger wiring requires deployment evidence. |
| Legal-hold-aware physical retention | in-progress | `services/core-control-plane/src/fdai/core/scheduler/continuation_retention.py`; `services/core-control-plane/src/fdai/delivery/persistence/postgres_scheduled_continuation_retention.py`; `services/core-control-plane/tests/core/scheduler/test_continuation_retention.py`; `services/core-control-plane/tests/persistence/test_scheduled_continuation_retention.py` | The coordinated worker deletes the projected turn, source result, and anchor in that order after a grace window, refuses an active anchor, fails closed on a legal hold or an unreadable hold registry, keeps a partial failure resumable, and collapses retry audit. A durable deletion fence is recorded before the first deletion and refuses a fenced anchor id at creation and delivery. The production PostgreSQL deleters carry scoped statements and an independent deletion readback; their live cases stay environment-gated and no governed purge receipt is retained. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-08-14 | in-progress | Adopted the implementation ledger; earlier provenance was not reconstructed. | `current change`; anchor, persistence, campaign, route, and Console evidence listed in the scope table. | Close no-skip persistence, authenticated delivery, external channel, and physical retention evidence. |
| 2026-08-14 | implemented | Strengthened the live anchor test and promoted PostgreSQL persistence after proving restart and concurrent expiry behavior. | `current change`; `test_scheduled_continuation.py` passed two cases with zero skips against a migrated disposable supported database. | Close authenticated delivery, external channel, and physical retention evidence. |
| 2026-08-14 | implemented | Normalized the standard psycopg DSN at the adapter boundary and exercised anchor persistence without skips. | `current change`; `test_scheduled_continuation.py` passed 3 cases; focused Ruff and mypy passed. | Retain authenticated delivery, external channel, and physical retention evidence. |
| 2026-08-16 | in-progress | Added the legal-hold-aware retention worker that coordinates ordered deletion, grace, hold, partial-failure, and audit behavior. | `current change`; `pytest services/core-control-plane/tests/core/scheduler/` passed 74 tests including 13 focused retention cases; focused Ruff passed. | Bind production result, projected-turn, and anchor deleters and retain authenticated delivery plus external channel evidence. |
| 2026-09-26 | in-progress | Bound the production PostgreSQL deleters for the projected turn, source briefing run, and anchor row with scoped statements and an independent deletion readback, and added the durable deletion fence that refuses a fenced anchor id at creation and external delivery. | `current change`; [Issue #1025](https://github.com/dotnetpower/fdai/issues/1025); `pytest services/core-control-plane/tests/core/scheduler services/core-control-plane/tests/persistence/test_scheduled_continuation.py services/core-control-plane/tests/persistence/test_scheduled_continuation_retention.py` passed 104 cases with 3 environment-gated skips; focused Ruff and strict mypy passed. | Run the environment-gated live deleter cases and retain one governed purge receipt, plus authenticated delivery and external channel evidence. |
| 2026-09-27 | in-progress | Exposed `PostgresScheduledContinuationDeleter` and `RetentionReadbackError` through the delivery persistence package, refused an unsupported retention target instead of planning no statement, and proved that a durable-fence retry resumes a partial purge while the fence stays recorded exactly once. | `current change`; [Issue #1025](https://github.com/dotnetpower/fdai/issues/1025); `pytest services/core-control-plane/tests/core/scheduler services/core-control-plane/tests/persistence/test_scheduled_continuation.py services/core-control-plane/tests/persistence/test_scheduled_continuation_retention.py` passed 110 cases with 3 environment-gated skips, which corrects the count recorded on 2026-09-26; focused Ruff and strict mypy passed. | Run the environment-gated live deleter cases and retain one governed purge receipt, plus authenticated delivery and external channel evidence. |

### Remaining work

- [x] Run PostgreSQL anchor cases against the supported local database with no skips and retain restart, concurrent expiry, winner-only audit, and idempotent retry evidence.
- [ ] Retain one authenticated web continuation receipt from scheduled result through anchor open, typed fact, follow-up answer, expiry, and unavailable replay.
- [ ] Retain Slack and Teams origin-thread, dedicated-thread, degradation, ambiguous acknowledgement, and durable retry receipts without widening the audience.
- [x] Implement a legal-hold-aware retention worker that coordinates source result, anchor, projected turn, audit, retry, and partial-failure behavior before presenting expiry as physical deletion.
- [x] Bind production deleters for the stored result, the projected conversation turn, and the
    PostgreSQL anchor row with scoped statements, a durable deletion fence, and an independent
    deletion readback that keeps a surviving copy pending.
- [ ] Run the environment-gated live deleter cases against the supported local database and retain
    one governed purge receipt before presenting expiry as completed physical deletion.
- [ ] Keep the fence keyed to the current anchor id derivation. A change to that derivation moves
    the fence key, so it needs a migration that carries forward existing tombstones before any
    recreated id can be accepted.
