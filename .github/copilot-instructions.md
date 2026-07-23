# FDAI - Copilot Instructions

Autonomous cloud operations control plane - an **AIOps** approach whose initial verticals
are **Resilience** (disaster recovery and chaos/resilience testing), **Change Safety** (safe
change and drift remediation), and **Cost Governance** (FinOps). The same architecture
applies to other AIOps domains (posture management, SRE/SLO, etc.), which are future scope.
Goal: minimize human intervention by resolving most events deterministically and using LLMs
only for the residual ambiguous cases.

This file is the small always-on contract. Detailed rules are loaded through
[`design-routes.json`](../scripts/lib/design-routes.json). Before an edit, read every
`must_read` document selected by all matching routes. The workspace hook blocks edits when
that context is missing or stale. A more specific instruction wins a conflict.

## Core Principles (MUST)

1. **Agent-driven:** Every capability belongs to an independently and concurrently runnable agent.
   Machine collaboration uses schema-validated event-bus pub/sub only; direct agent calls, RPC,
   implementation imports, and shared mutable workflow state are prohibited.
2. **Deterministic-first:** Resolve repeatable decisions with deterministic rules. Adaptive T2
   decisions require mixed-model, verifier, grounding, risk, and approval gates.
3. **Safe autonomy:** Every autonomous action requires a stop condition, rollback, blast-radius
   limit, dry-run, per-resource lock, idempotency key, and audit record. New capabilities start in
   shadow and change mode only through the authoritative promotion registry; runtime, environment,
   and fork status never promote or demote them.
4. **Evidence-governed:** Every decision and action is attributable, observable, and replayable.
   Insufficient evidence results in abstention or escalation. Human App Roles and the executor
   workload identity stay distinct; self-approval is prohibited.
5. **Secure boundaries:** Keep the repository customer-agnostic and free of secrets, tenant values,
   endpoints, and customer identifiers. Azure is the implemented target, provider contracts stay
   neutral, and non-Azure adapters require explicit approval.

## Agent Workflow (MUST)

1. Read every route-selected design document before editing.
2. Make the smallest coherent change, update affected contracts and docs, and never hand-edit
   generated runtime artifacts.
3. Run the narrowest executable check that can falsify the change. Follow the diff-scoped and
   parallel-worktree rules in
   [coding-conventions.instructions.md](instructions/coding-conventions.instructions.md).
4. Commit each validated user-requested change before reporting completion unless the user says
   not to commit. Stage only task-owned files and hunks; never commit failed or incomplete work.

## Issue Lifecycle (MUST)

- Every new issue includes explicit, observable **Exit criteria** as a checkbox list.
- After working on or reviewing an issue, add an English comment with evidence and residual work.
- When every exit criterion is satisfied, add the `completed` label. Keep the issue open while
  any residual work remains; close it only when no residual work remains.
- For another author's issue, add `review-needed` and wait for confirmation before closing. A
  reopened issue loses `completed` until its exit criteria are satisfied again.

English and Korean are both allowed in prose. Identifiers, paths, branches, punctuation, and
machine-record keys stay ASCII/English as defined by
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
