---
title: SRE foundations
description: The core SRE functions FDAI automates, and how each one maps to the control loop, the agents, and the three verticals.
sidebar:
  order: 1
---

# SRE foundations

FDAI is an autonomous take on **Site Reliability Engineering (SRE)**. SRE
defines a set of recurring functions: watch the system, catch regressions, ship
changes safely, plan capacity, control cost, prepare for disaster, and remove
toil. FDAI keeps every one of those functions and changes who runs them.
Repeatable cases become candidates for rule-driven handling, and people stay in
the loop for cases that are new, high risk, or short on evidence. How much runs
automatically is measured after observation-mode evaluation and promotion.

This page is the map. It lists the SRE functions FDAI covers, what each one
does, and where to read the mechanism in depth.

## The functions FDAI automates

| SRE function | What it does in FDAI | Vertical / owner |
|--------------|----------------------|------------------|
| Monitoring and observability | Takes in resource-change signals, activity-log events, and detected issues, then correlates them into incidents | Heimdall, Huginn |
| Incident detection and response | Routes each signal by confidence, decides a decision, and acts or escalates | trust-router, Forseti |
| Change management | Gates every proposed change against policy-as-code before it ships | Change Safety |
| Capacity and performance | Detects sizing gaps and proposes or runs promoted scaling actions against measured demand | Freyr, Cost Governance |
| Cost and efficiency | Detects spend anomalies and evaluates promoted waste-removal candidates | Njord, Cost Governance |
| Reliability and disaster recovery | Plans and runs promoted DR drills, restore exercises, and bounded chaos experiments | Resilience, Loki, Vidar |
| Toil elimination | Moves proven repeatable cases from manual handling to deterministic rules | deterministic-first |
| Postmortem and learning | Records an append-only audit entry for every action and proposes catalog updates from operating signals | Saga, Norns |

## Monitoring and observability

FDAI is event-driven, not a polling dashboard. Resource changes, activity-log
events, and issues detected by anomaly or forecast checks all arrive on the event
bus. The sensing agents normalize them, drop duplicates, and correlate them into
incidents, so one root event does not get counted as ten symptoms.

Example: five alerts fire from one failed deployment -> the collector correlates
them on a shared resource key -> one incident enters the loop, not five.

## Incident detection and response

The **trust router** scores every correlated event and picks the lowest tier
that can decide it (see [risk-tiers.md](risk-tiers.md)). Deterministic cases
resolve at T0 with no model call, and ambiguous cases move up. Detection stays
deterministic-first. An anomaly or a prediction raises a detected issue that the
safety check governs. It never acts on its own.

## A detected issue is not an action

An anomaly, forecast, correlation, or root-cause result is evidence. It enters
the same trust router and safety check as any other event. It becomes an executable
action only when a valid `ActionType` supplies the safety contract and every
verification, scope, lock, and approval requirement passes.

Example: a forecast predicts that capacity will run out -> Freyr emits a
detected issue -> the router selects a tier -> the safety check evaluates the
proposed scaling action -> the result is observation mode, human approval, or, if
the action is already promoted, automatic execution. The prediction itself never
scales the workload.

## Reasoning tier is not autonomy level

FDAI makes two monotonic decisions. First, the trust router selects the lowest
tier that can produce a supported candidate. Then the safety check combines that
tier with the matched policy, `ActionType` ceiling, static and live blast
radius, environment, operator role, evidence freshness, and promotion state.
Each input can lower autonomy; none can raise it above a stricter input.

| Candidate source | What it proves | What it does not prove |
|------------------|----------------|------------------------|
| T0 rule match | A deterministic rule applies | The action is low risk or promoted |
| T1 reuse | A prior pattern may apply after re-verification | Current scope and dependencies are unchanged |
| T2 proposal | Grounded reasoning passed its quality gate | The proposal may execute |

This separation is why a deterministic detected issue can still go to human
review, and why a well-supported T2 result can stay in observation mode.

## The runtime contract remains mandatory

Before anything changes, FDAI rechecks the proposed action against the current
inventory and policy. The executor proceeds only when it has a dry run, a stop
condition, a rollback path, an impact scope limit, a per-resource lock, a stable
idempotency key, an authorized workload identity, and a writable audit path. If a
required input goes stale or disappears, the action becomes an audited no-op, an
observation-mode result, or a denial, depending on policy. A console button or a
reply to a notification cannot stand in for these checks.

## Change management

Before a change ships, FDAI dry-runs it against policy-as-code, limits its impact
scope, and then either prepares it for the configured pull-request merge policy
or sends it for human approval. Actions arrive as **fix pull requests**, so
review, approval, and rollback all come from Git.

Example: an IaC pull request proposes a public-egress rule -> the safety check
marks it high risk -> an approval card reaches you in Teams -> you approve -> the
merge policy or an authorized approver completes delivery -> FDAI writes the
audit entry.

## Capacity, performance, and cost

Capacity and cost are two views of the same question: is this resource sized for
its demand? FDAI detects over- and under-provisioning and recommends a
right-size. Even a low-risk candidate such as releasing an unattached public IP
has to collect observation evidence and be promoted on its own before it can run
automatically. Anything that could degrade a live workload stays gated.

## Reliability and disaster recovery

Reliability work here is proactive. Scheduled DR drills, database restore
exercises, and chaos experiments with a bounded impact scope run on a cadence.
Cadence, scope, and proof stay separate: the scheduler owns cadence, the safety
check owns scope, and the audit log owns proof.

## Toil elimination

The whole point of the deterministic-first design is to remove toil. Because
rules decide the repeatable majority, you stop hand-approving the same drift,
cost regression, or policy violation every week. People are reserved for the new
and the high-risk cases (see
[deterministic-first.md](deterministic-first.md)).

## Postmortem and learning

Every final decision writes an append-only audit entry, including no-ops,
rejections, and approval timeouts. A learning loop watches those signals, such as
approvals, observation-mode drift, and overrides, and proposes catalog candidates
backed by evidence. It never edits or promotes the catalog itself.

## How SRE improvement is measured

Use paired baseline and treatment windows over the same scenario set. Outcome
metrics include MTTR distribution (mean, median, and p90), auto-resolution rate,
human touchpoints per incident, change lead time, and cost per resolved event.
Guard metrics include change-failure rate, false-positive and false-negative
rates, rollback rate, policy-violation escapes, and audit gaps.

FDAI does not claim an improvement from a higher automation percentage alone.
The result counts only when the outcome improves without regressing the guard
metrics.

## When FDAI itself is unhealthy

The control plane exposes readiness, event lag, dead-letter depth, dependency
health, synthetic-canary results, and audit completeness. A required dependency
failure lowers affected actions to shadow or deny. The executor stops mutation
when the safety contract, inventory freshness, lock, rollback support, or audit
write cannot be guaranteed.

This behavior keeps an observability failure from becoming an autonomy failure.
Operators can still inspect the degraded state and queued work without the
console or notification channel inheriting executor authority.

## Next steps

| To learn about | Read |
|----------------|------|
| The complete operator-facing SRE map | [Site Reliability Engineering](../sre/README.md) |
| How incidents move from open to closed | [Incident management](../sre/incident-management.md) |
| How FDAI produces grounded cause hypotheses | [Root-cause analysis](../sre/root-cause-analysis.md) |
| Why the repeatable majority never reaches an LLM | [deterministic-first.md](deterministic-first.md) |
| How decisions become auto or human approval | [risk-tiers.md](risk-tiers.md) |
| How every action inherits a safety contract | [ontology-driven-automation.md](ontology-driven-automation.md) |
| Which agents run each function and how they self-heal | [agents-and-self-healing.md](agents-and-self-healing.md) |
| The three verticals end to end | [../get-started.md](../get-started.md) |
