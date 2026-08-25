---
title: Durable Background Task Sessions
---

# Durable Background Task Sessions

This design defines durable, detached read-only investigations started from an operator
conversation. It covers task and attempt state, leases, progress, cancellation, restart behavior,
conversation handoff, user delivery boundaries, and operator visibility.

> **Scope:** Background tasks do not execute cloud changes. Mutation requests continue through the
> typed control loop, safety checks, human approval, Thor execution, rollback, and Saga audit.

## Design at a glance

A Contributor creates a bounded task record and receives `202` without waiting for execution. A
coordinator claims the queued attempt with a lease, runs the isolated typed read service, and stores
the terminal result together with a pending completion in one transaction. A separately leased
completion outbox appends the provenance-labeled conversation turn and enqueues the immutable reply
through the durable conversation delivery ledger.

![Design at a glance. The main stages are Operator conversation, Durable queued task, CAS lease claim, Read-only executor, Coalesced progress, Atomic terminal result and pending completion, Leased completion outbox, Idempotent conversation turn, Durable reply ledger.](../../diagrams/generated/fdai-roadmap-interfaces-background-task-sessions-01.en.svg)

## Contracts and state

`BackgroundTask` stores the owner principal, origin conversation and channel, read-only kind,
bounded prompt, context digest, capability profile, budgets, correlation ID, idempotency key,
creation time, and retention deadline. The only initial profile is `background.read-only`.
New tasks also record Heimdall as the accountable agent for the read investigation. The mechanical
`background-task-coordinator` remains a separate execution worker, and legacy records keep a null
agent attribution instead of receiving an inferred owner.

`BackgroundTaskAttempt` separates execution history from the task definition. Its state is:

```text
queued -> claimed -> running -> succeeded | failed | cancelled | timed_out | unknown
```

Queued attempts have no lease or result. Claimed and running attempts have a lease and no result.
Terminal attempts have an immutable result and no lease. Constructor and database constraints
apply the same rule.

Each terminal attempt has one completion outbox row with this state machine:

```text
pending -> sending -> delivered
                   -> failed -> sending
                   -> abandoned
```

Only `sending` carries a lease. A claim increments the delivery attempt count, which is bounded at
eight. `delivered` and `abandoned` are terminal completion states.

## Claims, leases, and restart behavior

PostgreSQL claims one queued row with `FOR UPDATE SKIP LOCKED`. Start, renew, and completion require
the expected revision, lease token, nonexpired lease, and allowed prior state in one conditional
update. Two coordinators cannot own the same attempt.

The coordinator renews its lease while the executor is active. An expired claimed or running
attempt becomes `unknown(process_lost)` through a bounded reconciliation query. It is not returned
to queued and is not automatically retried. A future retry creates a linked attempt only for an
explicitly retryable task kind or an operator-confirmed action.

## Execution and isolation

The target executor runs the typed read-investigation service with:

- A server-owned scope, exact resource resolution, and the seven registered read tools.
- No narrator backend, parent screen state, transcript, hidden reasoning, mutable memory, event bus,
  Thor, or executor identity.
- A normalized evidence result and bounded semantic progress instead of raw provider output.

The coordinator bounds concurrency, wall time, token, cost, tool-call, progress, and lease usage.
Timeout, cancellation, and executor error each produce a distinct terminal reason.
Daily cost windows use the store's UTC clock rather than a task-provided timestamp. When quota is
enabled, a creation timestamp more than 300 seconds from server time is rejected before insertion,
so a caller cannot select another quota day by backdating or future-dating a task.

## Progress and backpressure

Progress is structured as kind, bounded message, timestamp, and usage. The reporter emits at most
one event per configured interval and coalesces newer updates within that interval. The store
applies a per-task event cap and monotonic sequence. It never stores arbitrary command logs in the
conversation record.

The target Operator API lets authenticated operators read progress through GET or a server-sent
events (SSE) stream. The stream emits stored progress, bounded heartbeats while running, and one
terminal event before it closes. Cross-owner tasks use the same 404 response as missing tasks.

## Commands and authorization

The independent Operator Service always builds these routes from its frozen conversation-family
manifest. Each route authorizes the caller and delegates to an injected projection reader, proposal
outbox, or event stream; a missing dependency fails closed with `503`. The current PostgreSQL
conversation adapter handles these operations as generic shadow proposals, projection reads, and
audit replay. It does not yet materialize `BackgroundTask` records or owner-scoped task views.

The target background-task materializers enforce these operation-specific contracts:

- `POST /background-tasks` requires the Contributor `start-read-investigation` capability and returns
  immediately.
- `GET /background-tasks` and `GET /background-tasks/{task_id}` are owner-scoped.
- `GET /background-tasks/{task_id}/progress` and `/progress/stream` are owner-scoped.
- `POST /background-tasks/{task_id}/cancel` requires the owner or an FDAI Owner.

Create and cancel are audited through the existing hash-chained state-store audit boundary. Request
bodies and budgets are bounded. Idempotency is scoped by owner and key.

## Completion outbox and retries

The terminal attempt update and `pending` completion insertion commit in one PostgreSQL transaction.
The coordinator claims due `pending` or `failed` completions with `FOR UPDATE SKIP LOCKED`, changes
the row to `sending`, and requires the lease token for the final compare-and-set update. The sink
publish timeout is bounded by the completion lease.

A sink failure changes only the completion row. It never rewrites the result or reruns task
execution. Retry uses bounded exponential backoff, and the coordinator schedules its nearest due
completion retry in process. It does not wait for an external wake signal or a newly created task.
After eight attempts, or when the next retry reaches retention, the completion becomes `abandoned`.
When no sink is configured, reconciliation also closes a still-pending completion as
`abandoned(retention_expired)` at retention. The terminal transition records one bounded delivery
attempt for schema parity and allows the existing purge to remove the task without rerunning it.

If a process loses a `sending` lease, reconciliation changes the row to due `failed`, or to
`abandoned` when the attempt or retention bound is exhausted. A later coordinator can claim the
reconciled row without replaying the investigation.

## Completion ordering and replay

The completion audit, history turn, and outbound-enqueue audit sequence is designed to be safe to
replay. The target sink writes
`background-task.completed` and `background-task.delivery-enqueued` audit events through durable
state markers that commit the marker and audit entry atomically. A deterministic marker per
attempt and action keeps those audit events single-write across sink retries.

The conversation turn keeps deterministic turn and idempotency IDs, a
`[Background task result: ...]` label, correlation metadata, and `trusted=false`. The outbound
submit reuses the stable attempt origin, so the durable reply ledger also deduplicates replay.
Provider delivery remains a separate claim/lease/ack concern and does not claim exactly-once
delivery from external chat providers.

## Operations and retention

List and detail projections expose status, budget, lease expiry, usage, progress, duration inputs,
and terminal reason. The response contract also supports a request summary of up to 500 characters,
a result summary of up to 2,000 characters, up to 16 evidence references, truncation flags, nullable
accountable-agent attribution, and the separate execution-worker label. The current PostgreSQL
reader does not yet populate those narrative and attribution fields, so the Console renders them as
unavailable rather than inferring values. The projections omit broad context and do not expose
another principal's task count.
Retention purge selects a row only when the task attempt is terminal, the task retention deadline
has elapsed, and completion is `delivered` or `abandoned`. Deleting the attempt cascades its
progress and completion outbox rows. A pending, sending, or retryable failed completion therefore
keeps the task history available for recovery.

The coordinator drains active work for a bounded shutdown interval. Remaining work is cancelled in
process and becomes `unknown` when its lease expires after process loss.

A request-created attempt starts behind a creation-audit claim fence. The task store does not make
that attempt claimable until an idempotent StateStore marker and its audit entry are committed and
the service records the marker on the attempt. Redelivery reuses the same marker and only repairs
the claim fence. An audit or marker failure therefore leaves durable work unclaimable instead of
allowing an unaudited provider read.

## Verification

Focused core tests cover contract bounds, mutation-profile denial, concurrent claims, stale revision
and lease rejection, terminal immutability, owner and admin cancellation, progress sequence and cap,
coalescing, bounded concurrency, timeout, shutdown, task and completion process-loss reconciliation,
atomic terminal-plus-outbox commit, eight-attempt delivery bounds, self-scheduled retry, retention
purge predicates, and replay-idempotent conversation handoff. The PostgreSQL suite covers migration,
claims, quotas, restart reads, reconciliation, retry, and purge against a supported local service.

Operator-family tests cover the frozen routes, authorization envelopes, bounded bodies, cancellation
proposal classification, background-task list, detail, progress, finite SSE replay, cross-owner 404
equivalence, and fail-closed `503` behavior. Focused cross-process tests now prove request and
cancellation publication, Core persistence-before-wake, typed detached execution, and cancellation.
Governed restart and deployed delivery evidence remain part of the production verification work.

## Implementation status

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| Core records, quota, store, and coordinator logic | implemented | `services/core-control-plane/src/fdai/core/background_task/`; `services/core-control-plane/tests/core/background_task/` | The bounded records, state transitions, quota decisions, in-memory store, lease coordinator, retry scheduling, cancellation, and shutdown behavior have focused unit coverage. New tasks persist Heimdall accountability; legacy records may keep null attribution. |
| PostgreSQL task and completion persistence | implemented | `alembic/versions/20260720_0040_background_task.py`; `alembic/versions/20260722_0051_background_task_completion.py`; `service-migrations/branches/core-control-plane/versions/20260826_core_background_task_runtime_grants.py`; `services/core-control-plane/src/fdai/delivery/persistence/postgres_background_task.py`; `services/core-control-plane/src/fdai/delivery/persistence/postgres_background_task_completion.py`; focused live PostgreSQL tests (`12 passed`, no skips) | An isolated supported local database proves atomic claims, leases, quotas, progress, completion outbox, reconciliation, retries, restart reads, and retention purge behavior. The Core migration grants its runtime role only the operations each coordinator-owned table requires. Governed runtime evidence remains separate. |
| Production executor and coordinator composition | implemented | `services/core-control-plane/src/fdai/core/background_task/read_investigation_executor.py`; `services/core-control-plane/src/fdai/runtime/read_investigation_runtime.py`; focused executor, consumer, runtime, coordinator, and PostgreSQL tests | The optional Core binding constructs the typed executor, durable store, supervised coordinator, request consumer, reconciliation loop, quotas, cancellation, and bounded shutdown without creating another service or granting effect authority. |
| Completion sink and durable conversation handoff | in-progress | `services/core-control-plane/src/fdai/core/background_task/completion_sink.py`; `services/core-control-plane/src/fdai/delivery/persistence/background_task_completion_audit.py`; focused sink and audit tests | `ConversationCompletionSink` appends the deterministic untrusted turn, submits one immutable reply, and brackets handoff with atomic single-write completion markers. Replay reuses the same turn, delivery record, marker, and audit entry. Production composition still constructs none of these components. |
| Operator API routes, projections, and progress stream | implemented | `services/operator-service/src/fdai_operator_service/families/conversation/background_tasks.py`; `services/operator-service/src/fdai_operator_service/postgres_family_store.py`; `service-migrations/branches/operator-service/versions/20260823_operator_background_task_read.py`; focused projection, PostgreSQL, and family tests | Owner-filtered SQL materializes bounded list, detail, progress, and finite SSE replay with cross-owner 404 equivalence. It populates bounded request and result summaries, up to 16 evidence references, truncation flags, and nullable Heimdall accountability. The Operator role receives `SELECT` only. |
| FDAI Console task controls | in-progress | `console/src/routes/background-tasks.tsx`; `console/src/routes/background-tasks.css`; `console/src/routes/background-tasks.model.ts`; `console/src/routes/background-tasks.model.test.ts` | The bilingual read-only route prioritizes requested work, agent accountability, outcome and evidence, and an activity timeline. Technical usage is disclosed separately. Legacy records show explicit unavailable and unattributed states. It deliberately has no create, cancel, retry, or execute control while those API consumers are absent. |
| Audit, telemetry, and operational evidence | in-progress | `services/core-control-plane/src/fdai/core/background_task/service.py`; `services/core-control-plane/src/fdai/delivery/persistence/background_task_lifecycle_audit.py`; `services/core-control-plane/src/fdai/delivery/persistence/background_task_completion_audit.py` | Production creation and cancellation use idempotent StateStore lifecycle markers. Creation remains behind a durable claim fence until its marker commits. Completion marker persistence is also implemented and tested, but no production completion sink, runtime telemetry, restart receipt, or governed delivery evidence exists. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-08-19 | implemented | Removed a wall-clock expiry from the coordinator test fixture. Its fixed 2026-07-20 task retained data for 30 days, so the real clock began purging attempts before persistence and retry assertions on 2026-08-19. The fixture now uses a deterministic nonexpiring horizon without changing production retention behavior. | [Issue #218](https://github.com/dotnetpower/fdai/issues/218); the two failures reproduce on the parent revision and pass after the fixture correction; the focused coordinator file passes 6 cases with Ruff and format checks. | None for the fixture expiry; production composition remains tracked separately below. |
| 2026-08-13 | in-progress | Adopted the implementation ledger; earlier provenance was not reconstructed. | Current change in this owner pair; focused core, PostgreSQL, and Operator API checks listed in the scope table. | Wire the executor, coordinator, completion sink, API materializers, Console controls, live persistence checks, and governed operational evidence. |
| 2026-08-14 | implemented | Ran every focused background-task persistence case against an isolated supported local PostgreSQL database and removed the database after the run. | `current change`; `services/core-control-plane/tests/persistence/test_background_task.py`; `12 passed`, no skips. | Compose the production executor and completion sink, materialize Operator and Console surfaces, and retain governed operational evidence. |
| 2026-08-16 | in-progress | Implemented the completion sink that appends the deterministic conversation turn and submits the immutable reply through the durable delivery ledger. | `pytest services/core-control-plane/tests/core/background_task/` passed 29 focused tests, including replay reuse of one turn and one delivery record, terminal-only publication, untrusted turns, and fail-closed channel handling. | Bind the sink and coordinator in production composition, add completion audit markers, and retain governed delivery receipts. |
| 2026-08-23 | in-progress | Re-audited the detached-task boundary after the independent Operator Service and conversation runtime updates. The route manifest and generic authorization, proposal, and stream envelopes are implemented, but they still do not materialize or execute background tasks, so no scope row was promoted. | `current change`; `uv run pytest -q --no-cov services/core-control-plane/tests/core/background_task services/operator-service/tests/test_operator_conversation_family.py` (`39 passed`); `services/operator-service/src/fdai_operator_service/families/conversation/`; `services/operator-service/src/fdai_operator_service/family_adapters.py`. | Replace generic shadow handling with task-specific adapters, bind the executor and coordinator, add Console controls, and retain governed operational evidence. |
| 2026-08-23 | in-progress | Added atomic completion audit markers, owner-scoped background-task read materializers with least-privilege PostgreSQL access, and a bilingual read-only Console route. Twelve hardening rounds corrected deterministic terminal replay, 256-character identifiers, stale detail responses, safe `503` envelopes, PostgreSQL audit mode, complete 256-event progress replay, and normal state-transition reconciliation. No write or execution authority was added, and only Low residual tradeoffs remain. | `current change`; focused backend slice (`108 passed`), final Operator slice (`21 passed`), Console navigation/model slice (`28 passed`), Ruff, strict mypy, Console typecheck, production build and bundle gate, 18-pair catalog parity, service-migration inventory, and single Operator migration head. An authenticated standard-port local Console read showed four owner-scoped tasks, one selected terminal detail with two progress events and delivered completion, zero document/main/detail horizontal overflow, and 44 px mobile detail commands. | Define and bind the production proposal consumer and detached coordinator transport, then add create/cancel controls and governed deployment evidence. |
| 2026-08-23 | in-progress | Added durable Heimdall accountability for newly created read investigations and redesigned the read-only Console around requested work, accountable agent, outcome, evidence, and activity. The API contract keeps accountable agent and mechanical execution worker separate and leaves legacy attribution null. | `current change`; `services/core-control-plane/src/fdai/core/background_task/`; `services/operator-service/src/fdai_operator_service/families/conversation/background_tasks.py`; `console/src/routes/background-tasks.tsx`; `console/src/routes/background-tasks.css`; focused Operator projection tests (`8 passed`), Console decoder tests (`6 passed`), Ruff, source mypy, Console typecheck, production build, and bundle gate. An authenticated 390 px standard-port view measured zero document/detail/timeline horizontal overflow and 44 px detail commands. | Populate the bounded narrative, evidence, and agent fields in the owner-scoped PostgreSQL reader. Production create/cancel consumers and detached coordinator composition remain open. |
| 2026-08-23 | implemented | Composed the versioned start and cancellation consumer with the typed read-only executor and supervised Core coordinator. Hardening serialized concurrent ticks, coalesced wake bursts without dropping follow-up work, preserved repeated-cancel authorization, rejected wire control-character drift, and kept active PostgreSQL quotas across UTC midnight. | `current change`; the focused cross-process, background-task, PostgreSQL, Operator projection, topic, and local-environment gate passed 152 cases with no skips or warnings; the quota cases passed against local PostgreSQL. | Define the versioned terminal completion handoff, bind the Operator-owned conversation delivery path, and retain governed restart and delivery evidence. |
| 2026-08-23 | implemented | Bounded retention when the production completion sink is absent. In-memory and PostgreSQL reconciliation abandon nonterminal completions at retention, and the terminal purge removes their task, progress, and outbox rows without rewriting or rerunning the immutable result. | `current change`; focused in-memory retention passed 1 case and isolated PostgreSQL persistence passed 15 cases with no skips, including the pending-to-abandoned-to-purge regression. | Define and bind the versioned completion transport before claiming user delivery. |
| 2026-08-23 | implemented | Added an idempotent StateStore lifecycle audit writer and a creation-audit claim fence. Audit or marker failure leaves a durable request unclaimable; redelivery reuses one audit marker and only releases the fence after the marker is durable. Removed inert direct/streamed policy and run-store construction from the detached-only binding. | `current change`; focused in-memory and runtime checks passed 42 cases, lifecycle and full PostgreSQL persistence checks passed 20 cases with no skips, and Ruff plus strict mypy passed. | Define and bind terminal completion delivery, then retain governed restart and delivery evidence. |

| 2026-08-26 | implemented | Added an explicit Core migration grant after a protected recovery exposed `permission denied` while the detached coordinator reconciled `background_task_attempt`. The runtime role receives CRUD on attempts, read and append on progress, and read, append, and update on completions; `PUBLIC` remains revoked. | `current change`; `20260826_core_background_task_runtime_grants.py`; focused migration grant regression passed. | Build and deploy an exact attested Core image, apply the migration through the protected service workflow, and retain a crash-free restart receipt before claiming deployed validation. |

### Remaining work

- [x] Run all focused PostgreSQL cases against the supported local service and record passing claim, lease, quota, outbox, reconciliation, retry, restart, and purge evidence with no skipped cases.
- [x] Implement the production read-only executor and compose `BackgroundTaskCoordinator` into the Core runtime with bounded startup, lease renewal, reconciliation, cancellation, quotas, and shutdown behavior through the versioned request transport.
- [x] Implement the completion sink so it appends the deterministic conversation turn and submits the immutable reply through the durable delivery ledger without rerunning the investigation.
- [x] Write `background-task.completed` and `background-task.delivery-enqueued` through atomic single-write StateStore markers with concurrent replay and conflict tests.
- [ ] Define the versioned terminal completion contract in [Durable Conversation Delivery](durable-conversation-delivery.md) and [Service Graduation and Data Ownership](../architecture/service-graduation-and-ownership.md), then bind the completion sink and its audit writer without giving Core an Operator conversation write.
- [x] Materialize owner-scoped list, detail, progress, and finite SSE replay behind the Operator API routes, including cross-owner 404 equivalence and least-privilege PostgreSQL reads.
- [x] Populate request summaries up to 500 characters, result summaries up to 2,000 characters, up to 16 evidence references, truncation flags, and nullable Heimdall attribution in both owner-scoped PostgreSQL task queries, with focused projection and malformed-attribution tests.
- [x] Consume create and cancel proposals through the versioned production transport while preserving owner scope, digest validation, persistence-before-wake, and explicit poison-record handling.
- [x] Add a bilingual FDAI Console task list, detail, progress, and explicit refresh surface with focused decoder tests and no mutation controls.
- [ ] Add Console create and cancel controls only after the production proposal consumer returns authoritative task and cancellation receipts.
- [x] Bind idempotent creation and cancellation lifecycle audit to the production request consumer and prevent claims until creation audit is durable.
- [ ] Record governed restart, process-loss, completion retry, retention, delivery, and runtime telemetry receipts before promoting any row to `validated`.

## Related docs

| To learn about | Read |
|----------------|------|
| Isolated investigation workers | [Bounded Task Workers](../agents/bounded-task-workers.md) |
| Operator conversation boundaries | [Operator Console](operator-console.md) |
| User delivery durability | [Durable Conversation Delivery](durable-conversation-delivery.md) |
| Runtime parity | [Runtime Parity](../deployment/dev-and-deploy-parity.md) |
