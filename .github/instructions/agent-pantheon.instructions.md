---
description: Agent Pantheon roles, permissions, and the MUST rules for changing any agent code.
applyTo: "src/fdai/agents/**"
---

# Agent Pantheon - Roles and Code-Change Contract

This file is the **normative contract for editing any file under
`src/fdai/agents/**`**. It exists so that when the code changes, the change stays
consistent with the agent's declared role, permissions, and safety invariants -
never silently drifting from the design.

The authoritative design is [../../docs/roadmap/agents/agent-pantheon.md](../../docs/roadmap/agents/agent-pantheon.md)
(org chart, topic contract, ActionType role bindings, LLM policy, degradation
policy). This file is the short, always-loaded rule set; when the two disagree,
`agent-pantheon.md` wins for design and this file wins for the change process.
Related: [architecture.instructions.md](architecture.instructions.md) (Agent
Pantheon section, safety invariants), [coding-conventions.instructions.md](coding-conventions.instructions.md)
(SRP, testing, safety), [language.instructions.md](language.instructions.md)
(bilingual policy; machine records SHOULD stay English).

RFC 2119 keywords apply: **MUST** / **MUST NOT** are hard gates; **SHOULD** is a
strong default; **MAY** is optional.

## 1. The pantheon is fixed (MUST)

- The pantheon is **exactly 15 named agents**. A change MUST NOT add, remove, or
  rename an agent. A genuinely new capability that needs a new agent is an
  upstream design PR that extends `agent-pantheon.md` first, not a code edit.
- Each agent is a first-class `Agent` in the ontology. Its `AgentSpec` (name,
  layer, `owns`, `subscribes`, LLM flags, `hard_dependency`) is the machine-
  readable role. Editing an agent's behavior MUST keep its `AgentSpec` and this
  table in sync.

### 1.1 Directory layout (MUST)

The 15 pantheon members live **flat at the top level** of
`src/fdai/agents/`; framework code (bus, runtime, registry, base, pantheon
spec, arbitration, introspection, kpi, adapters, provider_adapters,
factory, workflows, topics, candidate_guard, divergence, bus_bridge,
bus_metrics, action_semantics, rate_limiter) lives under `src/fdai/agents/_framework/`.
This is the G-7 layout from tracker #14 and it is enforced by
`tests/agents/test_framework_layout.py`:

- A new `.py` file directly under `src/fdai/agents/` MUST be one of the
  15 pantheon members. Anything else belongs under `_framework/`.
- External callers (any file outside `src/fdai/agents/`) MUST import
  from `fdai.agents` (the facade), not from `fdai.agents._framework.<X>`.
  The leading underscore is not decorative - it signals "not for
  external consumption; reaching in defeats the facade and breaks
  silently on renames".
- A pantheon member MAY reach into `_framework/` (it needs `Agent`,
  `AgentSpec`, adapters, etc.). Pantheon members MUST NOT import each
  other; cross-member communication goes through the bus + typed topics
  so the arbitration model stays intact.
- Adding a new pantheon member is a **charter change**: upstream doc PR
  to `agent-pantheon.md`, this file, and the standard fork-lock review
  (see section 7). Adding a helper under `_framework/` does not.

## 2. Role, ownership, and topic table (authoritative for edits)

> **Machine-readable source of truth**: `PANTHEON_SPECS` in
> [`src/fdai/agents/_framework/pantheon.py`](../../src/fdai/agents/_framework/pantheon.py).
> Each `AgentSpec` there carries `name`, `layer`, `reports_to`, `owns`,
> `executes`, `initiates`, `subscribes`, `question_domains`, and
> `owns_code_paths`. The tables in this file and in
> [`docs/roadmap/agents/agent-pantheon.md`](../../docs/roadmap/agents/agent-pantheon.md)
> paraphrase that data for human readers. If they disagree, the code
> wins - and a regression test
> ([`tests/agents/test_pantheon_doc_parity.py`](../../tests/agents/test_pantheon_doc_parity.py))
> catches the drift on the 15 agent names.

Layer: `domain` (specialist) | `pipeline` (sensing/judgment/operations/interface)
| `governance` (staff). "Owns" = single-writer authority: only the owner agent
MAY publish that object type's topic.

| Agent | Role | Layer | Owns (single-writer) | Publishes topic(s) | Subscribes | LLM in hot-path | Hard dep |
|-------|------|-------|----------------------|--------------------|------------|-----------------|----------|
| **Odin** | Master Planner (cross-vertical arbiter, final tie-break) | governance | ArbitrationDecision | `object.arbitration-decision` | `object.arbitration-request`, `object.verdict` (portfolio) | no | no |
| **Thor** | Responder - **sole privileged executor**; MUST NOT judge | pipeline | ActionRun, ActionAttempt | `object.action-run` | `object.verdict`, `object.approval`, `object.rollback` | no | no |
| **Forseti** | Judge - issues Verdict (auto/hil/deny); reports to Odin, not Thor | pipeline | Verdict, RCA, SecurityEvent, ArbitrationRequest | `object.verdict`, `object.security-event`, `object.arbitration-request` | `object.anomaly`, `object.drift`, `object.cost-anomaly`, `object.capacity-forecast`, `object.arbitration-decision`, `object.rule` | yes (T2 abstain only) | no |
| **Huginn** | Event Collector / real-time resource discovery ingress - normalize + dedup + correlate | pipeline | Event | `object.event` | (external ingress) | no | no |
| **Heimdall** | Observer - anomaly/drift/forecast + security-severity correlation | pipeline | Anomaly, Drift, Forecast | `object.anomaly`, `object.drift`, `object.forecast` | `object.event`, `object.security-event`, `object.chaos-experiment` | no | no |
| **Vidar** | Recovery - rollback + DR failover principal | pipeline | Rollback | `object.rollback` | `object.action-run` (failed) | no | **yes** |
| **Var** | Approver - HIL principal; MUST stay distinct from Thor | pipeline | Approval | `object.approval` | `object.action-run` (hil) | no | no |
| **Bragi** | Narrator - conversational-port translator ONLY | pipeline | Conversation, Turn, UserPreference | `object.conversation`, `object.turn`, `object.user-preference` | (operator console) | yes (translator only) | no |
| **Saga** | Auditor - append-only chain + handoff-to-GitHub-issue | governance | AuditEntry, Issue | `object.audit-entry`, `object.issue` | (all terminal states, for audit) | no | **yes** |
| **Mimir** | Rule Steward - promote/revoke rules through the quality gate | governance | Rule, Policy | `object.rule` | `object.rule-candidate`, `object.issue` | no | no |
| **Muninn** | Memory - state snapshots + context index (RAG) | governance | StateSnapshot, ContextIndex | (state store) | `object.turn` | no | no |
| **Norns** | Learner - proposes inert RuleCandidates (never mutates catalog) | governance | RuleCandidate, PatternObservation | `object.rule-candidate` | `object.audit-entry`, `object.issue`, `object.approval`, consent-filtered `object.turn` review envelopes | off-path batch only | no |
| **Njord** | Cost specialist - advisory to Forseti | domain | CostAnomaly, Budget | `object.cost-anomaly` | (cost adapter) | no | no |
| **Freyr** | Capacity specialist - advisory to Forseti | domain | CapacityForecast, SizingRecommendation | `object.capacity-forecast` | (utilization adapter) | no | no |
| **Loki** | Chaos specialist - proposes experiments (always HIL) | domain | ChaosExperiment, ResilienceScore | `object.chaos-experiment` | (schedule) | no | no |

> `object.override` is **not** a registered topic and no agent owns `Override`.
> Do not publish or subscribe it. Override events flow through the exemption /
> rule-catalog machinery, not a pantheon topic.

## 3. Structural invariants that a code change MUST preserve

1. **Single-writer topics (MUST).** An agent MUST publish only to a topic whose
   object type it owns (column "Owns"). Adding a publish to another agent's topic
   is a defect; `registry.assert_can_publish` will reject it, and so must review.
2. **Judge != executor (MUST).** Forseti issues verdicts; Thor dispatches and is
   the *only* principal that mutates. A change that lets Forseti execute, or lets
   any non-Thor agent mutate, is a defect.
3. **Approval != execution (MUST).** Var carries the human approval; Thor
   executes. They MUST stay distinct principals (no self-approval, no shared
   identity).
4. **Narrator is a translator, not a judge/executor (MUST).** A conversational
   request that wants an action MUST re-enter the typed pipeline as a proposal
   whose `initiator_principal` is the operator - never let Bragi (or any
   conversational path) call an executor directly.
5. **Deterministic-first hot-path (MUST).** Sensing (Huginn, Heimdall) and the
   domain specialists (Njord, Freyr, Loki) MUST NOT invoke an LLM synchronously.
   Hot-path LLM is allowed only in the three declared places: Bragi translator,
   Forseti T2 abstain, Norns off-path batch.
6. **Discovery ownership stays split (MUST).** Huginn owns real-time resource
   discovery ingress and remains the sole writer of `Event`. Provider adapters
   own cloud parsing and enrichment; the inventory projector owns durable
   resource/link/tombstone projection; the Inventory sync job owns periodic
   full reconciliation; Heimdall owns discovery-health findings. Huginn MUST
   NOT import a cloud SDK or write an inventory database directly.
7. **Hard dependencies fail safe (MUST).** Saga and Vidar are hard dependencies.
   A change MUST NOT allow a mutation to proceed when Saga (audit) or Vidar
   (rollback) is unavailable; degrade to shadow, never fail open.
8. **Fork-locked ActionType bindings (MUST).** The five role fields on every
   ActionType - `initiators`, `judge`, `approver`, `executor`, `auditor` - plus
   `compensating_action`, `irreversible`, and `rollback_contract` are pantheon
   safety boundaries. Code and config MUST NOT repoint them per fork.
9. **Two ports share nothing but the trace (MUST).** The typed pub/sub port and
   the conversational port are separate. A conversational answer MUST NOT bypass
   the typed pipeline's judge/approve/execute steps.

## 4. Code-change MUST rules (the reason this file auto-loads)

When you add, edit, or refactor **any file under `src/fdai/agents/**`**, you MUST
do all of the following before proposing the change as complete:

1. **Name the agent(s) and restate the role.** Identify which pantheon agent the
   file implements and restate, from section 2, its role, `owns`, publish
   topics, subscribe topics, LLM policy, and whether it is a hard dependency.
   State it explicitly in the change description so the reader can check the edit
   against the role.
2. **Keep the AgentSpec and this table consistent.** If the edit changes what the
   agent subscribes/publishes/owns or its LLM/hard-dependency status, you MUST
   update the `AgentSpec`, this table, and `agent-pantheon.md` in the **same
   change** (docs never drift - see coding-conventions Documentation Workflow).
3. **Verify the wiring, not just the handler.** A handler that is never reached
   at runtime is a defect. When you add or change a subscription/publication, you
   MUST confirm the runtime composition root (`runtime.py` / the bus bridge)
   actually registers it and that the producer/consumer topics match. Flag any
   handler whose topic is not in the agent's `subscribes`, and any publish whose
   topic the agent does not own.
4. **Preserve every structural invariant in section 3.** Re-check the change
   against all nine. A change that weakens judge/executor separation,
   single-writer, approval/execution separation, hard-dependency fail-safe, or
   the deterministic hot-path is not mergeable.
5. **Uphold the safety invariants for any autonomous action path.** Every action
   an agent initiates, judges, approves, executes, or audits MUST carry a
   stop-condition, a rollback path (or `irreversible: true` + HIL quorum), a
   blast-radius limit, and an audit entry - and these MUST be present on the wire
   payload (e.g. `ActionRun`), not only in a constructor default. New behavior
   ships **shadow-first**.
6. **Enforce quorum for irreversible actions.** An `irreversible` ActionType MUST
   route through HIL with `quorum_required >= 2`, distinct approvers, and no
   self-approval. If you touch the verdict -> dispatch -> approval path (Forseti,
   Thor, Var), you MUST ensure `quorum_required` is set by the judge and honored
   by the executor - it MUST NOT be hard-coded to 1.
7. **Fail toward safety, never silently drop.** An agent that cannot resolve an
   event (no rule match, verifier abstain, missing context) MUST route to HIL /
   emit the appropriate outcome, not return `None` and let the event vanish.
8. **Propose the matching work explicitly.** If the change reveals a gap (a
   handler with no live producer, an owned object type never produced, a declared
   capability - rate limits, KPI emission, degradation probe, conversational
   answer - that is stubbed), you MUST call it out and propose the corresponding
   implementation/wiring/test as a follow-up, rather than leaving a dead seam
   unremarked.
9. **Add tests that pin the role.** A change to an agent MUST come with tests that
   exercise the behavior through its declared topics and assert the structural
   invariants it touches (single-writer rejection, no-self-approval, shadow-mode
   no-mutation, quorum, fail-closed degradation).

## 5. Implementation status

Current gaps and rollout evidence belong in the canonical
[agent-pantheon implementation plan](../../docs/roadmap/agents/agent-pantheon-implementation.md),
not in this edit-time contract. Before changing an affected path, load the
[agent-pantheon-edit skill](../skills/agent-pantheon-edit/SKILL.md), verify the
current implementation and neighboring tests, and update the plan when behavior changes.

> One line: restate the agent role, preserve all nine structural invariants, satisfy all nine
> change rules, and call out any dead seam exposed by the edit.
