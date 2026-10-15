---
title: FDAI Function Readiness Assessment
description: Evidence-backed readiness decisions and remaining conditions for the 52 FDAI product subfunctions.
---

# FDAI Function Readiness Assessment

This assessment records why each function in the [functional specification](functional-specification.md)
is Ready or Partial. It separates executable implementation, documented delivery gaps, and
installation-specific operational qualification instead of treating a feature name as proof.

> **Assessment basis:** 2026-10-15, base source revision
> `426507a57cbfbd9bc7a9b2c8941c3c5f60db229d` plus the current change. GitHub Copilot compared all
> 52 requirements with their owner records, then implemented or reverified the ten fastest closure
> candidates. The current campaign passed **389 tests across 27 focused file selections**, Console
> typecheck, and Terraform format checks. This is a repository assessment, not independent
> human approval or a new live Azure, model, production-database, or deployment validation.

## How to read the decisions

**Overall:** <span class="fdai-readiness-badge" data-readiness="ready">Ready 15/52</span> <span class="fdai-readiness-badge" data-readiness="partial">Partial 37/52</span> <span class="fdai-readiness-badge" data-readiness="blocked">Blocked 0/52</span> <span class="fdai-readiness-badge" data-readiness="planned">Planned 0/52</span> <span class="fdai-readiness-badge" data-readiness="not-assessed">Not assessed 0/52</span>
Ready applies only to the support scope stated in its record. It does not certify every
deployment, provider, scale, or autonomous action. Partial means the stated function has an
implementation, but mandatory coverage, integration, or verification remains open in the cited
owner. No installation was selected for a Blocked assessment. No entire subfunction was found
to be design-only; planned components inside a partially implemented function remain explicit.

The 37 Partial decisions use owner-ledger evidence and documented limitations, not newly rerun
runtime tests for every component. Historical test and live receipts remain historical; this
session does not renew them. Each remaining condition below identifies what prevents a Ready
claim for the full function. Reassess when its code, declared scope, or evidence changes.

Badge meanings are listed in the specification [readiness definitions](functional-specification.md#readiness-states).
Function names link to the corresponding record here. Engineering implementation ledgers are
English-only references and are not replaced by this assessment.

## F01. Operating environment

| Function | State | Evidence, supported scope, and remaining conditions |
|----------|-------|-----------------------------------------------------|
| <span id="f01-1">F01.1</span> | <span class="fdai-readiness-badge" data-readiness="ready">Ready</span> | Scope: pinned management-scope admission, continuous revalidation, fail-closed quarantine/recovery mechanics, and exact configured source bindings. The [intent ledger](../../roadmap-implementation/architecture/operating-intent-source.md), [inventory ledger](../../roadmap-implementation/architecture/continuous-operational-instance-graph.md), and current focused cohort support this scope. A particular installation's provider reachability and governed quarantine drill remain deployment qualification, not part of this Ready claim. |
| <span id="f01-2">F01.2</span> | <span class="fdai-readiness-badge" data-readiness="partial">Partial</span> | Governed intent and change windows exist in the [intent ledger](../../roadmap-implementation/architecture/operating-intent-source.md); rule settings and exceptions exist in the [rule ledger](../../roadmap-implementation/rules-and-detection/rule-governance.md). Source revalidation evidence and the durable rule-revision upgrade remain open. |
| <span id="f01-3">F01.3</span> | <span class="fdai-readiness-badge" data-readiness="ready">Ready</span> | Scope: typed primary and backup ownership, stewardship coverage checks, escalation resolution, and explicit handover mechanics for configured bindings. The [ownership ledger](../../roadmap-implementation/interfaces/human-agent-assignment-and-knowledge-handover.md) and current ownership/coverage cohort support this scope. Directory-specific people, contactability drills, and installation promotion receipts remain deployment qualification. |

## F02. Resources and relationships

| Function | State | Evidence, supported scope, and remaining conditions |
|----------|-------|-----------------------------------------------------|
| <span id="f02-1">F02.1</span> | <span class="fdai-readiness-badge" data-readiness="partial">Partial</span> | Complete inventory promotion and reconciliation have implementation and retained validation in the [inventory ledger](../../roadmap-implementation/architecture/continuous-operational-instance-graph.md). Private-safe change acceleration, exact-main provider closure, and deployment-specific schema/grant qualification remain open. |
| <span id="f02-2">F02.2</span> | <span class="fdai-readiness-badge" data-readiness="partial">Partial</span> | Verified relationships and bounded graph exploration exist in the [inventory ledger](../../roadmap-implementation/architecture/continuous-operational-instance-graph.md). Application-centric relationship completion and authenticated runtime-call evidence remain open; modeled links are not proof of every dependency. |
| <span id="f02-3">F02.3</span> | <span class="fdai-readiness-badge" data-readiness="ready">Ready</span> | Scope: normalized bitemporal observations, point-in-time topology, explicit source and interval coverage reasons, and absence-versus-unobserved semantics. The [inventory ledger](../../roadmap-implementation/architecture/continuous-operational-instance-graph.md) and focused pending-state/PostgreSQL tests support this scope. Installation retention length, archive/restore drills, and provider-wide interval completeness remain deployment qualification. |

## F03. Observation, prevention, and forecasts

| Function | State | Evidence, supported scope, and remaining conditions |
|----------|-------|-----------------------------------------------------|
| <span id="f03-1">F03.1</span> | <span class="fdai-readiness-badge" data-readiness="partial">Partial</span> | Signal adapters and detectors are covered by the [SRE map](../sre/README.md#sre-capability-map) and [inventory ledger](../../roadmap-implementation/architecture/continuous-operational-instance-graph.md). Real telemetry bindings, per-source completeness, and deployed collection measurement remain required for the full source set. |
| <span id="f03-2">F03.2</span> | <span class="fdai-readiness-badge" data-readiness="ready">Ready</span> | Scope: schema-validated workload SLOs, error-budget and multi-window burn evaluation, fail-closed insufficient-data handling, breach event publication, and an optional single-replica scheduled job. The [SLO guide](../sre/slos-and-error-budgets.md) and focused CLI/infrastructure tests support this scope. Workload definitions, metric bindings, schedule enablement, and measured run receipts remain installation configuration and qualification. |
| <span id="f03-3">F03.3</span> | <span class="fdai-readiness-badge" data-readiness="partial">Partial</span> | Capacity and forecast reasoning exists in the [capacity guide](../sre/capacity-and-performance.md) and [planning ledger](../../roadmap-implementation/decisioning/operational-planning.md). Fresh demand, quota/dependency evidence and the governed scale-out outcome cohort remain open. |
| <span id="f03-4">F03.4</span> | <span class="fdai-readiness-badge" data-readiness="partial">Partial</span> | Deterministic assessment and source-gap reporting are implemented in the [alert-quality ledger](../../roadmap-implementation/operations/alert-noise-governance.md). Authoritative recipient/ownership evidence, independent labels, provider conformance, and operational acceptance remain unverified. |

## F04. Incidents

| Function | State | Evidence, supported scope, and remaining conditions |
|----------|-------|-----------------------------------------------------|
| <span id="f04-1">F04.1</span> | <span class="fdai-readiness-badge" data-readiness="ready">Ready</span> | Scope: the built-in correlated incident registry and lifecycle workflow, including severity/state changes, assignment, audited writes, and replay. Reviewed [registry](../../../services/core-control-plane/src/fdai/core/incident/registry.py) and [workflow](../../../services/core-control-plane/src/fdai/core/incident/workflow.py); reran [lifecycle](../../../services/core-control-plane/tests/core/incident/test_incident_lifecycle.py), [workflow](../../../services/core-control-plane/tests/core/incident/test_incident_workflow.py), and [storm](../../../services/core-control-plane/tests/core/incident/test_storm.py) tests in cohort A. External notification qualification is separate under F09.3. |
| <span id="f04-2">F04.2</span> | <span class="fdai-readiness-badge" data-readiness="partial">Partial</span> | Tiered hypotheses, governed documents, telemetry routing, and causal evidence are implemented in the [RCA ledger](../../roadmap-implementation/rules-and-detection/root-cause-analysis.md). Exact-revision operational cause accuracy, abstention, multi-workspace evidence, and independently verified outcomes remain open. |
| <span id="f04-3">F04.3</span> | <span class="fdai-readiness-badge" data-readiness="partial">Partial</span> | Response planning and postmortem foundations exist in the [planning ledger](../../roadmap-implementation/decisioning/operational-planning.md) and [learning guide](../sre/postmortems-and-learning.md). Governed end-to-end approval, execution, observed recovery, and follow-up closure are not established for the full response path. |

## F05. Resilience and recovery

| Function | State | Evidence, supported scope, and remaining conditions |
|----------|-------|-----------------------------------------------------|
| <span id="f05-1">F05.1</span> | <span class="fdai-readiness-badge" data-readiness="partial">Partial</span> | Backup checks and restore prerequisites are defined in the [DR guide](../sre/disaster-recovery-and-drills.md) with implemented recovery mechanics in the [recovery ledger](../../roadmap-implementation/decisioning/recovery-and-chaos-enforcement.md). Retain exact-workload recovery-point, restore, and independent integrity evidence; backup success alone is insufficient. |
| <span id="f05-2">F05.2</span> | <span class="fdai-readiness-badge" data-readiness="partial">Partial</span> | The [DR guide](../sre/disaster-recovery-and-drills.md#recovering-fdai-itself) distinguishes implemented single-region recovery foundations from alternate-region infrastructure, traffic/event continuity, and measured failover/failback. Full-scope RPO/RTO and cleanup receipts remain required. |
| <span id="f05-3">F05.3</span> | <span class="fdai-readiness-badge" data-readiness="partial">Partial</span> | The provider package and guarded execution mechanics exist in the [Chaos ledger](../../roadmap-implementation/decisioning/recovery-and-chaos-enforcement.md). Protected provider inputs, actual agent-owned authority records, legitimate promotion, and the governed fault/recovery campaign remain open. |

## F06. Changes and architecture

| Function | State | Evidence, supported scope, and remaining conditions |
|----------|-------|-----------------------------------------------------|
| <span id="f06-1">F06.1</span> | <span class="fdai-readiness-badge" data-readiness="partial">Partial</span> | Policy assessment and typed planning exist in the [change guide](../capabilities/change-safety.md) and [planning ledger](../../roadmap-implementation/decisioning/operational-planning.md). Current end-to-end human approval and independent outcome evidence remain open; a simulation or proposal alone does not close the change. |
| <span id="f06-2">F06.2</span> | <span class="fdai-readiness-badge" data-readiness="partial">Partial</span> | Rule scoping, activation, and exceptions exist in the [rule ledger](../../roadmap-implementation/rules-and-detection/rule-governance.md). The durable rule-revision compatibility upgrade and operational rollout phases remain open, as does complete source coverage for drift assertions. |
| <span id="f06-3">F06.3</span> | <span class="fdai-readiness-badge" data-readiness="partial">Partial</span> | Review mechanics exist in the [ARB ledger](../../roadmap-implementation/architecture/architecture-review-board.md) and [readiness ledger](../../roadmap-implementation/operations/operational-readiness.md). Production evidence/owner bindings and the remediation publisher to the risk/approval ingress remain incomplete. |

## F07. Cost governance

| Function | State | Evidence, supported scope, and remaining conditions |
|----------|-------|-----------------------------------------------------|
| <span id="f07-1">F07.1</span> | <span class="fdai-readiness-badge" data-readiness="partial">Partial</span> | Subscription/resource analytics and Console projections are implemented in the [efficiency ledger](../../roadmap-implementation/architecture/finops-resource-efficiency.md). Complete utilization and relationship coverage, exact-cutoff exclusions, and current authoritative readback remain open. |
| <span id="f07-2">F07.2</span> | <span class="fdai-readiness-badge" data-readiness="partial">Partial</span> | Budget, trend, and anomaly foundations exist in the [efficiency ledger](../../roadmap-implementation/architecture/finops-resource-efficiency.md) and [FinOps ledger](../../roadmap-implementation/architecture/finops-autonomous-operations.md). Compatible utilization evidence and the qualifying operational cohort are incomplete; retained partial analytics are not a complete forecast qualification. |
| <span id="f07-3">F07.3</span> | <span class="fdai-readiness-badge" data-readiness="partial">Partial</span> | Generic right-size guards exist, but reviewed service-family profiles, coupled-target decision composition, and targeted clarification are explicitly not started in the [efficiency ledger](../../roadmap-implementation/architecture/finops-resource-efficiency.md). Shared foundations do not complete resource-level optimization. |
| <span id="f07-4">F07.4</span> | <span class="fdai-readiness-badge" data-readiness="partial">Partial</span> | Independent effect settlement is implemented in the [FinOps ledger](../../roadmap-implementation/architecture/finops-autonomous-operations.md). A live, pinned resource-efficiency episode with fully settled cost/capacity/service/recovery effects is still absent in the [efficiency ledger](../../roadmap-implementation/architecture/finops-resource-efficiency.md). |

## F08. Actions and workflows

| Function | State | Evidence, supported scope, and remaining conditions |
|----------|-------|-----------------------------------------------------|
| <span id="f08-1">F08.1</span> | <span class="fdai-readiness-badge" data-readiness="ready">Ready</span> | Scope: the shipped registered ActionType and Workflow catalogs, including parameters, references, risk/recovery declarations, and shadow defaults. Reviewed [ActionType](../../../services/core-control-plane/src/fdai/rule_catalog/schema/action_type.py) and [Workflow](../../../services/core-control-plane/src/fdai/rule_catalog/schema/workflow.py) loaders; reran [action catalog](../../../services/core-control-plane/tests/rule_catalog/test_action_type_catalog.py) and [workflow catalog](../../../services/core-control-plane/tests/rule_catalog/test_workflow_catalog.py) tests in cohort A. Catalog validity does not prove every design-inventory workflow is implemented or promoted. |
| <span id="f08-2">F08.2</span> | <span class="fdai-readiness-badge" data-readiness="partial">Partial</span> | Multi-step plans, specialist arbitration, and recovery contracts exist in the [planning ledger](../../roadmap-implementation/decisioning/operational-planning.md). Independent-service human-approval binding and governed end-to-end scale-out effect evidence remain open. |
| <span id="f08-3">F08.3</span> | <span class="fdai-readiness-badge" data-readiness="ready">Ready</span> | Scope: built-in due/manual dispatch, supported schedule kinds, bounded isolation, history, and continuation mechanics. Reviewed [scheduler](../../../services/core-control-plane/src/fdai/core/scheduler/service.py); cohort B reran seven [scheduler test files](../../../services/core-control-plane/tests/core/scheduler/), including duplicate suppression, history, isolation, and continuation retention/delivery. Dispatch acceptance is not action success or live channel qualification. |
| <span id="f08-4">F08.4</span> | <span class="fdai-readiness-badge" data-readiness="partial">Partial</span> | Typed execution, stop, and recovery mechanics exist in the [workflow ledger](../../roadmap-implementation/decisioning/process-automation.md) and [recovery ledger](../../roadmap-implementation/decisioning/recovery-and-chaos-enforcement.md). A promoted workflow with independent effect and recovery closure remains open; provider fencing also limits standing emergency authority. |

## F09. Operator investigation and collaboration

| Function | State | Evidence, supported scope, and remaining conditions |
|----------|-------|-----------------------------------------------------|
| <span id="f09-1">F09.1</span> | <span class="fdai-readiness-badge" data-readiness="partial">Partial</span> | Scoped conversation and evidence-backed investigation are documented in the [operator guide](../guides/use-operator-conversations.md) and [RCA ledger](../../roadmap-implementation/rules-and-detection/root-cause-analysis.md). Governed cause-quality qualification and complete source/channel bindings remain open; a rendered answer is not proof of semantic accuracy. |
| <span id="f09-2">F09.2</span> | <span class="fdai-readiness-badge" data-readiness="ready">Ready</span> | Scope: durable owner-scoped read investigations, leases, quotas, progress, typed create/cancel intake, restart-safe completion, Web handoff, Slack/Teams outbound enqueue, and Live-only Console controls. The [background-task ledger](../../roadmap-implementation/interfaces/background-task-sessions.md), focused tests, and isolated responsive Console check support this scope. Provider delivery and process-loss drills remain installation qualification. |
| <span id="f09-3">F09.3</span> | <span class="fdai-readiness-badge" data-readiness="partial">Partial</span> | Routing and durable channel mechanics exist in the [channel ledger](../../roadmap-implementation/interfaces/channels-and-notifications.md). Live callback/broker receipts, outbound Slack approval binding, and governed urgency/escalation evidence in the [authority ledger](../../roadmap-implementation/decisioning/escalation-and-standing-authority.md) remain open. |
| <span id="f09-4">F09.4</span> | <span class="fdai-readiness-badge" data-readiness="ready">Ready</span> | Scope: principal-bound continuation anchors, retained typed context, follow-up delivery state, expiry, and bounded retention. The [continuation ledger](../../roadmap-implementation/interfaces/scheduled-result-continuations.md) and current continuation cohort support this scope. Live channel-origin identity, real responder assignments, legal-hold purge, and proactive handover promotion remain separate installation qualification. |

## F10. Knowledge and rules

| Function | State | Evidence, supported scope, and remaining conditions |
|----------|-------|-----------------------------------------------------|
| <span id="f10-1">F10.1</span> | <span class="fdai-readiness-badge" data-readiness="partial">Partial</span> | Intake, protection, extraction, indexing, and retention controls exist in the [document ledger](../../roadmap-implementation/interfaces/document-ingestion.md). One governed five-service upload-to-citation/deletion/restart receipt and approved external protection/SharePoint bindings remain open. |
| <span id="f10-2">F10.2</span> | <span class="fdai-readiness-badge" data-readiness="ready">Ready</span> | Scope: revision-safe cloud knowledge collection, scheduling, extraction, activation/replacement, source-aware retrieval, and explicit freshness/applicability states. The [cloud knowledge ledger](../../roadmap-implementation/interfaces/cloud-resource-knowledge-lifecycle.md) and current focused cohort support this scope. Deployment-owned source enrollment, trust ceremonies, connector drills, and current corpus freshness remain installation qualification. |
| <span id="f10-3">F10.3</span> | <span class="fdai-readiness-badge" data-readiness="partial">Partial</span> | Authoring, activation, scoping, and exceptions exist in the [rule ledger](../../roadmap-implementation/rules-and-detection/rule-governance.md). Durable rule-revision dual-read compatibility and the ordered rollout/rollback phases remain open. |
| <span id="f10-4">F10.4</span> | <span class="fdai-readiness-badge" data-readiness="partial">Partial</span> | Document-to-rule/workflow conversion and governed handover are implemented in the [distillation ledger](../../roadmap-implementation/rules-and-detection/manual-distillation.md). Deployed access/purpose/withdrawal, legal-hold deletion, provider conformance, and separate promotion evidence remain open. |

## F11. Evaluation, learning, and promotion

| Function | State | Evidence, supported scope, and remaining conditions |
|----------|-------|-----------------------------------------------------|
| <span id="f11-1">F11.1</span> | <span class="fdai-readiness-badge" data-readiness="partial">Partial</span> | Immutable cases and learning candidates exist in the [learning ledger](../../roadmap-implementation/rules-and-detection/operational-learning-ontology.md). Scoped Pattern retention, current authorized admission, and the prediction-learning integration criteria remain incomplete. |
| <span id="f11-2">F11.2</span> | <span class="fdai-readiness-badge" data-readiness="partial">Partial</span> | Replay, scenario evaluation, and measured gates exist in the [learning ledger](../../roadmap-implementation/rules-and-detection/operational-learning-ontology.md) and [workflow ledger](../../roadmap-implementation/agents/agent-workflows.md). Complete live recurrence windows, action samples, baseline and trace evidence remain required for the full evaluation claim. |
| <span id="f11-3">F11.3</span> | <span class="fdai-readiness-badge" data-readiness="partial">Partial</span> | Governed promotion/override controls exist in the [governance ledger](../../roadmap-implementation/decisioning/operator-governance-profiles.md). Recall visibility in Operator/Console and production Release maximum bindings remain open; bundle lifecycle qualification is also incomplete. |

## F12. Authority, evidence, and service health

| Function | State | Evidence, supported scope, and remaining conditions |
|----------|-------|-----------------------------------------------------|
| <span id="f12-1">F12.1</span> | <span class="fdai-readiness-badge" data-readiness="partial">Partial</span> | Role and approval profiles exist, but standing emergency authority remains deferred in the [authority ledger](../../roadmap-implementation/decisioning/escalation-and-standing-authority.md) until a provider can enforce current lease/fencing at effect commit. Approval mechanics alone do not complete conditional prior authorization. |
| <span id="f12-2">F12.2</span> | <span class="fdai-readiness-badge" data-readiness="partial">Partial</span> | Versioned policy and safety checks exist in the [governance ledger](../../roadmap-implementation/decisioning/operator-governance-profiles.md). Recall projections, Release maximum inputs, and the measured deployment kill-switch/no-execute smoke in the [health ledger](../../roadmap-implementation/operations/operating-and-verification.md) remain open. |
| <span id="f12-3">F12.3</span> | <span class="fdai-readiness-badge" data-readiness="partial">Partial</span> | Hash-chained audit, retention, redaction, and legal-hold contracts exist in the [privacy ledger](../../roadmap-implementation/architecture/data-governance.md). Deployment privacy approval, audit anchoring, deletion, legal-hold, access-review, and incident-response receipts remain open. |
| <span id="f12-4">F12.4</span> | <span class="fdai-readiness-badge" data-readiness="partial">Partial</span> | Health signals and recovery foundations exist in the [health ledger](../../roadmap-implementation/operations/operating-and-verification.md) and [DR guide](../sre/disaster-recovery-and-drills.md). Complete exporter/threshold/owner/fallback mappings, numeric canary-audit latency, and operational recovery drills remain open. |

## F13. Evidence views and reporting

| Function | State | Evidence, supported scope, and remaining conditions |
|----------|-------|-----------------------------------------------------|
| <span id="f13-1">F13.1</span> | <span class="fdai-readiness-badge" data-readiness="partial">Partial</span> | Inventory exploration and report/incident views have retained validation in the [inventory ledger](../../roadmap-implementation/architecture/continuous-operational-instance-graph.md) and [report ledger](../../roadmap-implementation/interfaces/reporting-subsystem.md). Current source-qualified coverage across all listed work, approval, and outcome surfaces remains incomplete, including recall visibility. |
| <span id="f13-2">F13.2</span> | <span class="fdai-readiness-badge" data-readiness="ready">Ready</span> | Scope: declarative report catalogs, bounded rendering, per-widget isolation, supported exports including optional PDF, audit-backed Incident dossiers, and available/partial/unavailable source provenance. The [report ledger](../../roadmap-implementation/interfaces/reporting-subsystem.md) and focused model tests support this scope. Datasource-specific freshness, timeout campaigns, and authenticated deployment matrices remain installation qualification. |
| <span id="f13-3">F13.3</span> | <span class="fdai-readiness-badge" data-readiness="partial">Partial</span> | Baseline-based measurement is defined in the [outcome guide](../sre/measuring-sre-outcomes.md); settlement and campaign accounting exist in the [FinOps ledger](../../roadmap-implementation/architecture/finops-autonomous-operations.md). Qualifying action episodes and complete baseline/treatment outcome windows remain open. |

## F14. Installation, configuration, and extensions

| Function | State | Evidence, supported scope, and remaining conditions |
|----------|-------|-----------------------------------------------------|
| <span id="f14-1">F14.1</span> | <span class="fdai-readiness-badge" data-readiness="partial">Partial</span> | The [source-deployment ledger](../../roadmap-implementation/deployment/source-deployment.md) retains a verified keyless installation with browser, inventory, health, and zero-change evidence. Unchanged keyless rerun, key-holder installation, and Trial-to-full acceptance remain open; that one receipt is not a full installation matrix. |
| <span id="f14-2">F14.2</span> | <span class="fdai-readiness-badge" data-readiness="partial">Partial</span> | Source/offline paths exist, but the [Hub ledger](../../roadmap-implementation/deployment/hub-managed-lifecycle.md) retains unfinished authenticated APIs, migrations, lifecycle agents, and installation acceptance. Local Hub demos are not a supported completed lifecycle. |
| <span id="f14-3">F14.3</span> | <span class="fdai-readiness-badge" data-readiness="partial">Partial</span> | Model/settings foundations exist in the [productization owner](../../roadmap/fork-and-sequencing/productization-and-extensibility.md); Trial and watermark mechanisms exist in the [source ledger](../../roadmap-implementation/deployment/source-deployment.md). Live key-holder/Trial-to-full watermark evidence and complete recall-mode presentation remain open. |
| <span id="f14-4">F14.4</span> | <span class="fdai-readiness-badge" data-readiness="ready">Ready</span> | Scope: publisher trust checks, compatibility validation, immutable disabled-first installation, enable/disable/revoke lifecycle, typed runtime registration, and linked-receipt completeness rules. The [bundle ledger](../../roadmap-implementation/architecture/capability-bundle-lifecycle.md) and current extension/package-assurance cohort support this scope. A protected installation's exact-artifact ceremony and restart/disclosure receipt set remain installation qualification. |

## F15. Code security

| Function | State | Evidence, supported scope, and remaining conditions |
|----------|-------|-----------------------------------------------------|
| <span id="f15-1">F15.1</span> | <span class="fdai-readiness-badge" data-readiness="ready">Ready</span> | Scope: authorized exact-revision acquisition, isolated deterministic scan lanes, SARIF intake, Console and scheduled workers, independent result reconstruction, coverage reporting, and terminal request projection. The [scan ledger](../../roadmap-implementation/operations/code-security-scanning.md) and current worker/acceptance cohort support this scope. Deployed worker heartbeat and exact publication/readback receipts remain installation qualification. |
| <span id="f15-2">F15.2</span> | <span class="fdai-readiness-badge" data-readiness="ready">Ready</span> | Scope: deterministic canonical issues, severity/confidence/priority separation, bounded summaries, and verification/adjudication. Reviewed [canonicalization](../../../services/core-control-plane/src/fdai/core/security/code_findings/canonical.py) and [verification](../../../services/core-control-plane/src/fdai/core/security/code_findings/verification.py); reran canonical, severity, issue-summary, and verification tests in cohort A. This does not certify detector recall, arbitrary weaknesses, or live scanner accuracy. |
| <span id="f15-3">F15.3</span> | <span class="fdai-readiness-badge" data-readiness="ready">Ready</span> | Scope: signed, scoped developer remediation packs, helper guards, result claims, and coverage-equivalent rescan verification. Reviewed [pack runtime](../../../services/core-control-plane/src/fdai/core/security/code_findings/pack_runtime.py) and [verification](../../../services/core-control-plane/src/fdai/core/security/code_findings/verification.py); cohort A includes the [real temporary-git helper session](../../../services/core-control-plane/tests/core/security/code_findings/test_pack_helper_session.py), signing, export, guard, and rescan tests. FDAI does not edit a customer repository or treat a returned claim as a verified fix. |

## Focused verification performed

| Cohort | Exact local selection | Result |
|--------|-----------------------|--------|
| **A** | Incident `test_incident_lifecycle.py`, `test_incident_workflow.py`, `test_storm.py`; rule catalog `test_action_type_catalog.py`, `test_workflow_catalog.py`; code findings `test_canonical.py`, `test_severity.py`, `test_issue_summary.py`, `test_pack.py`, `test_pack_helper_session.py`, `test_diff_guard.py`, `test_signing.py`, `test_result_import.py`, `test_export_gate.py`, `test_verification.py`. | **286 passed**, no skips; 15 files. |
| **B** | Scheduler `test_scheduler.py`, `test_history.py`, `test_isolation.py`, `test_console_tool.py`, `test_continuation.py`, `test_continuation_delivery.py`, `test_continuation_retention.py`. | **111 passed**, no skips; 7 files. |
| **C** | Operating-intent admission/revalidation, ontology coverage reasons, capability extensions/package assurance, cloud knowledge collection/scheduling/extraction, ownership/stewardship coverage, scheduled continuations, and code-security result acceptance/workers. | **333 passed**, no skips; 21 files. |
| **D** | Changed Python contracts: reporting provenance, Operator background-task boundary, and SLO burn CLI. | **15 passed**, no skips; 3 files. |
| **E** | Changed Console model plus Container Apps scheduled-job contracts. | **41 passed**, one inapplicable manual-trigger skip; 3 files. Console typecheck and Terraform format checks also passed. |

The completed implementation then received two passes over 12 critique lenses: authority,
fail-closed behavior, idempotency, asynchronous cleanup, API drift, metric semantics, Kafka wiring,
Terraform least privilege, Live/Sample honesty, accessibility, test confidence, and documentation
truthfulness. The first pass found a concurrent cancellation-control gap and an ambiguous Terraform
precondition message. Both were hardened and rechecked; the second pass left no Medium-or-higher
code finding. A following isolated visual pass found undersized mobile inputs; after hardening, the
test-only Console route measured zero document and main overflow at 1440x900 and 390x844, at least
44 px for every mobile form target, and no create or cancel control in Sample mode. This was not
Browser Entra or full-stack evidence. Deployment-specific evidence gaps remain Partial rather than
being relabeled as code defects or Ready evidence.

The selections used the checkout's local Python and JavaScript toolchains, test doubles, temporary
files, and local contract inspection. They did not select or validate a production installation.

## Related docs

| To learn about | Read |
|----------------|------|
| Full function descriptions and state definitions | [Functional specification](functional-specification.md) |
| Detailed source ownership and delivery state | [Roadmap index](../../roadmap/README.md) |
