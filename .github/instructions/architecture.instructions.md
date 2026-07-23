---
description: "Use when changing the control loop, agents, contracts, ontology, rules, policies, risk decisions, or autonomous action behavior."
applyTo: "src/fdai/core/**,src/fdai/agents/**,src/fdai/shared/contracts/**,src/fdai/shared/ontology/**,rule-catalog/**,policies/**"
---

# Architecture

This file defines the control-plane architecture. It complements the deployment topology in
[app-shape.instructions.md](app-shape.instructions.md), the code/safety rules in
[coding-conventions.instructions.md](coding-conventions.instructions.md), and the phased plan
under [docs/roadmap](../../docs/roadmap/README.md). All coverage, latency, and cost figures
below are **targets to validate against a measured baseline**
([goals-and-metrics.md](../../docs/roadmap/architecture/goals-and-metrics.md)), not guarantees; state no
multiplier without measuring baseline and treatment on the same scenario set.

> **Related on-demand skills** (load when the task fits the description):
> [`.github/skills/coding-hardening/SKILL.md`](../skills/coding-hardening/SKILL.md)
> for the critique -> harden -> verify loop on safety-core modules;
> [`.github/skills/agent-pantheon-edit/SKILL.md`](../skills/agent-pantheon-edit/SKILL.md)
> for the safe-edit checklist under `src/fdai/agents/**` (also auto-loaded via
> [agent-pantheon.instructions.md](agent-pantheon.instructions.md)). Subsystem
> index (source -> tests -> docs) lives at
> [`docs/roadmap/architecture/code-map.md`](../../docs/roadmap/architecture/code-map.md).

## Design Principles

1. **Deterministic-first** - resolve every repeatable decision with rules, policies, and
   checklists. Reach for an LLM only after T0 and T1 cannot resolve the case.
2. **Confidence tiering** - route by a computed confidence so expensive inference stays a
   small minority of events (target ~5-10%; see Trust Routing).
3. **Risk-gated autonomy** - low-risk actions auto-execute; high-risk actions require
   human-in-the-loop (HIL) approval. Autonomy is never unconditional.
4. **Agent-driven event choreography** - independently runnable agents react to typed events, fan out work in parallel, and scale to zero when idle; no direct agent call chains.
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

## Agent-Driven Runtime (MUST)
- Every stage has one accountable pantheon agent; gateways, schedulers, adapters, and workers are mechanical relays, not hidden decision makers.
- Agents MUST be independently schedulable and concurrent: typed pub/sub only, no direct workflow calls/RPC/imports or shared mutable workflow state. Slow, failed, or backpressured subscribers MUST NOT block unrelated work.
- Explicit owners join correlated branches under deadlines/quorum/arbitration; ordering is causal/per-resource only. Bragi read-only introspection MUST NOT join, decide, approve, or execute.
- Delivery is at-least-once with idempotency, per-subscriber retry/backpressure, dead-letter, replay, and local/deployed parity. Tests prove overlap, isolation, ownership, duplicate/reorder safety, and restart/replay.

## Document Ingestion Is Agent-Owned (MUST)
Uploaded documents (drop zone, ChatOps, email-in, connector) enter the same agent-driven control loop as any event - Huginn ingress, Heimdall/Forseti admissibility, Var HIL, Muninn index, Saga audit, Norns/Mimir catalog growth, Bragi citation - not a standalone gateway side effect; the gateway is a mechanical relay without executor rights, and a stage that mutates ingestion state without an owning agent and a Saga audit entry is a defect. See [document-ingestion-agent-ownership.md](../../docs/roadmap/interfaces/document-ingestion-agent-ownership.md).

## Trust Routing (3-Tier)

Latency values are order-of-magnitude budgets, not SLAs. Coverage targets are approximate and
partition one event stream, so they must sum to ~100%; T0+T1 together target the ~85-90%
deterministic/lightweight share cited in
[goals-and-metrics.md](../../docs/roadmap/architecture/goals-and-metrics.md).

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
are fixed by [project-structure.md](../../docs/roadmap/architecture/project-structure.md).

## Control Loop

The diagram below is the **canonical** control-loop diagram. Docs that need to
refer to it MUST link back here (or use their own domain-specific mermaid that
does not restate the shape) rather than re-drawing this ASCII block.

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

Detection feeds the same loop, not a separate autonomy surface: `event-ingest` correlates incidents (deterministic keys, then T1 similarity); anomaly/forecast findings enter the trust router; RCA is a tier output (T0 direct, T1 prior-incident correlation, T2 grounded reasoning). Detection is deterministic-first, shadow-first, and never auto-acts; the risk gate governs its finding. Every prediction MUST carry immutable detector/version, target, breach predicate, feature cutoff, horizon, and uncertainty, then close against an actual outcome after horizon plus telemetry grace. Unobserved/intervened episodes are unscorable/censored, and action efficacy uses a separate ledger so prevention cannot manufacture a false positive. Full design:
[observability-and-detection.md](../../docs/roadmap/rules-and-detection/observability-and-detection.md).

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
[security-and-identity.md](../../docs/roadmap/architecture/security-and-identity.md)).

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

Rules use the normalized CSP-neutral schema and remain catalog-as-code. Conflict precedence is
severity, then configured source priority; unresolved ties route to HIL. Every collected, revised,
or discovered candidate carries provenance and stays inert until schema, verifier, regression, and
shadow promotion gates pass. Overrides never mutate catalog entries. Full governance lives in
[rule-governance.md](../../docs/roadmap/rules-and-detection/rule-governance.md).

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
  - `Approvals` - the human-facing L2/L3 label for queued `hil` verdicts and the
    `/hil-queue` surface. It improves operator comprehension without renaming the
    canonical machine verdict, route, schema, type, event, or audit value.
  - `narrator` - the console LLM tier; a **translator** (natural language <-> tool calls),
    never a judge. Distinct from the T2 quality-gate reasoner.
  - `operator-conversation` - one bounded, RBAC-scoped, audited multi-turn exchange.
  - `console-tool` - one exposed pipeline-stage view the narrator may call, tagged with a
    `side_effect_class` (`read` / `simulate` / `approve` / `execute` / `breakglass`).

The unified risk decision combines the authoritative `risk-classification` first-match table
with a never-raising six-axis ActionType ceiling (see the risk-gate references in the roadmap);
neither raises autonomy above the other.

## Agent Pantheon

The pantheon is exactly 15 named agents. `PANTHEON_SPECS` in
`src/fdai/agents/_framework/pantheon.py` is the machine source of truth. Changes under
`src/fdai/agents/` MUST load [agent-pantheon.instructions.md](agent-pantheon.instructions.md)
and the [agent-pantheon-edit skill](../skills/agent-pantheon-edit/SKILL.md).

The control-loop boundaries are fixed: Forseti judges, Thor alone executes, Var approves, Saga
audits, Vidar rolls back, and Bragi only translates. Typed and conversational ports share only the
correlation trace. Role bindings are distribution-locked and runtime configuration cannot repoint
them.

## Safety Invariants

Every autonomous action MUST have: a **stop-condition**, a tested **rollback path**, a
**blast-radius limit** (scope/batch/rate cap), and an **audit-log entry**; and it MUST run its
**what-if/dry-run** and hold the per-resource lock before applying a change. Missing any of
these means the action is incomplete and must not ship.

New capabilities ship in **shadow mode** (judge-and-log only, no execution). Promotion to
enforce is explicit, per-action, and gated on measured accuracy plus zero policy-violation
escapes in shadow; regressions demote back to shadow automatically
([security-and-identity.md](../../docs/roadmap/architecture/security-and-identity.md)).

## Human Override

Overrides are separate, audited policy artifacts. They may disable, lower severity, or relax a
declared parameter only at resource-group-equivalent scope or narrower. They never edit a rule,
suppress its finding, stop shadow evaluation, or bypass grounding and approval. Organization-wide
disablement is retirement, not override. See
[rule-governance.md](../../docs/roadmap/rules-and-detection/rule-governance.md).

## Observability

- Emit per-tier metrics (coverage share, latency, auto-resolution rate), the mixed-model
  disagreement rate, verifier pass/fail rate, and rollback rate; these feed the KPIs in
  [goals-and-metrics.md](../../docs/roadmap/architecture/goals-and-metrics.md).
- Trace each event end-to-end (event → tier → gate decision → action) with the correlating
  audit reference, so any autonomous action is reconstructable.
