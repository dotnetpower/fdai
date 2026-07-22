---
title: Site Reliability Engineering
description: The SRE operating model in FDAI, from signals and incidents through response, recovery, and learning.
---

# Site Reliability Engineering

Site Reliability Engineering (SRE) is the operating discipline that connects
FDAI's three initial verticals. Change Safety reduces change risk, Cost
Governance controls efficiency, and Resilience proves recovery. SRE brings
those capabilities into one evidence-driven lifecycle for observing,
responding, learning, and preparing.

This section is the operator-facing map. It explains what FDAI implements,
where human approval remains required, and which integrations must be supplied
by a deployment or downstream fork.

## What can you achieve?

### Turn signal storms into incidents

Correlate related resource events, telemetry detected issues, and changes into one
incident with stable membership and chronology.

Example: five alerts share a deployment and resource key -> event correlation
opens one incident -> triage reads one timeline instead of five pages.

### Investigate before proposing a change

Gather bounded evidence, produce grounded root-cause hypotheses, and keep every
mitigation behind the trust router, safety check, and approval policy.

Example: an error-rate alert -> investigation correlates a recent deployment ->
RCA cites the change and telemetry -> a response plan proposes rollback -> human approval
approval decides whether the proposal may re-enter the action pipeline.

### Learn without hiding failures

Use append-only audit history, postmortem drafts, shadow outcomes, and rollback
evidence to improve rules and runbooks without letting a learning component
change policy directly.

Example: a resolved incident -> postmortem extracts the timeline and action
outcome -> a catalog candidate is proposed with provenance -> normal review and
promotion gates still apply.

## Works across your stack

- **Azure signals**: Activity Log events, resource inventory, deployment
  history, and service metrics enter through provider adapters.
- **Telemetry systems**: metric, log, and trace providers supply evidence; they
  do not become a second execution path.
- **Git and ChatOps**: fix pull requests carry changes, while Teams or
  Slack carries approvals and operational notifications.
- **Audit and reporting**: every terminal outcome remains reconstructable from
  the append-only audit record and correlation references.

## How it works

1. **Observe and correlate.** Normalize events and detected issues, deduplicate them,
   and group related members into an incident.
2. **Investigate and respond.** Build a bounded evidence set, derive a grounded
   RCA, and route any proposed mitigation through the governed action pipeline.
3. **Recover and learn.** Verify recovery, write the terminal audit record,
   draft the postmortem, and propose evidence-backed improvements.

```text
signals -> finding -> incident -> investigation -> RCA
        -> response plan -> risk gate -> action or approval
        -> recovery evidence -> postmortem -> improvement candidate
```

## Two decisions govern every response

Trust routing and execution policy answer different questions. The trust router
picks T0 (deterministic rules), T1 (verified reuse), or T2 (grounded reasoning)
to produce a decision candidate. The safety check then computes the strictest
allowed outcome from policy, action type, impact scope, environment, evidence
freshness, identity, and promotion state.

| Decision | Question | Possible result |
|----------|----------|-----------------|
| Trust routing | Which tier can explain or propose? | T0, T1, T2, or hold for review |
| Risk gating | What may this proposal do now? | `auto`, `hil`, `deny`, or shadow-only |
| Execution | Are all runtime safety checks still valid? | Apply once, no-op, stop, or roll back |

A T0 match is not automatic permission to mutate, and a T2 proposal cannot
grant itself authority. Every executable action still needs a dry run,
stop condition, rollback path, impact scope limit, fresh inventory,
per-resource lock, idempotency key, authorized identity, and audit record.

## Degraded operation is an explicit state

FDAI does not translate missing evidence into a healthy system. A provider
failure marks dependent evidence unavailable. Stale inventory, a failed audit
write, an unavailable lock, or an unverified rollback path lowers the affected
action to shadow or deny. Notification failure follows durable retry or
escalation, but never becomes approval and never rolls back an already valid
incident transition.

## SRE capability map

| Area | Read | Upstream status |
|------|------|-----------------|
| Observability, correlation, anomaly, and forecasting | [Observability, detection, and forecasting](observability-detection-and-forecasting.md) | Covered; real telemetry adapters are deployment bindings |
| Workload objectives and burn rate | [SLOs and error budgets](slos-and-error-budgets.md) | Partial until a real metric provider and scheduled trigger are bound |
| Capacity and performance | [Capacity and performance](capacity-and-performance.md) | Covered; autonomous actions remain promotion-gated |
| Incident lifecycle | [Incident management](incident-management.md) | Covered |
| Bounded evidence gathering | [Triage and investigation](triage-and-investigation.md) | Covered; evidence depth depends on providers |
| Root-cause hypotheses | [Root-cause analysis](root-cause-analysis.md) | Covered; T2 depends on configured model and knowledge bindings |
| Response plans and mitigation | [Response plans and mitigation](response-plans-and-mitigation.md) | Covered; plans propose and route, never bypass approval |
| On-call and escalation | [On-call and escalation](on-call-and-escalation.md) | Partial until a paging adapter and direct-message targeting are bound |
| Post-incident learning | [Postmortems and learning](postmortems-and-learning.md) | Covered |
| Outcome measurement | [Measuring SRE outcomes](measuring-sre-outcomes.md) | Covered when baseline and treatment windows exist |
| Scenario evidence | [Scenario validation inventory](scenario-validation-inventory.md) | 18 demo, 10 live enforcement, 9 frozen replay, 132 catalog scenarios |
| Disaster recovery | [Disaster recovery and drills](disaster-recovery-and-drills.md) | Covered for shipped drills and adapters |
| Chaos engineering | [Chaos engineering](chaos-engineering.md) | Covered; every scenario starts in shadow |

> Status page broadcast and DORA deployment metrics remain deferred. They are
> not presented as available SRE features until their provider and data
> contracts are implemented.

## Grows with your environment

- **Day 1**: ingest signals in shadow, confirm incident grouping, and inspect
  evidence without enabling mutation.
- **Week 1**: bind workload metrics, define initial SLOs, connect on-call
  routing, and pretest response plans against synthetic or historical cases.
- **Month 1**: promote measured low-risk actions independently, schedule
  recovery drills, and use postmortem evidence to improve rules and runbooks.

## Get started

- Start with [observability, detection, and forecasting](observability-detection-and-forecasting.md).
- Follow an event through [incident management](incident-management.md).
- Learn how [root-cause analysis](root-cause-analysis.md) stays grounded.
- Review every [scenario validation set](scenario-validation-inventory.md).
- Prepare operator procedures with the [SRE runbook set](../../runbooks/README.md).

## Next steps

| To learn about | Read |
|----------------|------|
| How FDAI chooses T0, T1, or T2 | [Trust tiers](../concepts/risk-tiers.md) |
| How actions inherit safety contracts | [Ontology-driven automation](../concepts/ontology-driven-automation.md) |
| How recovery becomes a product capability | [Resilience](../capabilities/resilience.md) |
| How to inspect the evidence trail | [Read the audit log](../guides/read-audit-log.md) |
| What happens when approval receives no answer | [Escalation and standing authority](../../roadmap/decisioning/escalation-and-standing-authority.md) |
