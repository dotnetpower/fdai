# Bounded Task Workers implementation ledger

This delivery ledger preserves reviewable implementation scope, append-only transitions,
and resumable work while the roadmap owner remains focused on normative design.

## Implementation status

The bounded worker core, durable store and opt-in production composition are implemented and
covered by focused tests, including actual loopback PostgreSQL. The Operator API route contract
is present, but parent admission, store-backed projection materialization, Console presentation,
detached completion and governed live evidence remain incomplete.
This ledger separates implementation evidence from operational validation; passing focused tests
does not promote the capability or prove a deployed worker path.

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| Metered planning and prepared production adapter | implemented | `core/task_worker/planning_executor.py`; `delivery/azure/llm/task_worker.py`; focused provider tests | Durable reservation precedes one bounded call; measured and unresolved usage survive failure, cancellation and replay. Configured-rate USD accounting is not invoice evidence. |
| Request model, isolated context, and capability attenuation | implemented | `core/task_worker/models.py`, `attenuation.py`, `profiles.py`; `tests/core/task_worker/test_attenuation.py` | The request is depth-one, the context projection is bounded, and the final tool set is the deterministic intersection of the three authorities. |
| Runtime lifecycle, planning executor, and tool gateway | implemented | `core/task_worker/runtime.py`, `planning_executor.py`, `tools.py`; focused lifecycle and accounting tests | Admission, recovery and drain are serialized; queued cancellation is durable and heartbeats cannot erase reservations. No parent/tool-selection loop is added. |
| Durable snapshots, branch events, recovery, and owner-scoped queries | implemented | `delivery/persistence/postgres_task_worker.py`; runtime lease adapter; `tests/integration/services/test_task_worker_runtime_postgres.py` | Actual loopback PostgreSQL verifies exact Core login, lease exclusion/loss, atomic terminal rollback and recovery behind 1001 terminal rows. No deployed database claim. |
| Parent synthesis and completion-sink ordering | implemented | `core/task_worker/synthesis.py`, `runtime.py`; focused synthesis and runtime tests | Worker contributions remain untrusted and bounded; terminal persistence precedes optional sink delivery. No production completion sink binding was found. |
| GET-only Operator API projection | in-progress | `families/conversation/manifest.py`; `test_operator_conversation_family.py` | The three authenticated GET routes and response-envelope seam exist, but no materializer was found that derives owner-scoped worker projections from the task-worker store. |
| Production Core composition and recorded-read registry | implemented | `runtime/task_workers.py`, `bootstrap_core.py`, `bootstrap_resources.py`; focused factory, shutdown, actual-SQL and Core wheel tests | Opt-in assembly fails on missing dependencies. Two recorded inventory operations work; five sources stay explicitly unavailable. Construction performs no model call. |
| Parent, Console, detached completion and operational evidence | not-started | Separate package boundaries; no governed live receipt added by #805 | Authenticated parent admission, operator projections/UI, durable reply delivery and live failure-path evidence remain outside this binding. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-09-15 | implemented | Reconciled the existing mirrored ledger with the current inline scope and preserved all three history rows using the canonical owner-to-ledger migration plan. Both language owners now link to this one ledger instead of carrying different section/table structures. | `current change`; #805 / PR #1064; exact CI 34954596330 attempt 1 reproduced locally; both `test_translated_document_structure.py` checks pass after repair, and append-only tracking plus translation parity pass. | Protected delivery of the repaired head remains pending; runtime behavior and the separate product/operational packages below are unchanged. |
| 2026-09-15 | implemented | Composed opt-in production workers with prepared Azure planning, durable measured/unresolved accounting, scoped recorded reads, singleton recovery and dependency-ordered shutdown. Reproduced and fixed multi-fact, recovery-window, admission/cancellation and graph-reader assumptions. | `current change`; #805; [focused review and exact checks](../../internals/task-worker-production-805.md); 151 focused tests passed, including 19 actual-SQL and 4 wheel/import checks; strict mypy passed for 14 source files. | Parent admission/tool selection, owner-scoped Operator materialization, Console, detached replies, additional provider sources and governed live receipts remain separate. |
| 2026-09-15 | implemented | Reproduced acceptance of an unmetered provider, then replaced ignored cost limits and summary-derived tokens with a worker-specific bounded response. Review rejected adapting the unmetered shadow seam or treating a Protocol as proof of actual billing control. | `current change`; #805; focused planning-executor and runtime selection passed 34 tests; strict targeted mypy passed. | Prove concrete pre-dispatch limits and failure/cancellation accounting, then complete production composition and restart verification under #805. |
| 2026-08-13 | in-progress | Adopted the implementation ledger and separated the implemented worker core from unfinished production and projection integration. | Current task-worker source, persistence adapter and migration, focused core and persistence tests, and Operator API route tests. | Bind the production runtime and projections, expose the read-only operator experience, and capture governed live evidence. |

### Remaining work

- [x] Compose `TaskWorkerRuntime` with the production recorded-read registry and prepared answer-planning provider; startup, actual-SQL restart and packaging checks pass under #805 without a production synthetic fallback.
- [ ] Bind authenticated parent admission and tool selection to the existing answer plan before claiming an end-to-end investigation; independently supply the five unavailable evidence sources where required.
- [ ] Materialize `workers.list`, `workers.get`, and `workers.events` from the PostgreSQL worker store with owner predicates inside each query and foreign-owner 404 coverage.
- [ ] Wire durable completion delivery into the detached-session reply path and prove that sink failure appends an event without rewriting or rerunning the terminal result.
- [ ] Add the operator-facing read-only worker projection and capture governed live receipts for success, timeout, budget exhaustion, denial, restart recovery, and cross-owner isolation.
