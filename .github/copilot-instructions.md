# FDAI - Copilot Instructions

FDAI is an autonomous cloud-operations control plane for Resilience, Change Safety, and Cost
Governance. SRE/SLO is the operating model. Resolve repeatable events deterministically and use
LLMs only for residual ambiguity.

The [FDAI Constitution](../docs/roadmap/architecture/fdai-constitution.md) is the highest design
authority; this file is its compact always-on execution contract. Scoped instructions and designs
may refine it, but the Constitution always prevails.

Load task-specific context through [`design-routes.json`](../scripts/lib/design-routes.json) before
changing behavior. Request each required document with a direct `read_file` call because nested
parallel reads are not recorded by the design-context hook. Pre-commit checks staged design impact;
pre-push validates the committed snapshot.

## FDAI Core Principles (MUST)

1. **Intent-grounded:** Interpret natural language as typed intent: goal, target, scope, time, and
   constraints. Ambiguity requires clarification or abstention. Language never grants authority.
2. **Ontology-grounded:** Ground every entity, state, relationship, evidence item, and action in
   the canonical operating ontology. The ontology validates meaning and never grants authority.
3. **Relationship- and time-aware:** Correlate topology and dependencies with time-bounded
   telemetry, traces, and changes. Preserve effective time, event time, recorded time, freshness,
   completeness, and provenance. Never equate correlation with causation.
4. **Deterministic-first:** Resolve repeatable decisions with rules and policies. Use T2 reasoning
   only for grounded, mixed-model, verifier-checked, risk-gated, and approval-gated residual
   ambiguity. `T0`, `T1`, and `T2` describe product runtime behavior.
   They do not authorize a coding session to invoke a live model unless explicitly requested for
   live validation.
5. **Agent-driven:** Assign every capability to an independently runnable accountable agent.
   Authority-bearing collaboration and state transitions use schema-validated event-bus pub/sub
   only, without direct agent calls or shared mutable workflow state.
6. **Evidence-governed:** Make every conclusion and action attributable, observable, explainable,
   and replayable. Insufficient, stale, incomplete, or conflicting evidence requires bounded
   recovery, abstention, denial, or escalation.
7. **Safely autonomous:** Execute state changes only with explicit current human approval or valid
   standing human authorization when required. Silence never grants authority, self-approval is
   prohibited, and human and executor identities remain distinct. Require all seven safeguards:
   stop condition, tested rollback, blast-radius limit, successful dry-run, logical-target lock,
   stable idempotency key, and two-phase audit. New capabilities start in shadow mode and change
   mode only through the authoritative promotion registry.
8. **Effect-verified:** Verify expected effects through an independent authoritative observation.
   Dispatch, broker acceptance, or an API success is not an operational success.
9. **Secure boundaries:** Keep the repository customer-agnostic and free of secrets, tenant values,
   endpoints, and customer identifiers. Azure is the implemented target, provider contracts remain
   neutral, and non-Azure adapters require explicit approval.

If any applicable principle cannot be satisfied, FDAI MUST NOT act. It MUST produce an explicit
unknown, no-op, denial, rollback, or human-review outcome with an audit record.

## Agent Workflow (MUST)

1. Classify the request first. Architecture, public contracts, authority, cross-subsystem behavior,
   persistent data flow, or material tradeoffs require a small design, critique, and revision before
   implementation. Local fixes and already-approved designs do not require a new design artifact.
2. Resolve route-selected context once per task. Read every required document directly before a
   high-risk edit. Make the smallest coherent change, update affected contracts and docs, never
   hand-edit generated artifacts, and keep the user's requested outcome ahead of incidental tooling.
3. Derive plans from the revised design. Parallelize only independent work with bounded outputs and
   an explicit merge or verification point; keep shared files, state, and authority decisions serial.
4. Run the narrowest executable check that can falsify the change. Worker sessions MUST NOT run
   repository-wide checks or `verify.sh --fast` / `--all` unless explicitly requested. A session
   MUST NOT delegate validation of a dirty worktree. Delegated validation requires a clean committed snapshot in an isolated worktree.
   CI owns integration validation for pushed SHAs, and
   `make validation-all` is reserved for explicit merge or release boundaries.
5. Do not commit by default. Commit only when explicitly requested or required by an invoked
   workflow or external operation. Git, hook, signing, or push failures MUST NOT interrupt unfinished implementation.
   Except for repository-owned generated workflows, every agent-authored commit MUST originate in the
   active local checkout after focused validation and diff review. Never create a remote-only commit.
   Push only when requested, then verify the remote ref resolves to the expected local commit.
6. Treat GitHub Actions, Azure operations, container publication, and other slow network work as a
   post-validation phase. Deployment and release target a pushed SHA with required CI and protected
   preflight; local validation receipts never grant authority.
7. Prevent sensitive-input prompts. Secrets MUST NOT cross chat, tools, command lines, generated
   files, logs, or task output. Use existing identity or provider-hosted authorization; if a running
   terminal requests a secret, the user enters it directly. Never weaken a security control.
8. Bound long work with total, per-stage, and no-progress deadlines plus progress signals. Live
   network, Azure, or model validation requires an explicit request. An unexpected `T2` fallback,
   HTTP `429`/`503`, provider timeout, or deadline expiry ends that attempt; capture bounded evidence
   and do not retry the same live request without a new hypothesis or explicit request.

## Local Development Efficiency (MUST)

- Use loopback Docker PostgreSQL, service-owned local DSNs, the active local environment, and local
  records first. Never use a remote database to explain locally reproduced state.
- Azure PostgreSQL access is deployment work and runs only through the protected workflow or an
  explicitly requested live validation after focused checks. Never source its DSN locally or copy
  database contents between venues ad hoc.
- Reuse a healthy local stack and `.fdai/local-*.env`. Measure VPN, DNS, route, endpoint,
  authorization, and application state independently before diagnosing private connectivity.

## Issue Lifecycle (MUST)

- Every new issue includes explicit, observable **Exit criteria** as a checkbox list.
- Read-only analysis and reproduction do not require an issue. Reuse or create one before the
  first task-owned commit or external state change. Use `project-board.py start <issue-number>`
  when GitHub is available; Project updates are best-effort and never block local work.
- Issue content, labels, evidence comments, and open or closed state are authoritative. Project
  fields are derived; only `In progress` records active work.
- The WIP limit of two applies to active `Story` and `Bug` outcomes per maintainer. Child `Task`
  items do not consume another slot, and the board never replaces edit reservations.
- After work or review, add an English evidence comment. Add `completed` only when every criterion
  is satisfied; residual work keeps the issue open. For another author's issue, add
  `review-needed` and wait for confirmation before closing.

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
