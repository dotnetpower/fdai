---
title: RCA Evidence Collection Runbook
description: A template for assembling a bounded, cited evidence set before accepting a root-cause hypothesis.
---

# RCA Evidence Collection Runbook

Use this runbook to assemble a bounded, cited evidence set before accepting or
publishing a root-cause analysis (RCA) hypothesis. It separates collection from
interpretation so every causal claim can be traced to a known source and time.

> Collect only evidence authorized for the incident scope. Store opaque
> references and hashes instead of secrets or raw restricted payloads.

## Entry criteria

Begin after [incident triage](incident-triage.md) establishes an incident ID,
affected scope, accountable owner, evidence time range, and next decision
deadline. Repeat collection when the scope or timeline materially changes.

## Roles and collection boundary

| Item | Required value |
|------|----------------|
| Investigation owner | Accountable person for scope, budget, and final evidence set |
| Reviewer | Person who verifies source identity, citations, and unsupported gaps |
| Time boundary | Start and end timestamps, including justified lead-in time |
| Resource boundary | Included resources, dependencies, regions, and explicit exclusions |
| Evidence budget | Source, query, volume, and retention limits |
| Access boundary | Authorized identities and handling requirements |

Do not silently widen the collection boundary. Record and approve a revised
boundary before querying additional resources or time ranges.

## Evidence inventory

| Evidence class | What to collect | Reliability checks |
|----------------|-----------------|--------------------|
| Events and audit | Findings, state transitions, verdicts, approvals, actions | Producer, sequence, correlation ID, hash |
| Changes | Deployments, configuration, catalog, policy, and ownership updates | Version, actor, scope, completion state |
| Metrics | SLI, saturation, errors, latency, and dependency health | Source, aggregation, missing data, timestamp |
| Logs and traces | Correlated execution and request records | Clock, sampling, redaction, trace continuity |
| Inventory | Resource state and relationships at relevant times | Snapshot time, source, completeness |
| Knowledge | Rules, runbooks, prior incidents, and architecture references | Version, approval state, provenance |

Absence of a record is evidence only when the source was expected to emit it and
source health proves the absence is meaningful.

## Collection procedure

1. **Freeze the boundary.** Record the incident, target resources, time range,
	source allowlist, evidence budget, and access scope.
2. **Capture source health.** Verify clocks, ingestion delay, retention,
	sampling, and known gaps before interpreting returned data.
3. **Collect immutable references.** Gather correlated events, changes, metrics,
	logs, traces, inventory, rules, and approved knowledge references.
4. **Normalize time.** Preserve source timestamps and record any known clock
	offset. Do not rewrite timestamps to force an ordering.
5. **Build the chronology.** Order supported facts before ranking causes. Mark
	gaps and conflicting records explicitly.
6. **Form hypotheses.** For each candidate cause, state supporting evidence,
	contradicting evidence, and what observation would disprove it.
7. **Test citations.** Verify that every claim resolves to a supplied reference
	and that the reference was available within the collection boundary.
8. **Review the set.** Have the reviewer confirm scope, handling, freshness,
	citation integrity, alternatives, and unresolved ambiguity.

## Hypothesis record

Use the same fields for the leading hypothesis and its alternatives:

| Field | Content |
|-------|---------|
| Claim | One bounded causal statement |
| Supporting evidence | References that increase confidence in the claim |
| Contradicting evidence | References that reduce confidence or support an alternative |
| Falsifier | Observation that would disprove the claim |
| Confidence | Configured confidence value with its basis |
| Gaps | Missing or unreliable evidence that affects the conclusion |

Do not promote correlation alone to causation. A change near the incident start
is a candidate until mechanism and evidence support the causal link.

## Stop conditions

Stop when evidence exceeds scope, citations cannot be verified, timestamps are
inconsistent, source health is unknown, or a provider response may contain
unvouched data. Also stop when the collection may expose secrets or restricted
payloads beyond the approved handling boundary.

An unsupported result goes to human review as an unresolved hypothesis. It does
not become an execution-eligible mitigation.

## Evidence package and audit

The final package includes the boundary, source inventory, source-health checks,
chronology, evidence references and hashes, hypothesis records, reviewer,
confidence basis, and unresolved gaps. Record collection start and end times and
link the package version to the incident audit trail.

## Completion criteria

Collection is complete when every material claim has a verifiable citation,
credible alternatives are recorded, handling rules are satisfied, and the
reviewer accepts the package. The outcome can be a supported cause, a disproved
cause, or an explicit unresolved result.

## Related runbooks

| To continue with | Read |
|------------------|------|
| Refresh incident scope or severity | [Incident triage](incident-triage.md) |
| Route a supported mitigation proposal | [Incident mitigation and rollback](incident-mitigation-and-rollback.md) |
| Preserve the final causal review | [Postmortem workflow](postmortem-workflow.md) |
