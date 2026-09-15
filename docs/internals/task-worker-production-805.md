# Production task-worker composition review

This record scopes #805 to Core production composition and its local falsifying evidence. It
preserves the metered adapter delivered by #1018. Operator projections, Console UI, parent
admission/detached delivery and live receipts remain separate work, not implied by this binding.

## Design before implementation

**Initial design:** Bind the existing executor to the current narrator target, existing bounded
read-investigation providers and PostgreSQL, then recover pending rows at Core startup.

**Critique:** The existing contributor protocol returns usage only on success. A failure after
dispatch, cancellation, timeout or process death can leave a zero-usage row. A protocol marker is
not a pre-dispatch budget. Generic recent-row recovery can hide older interrupted rows behind
terminal history, and a second Core process must not mark another process's live workers failed.
The existing unmetered Pantheon conversational port cannot enforce worker ceilings and is not a
valid fallback. Model configuration, provider invoice spend and configured-rate budget accounting
are different evidence.

**Revised design:**

1. Keep the original bounded contributor seam compatible. Add a prepared-call seam with an
   immutable token/cost upper bound and an independently revalidated request identity. Production
   requires the prepared seam; it never adapts the unmetered Pantheon port.
2. Persist the reservation before provider dispatch. Preserve measured usage separately from
   unresolved reservation, including failures, cancellation, timeout and interrupted recovery.
   A missing usage envelope is unknown, never a free call. A response with known usage but invalid
   content retains that usage. Parent synthesis exposes completeness and unresolved ceilings.
3. One Azure OpenAI chat-completion request has explicit output limits and a conservative complete
   UTF-8 request-byte bound with framing reserve. Price comes from the existing resolved-family
   USD pricing table. No missing-price default, model fallback, repair call or retry is allowed.
   Costs are configured-rate accounting based on provider token counts, not invoice measurement.
4. Build the read-only registry over the existing promoted-inventory readers. Retain the exact
   seven-tool profile, server-selected scope, bounded arguments/results and explicit unsupported
   evidence. This package does not invent a parent request, new operator endpoint, tool-selection
   model loop or an authenticated parent-admission path.
5. Production composition is explicitly gated because it can incur model cost. An enabled binding
   requires the existing Core DSN, eligible resolved narrator target, USD pricing, workload identity,
   HTTP client and exact read scope. Missing dependencies fail before worker availability, not with
   an in-memory or fake provider. Construction/recovery performs no model call.
6. Use a Core-owned PostgreSQL runtime lease before startup recovery. Recover only unresolved rows
   in bounded batches, never rerun terminal work, and fail startup if recovery cannot complete
   within its bound. Drain task cancellation before releasing the runtime lease and HTTP client.
7. Keep fixed-agent roles, topics, approval, execution, promotion and Core service ownership
   unchanged. Exposing the constructed runtime does not wire deferred parent/Operator surfaces or
   prove a deployed investigation. All source/provider tests are synthetic unless explicitly named
   as local PostgreSQL evidence.

## Planned falsifying checks

- Reject unpriced, wrong-currency, over-token/over-cost, changed prepared input and unmetered
  production construction before token lookup or HTTP.
- Retain measured success/abstention/invalid-content usage and unknown reservation on missing
  usage, provider failure, cancellation, timeout and process restart. Heartbeat cannot erase it.
- Keep tool attenuation, exact configured scope, no arbitrary query/mutation, owner isolation,
  unchanged retry identity, and suppressed unsupported summaries.
- Fail enabled startup on missing dependencies/database role/schema/lease; reject a competing
  runtime; recover interrupted rows even behind more than 1000 terminal rows; never rerun terminal
  work; close acquired resources on startup failure and shutdown.
- Verify actual Core construction, service-owned migration/table prerequisites and package
  inventory. Run only focused tests and changed-input static/docs checks, not repository suites.

## Revised recorded-read boundary

The first production-registry SQL test failed because the broad graph reader requires tables that
the initial startup check did not verify. Source inspection also showed that rooted graph views
deliberately remove properties, so a mocked graph containing state cannot prove a real state read.
Use a focused PostgreSQL reader over the existing snapshot, active pointer, resource and realtime
tables instead. One SQL statement must bind exact resource identity, snapshot, recorded state,
freshness and pending-change checks to the same database snapshot. Select only bounded name/state
fields, not raw properties or a broad graph. No new schema, cloud read or authority is introduced.

New local regressions also reproduced duplicate-admission, active-recovery, queued-cancellation
and upstream-shutdown-failure races. Serialize lifecycle admission/recovery/drain, ensure a task
enters its cancellation handler before exposing its handle, and always attempt worker cleanup
before closing shared HTTP. These are source fixes, not live fault-injection evidence.

## Initial evidence boundary

Starting protected main is `d5851038bc9d99b5080138681b8d84ecb2ecfff2`, CI `34946198490`
successful. An isolated task checkout and locked Python 3.13.14 environment were created.
#805 has no competing open PR; project synchronization deferred after its bounded timeout.
No implementation or new passing test is claimed by this design record. Pylance could not analyze
the non-editor worktree; focused runtime tests and strict type checking must supply executable
facts there. A research agent was rate-limited; no retry or concurrent model fan-out followed.

## Focused source critiques

These are distinct code and contract reviews, not repeated test executions or borrowed handover
review rounds. Each row records the finding or rejected approach and its bounded resolution.

| Round | Review | Resolution and evidence |
|-------|--------|-------------------------|
| SC-01 | The original bounded seam could report usage only after a successful response. A Protocol alone cannot reserve a billable request. | Added the prepared seam, immutable body/binding comparison and checkpoint-before-dispatch ordering; preserved the original nonproduction seam. |
| SC-02 | Missing provider usage and cancellation could become an implicit zero-cost result. | Added incomplete usage and retained reservation; malformed usage, cancellation, timeout and replay tests retain uncertainty. |
| SC-03 | Joining multiple fact claims with a newline violated the worker summary text contract. | Baseline regression raised `ValueError`; space-joined output passes without changing evidence or authority. |
| SC-04 | The newest-1000-row query hid older unresolved work behind terminal history. | Baseline recovery regression failed; unresolved-only bounded batches recover behind 1001 newer terminal rows. |
| SC-05 | Separate terminal snapshot/event transactions could expose success without its branch event. | The additive recoverable-store contract commits both together; an actual PostgreSQL trigger failure rolls back the transition and retains usage. |
| SC-06 | A second Core instance could incorrectly recover another instance's live work. | Exact Core login/current-role checks and an exclusive database session lease precede recovery. Competing startup and admin impersonation fail. |
| SC-07 | A heartbeat could overwrite planning accounting with tool-only usage; missing durable fields could be coerced to zero. | Serialized checkpoint writes and strict measured-field decoding preserve reservations and reject malformed accounting. |
| SC-08 | Retrying the same request with narrower capabilities could reuse a now-denied result. | Retry requires identical attenuation; the regression rejects changed capabilities without rewriting the original result. |
| SC-09 | The broad graph reader needed unverified tables and deliberately omitted state properties. Mocked graph state was not production proof. | The first actual-read test failed. A focused one-statement exact-resource reader now selects only bounded name/state fields and provenance from existing tables. |
| SC-10 | Duplicate admission, active recovery and cancellation before execution exposed lifecycle races. | Three deterministic regressions failed before repair. Admission/recovery/drain locking and cancellation-ready task handles preserve one task and durable queued cancellation. |
| SC-11 | An isolated-executor stop failure skipped worker drain; a failed worker drain could retain its lease. | A failing shutdown regression drove nested cleanup; owned lease release and shared cleanup are attempted while failure still propagates. |
| SC-12 | The default seven-tool profile and constructed factory could overstate delivered functionality. | Only two recorded inventory tools have sources. Five return `source_unbound`; no tool-selection model loop, parent admission, Operator/Console or reply binding is claimed. |

## Local verification

All calls use the locked task-local Python 3.13.14 environment. The following completed batch
passed **151 tests in 15.40 seconds**, with no skips. It includes 19 real loopback PostgreSQL cases
and 4 Core wheel/isolated-import checks; the latter counts are subsets, not additional tests.

```text
UV_OFFLINE=1 .venv/bin/python -m pytest -q --no-cov --tb=short
   services/core-control-plane/tests/core/task_worker
   services/core-control-plane/tests/delivery/azure/llm/test_task_worker.py
   services/core-control-plane/tests/delivery/test_task_worker_inventory.py
   services/core-control-plane/tests/runtime/test_task_workers.py
   services/core-control-plane/tests/runtime/test_bootstrap_shutdown.py
   tests/integration/services/test_task_worker_runtime_postgres.py
   tests/integration/services/test_core_service_package.py
```

- **Database boundary:** Disposable databases used the owning worker, snapshot and realtime
   migrations and a real `fdai_core` login, not administrator `SET ROLE`. PostgreSQL schema/grant
   rejection, singleton exclusion/loss, reservation persistence, owner predicates, terminal rollback
   and recorded-state freshness were exercised. No app or remote database was used.
- **Provider boundary:** All HTTP and token providers were synthetic. Success, abstention, malformed
   content/usage, reservation/measured checkpoint failures, timeout, cancellation, oversized response,
   redirect, 429 and 503 tests make no live call and prove no retry path in the adapter.
- **Composition boundary:** The real factory opens/reopens the production store and providers in
   SQL tests. A sentinel test proves Core assembly reaches that factory; it is not full-stack startup.
   The Core wheel includes every new module and cold-imports without a monolithic distribution.
- **Static checks:** Strict mypy passed for all 14 changed source modules, including Core bootstrap
   and shutdown. Ruff lint and format passed for all 23 changed Python source/test files.
   Editor diagnostics reported no errors in the final selected runtime and SQL test files.
- **Input reuse:** After the successful batch, docstring and formatting-only changes retained all
   23 normalized execution ASTs. The two reconstructed test files were compared with that baseline;
   an editor-introduced missing parenthesis was repaired before the final successful comparison.
   Final SHA-256 manifest digest for the 23 Python files plus root/service project configuration and
   lockfile: `3630771a8a68ab489762e91eced5fe521f0849e187c6800238e93c5a8708c02b`.
- **Generated knowledge:** The 14 reviewed System Knowledge seeds reference 16 distinct source
   paths. Their intersection with this change is empty; no generated catalog was hand-edited or
   regenerated unnecessarily.
- **Documentation:** Two English/Korean pairs passed translation parity and Korean quality;
   four changed roadmap documents passed the size check, and both owners passed append-only
   tracking. Punctuation and readable-Hangul checks passed for all 29 task-owned files; all 154
   relative Markdown link/image targets resolved. Scoped translation refresh was a verified no-op.

The earlier 120-case checkpoint did not cover the five later reproduced lifecycle/real-read
failures. It is superseded by the completed batch above, not added to its denominator. No
repository-wide suite, live model, Azure operation, deployment, promotion or invoice evidence is
part of this local result.

## Final integrated source review

These reviews followed the last executable source change and the passing completed batch. Later
edits only corrected documentation and formatting, with execution-tree comparison. They are not
independent reviewers or runtime fault-injection attestations.

| Round | Boundary reviewed | Conclusion |
|-------|-------------------|------------|
| FI-01 | Pantheon, authority and dependency direction | No AgentSpec, topic, role, approval, action or privileged identity changed. Core imports no HTTP/PostgreSQL adapter. |
| FI-02 | Budget preparation and provider identity | The production executor requires preparation and a checkpoint. The adapter recomputes the complete binding before one request; oversized/unpriced input fails before identity/HTTP. |
| FI-03 | Known versus unresolved accounting | Returned integer token usage determines configured-rate cost. Missing or malformed usage remains incomplete; no invoice-exact or zero-cost success claim is made. |
| FI-04 | Heartbeat, checkpoint failure and terminal failure | Gateway locking preserves accounting order. Failed reservation prevents dispatch; measured failure retains usage; SQL finish is atomic with its event. |
| FI-05 | Replay and attenuation | Original request equality and capability equality precede terminal replay; a finished worker incurs no new provider call. |
| FI-06 | Admission, queued cancellation and active recovery | Serialized admission joins one task; cancellation-ready handles terminalize queued work; active same-instance recovery is rejected. |
| FI-07 | Database ownership and restart | Real Core login, grants and schema are required. One owner recovers bounded unresolved batches. Lost lease is not reacquired, and uncertain work is never executed by recovery. |
| FI-08 | Exact inventory source and time | One SQL statement retains generation, resource and observation time. Target overlays, newer failed collection, stale/future/expected data and nontext state remain unavailable. No broad property payload is exposed. |
| FI-09 | Provider response and degraded behavior | One bounded response, exact choice/message/content shape, explicit usage, no redirect, repair or fallback. HTTP failures retain reservation and no summary. |
| FI-10 | Shutdown resource ordering | Isolated-executor stop is attempted first, worker drain next, shared HTTP cleanup last. Drain failures propagate and lease cleanup is attempted; no operational completion is manufactured. |
| FI-11 | Compatibility and packaging | Original provider/store seams remain available for nonproduction callers. Production requires additive prepared/recoverable contracts. Focused strict types and isolated Core wheel imports pass. |
| FI-12 | Delivery scope and residual claims | This implements source composition, not parent/tool-selection admission, all seven data sources, Operator materialization, Console, detached replies or deployed readiness. A session lease is not exactly-once remote HTTP. |

No unresolved confirmed Medium/High finding remains in this bounded source review. Residual product
packages and operational validation remain explicit in the bilingual owner and its implementation
ledger. Local success does not replace exact-head protected CI or an independently authorized
deployment.
