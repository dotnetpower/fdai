---
title: FDAI Functional Specification
description: A hierarchical definition of FDAI's observation, incident judgment, operator support, authorized actions, and outcome verification.
---

# FDAI Functional Specification

FDAI observes Azure resources within an authorized management scope, identifies operational
issues from evidence, and helps operators respond. When an operator explicitly approves an
action or grants valid prior authorization, FDAI agents act within that authority, verify the
outcome, and retain an audit trail.

> This document defines target product functions, not a declaration that every function is
> implemented or enabled. Resource coverage, supported actions, and operational readiness need
> separate implementation evidence. The [FDAI Constitution](../../roadmap/architecture/fdai-constitution.md)
> and the linked owner documents govern the detailed safety and authority requirements.

## What this document covers

Use four levels to describe a function: product purpose, function group, subfunction, and
detailed function. The hierarchy follows the operator's workflow rather than the internal agent
organization. Common controls apply across every group; operating domains reuse the same flow.

## Product purpose

Detect operational issues in Azure resources, support timely operator response, and perform
automated actions only within explicitly authorized boundaries.

Deploying FDAI into a subscription does not grant blanket visibility or permission to change
resources. Coverage depends on configured sources, supported adapters, and access permissions.
Operators authorize work; a separate authenticated execution identity performs it. FDAI does
not share the operator's credentials or inherit all of the operator's permissions.

## Function hierarchy

Each numbered subfunction contains detailed functions that can receive their own acceptance
criteria. The group name is shown once to make the hierarchy easier to scan.

| Function group | Subfunction | Detailed functions |
|----------------|-------------|--------------------|
| **1. Observe operational state** | 1.1 Discover managed resources | Discover resources, collect configuration, and identify dependencies within the authorized scope. |
| | 1.2 Collect operational signals | Collect supported resource states, metrics, logs, and events with source and time information. |
| | 1.3 Detect changes | Detect resource creation, updates, deletion, configuration changes, and deployment changes. |
| | 1.4 Track observation quality | Identify collection gaps, missing permissions, stale data, and incomplete coverage. |
| **2. Assess anomalies and incidents** | 2.1 Detect anomalies | Detect policy violations, abnormal states, and concerning trends against configured operating criteria. |
| | 2.2 Investigate incidents | Correlate related events, assess affected resources, and identify possible causes. |
| | 2.3 Explain assessments | Classify severity, cite evidence, separate facts from hypotheses, and report unknown or conflicting results. |
| **3. Support operator response** | 3.1 Notify and escalate | Notify responsible responders, track delivery and acknowledgment, and escalate according to policy. |
| | 3.2 Support investigation | Answer authorized questions about state, change history, incident evidence, and action progress. |
| | 3.3 Propose response plans | Present actions, expected effects, risks, impact scope, stop conditions, and recovery plans. |
| **4. Perform authorized actions** | 4.1 Manage action authority | Manage per-action approval, conditional prior authorization, expiration, and revocation. |
| | 4.2 Validate before execution | Check current authority, policy, target identity and revision, impact limits, and required safeguards. |
| | 4.3 Execute registered actions | Execute supported registered actions, track progress, and prevent duplicate changes. |
| **5. Verify outcomes and recover** | 5.1 Verify expected effects | Use independent authoritative observations to check whether the intended effect occurred. |
| | 5.2 Handle failure | Apply stop conditions and authorized rollback or bounded recovery; escalate when recovery cannot proceed. |
| | 5.3 Report outcomes | Distinguish verified success, failure, and unresolved outcomes, notify operators, and connect follow-up work. |

Example: a resource health event arrives, related telemetry supports an incident assessment,
and the operator receives an evidence-backed response plan. An approved action passes the
execution checks, runs through the execution identity, and is reported as successful only after
an independent observer confirms the expected effect.

## Common controls

These controls apply to the whole hierarchy rather than forming additional workflow stages.

| Control | Functional requirements |
|---------|-------------------------|
| **Management scope and access** | Define the managed subscription and resource-group scope, user roles, execution identity, and minimum permissions. Keep unauthorized and unobserved resources visible as coverage limitations. |
| **Evidence and decisions** | Preserve source, provenance, time, freshness, and completeness. Prefer deterministic rules for repeatable decisions and use bounded, evidence-checked reasoning for unresolved ambiguity. Missing evidence remains unknown rather than healthy. |
| **Policy and execution safety** | Apply risk and approval policies. Every autonomous state change needs a stop condition, tested rollback or bounded recovery, an impact limit, successful dry-run or an explicitly permitted equivalent, a logical-target lock, duplicate prevention, and audit records before and after the effect. |
| **Capability lifecycle** | Separate availability, enablement, and execution authority. New capabilities start in observation mode, where they assess and record without applying the proposed changes; changing mode follows the governed promotion process. |
| **Audit and traceability** | Link observations, decisions, notifications, approvals, execution, verification, and recovery. Retain the identities, versions, timestamps, and evidence needed to reconstruct each outcome. |
| **FDAI service health** | Expose collection and notification failures and required-component availability. Missing safety dependencies block affected changes instead of silently bypassing a control. |

## Authority boundaries

Read access and change authority are separate. An action is eligible only when current policy,
risk, identity, approval, capability mode, and safety checks all permit it.

| Situation | Expected behavior |
|-----------|-------------------|
| Authorized observation or investigation | Read and explain within the allowed scope; no resource change is implied. |
| Explicit approval for one action | Execute only the approved action against its approved target, revision, and scope while the approval remains valid. |
| Valid prior authorization | Execute only when the declared trigger, action, scope, validity period, and applicable risk conditions are satisfied. |
| Missing, expired, revoked, or mismatched authority | Do not start the action. Request the required approval, hold for review, or deny it with an audit record. |

An unanswered notification, a natural-language request, or a broad role assignment alone does
not authorize a specific change. Revocation blocks new execution under that authorization;
work already in progress follows its defined stop and recovery policy. Irreversible production
actions require current approval for each execution rather than prior standing authorization.

For the detailed approval profiles and emergency limits, see
[Risk tiers](risk-tiers.md) and
[Escalation and Standing Authority](../../roadmap/decisioning/escalation-and-standing-authority.md).

## Operating domains

Domains describe where the functions apply. They are not competing top-level branches of the
function hierarchy, and listing a domain does not prove complete implementation coverage.

| Domain | Application of the common flow |
|--------|--------------------------------|
| **SRE operations** | Observe availability and performance, assess incidents and service objectives, and verify recovery. SRE is the overall operating model. |
| **Resilience** | Assess backup and recovery readiness and govern disaster-recovery drills, restore, failover, and separately authorized Chaos experiments. |
| **Change safety** | Assess proposed changes, configuration drift, policy compliance, and architecture constraints before and after a change. |
| **Cost governance** | Observe spend and utilization, detect anomalies, propose optimization, and verify the effects of approved changes. |

## Detailed function records

Give each detailed function an ID beneath its subfunction. Keep the ID stable when wording
changes, and use it to connect acceptance tests and implementation evidence without mixing
target requirements with delivery status.

The following example expands subfunction `4.1` into one testable requirement.

| Field | Example |
|-------|---------|
| **Function ID** | `4.1.3` |
| **Function name** | Revoke action approval |
| **Actor and trigger** | An authorized operator revokes an existing approval. |
| **Preconditions** | The operator can revoke that approval and identifies its exact revision. |
| **Expected behavior** | Block new execution using the revoked approval. Handle in-progress work through its defined stop and recovery policy. |
| **Acceptance criteria** | A new dispatch under the revoked approval is blocked; in-progress work has an explicit recorded outcome; the audit identifies the operator, approval revision, time, and affected actions. |
| **Exception behavior** | An unauthorized request is denied. Failure to establish current authority holds affected new execution for review. |

In a separate implementation record, connect each function ID to its status, supported resource
and action types, constraints, code and test references, and dated verification evidence.
Implementation, local verification, live operational verification, and production readiness are
different claims; none follows from the presence of this specification alone.

## Related docs

| To learn about | Read |
|----------------|------|
| Initial setup and the operator journey | [Get started](../get-started.md) |
| Component responsibilities | [FDAI Architecture](../architecture.md) |
| Observation before enabling changes | [Observe, then enable changes](shadow-then-enforce.md) |
| Approval and notification surfaces | [Approvals and channels](approvals-and-channels.md) |
| Product safety and authority requirements | [FDAI Constitution](../../roadmap/architecture/fdai-constitution.md) |
