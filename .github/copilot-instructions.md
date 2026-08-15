# FDAI - Copilot Instructions

Autonomous cloud operations control plane - an **AIOps** approach whose initial verticals
are **Resilience** (disaster recovery and chaos/resilience testing), **Change Safety** (safe
change, ARB, and drift remediation), and **Cost Governance** (FinOps). SRE/SLO is the operating
model across those verticals; additional AIOps domains such as posture management are future scope.
Goal: minimize human intervention by resolving most events deterministically and using LLMs
only for the residual ambiguous cases.

The [FDAI Constitution](../docs/roadmap/architecture/fdai-constitution.md) is the highest design
authority. This file is its short always-on execution summary; scoped instructions and detailed
designs may refine the constitution but never override it.

This file is the small always-on contract. Detailed rules are loaded through
[`design-routes.json`](../scripts/lib/design-routes.json). Resolve the route-selected context once
per task before changing behavior. The workspace hook hard-blocks only framework-surface,
constitutional, and design-gate edits when required context is missing or stale; ordinary edits
remain unblocked. Pre-commit checks staged design-document impact, and pre-push validates the
committed snapshot. Request each route-selected context document with a direct `read_file` call;
current VS Code does not invoke workspace hooks for reads nested in parallel wrappers. The single
pre-tool hook records only requested design-context paths; no post-tool hook receives or logs tool
response bodies. A more specific instruction wins a conflict only within the Constitution's bounds;
the Constitution always prevails.

## Core Principles (MUST)

1. **Agent-driven:** Every capability belongs to an independently and concurrently runnable agent.
   Authority-bearing collaboration and state transitions use schema-validated event-bus pub/sub only; direct agent calls, RPC,
   implementation imports, and shared mutable workflow state are prohibited.
2. **Deterministic-first:** Resolve repeatable decisions with deterministic rules. Adaptive T2
   decisions require mixed-model, verifier, grounding, risk, and approval gates.
3. **Safe autonomy:** Every autonomous state-changing action requires all seven safeguards: a stop condition,
   rollback, blast-radius limit, dry-run, logical-target lock, idempotency key, and two-phase audit record. New capabilities start in
   shadow and change mode only through the authoritative promotion registry; runtime, environment,
   and fork status never promote or demote them.
4. **Evidence-governed:** Every decision and action is attributable, observable, and replayable.
   Insufficient evidence results in abstention or escalation. High-impact execution requires either
   current human approval or valid standing human authorization; silence alone never grants authority.
   Human App Roles and the executor workload identity stay distinct; self-approval is prohibited.
5. **Secure boundaries:** Keep the repository customer-agnostic and free of secrets, tenant values,
   endpoints, and customer identifiers. Azure is the implemented target, provider contracts stay
   neutral, and non-Azure adapters require explicit approval.

## Agent Workflow (MUST)

1. Classify the request before implementation. A design pass is required when the change affects
   architecture, public contracts, security or authority boundaries, cross-subsystem behavior,
   persistent data flow, or presents multiple viable approaches with material tradeoffs. A small
   local fix, mechanical edit, or implementation of an already-approved design does not require a
   new design artifact.
2. For design-required work, draft the smallest sufficient design, critique it against the user
   requirements, route-selected documents, simplicity, failure modes, operability, and validation,
   then revise the design before implementation. Resolve material critique findings in the revised
   design; do not preserve rejected alternatives as implementation work.
3. For any task that needs an implementation plan, derive it from the revised design when one is
   required. Identify dependencies, shared files or mutable state, and validation joins; mark
   independent work explicitly and execute it in parallel with available parallel tools, subagents,
   or isolated worktrees. Keep dependent work sequential, and do not parallelize tasks that can
   race on the same files, state, authority decision, or generated artifact. Every parallel branch
   must have a bounded output and an explicit merge or verification point.
4. Before a high-risk framework-surface, constitutional, or design-gate edit, read every
   route-selected design document. For ordinary changes, resolve the controlling route context
   once per task before changing behavior; do not serialize work through unrelated reference docs.
5. Make the smallest coherent change, update affected contracts and docs, and never hand-edit
   generated runtime artifacts.
6. Worker sessions run only the narrowest executable check that can falsify their change. They
   MUST NOT run repository-wide checks, unscoped tests, or direct `verify.sh --fast` / `--all`.
   A session MUST NOT delegate validation of a dirty worktree to another execution session because
   that process can stage, restore, or discard task-owned changes. Delegated validation requires a
   clean committed snapshot in an isolated worktree; validate dirty task-owned paths directly in
   the owning session until they are committed.
   Follow the diff-scoped and parallel-worktree rules in
   [coding-conventions.instructions.md](instructions/coding-conventions.instructions.md).
7. Every commit is automatically registered in the Git-common-dir validation queue and wakes a
   low-priority background validator. The dedicated `Integration Validator` session is the manual
   status and fallback-drain surface; it runs `make validation-run` once only when pending work is
   not already active. Use `make validation-all` only at an explicit merge or release boundary.
   Normal pushes check receipts without waiting and are blocked until every outgoing commit has a
   centralized validation receipt. When a session must wait for a receipt or another filesystem
   completion artifact, it MUST use an event-driven watcher such as `inotifywait` instead of timed
   polling or repeated status checks. Start the watcher before rechecking whether the artifact
   already exists to avoid a check-to-watch race; if event watching is unavailable, use one bounded
   fallback check and report the pending state rather than polling.
8. Commit each focused-check-passing user-requested change before reporting completion unless the user says
   not to commit. Stage only task-owned files and hunks; never commit failed or incomplete work.
9. Treat slow network-dependent work as a post-validation phase. Do not watch or rerun GitHub
   Actions, deploy or provision Azure, or build or push container images while implementation or
   focused tests are incomplete. Commit the finished slice and obtain its centralized validation
   receipt first. Lightweight read-only identity and context checks may run earlier; they must not
   become long polling or remote troubleshooting.
10. Prevent interactive sensitive-input prompts before starting a command. Prefer an existing
   authenticated session, workload identity, credential-store reference, documented
   non-interactive mode, or provider-hosted browser/device authorization flow, and use a
   non-secret readiness check first. Passwords, passphrases, tokens, API keys, MFA or recovery
   codes, connection strings, private keys, and secret values MUST NOT cross chat,
   `vscode_askQuestions`, tool arguments, `send_to_terminal`, command lines, generated files,
   logs, or task output. Do not start `sudo`, password login, or another known prompting command
   through an agent tool. If a running terminal still requires sensitive input, tell the user to
   enter it directly in that terminal, preserve the exact continuation point, and treat the pause
   as an authentication handoff rather than task failure or completion. After confirmation,
   verify only non-secret authentication state and resume without repeating completed work or
   requesting the value again. Never weaken authentication, authorization, certificate checks,
   or another security control to avoid the prompt.
11. Bound every wait and every long-running command. Before starting work that can exceed a few
   minutes, declare an explicit budget, a per-stage deadline, and a no-progress deadline, and emit
   a progress signal as each unit completes. One long total timeout MUST NOT stand in for a
   per-stage deadline or a progress signal, because it makes a stalled run indistinguishable from a
   slow one. Make long work resumable so an interruption does not discard completed results, and
   prefer many short verifiable steps over one long opaque step. Batch related fixes into one
   verification round instead of repeating a full live gate after each small change, and run
   full-cohort or release-scale checks only at an explicit release or evidence boundary.

## Issue Lifecycle (MUST)

- Every new issue includes explicit, observable **Exit criteria** as a checkbox list.
- Read-only analysis and reproduction do not require an issue. Reuse or create one before the
   first task-owned commit or external state change.
- Use `python3 scripts/automation/project-board.py start <issue-number>` when GitHub is available.
   Project updates are best-effort and MUST NOT block local implementation, focused validation,
   commits, pushes, or centralized validation. Report deferred synchronization and retry later.
- Issue content, labels, evidence comments, and open or closed state are authoritative. Project
   fields are a derived execution view. Assignment records accountability; only `In progress`
   records active work.
- The WIP limit of two applies to active `Story` and `Bug` outcomes per maintainer. Child `Task`
   items do not consume another outcome slot and the board never replaces edit reservations.
- After working on or reviewing an issue, add an English comment with evidence and residual work.
- When every exit criterion is satisfied, add the `completed` label. Keep the issue open while
  any residual work remains; close it only when no residual work remains.
- For another author's issue, add `review-needed` and wait for confirmation before closing. A
  reopened issue loses `completed` until its exit criteria are satisfied again.

English is the canonical/default language, and Korean is a fully supported localization language.
Commit Korean prose as readable UTF-8, never as encoded escapes. Identifiers, paths, branches,
punctuation, and machine-record keys stay ASCII/English as defined by
[language.instructions.md](instructions/language.instructions.md). GitHub issues stay English.

## Routed Guides

- [architecture.instructions.md](instructions/architecture.instructions.md) - trust routing,
  control loop, action ontology, and safety invariants.
- [app-shape.instructions.md](instructions/app-shape.instructions.md) - topology, local/deployed
  parity, and console security boundaries.
- [coding-conventions.instructions.md](instructions/coding-conventions.instructions.md) - code,
  tests, docs-first/docs-after, and provider boundaries.
- [generic-scope.instructions.md](instructions/generic-scope.instructions.md) - generic upstream
  and downstream customization boundary.
- [agent-pantheon.instructions.md](instructions/agent-pantheon.instructions.md) - fixed agent roles.
- [documentation-style.instructions.md](instructions/documentation-style.instructions.md) and
  [language.instructions.md](instructions/language.instructions.md) - docs and localization.
- [ADR-0002](../docs/roadmap/architecture/decisions/0002-independent-runtime-axes.md) - independent
  runtime, environment, evidence, autonomy, identity, and fork axes.
