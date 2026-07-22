---
title: SLO Burn Response Runbook
description: A template for validating a detected error-budget burn issue and routing a governed response.
---

# SLO Burn Response Runbook

Use this runbook when a workload service-level objective (SLO) emits
`slo.error_budget_burn`. It verifies the objective and source data, confirms the
short- and long-window burn, correlates likely context, and routes a governed
incident response without treating missing data as healthy.

> Thresholds, objective values, metric queries, and notification routes are
> configuration supplied by the downstream fork. This template does not define
> one universal burn policy.

## Entry criteria and ownership

Start with the detected issue ID, SLO and service IDs, evaluated windows, source
timestamp, and configured route. Assign an owner for verification and record
the next decision deadline before beginning deeper investigation.

| Required input | What to verify |
|----------------|----------------|
| SLO version | Objective, indicator, target, evaluation period, and owner |
| Metric source | Query or projection, aggregation, dimensions, and freshness |
| Burn windows | Short and long window boundaries, thresholds, and sample counts |
| Error budget | Consumed and remaining budget for the active period |
| Scope | Service, region, operation, dependency, and explicit exclusions |
| Context | Deployments, maintenance, capacity events, and open incidents |

## Validate the detected issue

1. Confirm the detected issue references the currently active SLO version.
2. Verify the service-level indicator (SLI), which is the measured signal behind
	the objective, uses the intended scope and dimensions.
3. Check source health, ingestion delay, sampling, and missing-data behavior.
4. Recompute or independently inspect both configured windows from the same source.
5. Confirm threshold comparisons and remaining error budget without rounding away a breach.
6. Compare the detected issue timestamp with deployments, maintenance, capacity, and incidents.

If the detected issue is invalid, record why and route the labeled case to [alert
tuning](alert-tuning.md). Do not simply close it as noise.

## Response procedure

1. **Record the baseline.** Capture the window values, error budget, source
	freshness, affected dimensions, and current user impact.
2. **Check for an incident.** Update an existing correlated incident or open a
	new one using a stable correlation key.
3. **Set severity.** Apply configured severity policy to measured user impact,
	burn, duration, and scope. The burn alert alone does not bypass policy.
4. **Assign and notify.** Select the configured owner, send durable notification,
	and verify delivery or fallback outcome.
5. **Investigate context.** Start a bounded investigation across recent changes,
	capacity, dependencies, and related detected issues.
6. **Prepare mitigation.** For any proposed change, record evidence, intended
	effect, scope, what-if result, stop conditions, and rollback.
7. **Route the proposal.** Send the typed action through risk and approval policy.
8. **Observe recovery.** Continue both burn windows through the configured
	recovery period before declaring the SLO stable.

## Decision branches

| Detected issue state | Response |
|---------------|----------|
| Both windows breach and impact is confirmed | Triage or update the incident immediately |
| Short window breaches but long window does not | Monitor to the next deadline and inspect acute context |
| Long window breaches without a short-window spike | Investigate sustained degradation and budget trend |
| Burn is valid but no user impact is yet visible | Keep the detected issue active and investigate before budget exhaustion |
| Source or SLI scope is invalid | Record an invalid detected issue and begin measured alert tuning |
| Existing incident already covers the scope | Add evidence to that incident rather than opening a duplicate |

## Stop conditions

Stop when samples are stale, the SLI is mis-scoped, missing data was treated as
zero, window boundaries differ from configuration, or rollback and impact bounds
are unavailable. Stop state transitions when the incident has changed
concurrently, refresh it, and repeat the decision.

## Verification and recovery

Recovery requires more than one healthy sample. Verify that:

- **Windows**: short and long burn values remain below their configured recovery conditions.
- **Budget**: remaining error budget and projection are recorded after mitigation.
- **Impact**: affected operations and dependencies pass their health checks.
- **Change**: any mitigation has a known active version and rollback reference.
- **Incident**: the state moves to monitoring with a defined review deadline.

If a mitigation worsens the burn or another guard condition, follow [incident
mitigation and rollback](incident-mitigation-and-rollback.md).

## Evidence and audit

Record SLO version, window values, source timestamp, incident ID, proposal ID,
decision, and terminal outcome. Also record SLI dimensions, source-health checks,
error-budget values, correlation context, notification outcome, and recovery window.

## Completion criteria

Complete the response when the detected issue is classified as valid or invalid, the
incident and owner are known, every proposal has a terminal decision, and the
SLO has either passed its recovery window or remains open with a next decision
deadline. Preserve invalid detected issues as labeled tuning scenarios.

## Related runbooks

| To continue with | Read |
|------------------|------|
| Establish incident scope and ownership | [Incident triage](incident-triage.md) |
| Improve an invalid or noisy detector | [Alert tuning](alert-tuning.md) |
| Execute a verified response safely | [Incident mitigation and rollback](incident-mitigation-and-rollback.md) |
