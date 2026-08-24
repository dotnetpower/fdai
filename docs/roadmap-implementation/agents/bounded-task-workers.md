# Bounded Task Workers implementation ledger

This delivery ledger preserves reviewable implementation scope, append-only transitions,
and resumable work while the roadmap owner remains focused on normative design.

## Implementation status

The bounded worker core and durable store are implemented and covered by focused tests. The
Operator API route contract is present, but production worker composition, store-backed
projection materialization, console presentation, and governed live evidence remain incomplete.
This ledger separates implementation evidence from operational validation; passing focused tests
does not promote the capability or prove a deployed worker path.

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| Request model, isolated context, and capability attenuation | implemented | `core/task_worker/models.py`, `attenuation.py`, `profiles.py`; `tests/core/task_worker/test_attenuation.py` | The request is depth-one, the context projection is bounded, and the final tool set is the deterministic intersection of the three authorities. |
| Runtime lifecycle, planning executor, and tool gateway | implemented | `core/task_worker/runtime.py`, `planning_executor.py`, `tools.py`; focused runtime and planning-executor tests | State transitions, concurrency, timeouts, cancellation ownership, budgets, heartbeats, read-only dispatch, abstention, and bounded failures are implemented without a production runtime binding. |
| Durable snapshots, branch events, recovery, and owner-scoped queries | implemented | `delivery/persistence/postgres_task_worker.py`; Alembic revision `20260720_0039`; `tests/persistence/test_task_worker.py` | PostgreSQL compare-and-swap persistence and restart recovery exist. This row does not claim a deployed database validation. |
| Parent synthesis and completion-sink ordering | implemented | `core/task_worker/synthesis.py`, `runtime.py`; focused synthesis and runtime tests | Worker contributions remain untrusted and bounded; terminal persistence precedes optional sink delivery. No production completion sink binding was found. |
| GET-only Operator API projection | in-progress | `families/conversation/manifest.py`; `test_operator_conversation_family.py` | The three authenticated GET routes and response-envelope seam exist, but no materializer was found that derives owner-scoped worker projections from the task-worker store. |
| Production composition and operational evidence | not-started | No non-test `TaskWorkerRuntime` construction, console task-worker surface, or governed live receipt was found | Production tools, planning integration, completion delivery, projection reads, and live failure-path evidence remain to be wired and exercised. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-08-13 | in-progress | Adopted the implementation ledger and separated the implemented worker core from unfinished production and projection integration. | Current task-worker source, persistence adapter and migration, focused core and persistence tests, and Operator API route tests. | Bind the production runtime and projections, expose the read-only operator experience, and capture governed live evidence. |

### Remaining work

- [ ] Compose `TaskWorkerRuntime` with the production read-only tool registry and answer-planning provider, then prove startup and restart behavior without a synthetic fallback.
- [ ] Materialize `workers.list`, `workers.get`, and `workers.events` from the PostgreSQL worker store with owner predicates inside each query and foreign-owner 404 coverage.
- [ ] Wire durable completion delivery into the detached-session reply path and prove that sink failure appends an event without rewriting or rerunning the terminal result.
- [ ] Add the operator-facing read-only worker projection and capture governed live receipts for success, timeout, budget exhaustion, denial, restart recovery, and cross-owner isolation.
