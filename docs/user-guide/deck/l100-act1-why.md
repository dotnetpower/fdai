---
title: "FDAI Proposal Act 1: Why Change and Why FDAI"
description: Proposal slides 1-8 covering the operating-model case for change and the FDAI architecture.
---

# FDAI Proposal Act 1: Why Change and Why FDAI

Act 1 establishes the decision context before presenting implementation detail. It moves from the limits of ticket-driven operations to a bounded, agent-operated control plane and closes with the architecture a reviewer can challenge.

> **Slides:** 1-8 of 26
>
> **Agenda sections:** Why cloud operations must change, Introducing FDAI, Overall architecture

## Proposal opening

### Slide 1. Title

**Decision question:** What operating model is this proposal asking us to consider?

**Key message:** FDAI is an autonomous cloud platform operated by a fixed organization of agents under explicit authority and safety boundaries.

**On-slide copy:**

- **Forward Deployed Agents**
- **An Autonomous Cloud Platform Operated by Agents**
- Proposal for a measurable, observation-first adoption

**Visual:** A quiet white field with one thin event path connecting signal, decision, action, and evidence. Keep the title as the first-viewport signal.

**Evidence to bring:** Proposal owner, review date, and approved delivery classification.

**Presenter note:** Do not explain features on the cover. State the operating-model proposition and move to the agenda.

### Slide 2. Agenda

**Decision question:** Which questions will this proposal answer?

**Key message:** The proposal progresses from need, to system design, to operational control, to adoption.

**On-slide copy:**

1. Why cloud operations must change
2. Introducing FDAI
3. Overall architecture
4. Meet the 15 agents
5. How AI agents collaborate
6. Operating scenarios
7. When people step in
8. Areas of operations automation
9. Expected outcomes
10. Demo
11. Adoption approach

**Visual:** A numbered two-column contents page with no icons or card chrome.

**Evidence to bring:** The agreed review objective: architecture review, pilot sponsorship, or operating-model alignment.

**Presenter note:** Name the decision expected at the end. Avoid presenting the agenda as a feature list.

## Why cloud operations must change

### Slide 3. The operating load scales faster than the team

**Decision question:** Is the current operating model able to absorb more resources, policies, and events without adding the same amount of manual coordination?

**Key message:** Cloud scale multiplies small decisions, while ticket queues and dashboards still serialize those decisions through people.

**On-slide copy:**

| Operating signal | Current handoff | Structural constraint |
|------------------|-----------------|-----------------------|
| Incident or anomaly | Alert to operator | Context is rebuilt for each event. |
| Infrastructure change | Ticket and review | Safety checks differ by team and tool. |
| Cost or capacity drift | Report and follow-up | Detection and correction are separated. |
| Recovery readiness | Scheduled exercise | Evidence arrives after the risk window. |

**Visual:** Four operating loops converging on one human queue, with elapsed time shown as waiting rather than execution.

**Evidence to bring:** Customer-approved baseline counts for alerts, handoffs, recurring tasks, and review delay. Leave values blank if they are not measured.

**Presenter note:** Replace generic examples with the top three approved recurring events. Do not invent an automation percentage.

### Slide 4. Earlier automation stops at known paths

**Decision question:** Why are scripts, alerts, and assistants not enough on their own?

**Key message:** Existing tools automate individual steps, but they do not provide a shared authority model for deciding, approving, executing, recovering, and proving outcomes.

**On-slide copy:**

| Approach | What it does well | Where the operating gap remains |
|----------|-------------------|---------------------------------|
| Scripts and runbooks | Repeat a known procedure | Weak coordination across changing context. |
| Monitoring and alerts | Detect and notify | The operator still rebuilds evidence and chooses the action. |
| Workflow automation | Route approvals and tasks | The workflow owns the path, not the decision quality. |
| General assistants | Explain and propose | Authority, execution, rollback, and audit need separate controls. |

**Visual:** One horizontal comparison table. Use checkmarks sparingly and avoid winner-versus-loser styling.

**Evidence to bring:** Current toolchain map and one example that crosses monitoring, ticketing, execution, and audit systems.

**Presenter note:** Treat current investments as inputs to FDAI, not as failed attempts that must be replaced.

## Introducing FDAI

### Slide 5. FDAI changes the unit of automation

**Decision question:** What is different about FDAI?

**Key message:** FDAI assigns enduring operational responsibilities to independently runnable agents instead of assembling another centralized workflow.

**On-slide copy:**

- **Agent-driven:** Each capability has a named owner and a schema-validated event contract.
- **Deterministic first:** Repeatable decisions use rules and policy before adaptive reasoning.
- **Safe autonomy:** Every action carries stop, rollback, impact, dry-run, lock, retry, and audit controls.
- **Evidence governed:** Every decision can be attributed, inspected, and replayed.
- **Secure boundaries:** Approval, execution, and human identity remain separate.

**Visual:** Five operating principles arranged around the statement "responsibility is the unit of automation." Use plain typography and thin connectors.

**Evidence to bring:** Links to the architecture principles and the action contract used in the demo.

**Presenter note:** The claim is structural, not that one model can operate the cloud without controls.

### Slide 6. The platform is autonomous because authority is bounded

**Decision question:** What prevents an agent from taking an action outside its mandate?

**Key message:** FDAI makes trust inspectable by separating who observes, judges, approves, executes, recovers, and audits.

**On-slide copy:**

| Responsibility | Named owner | Boundary |
|----------------|-------------|----------|
| Observe and normalize | Huginn and Heimdall | Cannot execute changes. |
| Judge | Forseti | Cannot approve or execute its own decision. |
| Carry human approval | Var | Cannot impersonate the executor. |
| Dispatch and recover | Thor and Vidar | Can run only typed, gated actions. |
| Preserve evidence | Saga | Append-only audit role. |

**Visual:** Five equal columns with clear separation and no shared identity spanning the columns.

**Evidence to bring:** One action record showing initiator, judge, approver, executor, auditor, and stable correlation identifiers.

**Presenter note:** Use this slide to define autonomy as bounded decision and action, not unrestricted change.

## Overall architecture

### Slide 7. One control plane, five responsibility layers

**Decision question:** Where does FDAI sit in the existing cloud operating stack?

**Key message:** FDAI adds a governed control plane above provider APIs and below operator channels, while preserving provider-neutral contracts around an Azure implementation.

**On-slide copy:**

1. **Signals and providers:** Azure events, inventory, telemetry, policy, cost, and delivery adapters.
2. **Typed event fabric:** Schema validation, ownership, correlation, and replay.
3. **Agent control plane:** Fifteen fixed agents for sensing, judgment, action, governance, and domains.
4. **Safety and evidence:** Risk decisions, approval, locks, rollback, and audit.
5. **Operator experience:** Read-only console, conversation, notifications, and approval channels.

**Visual:** Five unframed horizontal bands. Show provider APIs at the bottom and people at the top. Do not draw the console as the control plane.

**Evidence to bring:** Current integration map and the provider adapters selected for the pilot.

**Presenter note:** Azure is the implemented target. Avoid implying that other cloud adapters already exist.

### Slide 8. Every event follows the same governed path

**Decision question:** Can reviewers trace how a signal becomes an action?

**Key message:** Signals move through normalization, decision tier selection, verification, risk classification, execution or approval, and evidence capture.

**On-slide copy:**

```text
Signal -> Normalize -> Correlate -> Choose decision tier -> Verify
       -> Classify risk -> Auto / Human approval / Block -> Execute or hold
       -> Verify outcome -> Audit
```

- Missing evidence produces review or a blocked action, not a guessed change.
- The same correlation and retry identity follows the event through the terminal state.
- The console reads the resulting state; it does not become a second execution path.

**Visual:** A left-to-right pipeline with one three-way branch at the risk decision and a return path from outcome verification to recovery.

**Evidence to bring:** A synthetic end-to-end trace used again in Slides 14-18 and in the demo.

**Presenter note:** Keep one scenario across the proposal so the architecture, human control, demo, and measures connect.

## Next steps

| To continue | Read |
|-------------|------|
| Meet the 15 agents and follow their collaboration | [Act 2](l100-act2-how.md) |
| Review the architecture source of truth | [Project structure](../../roadmap/architecture/project-structure.md) |
| Review the fixed organization | [Agent pantheon](../../roadmap/agents/agent-pantheon.md) |
