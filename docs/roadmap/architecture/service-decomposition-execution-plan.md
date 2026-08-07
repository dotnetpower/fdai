---
title: Service Decomposition Execution Plan
---
# Service Decomposition Execution Plan

This document tracks the implementation that moves FDAI to five independently
deployable runtime services. It is the durable progress record for the refactor;
design details remain in the owning architecture documents.

> **Target:** The program is complete only when all five services are deployed
> with distinct entry points, health checks, identities, and typed transport.
> An unmet Executor gate blocks completion instead of reducing the target back
> to four services.
>
> **Safety:** A checked item means its exit evidence exists. Planning text,
> package movement, or a passing unit test alone does not prove a process
> boundary is ready for authority cutover.

## Design at a glance

FDAI will finish this program with five runtime services. The first four roles
already exist, although their internal package and deployment boundaries still
need hardening. The fifth service extracts Thor-owned execution from Core so
only the isolated Executor holds mutation-capable workload identity.

| # | Runtime service | Target responsibility | Ingress | Executor authority |
|---|-----------------|-----------------------|---------|--------------------|
| 1 | Core Control Plane | Agent runtime, decisioning, approval joins, audit intent, recovery coordination | Internal event bus | None after cutover |
| 2 | Operator Service | Authenticated queries, conversations, projections, and governed request submission | External HTTPS and event bus | None |
| 3 | Document Ingestion API | Authenticated upload intake and API-owned document transitions | External HTTPS and event bus | None |
| 4 | Document Processing Worker | Durable inspection, extraction, indexing, claims, and reconciliation | Internal event bus and probes | None |
| 5 | Isolated Executor | Thor-owned command validation, target lock, provider effect, rollback attempt, and execution receipt | Internal event bus and probes | Sole holder |

The ontology, Rule Catalog, Rego build pipeline, Console, scheduled jobs, and
the 15 agents do not become separate services in this program. They remain
contracts, packages, static clients, jobs, or independently runnable event
subscribers inside their owning runtime service.

## Status summary

| State | Count | Meaning |
|-------|-------|---------|
| Completed | 6 | SD-00, SD-01, SD-02, SD-04, SD-05, and SD-06 have recorded exit evidence and focused validation. |
| In progress | 1 | SD-03 remains active in its persistent isolated worktree. |
| Planned | 2 | SD-08 and SD-09 have not started. |
| Blocked | 1 | SD-07 waits for centralized validation receipts and a pushable remote commit before live dispatch. |

Last updated: 2026-08-07.

## Execution checklist

| Done | ID | Work package | Dependencies | Parallel lane | Exit evidence |
|------|----|--------------|--------------|---------------|---------------|
| [x] | SD-00 | Freeze the five-service topology, owners, contracts, writers, identities, baseline tests, and rollback units in canonical documents and machine manifests. | None | Serial | Reviewed topology and ownership records; baseline check receipt |
| [x] | SD-01 | Decompose Operator route families into transport, application, projection, adapter, streaming, and persistence packages without changing JSON, SSE, authentication, or history behavior. | SD-00 | A | Frozen route contracts and package-boundary checks |
| [x] | SD-02 | Isolate Core composition, Thor execution, Saga audit intent and closure, and Vidar recovery behind explicit injected ports. | SD-00 | A | Authority regression and import-boundary receipts |
| [ ] | SD-03 | Harden the Ingestion API and Worker identities, database grants, claims, duplicate/reorder behavior, restart recovery, probes, and co-host rollback. | SD-00 | A | Role tests and a rollback rehearsal within 15 minutes |
| [x] | SD-04 | Add canonical ontology release distribution, exact reference pinning, N/N-1 compatibility, projection-writer ownership, mismatch rejection, replay, and rollback. | SD-00 | B | Cross-service ontology compatibility and semantic regression receipts |
| [x] | SD-05 | Build the Rego knowledge path from canonical AST analysis through catalog build, semantic validation, ontology/vector generations, incremental parity, exact applicability, evaluation, and governed feedback. | SD-04 | B | Query-to-exact-Rego contract tests and generation rollback receipt |
| [x] | SD-06 | Add canonical Change lineage, provider adapters, decision trace, delivery/outcome joins, resilience coverage, candidate-only learning, and the read-only Operator projection. | SD-02, SD-04, SD-05 | C | Replayable lineage and authority non-escalation receipts |
| [ ] | SD-07 | Implement the Isolated Executor command and receipt contracts, durable attempt mechanics, shadow consumer, health, telemetry, identity, and Container App without effect authority. | SD-02, SD-04 | C | Duplicate, reorder, restart, deadline, lock, and shadow receipts |
| [ ] | SD-08 | Cut mutation authority over to the Isolated Executor, remove executor roles from Core, verify independent effects, and rehearse return to the in-process topology. | SD-07 | Serial | Effective-access proof, exact-topology smoke, and timed rollback receipt |
| [ ] | SD-09 | Remove expired compatibility paths, enforce boundaries, update canonical documentation, run centralized stable-batch validation, and close residual work. | SD-01 through SD-08 | Serial | Green validation receipt for the exact commit range |

## Parallel execution rules

- **Lane A:** Operator, Core boundary, and ingestion work may run in separate
  worktrees after SD-00 when owned paths do not overlap.
- **Lane B:** Ontology boundary hardening may overlap package work. Rego
  generation waits for the canonical ontology release and semantic validation.
- **Lane C:** Change lineage and Executor shadow implementation may overlap only
  when shared contracts, pantheon role files, composition, and infrastructure
  identity files have one serial integration owner.
- **Serial joins:** Shared contracts, writer cutovers, production composition,
  identity cutover, rollback rehearsal, and stable-batch validation never run in
  competing sessions.

## Parallel session collision guard

Every session reserves its work package, branch or worktree, owned paths, and release condition
before editing. A second session must inspect the active reservations and the target worktree's
dirty and unmerged paths. It waits for a handoff when any owned path overlaps, even when the two
sessions use different branches.

- **Exclusive paths:** A session edits only its reserved paths. Dirty, untracked, renamed, or
  unmerged files in another session's reservation are not available for cleanup, formatting,
  conflict resolution, or opportunistic refactoring.
- **Integration owner:** One serial integration owner manages this plan pair,
  `config/service-decomposition.json`, cross-package shared contracts, pantheon role files,
  production composition, and identity cutover. Package-specific infrastructure remains with the
  package owner until handoff.
- **Handoff:** The owner releases paths only after a focused commit, its validation receipt, and
  residual work are recorded. The integration owner performs cherry-pick, merge, status changes,
  and dependency release; worker sessions do not race those joins.
- **Validation isolation:** A worker validates only its committed diff or reserved worktree. It
  does not run a changed-file selector over another session's dirty tree.
- **Persistent worktrees:** Every active worker uses a path under
  `/home/moonchoi/dev/fdai-worktrees/`. New reservations cannot use `/tmp` because host restart or
  cleanup can remove a worktree before its handoff evidence is integrated.

| Reservation | Current owner | Reserved paths | Release condition |
|-------------|---------------|----------------|-------------------|
| SD-01 completed route closure | Integration owner on `main`; handed-off worker retained read-only at `/home/moonchoi/dev/fdai-worktrees/sd01-turn-execution` | No source paths reserved. The old `/home/moonchoi/dev/fdai-worktrees/sd01-route-closure` worktree remains read-only and non-reserved; its untracked worker-local `chat_route_common.py` artifact must not be merged or cleaned opportunistically. | Completed and released after transport-only route ownership, application lifecycle ownership, unchanged wire behavior, and zero reverse imports passed focused validation and independent review |
| SD-03 effective access and rollback | Existing SD-03 isolated session at `/home/moonchoi/dev/fdai-worktrees/sd03-effective-access` | Ingestion runtime, ingestion-specific Terraform, access probe, and matching tests | Effective-access proof and rollback evidence handed to the integration owner |
| SD-06 completed lineage | Integration owner on `main`; prior core, projection, and hardening workers retained read-only | All SD-06 implementation paths released after `d4e430d60` | Canonical lineage, provider compatibility, decision/resilience traces, candidate-only learning, bounded Operator projection, and 14 critique rounds pass focused validation with no Medium-or-higher residual; execution and promotion authority remain zero |
| SD-07 serial finish | Integration owner on `main`; prior worker retained at `/home/moonchoi/dev/fdai-worktrees/sd07-shadow-executor` | `infra/modules/isolated-executor/**`; SD-07-only blocks in `infra/main.tf`, `infra/variables.tf`, and `infra/outputs.tf`; `deploy_isolated_executor` blocks in `.github/workflows/deploy-dev.yml`; matching Terraform/workflow tests; production composition and paired docs | Shadow deployment evidence recorded without effect authority; avoid ingestion modules and every SD-03-owned Terraform hunk; the released worker is read-only |
| SD-07 image health recovery | Persistent worker at `/home/moonchoi/dev/fdai-worktrees/sd07-health-recovery` | `Dockerfile`, `.github/workflows/deploy-dev.yml`, paired deployment docs, protected plan verification under `scripts/deployment/azure/`, typed plan evidence in `src/fdai/deployment_cli/remote.py` and `src/fdai/delivery/github/deployment_workflow.py`, matching focused tests, and only the isolated-Executor container command/test when executable fallback is required | An exact current image proves the isolated Executor startup contract before Terraform, the deployed revision reaches healthy without effect authority, and at least 10 critique rounds leave no Medium-or-higher residual; Terraform apply and rollback remain serial with SD-03 |
| Serial integration | Integration owner | This plan pair, machine status manifest, cross-package contracts, production composition, pantheon roles, and executor identity cutover | Focused package handoff accepted and dependency status updated |

## Progress update contract

Update this document in the same focused commit that changes a work package's
state. For each transition:

1. Update the status summary counts and the `Last updated` date.
2. Check an item only after its exit evidence exists.
3. Add the commit and focused check receipt to the evidence log.
4. Record a blocker with its owning gate and next disconfirming check.
5. Do not mark a parent item complete while a dependency or residual authority
   cutover remains open.

## Evidence log

| Date | Work package | State | Commit or receipt | Evidence and residual work |
|------|--------------|-------|-------------------|----------------------------|
| 2026-08-07 | SD-00 | Completed | `config/service-decomposition.json` at `95bd58718` | Five-service target and work-package DAG accepted. Baseline packs recorded 918 passed and 2 PostgreSQL-only skips; the live checks remain owned by SD-03 and SD-05. |
| 2026-08-07 | SD-01 | In progress | Start `ccfa3c3dd` | Claims-family package move is the first Operator slice. |
| 2026-08-07 | SD-02 | In progress | Start `ccfa3c3dd` | Thor execution port and receipt contract isolation started. |
| 2026-08-07 | SD-03 | In progress | Start `ccfa3c3dd` | Ingestion identity and storage-role verification started. |
| 2026-08-07 | SD-04 | In progress | Start `ccfa3c3dd` | Cross-service ontology release compatibility gate started. |
| 2026-08-07 | SD-02 | Completed | `2a82507cb`, `7e15ba084`, `7a48288cb` | Shared execution instances, durable Saga audit readiness, Vidar recovery readiness, normal dispatch, and HIL resume are explicit composition evidence; 122 union tests passed. |
| 2026-08-07 | SD-04 | Completed | `f5cf51e3a`, `91c88f2a3`, `a5350296e`, `b24c2d90d`, `07161a96c` | Exact release refs, additive N/N-1 compatibility, revision-fenced projection writers, mismatch rejection before provider I/O, and replay-stable atomic generation rollback passed a 142-test focused union. Eight PostgreSQL live cases remained skipped because `FDAI_DATABASE_URL` was unset; the baseline assigns that live generation receipt to SD-05. |
| 2026-08-07 | SD-05 | Completed | `1c9ce4e94` through `d211570c6`, `b24c2d90d`, `4f01a02e8` | Canonical AST manifests, promoted surfaces, held-out evaluation, concept-first exact Rule refs, atomic generations, rollback, and governed feedback are complete. The focused route passed 105 tests, the lifecycle pack passed 43 tests, and all 12 PostgreSQL generation and parity tests ran without skips. Retrieval retained `execution_authority: false`; SD-06 is dependency-ready. |
| 2026-08-07 | SD-06 | In progress | Start `74694b6ca` | A persistent core-only worker owns the immutable canonical Change lineage slice. It reuses existing `ChangeRecord`, `ChangeAssessment`, `DecisionCase`, and `ResponseOutcome` identities without adding a shared contract or touching Operator, ingestion, executor, composition, or infrastructure paths. |
| 2026-08-07 | SD-06 | In progress | `3fcf91880` | The first canonical lineage slice joins `ChangeRecord`, `ChangeAssessment`, the selected `DecisionCase` option, `Action`, and `ResponseOutcome` into one immutable replay-stable record. It rejects correlation, target, ActionType, digest, identity, and causal-order mismatches, canonicalizes evidence references, and hard-codes zero execution and promotion authority. Ruff, strict mypy, and 7 focused tests passed on the worker and again on `main`. Provider, resilience, candidate-learning, and read-only Operator joins remain open. |
| 2026-08-07 | SD-06 | In progress | `9f1c3be30`, `b2fd7401b`, `bcf9c701f` | Immutable resilience and decision traces now bind execution mode, impact scope, rollback contract, effect timing, recovery result, objective scores, protected objectives, constraints, approval requirements, selected effects, and reasoning receipts into lineage identity. Invalid observation windows and ambiguous score identities fail closed. Trace values and their boundary tests were split by responsibility; source files are 260 and 196 lines. Ruff, strict mypy, and all 11 focused package tests passed on the worker and `main`. Provider, candidate-learning, and read-only Operator joins remain open. |
| 2026-08-07 | SD-06 | In progress | `c64834b3a`, `52dbb2ba3` | Deterministic lineage learning projections are inert, require a separately sealed operational case, report `operational_reuse_eligible: false`, and hard-code zero execution and promotion authority. Public GitHub and Azure DevOps `ChangeFeed.recent()` outputs both pass canonical lineage and candidate extraction through mock transports, so no duplicate core adapter was added. Ruff, strict mypy, and all 16 focused package tests passed on `main`. The core-only reservation is released; read-only Operator projection waits for the SD-01 route handoff. |
| 2026-08-07 | SD-06 | In progress | Projection start `2ecd7a36c` | The SD-01 capability package is integrated. A new persistent worker owns only the pure `projections/change_lineage` package and its focused test. It cannot register HTTP routes or touch app, persistence, composition, core, or the SD-01 route reservation. The slice is falsified if a projected candidate becomes reusable without a sealed case, exposes nonzero authority, leaks unbounded source data, or imports Starlette/routes. |
| 2026-08-07 | SD-06 | In progress | `e76874409`; projection handoff | Frozen summary and detail views bound canonical lineage to candidate sealing and zero authority, rejected oversized identities, explicitly bounded display reason and evidence, and omitted raw provider content. Four projection tests, the Operator boundary gate, Ruff, and strict mypy passed. The combined lineage/projection union passed 20 tests. The implementation reservation is released; the next disconfirming check is the SD-01 conversation-persistence handoff followed by collision-free module-map ownership and HTTP registration review. |
| 2026-08-07 | SD-06 | In progress | Hardening start `96c959429` | A persistent isolated worker owns only the released SD-06 source and focused-test paths for at least 10 critique rounds. Each reproducible Medium-or-higher defect receives one focused fix, test, and commit; verified false positives count as critique rounds without production edits. Final completion requires an independent Low-only residual review. |
| 2026-08-07 | SD-06 | In progress | Hardening round 9 scope | GitHub `ChangeFeed.recent()` raised `TypeError` when naive query bounds were compared with its aware normalized deployment timestamp, while the Azure DevOps peer normalizes the same bounds to UTC. The unowned GitHub adapter file is added to this worker only for that reproduced parity fix; all other provider paths remain read-only. |
| 2026-08-07 | SD-06 | Completed | `f83c82f62` through `d4e430d60`; Low-only review | Fourteen critique rounds fixed reproducible lineage/candidate digest forgery, causal timestamp omission, assessment evidence loss, outcome-effect mismatch, selected-option conflict, resilience timing bypass, projection identity/count/reason metadata gaps, and GitHub naive-window failure. Two impossible-state or intentionally never-raising authority claims were rejected as false positives. Final independent review found no Medium-or-higher residuals. Ruff, strict mypy, the Operator boundary gate, and 43 focused lineage/projection/provider tests passed on exact `main`. Low residuals are the fail-closed silent skip of malformed GitHub timestamps, content-digest visibility in the authorized detail projection, and the 401-line lineage model just above the 400-line advisory. |
| 2026-08-07 | SD-01 | In progress | `f220eb06f`, `2739e2be6`, `7c18ed513`, `0ab723835`, `64955ba87` | Stream metrics, terminal projections, post-generation orchestration, application capability ownership, and authenticated request preparation moved behind explicit application or projection packages. The latest request-preparation union passed 192 tests, the application/projection reverse-import count is zero, and the scoped boundary gate is green. JSON, SSE, authentication, cancellation, and history wire behavior remain route-owned. Remaining route families and final compatibility classification keep SD-01 open. |
| 2026-08-07 | SD-01 | In progress | `2111617b8` | Trajectory detail, deterministic screen answers, redacted model tracing, and response resource context moved to pure conversation projections without compatibility shims. The main integration union passed 258 tests, application/projection-to-route imports remained zero, and the scoped boundary and translation gates passed. |
| 2026-08-07 | SD-01 | In progress | `bbb5ac552` | Answer planning, terminal quality review, content-policy recovery, and busy-input steer or interrupt coordination moved to explicit application packages with no compatibility shims. The main lifecycle union passed 131 tests, application/projection-to-route imports remained zero, and chat route files fell from 25 to 17. |
| 2026-08-07 | SD-01 | In progress | `2ecd7a36c` | Agent delegation, runtime-skill disclosure, configuration drift, public-web evidence, request-time capability visibility, and topology intent moved behind application or adapter boundaries. The main capability union passed 110 tests, reverse imports remained zero, provider scope stayed server-owned, and chat route files fell from 17 to 11. |
| 2026-08-07 | SD-01 | In progress | `10d7ae266` | Principal-scoped transcript and image lifecycle persistence moved behind `persistence.conversation`; exact document evidence moved to a pure conversation projection. The worker handoff passed 438 focused tests. The main persistence union passed 155 tests, reverse imports remained zero, scoped boundaries and translations passed, and eight chat route files remain. Final response-tail and route-common coordination plus route-family classification keep SD-01 open. |
| 2026-08-07 | SD-01 | In progress | `e141ab07e` | Policy and response completion moved behind explicit application owners, and the chat family reached a six-file structural inventory. The main union passed 235 tests; Ruff, strict mypy, the structural boundary gate, and the translation gate passed; reverse imports remained zero. Independent review found a High residual because `chat.py` and `chat_stream.py` still coordinate planning, evidence, persistence, and metering. This is partial structural closure, not SD-01 completion. |
| 2026-08-07 | SD-01 | In progress | Reservation handoff | The active reservation moved to `/home/moonchoi/dev/fdai-worktrees/sd01-turn-execution`. The old `/home/moonchoi/dev/fdai-worktrees/sd01-route-closure` worktree remains read-only because it contains an untracked worker-local `chat_route_common.py` artifact whose content differs from the deleted historical blob. It is not an active reservation and must not be cleaned or merged opportunistically. |
| 2026-08-07 | SD-06 | In progress | `226e1058a` | The canonical module inventory now owns `projections/change_lineage` as a bounded read-only, request-local projection with no execution, promotion, provider-I/O, or persistence authority. The exact Operator package and route inventory passed 10 tests, and the bilingual map, translation, and punctuation gates passed. SD-06 remains open only for its reserved critique campaign and later status closure. |
| 2026-08-07 | Parallel sessions | In progress | Persistent worktree migration | Active SD-03 and retained SD-07 workers moved to `/home/moonchoi/dev/fdai-worktrees/`; all new workers use that persistent root. Temporary worktree paths are no longer valid reservations. |
| 2026-08-07 | SD-07 | In progress | Start `03f6ef265` on `work/sd07-shadow-executor` | Command/receipt transport and durable shadow-attempt mechanics started in `/tmp/fdai-sd07`. Effect authority, production composition, pantheon roles, and identity cutover remain reserved for serial integration. |
| 2026-08-07 | SD-07 | In progress | `3b84ee15a`, `800eee04b` | Versioned command/receipt schemas, durable duplicate/reorder/restart/deadline closure, poison-record DLQ, at-least-once receipt publication, supervised health, and no-effect telemetry passed a 55-test focused union on `main`. Logical-target lock evidence, production composition, workload identity, and Container App deployment remain open; effect authority stays unavailable until SD-08. |
| 2026-08-07 | SD-07 | In progress | `9ff088aec` | The existing `ResourceLock` seam now serializes same-target shadow commands while different targets overlap, exact target identity is used, and handler failure releases the lock. The 59-test focused union passed on the worker and the lock handoff is integrated. Production composition, workload identity, Container App deployment, and live shadow smoke remain open. |
| 2026-08-07 | SD-07 | In progress | Serial start `b813a227f` | The packaged shadow entry point and explicit deployed-process marker are integrated. Serial IaC now owns only the reserved isolated-Executor module and SD-07-specific root blocks; SD-03 ingestion Terraform remains untouched. |
| 2026-08-07 | SD-07 | In progress | `0c52be49d` | Opt-in internal Container App IaC, a dedicated no-effect UAMI, operational command/DLQ/receipt entities, Key Vault-backed durable state, distributed lock DSN, and internal probes are implemented. Root Terraform validate passed, the module shadow-boundary test passed 1/1, and authority tests passed 3/3 with no SD-03 path changes. Live runner plan/apply, exact-topology smoke, and timed rollback remain open. |
| 2026-08-07 | SD-07 | Blocked | `f3eb25593`; live gate | The private-runner workflow exposes `deploy_isolated_executor`, preserves plan-only default and design-mocks exclusivity, and verifies the app revision after apply; 24 workflow tests passed. The pre-status measurement recorded 575 pending commits in the shared queue and local `main` 50 commits ahead of `origin/main`, so live dispatch waits for the Integration Validator. The next disconfirming check is an exact validation receipt for the SD-07 commits followed by a successful push; only then run the plan-only workflow. |
| 2026-08-07 | SD-06 | Completed | `3d601afbe`; Low residual follow-up | A malformed GitHub deployment timestamp still fails closed, but now emits one redacted structured warning with only provider, record type, and reason fields. Provider row values, repository identity, and commit refs stay out of the log. All 9 GitHub change-feed tests, Ruff, and strict mypy passed. The remaining Low residuals are authorized detail-projection content digests and the 401-line lineage model just above the 400-line advisory. |
| 2026-08-07 | SD-06 | Completed | `7dca0e720`, `fe1664664`, `e70273d45`; final Low-only follow-up | Canonical identity serialization moved to a focused module with an exact digest snapshot, reducing the aggregate lineage model from 401 to 340 lines. Direct summary/detail construction now rejects forged lineage, candidate, assessment, and target digest shapes, and bounded evidence always retains the canonical assessment reference. Exact `main` passed 46 focused lineage/projection/GitHub tests, Ruff, strict mypy, the Operator boundary gate, signed framework integrity, and editor diagnostics. Independent review found no Medium-or-higher or reproducible Low defect. Non-decreasing equal timestamps remain valid for coarse clocks, long provider identities remain valid in core while the Operator projection rejects them above its display bound, and authorized content-digest visibility remains an intentional Low replay reference with no HTTP, persistence, provider-I/O, execution, or promotion path. |
| 2026-08-07 | SD-01 | Completed | `e141ab07e`, `d741d40e4`, `2de2c15f1`, `2c9bbd89f`; final independent review | `e141ab07e` established partial structural closure, `d741d40e4` added typed JSON execution, `2de2c15f1` added typed SSE execution, and `2c9bbd89f` locked the structural boundary and documentation. The main union passed 283 tests after SSE integration, and the focused structural closure passed 114 tests. The exact route inventory is `chat.py`, `chat_registration.py`, `chat_stream.py`, `chat_stream_protocol.py`, `chat_stream_request.py`, and `chat_verification.py`; `chat.py` is 259 LOC and `chat_stream.py` is 211 LOC. Application, projection, and persistence reverse imports to routes are zero, and `turn_execution` imports of Starlette, routes, and concrete adapters are zero. Ruff and strict mypy are green, and translations pass 175/175. JSON/SSE transport, authentication, request parsing, status mapping, frame sequencing, and cancellation stay route-owned; planning, evidence, generation, verification, persistence, and metering lifecycle coordination stay application-owned. Wire, replay, interruption, and history behavior are preserved. Independent final review found zero Medium-or-higher findings and one Low residual: the implementation-free `routes/chat_verification.py` compatibility facade remains for catalog/source-path compatibility and is an SD-09 cleanup candidate, not a completion blocker. |
| 2026-08-07 | SD-01 | Completed | Hardening rounds 1-13; Low-only review | Twelve independent critique rounds covered JSON and SSE transport parity, route inventory, lifecycle ordering and cancellation, persistence and replay, principal isolation, identity boundaries, redaction, and provenance. One reproducible Medium finding showed arbitrary document-resolver `RuntimeError` details crossing both JSON and SSE HTTP responses. The shared request-preparation and JSON lifecycle boundaries now emit a fixed unavailable detail while preserving the original exception as the internal cause. The complete chat-route suite passed 82 tests; the exact redaction regressions passed 2 tests; Ruff, formatting, and strict mypy passed on the production slice. Round 13 independently rejected the alleged incomplete SSE status map, double cleanup, completion-before-persistence, and duplicate-planning findings against the current call paths. No Medium-or-higher residual remains. The implementation-free `routes/chat_verification.py` facade remains the intentional Low SD-09 cleanup candidate. |
| 2026-08-07 | SD-07 | In progress | Live run `31177967045`; image admission recovery start | Terraform apply and convergence succeeded, but the isolated Executor revision remained unhealthy because the configured `fdai-isolated-executor` command was absent from the reused ACR `v0.1.163` image. Log Analytics proved repeated OCI `ContainerCreateFailure` before process start; image pull, Core health, and Operator API health succeeded. The persistent recovery worker owns only the image-admission slice. The next disconfirming check is an exact current image whose isolated entry point passes before Terraform and whose revision reaches healthy. |

## Related documents

| To learn about | Read |
|----------------|------|
| Graduation, ownership, and rollback gates | [Service Graduation and Data Ownership](service-graduation-and-ownership.md) |
| Repository package boundaries | [Project Structure](project-structure.md) |
| Azure runtime and identity deployment | [Deploy and Onboard](../deployment/deploy-and-onboard.md) |
| Operating ontology release boundaries | [Operating Ontology Platform](operating-ontology-platform.md) |
| Operator package ownership | [Operator Console Module Map](../interfaces/operator-console-module-map.md) |
