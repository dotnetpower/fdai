---
title: Alert Tuning Runbook
description: A template for reducing alert noise and missed detection through measured rule and routing changes.
---

# Alert Tuning Runbook

Use this runbook when false positives, false negatives, duplicate incidents, or
stale routing reduce the usefulness of an alert. It keeps tuning measurable by
comparing one proposed change against a frozen baseline in observation mode, where
FDAI observes and logs but does not act.

> Keep environment-specific detector names, dashboard queries, notification
> destinations, and promotion commands in the downstream fork. Do not put
> customer values in this upstream template.

## When to use this runbook

Start this runbook when one or more of these signals persist beyond the normal
observation window:

- **False positives**: alerts fire but labeled evidence shows no actionable condition.
- **False negatives**: a confirmed incident has no matching detector or route event.
- **Duplicates**: one condition creates multiple incidents or repeated notifications.
- **Late delivery**: the detector fires on time but correlation or routing misses its deadline.
- **Stale routing**: delivery targets, ownership, or escalation policy no longer match the service.

Do not use tuning to hide a currently active incident. Complete [incident
triage](incident-triage.md) first, then return with a labeled case.

## Roles and inputs

| Item | Required input |
|------|----------------|
| Owner | Person accountable for the detector or route under review |
| Reviewer | A person other than the owner who approves promotion or rollback |
| Scenario set | Frozen positive, negative, duplicate, and delivery-failure cases |
| Baseline | Detector, correlation, routing, catalog, and configuration versions |
| Guard metrics | Missed incidents, notification latency, duplicate ratio, and policy escapes |
| Observation window | A fixed duration or event count used for baseline and treatment |

The owner can prepare and run the comparison. Promotion needs an independent
review so the person optimizing alert volume does not approve a weaker safety
signal alone.

## Preflight

Before changing configuration:

1. Confirm the scenario labels have an evidence source and review date.
2. Record the current detector, correlation, routing, and catalog versions.
3. Confirm baseline and treatment runs use the same scenarios and observation window.
4. Verify shadow results write audit records without opening, closing, or mutating incidents.
5. Save the current configuration as the rollback reference.
6. Pause tuning if an active incident depends on the detector being changed.

## Diagnose the failure

Classify the observed defect before selecting a change. One defect can have
multiple symptoms, but each treatment run changes only one axis.

| Symptom | Inspect first | Typical treatment axis |
|---------|---------------|------------------------|
| Stable noise at all hours | Baseline and threshold | Baseline window or threshold |
| Noise at predictable times | Seasonality model | Seasonal window or schedule |
| Repeated alerts for one condition | Deduplication and debounce | Correlation key or debounce interval |
| Related signals split into incidents | Correlation evidence | Correlation rule or time window |
| Confirmed incident had no alert | Coverage and missing-data handling | Detector condition or data-quality route |
| Correct alert reached the wrong responder | Ownership and channel policy | Route mapping or escalation policy |
| Correct route arrived late or failed | Delivery outcome and retry audit | Delivery retry or fallback route |

## Procedure

1. **Measure the baseline.** Run the frozen scenario set and capture fire rate,
	precision, recall, duplicate ratio, cold-start holds, delivery latency, and
	terminal delivery outcomes.
2. **Choose one treatment.** State the defect classification, the single
	configuration axis to change, and the expected metric movement.
3. **Run in shadow.** Apply the treatment only to the shadow evaluator and rerun
	the same scenario set under the same observation window.
4. **Compare results.** Calculate baseline and treatment values for every primary
	and guard metric. Explain missing samples instead of treating them as zero.
5. **Review failures.** Inspect every newly missed incident, policy escape,
	uncorrelated duplicate, and failed delivery before considering promotion.
6. **Decide.** Promote only when the target metric improves, guard metrics remain
	within their declared bounds, and the independent reviewer accepts the evidence.
7. **Observe the rollout.** Keep the prior configuration available and monitor the
	promoted version for the declared observation window.

## Decision branches

| Result | Action |
|--------|--------|
| Target metric improves and all guard metrics pass | Approve the configured promotion path |
| Target metric improves but a guard metric regresses | Reject the treatment and restore the baseline |
| Results are inconclusive | Extend or relabel the scenario set, then restart from baseline |
| A policy-violation escape appears | Block promotion and route the case for safety review |
| Live observation differs materially from shadow | Roll back and preserve both result sets for review |

## Stop conditions

Stop the run when any of these conditions occurs:

- **Unreliable labels**: evidence is missing, stale, or disputed.
- **Invalid comparison**: baseline and treatment use different scenarios or windows.
- **Safety regression**: missed incidents or policy-violation escapes increase.
- **Hidden scope change**: more than one configuration axis changed.
- **Active dependency**: an ongoing incident needs the detector in its current form.

Do not suppress an alert solely to reduce volume. A lower alert count is not an
improvement when detection or delivery quality declines.

## Rollback and recovery

Restore the recorded baseline version when promotion guard metrics fail or live
observation diverges from shadow. Rerun a small canary subset after rollback and
confirm that detector, correlation, and delivery outcomes match the prior baseline.
Keep the failed treatment as evidence; do not overwrite it with the rollback run.

## Evidence and audit

Attach these records to the tuning decision:

- **Identity**: owner, reviewer, detector or route ID, and change reference.
- **Versions**: detector, correlation, routing, catalog, baseline, and treatment versions.
- **Dataset**: scenario-set hash, label provenance, and observation window.
- **Measurements**: baseline and treatment values for every primary and guard metric.
- **Exceptions**: missed cases, duplicates, failed deliveries, and policy escapes.
- **Decision**: promote, reject, extend, or roll back, with the approving principal.
- **Outcome**: rollout window, rollback reference, and final configuration version.

## Completion criteria

Close the tuning work only when the decision is audited, the active configuration
version is known, and either the promoted treatment or restored baseline has passed
its observation window. Send newly discovered response gaps to the
[postmortem workflow](postmortem-workflow.md) rather than expanding this change.

## Related runbooks

| To continue with | Read |
|------------------|------|
| Scope and classify an active incident | [Incident triage](incident-triage.md) |
| Validate a service-level objective burn | [SLO burn response](slo-burn-response.md) |
| Turn a response gap into owned follow-up | [Postmortem workflow](postmortem-workflow.md) |
