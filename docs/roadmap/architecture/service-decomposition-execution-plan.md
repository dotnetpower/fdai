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
| Completed | 4 | Exit evidence and focused validation are recorded. |
| In progress | 3 | SD-01, SD-03, and SD-06 use persistent isolated worktrees. |
| Planned | 2 | Work has not started or an ownership handoff is pending. |
| Blocked | 1 | SD-07 waits for centralized validation receipts and a pushable remote commit before live dispatch. |

Last updated: 2026-08-07.

## Execution checklist

| Done | ID | Work package | Dependencies | Parallel lane | Exit evidence |
|------|----|--------------|--------------|---------------|---------------|
| [x] | SD-00 | Freeze the five-service topology, owners, contracts, writers, identities, baseline tests, and rollback units in canonical documents and machine manifests. | None | Serial | Reviewed topology and ownership records; baseline check receipt |
| [ ] | SD-01 | Decompose Operator route families into transport, application, projection, adapter, streaming, and persistence packages without changing JSON, SSE, authentication, or history behavior. | SD-00 | A | Frozen route contracts and package-boundary checks |
| [x] | SD-02 | Isolate Core composition, Thor execution, Saga audit intent and closure, and Vidar recovery behind explicit injected ports. | SD-00 | A | Authority regression and import-boundary receipts |
| [ ] | SD-03 | Harden the Ingestion API and Worker identities, database grants, claims, duplicate/reorder behavior, restart recovery, probes, and co-host rollback. | SD-00 | A | Role tests and a rollback rehearsal within 15 minutes |
| [x] | SD-04 | Add canonical ontology release distribution, exact reference pinning, N/N-1 compatibility, projection-writer ownership, mismatch rejection, replay, and rollback. | SD-00 | B | Cross-service ontology compatibility and semantic regression receipts |
| [x] | SD-05 | Build the Rego knowledge path from canonical AST analysis through catalog build, semantic validation, ontology/vector generations, incremental parity, exact applicability, evaluation, and governed feedback. | SD-04 | B | Query-to-exact-Rego contract tests and generation rollback receipt |
| [ ] | SD-06 | Add canonical Change lineage, provider adapters, decision trace, delivery/outcome joins, resilience coverage, candidate-only learning, and the read-only Operator projection. | SD-02, SD-04, SD-05 | C | Replayable lineage and authority non-escalation receipts |
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
| SD-01 capability routes | Persistent worker at `/home/moonchoi/dev/fdai-worktrees/sd01-capability-routes` | `chat_agent_delegate.py`, `chat_skills.py`, `chat_configuration_drift.py`, `chat_web_search.py`, `chat_capability_registry.py`, `chat_topology_intent.py`, destination application packages, matching tests, and module-map updates | Capability handoff preserves read-only provider boundaries and deterministic intent precedence with zero application-to-route imports |
| SD-03 effective access and rollback | Existing SD-03 isolated session at `/home/moonchoi/dev/fdai-worktrees/sd03-effective-access` | Ingestion runtime, ingestion-specific Terraform, access probe, and matching tests | Effective-access proof and rollback evidence handed to the integration owner |
| SD-06 canonical Change lineage | Persistent worker at `/home/moonchoi/dev/fdai-worktrees/sd06-change-lineage` | `src/fdai/core/change_lineage/**` and `tests/core/change_lineage/**` only | Immutable replay-stable Change -> assessment -> decision -> action -> outcome lineage passes focused tests and proves zero execution or promotion authority; shared contracts, agents, composition, Operator API, ingestion, infra, and this plan remain read-only |
| SD-07 serial finish | Integration owner on `main`; prior worker retained at `/home/moonchoi/dev/fdai-worktrees/sd07-shadow-executor` | `infra/modules/isolated-executor/**`; SD-07-only blocks in `infra/main.tf`, `infra/variables.tf`, and `infra/outputs.tf`; `deploy_isolated_executor` blocks in `.github/workflows/deploy-dev.yml`; matching Terraform/workflow tests; production composition and paired docs | Shadow deployment evidence recorded without effect authority; avoid ingestion modules and every SD-03-owned Terraform hunk; the released worker is read-only |
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
| 2026-08-07 | SD-01 | In progress | `f220eb06f`, `2739e2be6`, `7c18ed513`, `0ab723835`, `64955ba87` | Stream metrics, terminal projections, post-generation orchestration, application capability ownership, and authenticated request preparation moved behind explicit application or projection packages. The latest request-preparation union passed 192 tests, the application/projection reverse-import count is zero, and the scoped boundary gate is green. JSON, SSE, authentication, cancellation, and history wire behavior remain route-owned. Remaining route families and final compatibility classification keep SD-01 open. |
| 2026-08-07 | SD-01 | In progress | `2111617b8` | Trajectory detail, deterministic screen answers, redacted model tracing, and response resource context moved to pure conversation projections without compatibility shims. The main integration union passed 258 tests, application/projection-to-route imports remained zero, and the scoped boundary and translation gates passed. |
| 2026-08-07 | SD-01 | In progress | `bbb5ac552` | Answer planning, terminal quality review, content-policy recovery, and busy-input steer or interrupt coordination moved to explicit application packages with no compatibility shims. The main lifecycle union passed 131 tests, application/projection-to-route imports remained zero, and chat route files fell from 25 to 17. |
| 2026-08-07 | Parallel sessions | In progress | Persistent worktree migration | Active SD-03 and retained SD-07 workers moved to `/home/moonchoi/dev/fdai-worktrees/`; all new workers use that persistent root. Temporary worktree paths are no longer valid reservations. |
| 2026-08-07 | SD-07 | In progress | Start `03f6ef265` on `work/sd07-shadow-executor` | Command/receipt transport and durable shadow-attempt mechanics started in `/tmp/fdai-sd07`. Effect authority, production composition, pantheon roles, and identity cutover remain reserved for serial integration. |
| 2026-08-07 | SD-07 | In progress | `3b84ee15a`, `800eee04b` | Versioned command/receipt schemas, durable duplicate/reorder/restart/deadline closure, poison-record DLQ, at-least-once receipt publication, supervised health, and no-effect telemetry passed a 55-test focused union on `main`. Logical-target lock evidence, production composition, workload identity, and Container App deployment remain open; effect authority stays unavailable until SD-08. |
| 2026-08-07 | SD-07 | In progress | `9ff088aec` | The existing `ResourceLock` seam now serializes same-target shadow commands while different targets overlap, exact target identity is used, and handler failure releases the lock. The 59-test focused union passed on the worker and the lock handoff is integrated. Production composition, workload identity, Container App deployment, and live shadow smoke remain open. |
| 2026-08-07 | SD-07 | In progress | Serial start `b813a227f` | The packaged shadow entry point and explicit deployed-process marker are integrated. Serial IaC now owns only the reserved isolated-Executor module and SD-07-specific root blocks; SD-03 ingestion Terraform remains untouched. |
| 2026-08-07 | SD-07 | In progress | `0c52be49d` | Opt-in internal Container App IaC, a dedicated no-effect UAMI, operational command/DLQ/receipt entities, Key Vault-backed durable state, distributed lock DSN, and internal probes are implemented. Root Terraform validate passed, the module shadow-boundary test passed 1/1, and authority tests passed 3/3 with no SD-03 path changes. Live runner plan/apply, exact-topology smoke, and timed rollback remain open. |
| 2026-08-07 | SD-07 | Blocked | `f3eb25593`; live gate | The private-runner workflow exposes `deploy_isolated_executor`, preserves plan-only default and design-mocks exclusivity, and verifies the app revision after apply; 24 workflow tests passed. The pre-status measurement recorded 575 pending commits in the shared queue and local `main` 50 commits ahead of `origin/main`, so live dispatch waits for the Integration Validator. The next disconfirming check is an exact validation receipt for the SD-07 commits followed by a successful push; only then run the plan-only workflow. |

## Related documents

| To learn about | Read |
|----------------|------|
| Graduation, ownership, and rollback gates | [Service Graduation and Data Ownership](service-graduation-and-ownership.md) |
| Repository package boundaries | [Project Structure](project-structure.md) |
| Azure runtime and identity deployment | [Deploy and Onboard](../deployment/deploy-and-onboard.md) |
| Operating ontology release boundaries | [Operating Ontology Platform](operating-ontology-platform.md) |
| Operator package ownership | [Operator Console Module Map](../interfaces/operator-console-module-map.md) |
