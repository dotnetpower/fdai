---
title: "FDAI Proposal Act 2: Agents, Collaboration, and Control"
description: Proposal slides 9-18 covering the 15-agent organization, collaboration, and human control.
---

# FDAI Proposal Act 2: Agents, Collaboration, and Control

Act 2 makes the operating model inspectable. It names all 15 agents, shows how typed events replace direct agent calls, and follows one event through decision, action, human approval, recovery, and audit.

> **Slides:** 9-18 of 26
>
> **Agenda sections:** Meet the 15 agents, How AI agents collaborate, Operating scenarios, When people step in

## Meet the 15 agents

### Slide 9. A fixed organization, not a collection of assistants

**Decision question:** Who owns each part of the operating loop?

**Key message:** FDAI defines 15 independently runnable agents once upstream and assigns each a stable mandate, object ownership, and event contract.

**On-slide copy:**

```text
Odin - Master Planner
  Thor - Responder          Forseti - Judge
    Vidar - Recovery          Huginn - Event Collector
    Var - Approver            Heimdall - Observer
    Bragi - Narrator          Njord - Cost
                              Freyr - Capacity
Staff: Mimir - Rules, Muninn - Memory, Saga - Audit,
       Norns - Learning       Loki - Chaos
```

- Forks configure the organization but do not add, remove, or rename agents.
- Each object type has one writer and may have many readers.

**Visual:** A restrained organization chart with solid operating lines and dotted governance staff lines. Use one blue accent for active flow, not group-colored cards.

**Evidence to bring:** Pantheon parity test and the machine-readable `PANTHEON_SPECS` source.

**Presenter note:** Read the groups, not every name. Use Slides 10-11 for role detail.

### Slide 10. Sensing, judgment, action, and interface roles

**Decision question:** Which agents touch the live operating path?

**Key message:** Live-path agents have narrow responsibilities that prevent observation, judgment, approval, and execution from collapsing into one identity.

**On-slide copy:**

| Agent | Plain-language role | Does not own |
|-------|---------------------|--------------|
| Huginn | Collects, normalizes, and correlates events. | Judgment or execution. |
| Heimdall | Detects anomaly, drift, and forecast outcomes. | Remediation execution. |
| Forseti | Issues the decision and grounded analysis. | Approval or execution. |
| Thor | Dispatches typed, approved action runs. | Judgment or human identity. |
| Var | Carries human approval or rejection. | Executor credentials. |
| Vidar | Runs recovery and rollback paths. | Self-approval. |
| Bragi | Translates operator intent and presents answers. | Changing the underlying decision. |

**Visual:** A single swimlane from sense to judge to approve or dispatch to recover, with Bragi placed above as the human interface.

**Evidence to bring:** One role-binding example from the action ontology.

**Presenter note:** Thor is the responder and dispatcher. Do not describe it as a second judge.

### Slide 11. Planning, evidence, learning, and domain roles

**Decision question:** Who governs the loop and supplies specialist evidence?

**Key message:** Governance and domain agents advise or preserve state without acquiring hidden execution authority.

**On-slide copy:**

| Agent | Plain-language role | Control boundary |
|-------|---------------------|------------------|
| Odin | Arbitrates competing domain objectives. | Deterministic and evidence recorded. |
| Mimir | Owns rules and policy lifecycle. | Promotion follows quality gates. |
| Muninn | Preserves state, context indexes, and case history. | Memory does not decide. |
| Saga | Appends audit evidence and escalates issues. | Audit does not execute. |
| Norns | Proposes inert rule candidates from repeated evidence. | Cannot promote its own proposal. |
| Njord | Detects cost anomalies and proposes cost actions. | No execution authority. |
| Freyr | Forecasts capacity and proposes sizing actions. | No execution authority. |
| Loki | Proposes bounded resilience experiments. | Chaos actions require human approval. |

**Visual:** Two unframed tables labeled Governance and Domain specialists. Keep all rows neutral and equal.

**Evidence to bring:** One example of a specialist conflict and the recorded arbitration result.

**Presenter note:** Learning produces candidates, not live rules. This distinction protects the promotion boundary.

## How AI agents collaborate

### Slide 12. Agents collaborate through typed events

**Decision question:** How does FDAI prevent hidden coupling between agents?

**Key message:** Machine collaboration uses schema-validated publish and subscribe events, not direct calls, private RPC, or shared mutable workflow state.

**On-slide copy:**

- **Publish:** The single owner creates a typed object and correlation identity.
- **Validate:** The event fabric checks schema, ownership, and required evidence.
- **Subscribe:** Any authorized agent can react without importing another agent's implementation.
- **Replay:** The same event and configuration reproduce the same deterministic path.

```text
Agent -> Typed event -> Schema and ownership check -> Subscribers
```

**Visual:** A central event fabric with independent agent endpoints. Cross out only direct agent-to-agent arrows.

**Evidence to bring:** Event schema, ownership table, and a replayed synthetic trace.

**Presenter note:** The event bus is an architectural boundary, not just transport selection.

### Slide 13. The lowest sufficient decision tier wins

**Decision question:** When does adaptive reasoning enter the path?

**Key message:** FDAI resolves repeatable cases with deterministic rules first and reserves grounded adaptive reasoning for declared ambiguity.

**On-slide copy:**

| Tier | Use | Required control |
|------|-----|------------------|
| T0 | Deterministic rules and policy lookup. | Exact inputs and replayable result. |
| T1 | Lightweight similarity reuse for known patterns. | Bounded match and prior evidence. |
| T2 | Grounded adaptive reasoning for ambiguous cases. | Independent verification, evidence, schema, risk, and approval gates. |

- No fixed percentage is promised before the pilot baseline.
- A lower-confidence outcome moves to review or is blocked.

**Visual:** Three horizontal tiers with T0 widest and no numeric percentages. Show evidence requirements increasing toward T2.

**Evidence to bring:** Candidate event set and the criteria used to assign each event to a tier.

**Presenter note:** Present tier distribution as a pilot measure, not a product benchmark.

## Operating scenarios

### Slide 14. Scenario: one signal becomes one governed decision

**Decision question:** What happens from the first signal to a decision?

**Key message:** FDAI preserves context and evidence while reducing duplicate signals to one decision path.

**On-slide copy:**

1. Huginn receives and normalizes the provider event.
2. Heimdall correlates related signals and detects the operating condition.
3. Forseti selects T0, T1, or T2 and verifies the evidence.
4. Policy classifies the proposed action as automatic, human approval, or blocked.
5. Saga records the decision even when no action runs.

**Visual:** Use one synthetic example, such as capacity risk or an idle resource, and annotate the same correlation identity at every step.

**Evidence to bring:** Input event, normalized event, decision object, policy result, and audit entry.

**Presenter note:** Avoid switching scenarios between architecture and demo. Consistency is more persuasive than breadth.

### Slide 15. Every action carries its own safety contract

**Decision question:** What must be true before an action can run?

**Key message:** An untyped action or an action missing a safety field cannot enter the execution path.

**On-slide copy:**

| Safety field | Question answered |
|--------------|-------------------|
| Stop condition | When must the action stop? |
| Rollback | How is the prior state restored? |
| Impact limit | Which resources and scale may change? |
| Dry run | What will happen before execution? |
| Per-resource lock | What prevents conflicting concurrent work? |
| Idempotency key | How is retry made safe? |
| Audit record | How is intent, identity, and outcome preserved? |

**Visual:** One action contract expanded as a clean specification sheet. Do not decorate each field as a separate card.

**Evidence to bring:** The exact synthetic action type used in the demo and its rollback definition.

**Presenter note:** The safety contract is a type-level entry condition, not a best-effort runtime reminder.

### Slide 16. The decision has three explicit outcomes

**Decision question:** How does FDAI choose between autonomous action and human control?

**Key message:** Risk and evidence determine whether the action runs automatically, waits for approval, or is blocked.

**On-slide copy:**

| Outcome | Typical condition | Terminal evidence |
|---------|-------------------|-------------------|
| Automatic | Low impact, complete evidence, promoted capability. | Dry run, action result, verification, audit. |
| Human approval | Material impact, close objective conflict, or policy requirement. | Approval identity, reason, expiry, action or timeout. |
| Blocked | Missing evidence, disallowed scope, failed verification, or unsafe contract. | Block reason and preserved trace. |

- Approval channel failure keeps the action waiting or lets it expire.
- Runtime, environment, or fork status never promotes a capability by itself.

**Visual:** One decision node with three equally visible branches. Do not emphasize automatic action as the preferred result.

**Evidence to bring:** Policy decision output for all three branches.

**Presenter note:** A blocked action is a valid controlled outcome, not a system failure.

## When people step in

### Slide 17. People set policy and decide material exceptions

**Decision question:** Which decisions remain explicitly human?

**Key message:** FDAI removes repetitive coordination while keeping people accountable for policy, material impact, exceptions, and promotion.

**On-slide copy:**

- Approve or reject actions above the configured impact boundary.
- Resolve close conflicts between resilience, safety, cost, and capacity objectives.
- Define policy, scope, role assignments, and approval separation.
- Review evidence before moving a capability from observation to enforcement.
- Accept, revise, or reject rule candidates proposed by Norns.

**Visual:** A policy-to-exception continuum. Place repeatable decisions on the system side and accountable judgment on the human side.

**Evidence to bring:** Proposed approver groups, executor workload identity, escalation path, and expiry behavior.

**Presenter note:** Self-approval is not supported. Human App Roles and the executor workload identity remain distinct.

### Slide 18. Every path ends in evidence and ownership

**Decision question:** Can an operator explain what happened, why, and who was accountable?

**Key message:** Execution, rejection, timeout, rollback, and no-action outcomes all produce evidence that the read-only console can project.

**On-slide copy:**

| Evidence | What the reviewer can verify |
|----------|------------------------------|
| Correlation and idempotency | The complete event-to-action chain. |
| Inputs and supporting evidence | What the decision relied on. |
| Decision and policy result | Why the path was automatic, approved, or blocked. |
| Human and workload identities | Who approved and which identity executed. |
| Outcome and recovery state | Whether verification passed or rollback ran. |
| Accountable owner | Who handles escalation and knowledge handover. |

**Visual:** A read-only evidence timeline beside a compact ownership panel. Avoid an action button in the console mockup.

**Evidence to bring:** One complete audit record and the matching operator-console projection.

**Presenter note:** Close Act 2 by asking whether the proposed control boundary is reviewable, not whether every integration is already selected.

## Next steps

| To continue | Read |
|-------------|------|
| Define automation scope, outcomes, demo, and adoption | [Act 3](l100-act3-adopt.md) |
| Review role ownership in detail | [Agent pantheon](../../roadmap/agents/agent-pantheon.md) |
| Review execution safeguards | [Execution model](../../roadmap/decisioning/execution-model.md) |
