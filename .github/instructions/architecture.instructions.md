---
description: Architecture principles, trust routing, control loop, and rule catalog.
applyTo: "**"
---

# Architecture

This file defines the control-plane architecture. It complements the deployment topology in
[app-shape.instructions.md](app-shape.instructions.md), the code/safety rules in
[coding-conventions.instructions.md](coding-conventions.instructions.md), and the phased plan
under [docs/roadmap](../../docs/roadmap/README.md). All coverage, latency, and cost figures
below are **targets to validate against a measured baseline**
([goals-and-metrics.md](../../docs/roadmap/goals-and-metrics.md)), not guarantees; state no
multiplier without measuring baseline and treatment on the same scenario set.

## Design Principles

1. **Deterministic-first** - resolve every repeatable decision with rules, policies, and
   checklists. Reach for an LLM only after T0 and T1 cannot resolve the case.
2. **Confidence tiering** - route by a computed confidence so expensive inference stays a
   small minority of events (target ~5-10%; see Trust Routing).
3. **Risk-gated autonomy** - low-risk actions auto-execute; high-risk actions require
   human-in-the-loop (HIL) approval. Autonomy is never unconditional.
4. **Event-driven** - wake on events, scale to zero when idle. No constant polling.
5. **Policy, state, and audit as code** - policy-as-code (OPA/Rego), tracked state, and a full
   append-only audit log for every autonomous action.
6. **Living rules** - the rule catalog is continuously **collected, updated, and
   discovered**: automated agents scan upstream sources for new/changed controls, keep
   existing rules current, and propose novel candidates from operational signals
   (incidents, HIL patterns, shadow outcomes, override events). Every candidate - no matter
   how it was generated - MUST cite `provenance` and MUST pass the same quality gate
   (schema, mixed-model cross-check, verifier, regression, shadow) before it can enter the
   catalog. Candidates without grounded provenance are rejected.
7. **Human override on top** - humans retain a final control surface above the automated
   gate. An operator MAY narrow, downgrade, or disable an accepted rule via a scoped,
   policy-as-code override (see Human Override). Overrides never edit rule text and never
   suppress the audit record of the underlying finding; they are themselves audited and
   feed back into the discovery loop.
8. **Fail toward safety** - any failure, low confidence, or budget/rate overflow degrades to
   HIL, never to an ungated auto-action.

## Trust Routing (3-Tier)

Latency values are order-of-magnitude budgets, not SLAs. Coverage targets are approximate and
partition one event stream, so they must sum to ~100%; T0+T1 together target the ~85-90%
deterministic/lightweight share cited in
[goals-and-metrics.md](../../docs/roadmap/goals-and-metrics.md).

| Tier | Handles | Model use | Latency budget | Coverage target |
|------|---------|-----------|----------------|-----------------|
| **T0 deterministic** | policy eval, checklists, what-if (dry-run predicted effect), config drift, anomaly-threshold checks | none | ms-s | 70-80% |
| **T1 lightweight** | embedding similarity to past incidents, reuse of learned actions, root-cause correlation to prior resolved incidents, small-model classification of routine cases | embedding + small/cheap LLM | ~s | 15-20% |
| **T2 reasoning** | novel or ambiguous cases only, grounded root-cause reasoning | frontier LLMs (2+ distinct) | s-tens of s | 5-10% |

### Routing and Tier Boundaries

The trust router computes a per-event confidence and selects the lowest sufficient tier:

- **→ T0** when the normalized event maps to a rule/policy with a deterministic verdict.
- **→ T1** when no exact rule matches but similarity to a prior resolved incident clears a
  configured score threshold and a learned action exists.
- **→ T2** only when T0 and T1 abstain (no rule match; similarity below threshold; ambiguous).

Confidence inputs (rule match, similarity score, historical success rate) and their thresholds
are **configuration**, not hard-coded. Module names for these stages
(`event-ingest`, `trust-router`, `tiers/*`, `quality-gate`, `risk-gate`, `executor`, `audit`)
are fixed by [project-structure.md](../../docs/roadmap/project-structure.md).

## Control Loop

```text
event bus
  -> event-ingest (normalize + deduplicate + correlate)
  -> trust-router (confidence -> tier)
  -> T0 | T1 | (T2 -> quality-gate)
  -> risk-gate
       -> auto  -> executor -> delivery -> audit
       -> HIL   -> approval -> executor -> delivery -> audit   (reject/timeout -> no-op -> audit)
       -> abstain/deny -> no-op -> audit
```

T2 output is never routed straight to the risk gate; it must clear the quality gate first.
Every terminal path - including reject, HIL timeout, abstain, and deny - writes an audit entry.

### Detection Signals (correlation, anomaly, prediction, RCA)

Detection feeds the same loop; it is not a separate autonomy surface. `event-ingest` correlates
related events into one incident (deterministic keys first, T1 similarity for fuzzy grouping).
**Anomaly** and **predictive/forecast** detectors emit normalized findings that enter the trust
router like any event, and **root-cause analysis** is a first-class tier output (T0 direct cause,
T1 correlation to resolved incidents, T2 grounded reasoning). Detection stays deterministic-first,
ships in shadow mode, and a prediction or anomaly **never auto-acts on its own** - it raises a
finding the risk gate governs. Full design:
[observability-and-detection.md](../../docs/roadmap/observability-and-detection.md).

### Idempotency, Ordering, and Replay

- **Idempotency**: each event carries a stable key; processing is idempotent so at-least-once
  delivery and retries cannot double-apply an action.
- **Ordering**: events that mutate the same resource are serialized on a per-resource key;
  concurrent actions on one resource are mutually excluded.
- **Replay**: the append-only audit log is the source of truth and supports deterministic
  replay for debugging and post-incident review; replay is judge-only (never re-executes).

## LLM Quality Gate (required for T2)

T2 inputs (event payloads, tool output) are **untrusted** and may carry prompt injection; the
verifier and policy re-check are the authority, not model text (see the threat model in
[security-and-identity.md](../../docs/roadmap/security-and-identity.md)).

- **Mixed-model cross-check**: run two or more distinct models (ideally different vendors or
  families) on the same judgment. A single model is never sufficient. On agreement, proceed;
  on disagreement, **escalate to HIL** (do not auto-resolve).
- **Verifier**: re-validate every generated action against deterministic rules (policy-as-code
  and what-if) before it can execute.
- **Grounding (RAG)**: force citation of the rules/policies that justify the judgment;
  **abstain** (route to HIL, take no auto-action) when the answer is unsupported.
- **Threshold gate**: schema, policy, what-if, and security-scan checks must all pass and
  confidence must clear a configured threshold; otherwise route to HIL.
- Generation is done by the LLM; **execution eligibility is granted by deterministic
  verification**, never by the model alone.

Definitions: *escalate* = route to a human for approval; *abstain/hold* = take no autonomous
action and hand off to HIL.

## Rule Catalog

- Normalize every rule to a common, CSP-neutral schema:
  `id, version, source, severity, category, resource-type, check-logic, remediation,
  provenance`.
- **Conflict handling**: when multiple rules match one event, deduplicate by `id` and resolve
  precedence by severity, then by source priority; ties escalate to HIL rather than
  auto-picking. Version each rule so changes are traceable and reversible.
- Sources include Azure WAF/AKS Baseline/MCSB/Policy/Advisor, CIS Benchmarks, OPA/Gatekeeper,
  IaC scanners (Checkov, tfsec, KICS, Trivy), kube-bench, and static analyzers.
- The catalog is stored as **catalog-as-code** and updated via a continuous pipeline
  (`source watcher -> collect -> shadow evaluation -> regression -> promote/rollback`).
  Promotion requires the regression suite to pass with no policy-violation escapes; a failing
  regression blocks promotion and can roll a rule back.
- **Autonomous discovery loop** - the same pipeline also runs a long-horizon loop that
  observes operational signals (audit log, HIL approvals, shadow outcomes, rollbacks,
  override events) and proposes rule candidates: **new** rules for recurring patterns not
  yet covered, **revisions** for rules whose upstream source changed or whose shadow
  accuracy drifted, and **retirements** for rules whose active overrides indicate a poor
  fit. Candidates are handled as inert data until the quality gate promotes them; the loop
  never mutates the catalog directly.

## Action Ontology and Console Vocabulary

The action ontology and the conversational operator surface add these terms to the shared
domain vocabulary. Reuse them verbatim in code, docs, and identifiers.

- **ActionType categories** (top-level bucket on every ontology entry):
  - `remediation` - rule-fired, config-drift-style change.
  - `ops` - operator-requested runtime action (restart, scale, flush).
  - `governance` - ontology / catalog / exemption / promotion change.
  - `tool` - invoke a registered function (generate a document, send a notification,
    open a ticket) via the `tool_call` execution path; no substrate mutation.
  New categories require a doc PR that also updates this list.
- **Trigger axis**: `rule_violation`, `operator_request`, `both` - who initiates an action.
- **Execution paths**: `pr_native`, `direct_api`, `pr_manual`, `tool_call` - how the executor
  applies it. `tool_call` invokes a registered function behind the `ToolExecutor` provider
  (the ontology-native counterpart of an LLM calling a tool; the same seam an MCP adapter
  attaches to), never a substrate mutation.
- **Operator console** terms:
  - `operator-console` - the conversational pull-direction surface (CLI / Teams / Slack / web).
  - `narrator` - the console LLM tier; a **translator** (natural language <-> tool calls),
    never a judge. Distinct from the T2 quality-gate reasoner.
  - `operator-conversation` - one bounded, RBAC-scoped, audited multi-turn exchange.
  - `console-tool` - one exposed pipeline-stage view the narrator may call, tagged with a
    `side_effect_class` (`read` / `simulate` / `approve` / `execute` / `breakglass`).

The unified risk decision combines the authoritative `risk-classification` first-match table
with a never-raising six-axis ActionType ceiling (see the risk-gate references in the roadmap);
neither raises autonomy above the other.

## Agent Pantheon

The control loop is owned by a fixed set of 15 named agents that live as first-class
`Agent` objects in the ontology. The pantheon is customer-agnostic and defined upstream
only: forks configure it (bindings, enable/disable, rate limits) but MUST NOT add,
remove, or rename agents. Full design, org chart, topic contract, and per-agent
responsibilities live in [../../docs/roadmap/agent-pantheon.md](../../docs/roadmap/agent-pantheon.md).
When editing agent code under `src/fdai/agents/**`, the role table and the MUST rules
in [agent-pantheon.instructions.md](agent-pantheon.instructions.md) apply (it auto-loads
for that path).

The names below are the canonical identifiers used in code, config, audit entries, and
docs. Reuse them verbatim.

- **Odin** (Master Planner) - cross-vertical arbitration; final tie-breaker before Forseti
  finalizes a verdict.
- **Thor** (Responder) - dispatcher of verdicts and sole privileged executor principal;
  MUST NOT judge.
- **Forseti** (Judge) - issues the `Verdict` (auto / hil / deny) after mixed-model
  cross-check, verifier, and grounding; reports to Odin, not Thor.
- **Huginn** (Event Collector), **Heimdall** (Observer) - sensing; deterministic-first,
  MUST NOT invoke an LLM synchronously in the hot-path.
- **Var** (Approver) - HIL approval principal; MUST stay distinct from Thor.
- **Vidar** (Recovery) - rollback and DR failover principal.
- **Bragi** (Narrator) - conversational-port translator only; a Bragi that calls an
  executor directly is a defect.
- **Saga** (Auditor) - append-only audit and Handoff-to-GitHub-issue executor.
- **Mimir** (Rule Steward), **Norns** (Learner), **Muninn** (Memory) - governance staff.
- **Njord** (Cost), **Freyr** (Capacity), **Loki** (Chaos) - domain specialists;
  advisory to Forseti, they do not execute.

Two-port model: every agent exposes a **typed pub/sub port** (schema-checked, hot-path,
deterministic-first) and a **conversational port** (natural language, LLM-backed, for
operator questions and agent-to-agent introspection). The two ports share nothing except
the correlation trace; a conversational request that asks for an action MUST re-enter
the typed pipeline (no bypass).

Every `ActionType` binds five agent roles: `initiators`, `judge`, `executor`, `approver`,
`auditor`. The registry rejects any lifecycle event whose `producer_principal` does not
match the declared role. The `executor`, `judge`, `approver`, `auditor`, and `initiators`
fields are fork-locked (see the fork boundaries in
[../../docs/roadmap/agent-pantheon.md](../../docs/roadmap/agent-pantheon.md#10-fork-customization)).

Handoff, security notification, and privilege-escalation monitoring all flow through the
same lifecycle and audit machinery - no side-channel side-effects. When an agent cannot
resolve a request, Saga materializes a `HandoffEscalation` into a GitHub issue with
fingerprint-based deduplication.

## Safety Invariants

Every autonomous action MUST have: a **stop-condition**, a tested **rollback path**, a
**blast-radius limit** (scope/batch/rate cap), and an **audit-log entry**; and it MUST run its
**what-if/dry-run** and hold the per-resource lock before applying a change. Missing any of
these means the action is incomplete and must not ship.

New capabilities ship in **shadow mode** (judge-and-log only, no execution). Promotion to
enforce is explicit, per-action, and gated on measured accuracy plus zero policy-violation
escapes in shadow; regressions demote back to shadow automatically
([security-and-identity.md](../../docs/roadmap/security-and-identity.md)).

## Human Override

An operator MAY override an accepted rule when it is too aggressive for a specific
environment. Overrides sit **above** the automated quality gate - an override always wins
against the promotion decision on the scope it covers - but they never bypass audit or
grounding.

- **Policy-as-code, separate artifact**: an override is a declarative artifact stored
  alongside the catalog, not an edit to the rule text. Removing the override restores the
  rule automatically; upstream rule updates flow through without touching overrides.
- **Scope MUST be bounded to a resource-group-equivalent grouping or narrower** (the
  `resource-group` layer of the scope hierarchy in
  [rule-governance.md](../../docs/roadmap/rule-governance.md), or `resource`).
  Organization- or account-wide overrides are rejected; disabling a rule everywhere is not
  an override, it is a rule retirement and must go through the catalog pipeline.
- **Permitted modes**: `disabled` (rule off in the scope), `severity-downgrade`
  (e.g. `critical -> medium`), and `parameter-relaxation` (widen a threshold within limits
  the rule declares). Anything broader is out of scope for override.
- **No forced expiry**: overrides MAY be long-lived. A justification and a distinct
  approver (no self-approval) are always required.
- **Shadow keeps running**: an override disables *execution* on the scope, not detection.
  The evaluator continues to record what the rule would have flagged, feeding the
  autonomous discovery loop.
- **Feedback**: recurring or long-lived overrides on the same rule are treated by the
  discovery loop as a signal to propose a revision or retirement of that rule; the
  proposal still passes the standard quality gate.
- Every override create/modify/remove event is an append-only audit entry with actor,
  reason, target rule, and scope. Overrides never suppress the audit record of the
  underlying finding; they record why execution was suppressed.

## Observability

- Emit per-tier metrics (coverage share, latency, auto-resolution rate), the mixed-model
  disagreement rate, verifier pass/fail rate, and rollback rate; these feed the KPIs in
  [goals-and-metrics.md](../../docs/roadmap/goals-and-metrics.md).
- Trace each event end-to-end (event → tier → gate decision → action) with the correlating
  audit reference, so any autonomous action is reconstructable.
