---
title: FDAI Functional Specification
description: A hierarchical definition of FDAI's operating functions, shared automation, governance, and product capabilities, separate from execution flow and implementation status.
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
detailed function. The hierarchy describes operator outcomes rather than internal agent names.
Keep product functions, the common operating flow, and implementation coverage separate.

| View | Question | Contents |
|------|----------|----------|
| **Product function hierarchy** | What does FDAI provide? | Numbered function groups, subfunctions, and detailed requirements. |
| **Common operating flow** | How does a function reach an outcome? | Observation, assessment, planning, authorization, execution, verification, recovery, audit, and improvement. |
| **Implementation coverage** | What is supported and verified now? | Supported targets and actions, deployment bindings, constraints, and dated code, test, and operational evidence. |

## Product purpose

Detect operational issues in Azure resources, support timely operator response, and perform
automated actions only within explicitly authorized boundaries.

Deploying FDAI into a subscription does not grant blanket visibility or permission to change
resources. Coverage depends on configured sources, supported adapters, and access permissions.
Operators authorize work; a separate authenticated execution identity performs it. FDAI does
not share the operator's credentials or inherit all of the operator's permissions.

## Function hierarchy

The following inventory expands the operating domains and shared product capabilities into
testable functions. IDs prefixed with `F` identify product functions, not workflow stages or
agent roles. Each subfunction can have detailed requirements with separate acceptance criteria.

### Operational foundation

| Function group | Subfunction | Detailed functions |
|----------------|-------------|--------------------|
| **F01. Configure the operating environment** | F01.1 Management scope | Configure the managed subscription and resource-group scope, observation sources, access requirements, and connection readiness. |
| | F01.2 Operating criteria | Define service objectives, thresholds, maintenance windows, notification suppression, and impact limits as governed configuration. |
| | F01.3 Operational ownership | Assign accountable owners and backup responders, contact routes, and ownership handover requirements. |
| **F02. Manage resources and relationships** | F02.1 Resource inventory | Discover resources, collect configuration and ownership facts, and reconcile additions, changes, and deletions. |
| | F02.2 Service and dependency relationships | Relate resources to services and workloads through the operating ontology, the shared model of operational meaning; inspect dependency and impact paths. |
| | F02.3 Historical state and coverage | Query state and topology at a stated time, retain source and freshness, and distinguish absent resources from unobserved ones. |

### Operating capabilities

| Function group | Subfunction | Detailed functions |
|----------------|-------------|--------------------|
| **F03. Observe, prevent, and forecast** | F03.1 Operational signals | Collect resource health, metrics, logs, traces, events, and changes through supported sources. |
| | F03.2 Service reliability objectives | Evaluate service-level objectives (SLOs), error budgets, and the rate at which the budget is consumed. |
| | F03.3 Capacity and performance | Assess utilization, performance trends, capacity pressure, and evidence-backed forecasts. |
| | F03.4 Detection quality | Detect abnormal states and trends, assess alert noise, and expose missing permissions, stale signals, and incomplete coverage. |
| **F04. Manage incidents** | F04.1 Incident lifecycle | Normalize and deduplicate events, correlate incident signals, classify severity, and track acknowledgment, ownership, progress, and closure. |
| | F04.2 Investigation and cause analysis | Gather bounded evidence, assess service impact, and distinguish causal hypotheses from confirmed facts and conflicting evidence. |
| | F04.3 Response and follow-up | Propose mitigation, track independently verified recovery, retain unresolved outcomes, and prepare post-incident review and follow-up work. |
| **F05. Govern resilience and recovery** | F05.1 Backup and recovery readiness | Assess backup coverage, recovery-point availability, and restore prerequisites without treating a successful backup as proof of recoverability. |
| | F05.2 Disaster-recovery drills | Plan and authorize restore and failover drills, measure recovery point and time objectives (RPO and RTO), and verify recovery and failback effects. |
| | F05.3 Chaos experiments | Plan separately authorized fault experiments with bounded impact, continuous stop conditions, and tested recovery. |
| **F06. Govern changes and architecture** | F06.1 Proposed-change assessment | Inspect proposed infrastructure and configuration changes, evaluate policy and risk, and present pre-change simulation and rollback evidence. |
| | F06.2 Drift and policy compliance | Detect configuration drift and control gaps, retain exceptions and evidence, and propose governed corrections. |
| | F06.3 Architecture and readiness review | Assemble Architecture Review Board (ARB) evidence, assess architectural constraints, and check ownership and operational readiness before handover or promotion. |
| **F07. Govern cost** | F07.1 Cost visibility and allocation | Associate spend and utilization with resources and services, identify allocation gaps, and explain source coverage. |
| | F07.2 Budgets and forecasts | Compare spend with budgets and baselines, detect anomalies, and forecast costs with stated assumptions. |
| | F07.3 Optimization planning | Recommend resource sizing and cleanup, assess reliability and capacity trade-offs, and route eligible actions through approval and execution. |
| | F07.4 Realized savings | Verify utilization and cost effects against comparable baseline and treatment periods; distinguish estimated savings from realized savings. |

### Shared automation and operator support

| Function group | Subfunction | Detailed functions |
|----------------|-------------|--------------------|
| **F08. Manage actions and workflows** | F08.1 Registered action catalog | Describe supported actions and workflows, parameters, prerequisites, risk limits, and recovery contracts. |
| | F08.2 Response planning | Compose multi-step plans, compare alternatives and objective conflicts, and validate exact targets, expected effects, and stop conditions. |
| | F08.3 Triggers and schedules | Support governed operator, event, and scheduled initiation; track occurrences and execution history and isolate scheduled tasks within declared limits. |
| | F08.4 Execution and recovery | Dispatch authorized work once, track progress, stop at defined boundaries, and apply approved rollback or bounded recovery. |
| **F09. Support operator investigation and collaboration** | F09.1 Evidence-backed conversations | Answer scoped questions about resources, incidents, plans, and FDAI behavior through supported Web Console, CLI, and ChatOps interfaces with citations and explicit uncertainty. |
| | F09.2 Background investigations | Track durable long-running investigations, progress, cancellation, queued input, and resumable results without treating conversation state as execution authority. |
| | F09.3 Notifications and escalation | Route alerts and approval requests, track per-channel delivery and acknowledgment, apply declared fallback routes, and escalate without interpreting silence as consent. |
| | F09.4 Continuity and handover | Preserve authorized conversation context, verified channel identity links, responder assignments, and explicit ownership handover. |
| **F10. Manage operating knowledge and rules** | F10.1 Document and attachment intake | Ingest supported manuals, documents, and evidence attachments with access checks, extraction limits, retention, and deletion controls. |
| | F10.2 Knowledge retrieval and freshness | Retrieve operational knowledge and past cases with source, version, scope, collection time, and freshness; explain missing or conflicting knowledge. |
| | F10.3 Rule governance | Author and scope rules, manage versions, enablement and exceptions, and review proposed additions, revisions, or retirement. |
| | F10.4 Governed knowledge compilation | Propose rules, workflows, and ontology facts from reviewed documents; validate provenance and semantics before separate approval and activation. |
| **F11. Evaluate, learn, and promote** | F11.1 Operational feedback | Capture operator feedback and immutable incident and action outcomes as attributed learning candidates. |
| | F11.2 Evaluation and replay | Evaluate detection, reasoning, plans, and recovery through scenario tests, historical replay, and comparable measured outcomes. |
| | F11.3 Capability promotion and recall | Evaluate capabilities in observation mode, govern activation and promotion, and demote or recall regressions without letting learned output grant authority. |
| **F12. Govern authority, evidence, and service health** | F12.1 Identity and approval | Manage roles, exact-action approvals, conditional prior authorization, approval profiles, expiration, and revocation with separate approval and execution identities. |
| | F12.2 Policy and safety | Apply versioned policies, risk limits, emergency-stop controls, and all required execution safeguards. |
| | F12.3 Audit and data governance | Preserve attributable decisions and effect records, support replay, and enforce data access, retention, privacy, and evidence-export boundaries. |
| | F12.4 FDAI health and recovery | Monitor required services, models, source and delivery connections, durable state, and audit dependencies; expose degraded operation and control-plane recovery needs. |

### Supporting product capabilities

| Function group | Subfunction | Detailed functions |
|----------------|-------------|--------------------|
| **F13. Present operational evidence and reports** | F13.1 Operational views | Present resources, relationships, incidents, work, approvals, history, and source-qualified outcomes through authorized read views. |
| | F13.2 Reports and export | Render catalog-defined reports and supported exports with source, scope, time, and partial-source failures; reports do not execute actions. |
| | F13.3 Outcome measurement | Measure reliability, recovery, automation, and cost outcomes against declared baselines instead of claiming improvement from activity counts alone. |
| **F14. Install, configure, and extend FDAI** | F14.1 Installation and onboarding | Establish installation scope and identity, check prerequisites, configure real source bindings, and verify startup readiness. |
| | F14.2 Updates and distribution | Cover source deployment and signed offline packages; distinguish the designed, not implemented, Hub-managed lifecycle from available installation paths. |
| | F14.3 Capability settings | Expose availability, enablement, mode, prerequisites, licensing limits, and model health without treating enablement or entitlement as action authority. |
| | F14.4 Trusted extensions and integrations | Govern versioned capability bundles, skills, provider adapters, and Model Context Protocol (MCP) tools through publisher trust, compatibility checks, scoped access, activation, and revocation. |
| **F15. Assess code security** | F15.1 Governed scan and finding intake | Acquire authorized exact-revision code for isolated scanning or ingest supported external security findings while reporting scan coverage and limits. |
| | F15.2 Findings and prioritization | Consolidate findings by root cause, separate severity from confidence and priority, and record verification and false-positive review. |
| | F15.3 Developer remediation support | Produce evidence-backed remediation packs for developer-run coding sessions and verify returned fix claims by rescan; this path does not edit customer repositories. |

## Common operating flow

The original five groups below describe the reusable processing flow, not the complete product
inventory. Their numeric references are retained for continuity and are distinct from `F` IDs.
Every applicable product function uses this flow and the common controls; a read-only function
does not acquire mutation authority by reaching a planning stage.

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

Audit and evidence retention span all five groups. Verified outcomes and operator feedback
then feed F10 and F11 as candidates for reviewed knowledge and rule improvements, not as
automatic permission to change policy or execute another action.

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

SRE is the overall operating model. F03-F07 expand the four operating domains below into product
functions, while the shared capabilities support every domain. Reporting and code-security
analysis are supporting capabilities, not additional constitutional domains. Listing a domain
does not prove complete implementation coverage.

| Domain | Application of the common flow |
|--------|--------------------------------|
| **SRE operations** | Observe availability and performance, assess incidents and service objectives, and verify recovery. SRE is the overall operating model. |
| **Resilience** | Assess backup and recovery readiness and govern disaster-recovery drills, restore, failover, and separately authorized Chaos experiments. |
| **Change safety** | Assess proposed changes, configuration drift, policy compliance, and architecture constraints before and after a change. |
| **Cost governance** | Observe spend and utilization, detect anomalies, propose optimization, and verify the effects of approved changes. |

## Coverage and owner references

This inventory was compared with the roadmap index, the SRE capability map, productization
designs, and the reporting and code-security owner documents. These references support scope,
not a claim of exhaustive code review, live validation, or runtime readiness. Detailed contracts
and current implementation status stay with their owners.

| Function groups | Owner references |
|-----------------|------------------|
| **F01-F02: Operating foundation** | [Operating intent](../../roadmap/architecture/operating-intent-source.md), [continuous inventory and relationships](../../roadmap/architecture/continuous-operational-instance-graph.md), [ownership and handover](../../roadmap/interfaces/human-agent-assignment-and-knowledge-handover.md). |
| **F03-F04: SRE and incidents** | [SRE capability map](../sre/README.md), [incident management](../sre/incident-management.md), [capacity and performance](../sre/capacity-and-performance.md). |
| **F05: Resilience** | [Resilience](../capabilities/resilience.md), [disaster recovery and drills](../sre/disaster-recovery-and-drills.md), [Chaos engineering](../sre/chaos-engineering.md). |
| **F06: Change and architecture** | [Change safety](../capabilities/change-safety.md), [architecture review](../../roadmap/architecture/architecture-review-board.md), [operational readiness](../../roadmap/operations/operational-readiness.md). |
| **F07: Cost** | [Cost governance](../capabilities/cost-governance.md), [resource efficiency](../../roadmap/architecture/finops-resource-efficiency.md). |
| **F08: Actions and workflows** | [Agent workflows](../../roadmap/agents/agent-workflows.md), [operational planning](../../roadmap/decisioning/operational-planning.md), [process automation](../../roadmap/decisioning/process-automation.md). |
| **F09: Operator support** | [Operator conversations](../guides/use-operator-conversations.md), [channels and notifications](../../roadmap/interfaces/channels-and-notifications.md), [background investigations](../../roadmap/interfaces/background-task-sessions.md). |
| **F10: Knowledge and rules** | [Document ingestion](../../roadmap/interfaces/document-ingestion.md), [manual distillation](../../roadmap/rules-and-detection/manual-distillation.md), [rule governance](../../roadmap/rules-and-detection/rule-governance.md). |
| **F11: Evaluation and learning** | [Operational learning](../../roadmap/rules-and-detection/operational-learning-ontology.md), [postmortems and learning](../sre/postmortems-and-learning.md), [capability lifecycle](../../roadmap/architecture/capability-bundle-lifecycle.md). |
| **F12: Authority and health** | [FDAI Constitution](../../roadmap/architecture/fdai-constitution.md), [governance profiles](../../roadmap/decisioning/operator-governance-profiles.md), [data governance](../../roadmap/architecture/data-governance.md), [operating and verification](../../roadmap/operations/operating-and-verification.md). |
| **F13: Reports and outcomes** | [Reporting](../../roadmap/interfaces/reporting-subsystem.md), [measuring SRE outcomes](../sre/measuring-sre-outcomes.md). |
| **F14: Product lifecycle and extensions** | [Deployment quickstart](../deploy-quickstart.md), [Hub-managed lifecycle](../../roadmap/deployment/hub-managed-lifecycle.md), [productization and extensibility](../../roadmap/fork-and-sequencing/productization-and-extensibility.md). |
| **F15: Code security** | [Code-security findings](../../roadmap/operations/code-security-findings.md), [code-security scanning](../../roadmap/operations/code-security-scanning.md). |

## Detailed function records

Give each detailed function an ID beneath its subfunction. Keep the ID stable when wording
changes, and use it to connect acceptance tests and implementation evidence without mixing
target requirements with delivery status.

The following example expands product subfunction `F12.1` into one testable requirement. The
original draft ID `4.1.3` remains an alias to preserve references to approval revocation.

| Field | Example |
|-------|---------|
| **Function ID** | `F12.1.3` |
| **Previous draft ID** | `4.1.3` |
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

Record those claims separately rather than reducing them to a single complete/incomplete flag.
Until the owning code and evidence have been checked, implementation coverage is not assessed.

| Coverage field | Required information |
|----------------|----------------------|
| **Function and implementation** | Stable function ID, owner, and separately evidenced design-only, partial, or implemented scope. |
| **Supported scope** | Resource and action types, interfaces, known exclusions, and deployment prerequisites. |
| **Bindings and authority** | Real source and channel bindings, effective scope, capability mode, and approval requirements. |
| **Verification** | Separate local test results, live operational observations, and promotion or production-readiness evidence. |
| **Traceability** | Exact source or release revision, test references, observation time, evidence provenance, and remaining work. |

## Related docs

| To learn about | Read |
|----------------|------|
| Initial setup and the operator journey | [Get started](../get-started.md) |
| Component responsibilities | [FDAI Architecture](../architecture.md) |
| Observation before enabling changes | [Observe, then enable changes](shadow-then-enforce.md) |
| Approval and notification surfaces | [Approvals and channels](approvals-and-channels.md) |
| Product safety and authority requirements | [FDAI Constitution](../../roadmap/architecture/fdai-constitution.md) |
