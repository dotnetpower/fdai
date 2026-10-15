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

> Readiness describes completion within a declared support scope. It does not describe the
> connection state of a particular installation or grant automatic execution authority. Local
> verification and live operational verification remain separate in the assessment evidence.

All 52 subfunctions start as **Not assessed** in this register. This does not override existing
implementation claims in the owner documents or mean that the functions are unimplemented.
Group summaries count subfunction assessments, not deployment health or percentage complete.
**Overall: Ready 0/52; Not assessed 52/52.** No code or operational readiness audit is claimed.

### Operational foundation

| Function group | Subfunction | <span style="display: inline-block; min-width: 16rem">Detailed functions</span> | Readiness |
|----------------|-------------|--------------------|-----------|
| **F01. Configure the operating environment** <br><span style="white-space: nowrap">Ready 0/3;</span><br><span style="white-space: nowrap">Not assessed 3/3</span> | F01.1 Management scope | Configure the managed subscription and resource-group scope, observation sources, access requirements, and connection readiness. | <span style="white-space: nowrap">[Not assessed](#readiness-assessment)</span> |
| | F01.2 Operating criteria | Define service objectives, thresholds, maintenance windows, notification suppression, and impact limits as governed configuration. | <span style="white-space: nowrap">[Not assessed](#readiness-assessment)</span> |
| | F01.3 Operational ownership | Assign accountable owners and backup responders, contact routes, and ownership handover requirements. | <span style="white-space: nowrap">[Not assessed](#readiness-assessment)</span> |
| **F02. Manage resources and relationships** <br><span style="white-space: nowrap">Ready 0/3;</span><br><span style="white-space: nowrap">Not assessed 3/3</span> | F02.1 Resource inventory | Discover resources, collect configuration and ownership facts, and reconcile additions, changes, and deletions. | <span style="white-space: nowrap">[Not assessed](#readiness-assessment)</span> |
| | F02.2 Service and dependency relationships | Relate resources to services and workloads through the operating ontology, the shared model of operational meaning; inspect dependency and impact paths. | <span style="white-space: nowrap">[Not assessed](#readiness-assessment)</span> |
| | F02.3 Historical state and coverage | Query state and topology at a stated time, retain source and freshness, and distinguish absent resources from unobserved ones. | <span style="white-space: nowrap">[Not assessed](#readiness-assessment)</span> |

### Operating capabilities

| Function group | Subfunction | <span style="display: inline-block; min-width: 16rem">Detailed functions</span> | Readiness |
|----------------|-------------|--------------------|-----------|
| **F03. Observe, prevent, and forecast** <br><span style="white-space: nowrap">Ready 0/4;</span><br><span style="white-space: nowrap">Not assessed 4/4</span> | F03.1 Operational signals | Collect resource health, metrics, logs, traces, events, and changes through supported sources. | <span style="white-space: nowrap">[Not assessed](#readiness-assessment)</span> |
| | F03.2 Service reliability objectives | Evaluate service-level objectives (SLOs), error budgets, and the rate at which the budget is consumed. | <span style="white-space: nowrap">[Not assessed](#readiness-assessment)</span> |
| | F03.3 Capacity and performance | Assess utilization, performance trends, capacity pressure, and evidence-backed forecasts. | <span style="white-space: nowrap">[Not assessed](#readiness-assessment)</span> |
| | F03.4 Detection quality | Detect abnormal states and trends, assess alert noise, and expose missing permissions, stale signals, and incomplete coverage. | <span style="white-space: nowrap">[Not assessed](#readiness-assessment)</span> |
| **F04. Manage incidents** <br><span style="white-space: nowrap">Ready 0/3;</span><br><span style="white-space: nowrap">Not assessed 3/3</span> | F04.1 Incident lifecycle | Normalize and deduplicate events, correlate incident signals, classify severity, and track acknowledgment, ownership, progress, and closure. | <span style="white-space: nowrap">[Not assessed](#readiness-assessment)</span> |
| | F04.2 Investigation and cause analysis | Gather bounded evidence, assess service impact, and distinguish causal hypotheses from confirmed facts and conflicting evidence. | <span style="white-space: nowrap">[Not assessed](#readiness-assessment)</span> |
| | F04.3 Response and follow-up | Propose mitigation, track independently verified recovery, retain unresolved outcomes, and prepare post-incident review and follow-up work. | <span style="white-space: nowrap">[Not assessed](#readiness-assessment)</span> |
| **F05. Govern resilience and recovery** <br><span style="white-space: nowrap">Ready 0/3;</span><br><span style="white-space: nowrap">Not assessed 3/3</span> | F05.1 Backup and recovery readiness | Assess backup coverage, recovery-point availability, and restore prerequisites without treating a successful backup as proof of recoverability. | <span style="white-space: nowrap">[Not assessed](#readiness-assessment)</span> |
| | F05.2 Disaster-recovery drills | Plan and authorize restore and failover drills, measure recovery point and time objectives (RPO and RTO), and verify recovery and failback effects. | <span style="white-space: nowrap">[Not assessed](#readiness-assessment)</span> |
| | F05.3 Chaos experiments | Plan separately authorized fault experiments with bounded impact, continuous stop conditions, and tested recovery. | <span style="white-space: nowrap">[Not assessed](#readiness-assessment)</span> |
| **F06. Govern changes and architecture** <br><span style="white-space: nowrap">Ready 0/3;</span><br><span style="white-space: nowrap">Not assessed 3/3</span> | F06.1 Proposed-change assessment | Inspect proposed infrastructure and configuration changes, evaluate policy and risk, and present pre-change simulation and rollback evidence. | <span style="white-space: nowrap">[Not assessed](#readiness-assessment)</span> |
| | F06.2 Drift and policy compliance | Detect configuration drift and control gaps, retain exceptions and evidence, and propose governed corrections. | <span style="white-space: nowrap">[Not assessed](#readiness-assessment)</span> |
| | F06.3 Architecture and readiness review | Assemble Architecture Review Board (ARB) evidence, assess architectural constraints, and check ownership and operational readiness before handover or promotion. | <span style="white-space: nowrap">[Not assessed](#readiness-assessment)</span> |
| **F07. Govern cost** <br><span style="white-space: nowrap">Ready 0/4;</span><br><span style="white-space: nowrap">Not assessed 4/4</span> | F07.1 Cost visibility and allocation | Associate spend and utilization with resources and services, identify allocation gaps, and explain source coverage. | <span style="white-space: nowrap">[Not assessed](#readiness-assessment)</span> |
| | F07.2 Budgets and forecasts | Compare spend with budgets and baselines, detect anomalies, and forecast costs with stated assumptions. | <span style="white-space: nowrap">[Not assessed](#readiness-assessment)</span> |
| | F07.3 Optimization planning | Recommend resource sizing and cleanup, assess reliability and capacity trade-offs, and route eligible actions through approval and execution. | <span style="white-space: nowrap">[Not assessed](#readiness-assessment)</span> |
| | F07.4 Realized savings | Verify utilization and cost effects against comparable baseline and treatment periods; distinguish estimated savings from realized savings. | <span style="white-space: nowrap">[Not assessed](#readiness-assessment)</span> |

### Shared automation and operator support

| Function group | Subfunction | <span style="display: inline-block; min-width: 16rem">Detailed functions</span> | Readiness |
|----------------|-------------|--------------------|-----------|
| **F08. Manage actions and workflows** <br><span style="white-space: nowrap">Ready 0/4;</span><br><span style="white-space: nowrap">Not assessed 4/4</span> | F08.1 Registered action catalog | Describe supported actions and workflows, parameters, prerequisites, risk limits, and recovery contracts. | <span style="white-space: nowrap">[Not assessed](#readiness-assessment)</span> |
| | F08.2 Response planning | Compose multi-step plans, compare alternatives and objective conflicts, and validate exact targets, expected effects, and stop conditions. | <span style="white-space: nowrap">[Not assessed](#readiness-assessment)</span> |
| | F08.3 Triggers and schedules | Support governed operator, event, and scheduled initiation; track occurrences and execution history and isolate scheduled tasks within declared limits. | <span style="white-space: nowrap">[Not assessed](#readiness-assessment)</span> |
| | F08.4 Execution and recovery | Dispatch authorized work once, track progress, stop at defined boundaries, and apply approved rollback or bounded recovery. | <span style="white-space: nowrap">[Not assessed](#readiness-assessment)</span> |
| **F09. Support operator investigation and collaboration** <br><span style="white-space: nowrap">Ready 0/4;</span><br><span style="white-space: nowrap">Not assessed 4/4</span> | F09.1 Evidence-backed conversations | Answer scoped questions about resources, incidents, plans, and FDAI behavior through supported Web Console, CLI, and ChatOps interfaces with citations and explicit uncertainty. | <span style="white-space: nowrap">[Not assessed](#readiness-assessment)</span> |
| | F09.2 Background investigations | Track durable long-running investigations, progress, cancellation, queued input, and resumable results without treating conversation state as execution authority. | <span style="white-space: nowrap">[Not assessed](#readiness-assessment)</span> |
| | F09.3 Notifications and escalation | Route alerts and approval requests, track per-channel delivery and acknowledgment, apply declared fallback routes, and escalate without interpreting silence as consent. | <span style="white-space: nowrap">[Not assessed](#readiness-assessment)</span> |
| | F09.4 Continuity and handover | Preserve authorized conversation context, verified channel identity links, responder assignments, and explicit ownership handover. | <span style="white-space: nowrap">[Not assessed](#readiness-assessment)</span> |
| **F10. Manage operating knowledge and rules** <br><span style="white-space: nowrap">Ready 0/4;</span><br><span style="white-space: nowrap">Not assessed 4/4</span> | F10.1 Document and attachment intake | Ingest supported manuals, documents, and evidence attachments with access checks, extraction limits, retention, and deletion controls. | <span style="white-space: nowrap">[Not assessed](#readiness-assessment)</span> |
| | F10.2 Knowledge retrieval and freshness | Retrieve operational knowledge and past cases with source, version, scope, collection time, and freshness; explain missing or conflicting knowledge. | <span style="white-space: nowrap">[Not assessed](#readiness-assessment)</span> |
| | F10.3 Rule governance | Author and scope rules, manage versions, enablement and exceptions, and review proposed additions, revisions, or retirement. | <span style="white-space: nowrap">[Not assessed](#readiness-assessment)</span> |
| | F10.4 Governed knowledge compilation | Propose rules, workflows, and ontology facts from reviewed documents; validate provenance and semantics before separate approval and activation. | <span style="white-space: nowrap">[Not assessed](#readiness-assessment)</span> |
| **F11. Evaluate, learn, and promote** <br><span style="white-space: nowrap">Ready 0/3;</span><br><span style="white-space: nowrap">Not assessed 3/3</span> | F11.1 Operational feedback | Capture operator feedback and immutable incident and action outcomes as attributed learning candidates. | <span style="white-space: nowrap">[Not assessed](#readiness-assessment)</span> |
| | F11.2 Evaluation and replay | Evaluate detection, reasoning, plans, and recovery through scenario tests, historical replay, and comparable measured outcomes. | <span style="white-space: nowrap">[Not assessed](#readiness-assessment)</span> |
| | F11.3 Capability promotion and recall | Evaluate capabilities in observation mode, govern activation and promotion, and demote or recall regressions without letting learned output grant authority. | <span style="white-space: nowrap">[Not assessed](#readiness-assessment)</span> |
| **F12. Govern authority, evidence, and service health** <br><span style="white-space: nowrap">Ready 0/4;</span><br><span style="white-space: nowrap">Not assessed 4/4</span> | F12.1 Identity and approval | Manage roles, exact-action approvals, conditional prior authorization, approval profiles, expiration, and revocation with separate approval and execution identities. | <span style="white-space: nowrap">[Not assessed](#readiness-assessment)</span> |
| | F12.2 Policy and safety | Apply versioned policies, risk limits, emergency-stop controls, and all required execution safeguards. | <span style="white-space: nowrap">[Not assessed](#readiness-assessment)</span> |
| | F12.3 Audit and data governance | Preserve attributable decisions and effect records, support replay, and enforce data access, retention, privacy, and evidence-export boundaries. | <span style="white-space: nowrap">[Not assessed](#readiness-assessment)</span> |
| | F12.4 FDAI health and recovery | Monitor required services, models, source and delivery connections, durable state, and audit dependencies; expose degraded operation and control-plane recovery needs. | <span style="white-space: nowrap">[Not assessed](#readiness-assessment)</span> |

### Supporting product capabilities

| Function group | Subfunction | <span style="display: inline-block; min-width: 16rem">Detailed functions</span> | Readiness |
|----------------|-------------|--------------------|-----------|
| **F13. Present operational evidence and reports** <br><span style="white-space: nowrap">Ready 0/3;</span><br><span style="white-space: nowrap">Not assessed 3/3</span> | F13.1 Operational views | Present resources, relationships, incidents, work, approvals, history, and source-qualified outcomes through authorized read views. | <span style="white-space: nowrap">[Not assessed](#readiness-assessment)</span> |
| | F13.2 Reports and export | Render catalog-defined reports and supported exports with source, scope, time, and partial-source failures; reports do not execute actions. | <span style="white-space: nowrap">[Not assessed](#readiness-assessment)</span> |
| | F13.3 Outcome measurement | Measure reliability, recovery, automation, and cost outcomes against declared baselines instead of claiming improvement from activity counts alone. | <span style="white-space: nowrap">[Not assessed](#readiness-assessment)</span> |
| **F14. Install, configure, and extend FDAI** <br><span style="white-space: nowrap">Ready 0/4;</span><br><span style="white-space: nowrap">Not assessed 4/4</span> | F14.1 Installation and onboarding | Establish installation scope and identity, check prerequisites, configure real source bindings, and verify startup readiness. | <span style="white-space: nowrap">[Not assessed](#readiness-assessment)</span> |
| | F14.2 Updates and distribution | Cover source deployment and signed offline packages; distinguish the designed, not implemented, Hub-managed lifecycle from available installation paths. | <span style="white-space: nowrap">[Not assessed](#readiness-assessment)</span> |
| | F14.3 Capability settings | Expose availability, enablement, mode, prerequisites, licensing limits, and model health without treating enablement or entitlement as action authority. | <span style="white-space: nowrap">[Not assessed](#readiness-assessment)</span> |
| | F14.4 Trusted extensions and integrations | Govern versioned capability bundles, skills, provider adapters, and Model Context Protocol (MCP) tools through publisher trust, compatibility checks, scoped access, activation, and revocation. | <span style="white-space: nowrap">[Not assessed](#readiness-assessment)</span> |
| **F15. Assess code security** <br><span style="white-space: nowrap">Ready 0/3;</span><br><span style="white-space: nowrap">Not assessed 3/3</span> | F15.1 Governed scan and finding intake | Acquire authorized exact-revision code for isolated scanning or ingest supported external security findings while reporting scan coverage and limits. | <span style="white-space: nowrap">[Not assessed](#readiness-assessment)</span> |
| | F15.2 Findings and prioritization | Consolidate findings by root cause, separate severity from confidence and priority, and record verification and false-positive review. | <span style="white-space: nowrap">[Not assessed](#readiness-assessment)</span> |
| | F15.3 Developer remediation support | Produce evidence-backed remediation packs for developer-run coding sessions and verify returned fix claims by rescan; this path does not edit customer repositories. | <span style="white-space: nowrap">[Not assessed](#readiness-assessment)</span> |

## Readiness states

| State | Assessment rule |
|-------|-----------------|
| **Ready** | Implementation and required verification are complete for the declared scope, with current evidence and no remaining mandatory condition. |
| **Partial** | Some required implementation or verification remains incomplete; record the supported subset and the remaining work. |
| **Blocked** | A required condition prevents use in the assessed environment; record that environment's scope, the blocker, and recovery conditions. |
| **Planned** | Design exists but no executable implementation exists for the assessed scope. |
| **Not assessed** | Evidence has not been reviewed or no longer supports a current assessment. This is neither Ready nor evidence of missing implementation. |

Only product subfunctions receive readiness states. The common flow below is a process model,
not a second status inventory. Rollups retain each state's count instead of marking a group
Ready when only some children are Ready. Update the row, group summary, and overall counts
together after an evidence review; changes in scope or source revision require revalidation.

## Readiness assessment

Every current status link leads here because no per-function readiness assessment has been
performed yet. The owner references establish intended scope, not readiness evidence. When a
function is assessed, link its status to a function-specific record using the fields below.

| Assessment field | Required information |
|------------------|----------------------|
| **Function, state, and assessment basis** | Stable function ID, assessed state, accountable reviewer, source or release revision, and assessment date. |
| **Support scope** | Supported resources, actions, interfaces, exclusions, and the acceptance criteria being assessed. |
| **Verification evidence** | Code and test references and dated observations, with local, live operational, and production-readiness results distinguished. |
| **Use conditions** | Required source bindings, permissions, channels, configuration, capability mode, and the scope of any environment-specific assessment. |
| **Remaining work and reassessment** | Observable unmet conditions, the work required to reach Ready, and revision or freshness changes that invalidate the assessment. |

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
| **Readiness** | Not assessed; the acceptance criteria below are requirements, not verification evidence. |
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
