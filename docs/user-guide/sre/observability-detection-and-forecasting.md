---
title: Observability, Detection, and Forecasting
description: How FDAI turns events and telemetry into correlated, explainable detected issues without creating a second execution path.
---

# Observability, Detection, and Forecasting

FDAI treats observability as evidence production, not as an execution surface.
Events, metrics, logs, traces, anomalies, and forecasts become normalized
detected issues that re-enter the same trust and risk pipeline as every other event.

> Event correlation, deterministic anomaly detection, and forecasting are
> implemented upstream. A deployment must bind real metric, log, and trace
> providers before those paths can observe live workloads.

## What this guide covers

- The difference between raw signals, detected issues, incidents, and actions.
- How deterministic correlation reduces alert noise without discarding data.
- How anomaly and forecast detectors remain explainable and shadow-first.
- Which evidence an operator should inspect before trusting a detection result.

## Signal model

| Record | Meaning | May execute? |
|--------|---------|--------------|
| Raw signal | One provider event, metric sample, log, or trace | No |
| Detected issue | A normalized anomaly, forecast, or policy observation | No |
| Incident | A stable group of related events and detected issues | No |
| RCA hypothesis | A cited explanation of an incident | No |
| Action proposal | A typed change with a safety contract | Only after normal gates |

A detected issue never grants permission to mutate. It must map to an `ActionType`,
pass verification and scope checks, acquire the resource lock, and receive the
risk decision required by policy.

## Correlate before deciding

Correlation runs after normalization and deduplication. It groups signals by
stable keys such as resource, deployment, trace, causal parent, and bounded time
window. Late members can join an open incident; events past the configured
window open a linked follow-on incident.

Correlation asserts that records belong together. It does not claim that one
record caused another. Root-cause analysis owns causation.

Example: a deployment emits one change event and four services emit errors ->
the shared deployment and resource graph produce one incident -> all five raw
records remain available as members -> RCA evaluates cause separately.

## Detect anomalies explainably

Deterministic detectors compare a metric against a configured rolling or
seasonal baseline. A detected issue records the baseline, observed value, deviation,
direction, window, and severity so an operator can reproduce why it fired.

- **Cold start**: insufficient history holds for review instead of guessing.
- **Flat baseline**: zero variance is handled explicitly rather than dividing
  by zero or creating infinite severity.
- **Seasonality**: a sample is compared with the same hour or weekly phase, not
  a pooled 24x7 average.
- **Composite degradation**: multiple metric detected issues can require quorum before
  a compound anomaly is emitted.
- **Change awareness**: maintenance and in-flight changes annotate or suppress
  expected deviations.

Composite detection is a fuser, not another baseline. It collapses duplicate
metrics to their strongest occurrence and emits only when a configured quorum
of distinct members fires for the same resource and window. Below quorum it
holds for review. At or above quorum it can raise severity from the breadth and combined
magnitude of the members, but the result remains a observation mode detected issue.

## Evaluate deterministic operational conditions

Not every useful condition needs a statistical baseline. The versioned
operational-insight catalog supplies deterministic recipes for infrastructure,
application performance, data systems, SLO burn, alert quality, cost, security,
and recovery hygiene. Each recipe applies an explicit operator such as
`above`, `below`, delta, ratio, `absent`, or `stale` to normalized samples.

Recipes record the observed value, reference, threshold, score, and explanation.
Incomplete, non-finite, undersampled, or invalid ratio inputs hold without a
detected issue. Thresholds and metric bindings stay in catalog data so a deployment can
tune them without changing the evaluator. Every recipe starts in observation mode
and re-enters event ingest for stable deduplication before trust routing.

## Distinguish absence from provider failure

A successful query with no samples can be evidence for an `absent` recipe. A
provider error is different: FDAI marks that metric unavailable and suppresses
every dependent recipe, so a telemetry outage cannot be reported as a workload
outage. Stale recipes use a bounded extended lookback; if no last-seen sample
exists there, they hold instead of inventing a timestamp or a value.

| Input state | Detector behavior | Operator meaning |
|-------------|-------------------|------------------|
| Successful query with valid samples | Evaluate the recipe or baseline | Evidence is available |
| Successful empty query | Evaluate only semantics that allow absence | Absence may be evidence |
| Provider error | Suppress dependent evaluations | Evidence is unavailable |
| Cold or stale history | Hold for review or hold | Evidence is insufficient |

## Forecast threshold breaches

Forecast detectors estimate whether a measured trend will cross a configured
threshold within a bounded horizon. Each result carries an estimated breach
time, fit quality, and uncertainty band. A weak fit or uncertain crossing
holds for review.

Common targets include capacity exhaustion, replication lag approaching an RPO
limit, certificate expiry, budget run rate, and backup-retention drift.

A forecast is not deterministic truth. It raises a detected issue and can propose a
preventive fix pull request, but the proposal still passes the trust
router, verifier, safety check, and normal approval policy.

Before promotion, a forecaster backtests known historical breaches and clears
its configured accuracy bar in observation mode. FDAI tracks forecast error after
promotion. Measured drift moves the forecaster back to shadow, while prediction
intervals can suppress an uncertain point-estimate breach but never create a
breach the point forecast did not predict.

## Operator workflow

1. Confirm the provider, resource, time window, and data freshness.
2. Inspect the baseline, threshold, deviation, and cold-start state.
3. Distinguish a successful empty query from an unavailable provider result.
4. Check incident membership and whether a deployment or maintenance window
   explains the signal.
5. Follow the correlation ID to RCA, decision, action proposal, and audit rows.
6. Treat missing evidence as unavailable. Do not infer zero or healthy state.

## Evidence and guard metrics

Track detector fire rate, cold-start abstentions, false-positive rate,
false-negative rate, forecast precision and recall, forecast lead time, and
incident-to-raw-signal ratio. Promotion requires measured evidence on a frozen
scenario set; regression moves the detector back to shadow.

## Deep reference

The implementation contract, detector algorithms, and control-loop wiring are
specified in [Observability and Detection](../../roadmap/rules-and-detection/observability-and-detection.md).

## Next steps

| To learn about | Read |
|----------------|------|
| How detected issues become incidents | [Incident management](incident-management.md) |
| How workload impact changes priority | [SLOs and error budgets](slos-and-error-budgets.md) |
| How cause differs from correlation | [Root-cause analysis](root-cause-analysis.md) |
| How to inspect terminal evidence | [Read the audit log](../guides/read-audit-log.md) |
