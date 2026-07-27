---
title: "Deck Act 1: Why now and what FDAI is"
description: Slides 1-10 of the FDAI L100 deck - the operational pain, why earlier automation stalled, the FDAI definition, and the agent-driven architecture.
---

# Deck Act 1: Why now and what FDAI is

Slides 1-10 move the room from "this is our daily reality" to "this is what an
agent-driven control plane changes". Act 1 spends more time on the customer's
world than on FDAI, and it introduces the architecture only after the audience
has agreed on the problem.

Read [the deck kit](README.md) first for density levels, timing, and the slots
you fill per customer.

## Slide 1. Title

- **Headline**: FDAI - an agent-driven control plane for cloud operations.
- **Density**: `Light`
- **Body**: Product name, one-line subtitle ("Agents handle the repeatable
  majority. You decide the risky few."), presenter name and date placeholders.
- **Visual**: Full-bleed [nebula-2000x1125.png](nebula-2000x1125.png) with the
  title block bottom-left.
- **Speaker notes**: Open with the promise of the session in one sentence, then
  move on. Don't explain the product on the title slide.
- **Sources**: [Get started with FDAI](../get-started.md)

## Slide 2. What you'll take away

- **Headline**: Four questions, answered in 45 minutes.
- **Density**: `Light`
- **Body**: Four numbered blocks - What is FDAI? How does it stay safe? What
  improves for us? How do we start?
- **Visual**: Four blocks across the slide with a progress marker reused as a
  running header on later section dividers.
- **Speaker notes**: Ask the room which of the four matters most, and adjust
  depth later. This is the only interactive moment in Act 1.
- **Sales angle**: The answer you hear here tells you whether to lead with
  resilience, change safety, or cost governance on slides 17-19.

## Slide 3. The operating reality today

- **Headline**: Most operational work is the same work, repeated.
- **Density**: `Detailed`
- **Body**
  - The same event classes return week after week: configuration drift, policy
    violations, capacity and cost regressions, recovery gaps.
  - Each one costs a human pass: notice, interpret, check the runbook, decide,
    apply, and write it down.
  - Change lead time is dominated by waiting, not by working.
  - Recovery paths are documented more often than they're exercised.
  - Evidence for auditors is reassembled by hand after the fact.
- **Visual**: A one-day operations timeline with the repeated events highlighted,
  plus an empty baseline table (`Event class | Volume per week | Human minutes
  each`) the customer fills in.
- **Speaker notes**: Use the customer's own words from the pre-meeting interview
  in the quote slot. If the room doesn't recognize this slide, stop and ask what
  their real top three are before continuing.
- **Sales angle**: This is the slide where the customer decides whether the rest
  of the deck is about them. Don't rush it.
- **Sources**: [Goals and metrics](../../roadmap/architecture/goals-and-metrics.md)

## Slide 4. Why earlier automation stalled

- **Headline**: The bottleneck was never execution. It was trustworthy judgment.
- **Density**: `Standard`
- **Body**
  - Scripts and runbooks automate the steps but not the decision, so they break
    when conditions shift and they decay when their author moves on.
  - Alert automation routes faster but still ends at a person, because nothing in
    the chain is allowed to decide.
  - A single general-purpose assistant can suggest an action, but with no
    ownership boundary, no approval path, and no audit trail, nobody lets it act.
- **Visual**: Three columns with a "where it stops" marker at the bottom of each.
- **Speaker notes**: Name the pattern the customer already tried. Agreeing that
  their previous attempt was reasonable buys credibility for the next slide.

## Slide 5. Why this is possible now

- **Headline**: Machine-readable operations finally exist.
- **Density**: `Standard`
- **Body**
  - Infrastructure-as-code and policy-as-code (policies expressed as
    machine-readable rules) turn intent into facts a system can evaluate.
  - Cloud platforms emit resource-change and activity signals as streams, so
    detection no longer depends on scraping.
  - Agent design matured past chat: named roles, owned object types, and
    schema-checked contracts make autonomy reviewable.
- **Visual**: Three enabling layers stacked under a single "now feasible" band.

## Slide 6. What FDAI is

- **Headline**: Rules settle the repeatable majority. Judgment is reserved for
  the ambiguous few.
- **Density**: `Detailed`
- **Body**
  - One-line definition: an autonomous cloud operations control plane that
    resolves repeatable operational events with rules, policies, and typed
    actions, and reserves model-based reasoning for the cases the deterministic
    path can't decide.
  - The five operating principles, one line each: rules before reasoning;
    observe, then enable changes; safety-gated autonomy; separated authority;
    evidence on every path.
  - Azure is the implemented target, and cloud calls go through provider
    contracts, so decision logic isn't rewritten if the host changes.
- **Visual**: The definition as a single centered sentence, with the five
  principles as numbered chips underneath.
- **Speaker notes**: Read the definition verbatim. It's the sentence the audience
  repeats to colleagues who weren't in the room.
- **Sources**: [Get started with FDAI](../get-started.md)

## Slide 7. Agent-driven architecture

- **Headline**: Not one assistant with broad permissions - an organization of
  agents with separated authority.
- **Density**: `Detailed`
- **Body**
  - Every capability belongs to an agent that can run independently and
    concurrently.
  - Each agent has one mandate, the object types it owns, the topics it
    subscribes to, and bounded permissions.
  - Agents collaborate only through a schema-checked event bus. Direct calls,
    remote procedure calls, implementation imports, and shared mutable workflow
    state aren't allowed.
  - The effect: observing, deciding, approving, executing, and recording never
    collapse into one component that can quietly do all five.
- **Visual**: Left, a monolithic assistant with every arrow pointing into one
  box. Right, the same arrows separated across named agents. Same inputs, same
  outputs, different accountability.
- **Speaker notes**: This is the slide the deck is built around. State it plainly:
  the reason FDAI can be trusted with autonomy is structural, not a matter of
  model quality.
- **Sales angle**: This is the direct answer to "how do we know the AI won't do
  something unexpected". The answer is a boundary, not a promise.
- **Sources**: [FDAI architecture](../architecture.md)

## Slide 8. The 15 agents and what each one owns

- **Headline**: A fixed organization, so authority can't be renamed or merged.
- **Density**: `Detailed`
- **Body** - five groups, one line each
  - Sense: Huginn owns normalized events and resource discovery. Heimdall owns
    anomaly, drift, and forecast detected issues.
  - Judge: Forseti issues decisions. Odin resolves cross-vertical conflicts
    first.
  - Act, approve, recover, explain: Thor is the only privileged executor. Var
    carries human approval. Vidar owns rollback. Bragi translates operator
    conversations.
  - Govern evidence: Saga owns the append-only audit trail. Mimir owns rules.
    Norns proposes inert rule candidates. Muninn owns state and context.
  - Domain evidence: Njord (cost), Freyr (capacity), and Loki (fault exercises)
    advise judgment and never execute.
  - The 15 roles are fixed by the product. A deployment binds providers, tunes
    thresholds, and adds catalog entries. Audit and rollback can't be turned off.
- **Visual**: Five colored groups in an org-chart layout, with a lock icon on the
  audit and rollback nodes.
- **Speaker notes**: Don't read all 15 names. Read the five group labels and
  point at the two locked nodes.
- **Sources**: [FDAI architecture](../architecture.md),
  [Agents and self-healing](../concepts/agents-and-self-healing.md)

## Slide 9. One writer per object type

- **Headline**: Knowing a topic name isn't the same as holding authority over it.
- **Density**: `Standard`
- **Body**
  - Information fans out to many readers, but each authoritative object type has
    exactly one writer.
  - Normalized events come only from Huginn, decisions only from Forseti,
    privileged execution only from Thor, approvals only from Var, rollback only
    from Vidar, audit entries only from Saga.
  - The runtime checks ownership on publish. A record that claims a producer
    which doesn't own the topic is routed to the dead-letter queue.
- **Visual**: A fan-out diagram, read paths thin and many, write paths thick and
  single, with a lock on each writer.
- **Speaker notes**: Security and architecture reviewers care most about this
  slide. In a sales-led session, give it 30 seconds and offer the deep dive as a
  follow-up.
- **Sources**: [FDAI architecture](../architecture.md)

## Slide 10. What actually changes

- **Headline**: The loop you run by hand becomes a loop that runs continuously.
- **Density**: `Light`
- **Body**
  - Before: people detect, interpret, decide, apply, and document, event by
    event.
  - After: agents run that loop continuously, and people set policy, handle
    exceptions, approve the risky few, and improve the rules.
- **Visual**: Two circular loops side by side. Left loop has a person icon at
  every step. Right loop has agents at each step and a person at the approval and
  policy positions only.
- **Speaker notes**: Close Act 1 here and pause. If the room accepts this slide,
  Act 2 becomes a "how" conversation instead of a "why" argument.

## Next steps

| To learn about | Read |
|----------------|------|
| The next ten slides | [Act 2 - How it works and what you get](l100-act2-how.md) |
| Deck rules, timing, and asset slots | [FDAI L100 deck kit](README.md) |
| The architecture behind slides 7-9 | [FDAI architecture](../architecture.md) |
