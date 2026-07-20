---
title: Capacity and Performance
description: How FDAI turns measured demand and forecasts into bounded capacity issues and governed scaling proposals.
---

# Capacity and Performance

Capacity work asks whether a resource can meet measured demand without wasting
cost or exhausting a dependency. FDAI combines current utilization, forecast
evidence, minimum floors, dependency checks, and promotion state before it can
propose a scaling action.

## Capacity evidence

- Current utilization and saturation by resource and window.
- Demand trend, forecast horizon, uncertainty, and expected breach time.
- Minimum and maximum capacity plus warm-capacity floors.
- Quota, regional availability, and dependent-resource constraints.
- Workload SLO and error-budget impact.
- Cost estimate and rollback or scale-back path.

Missing or stale telemetry produces unavailable or abstained evidence. It does
not produce a zero-demand assumption.

## Decide without conflicting specialists

Freyr evaluates capacity while Njord evaluates cost. Their advice can conflict,
such as scale up for reliability versus scale down for efficiency. Specialists
remain advisory; Forseti and the risk gate apply the configured precedence and
autonomy ceiling.

Forseti emits a cross-vertical arbitration request when advice conflicts. Odin
applies the versioned priority policy from the rule catalog and returns one
reproducible arbitration result before Forseti makes the verdict. The default
policy prefers SLO protection over cost and architecture advice, but a deployment
can supply a reviewed policy without changing agent code. The arbitration result
is evidence; it cannot relax a risk-gate ceiling.

Example: low utilization suggests scale-down while an SLO forecast shows an
imminent capacity breach -> the configured priority policy preserves the SLO
floor -> what-if still checks quota and dependencies -> the risk gate decides
shadow, approval, or promoted execution.

## Scaling proposal flow

1. A detector or scheduled evaluation emits a capacity finding.
2. The finding correlates with workload SLO, current changes, and incidents.
3. What-if verifies quota, dependencies, floors, and expected effect.
4. A typed scale proposal carries scope, batch, rate, stop condition, and rollback.
5. Shadow evidence and promotion state determine whether the proposal can reach
   approval or promoted auto behavior.

## Guardrails

Never scale below a declared safety floor, strand a dependency, exceed quota,
or treat a forecast as execution authority. Per-resource locks and bounded
batch changes prevent competing scale actions from racing.

| Runtime check | If it passes | If it fails or is unknown |
|---------------|--------------|---------------------------|
| Demand and SLO evidence is fresh | Continue to what-if | Hold with unavailable evidence |
| Quota and dependency checks pass | Build a typed proposal | No proposal |
| Floor, batch, and rate limits hold | Continue to the risk gate | Deny or reduce scope |
| Lock and idempotency claim succeed | Apply at most once | Retry safely or no-op |
| Stop condition remains healthy | Continue the bounded batch | Stop and follow rollback policy |

## Next steps

| To learn about | Read |
|----------------|------|
| How forecasts are formed | [Observability, detection, and forecasting](observability-detection-and-forecasting.md) |
| How workload impact is measured | [SLOs and error budgets](slos-and-error-budgets.md) |
| How cost and capacity interact | [Cost Governance](../capabilities/cost-governance.md) |
| How actions are promoted | [Shadow, then enforce](../concepts/shadow-then-enforce.md) |
