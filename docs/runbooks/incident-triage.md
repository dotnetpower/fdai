---
title: Incident Triage Runbook
description: A customer-neutral template for confirming incident scope, severity, ownership, and investigation readiness.
---

# Incident Triage Runbook

Use this runbook when an incident opens or materially changes severity, scope,
or ownership. Triage establishes what is affected, how urgent the impact is,
who owns the next decision, and whether the evidence is fresh enough to begin
a bounded investigation.

> Triage does not establish root cause and does not authorize mitigation. It
> creates a reliable incident boundary and the next decision deadline.

## When to start or repeat triage

Run triage for these events:

- **New incident**: correlation creates an incident from one or more findings.
- **Material update**: affected resources, user impact, or SLO burn changes.
- **Ownership failure**: delivery fails or the assigned responder cannot accept the incident.
- **Merged or split evidence**: correlation membership changes enough to alter scope.
- **Recovery signal**: impact appears resolved and the incident may move to monitoring.

## Preconditions

- **Identity**: incident ID, correlation keys, current state, and member count.
- **Freshness**: telemetry, inventory, deployment, and notification timestamps.
- **Ownership**: accountable owner and the on-call schedule or route used.
- **Impact inputs**: affected users or operations, SLO state, duration, and bounded scope.
- **Concurrency**: expected current state for every incident transition.

If a source is unavailable, mark it unavailable. Do not infer healthy state from
missing data.

## Roles

| Role | Responsibility |
|------|----------------|
| Triage owner | Maintains scope, severity basis, unknowns, and next decision time |
| Responder | Accepts the notification and begins bounded investigation |
| Service owner | Confirms service context and business impact when available |
| Auditor | Records membership, severity, ownership, and state transitions |

## Establish severity

Use measured impact and the repository's configured severity policy. The table
below guides evidence collection; it does not replace that policy.

| Signal | Evidence to record |
|--------|--------------------|
| User or operation impact | Unavailable or degraded capability and observed population |
| SLO impact | Objective, windows, burn values, and remaining error budget |
| Scope | Affected resources, regions, dependencies, and exclusions |
| Duration | First observed time, confirmation time, and whether impact is ongoing |
| Recoverability | Known workaround, rollback readiness, and protected dependencies |

## Procedure

1. **Confirm the incident record.** Verify identity, correlation keys, current
	state, member count, and the newest member timestamp.
2. **Validate membership.** Confirm affected resources and add or remove members
	only through an audited correction with a reason.
3. **Bound the impact.** Record affected capability, resource scope, start time,
	SLO state, dependencies, and known exclusions.
4. **Set severity.** Apply configured policy to measured impact. Record the
	evidence and rule used, including uncertainty.
5. **Assign ownership.** Select the responder from the configured route, set the
	next decision deadline, and identify the service owner when available.
6. **Transition safely.** Move the incident to `triaging` using the expected
	current state so a concurrent update cannot be overwritten.
7. **Start investigation.** Define a time range, resource scope, evidence budget,
	and the first questions to answer.
8. **Notify and verify.** Send the durable notification and confirm accepted,
	failed, or fallback delivery rather than assuming success.

## Decision branches

| Condition | Next step |
|-----------|-----------|
| Scope and severity are established | Start [RCA evidence collection](rca-evidence-collection.md) |
| A known, verified mitigation is ready | Route it through [incident mitigation and rollback](incident-mitigation-and-rollback.md) |
| Evidence sources are unavailable | Keep severity conservative and escalate source recovery |
| Multiple unrelated causes are present | Split through an audited correlation correction |
| No impact remains but recovery is not yet stable | Move to monitoring with a review deadline |
| Notification is not accepted | Use the configured fallback and record every attempt |

## Stop conditions

Stop and escalate when identity, ownership, scope, or evidence freshness cannot
be established. Stop transitions when the expected incident state has changed,
then refresh and repeat triage. Do not lower severity from missing data.

## Evidence and audit

Record transition audit ID, owner, severity basis, member references,
investigation ID, notification result, and next review time. Also record source
freshness, unknowns, exclusions, and every membership correction.

## Completion criteria

Triage is complete when the incident has a validated boundary, severity basis,
accountable owner, accepted notification or exhausted fallback, bounded
investigation, and next decision deadline. Repeat triage whenever one of those
facts materially changes.

## Related runbooks

| To continue with | Read |
|------------------|------|
| Validate a burn-rate trigger | [SLO burn response](slo-burn-response.md) |
| Build an evidence-backed chronology | [RCA evidence collection](rca-evidence-collection.md) |
| Execute or roll back a governed response | [Incident mitigation and rollback](incident-mitigation-and-rollback.md) |
