---
title: "Deck Act 2: How it works and what you get"
description: Slides 11-21 of the FDAI L100 deck - the event loop, the trust tiers, the safety boundaries, the three verticals, and the demo and console slots.
---

# Deck Act 2: How it works and what you get

Slides 11-21 answer two questions in order: how does one event actually get
handled, and what stops a bad action. Only then does the deck show outcomes per
vertical and hand over to the demo.

Read [the deck kit](README.md) first for density levels, timing, and the slots
you fill per customer.

## Slide 11. The journey of one event

- **Headline**: Every signal takes the same governed path.
- **Density**: `Detailed`
- **Body** - five steps, one line each
  - Ingest and correlate: validate the schema, drop repeats with a key that makes
    a retry safe, and group related signals into one incident.
  - Route to the lowest tier that can decide.
  - Verify before classifying risk: a model-proposed action passes cross-model
    agreement, an evidence check, and schema, policy, security, and what-if
    checks.
  - Apply the safety check: action risk, impact scope, system health, and policy
    produce one of automatic, human approval, or blocked.
  - Execute once and record every path: a per-resource lock, an action that is
    safe to retry, and an audit entry for approvals, rejections, timeouts,
    rollbacks, and no-ops alike.
- **Visual**: A horizontal pipeline, simplified from the architecture flow
  diagram, with the three safety-check outcomes branching at the end.
- **Speaker notes**: Walk one concrete event end to end, ideally the same
  scenario the demo on slide 20 uses.
- **Sources**: [FDAI architecture](../architecture.md)

## Slide 12. Deterministic first

- **Headline**: Reasoning is the exception, not the default.
- **Density**: `Detailed`
- **Body**
  - T0, deterministic rules: policy-as-code decisions with a known correct
    answer. No model call. Target coverage 70-80%.
  - T1, lightweight reuse: pattern matching, similarity over past resolved
    incidents, and small classifiers. Target 15-20%.
  - T2, grounded reasoning: frontier models with cross-model agreement, a
    deterministic verifier, and an evidence check. Target 5-10%.
  - These are design targets, not measured results. FDAI reports coverage only
    against a measured baseline.
- **Visual**: A funnel with the three tiers, each band labeled with its target
  share and the words "target, not a claim".
- **Speaker notes**: Say the last bullet out loud. Volunteering the limit of the
  claim is what makes the rest of the numbers credible.
- **Sales angle**: Cost and predictability both follow from this slide - most
  events never reach a model call.
- **Sources**: [Deterministic first](../concepts/deterministic-first.md),
  [Goals and metrics](../../roadmap/architecture/goals-and-metrics.md)

## Slide 13. Every action carries its own safety contract

- **Headline**: Nothing is improvised. Every change is an instance of a typed
  action.
- **Density**: `Detailed`
- **Body**
  - Each change FDAI can make is a catalog entry kept as code, not a free-form
    instruction.
  - The type carries a stop condition, a rollback path, an impact scope limit, a
    dry run, a per-resource lock, a key that makes a retry safe, and an audit
    record. A concrete action inherits all of them.
  - The safety check then routes the action to automatic, human approval, or
    blocked, based on risk, scope, system health, and policy.
- **Visual**: One action card blown up, with each safety field labeled and a
  callout that the fields are inherited, not written per incident.
- **Speaker notes**: This is the answer to "what if the model asks for something
  destructive". An action that has no type can't be produced at all.
- **Sources**: [Ontology-driven automation](../concepts/ontology-driven-automation.md),
  [Trust tiers](../concepts/risk-tiers.md)

## Slide 14. Observation mode, then changes enabled

- **Headline**: New capability watches before it's allowed to touch anything.
- **Density**: `Standard`
- **Body**
  - Every new rule or action ships in observation mode: it decides and logs, but
    applies nothing.
  - It moves to enforcement mode only after its measured accuracy holds and its
    guard metrics haven't regressed.
  - If a guard metric regresses later, the capability returns to observation mode
    automatically.
- **Visual**: A timeline from install to observation to a promotion gate to
  enforcement, with a return arrow labeled "automatic".
- **Speaker notes**: Pair this with the pilot on slide 26. Day 1 of a pilot is
  always observation mode, so the first weeks carry no change risk.
- **Sales angle**: Direct answer to "will this start changing our production on
  day one". It can't.
- **Sources**: [Observation mode](../concepts/shadow-then-enforce.md)

## Slide 15. Where people stay in the loop

- **Headline**: The approver and the executor are never the same identity.
- **Density**: `Standard`
- **Body**
  - Approval requests arrive as cards in Teams or Slack with the decision, the
    evidence, and the rollback path attached.
  - Human roles and the executor identity are separate principals, and
    self-approval isn't allowed.
  - If the approval channel is down, high-risk work waits instead of proceeding
    unapproved.
- **Visual**: An approval card mockup on the left, and an identity boundary
  diagram on the right showing the approver and executor as separate principals.
- **Sources**: [Approvals and channels](../concepts/approvals-and-channels.md),
  [Approve a change](../guides/approve-change.md)

## Slide 16. Evidence on every path

- **Headline**: Automatic, blocked, timed out, rolled back, no-op - all recorded
  the same way.
- **Density**: `Standard`
- **Body**
  - The audit trail is append-only and covers outcomes that changed nothing, not
    only outcomes that acted.
  - Each entry ties the decision to the evidence, the rule or model path, the
    approver, and the rollback reference.
  - The operator console reads projections only. It holds no permission to
    execute and can't approve.
- **Visual**: One audit entry expanded into its fields, with the console shown
  read-only beside it.
- **Speaker notes**: Compliance-driven customers often buy on this slide. Offer
  to walk one real entry during the demo.
- **Sources**: [Read the audit log](../guides/read-audit-log.md)

## Slide 17. Outcome - resilience

- **Headline**: Recovery is proven on a schedule, not discovered during an
  outage.
- **Density**: `Detailed`
- **Body**
  - Disaster-recovery rehearsals run inside a defined exercise window and record
    their outcome.
  - Database exercises restore against your target recovery point and recovery
    time, and flag gaps before they matter.
  - Fault-injection experiments stay inside a declared impact scope.
  - Failures that match a resolved incident are fixed automatically. Novel ones
    escalate to you.
  - Example: a nightly job finds a point-in-time-restore gap on a critical
    database, a paired restore drill is scheduled inside the exercise window, the
    restore meets the targets, and the audit entry is written.
  - Measured as: time to resolve (median and p90) and the share of events
    resolved with no human touchpoint. Guard metrics: rollback rate and missed
    detection rate.
- **Visual**: A drill calendar strip above an outcome-metric row with empty
  baseline and target cells.
- **Sources**: [Resilience](../capabilities/resilience.md)

## Slide 18. Outcome - change safety

- **Headline**: Every change is evaluated before it can reach production.
- **Density**: `Detailed`
- **Body**
  - Each proposed change is dry-run against policy-as-code before anything is
    applied.
  - Configuration that diverges from its declared state is detected and either
    corrected automatically or raised for review.
  - Low-risk changes merge on their own. High-risk changes wait for your
    approval.
  - Changes ship as pull requests, so the change record and the rollback path
    already live in git.
  - Example: an infrastructure pull request proposes a public-egress network
    rule, the safety check marks it high risk, an approval card arrives in the
    channel, the approver accepts, and the fix merges with its audit entry.
  - Measured as: change lead time (median and p90). Guard metrics: change failure
    rate must not increase, and policy-violation escapes must be zero.
- **Visual**: A change pipeline with the safety check as a fork, and the two
  guard metrics pinned as red-line markers.
- **Sources**: [Change safety](../capabilities/change-safety.md)

## Slide 19. Outcome - cost governance

- **Headline**: Waste is removed automatically only where removal is safe.
- **Density**: `Detailed`
- **Body**
  - Spend that deviates from the expected baseline raises a detected issue.
    Detection alone never acts.
  - Over-provisioned resources are flagged with a concrete, reversible fix.
  - The low-risk subset - idle disk cleanup, unused public IP release, orphan
    network interface removal - runs on its own with a rollback path.
  - Anything with real impact scope waits for approval.
  - Example: a cost anomaly fires on an over-provisioned cache tier, a
    deterministic rule matches, two weeks of observation mode prove the rule,
    the action moves to enforcement mode, and the right-sizing fix ships as a
    pull request with a rollback path.
  - Measured as: cost per optimization. Guard metric: rollback rate must not
    increase. FDAI never claims a savings multiplier without a paired
    measurement.
- **Visual**: A two-column split - "acts on its own" versus "waits for you" -
  with the example actions listed under each.
- **Sources**: [Cost governance](../capabilities/cost-governance.md)

## Slide 20. Demo

- **Headline**: One event, end to end, in five minutes.
- **Density**: `Standard`, with detailed presenter instructions
- **Body**
  - Video slot: 4-6 minutes, plays without sound, Korean captions burned in.
  - Scenario beats: a drift signal arrives, the deterministic tier decides, the
    approval card appears in the channel, the approver accepts, the fix ships as
    a pull request, and the audit entry closes the loop.
  - Set up in 30 seconds before playing: name the event and what to watch for.
  - Close in 30 seconds after playing: point back to the safety fields from slide
    13 that appeared on screen.
  - Keep three fallback stills on the following hidden slide in case playback
    fails.
- **Visual**: Video frame centered, with the five scenario beats as a caption
  strip beneath it so the story survives a playback failure.
- **Speaker notes**: Don't narrate over the video. Let it run, then interpret.
- **Sales angle**: Pick the scenario closest to the customer's environment. A
  recognizable resource type matters more than a spectacular fix.

## Slide 21. What operators see

- **Headline**: A read-only console over the same audit trail.
- **Density**: `Standard`
- **Body**
  - Screenshot slots: decision detail with its evidence, pending approvals,
    audit history, and the ownership view.
  - The console shows state and evidence. It doesn't hold the executor identity
    and can't approve or change anything.
  - Operators can ask questions in their own language, and the answer is built
    from the same records the audit trail holds.
- **Visual**: Four screenshots in a 2x2 grid with a "read-only" badge across the
  set.
- **Speaker notes**: Screenshots use demo data only. Never capture a customer
  environment for this slide.

## Next steps

| To learn about | Read |
|----------------|------|
| The final ten slides | [Act 3 - Adopt, deliver, and measure](l100-act3-adopt.md) |
| The earlier slides | [Act 1 - Why now and what FDAI is](l100-act1-why.md) |
| Deck rules, timing, and asset slots | [FDAI L100 deck kit](README.md) |
