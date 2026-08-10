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
| Completed | 10 | SD-00 through SD-09 have recorded exit evidence and focused validation. |
| In progress | 0 | No service-decomposition work package remains active. |
| Planned | 0 | No service-decomposition work package remains planned. |
| Blocked | 0 | No work package is currently blocked. |

Last updated: 2026-08-09.

## Execution checklist

| Done | ID | Work package | Dependencies | Parallel lane | Exit evidence |
|------|----|--------------|--------------|---------------|---------------|
| [x] | SD-00 | Freeze the five-service topology, owners, contracts, writers, identities, baseline tests, and rollback units in canonical documents and machine manifests. | None | Serial | Reviewed topology and ownership records; baseline check receipt |
| [x] | SD-01 | Decompose Operator route families into transport, application, projection, adapter, streaming, and persistence packages without changing JSON, SSE, authentication, or history behavior. | SD-00 | A | Frozen route contracts and package-boundary checks |
| [x] | SD-02 | Isolate Core composition, Thor execution, Saga audit intent and closure, and Vidar recovery behind explicit injected ports. | SD-00 | A | Authority regression and import-boundary receipts |
| [x] | SD-03 | Harden the Ingestion API and Worker identities, database grants, claims, duplicate/reorder behavior, restart recovery, probes, and co-host rollback. | SD-00 | A | Role tests and a rollback rehearsal within 15 minutes |
| [x] | SD-04 | Add canonical ontology release distribution, exact reference pinning, N/N-1 compatibility, projection-writer ownership, mismatch rejection, replay, and rollback. | SD-00 | B | Cross-service ontology compatibility and semantic regression receipts |
| [x] | SD-05 | Build the Rego knowledge path from canonical AST analysis through catalog build, semantic validation, ontology/vector generations, incremental parity, exact applicability, evaluation, and governed feedback. | SD-04 | B | Query-to-exact-Rego contract tests and generation rollback receipt |
| [x] | SD-06 | Add canonical Change lineage, provider adapters, decision trace, delivery/outcome joins, resilience coverage, candidate-only learning, and the read-only Operator projection. | SD-02, SD-04, SD-05 | C | Replayable lineage and authority non-escalation receipts |
| [x] | SD-07 | Implement the Isolated Executor command and receipt contracts, durable attempt mechanics, shadow consumer, health, telemetry, identity, and Container App without effect authority. | SD-02, SD-04 | C | Duplicate, reorder, restart, deadline, lock, and shadow receipts |
| [x] | SD-08 | Cut mutation authority over to the Isolated Executor, remove executor roles from Core, verify independent effects, and rehearse return to the in-process topology. | SD-07 | Serial | Effective-access proof, exact-topology smoke, and timed rollback receipt |
| [x] | SD-09 | Remove expired compatibility paths, enforce boundaries, update canonical documentation, run centralized stable-batch validation, and close residual work. | SD-01 through SD-08 | Serial | Green validation receipt for the exact commit range |

## Independent service extraction

The completed SD program proves five deployed process, health, transport, and identity boundaries.
The IS program now makes those five roles independently buildable and releasable. Completion
requires five Python distributions, images, Terraform roots, migration branches, and isolated
upgrade/rollback proofs. A service may import only versioned shared contracts, provider Protocols,
and telemetry primitives from another distribution; importing another service implementation is
not supported.

### Final repository layout

The IS program is complete only when repository ownership matches runtime ownership. Each service
owns its implementation, unit tests, build definition, and Python distribution below one service
root. The repository root retains cross-service integration tests and workspace orchestration, not
a second application package.

```text
fdai/
├── services/
│   ├── core-control-plane/
│   │   ├── docker/Dockerfile
│   │   ├── services/core-control-plane/src/fdai/
│   │   ├── src/fdai_core_service/
│   │   ├── services/core-control-plane/tests/
│   │   └── pyproject.toml
│   ├── operator-service/
│   │   ├── docker/Dockerfile
│   │   ├── src/fdai_operator_service/
│   │   ├── services/core-control-plane/tests/
│   │   └── pyproject.toml
│   ├── document-ingestion-api/src/fdai_ingestion_api_service/
│   ├── document-processing-worker/src/fdai_document_worker_service/
│   └── isolated-executor/src/fdai_executor_service/
├── packages/
│   └── service-contracts/
│       ├── src/fdai_service_contracts/
│       ├── services/core-control-plane/tests/
│       └── pyproject.toml
├── services/core-control-plane/tests/
│   └── integration/
└── pyproject.toml
```

- **Service roots:** `services/<service>/` are the only implementation and unit-test owners for
  the five runtime services. A service-specific Dockerfile builds only that service distribution.
- **Shared package:** `packages/service-contracts/` contains versioned wire contracts, provider
  Protocols, and telemetry primitives only. It does not contain business logic, composition, data
  access, or another service's adapter.
- **Root workspace:** The root `pyproject.toml` coordinates workspace members and development
  tooling with `package = false`. It does not publish or install a monolithic FDAI application
  distribution.
- **Cross-service tests:** Root `tests/integration/` verifies wire compatibility and deployed
  workflows. Unit and component tests move with their owning service.
- **Retired compatibility tree:** Top-level `src/fdai/`, the shared multi-target service
  Dockerfile, legacy service entry points, and duplicate contract definitions are migration-only
  artifacts. IS-08 removes them locally before IS-07 proves image-based N/N-1 rollback from the
  final service-owned sources. Git history and immutable prior images replace a checked-in legacy
  source tree as the rollback mechanism.

| Done | ID | Work package | Dependencies | Exit evidence |
|------|----|--------------|--------------|---------------|
| [x] | IS-00 | Freeze current implementation-import debt and exact package, image, state, migration, and rollback targets. | None | Machine manifest and non-growth gate |
| [x] | IS-01 | Extract the versioned shared contract SDK without service implementations. | IS-00 | Five consumers install and validate the same SDK |
| [x] | IS-02 | Add five independently executable service distributions and composition roots. | IS-01 | Five isolated wheel and cold-start receipts |
| [x] | IS-03 | Remove every cross-service implementation import. | IS-01, IS-02 | Import count zero and enforced boundary gate |
| [x] | IS-04 | Split durable writer grants and migration branches by service. | IS-02 | Five migration heads and zero writer overlap |
| [x] | IS-05 | Build, scan, attest, and publish five minimal service images. | IS-02, IS-03 | Five immutable image, SBOM, and startup receipts |
| [x] | IS-06 | Split service Terraform roots, state, and deployment workflows from the shared platform. | IS-04, IS-05 | Five local roots, isolated backend contracts, state ownership checks, and peer-isolation mechanics pass |
| [x] | IS-07 | Prove N/N-1 contracts and independent upgrade/rollback for each service. | IS-03, IS-06, IS-08 | Five local N -> N-1 -> N artifact transitions and ten peer-stable focused receipts pass |
| [x] | IS-08 | Move implementation, unit tests, build definitions, and distributions under their five service roots; retire the top-level monolith source, duplicate contracts, co-host, in-process authority, shared-image, and shared-migration compatibility paths. | IS-03, IS-05 | Final repository layout matches the documented tree; top-level production source and topology compatibility path counts are zero |
| [ ] | IS-09 | Enforce the final repository layout, run at least ten independent critique-and-hardening rounds, and close the program. | IS-07, IS-08 | Layout and import gates pass; Medium-or-higher residual count zero; deferred remote verification passes |

The machine source of truth is `config/independent-services.json`. Every migration wave updates its
status and evidence in the same focused commit. Shared Event Hubs, PostgreSQL hosting, ACR, Key
Vault, networking, and observability remain platform resources; logical ownership, credentials,
schemas, migration history, deployment state, and rollback are service-specific.

IS-06 and IS-07 close on local executable evidence so implementation can proceed without waiting
for a deployment environment. Exact remote plan/apply, peer-drift, and rolling receipts are a
separate program-final verification gate owned by IS-09. A failed final verification reopens the
affected package and blocks program closure; local evidence never claims a live deployment result.

The accepted IS-00 AST baseline is 140 Operator files, 5 ingestion files, and 2 isolated Executor
files importing `fdai.core`. These are migration debts, not permitted target dependencies. The
non-growth gate blocks an increase while later work packages reduce every count to zero.

IS-01/02 produced one implementation-free contract wheel and five service wheels with unique
console entry points. Their first composition roots deliberately lazy-import the existing FDAI
implementation so behavior stays unchanged. The five wrapper imports are an explicit IS-03 debt;
they are not evidence of final source independence.

IS-03 removed those wrappers and every cross-service implementation import from the five service
distributions. Local IS-08 now gives Core physical ownership of `src/fdai` and
`src/fdai_core_service` below its service root. The other four services contain only service-local
implementation and the contract SDK. Each service owns its tests and `docker/Dockerfile`; the root
workspace is non-package orchestration; and only cross-service checks remain under
`tests/integration`. The root and shared multi-target Dockerfiles, legacy entry points, duplicate
contracts, and generic ingestion co-host seam are absent.

Local completion evidence includes six independently built wheels, five nonroot service images,
five image health checks, five validated migration branches covering 104 tables and 11
transitions, five locally validated Terraform roots, zero cross-service implementation imports,
and forty-one independent critique-and-hardening rounds with zero Medium-or-higher local residuals.
IS-06 and IS-07 are locally complete. Exact remote plan/apply and
rolling confirmation is deferred to IS-09 and uses final service-owned inputs without restoring
the monolith as a rollback source. IS-09 pins deployable distribution `0.1.2` images as N-1 and
distribution `0.1.3` as N while retaining the existing contract-set `1.0.0`/`1.1.0` matrix.

Protected service deployment separates immutable artifact provenance from execution-control
provenance. A target `commit_sha` may be any ancestor of protected `main`, which permits an
attested N-1 image to participate in rollback rehearsal. The workflow itself and every deployment
control script, Terraform root, service migration, and peer-state input always come from current
protected `main`; exact plan/apply replay rejects a control change between its two runs. Image
builds and plans may run concurrently across the five runner slots, but evidence-bearing applies
run serially so each service receipt can prove that all four peer states remained unchanged.

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
| SD-03 completed effective access and rollback | Integration owner on `main`; prior worker retained read-only at `/home/moonchoi/dev/fdai-worktrees/sd03-effective-access` | No source paths reserved | Live effective-access proof and the 2-second rollback rehearsal were accepted and the implementation reservation was released |
| SD-06 completed lineage | Integration owner on `main`; prior core, projection, and hardening workers retained read-only | All SD-06 implementation paths released after `d4e430d60` | Canonical lineage, provider compatibility, decision/resilience traces, candidate-only learning, bounded Operator projection, and 14 critique rounds pass focused validation with no Medium-or-higher residual; execution and promotion authority remain zero |
| SD-07 completed shadow Executor | Integration owner on `main`; prior shadow and health-recovery workers retained read-only | All SD-07 implementation and image-admission paths released after `aa89b0bf1` | Exact protected apply, healthy shadow revision, canary, immutable receipt, digest-bound image admission, 11 critique rounds, and focused validation pass with effect authority remaining zero |
| SD-08 completed authority cutover | Integration owner on `main`; prior worker retained read-only at `/home/moonchoi/dev/fdai-worktrees/sd08-authority-cutover` | No source paths reserved after the closing commit | Exact cutover and rollback plans, independent effects, continuous offsets, five healthy services, no-op convergence, cleanup, and timed receipts accepted |
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
| 2026-08-07 | SD-03 | Completed | `480d11686`, `5c034fc65`; live effective-access receipt | Seven focused Terraform cases passed, the split-to-cohost-to-split rehearsal completed in 2 seconds against a 900-second budget, and the VNet runner confirmed exact inherited Azure RBAC plus non-privileged PostgreSQL runtime roles. The live ingestion API and worker revisions are healthy. |
| 2026-08-07 | SD-07 | In progress | Plan `31179749690`; apply `31180087754` | The exact protected plan was `0 add / 9 in-place change / 0 destroy` and the apply completed exact-plan verification, convergence, both migrations, five healthy runtime revisions, API health, canary, and immutable receipt. The isolated identity has only ACR pull, command receive, receipt/DLQ send, and state-secret read roles; effect authority remains zero. The prior in-process Core path remains the SD-08 rollback artifact. Image-admission critique handoff and the SD-08 timed authority-cutover rollback remain open. |
| 2026-08-07 | SD-07 | Completed | `c8a32ae77` through `aa89b0bf1`; rounds 1-11 | The final image verifies the isolated entry point under uid 65532. Protected plans accept only an attested GHCR subject whose ACR digest matches, require explicit authorized promotion, preserve strict runtime-image metadata, and bound every external image operation. The exact main union passed 72 verifier, workflow, image, transport, and CLI tests plus Ruff, strict mypy, YAML, translation, punctuation, and whitespace checks. Independent review found no reproducible Medium-or-higher residual; malformed registry responses and unavailable pre-promoted images fail closed. Live run `31180087754` completed health, canary, and immutable apply receipt with effect authority at zero. SD-08 is dependency-ready and remains serial. |
| 2026-08-07 | SD-08 | In progress | Identity-boundary discovery start | The first hypothesis that one Event Hubs role could simply move was falsified: the current aggregate identity also owns Core transport and startup dependencies, while Core directly attaches the aggregate and three vertical identities. The serial worker first separates required Core transport/read identity from mutation-capable executor identities in design and topology tests. Effect authority remains zero until a later exact cutover plan and rollback receipt. |
| 2026-08-08 | SD-08 | In progress | Implementation-ready focused receipt | Additive Executor receipt `1.1.0`, remote direct-API command/receipt correlation, pre-effect audit intent, stable Core receipt consumer group, duplicate-safe isolated dispatch, explicit default-off Terraform cutover, gateway principal transfer, reversible NSG probe, and protected workflow verification passed 126 focused tests, strict mypy, Ruff, Terraform validate, six root topology cases, and two module cases. Live effect authority remains unchanged until the protected plan is accepted and applied. |
| 2026-08-08 | SD-08 | Completed | Plans `31207740363`, `31211368557`, `31214493667`; applies `31209982126`, `31211927016`, `31214900219` | The first isolated proof used offsets `[0,1]`, one provider write, ARM present/absent observation, cleanup, and a 142-second receipt. The rollback plan was `0 add / 3 change / 0 destroy`; local transport then proved one write and cleanup in 450 seconds. The final cutover plan was `0 add / 4 in-place change / 0 destroy`, with no replacement or role-assignment change. Final isolated transport continued at offsets `[3,4]`, produced exactly one provider write, passed independent ARM observation and cleanup in 436 seconds, kept all five revisions healthy, completed canary, and converged to no changes. |
| 2026-08-08 | SD-09 | Completed | Closing validation receipt | The obsolete `routes.chat_verification` source-path facade was removed after the capability catalog moved to the owned verification package. All 22 reviewed boundary-docstring scopes now enforce, and the capability catalog, Operator layout, and boundary suite passed 30 focused tests with zero reported boundary gaps. Centralized validation passed 15076 tests with 15 environment-dependent skips, strict mypy over 1904 source files, and every repository gate before push. |
| 2026-08-09 | IS-06 | Completed locally | Local deployment receipt | Five Terraform roots and backend contracts, five state-migration ownership contracts, protected plan/apply guards, and semantic four-peer isolation mechanics passed 113 focused deployment tests. Exact remote receipts remain deferred to the IS-09 program-final gate and are not claimed by this transition. |
| 2026-08-09 | IS-07 | Completed locally | Local transition evidence | Five `0.1.3 -> 0.1.2 -> 0.1.3` wheel transitions, ten nonroot service images, and ten peer-stable focused migration/rollback receipts passed with preserved offsets, zero peer restarts, and zero duplicate terminal effects. Remote rolling confirmation remains deferred to IS-09. |
| 2026-08-09 | IS-09 | Local review complete | Rounds 11-14; `07db3e5d8` | Four independent rounds reviewed protected deploy provenance, semantic peer-state isolation, seven-root drift detection, and N/N-1 evidence integrity. One reproducible Medium finding allowed a completed program-final status with incomplete accepted receipt counts; the checker now requires all five plan/apply and all five upgrade/rollback receipts. Focused manifest and compatibility checks pass with zero Medium-or-higher local residuals. IS-09 remains in progress until the deferred remote 5+5 verification passes. |
| 2026-08-09 | IS-09 | Hardening continues | Rounds 15-28 | Ten independent reviews covered protected deploy, plan sealing, peer isolation, rollback, live compatibility, migrations, supply chain, drift, Terraform ownership, and final closure. Live runs then hardened bounded parallel runner slots, remote shell expansion, explicit registration success, and final-path image shebangs. Core run `31274885226` proved the broken image failed closed and restored a healthy prior revision; the corrected Core image builds and imports locally. Medium-or-higher local residuals are zero; remote 5+5 verification remains required. |
| 2026-08-09 | IS-09 | Live evidence hardening | Round 29 | A live evidence artifact can no longer pass by rehashing `observed:false` content. Validation now binds every observation's kind and service and requires a true observed result before its content-addressed ref can satisfy a live migration or rollback receipt. |
| 2026-08-09 | IS-09 | Worker cutover recovery | Round 30 | Run `31276433851` failed before mutation because the live legacy ClamAV sidecar had no probes. Initial cutover now snapshots that exact empty probe contract only for rollback and verifies its exact restoration; normal snapshots and every new worker revision still require startup, liveness, and readiness TCP probes. |
| 2026-08-09 | IS-09 | Runtime dependency and migration readiness | Round 31 | Live revisions exposed missing `aiohttp` in the ingestion API and unapplied Operator/Executor role branches. The ingestion distribution now owns the async Azure transport dependency, and protected service apply resolves a validated Key Vault reference, masks the admin DSN, and advances the exact service-owned migration branch before traffic. |
| 2026-08-09 | IS-09 | Exact secret rollback | Round 32 | Operator and Executor recovery revisions were healthy, but verification found post-apply `database-dsn` aliases beside legacy names. Rollback now removes only secret names absent from the immutable snapshot, restores prior Key Vault references, and then verifies exact equality. |
| 2026-08-09 | IS-09 | Enforced database principal | Round 33 | Plans declared `fdai_operator`, `fdai_executor`, and the other service roles while some DSN secrets still authenticated as the admin principal. All five service modules now set PostgreSQL `PGOPTIONS=-c role=<declared role>` so readiness and grants evaluate the intended `current_user`. |
| 2026-08-09 | IS-09 | Historical rollback provenance | Round 34 | The privileged workflow guard required a historical image source to contain byte-identical deployment controls, which made any control hardening permanently block N-1 rollback. Historical artifact revisions now require protected-main ancestry and attestation while the executing workflow and controls remain pinned to current protected `main`. |
| 2026-08-09 | IS-09 | Current deployment source | Round 35 | Live preflight found that `commit_sha` selected both an image revision and historical Terraform, which could silently remove later role and recovery hardening during rollback. The value now binds only immutable image provenance; Terraform roots, migrations, legacy state operations, and peer capture all use current protected `main`. The canceled Operator run stopped during backend validation, and every mutation step was skipped. |
| 2026-08-09 | IS-09 | Complete plan staleness fence | Round 36 | A migration dependency fix landed after successful plans, but apply provenance compared only the workflow and helper scripts. Exact apply now rejects changes to the workflow, deployment helpers, all service Terraform roots and shared modules, service migrations, root project dependencies, or the semantic `uv.lock` graph. A release-only root version change does not invalidate an otherwise identical plan. The affected plans were discarded before apply. |
| 2026-08-09 | IS-09 | Initial migration adoption | Round 37 | Core apply run `31281314437` failed before snapshot or Terraform mutation because the service migration baseline was not stamped. Initial cutover now observes the exact legacy head and owned-schema fingerprint, persists adoption and schema evidence with a commit-pinned rollback reference, idempotently stamps only the exact baseline, and then upgrades the service branch. Standard applies never create a baseline. |
| 2026-08-09 | IS-09 | Adoption evidence schema parity | Round 38 | The public adoption-evidence schema still required 79 legacy revisions while every validated adoption manifest required the canonical 81. The schema now matches the live inventory, and a regression test derives both the required head and revision count from the canonical migration graph. |
| 2026-08-09 | IS-09 | Adoption retry and evidence durability | Round 39 | An interrupted initial cutover could upgrade the service migration branch and then fail later, after which retry regenerated baseline evidence against the evolved schema and blocked itself. Prepare and stamp now no-op only when the exact service lineage contains the baseline, reject every other existing lineage, and retain portable adoption plus schema evidence for 90 days even when a later migration step fails. |
| 2026-08-09 | IS-09 | Legacy-head adoption prerequisite | Round 40 | Core apply run `31284637886` failed before snapshot or Terraform mutation because the live legacy lineage was at `20260806_0077` while adoption requires `20260808_0079`. Initial cutover now advances the legacy Alembic lineage through the additive ontology-direction migrations before observing schema evidence, stamping the service baseline, and upgrading the service branch. Legacy migration files and `alembic.ini` are also exact plan/apply provenance inputs. |
| 2026-08-09 | IS-09 | Legacy migration working directory | Round 41 | Core apply run `31286708624` failed before snapshot or Terraform mutation because Alembic resolved the relative `script_location` outside the protected checkout. The legacy upgrade now runs in a subshell rooted at the exact protected controls checkout, so both `alembic.ini` and its tracked migration directory resolve from the same sealed source. |
| 2026-08-09 | IS-09 | Release-safe plan provenance | Round 42 | Automatic release commits changed only root package versions and repeatedly invalidated protected plans even though dependencies and deployment controls were unchanged. Apply now compares strict controls byte-for-byte and compares `pyproject.toml` plus `uv.lock` semantically after removing only the root FDAI release version. Dependency, lock graph, migration, workflow, helper, or Terraform changes still invalidate the plan. |
| 2026-08-09 | IS-09 | Service migration revision capacity | Round 43 | Core apply run `31294369918` reached the adopted service baseline, then failed before Terraform mutation because Alembic created the service version column at 32 characters while the next branch revision id was longer. Baseline stamping and every service upgrade now widen only the service-owned version column to 128 characters before writing branch history; the legacy Alembic table remains unchanged. |
| 2026-08-09 | IS-09 | Bounded slow revision readiness | Round 44 | Core apply run `31295906457` completed migration and Terraform apply, but the new digest-pinned revision needed more than the old nominal three-minute polling window. It later reported healthy, after automatic rollback had already restored and verified the prior image. Post-apply health now waits up to the existing 900-second deployment proof budget before rollback; an unhealthy or inactive revision still fails closed. |
| 2026-08-09 | IS-09 | No-ingress revision activation | Round 45 | Core apply run `31297621282` waited the full 900-second budget, but the new revision stayed healthy, stopped, and inactive with zero replicas because the internal no-ingress service had no traffic switch to activate it. Verification now requires the latest revision to differ from the snapshot and run the exact protected image before issuing one bounded Container Apps revision activation, then continues the same health and rollback checks. |
| 2026-08-09 | IS-09 | Core runtime database role | Round 46 | Activation-aware Core run `31299720389` started the exact image, but Log Analytics showed repeated exit code 1 because PostgreSQL role `fdai_core` did not exist. The Core migration branch now creates that non-login role and grants it only the 34 Core-owned tables plus the audit sequence; schema-wide and default privileges remain prohibited. |
| 2026-08-09 | IS-09 | Notification dependency degradation | Round 47 | Core-role run `31301828821` passed database startup, then Log Analytics showed that a missing A2 operational-alert channel aborted the complete Core process. The runtime now reports the unavailable route and keeps unrelated read, deny, queue, and shadow paths available; any action that requires that notification route remains without a usable delivery channel and cannot claim delivery. |
| 2026-08-09 | IS-09 | Complete container catalog selection | Round 48 | Corrected-image Core run `31311862255` passed role and notification startup, then Log Analytics showed that catalog discovery selected an incomplete virtual-environment `rule-catalog` and could not find the chaos scenario schema. Runtime catalog resolution now checks the complete `/app/rule-catalog` payload before package-parent development fallbacks, and symptom-index startup receives that resolved chaos catalog explicitly instead of using an import-time default. |
| 2026-08-09 | IS-09 | Provisioned startup probe topic | Round 49 | Catalog-corrected Core run `31316016509` reached the health server but remained not ready because it used the primary bootstrap endpoint while the dedicated `runtime.startup.probe` entity belongs to the operational namespace. Reusing the full primary namespace was tested as a bounded intermediate correction and did not establish a successful round-trip. |
| 2026-08-10 | IS-09 | Startup probe consumer readiness | Round 51 | Live Core logs showed each unique Event Hubs consumer group needed about three seconds to join, while the independent service omitted the configured settle budget and published after the runtime's 0.5-second default. The consumer then started at the latest offset after the synthetic record and the round trip timed out. The service now injects a 12-second settle budget, a 30-second probe deadline, and a 75-second phase deadline with ordering validation and retry headroom; the probe still fails closed when no exact round trip is observed. |
| 2026-08-09 | IS-09 | Operational startup probe binding | Round 50 | Canonical Core apply `31318043097` proved that sharing the primary governed-ingress topic leaves the synthetic consumer timing out and correctly triggers automatic rollback. The independent Core contract now receives the existing operational bootstrap endpoint and dedicated startup topic, preserving synthetic scope, identity isolation, and both namespace entity limits. |
| 2026-08-09 | IS-09 | No-ingress health evidence | Round 51 | The same apply exposed that Azure reports no `healthState` for the internal no-ingress Core app. Health and rollback verification now accept an absent state only when ingress is disabled and the exact revision is active, `Running`, and has at least one replica; ingress-enabled apps still require `Healthy`. |
| 2026-08-09 | IS-09 | Manifest context sanitization | Round 52 | Final-evidence review found that deployment-context rejection covered the remote aggregate but not its independent-service manifest input. Validation now applies the same recursive identifier, endpoint, and deployment-key rejection to both inputs before reading release or distribution fields. |
| 2026-08-09 | IS-09 | Serial transition windows | Round 53 | Temporal critique found that global serialization covered apply windows but not protected plans, and phase ordering did not explicitly require every rollback before the first restore. The verifier now rejects every overlapping plan/apply window and requires complete initial, rollback, and restore phase joins. |
| 2026-08-10 | IS-09 | Canonical N source binding | Round 54 | Supply-chain critique found that N-1 was bound to its manifest source while N accepted any source revision whose workflow head matched itself. The transition manifest now records the exact N source, and final evidence rejects any N release, image set, or stage chain that is not rooted in that revision. |
| 2026-08-10 | IS-09 | Closed local evidence schema | Round 55 | Evidence-boundary critique found that local transition services and artifacts were spot-checked but could carry unrecognized fields. The checker now requires exact top-level, service, and artifact key sets before accepting local N -> N-1 -> N evidence. |
| 2026-08-10 | IS-09 | Complete remote count join | Round 56 | Program-final critique found that the integration gate rechecked the two 5/5 targets but relied on the nested verifier for the 15 plans, 15 applies, and 30 peer receipts. The completion join now independently requires all five derived counts before loading live compatibility evidence. |
| 2026-08-10 | IS-09 | Exact document-service identity selection | Round 57 | Ingestion API run `31348846570` reached the new revision but crash-looped because Azure SDK clients used an unqualified Managed Identity credential even though the Container App declared an exact user-assigned client id. The API and Worker now require `FDAI_MI_CLIENT_ID` and construct every Azure adapter credential with that exact client id; missing identity selection fails before provider probes. |
| 2026-08-10 | IS-09 | Corrected canonical N image source | Round 58 | Supply-chain run `31349808536` successfully built, scanned, and attested all five images from the identity-corrected source. The machine transition contract now pins that source as N, so subsequent plans, restores, and final evidence cannot mix the prior crash-looping document images with corrected peers. |
| 2026-08-10 | IS-09 | Key Vault secret normalization guard | Round 59 | A post-cutover Operator plan exposed AzureRM refresh drift only at an empty or omitted `secret[*].value` beside an unchanged Key Vault reference. The protected plan guard now accepts only that exact provider normalization shape; a non-empty value, changed secret metadata, or any additional drift remains blocked. |
| 2026-08-10 | IS-09 | Encoded context rejection | Round 60 | Customer-agnostic evidence review found that percent-encoded Azure paths and compact GUID values could bypass literal identifier checks. Validation now performs bounded URL decoding and rejects exact compact GUID values before reading evidence fields. |
| 2026-08-10 | IS-09 | Exact remote manifest schema | Round 61 | Manifest-shape review found that the remote verifier relied on the outer checker for canonical transition keys and service coverage. The verifier now independently requires the exact transition schema and all five unique canonical service declarations. |
| 2026-08-10 | IS-09 | Completion dependency join | Round 62 | Work-package review found that the program-final path checked remote completion but did not independently join both IS-09 dependencies. IS-09 completion now requires IS-07 and IS-08 to remain completed. |

| 2026-08-10 | IS-09 | Trusted GitHub evidence binding | Round 63 | Final-proof critique found that internally consistent run ids, timestamps, artifact digests, and peer status remained self-asserted in tracked JSON. A dedicated read-only workflow now verifies every run against the GitHub API, downloads and checks each plan metadata and peer receipt artifact, rechecks deployment-input equivalence and image attestations, and signs the aggregate. Program-final completion requires the portable bundle to verify against that exact signer and source revision. |
| 2026-08-10 | IS-09 | Recovery revision metadata guard | Round 64 | A verified Core rollback changed Azure's computed latest revision name and revision suffix outside Terraform state, so the next standard plan was blocked despite unchanged runtime and authority fields. The guard now accepts only those two computed identifiers; any container, identity, secret, platform, or authority drift remains ineligible. |
| 2026-08-10 | IS-09 | Observable sidecar contract normalization | Round 65 | Worker apply `31352359688` deployed the exact reviewed image and healthy revision, but post-apply verification compared Terraform container fields such as empty `args`, `env`, and `volume_mounts` plus `ephemeral_storage` with the Azure Resource Manager revision shape, which omits those defaults and nests CPU and memory under `resources`. The sealed sidecar digest now covers the exact ARM-observable name, CPU, and memory contract; immutable image and probe digests remain separate, while the reviewed Terraform plan still guards non-observable fields. Unknown or non-empty unsupported runtime fields remain fail-closed. |
| 2026-08-10 | IS-09 | Adoption and compatibility-proof separation | Round 66 | Evidence review found that the positional `initial` N stage was incorrectly required to use the one-time `initial-cutover` deployment mode. One-time state and schema adoption is a preparatory service transition and cannot be replayed for each corrected image source. The final remote N -> N-1 -> N compatibility proof now starts only after all five services are adopted and requires standard protected plans for every stage, preventing repeated adoption while preserving fresh revision, rollback, and peer-isolation evidence. |
| 2026-08-10 | IS-09 | Durable remote adoption prerequisite | Round 67 | Program-final review found that one-time adoption evidence remained only in 90-day workflow artifacts and was not joined to the final attested aggregate. The aggregate now records all five adoption runs, artifact digests, observed legacy head and revision count, schema fingerprints, owned-table counts, verification times, and commit-pinned rollback references. The GitHub binder verifies each run, successful migration and artifact-upload steps, API artifact digest, and both downloaded JSON records before final attestation. A failed later health or peer check does not erase a completed adoption, but a missing or failed adoption step blocks closure. |
| 2026-08-10 | IS-09 | Genuine kind-specific live observations | Round 68 | Safety critique found that the live-evidence builder relabeled generic transition metadata as seven `observed=true` kinds. Successful applies now seal a separate artifact only after image attestation, service migration, exact health and identity verification, and four-peer isolation succeed. Health, identity, image, state-offset, schema, source, and topology records carry distinct evidence; the final aggregate stores their exact content and artifact digest, and the GitHub binder checks the successful steps plus downloaded artifact before attestation. The builder only copies those observed records and rejects missing, relabeled, or `observed=false` content. |
| 2026-08-10 | IS-09 | Deterministic live compatibility binding | Round 67 | Completion-path review found that schema-valid live receipts and observation manifests could be authored independently of the trusted remote aggregate. The program-final checker now derives all ten migration/rollback receipts and thirty-five observation records from exact rollback/restore run, plan, context, peer-receipt, source, and serial peer-version coordinates, then requires byte-equivalent JSON values before compatibility validation. Self-asserted live records can no longer close IS-09. |
| 2026-08-10 | IS-09 | Fresh protected revision per plan | Round 68 | Core apply `31353853013` proved that an externally verified rollback can leave Terraform configuration at N while Azure's latest active revision remains the restored image. A fresh plan then applied zero changes and health verification correctly rejected the old image. The shared Container App module now seals a bounded plan-time revision suffix into every saved plan, and the guard permits only that syntax beside the exact image change. Every protected apply therefore creates a newly verifiable revision without weakening container, identity, secret, platform, or authority checks. |
| 2026-08-10 | IS-09 | Bounded direct peer-state capture | Round 69 | Remote operability review found that each evidence run initialized four full Terraform peer roots twice merely to read isolated backend state, making the 30-run serial proof vulnerable to multi-hour provider and backend delays. Peer capture now downloads each exact allowlisted backend blob through Azure CLI with the already authenticated runner identity and a 60-second stop condition. The existing canonical state projection and before/after digest verifier remain unchanged. |
| 2026-08-10 | IS-09 | Split adoption observation and completion | Round 70 | Adoption replay review found that Core's durable schema observation was uploaded before a later migration failure, while a subsequent protected run completed the same migration but no longer emitted the one-time artifact. Replaying `initial-cutover` after adoption is correctly blocked. Remote evidence now binds an exact artifact run and an exact later completion run separately, verifies both against GitHub workflow steps, and accepts only a protected-main migration success paired with the original immutable schema and rollback record. |
| 2026-08-10 | IS-09 | Split adoption controls equivalence | Round 71 | Follow-up critique found that the split completion and artifact runs were each bound to GitHub but were not compared with the aggregate's deployment controls. The attestation verifier now requires the completion workflow head, artifact workflow head, and artifact rollback-reference controls commit to remain deployment-input-equivalent to the aggregate controls. This permits release-only commits while rejecting adoption proof assembled across materially different migration, workflow, infrastructure, or dependency controls. |
| 2026-08-10 | IS-09 | Historical adoption ancestry correction | Round 72 | Executable review showed that requiring final-control equivalence would reject valid one-time adoptions precisely because later rollout hardening changed deployment inputs. Adoption evidence now requires all three cited revisions to be ancestors of the final protected-main controls commit instead. Exact GitHub run, successful step, artifact digest, schema fingerprint, and rollback-reference bindings remain mandatory; only the false claim that historical and final controls are equivalent is removed. Final transition plans still require deployment-input equivalence. |
| 2026-08-10 | IS-09 | Observable sidecar probe normalization | Round 73 | Worker apply `31361034521` reached a healthy N revision, but verification hashed Terraform provider defaults such as empty headers and paths plus zero delays while Azure Resource Manager omits those defaults. Plan sealing now removes only the exact ARM-omitted default values and rejects unknown probe fields before hashing. Non-default thresholds, delays, intervals, timeout, transport, and port remain sealed and must match the observed revision exactly. |

## Related documents

| To learn about | Read |
|----------------|------|
| Graduation, ownership, and rollback gates | [Service Graduation and Data Ownership](service-graduation-and-ownership.md) |
| Repository package boundaries | [Project Structure](project-structure.md) |
| Azure runtime and identity deployment | [Deploy and Onboard](../deployment/deploy-and-onboard.md) |
| Operating ontology release boundaries | [Operating Ontology Platform](operating-ontology-platform.md) |
| Operator package ownership | [Operator Console Module Map](../interfaces/operator-console-module-map.md) |
