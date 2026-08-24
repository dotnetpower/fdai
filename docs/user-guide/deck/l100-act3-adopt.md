---
title: "FDAI Proposal Act 3: Scope, Outcomes, Demo, and Adoption"
description: Proposal slides 19-26 covering automation scope, measured outcomes, demonstration, and adoption.
---

# FDAI Proposal Act 3: Scope, Outcomes, Demo, and Adoption

Act 3 turns the architecture into an adoption decision. It defines where automation can begin, how a pilot measures value without overclaiming, what the demo must prove, and which exit criteria govern each expansion of authority.

> **Slides:** 19-26 of 26
>
> **Agenda sections:** Areas of operations automation, Expected outcomes, Demo, Adoption approach

## Areas of operations automation

### Slide 19. Automate by decision class, not by tool

**Decision question:** Which operational work belongs in observation, automatic action, or human approval?

**Key message:** FDAI expands automation only where evidence, action safety, and policy support the specific decision class.

**On-slide copy:**

| Area | Observe and advise | Candidate for automatic action | Keep behind human approval |
|------|--------------------|--------------------------------|----------------------------|
| Resilience | Drift, recovery readiness, experiment results. | Previously promoted low-impact recovery steps. | Failover and chaos experiments with material impact. |
| Change safety | Plan drift, policy violations, dry-run result. | Bounded, reversible corrections after promotion. | Broad scope, identity, network, or data-risk changes. |
| Cost governance | Cost anomaly, idle resource, budget trend. | Low-impact cleanup with verified ownership and rollback. | Commitment, deletion, or capacity trade-offs with material impact. |
| Capacity | Forecast and sizing recommendation. | Narrow, reversible scaling within policy. | Close conflict with cost or resilience objectives. |

**Visual:** One boundary matrix. Use neutral cells and a single blue outline around the selected pilot class, with no colored edge bars.

**Evidence to bring:** Candidate event inventory, action types, impact limits, owners, and current approval rules.

**Presenter note:** Select one decision class for the pilot. A vertical name alone is too broad to authorize automation.

### Slide 20. Authority grows through measured promotion

**Decision question:** How does a capability move from observation to changing resources?

**Key message:** New capabilities start in observation mode and enter enforcement only through an authoritative promotion decision based on measured evidence.

**On-slide copy:**

1. **Register:** Bind scope, owner, action contract, and guardrails.
2. **Observe:** Produce decisions, dry runs, and evidence without applying changes.
3. **Compare:** Measure precision, coverage, review load, rollback readiness, and policy conformance.
4. **Review:** Named owners approve or hold the promotion decision.
5. **Enforce:** Enable only the approved decision class and impact scope.
6. **Demote:** Return to observation when guardrails regress.

**Visual:** A horizontal maturity path with a clear return arrow from enforcement to observation. Keep environment, runtime, and fork as separate labels outside the path.

**Evidence to bring:** Promotion registry entry, target measures, guardrail thresholds, and the owner meeting record.

**Presenter note:** Deployment does not equal promotion. Day 1 can be operationally useful while applying no changes.

## Expected outcomes

### Slide 21. Define value as a measured before-and-after change

**Decision question:** How will the pilot prove value without relying on generic industry claims?

**Key message:** Every benefit pairs an existing baseline, a pilot measure, and a guardrail that prevents improvement in one metric from hiding new risk.

**On-slide copy:**

| Outcome measure | Direction to test | Guardrail |
|-----------------|-------------------|-----------|
| Time from signal to qualified decision | Decrease | Unsupported-decision rate does not rise. |
| Repetitive handoffs per event | Decrease | Required approval separation remains intact. |
| Decisions resolved at T0 or T1 | Increase where evidence supports it | Review and block rates remain visible. |
| Recovery verification time | Decrease | Rollback success and recovery objectives remain within policy. |
| Cost per verified improvement | Decrease | Availability, capacity, and change risk remain within bounds. |

**Visual:** A baseline-to-pilot comparison with a paired guardrail column. Leave numerical fields blank until the baseline workshop.

**Evidence to bring:** Baseline window, event cohort definition, data source, owner, and reporting cadence for each measure.

**Presenter note:** Avoid a savings multiple or automation percentage unless the customer has measured both sides with the same cohort.

### Slide 22. Expected outcomes across the first three domains

**Decision question:** What should improve if the control loop works as designed?

**Key message:** FDAI aims to make resilience, change safety, and cost governance more continuous, explainable, and reversible.

**On-slide copy:**

| Domain | Current constraint | Pilot hypothesis | Evidence of success |
|--------|--------------------|------------------|---------------------|
| Resilience | Recovery confidence depends on periodic exercises. | Continuous evidence finds readiness gaps earlier. | Verified exercises, recovery outcomes, and rollback records. |
| Change safety | Safety checks vary by path and team. | Typed dry runs and policy produce consistent decisions. | Policy result, impact scope, approval, and post-change verification. |
| Cost governance | Detection and correction are separate work queues. | Repeated low-impact opportunities can follow one governed loop. | Qualified anomaly, owner confirmation, measured correction, no guardrail breach. |

**Visual:** Three aligned rows flowing from constraint to hypothesis to evidence. Do not use oversized outcome numbers before measurement.

**Evidence to bring:** One approved scenario and measure set for each domain included in the pilot.

**Presenter note:** A pilot can begin with one domain. The architecture remains the same when another domain is added.

## Demo

### Slide 23. Demo one complete event, not a feature tour

**Decision question:** What must the demo make believable?

**Key message:** The demo should prove the event-to-evidence chain and authority separation in one scenario that remains understandable without narration.

**On-slide copy:**

1. **Signal:** A synthetic cloud event enters through the provider adapter.
2. **Decision:** The agent path produces evidence, tier, and policy result.
3. **Human moment:** A material action waits for an independent approval.
4. **Action and recovery:** The approved typed action runs with dry-run, lock, and rollback.
5. **Evidence:** The console shows the decision, identities, outcome, and accountable owner.

**Visual:** A five-frame filmstrip using actual synthetic console captures. Put captions below the media, not over it.

**Evidence to bring:** Pre-recorded fallback, synthetic payloads, stable local data, and a complete audit trace.

**Presenter note:** The demo proves governance as much as automation. Do not skip the blocked or approval path to save time.

### Slide 24. Demo acceptance criteria

**Decision question:** How will reviewers know the demo showed the real control boundary?

**Key message:** A successful demo exposes both the expected action and the paths that safely refuse to act.

**On-slide copy:**

- The same correlation identity is visible from signal through terminal evidence.
- The decision shows its evidence and selected T0, T1, or T2 tier.
- A missing safety field or disallowed scope is visibly blocked.
- A material action cannot continue without a separate approver identity.
- Retry does not duplicate the action, and a resource lock prevents conflict.
- Outcome verification and rollback state are visible in the audit timeline.
- The operator console remains read-only.

**Visual:** A plain checklist beside one evidence timeline. Avoid success-only green styling; blocked checks are expected proof.

**Evidence to bring:** Demo test record with pass or fail results and links to each artifact.

**Presenter note:** Record any criterion not shown live as residual work. Do not substitute narration for missing evidence.

## Adoption approach

### Slide 25. Adopt in bounded phases

**Decision question:** What work is required before the first controlled automation?

**Key message:** Adoption begins with ownership, scope, and read-only evidence, then expands one measured decision class at a time.

**On-slide copy:**

| Phase | Work | Exit evidence |
|-------|------|---------------|
| 0. Baseline workshop | Select event cohort, measures, owners, and candidate scope. | Signed scope and baseline plan. |
| 1. Foundation | Connect providers, identity, event fabric, state, and read-only console. | End-to-end synthetic trace. |
| 2. Observation pilot | Bind rules, policies, actions, and adapters without applying changes. | Measured decision and guardrail report. |
| 3. Promotion review | Review evidence for one low-impact decision class. | Recorded approve or hold decision. |
| 4. Controlled expansion | Add scope or another domain independently. | New baseline and unchanged safety contract. |

**Visual:** Five numbered phases on one line. Show a decision gate between phases, not a continuous acceleration arrow.

**Evidence to bring:** Named platform, policy, security, operations, and FDAI owners with backup coverage.

**Presenter note:** Customer-specific rules, policy overlays, provider implementations, action entries, and deployment values use supported extension points. Core control-loop changes are outside pilot customization.

### Slide 26. Proposed next decision

**Decision question:** What should the review group authorize now?

**Key message:** Authorize a baseline workshop and observation pilot with explicit scope, measures, owners, and stop conditions before considering enforcement.

**On-slide copy:**

**Proposed commitment**

- One approved event cohort and one candidate decision class.
- Read-only provider access and synthetic demo data.
- Named accountable owners for platform, policy, security, approval, and FDAI maintenance.
- Baseline measures and guardrails agreed before observation begins.
- Promotion reviewed separately after the observation report.

**Decision options**

| Proceed | Refine | Hold |
|---------|--------|------|
| Scope and owners are ready. | A baseline, owner, or guardrail needs definition. | Required identity or evidence boundary cannot be met. |

**Visual:** One decision statement followed by a compact three-column decision table. End with the proposed workshop date and owner, not a generic thank-you slide.

**Evidence to bring:** Draft workshop charter, attendee roles, data request, and observation-pilot exit criteria.

**Presenter note:** The requested decision is permission to measure in observation mode, not permission to enable autonomous changes.

## Next steps

| To act | Read |
|--------|------|
| Plan the baseline workshop | [Deploy and onboard](../../roadmap/deployment/deploy-and-onboard.md) |
| Prepare operational ownership | [Agent ownership and transition](../../roadmap/interfaces/agent-stewardship-and-handover.md) |
| Review the complete proposal source | [Deck kit](README.md) |
