---
title: "Deck Act 3: Adopt, deliver, and measure"
description: Slides 22-30 of the FDAI L100 deck - the operating-model shift, ownership, the repeatable delivery kit, onboarding, metrics, objections, and next steps.
---

# Deck Act 3: Adopt, deliver, and measure

Slides 22-30 answer the question every room reaches after the demo: what does
this mean for our team, how long does it take, and what do we commit to. Act 3
is also the part of the deck that stays identical across customers, which is
what makes the delivery repeatable.

Read [the deck kit](README.md) first for density levels, timing, and the slots
you fill per customer.

## Slide 22. How the operating model shifts

- **Headline**: The work doesn't disappear. It moves up a level.
- **Density**: `Detailed`
- **Body** - a three-column table (`Operational step | Today | With FDAI`)
  - Detect: someone notices an alert - agents normalize and correlate signals
    continuously.
  - Classify: a person reads the runbook - deterministic rules decide, and only
    ambiguous cases reach model-based reasoning.
  - Act: a person applies the change - the executor applies a typed action with
    a rollback path.
  - Approve: an ad-hoc chat thread - a structured approval card with the evidence
    attached.
  - Prove: evidence collected after the fact - an audit entry written on every
    path, including the paths that changed nothing.
  - Improve: tribal knowledge - rule candidates proposed from outcomes and
    reviewed by your team.
  - What people newly own: policy definition, exception judgment, approvals, and
    rule review. What never moves: final responsibility.
- **Visual**: The table, with the "With FDAI" column color-coded to show which
  cells are agent-run and which stay human.
- **Speaker notes**: Say the last bullet explicitly. The most common internal
  objection isn't technical, it's "what happens to my team".
- **Sales angle**: Position this as role elevation, not headcount reduction. The
  same team covers more surface with a shorter queue.

## Slide 23. Every agent has an accountable owner

- **Headline**: Automation without a named owner is just an unowned system.
- **Density**: `Standard`
- **Body**
  - Each of the 15 agents maps to a named person or team, so escalation and
    review always have a destination.
  - Ownership is an accountability overlay, not a permission grant. Being the
    owner of an agent's domain doesn't hand anyone the executor identity.
  - If an agent has no live owner, escalation moves to the final owner rather
    than leaving the domain silently unowned.
  - The ownership map is reviewed like any other governed change and shows up in
    the read-only console.
- **Visual**: The 15-agent org chart from slide 8, with a person or team badge
  attached to each node and one node highlighted as unowned to show the fallback
  path.
- **Speaker notes**: This slide converts "we're handing operations to a machine"
  into "we're handing operations to a machine that a named person supervises".
- **Sources**: [Agent operational ownership and ownership handover](../../roadmap/interfaces/agent-stewardship-and-handover.md)

## Slide 24. Delivery is onboarding, not a build

- **Headline**: The product stays fixed. Only your context is loaded.
- **Density**: `Detailed`
- **Body**
  - Fixed for every customer: the control loop, the event contracts, the 15
    agent roles, and the safety invariants.
  - Loaded per customer: rules, action types, policies, deployment configuration,
    and adapter bindings.
  - Nothing customer-specific is written into the core, so every deployment keeps
    receiving product improvements instead of drifting into a private branch.
  - Consequence for the customer: predictable scope, a shorter first delivery,
    and upgrades that don't require re-testing bespoke code.
- **Visual**: Two concentric rings. The locked inner ring is the product, and the
  outer ring holds the five swappable layers from slide 25.
- **Speaker notes**: This is the slide that makes a second and third delivery
  cheaper than the first. Say that plainly to a sponsor who's thinking about
  scale-out.
- **Sources**: [Downstream fork guide](../../roadmap/fork-and-sequencing/downstream-fork-guide.md)

## Slide 25. The five customization seams

- **Headline**: Five places to change. No sixth.
- **Density**: `Detailed`
- **Body** - a table (`Seam | What you change | Code change needed | How it's verified`)
  - Rule catalog: which conditions produce which decision. No code change.
    Verified by regression tests and an observation-mode run.
  - Action types: which changes are possible at all, each with its own safety
    contract. No code change. Verified by catalog schema checks and a dry run.
  - Policies: the machine-readable rules the deterministic tier evaluates. No
    code change. Verified by policy tests.
  - Deployment configuration: tenant identity, resource scope, secret references,
    environment. No code change, and these values stay out of source control.
  - Adapters: approval channel, model provider, search, and scope resolution,
    bound at startup. Implementation only, never a change to the core.
  - Anti-patterns to call out: editing the core for one customer, and hard-coding
    tenant values into rules.
- **Visual**: The table, with a lock icon in a sixth row labeled "core - not a
  customization point".
- **Speaker notes**: Technical buyers ask "how much of this is bespoke for us".
  This slide answers with a bounded list.

## Slide 26. The first month

- **Headline**: Read-only on day one. Changes only after they're proven.
- **Density**: `Detailed`
- **Body**
  - Day 1: deploy into the target subscription and start observing. Everything
    runs in observation mode, and nothing is applied.
  - Week 1: measure the baseline, connect the approval channel, and turn the top
    repeated event classes into rules.
  - Month 1: enable changes for the low-risk subset that cleared its promotion
    gate, then extend to the second vertical.
  - Pilot scope slot: one subscription, resource group, or workload agreed with
    the customer.
  - Exit criteria for the pilot are agreed up front: a measured baseline, a
    target set of event classes covered, and zero policy-violation escapes.
- **Visual**: A three-column timeline with a "no changes applied" band across
  Day 1 and Week 1.
- **Sources**: [Deploy and onboard](../../roadmap/deployment/deploy-and-onboard.md),
  [Deploy quickstart](../deploy-quickstart.md)

## Slide 27. What we measure

- **Headline**: A baseline first. Claims after.
- **Density**: `Detailed`
- **Body**
  - Directional metrics: time to resolve, share of events resolved with no human
    touchpoint, change lead time, and cost per optimization.
  - Guard metrics that may not regress: rollback rate, change failure rate,
    missed detection rate, and policy-violation escapes, which stay at zero.
  - Every metric is reported as median and p90, not as an average alone.
  - Empty table slot (`Metric | Your baseline | Target | How it's measured`) that
    the customer fills during the baseline workshop.
- **Visual**: Two metric groups side by side, directional metrics with up or down
  arrows and guard metrics with red-line markers.
- **Speaker notes**: Refuse to give a savings multiplier here, and explain why:
  an unmeasured number is the fastest way to lose a technical room.
- **Sources**: [Goals and metrics](../../roadmap/architecture/goals-and-metrics.md)

## Slide 28. Is this a fit yet

- **Headline**: Four conditions, answered honestly.
- **Density**: `Standard`
- **Body**
  - Do operators repeatedly approve or roll back the same event classes? If not,
    there's nothing repeatable to automate yet.
  - Is infrastructure expressed as infrastructure-as-code and policy-as-code? The
    deterministic tier needs machine-readable rules.
  - Can a baseline be reproduced? Without it, no improvement can be proven.
  - Are you on Azure? Azure is the implemented target today.
  - Prerequisites to line up: subscription permissions, event sources, an
    approval channel, and region and quota headroom.
- **Visual**: The four-question decision flow, with "not a fit yet" endpoints
  drawn as neutral, not as failures.
- **Speaker notes**: Disqualifying honestly on this slide protects the pilot. A
  customer without a baseline should start with the baseline workshop only.
- **Sources**: [Get started with FDAI](../get-started.md)

## Slide 29. The questions you're about to ask

- **Headline**: The five objections, answered in one line each.
- **Density**: `Detailed`
- **Body**
  - "Will it change things on its own?" Only capabilities that cleared their
    promotion gate, only within their impact scope, and only when the safety
    check returns automatic.
  - "What if it's wrong?" A rollback path ships with the action, the outcome is
    audited, and a regression returns the capability to observation mode.
  - "Does our data go to a model?" Most events never reach a model call, and the
    ones that do pass an evidence check and a deterministic verifier before
    anything can run.
  - "Are we locked in?" Rules and policies are data, cloud calls sit behind
    provider contracts, and changes are delivered as pull requests in your own
    repository.
  - "What happens to our team?" The team moves from executing steps to owning
    policy, exceptions, and approvals.
- **Visual**: Five question-and-answer rows, with the question in large type and
  the answer beneath.
- **Speaker notes**: Deliver this slide even if nobody asked. Naming the
  objection first is what makes the answer land.

## Slide 30. Next steps

- **Headline**: Three commitments, in order.
- **Density**: `Standard`
- **Body**
  - Baseline workshop, half a day: agree the event classes, the metrics, and how
    they're measured.
  - Observation-mode pilot, 2-4 weeks: deploy into the agreed scope, apply
    nothing, and produce measured evidence.
  - Promotion review: decide together which low-risk actions get changes enabled,
    and what the second vertical is.
  - Owner and date slots for each step.
  - Reading list for the room: get started, architecture, and the capability page
    matching their lead priority.
- **Visual**: Three numbered commitment cards with an owner and date line under
  each, and a small reading-list block in the corner.
- **Speaker notes**: End on the commitment slide, not on a thank-you slide. Ask
  for the workshop date in the room.
- **Sources**: [Get started with FDAI](../get-started.md),
  [FDAI architecture](../architecture.md)

## Next steps

| To learn about | Read |
|----------------|------|
| The earlier slides | [Act 2 - How it works and what you get](l100-act2-how.md) |
| Deck rules, timing, and asset slots | [FDAI L100 deck kit](README.md) |
| The delivery model behind slides 24-25 | [Downstream fork guide](../../roadmap/fork-and-sequencing/downstream-fork-guide.md) |
