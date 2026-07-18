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
| **Norns** | Learner - proposes inert RuleCandidates (never mutates catalog) | governance | RuleCandidate, PatternObservation | `object.rule-candidate` | `object.audit-entry`, `object.issue`, `object.approval` | off-path batch only | no |
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

## 5. Known role/implementation gaps (keep visible; do not regress)

These are documented shortfalls between `agent-pantheon.md` and the current
code. A change in the affected area SHOULD close the gap or, at minimum, MUST NOT
deepen it. Do not delete this list without closing the item.

- **Quorum for irreversible actions is catalog-backed and plumbed end to end.** Forseti stamps
  `quorum_required` on the verdict via
  `agents/_framework/action_semantics.quorum_for` (2 for an irreversible
  ActionType, 1 otherwise), Thor propagates it onto the `ActionRun` (floored
  at 1, never hard-coded), and Var enforces the distinct-approver quorum with
   no self-approval. The live `PantheonRuntime` receives the authoritative
   ActionType catalog from the control loop; Forseti and Heimdall share its
   `irreversible` and `rollback_contract` values. The name heuristic remains
   only as a zero-config unit-test/local fallback when no catalog is injected.
  The `remediate.delete-storage` default verdict remains `deny` (a policy
  choice, not a plumbing gap); the quorum rides along so a fork that routes
  an irreversible action to `hil` gets two-approver enforcement for free.
- **Forseti's `cost_spike` placeholder remediation is removed.** A raw
   `cost_spike` event without a typed ActionType now routes to HIL/no-rule-match
   rather than being mislabeled as an admin-privilege notification. The other
   Wave-3 event/risk tables remain deterministic compatibility defaults until
   their event-to-rule projection has a schema-backed source.
- **Forseti no-rule-match routes to HIL** (rule 4.7). An identifiable
  incident with a concrete resource target but no matching rule emits an
  `hil` verdict (`reason: no_rule_match`, empty `action_type`,
  `quorum_required: 1`) so a human triages it instead of the event
  vanishing. A payload with no resource target or no correlation id
  abstains (recorded via the `no_rule_match` counter) so malformed / junk
  ingress cannot manufacture HIL items - dropping malformed input is the
  event-ingest boundary's job, not the judge's.
- **Vidar rollback dispatch is provider-backed.** The runtime injects rollback
   executors keyed by `rollback_contract`; an unbound contract, provider error,
   or missing receipt emits a failed rollback instead of fabricating success.
   Thor keeps the failed ActionRun and resource lock until Vidar's receipt
   arrives, then records `rolled_back` or `rollback_failed`.
- **Pantheon enforce mode fails closed at startup.** A live Thor executor,
   durable ActionRun store, StateStore-backed Saga, and rollback executor
   registry are all required before `enforce=True` can start.
- **Live degradation policy is not driven by health probes** (Saga/Vidar
  availability are constructor flags, not runtime signals).
- **Discovery loop (Saga -> Norns -> Mimir) is mostly wired.** The
  **outcome loop** is closed: Saga republishes each terminal action outcome
  (succeeded / failed / rolled_back, normalized via
  `action_semantics.outcome_result`) as `object.audit-entry`, and Norns'
  outcome learner - now aligned to its declared `object.audit-entry`
  subscription and deduping per `correlation_id` - scores rollback rates
  from it. `object.override` is no longer subscribed (it is not a pantheon
  topic); the override learner is the public `Norns.observe_override()` the
  exemption machinery calls. **Norns now publishes `object.rule-candidate`**:
  its `flush_candidates()` drains newly-formed inert candidates onto the bus
  (single-writer; idempotent via a cursor), and Mimir consumes them through
  its `CandidateGuard` (grounded provenance + poisoning defense) into the
  pending / quarantine lists - it never auto-promotes. **The `object.approval`
  learner is wired**: recurring HIL rejections of the same action type propose
  an inert `revision` candidate (the safe, autonomy-lowering direction,
  symmetric with the override learner; approvals are counted for evidence
  only, never an auto-promotion). **Saga now publishes `object.issue`**: on
  `escalate_to_github_issue` it emits the issue onto the bus (it is the single
  writer of Issue), so recurring handoffs feed Norns' fingerprint learner end
  to end. **The handoff trigger is wired**: `PantheonRuntime.ask` calls
  `Saga.escalate_to_github_issue` when a conversational turn abstains with no
  route (`handoff_needed`), fingerprinted on the normalized question so repeat
  asks dedup (a comment, not a new issue) - it never bypasses the typed
  pipeline (it records that no agent could help, not the operator's action).
  **Remaining**: the optional scenario-coverage learner's `new-scenario`
  proposal_kind is not yet in the `CandidateGuard` allowlist (quarantined until
  a scenario intake path lands).
- **LLM bindings are placeholders** (`hot_path_llm` / `off_path_llm` booleans; no
  `llm_bindings` field; no model is invoked). The conversational port answers are
  base stubs on all agents except Bragi routing.
- **Rate limits are enforced on the proposal path.** Per-agent measurable
  behaviour IS emitted: every agent records colon-namespaced behaviour
  counters (`verdict:auto`, `no_rule_match`, `security_event`, ...) via the
  base `record_behavior`, exposed through `behavior_snapshot()` /
  `health()` and merged per-agent into `PantheonRuntime.health()`. This is
  the measurement substrate for scenario tests and the KPI collector;
  wiring the counters into a durable KPI sink is the remaining step. The
  declared `RateLimits` (default 20/min, 100/hr - agent-pantheon.md 7.9)
  are now enforced by the base `Agent._publish_proposal` helper backed by a
  deterministic `RateLimiter` (per-minute + per-hour windows): a discretionary
  proposal over budget is throttled (held on the emitting agent's bounded
  buffer, flushed when the window refills) and the drop is recorded as
  `rate_limit_exceeded`. **Scope**: only genuinely discretionary proposals
  route through `_publish_proposal` (Norns' `object.rule-candidate` and Njord's
  `object.cost-anomaly`, which fire only on an actual pattern / anomaly);
  pipeline-critical emissions (verdicts, action-runs, approvals, audit) and
  sensing findings (anomaly / drift / forecast) publish directly and are never
  rate-limited. Freyr's `object.capacity-forecast` is deliberately NOT rate
  limited: it is a telemetry-cadence refresh (one per ingested sample, bounded
  by the caller's sampling rate), not a discretionary proposal, so throttling
  it would shed meaningful forecasts at random when the window fills with
  routine samples. **Remaining**: Loki keeps its own stronger blast-radius cap
  (a proposal-storm guard that also gates in-flight targets, so a generic
  limiter would be redundant and could leak the in-flight accounting); Forseti
  arbitration requests MAY adopt `_publish_proposal` later; and the overflow
  `RateLimitExceeded` audit entry (agent-pantheon.md 7.9) is recorded as a
  behaviour counter, not yet a durable audit-chain record.
- **Producer-principal is now verified on both sides.** Publish-side
  single-writer auth (`registry.assert_can_publish`) is complemented by a
  consumer-side check in `EventBusBridge` (`verify_producer_principal`,
  default on): a delivered record whose `producer_principal` is not the
  topic owner is dead-lettered, never handed to a subscriber. An absent
  principal is allowed (publish-side `missing_*` counters surface it).
- **DLQ redrive and ordered-topic halt are opt-in, not automatic.**
  `EventBusBridge.redrive` reprocesses `<topic>.dlq` only when an operator
  invokes it; `halt_ordered_topic_on_poison` (default off) preserves
  per-resource ordering by halting a consumer on a poison mutation record.
- **Bus-level payload schema validation is a seam, not a default.**
  `EventBusBridge.payload_validator` can reject a malformed record at the
  publish boundary, but no `ContractValidator`-backed validator is wired by
  default - a fork opts in.
- **Event replay / offset seek is not exposed on the `EventBus` Protocol.**
  Deterministic replay for post-incident review relies on the audit chain,
  not a broker seek; adding a `seek` / `replay` capability to the Protocol
  is future work.

> One line: editing an agent means first restating its role from section 2,
> keeping the nine structural invariants (section 3), and satisfying the nine
> code-change rules (section 4) - including proposing the follow-up work for any
> dead seam you touch.
