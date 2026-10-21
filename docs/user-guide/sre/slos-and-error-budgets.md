---
title: SLOs and Error Budgets
description: Learn how FDAI evaluates workload objectives and turns burn-rate evidence into governed incident signals.
---

# SLOs and Error Budgets

Service level objectives (SLOs) connect technical signals to user impact.
FDAI evaluates workload-facing service level indicators (SLIs), objectives,
error budgets, and multi-window burn rates so incident priority and change
decisions can use measured reliability evidence.

> The SLO registry, evaluator, event runner, one-shot command, and optional Container Apps schedule
> are implemented. Live evaluation remains partial until a deployment packages a non-empty
> workload catalog, binds an authoritative `MetricProvider`, enables the schedule, and retains run
> evidence. Workload SLOs are distinct from FDAI control-plane health objectives.

## Define the objective

An SLO entry identifies the workload and scope, SLI kind, target, measurement
window, and burn-rate alert windows. Definitions live in catalog-as-code and
are validated at load time.

| Element | Example meaning |
|---------|-----------------|
| SLI | Successful requests divided by valid requests |
| Objective | 99.9% over 30 days |
| Error budget | The allowed unsuccessful fraction for that window |
| Burn rate | How quickly the remaining budget is being consumed |

## Keep the two SLO identities separate

Workload SLOs measure the service FDAI operates. Control-plane SLOs measure
FDAI itself, such as event-processing latency, action success, and console
availability. A healthy control plane does not prove the workload is healthy,
and a workload incident does not by itself prove FDAI is degraded.

| Identity | Used for | Example |
|----------|----------|---------|
| Workload SLO | Incident impact and risky-change policy | Request success for a managed service |
| FDAI control-plane SLO | Platform readiness and safe degradation | Event decision completed within budget |

## Evaluate burn rate

FDAI uses short and long windows together. A short spike alone can be noise; a
long-window breach alone can react too slowly. Multi-window evaluation raises a
detected issue only when the configured combination indicates sustained or urgent
budget consumption.

The result records objective, attainment, remaining budget, evaluated windows,
thresholds, and source freshness. Missing or stale metric data fails closed and
does not become a healthy value.

The catalog defines the short and long windows and their thresholds. The guide
does not prescribe one universal numeric pair because service traffic and
objectives differ. FDAI evaluates the configured pair deterministically and
records both window results, including a no-detected issue outcome, so operators can
reproduce why an alert fired or held.

`python -m fdai.delivery.slo_burn_cli` runs one bounded evaluation pass. A deployment enables the
optional `slo_burn_cron_expression` only after its workload SLO YAML is present in the configured
catalog path. An empty catalog is a configuration error, and missing metric samples return
`retry_required` rather than a successful all-clear.

## From breach to response

1. The metric provider returns bounded, timestamped samples.
2. The burn-rate evaluator computes the configured windows.
3. `SloBurnRunner` publishes an `slo.error_budget_burn` event.
4. Event ingest deduplicates and correlates it with active changes or incidents.
5. The trust router and safety check decide whether to observe, notify, request
   approval, or route a typed mitigation.

An SLO breach is a detected issue, not permission to roll back or scale. Any response
still needs an `ActionType`, verification, impact scope bounds, rollback, and
the required decision.

During active budget burn, policy can raise incident priority or lower the
autonomy ceiling for risky changes. That policy is an explicit safety check input,
not an implicit side effect of the dashboard. Missing data cannot consume zero
budget or authorize a change; it produces unavailable evidence and suppresses
dependent decisions.

## Operator checks

- Confirm the SLI measures user impact rather than a convenient infrastructure
  proxy.
- Check the metric source, freshness, missing-data policy, and measurement
  window.
- Review short- and long-window burn rates together.
- Correlate burn with deployments, maintenance windows, and active incidents.
- Freeze risky change only through a governed policy, never from a browser-only
  calculation.

## Next steps

| To learn about | Read |
|----------------|------|
| How telemetry becomes a detected issue | [Observability, detection, and forecasting](observability-detection-and-forecasting.md) |
| How a breach joins an incident | [Incident management](incident-management.md) |
| How capacity evidence complements SLOs | [Capacity and performance](capacity-and-performance.md) |
| The canonical outcome metrics | [Goals and metrics](../../roadmap/architecture/goals-and-metrics.md) |
