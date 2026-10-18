---
title: FDAI Function Readiness Assessment
description: Evidence-backed readiness decisions and remaining conditions for the 52 FDAI product subfunctions.
---

# FDAI Function Readiness Assessment

This assessment records why each function in the [functional specification](functional-specification.md)
is Ready or Partial. It separates executable implementation, documented delivery gaps, and
installation-specific operational qualification instead of treating a feature name as proof.

> **Audit basis:** 2026-10-18, source revision
> `8819a28951fd5c21858adc0a8e7a6d5278ba4745`. All 21 F10-F15 subfunctions were compared with
> owner ledgers, relevant source, and exact issue states. Ten Ready labels are corrected to
> Partial. F01-F09 retain their prior assessments. The
> [complete inventory and execution plan](functional-readiness-backlog.md) records every reviewed
> subfunction, remaining work, dependencies, and exit criteria. No runtime tests or live
> operational validation were performed for this documentation audit.

> **Historical implementation evidence:** At revision
> `966082d265a7a230b41394b67e63ccd6fd328fa9` plus the F06/F07 implementation change, the closure
> campaigns traced every mandatory verb through source, composition, persistence, authority, and
> evidence owners. Their final cumulative slices passed **908 focused tests**, plus **8 actual
> isolated PostgreSQL checks**; one unrelated optional PostgreSQL exporter test skipped because its
> external validation variable wasn't configured. Ten critique rounds with ten controls each were
> completed for each function group, with no confirmed defect above Low in the final implemented
> slices. This is repository implementation evidence, not independent human approval or a new live
> Azure, model, billing, production-database, or deployment validation.

## How to read the decisions

**Overall:** <span class="fdai-readiness-badge" data-readiness="ready">Ready 28/52</span> <span class="fdai-readiness-badge" data-readiness="partial">Partial 24/52</span> <span class="fdai-readiness-badge" data-readiness="blocked">Blocked 0/52</span> <span class="fdai-readiness-badge" data-readiness="planned">Planned 0/52</span> <span class="fdai-readiness-badge" data-readiness="not-assessed">Not assessed 0/52</span>
Ready applies only to the support scope stated in its record. It does not certify every
deployment, provider, scale, or autonomous action. Partial means the stated function has an
implementation, but mandatory coverage, integration, or verification remains open in the cited
owner. No installation was selected for a Blocked assessment. No entire subfunction was found
to be design-only; planned components inside a partially implemented function remain explicit.

The 24 Partial decisions retain their implemented subset and recorded focused checks, but
they do not narrow away mandatory verbs or required operational evidence. Historical live receipts
remain historical; this session does not renew them or qualify a particular installation. Promote
one of these functions only after every remaining condition in its record is satisfied.

Badge meanings are listed in the specification [readiness definitions](functional-specification.md#readiness-states).
Function names link to the corresponding record here. Engineering implementation ledgers are
English-only references and are not replaced by this assessment.

## F01. Operating environment

| Function | State | Evidence, supported scope, and remaining conditions |
|----------|-------|-----------------------------------------------------|
| <span id="f01-1">F01.1</span> | <span class="fdai-readiness-badge" data-readiness="ready">Ready</span> | Scope: pinned management-scope admission, continuous revalidation, fail-closed quarantine/recovery mechanics, and exact configured source bindings. The [intent ledger](../../roadmap-implementation/architecture/operating-intent-source.md), [inventory ledger](../../roadmap-implementation/architecture/continuous-operational-instance-graph.md), and current focused cohort support this scope. A particular installation's provider reachability and governed quarantine drill remain deployment qualification, not part of this Ready claim. |
| <span id="f01-2">F01.2</span> | <span class="fdai-readiness-badge" data-readiness="partial">Partial</span> | Scope: versioned operating intent, service objectives and thresholds, maintenance windows, notification suppression, impact limits, scoped rule activation, and revisioned exceptions under the current schemas. The [intent ledger](../../roadmap-implementation/architecture/operating-intent-source.md), [rule ledger](../../roadmap-implementation/rules-and-detection/rule-governance.md), and 9 focused tests support this scope. Installation source revalidation and upgrade of retained legacy rule revisions remain deployment qualification. |
| <span id="f01-3">F01.3</span> | <span class="fdai-readiness-badge" data-readiness="ready">Ready</span> | Scope: typed primary and backup ownership, stewardship coverage checks, escalation resolution, and explicit ownership handover mechanics for configured bindings. The [ownership ledger](../../roadmap-implementation/interfaces/human-agent-assignment-and-knowledge-handover.md) and current ownership/coverage cohort support this scope. Directory-specific people, contactability drills, and installation promotion receipts remain deployment qualification. |

## F02. Resources and relationships

| Function | State | Evidence, supported scope, and remaining conditions |
|----------|-------|-----------------------------------------------------|
| <span id="f02-1">F02.1</span> | <span class="fdai-readiness-badge" data-readiness="ready">Ready</span> | Scope: complete-generation inventory collection, atomic snapshot promotion, reconciliation of additions, changes, and deletions, promotion receipts, and fail-closed consistency checks. The [inventory ledger](../../roadmap-implementation/architecture/continuous-operational-instance-graph.md) and focused inventory cohort support this scope. Provider reachability, deployment schema/grants, and a particular installation's complete collection remain deployment qualification. |
| <span id="f02-2">F02.2</span> | <span class="fdai-readiness-badge" data-readiness="ready">Ready</span> | Scope: typed resource and workload relationships, independently verified reciprocal links, cardinality checks, and bounded graph exploration with explicit completeness limits. The [inventory ledger](../../roadmap-implementation/architecture/continuous-operational-instance-graph.md) and focused relationship/competency tests support this scope. Modeled links never prove every application dependency; live call-derived coverage remains deployment qualification. |
| <span id="f02-3">F02.3</span> | <span class="fdai-readiness-badge" data-readiness="ready">Ready</span> | Scope: normalized bitemporal observations, point-in-time topology, explicit source and interval coverage reasons, and absence-versus-unobserved semantics. The [inventory ledger](../../roadmap-implementation/architecture/continuous-operational-instance-graph.md) and focused pending-state/PostgreSQL tests support this scope. Installation retention length, archive/restore drills, and provider-wide interval completeness remain deployment qualification. |

## F03. Observation, prevention, and forecasts

| Function | State | Evidence, supported scope, and remaining conditions |
|----------|-------|-----------------------------------------------------|
| <span id="f03-1">F03.1</span> | <span class="fdai-readiness-badge" data-readiness="ready">Ready</span> | Scope: supported inventory, resource-state, metric, Kubernetes, and observation-campaign adapters; typed source receipts; bounded collection; and explicit unavailable, incomplete, stale, and permission-limited states. The [SRE map](../sre/README.md#sre-capability-map), [inventory ledger](../../roadmap-implementation/architecture/continuous-operational-instance-graph.md), and focused observation cohort support this scope. Source enrollment and measured collection coverage remain installation qualification. |
| <span id="f03-2">F03.2</span> | <span class="fdai-readiness-badge" data-readiness="ready">Ready</span> | Scope: schema-validated workload SLOs, error-budget and multi-window burn evaluation, fail-closed insufficient-data handling, breach event publication, and an optional single-replica scheduled job. The [SLO guide](../sre/slos-and-error-budgets.md) and focused CLI/infrastructure tests support this scope. Workload definitions, metric bindings, schedule enablement, and measured run receipts remain installation configuration and qualification. |
| <span id="f03-3">F03.3</span> | <span class="fdai-readiness-badge" data-readiness="ready">Ready</span> | Scope: typed capacity forecasts, demand and constraint inputs, hard-constraint filtering before option scoring, bounded simulation, and capacity-aware operational plans. The [capacity guide](../sre/capacity-and-performance.md), [planning ledger](../../roadmap-implementation/decisioning/operational-planning.md), and focused planning/specialist tests support this scope. Fresh demand, quota, dependency, and observed scale-out outcomes remain installation qualification. |
| <span id="f03-4">F03.4</span> | <span class="fdai-readiness-badge" data-readiness="ready">Ready</span> | Scope: deterministic alert-quality assessment, source-gap and completeness reporting, bounded temporal evaluation, proposal safety checks, and explicit unknown outcomes. The [alert-quality ledger](../../roadmap-implementation/operations/alert-noise-governance.md) and focused Core/Operator tests support this scope. Provider-specific labels, recipient bindings, and operational acceptance remain installation qualification. |

## F04. Incidents

| Function | State | Evidence, supported scope, and remaining conditions |
|----------|-------|-----------------------------------------------------|
| <span id="f04-1">F04.1</span> | <span class="fdai-readiness-badge" data-readiness="ready">Ready</span> | Scope: the built-in correlated incident registry and lifecycle workflow, including detector-created Incidents, severity/state changes, assignment, audited writes, and replay. The default policy opens a medium-or-higher episode only after five distinct correlated detected issues arrive within five minutes with complete bounded evidence; low, informational, sparse, unrelated, or duplicate detected issues correctly produce no Incident. Reviewed [registry](../../../services/core-control-plane/src/fdai/core/incident/registry.py), [workflow](../../../services/core-control-plane/src/fdai/core/incident/workflow.py), and the analyzer-to-Incident path; reran the focused lifecycle, workflow, storm, auto-open, runtime-settings, and analyzer handoff checks. A zero Incident count is therefore not a readiness failure by itself. Installation overrides and fresh operational creation evidence remain deployment qualification. External notification qualification is separate under F09.3. |
| <span id="f04-2">F04.2</span> | <span class="fdai-readiness-badge" data-readiness="ready">Ready</span> | Scope: tiered causal hypotheses, governed document and telemetry evidence, topology/change discrimination, conflicting-evidence handling, abstention, and auditable causal chains. The [RCA ledger](../../roadmap-implementation/rules-and-detection/root-cause-analysis.md) and focused RCA cohort support this scope. Exact cause accuracy and multi-workspace source coverage remain installation and operational qualification. |
| <span id="f04-3">F04.3</span> | <span class="fdai-readiness-badge" data-readiness="ready">Ready</span> | Scope: typed response-plan construction, mitigation alternatives, expected effects, stop/recovery contracts, incident handoff, unresolved outcome retention, and postmortem/follow-up preparation. The [planning ledger](../../roadmap-implementation/decisioning/operational-planning.md), [learning guide](../sre/postmortems-and-learning.md), and focused planning tests support this scope. A particular action's approval, execution, and observed recovery remain action and deployment qualification. |

## F05. Resilience and recovery

| Function | State | Evidence, supported scope, and remaining conditions |
|----------|-------|-----------------------------------------------------|
| <span id="f05-1">F05.1</span> | <span class="fdai-readiness-badge" data-readiness="ready">Ready</span> | Scope: backup-readiness assessment, recovery-point evidence requirements, restore prerequisites, bounded recovery-plan construction, and fail-closed treatment of missing integrity evidence. The [DR guide](../sre/disaster-recovery-and-drills.md), [recovery ledger](../../roadmap-implementation/decisioning/recovery-and-chaos-enforcement.md), and focused recovery tests support this scope. Exact-workload backup, restore, and independent integrity receipts remain installation qualification; backup success alone is never recoverability proof. |
| <span id="f05-2">F05.2</span> | <span class="fdai-readiness-badge" data-readiness="partial">Partial</span> | Scope: governed PostgreSQL restore drills with plan and authority checks, Azure restore dispatch, integrity and smoke verification, measured RPO/RTO, terminal audit, cleanup, and sanitized reporting. The [DR guide](../sre/disaster-recovery-and-drills.md#recovering-fdai-itself) and 26 focused tests support this scope. Alternate-region infrastructure, traffic/event continuity, and a particular installation's failover/failback receipts remain deployment qualification. |
| <span id="f05-3">F05.3</span> | <span class="fdai-readiness-badge" data-readiness="partial">Partial</span> | Scope: typed Chaos plans, separate current authority, bounded provider fault dispatch, continuous stop evaluation, recovery, effect verification, terminal audit, and fail-closed unsupported providers. The [Chaos ledger](../../roadmap-implementation/decisioning/recovery-and-chaos-enforcement.md) and 23 focused tests support this scope. Provider credentials, promoted experiments, and live fault/recovery campaigns remain deployment qualification. |

## F06. Changes and architecture

| Function | State | Evidence, supported scope, and remaining conditions |
|----------|-------|-----------------------------------------------------|
| <span id="f06-1">F06.1</span> | <span class="fdai-readiness-badge" data-readiness="ready">Ready</span> | Scope: typed proposed-change intake, policy/risk assessment, exact target and revision validation, bounded simulation, alternative comparison, stop conditions, and rollback evidence in the finalized plan. The [change guide](../capabilities/change-safety.md), [planning ledger](../../roadmap-implementation/decisioning/operational-planning.md), and focused planning tests support this scope. Approval, execution, and independent post-change observation remain separate action qualification; a proposal never closes a change. |
| <span id="f06-2">F06.2</span> | <span class="fdai-readiness-badge" data-readiness="partial">Partial</span> | Scope: current-schema drift and control-gap detection, scoped policy evaluation, evidence-bearing exceptions, deterministic conflicts, and all nine Rule-revision phases through retained artifacts, cohort activation, retirement, rollback, and authority compare-and-set. The [rule ledger](../../roadmap-implementation/rules-and-detection/rule-governance.md) and 78 current focused checks support the implemented scope. A real installation still needs legacy-pointer migration, complete provider collection, trusted Entra verifier evidence, scaled-replica convergence, direct/offline activation receipts, and measured rollout quality. Those are mandatory operational conditions, so this function remains Partial. |
| <span id="f06-3">F06.3</span> | <span class="fdai-readiness-badge" data-readiness="partial">Partial</span> | Scope: immutable ARB evidence packages and receipts, architecture and readiness assessment, runtime-selected typed ORR ingress, receipt-gated readiness, Forseti-owned observation, and durable cross-replica idempotency and projection fences. Missing, ambiguous, stale, truncated, or incomplete sources hold without granting approval, topic ownership, mutation, or execution authority. The [ARB ledger](../../roadmap-implementation/architecture/architecture-review-board.md), [readiness ledger](../../roadmap-implementation/operations/operational-readiness.md), 194 focused checks, and four isolated PostgreSQL checks support this scope. Production posture/report/admission providers, accountable owner approvals, end-to-end shadow and promotion cohorts, signed terminals, and deployed Workflow effect receipts remain mandatory and unverified, so this function remains Partial. |

## F07. Cost governance

| Function | State | Evidence, supported scope, and remaining conditions |
|----------|-------|-----------------------------------------------------|
| <span id="f07-1">F07.1</span> | <span class="fdai-readiness-badge" data-readiness="ready">Ready</span> | Scope: bounded subscription/resource cost and utilization analytics, allocation gaps, service/resource attribution, source provenance, and Console projections that preserve incomplete or unavailable evidence. The [efficiency ledger](../../roadmap-implementation/architecture/finops-resource-efficiency.md) and focused FinOps tests support this scope. Current billing/utilization bindings and complete relationship coverage remain installation qualification. |
| <span id="f07-2">F07.2</span> | <span class="fdai-readiness-badge" data-readiness="ready">Ready</span> | Scope: bounded budget comparison, baseline and trend analysis, source-window forecasts, and durable prediction-to-actual calibration with sample count, MAPE, signed bias, source lineage, and explicit partial or unavailable states. The [efficiency ledger](../../roadmap-implementation/architecture/finops-resource-efficiency.md), [FinOps ledger](../../roadmap-implementation/architecture/finops-autonomous-operations.md), and focused Cost Governance tests support this scope. Current installation billing and utilization bindings plus a measured nonzero calibration cohort remain installation qualification; missing or zero actual denominators never become a zero-error claim. |
| <span id="f07-3">F07.3</span> | <span class="fdai-readiness-badge" data-readiness="ready">Ready</span> | Scope: five versioned service-family profiles, required-metric and incompatibility checks, single-resource and bounded coupled-target planning, activation-fenced canonical ingress, Njord-owned durable publication, accountable Freyr/Forseti/Odin processing, typed clarification reinjection, and existing Var/Thor approval and execution seams. The [efficiency ledger](../../roadmap-implementation/architecture/finops-resource-efficiency.md) and focused package, agent, delivery, and cross-vertical tests support this scope. Live installation approval, execution, rollback, and independently settled outcome receipts remain installation qualification and don't follow from the Ready state. |
| <span id="f07-4">F07.4</span> | <span class="fdai-readiness-badge" data-readiness="ready">Ready</span> | Scope: exact case and action revision settlement, one currency, comparable baseline and treatment windows, demand normalization, independent cost/capacity/service/recovery effects, and separate verified run-rate and invoice-allocated evidence classes. Invoice allocation additionally requires finalized billing and allocation-rule receipts. The [FinOps ledger](../../roadmap-implementation/architecture/finops-autonomous-operations.md), [efficiency ledger](../../roadmap-implementation/architecture/finops-resource-efficiency.md), and focused settlement tests support this scope. A live pinned settled episode and finalized billing receipt remain installation qualification, not implementation evidence. |

## F06 and F07 remaining operational work

The closure campaigns completed every reproducible repository implementation gap they found. The
items below require an exact installation, external identity, accountable human, provider source,
or measured operational episode. They remain mandatory. A Ready result for F07 means that the
generic implementation supports the stated behavior; it doesn't manufacture these installation
inputs or prove production savings.

### F06.2 deployment and policy rollout

| Remaining work | Responsible owner | Completion evidence |
|----------------|-------------------|---------------------|
| Migrate a retained legacy Rule pointer and cohort through the current nine-phase revision path | Mimir and release owner | Exact old/new releases, migration receipt, active-pointer readback, rollback and retained-history verification |
| Bind complete drift and control-gap provider collection | Huginn, Heimdall and deployment provider owner | Authenticated scope, source identity, completeness/freshness receipt and measured missing-source behavior |
| Deploy the trusted Entra governance verifier GitHub App | Security and repository owner | Installed App id, phishing-resistant identity attestation and accepted exact-head check run |
| Prove a governed change is blocked, then cleared by corrected independent review | Var, Mimir and Saga | Self-approval or sub-quorum denial, corrected approval, exact-head check and audit linkage |
| Schedule exemption expiry with a production notifier | Mimir, Saga and operations owner | Job schedule, expiry audit, one real notification receipt and duplicate suppression |
| Bind the override-discovery evidence source | Norns, Mimir and deployment composition owner | Current `governance.override_resolved` source, exact window and independent source admission |
| Verify generation convergence across serving replicas | Mimir and runtime/release owner | Two or more serving replicas agree on one generation after restart and rollback |
| Exercise direct and offline activation paths | Mimir, Var, Saga and release owner | Authenticated direct approval and signed offline package receipts with exact revision readback |
| Measure provider-complete drift quality | Heimdall and Forseti | Frozen scope with false-positive, false-negative, hold and coverage denominators |

### F06.3 ARB and operational-readiness qualification

| Remaining work | Responsible owner | Completion evidence |
|----------------|-------------------|---------------------|
| Bind a production posture provider | Heimdall, Assurance Twin and deployment owner | Current workload/scope projection with source identity, freshness and completeness |
| Bind the readiness-report publisher | Forseti, Saga and Operator owner | Authenticated Checks API or Console projection receipt with exact source revision |
| Bind decision-evidence admission for ARB | Security and evidence owner | Governed evidence store, trust roots, purpose, scope and revision admission |
| Configure real ARB owners, evidence and approval routes | Architecture, security, privacy, data, operations, reliability, release, cost and performance owners | Named owners, escalation routes, evidence digests and attributed approvals |
| Retain one governed ORR shadow receipt | Forseti, Saga and operations owner | Ownership-transfer event, independent bundle, durable report and no execution effect |
| Carry one ORR through the safety check and human approval | Forseti, Var and Saga | Broker receipt, exact risk decision and distinct attributed approver |
| Measure a frozen false-positive shadow cohort | Forseti, Muninn and assurance owner | Representative scenario manifest, decisions, outcomes, denominators and uncertainty |
| Record an authoritative promotion decision | Mimir, Var and promotion owner | Reviewed cohort, exact promotion subject, approval and current registry readback |
| Run one staging ARB Process to a signed terminal | Forseti, Var, Saga and ARB owners | Owner approvals, Process history and independently verified signed terminal |
| Verify Workflow enforcement parity | Var, Thor, Saga and deployment owner | Same allowlisted Workflow in local/deployed venues, promoted ActionType and independent effect |
| Retain the complete owned-topic ARB trace | Pantheon topic owners | Schema-validated stage records on every declared owner topic with causal correlation |
| Close ARB-4 effects and ARB-5 promotion cohorts | Heimdall, Vidar, Muninn, Norns and Mimir | ActionRun, independent outcome, recovery and long-window cohort receipts |

### F07 installation activation and measurement

| Remaining work | Responsible owner | Completion evidence |
|----------------|-------------------|---------------------|
| Bind real billing, Budget, Advisor and utilization sources | Installation and Cost Analytics provider owner | Current authenticated source manifests and complete/partial/unavailable readback |
| Verify service, workload and relationship coverage | Installation ontology and inventory owner | Coverage receipt for the exact cost allocation scope |
| Accumulate a nonzero forecast-calibration cohort | Njord and analytics evidence owner | Authoritative actuals, sample count, MAPE, signed bias and source lineage |
| Retain one pinned live DecisionCase and approval | Forseti, Var and installation operator | Exact case/action revision, target, current policy and attributed approval |
| Retain execution and rollback receipts | Thor, Vidar and executor deployment owner | Idempotent execution, postcondition, rollback or no-rollback fact and effect correlation |
| Produce independent cost, capacity, service and recovery effects | Heimdall, Saga and settlement producer | Four independently sourced statuses bound to the same action and windows |
| Qualify comparable-demand run-rate savings | Cost Governance measurement owner | Baseline/treatment demand normalization and verified run-rate receipt |
| Qualify invoice-allocated savings | Billing and allocation owner | Final invoice and exact allocation-rule receipts |
| Accumulate the W7 operating cohort | Installation owner and protected campaign | 30 distinct days, at least 100 eligible samples and the declared recurrence window |
| Complete independent target review | Six independent human reviewers | Six attributed reviews over the exact target package and evidence set |
| Perform the production package cutover | Release and deployment owner | Activated package revision, inert Core facade removal and rollback/readback receipts |
| Complete the successor W7 cohort and independent target reviews | FDAI maintainer, installation owner and six independent reviewers | [W7 cohort #2207](https://github.com/dotnetpower/fdai/issues/2207) and [target reviews #2208](https://github.com/dotnetpower/fdai/issues/2208) closed with exact-revision campaign evidence and six separate attributable decisions |
| Run the optional campaign-export PostgreSQL test | Local validation owner | Dedicated validation DSN and passing exporter persistence test; this doesn't replace live evidence |

## F08. Actions and workflows

| Function | State | Evidence, supported scope, and remaining conditions |
|----------|-------|-----------------------------------------------------|
| <span id="f08-1">F08.1</span> | <span class="fdai-readiness-badge" data-readiness="ready">Ready</span> | Scope: the shipped registered ActionType and Workflow catalogs, including parameters, references, risk/recovery declarations, and shadow defaults. Reviewed [ActionType](../../../services/core-control-plane/src/fdai/rule_catalog/schema/action_type.py) and [Workflow](../../../services/core-control-plane/src/fdai/rule_catalog/schema/workflow.py) loaders; reran [action catalog](../../../services/core-control-plane/tests/rule_catalog/test_action_type_catalog.py) and [workflow catalog](../../../services/core-control-plane/tests/rule_catalog/test_workflow_catalog.py) tests in cohort A. Catalog validity does not prove every design-inventory workflow is implemented or promoted. |
| <span id="f08-2">F08.2</span> | <span class="fdai-readiness-badge" data-readiness="ready">Ready</span> | Scope: multi-step plan composition, hard-constraint filtering, specialist arbitration, exact target/effect validation, recovery contracts, sealed plan digests, and dispatch-readiness checks. The [planning ledger](../../roadmap-implementation/decisioning/operational-planning.md) and focused planning/specialist tests support this scope. Human approval and effect verification remain required when a plan is executed. |
| <span id="f08-3">F08.3</span> | <span class="fdai-readiness-badge" data-readiness="ready">Ready</span> | Scope: built-in due/manual dispatch, supported schedule kinds, bounded isolation, history, and continuation mechanics. Reviewed [scheduler](../../../services/core-control-plane/src/fdai/core/scheduler/service.py); cohort B reran seven [scheduler test files](../../../services/core-control-plane/tests/core/scheduler/), including duplicate suppression, history, isolation, and continuation retention/delivery. Dispatch acceptance is not action success or live channel qualification. |
| <span id="f08-4">F08.4</span> | <span class="fdai-readiness-badge" data-readiness="partial">Partial</span> | Scope: exact-revision dispatch, duplicate suppression, per-target locking, progress and stop checks, approved rollback or bounded recovery, terminal audit, and independent effect closure across supported workflow/provider contracts. The [workflow ledger](../../roadmap-implementation/decisioning/process-automation.md), [recovery ledger](../../roadmap-implementation/decisioning/recovery-and-chaos-enforcement.md), and 360 focused tests support this scope. Provider fencing, promotion, and a live recovery closure remain deployment qualification. |

## F09. Operator investigation and collaboration

| Function | State | Evidence, supported scope, and remaining conditions |
|----------|-------|-----------------------------------------------------|
| <span id="f09-1">F09.1</span> | <span class="fdai-readiness-badge" data-readiness="ready">Ready</span> | Scope: model-backed typed intent, principal-scoped read investigation, ontology/RCA evidence selection, bounded citations and limitations, explicit unknown/partial outcomes, and Web/CLI/ChatOps presentation contracts. The [operator guide](../guides/use-operator-conversations.md), [RCA ledger](../../roadmap-implementation/rules-and-detection/root-cause-analysis.md), and focused semantic/read-investigation cohort support this scope. Source/channel enrollment and live cause-quality measurement remain installation qualification. |
| <span id="f09-2">F09.2</span> | <span class="fdai-readiness-badge" data-readiness="ready">Ready</span> | Scope: durable owner-scoped read investigations, leases, quotas, progress, typed create/cancel intake, restart-safe completion, Web handoff, Slack/Teams outbound enqueue, and Live-only Console controls. The [background-task ledger](../../roadmap-implementation/interfaces/background-task-sessions.md), focused tests, and isolated responsive Console check support this scope. Provider delivery and process-loss drills remain installation qualification. |
| <span id="f09-3">F09.3</span> | <span class="fdai-readiness-badge" data-readiness="ready">Ready</span> | Scope: typed notification categories, durable routing and per-channel state, verified identity pairing, acknowledgment, fallback, bounded escalation, timeout no-op, and Slack/Teams adapter contracts. The [channel ledger](../../roadmap-implementation/interfaces/channels-and-notifications.md) and focused notification/channel cohort support this scope. Provider delivery, tenant callback, and broker receipts remain installation qualification; silence never grants consent. |
| <span id="f09-4">F09.4</span> | <span class="fdai-readiness-badge" data-readiness="ready">Ready</span> | Scope: principal-bound continuation anchors, retained typed context, follow-up delivery state, expiry, and bounded retention. The [continuation ledger](../../roadmap-implementation/interfaces/scheduled-result-continuations.md) and current continuation cohort support this scope. Live channel-origin identity, real responder assignments, legal-hold purge, and proactive ownership handover promotion remain separate installation qualification. |

## F10. Knowledge and rules

| Function | State | Evidence, supported scope, and remaining conditions |
|----------|-------|-----------------------------------------------------|
| <span id="f10-1">F10.1</span> | <span class="fdai-readiness-badge" data-readiness="partial">Partial</span> | Implemented locally: authenticated intake, immutable versions, bounded extraction/OCR, indexing, retention/deletion, restart-safe handoff, and the K02 purpose-bound protected original download with canonical audited receipts, bounded authority, current access/revision and stream rechecks. The [document ledger](../../roadmap-implementation/interfaces/document-ingestion.md) records #2214's 132 focused behavior and 29 ownership checks separately from the historical 929-test cohort. Remaining: exact five-service lifecycle/failure receipts and approved SharePoint/protection, revocation, deletion, cursor and backpressure readback. [K01-K02](functional-readiness-backlog.md#f10-knowledge-and-rule-work) remain mandatory operational gates; local export implementation does not close them. |
| <span id="f10-2">F10.2</span> | <span class="fdai-readiness-badge" data-readiness="partial">Partial</span> | Implemented locally: revision-safe collection/scheduling, manual v2/v3 admission, dated retrieval/containment, and #2217's explicit prior-policy application API with independent Var/Saga verification and transaction-fenced persisted readback. The [cloud knowledge ledger](../../roadmap-implementation/interfaces/cloud-resource-knowledge-lifecycle.md) and [structured retrieval ledger](../../roadmap-implementation/interfaces/cloud-resource-knowledge-structured-rag.md) record the final 672 focused passes, including legacy guard compatibility, and 24 actual PostgreSQL passes separately from operational evidence. #2232 adds opt-in attribute-scope normalizer `2.1.1`, reader `3.1.1`, and 329 focused passes without rewriting old checkpoints or source dates. Remaining: actual independently approved policy/read grants and promotion, real-source/answer quality, trust/enrollment, and connected/egress-denied receipts. See [K03-K05](functional-readiness-backlog.md#f10-knowledge-and-rule-work); keep Partial rather than treating source implementation as operational qualification. |
| <span id="f10-3">F10.3</span> | <span class="fdai-readiness-badge" data-readiness="partial">Partial</span> | Scope: current-schema rule authoring, provenance and quality validation, immutable versions, scoped activation, revisioned exceptions, retirement proposals, conflict resolution, and rollback-safe catalog state. The [rule ledger](../../roadmap-implementation/rules-and-detection/rule-governance.md) and 72 focused tests support this scope. Legacy-revision dual-read migration and a deployment's phased rollout remain installation/upgrade qualification. |
| <span id="f10-4">F10.4</span> | <span class="fdai-readiness-badge" data-readiness="partial">Partial</span> | Implemented locally: source-before-content provenance, sensitivity/freshness and ontology checks, deterministic independent verification, inert proposals, and private-package retirement. The [distillation ledger](../../roadmap-implementation/rules-and-detection/manual-distillation.md) retains mandatory deployed ACL/purpose, withdrawal, legal-hold/deletion, provider/cohort and actual EN/KO assistive-output evidence. See [K06-K07](functional-readiness-backlog.md#f10-knowledge-and-rule-work). Compilation grants no activation authority, and local tests do not close the operational conformance gate. |

## F11. Evaluation, learning, and promotion

| Function | State | Evidence, supported scope, and remaining conditions |
|----------|-------|-----------------------------------------------------|
| <span id="f11-1">F11.1</span> | <span class="fdai-readiness-badge" data-readiness="partial">Partial</span> | Implemented: attributed feedback, immutable incident/action cases, prediction closure, inert candidates, and local retention/hold controls. The [learning ledger](../../roadmap-implementation/rules-and-detection/operational-learning-ontology.md) and [prediction ledger](../../roadmap-implementation/rules-and-detection/prediction-learning-and-case-history.md) retain source-history, Settings/collector, context-lifecycle and retained-Pattern integration work as well as operational gates. See [L01-L03](functional-readiness-backlog.md#f11-f13-learning-authority-health-and-outcomes); the isolated LOCAL lease implementation does not qualify external sources. |
| <span id="f11-2">F11.2</span> | <span class="fdai-readiness-badge" data-readiness="partial">Partial</span> | Implemented: judge-only replay, scenario/assurance-twin evaluation, baseline comparison, censored outcomes, and O7 evidence bound to the exact threshold policy. The [learning ledger](../../roadmap-implementation/rules-and-detection/operational-learning-ontology.md) and [workflow status](../../roadmap/agents/agent-workflows.md#implementation-status) support local checks. Remaining: coherent external issuer, preregistered SLO/safety-budget comparison, complete recurrence windows, action-specific days/sample sizes, confidence and zero-escape evidence. See [L03-L04](functional-readiness-backlog.md#f11-f13-learning-authority-health-and-outcomes). |
| <span id="f11-3">F11.3</span> | <span class="fdai-readiness-badge" data-readiness="partial">Partial</span> | Implemented: promotion/override attribution, automatic demotion, durable recall/lift, recall precedence, forced `shadow`, and Operator/Console recall visibility. The [governance ledger](../../roadmap-implementation/decisioning/operator-governance-profiles.md) and recorded focused tests support this subset. Remaining: production Release maximum integration and governed activation/recall receipts, [A01-A02](functional-readiness-backlog.md#f11-f13-learning-authority-health-and-outcomes). The current fail-closed shadow-only maximum is an implementation boundary, not a production binding. |

The [#2224 action-history source correction](../../roadmap-implementation/rules-and-detection/prediction-learning-and-case-history.md)
also keeps F11.1/F11.2 Partial: audit timestamps, latest-state joins, shadow success and empty
results cannot prove complete event-time intervention history. The source now emits explicit
incomplete coverage without normalized transitions; its existing consumers remain Incomplete,
not zero-intervention or Ready. Actual source-owned anchors and completeness proofs remain open.

## F12. Authority, evidence, and service health

| Function | State | Evidence, supported scope, and remaining conditions |
|----------|-------|-----------------------------------------------------|
| <span id="f12-1">F12.1</span> | <span class="fdai-readiness-badge" data-readiness="partial">Partial</span> | Scope: role separation, exact-action approvals, expiry and revocation, conditional prior authorization, current lease and fencing contracts, quorum profiles, and fail-closed dispatch when authority or provider enforcement is unavailable. The [authority ledger](../../roadmap-implementation/decisioning/escalation-and-standing-authority.md) and 702 focused tests support this scope. Binding a provider that enforces fencing at effect commit and exercising standing authority remain deployment qualification. |
| <span id="f12-2">F12.2</span> | <span class="fdai-readiness-badge" data-readiness="partial">Partial</span> | Scope: versioned policy and risk decisions, emergency-stop and recall precedence, all seven execution safeguards, deny/no-op terminal audit, fail-closed no-execute behavior, and an authenticated operational-state read surface. The signed Operator-to-Var kill-switch path, [security ledger](../../roadmap-implementation/architecture/security-and-identity.md), [authoritative health status](../../roadmap/operations/operating-and-verification.md#implementation-status), and focused safety tests support local implementation. Release maximum bindings and a measured deployment engage/no-execute/disengage drill remain installation qualification. |
| <span id="f12-3">F12.3</span> | <span class="fdai-readiness-badge" data-readiness="partial">Partial</span> | Scope: attributable hash-chained audit, deterministic replay, purpose/scope access checks, pre-model minimization, redacted export, bounded retention and deletion, legal holds, tombstones, and retry-safe audit receipts. The [privacy ledger](../../roadmap-implementation/architecture/data-governance.md) and focused audit/retention/privacy cohort support this scope. Privacy approval, external anchoring or WORM storage, and live access-review/incident receipts remain deployment qualification. |
| <span id="f12-4">F12.4</span> | <span class="fdai-readiness-badge" data-readiness="partial">Partial</span> | Implemented: the 15-signal policy/exporter registry, eight-field operational-state contract, service/model and evidence health queries, and exact 30-second consumed-canary check. #2218 / PR #2220 binds actual listener, protected readiness and persisted emergency-stop signals, plus installed version, consumed-policy digest and emergency-stop fields, with 92 focused passes. #2228 adds process-scoped runtime-entry-to-first-protected-ready duration, with 80 focused passes in an overlapping test slice. Its observation timestamp is frozen, not renewed by collection. The [authoritative health status](../../roadmap/operations/operating-and-verification.md#implementation-status) keeps the other eleven signals and five fields explicitly unavailable. Their real sources, measured primary/fallback delivery, live canary, stabilization and recovery-drill evidence remain mandatory. |

## F13. Evidence views and reporting

| Function | State | Evidence, supported scope, and remaining conditions |
|----------|-------|-----------------------------------------------------|
| <span id="f13-1">F13.1</span> | <span class="fdai-readiness-badge" data-readiness="ready">Ready</span> | Scope: authorized read views for resources, relationships, incidents, plans/processes, approvals, audit/history, source-qualified outcomes, and promotion/recall state, with unavailable/partial evidence kept explicit. The [inventory ledger](../../roadmap-implementation/architecture/continuous-operational-instance-graph.md), [report ledger](../../roadmap-implementation/interfaces/reporting-subsystem.md), retained view tests, and current recall projection tests support this scope. Deployment source freshness and authenticated provider coverage remain installation qualification. |
| <span id="f13-2">F13.2</span> | <span class="fdai-readiness-badge" data-readiness="partial">Partial</span> | Implemented: declarative catalogs, bounded rendering, widget isolation, exports/PDF, and source provenance. The [report ledger](../../roadmap-implementation/interfaces/reporting-subsystem.md) retains historical authenticated built-in Incident RCA/PDF evidence, but broader datasource and authenticated error/isolation receipts remain open. Complete [V01](functional-readiness-backlog.md#f11-f13-learning-authority-health-and-outcomes) before extending that validated subset to the full report function. |
| <span id="f13-3">F13.3</span> | <span class="fdai-readiness-badge" data-readiness="partial">Partial</span> | Scope: baseline/treatment cohort measurement for reliability, recovery, automation, and cost; provenance/completeness gates; independent settlement; censored/unscorable outcomes; and rejection of activity counts as improvement. The [outcome guide](../sre/measuring-sre-outcomes.md), [FinOps ledger](../../roadmap-implementation/architecture/finops-autonomous-operations.md), and focused measurement cohort support this scope. Qualifying live episodes and complete operational windows remain deployment qualification. |

## F14. Installation, configuration, and extensions

| Function | State | Evidence, supported scope, and remaining conditions |
|----------|-------|-----------------------------------------------------|
| <span id="f14-1">F14.1</span> | <span class="fdai-readiness-badge" data-readiness="partial">Partial</span> | Implemented: source deployment, prerequisites, target validation, image/Terraform orchestration, Trial, health, update/rollback and teardown. The [source ledger](../../roadmap-implementation/deployment/source-deployment.md) and historical 207-test cohort support this subset. WP6 has one new-Trial receipt but still needs unchanged Trial rerun, new full entitlement, and Trial-to-full rerun with watermark removal. See [I01](functional-readiness-backlog.md#f14-f15-distribution-extensions-and-scanning). |
| <span id="f14-2">F14.2</span> | <span class="fdai-readiness-badge" data-readiness="partial">Partial</span> | Implemented: source and signature-verified offline distribution, tamper/deadline/cancellation guards, and isolated shipped-wheel installation. The [source ledger](../../roadmap-implementation/deployment/source-deployment.md) still requires WP8 source-path cleanup after WP6; current help/parser expose `--online`. Reconcile distribution recovery/acceptance in [I02-I03](functional-readiness-backlog.md#f14-f15-distribution-extensions-and-scanning). The [Hub ledger](../../roadmap-implementation/deployment/hub-managed-lifecycle.md) contains partial software, not a complete available lifecycle; Hub/public publication are not source/offline prerequisites. |
| <span id="f14-3">F14.3</span> | <span class="fdai-readiness-badge" data-readiness="partial">Partial</span> | Implemented: availability, enablement, effective mode, profile/add-ons, Trial watermark, model health, override and recall display without action authority. The [governance ledger](../../roadmap-implementation/decisioning/operator-governance-profiles.md), [source ledger](../../roadmap-implementation/deployment/source-deployment.md), and recorded recall tests support local behavior. Remaining: production Release ceiling input and live entitlement-transition readback, [A01 and I01](functional-readiness-backlog.md). Optional authoring UI and physical policy-table migration remain separate conditional scope. |
| <span id="f14-4">F14.4</span> | <span class="fdai-readiness-badge" data-readiness="partial">Partial</span> | Implemented: publisher trust, compatibility, immutable disabled-first bundles, enable/disable/revoke, and typed registration. The [bundle ledger](../../roadmap-implementation/architecture/capability-bundle-lifecycle.md) retains a mandatory linked exact-artifact receipt set for lifecycle, restart/disclosure, typed routing and audit. Complete [X01](functional-readiness-backlog.md#f14-f15-distribution-extensions-and-scanning); #355 closing as not planned did not validate that gate. |

## F15. Code security

| Function | State | Evidence, supported scope, and remaining conditions |
|----------|-------|-----------------------------------------------------|
| <span id="f15-1">F15.1</span> | <span class="fdai-readiness-badge" data-readiness="partial">Partial</span> | Implemented: exact-revision acquisition, isolated lanes, SARIF intake, Console/scheduled workers, independent local acceptance, coverage and terminal projections. The [scan ledger](../../roadmap-implementation/operations/code-security-scanning.md) retains historical installed isolation/readiness, but #2128 remains paused with no terminal installed scan or completed same-correlation business chain. Complete [S01-S02](functional-readiness-backlog.md#f14-f15-distribution-extensions-and-scanning). Worker readiness, provider acceptance, and local scan receipts are not the missing deployed terminal. |
| <span id="f15-2">F15.2</span> | <span class="fdai-readiness-badge" data-readiness="ready">Ready</span> | Scope: deterministic canonical issues, severity/confidence/priority separation, bounded summaries, and verification/adjudication. Reviewed [canonicalization](../../../services/core-control-plane/src/fdai/core/security/code_findings/canonical.py) and [verification](../../../services/core-control-plane/src/fdai/core/security/code_findings/verification.py); reran canonical, severity, issue-summary, and verification tests in cohort A. This does not certify detector recall, arbitrary weaknesses, or live scanner accuracy. |
| <span id="f15-3">F15.3</span> | <span class="fdai-readiness-badge" data-readiness="ready">Ready</span> | Scope: signed, scoped developer remediation packs, helper guards, result claims, and coverage-equivalent rescan verification. Reviewed [pack runtime](../../../services/core-control-plane/src/fdai/core/security/code_findings/pack_runtime.py) and [verification](../../../services/core-control-plane/src/fdai/core/security/code_findings/verification.py); cohort A includes the [real temporary-git helper session](../../../services/core-control-plane/tests/core/security/code_findings/test_pack_helper_session.py), signing, export, guard, and rescan tests. FDAI does not edit a customer repository or treat a returned claim as a verified fix. |

## Historical focused verification

The following results belong to the earlier implementation campaigns. This documentation audit
reuses their stated boundaries; it did not rerun them. The
[F10-F15 plan](functional-readiness-backlog.md) separates source work from still-mandatory
operational evidence, and does not turn these historical counts into a fresh validation receipt.

| Cohort | Exact local selection | Result |
|--------|-----------------------|--------|
| **A** | Incident `test_incident_lifecycle.py`, `test_incident_workflow.py`, `test_storm.py`; rule catalog `test_action_type_catalog.py`, `test_workflow_catalog.py`; code-security detected issues `test_canonical.py`, `test_severity.py`, `test_issue_summary.py`, `test_pack.py`, `test_pack_helper_session.py`, `test_diff_guard.py`, `test_signing.py`, `test_result_import.py`, `test_export_gate.py`, `test_verification.py`. | **286 passed**, no skips; 15 files. |
| **B** | Scheduler `test_scheduler.py`, `test_history.py`, `test_isolation.py`, `test_console_tool.py`, `test_continuation.py`, `test_continuation_delivery.py`, `test_continuation_retention.py`. | **111 passed**, no skips; 7 files. |
| **C** | Operating-intent admission/revalidation, ontology coverage reasons, capability extensions/package assurance, cloud knowledge collection/scheduling/extraction, ownership/stewardship coverage, scheduled continuations, and code-security result acceptance/workers. | **333 passed**, no skips; 21 files. |
| **D** | Changed Python contracts: reporting provenance, Operator background-task boundary, and SLO burn CLI. | **15 passed**, no skips; 3 files. |
| **E** | Changed Console model plus Container Apps scheduled-job contracts. | **41 passed**, one inapplicable manual-trigger skip; 3 files. Console typecheck and Terraform format checks also passed. |
| **F** | Inventory/reconciliation, relationship verification, supported observation adapters, alert quality, RCA, and recovery-readiness mechanics. | **1,196 passed**, no skips. |
| **G** | Operational planning, capacity/FinOps specialists, read investigation and semantic turns, notifications, channel identity/pairing, and Slack/Teams adapters. | **1,024 passed**, 8 inapplicable integration skips. |
| **H** | Document contracts, ingestion API, processing worker, Core document ownership, and governed distillation. | **929 passed**, 1 unavailable-database skip. |
| **I** | Source deployment input, image, Terraform, Trial, update, teardown, and control-package mechanics under the deployment CLI's own pytest configuration. | **207 passed**, no skips. |
| **J** | Signed offline package productization, tamper rejection, release guards, deadlines, mirror input, build environment, and nested cancellation. | **70 passed**, no skips. |
| **K** | New capability-recall Operator join and Console contract/rendering. | **13 passed**, no skips. |
| **L** | New versioned single-resource optimization planner, evidence bounds, safety guards, and authority-neutral candidate contract. | **15 passed**, no skips; Ruff and strict mypy also passed. |
| **M** | Operating criteria, rule/drift governance, ARB evidence, readiness, and rule lifecycle. | **389 passed**, no skips. |
| **N** | Disaster-recovery and Chaos drills, workflow execution/recovery, exact approval and conditional prior-authority contracts. | **1,114 passed**, no skips; 61 unsupported-provider assertions confirmed fail-closed behavior. |
| **O** | Cost budgets, forecasts, optimization, settlement, and baseline-based outcome measurement. | **652 passed**, one unavailable optional-database skip. |
| **P** | Operational feedback, replay and assurance twins, audit, privacy, retention, legal hold, health, readiness, and recovery signals. | **810 passed**, one unavailable optional-database skip. |

The first implementation campaign received two passes over 12 critique lenses: authority,
fail-closed behavior, idempotency, asynchronous cleanup, API drift, metric semantics, Kafka wiring,
Terraform least privilege, Live/Sample honesty, accessibility, test confidence, and documentation
truthfulness. The first pass found a concurrent cancellation-control gap and an ambiguous Terraform
precondition message. Both were hardened and rechecked; the second pass left no Medium-or-higher
code defect. A following isolated visual pass found undersized mobile inputs; after hardening, the
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
| All F10-F15 remaining work, owners, dependencies, and exit criteria | [Readiness audit and completion plan](functional-readiness-backlog.md) |
| Detailed source ownership and delivery state | [Roadmap index](../../roadmap/README.md) |
