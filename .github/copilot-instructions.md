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
[`design-routes.json`](../scripts/lib/design-routes.json). Before an edit, read every
`must_read` document selected by all matching routes. The workspace hook blocks edits when
that context is missing or stale. The single pre-tool hook records existing repository files
requested through `read_file`; no post-tool hook receives or logs tool response bodies. A more
specific instruction wins a conflict only within the Constitution's bounds; the Constitution
always prevails.

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

1. Read every route-selected design document before editing.
2. Make the smallest coherent change, update affected contracts and docs, and never hand-edit
   generated runtime artifacts.
3. Worker sessions run only the narrowest executable check that can falsify their change. They
   MUST NOT run repository-wide checks, unscoped tests, or direct `verify.sh --fast` / `--all`.
   Follow the diff-scoped and parallel-worktree rules in
   [coding-conventions.instructions.md](instructions/coding-conventions.instructions.md).
4. Every commit is automatically registered in the Git-common-dir validation queue. The dedicated
   `Integration Validator` session runs `make validation-run` once per stable batch; use
   `make validation-all` only at an explicit merge or release boundary. Normal pushes are blocked
   until every outgoing commit has a centralized validation receipt.
5. Commit each focused-check-passing user-requested change before reporting completion unless the user says
   not to commit. Stage only task-owned files and hunks; never commit failed or incomplete work.

## Continuous Conversation Assurance Triggers (MUST)

Treat `대화개선`, `채팅개선`, `대화무한개선`, `채팅무한개선`, `conversation improvement`,
`chat improvement`, and `continuous conversation assurance` as requests to load the
`conversational-assurance` skill and start exactly one explicit bounded campaign. Use the persisted
SRE, ARB, Change Management, DR, Chaos, or Balanced focus; default to SRE when no focus is stored,
and update it when the operator names a different focus. One campaign may evaluate at most 20 new
questions and start at most 20 hardening attempts. These are per-campaign limits, not daily limits;
a later explicit trigger starts a new campaign with fresh limits.

Treat `대화개선 현황`, `채팅개선 현황`, and `conversation assurance status` as read-only status
requests. Do not restart the campaign or ask for focus. Report the campaign summary and a Markdown
table of the latest 20 question-and-answer evaluations.

Every cycle MUST measure answer appropriateness, terminal verification state, answer-type-specific
visualization, investigation and redacted execution detail, total latency, and per-phase
bottlenecks through the same Operator API stream used by the Console. Score exactly ten named
rubrics at 0 or 1 point each and report a total out of 10; the campaign pass threshold is 9/10.
Persist every redacted question, answer, rubric result, timing summary, and regression cohort in
ignored mode-`0600` ledgers. All prior and cohort questions participate in duplicate rejection. A
score below 9 starts or resumes an isolated Copilot hardening candidate immediately; the same
question and its paraphrase cohort are remeasured
until every item reaches at least 9/10 or the campaign hardening limit is reached. After focused
verification, the next bounded question cycle starts within the same explicit campaign until its
question limit is reached or a cycle cannot make progress. The loop remains A0/read-only, never
merges to `main`, never uses generated text as a command, and never grants approval or execution
authority.

Conversation assurance MUST NOT start from systemd, login, boot, a recurring timer, stale-activity
recovery, or any other implicit scheduler. Only an explicit campaign trigger may start work.
`.improve/STOP` remains the immediate local stop switch.

## Issue Lifecycle (MUST)

- Every new issue includes explicit, observable **Exit criteria** as a checkbox list.
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
