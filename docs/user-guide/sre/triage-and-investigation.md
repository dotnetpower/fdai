---
title: Triage and Investigation
description: How FDAI gathers bounded cross-resource evidence and produces an auditable investigation report.
---

# Triage and Investigation

Triage establishes ownership, impact, and urgency. Investigation then gathers
the smallest evidence set that can explain the incident without turning a read
operation into a hidden mutation path.

## Investigation contract

An investigation request names the incident, target resources, time range, and
latency budget. Resource analyzers read provider evidence and return structured
detected issues. The coordinator builds a timeline, correlations, an optional
root-cause hypothesis, and prioritized recommendations.

The report is read-only. A recommendation naming a fix is still only a
proposal and must re-enter the typed action pipeline.

## Bounded evidence gathering

- **Resource scope** limits which resources an analyzer may inspect.
- **Time range** prevents an unbounded history query.
- **Latency budget** records whether the investigation completed in time.
- **Provider failures** become unavailable evidence, not invented facts.
- **Priorities** rank recommendations as P1, P2, or P3 without granting
  execution authority.

Evidence availability is explicit rather than inferred from a missing field.
Priority is local ordering inside the report; it is not severity, confidence,
or an autonomy decision unless a separate policy says so.

| Evidence state | Meaning | Downstream behavior |
|----------------|---------|---------------------|
| Available | Provider returned bounded, fresh data | May support detected issues and hypotheses |
| Empty | Query succeeded with no matching records | Report absence with query scope |
| Unavailable | Provider failed or dependency is unhealthy | Mark the gap and suppress dependent claims |
| Stale | Data exists but exceeds its freshness policy | Hold dependent conclusions for review |

## Triage workflow

1. Confirm incident severity, owner, affected resources, and user impact.
2. Check whether telemetry and inventory are fresh enough to investigate.
3. Run analyzers only for the declared resource types.
4. Build the ordered timeline before asserting causality.
5. Separate correlated observations from grounded root-cause hypotheses.
6. Route actionable recommendations to an incident response plan or normal
   action proposal.

## Read the report

| Section | Question it answers |
|---------|---------------------|
| Detected issues | What did each resource analyzer observe? |
| Timeline | In what order did changes and symptoms occur? |
| Correlations | Which observations move together? |
| RCA hypothesis | What cause is supported by cited evidence? |
| Recommendations | What should be inspected, simulated, or proposed next? |
| Budget result | Did evidence gathering finish within its declared limit? |

## Failure behavior

A wedged analyzer is bounded and produces a no-action result. An exception is
recorded as unavailable evidence rather than crashing the response and losing
the audit trail. Cancellation still aborts the investigation cleanly.

Analyzers fail independently. Completed analyzer results remain in a partial
report while failed or timed-out analyzers contribute explicit gaps. When the
overall latency budget expires, the coordinator stops gathering new evidence,
records whether the budget was met, and returns only supported observations.
It does not fill missing sections with model prose or turn a partial report into
an action.

Before using a recommendation, verify that its supporting analyzer completed,
the cited evidence is fresh, and the recommendation remains within the declared
resource and time scope. A high report priority can accelerate review, but it
cannot bypass RCA evidence check, risk classification, or approval.

## Next steps

| To learn about | Read |
|----------------|------|
| How the incident record changes | [Incident management](incident-management.md) |
| How cited hypotheses are gated | [Root-cause analysis](root-cause-analysis.md) |
| How a recommendation becomes a proposal | [Response plans and mitigation](response-plans-and-mitigation.md) |
| How to inspect supporting records | [Read the audit log](../guides/read-audit-log.md) |
