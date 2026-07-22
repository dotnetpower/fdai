---
title: Code Map
---
# Code Map

A one-page index of the FDAI codebase so anyone (agent or human) can jump
from a subsystem name to its source, its tests, and its design doc in one
hop. This is the **scannable partner** to [project-structure.md](project-structure.md),
which explains the module boundaries and the DI seams in detail.

Use this doc when you need to answer "where does X live?" without opening
`list_dir` five times. The tables below cover the core control-plane
subsystems, the 15 pantheon agents, and the delivery / shared plumbing
packages.

## Design at a glance

- **`src/fdai/core/`** is the headless control plane. No UI, no direct cloud
  SDK imports. The control-plane subsystems and the top-level
  `ontology_explorer.py` module are grouped by control-loop role below.
- **`src/fdai/agents/`** is the 15-agent pantheon (flat, one file per agent)
  plus `_framework/` (bus, runtime, registry, pantheon spec).
- **`src/fdai/delivery/`** are outbound adapters (Azure, chatops, PR gates,
  notifications, persistence, read API).
- **`src/fdai/shared/`** is the CSP-neutral plumbing: contracts, ontology,
  provider Protocols, streaming, telemetry, resilience.
- **`src/fdai/composition/`** is the composition root (fork DI attaches
  here).
- **`src/fdai/rule_catalog/`** loads the catalog under `rule-catalog/`.

## Control-loop subsystems

The 12 subsystems that make up the hot path from event to audit. These are
the safety-core modules held to the >= 90% coverage floor.

| Subsystem | Responsibility | Source | Tests | Design doc |
|-----------|----------------|--------|-------|------------|
| event_ingest | Normalize + dedupe + correlate events into incidents | [src/fdai/core/event_ingest/](../../../src/fdai/core/event_ingest/) | [tests/core/event_ingest/](../../../tests/core/event_ingest/) | [architecture.instructions.md § Control Loop](../../../.github/instructions/architecture.instructions.md#control-loop) |
| trust_router | Compute confidence, route to T0/T1/T2 | [src/fdai/core/trust_router/](../../../src/fdai/core/trust_router/) | [tests/core/trust_router/](../../../tests/core/trust_router/) | [architecture.instructions.md § Trust Routing](../../../.github/instructions/architecture.instructions.md#trust-routing-3-tier) |
| tiers/t0_deterministic | Policy + checklist + what-if + drift | [src/fdai/core/tiers/t0_deterministic/](../../../src/fdai/core/tiers/t0_deterministic/) | [tests/core/tiers/](../../../tests/core/tiers/) | project-structure.md |
| tiers/t1_lightweight | Similarity reuse + small-model classify | [src/fdai/core/tiers/t1_lightweight/](../../../src/fdai/core/tiers/t1_lightweight/) | [tests/core/tiers/](../../../tests/core/tiers/) | project-structure.md |
| tiers/t2_reasoning | Frontier-model reasoning (novel cases only) | [src/fdai/core/tiers/t2_reasoning/](../../../src/fdai/core/tiers/t2_reasoning/) | [tests/core/tiers/](../../../tests/core/tiers/) | [llm-strategy.md](llm-strategy.md) |
| quality_gate | Mixed-model + verifier + grounding guard for T2 | [src/fdai/core/quality_gate/](../../../src/fdai/core/quality_gate/) | [tests/core/quality_gate/](../../../tests/core/quality_gate/) | [architecture.instructions.md § LLM Quality Gate](../../../.github/instructions/architecture.instructions.md#llm-quality-gate-required-for-t2) |
| risk_gate | Unified auto vs HIL vs deny authority | [src/fdai/core/risk_gate/](../../../src/fdai/core/risk_gate/) | [tests/core/risk_gate/](../../../tests/core/risk_gate/) | [decisioning/](../decisioning/) |
| hil_resume | Park + push + resume on human decision | [src/fdai/core/hil_resume/](../../../src/fdai/core/hil_resume/) | [tests/core/hil_resume/](../../../tests/core/hil_resume/) | project-structure.md |
| executor | Per-resource lock, idempotent apply | [src/fdai/core/executor/](../../../src/fdai/core/executor/) | [tests/core/](../../../tests/core/) (executor tests) | project-structure.md |
| execution_backend | Profile intersection, durable reconciliation, and shadow health probes; no eligibility authority ([design](../interfaces/execution-backends.md)) | [src/fdai/core/execution_backend/](../../../src/fdai/core/execution_backend/) | [tests/core/execution_backend/](../../../tests/core/execution_backend/) | [execution-backends.md](../interfaces/execution-backends.md) |
| audit | Append-only hash-chained log, nullable-stage correlation traces, and KPI emission | [src/fdai/core/audit/](../../../src/fdai/core/audit/) | [tests/core/audit/](../../../tests/core/audit/) | [security-and-identity.md](security-and-identity.md) |
| control_loop | Pipeline orchestrator (Stage protocol) | [src/fdai/core/control_loop/](../../../src/fdai/core/control_loop/) | [tests/core/](../../../tests/core/) | project-structure.md |
| pipeline | Domain-group facade for the above | [src/fdai/core/pipeline/](../../../src/fdai/core/pipeline/) | (same as members) | project-structure.md |

## Detection, RCA, and incident lifecycle

| Subsystem | Responsibility | Source | Tests |
|-----------|----------------|--------|-------|
| detection | Anomaly, forecast, and 50 catalog-driven operational insight producers (re-enter event-ingest) | [src/fdai/core/detection/](../../../src/fdai/core/detection/) | [tests/core/detection/](../../../tests/core/detection/) |
| rca | Root-cause analysis (T0 + T2 behind seam) | [src/fdai/core/rca/](../../../src/fdai/core/rca/) | [tests/core/rca/](../../../tests/core/rca/) |
| incident | Incident lifecycle registry + state machine | [src/fdai/core/incident/](../../../src/fdai/core/incident/) | [tests/core/incident/](../../../tests/core/incident/) |
| slo | Workload SLO / burn-rate evaluator | [src/fdai/core/slo/](../../../src/fdai/core/slo/) | [tests/core/slo/](../../../tests/core/slo/) |
| irp | Incident response plan orchestrator | [src/fdai/core/irp/](../../../src/fdai/core/irp/) | [tests/core/irp/](../../../tests/core/irp/) |
| investigation | Bounded evidence-gathering runner | [src/fdai/core/investigation/](../../../src/fdai/core/investigation/) | [tests/core/investigation/](../../../tests/core/investigation/) |
| runbook | Linear runbook + on-failure branches | [src/fdai/core/runbook/](../../../src/fdai/core/runbook/) | [tests/core/](../../../tests/core/) |
| postmortem | LLM-optional PIR draft | [src/fdai/core/postmortem/](../../../src/fdai/core/postmortem/) | [tests/core/postmortem/](../../../tests/core/postmortem/) |
| chaos | Resilience / chaos probes | [src/fdai/core/chaos/](../../../src/fdai/core/chaos/) | [tests/core/chaos/](../../../tests/core/chaos/) |
| capacity | Capacity + forecast findings | [src/fdai/core/capacity/](../../../src/fdai/core/capacity/) | [tests/core/capacity/](../../../tests/core/capacity/) |
| oncall | On-call rotation reader (read-only) | [src/fdai/core/oncall/](../../../src/fdai/core/oncall/) | [tests/core/](../../../tests/core/) |

## Knowledge, memory, and prompts

| Subsystem | Responsibility | Source | Tests |
|-----------|----------------|--------|-------|
| knowledge | Long-term knowledge store seam | [src/fdai/core/knowledge/](../../../src/fdai/core/knowledge/) | [tests/core/knowledge/](../../../tests/core/knowledge/) |
| operator_memory | HIL-approved operator note store | [src/fdai/core/operator_memory/](../../../src/fdai/core/operator_memory/) | [tests/core/operator_memory/](../../../tests/core/operator_memory/) |
| learning | Consent-gated off-path post-turn eligibility, mixed-family consensus, deduplication, and inert proposal routing ([design](../decisioning/post-turn-improvement-review.md)) | [src/fdai/core/learning/](../../../src/fdai/core/learning/) | [tests/core/learning/](../../../tests/core/learning/) |
| trajectory | Authorization-first immutable source join, versioned observable envelope, deterministic JSONL export, offline validation/replay, retention/legal hold, and reviewed-only Norns aggregate intake ([design](../interfaces/governed-trajectory-datasets.md)) | [src/fdai/core/trajectory/](../../../src/fdai/core/trajectory/) and [src/fdai/shared/providers/trajectory.py](../../../src/fdai/shared/providers/trajectory.py) | [tests/core/trajectory/](../../../tests/core/trajectory/), [tests/delivery/trajectory/](../../../tests/delivery/trajectory/), and focused API/persistence/agent tests |
| task_worker | Isolated depth-one read-only investigations with attenuated capabilities, durable branch state, and untrusted parent synthesis ([design](../agents/bounded-task-workers.md)) | [src/fdai/core/task_worker/](../../../src/fdai/core/task_worker/) | [tests/core/task_worker/](../../../tests/core/task_worker/) |
| background_task | Durable detached read-only sessions with lease/CAS ownership, server-clock quotas, coalesced progress, atomic completion outbox, bounded handoff retry, process-loss reconciliation, and gated retention purge ([design](../interfaces/background-task-sessions.md)) | [src/fdai/core/background_task/](../../../src/fdai/core/background_task/) | [tests/core/background_task/](../../../tests/core/background_task/) |
| read_investigation | Exact-resource-first Azure VM and network reads, bounded parallel evidence, RG-scoped subscription health and representative metric sweeps, durable latency profiles, and direct/streamed/detached policy ([design](../interfaces/azure-read-investigations.md)) | [src/fdai/core/read_investigation/](../../../src/fdai/core/read_investigation/), [src/fdai/shared/providers/read_investigation.py](../../../src/fdai/shared/providers/read_investigation.py), and [src/fdai/delivery/azure/subscription_health.py](../../../src/fdai/delivery/azure/subscription_health.py) | [tests/core/read_investigation/](../../../tests/core/read_investigation/), [tests/delivery/azure/read_investigation/](../../../tests/delivery/azure/read_investigation/), and focused Azure/read API tests |
| briefing | Deterministic opening and scheduled briefings over the report feed | [src/fdai/core/briefing/](../../../src/fdai/core/briefing/) | [tests/core/briefing/](../../../tests/core/briefing/) |
| busy_input | Durable queue, interrupt, and safe-boundary steer arbitration shared by web, Slack, and Teams conversations ([design](../interfaces/busy-input-modes.md)) | [src/fdai/core/conversation/](../../../src/fdai/core/conversation/) | [tests/conversation/](../../../tests/conversation/) |
| durable_delivery | Verified principal bindings, persisted outbound responses, bounded recovery, and adapter breakers ([design](../interfaces/durable-conversation-delivery.md)) | [src/fdai/core/conversation/](../../../src/fdai/core/conversation/) | [tests/conversation/](../../../tests/conversation/) and [tests/persistence/](../../../tests/persistence/) |
| user_context_projection | Metadata-only user context and workflow binding projection into the runtime ontology | [src/fdai/core/user_context_projection.py](../../../src/fdai/core/user_context_projection.py) | [tests/core/test_user_context_projection.py](../../../tests/core/test_user_context_projection.py) |
| working_context | Per-turn prompt assembly, invariant validation, capability-gated policy lifecycle, bounded shadow comparison, and approved-fixture replay ([design](../decisioning/context-selection-policy.md)) | [src/fdai/core/working_context/](../../../src/fdai/core/working_context/) | [tests/core/working_context/](../../../tests/core/working_context/) |
| prompts | Catalog-as-code prompt composer | [src/fdai/core/prompts/](../../../src/fdai/core/prompts/) | [tests/core/](../../../tests/core/) |
| skills | Progressive disclosure, governed bundles, and durable approved-source quarantine ([bundle design](../decisioning/governed-skill-bundles.md), [source design](../interfaces/skill-source-management.md)) | [src/fdai/core/skills/](../../../src/fdai/core/skills/) and [src/fdai/core/supply_chain/](../../../src/fdai/core/supply_chain/) | [tests/core/skills/](../../../tests/core/skills/), [tests/core/supply_chain/](../../../tests/core/supply_chain/), and [tests/persistence/](../../../tests/persistence/) |
| programmatic_pipeline | Reviewed bounded read-only tool loops with run capabilities, durable receipts, isolated runners, and compact results ([design](../interfaces/programmatic-tool-pipelines.md)) | [src/fdai/core/programmatic_pipeline/](../../../src/fdai/core/programmatic_pipeline/) | [tests/core/programmatic_pipeline/](../../../tests/core/programmatic_pipeline/) and [tests/delivery/programmatic_pipeline/](../../../tests/delivery/programmatic_pipeline/) |
| browser_evidence | Origin and DNS policy, redaction, immutable artifacts, evidence-only surfaces, and shadow comparison ([design](../interfaces/browser-evidence.md)) | [src/fdai/core/browser_evidence/](../../../src/fdai/core/browser_evidence/) | [tests/core/browser_evidence/](../../../tests/core/browser_evidence/) and [tests/delivery/browser/](../../../tests/delivery/browser/) |
| tools | T2 tool registry + ToolExecutor + typed command catalog | [src/fdai/core/tools/](../../../src/fdai/core/tools/) | [tests/core/tools/](../../../tests/core/tools/) |
| web_search | Last-resort web-search seam | [src/fdai/core/web_search/](../../../src/fdai/core/web_search/) | [tests/core/web_search/](../../../tests/core/web_search/) |
| capability_catalog | What each agent knows how to do | [src/fdai/core/capability_catalog/](../../../src/fdai/core/capability_catalog/) | [tests/core/capability_catalog/](../../../tests/core/capability_catalog/) |
| ontology_explorer | Deterministic Mermaid renderer for the loaded ObjectType / LinkType catalog (single module, not a package) | [src/fdai/core/ontology_explorer.py](../../../src/fdai/core/ontology_explorer.py) | [tests/core/](../../../tests/core/) |

## Operator surfaces and notifications

| Subsystem | Responsibility | Source | Tests |
|-----------|----------------|--------|-------|
| conversation | NL turn -> one read-only tool call | [src/fdai/core/conversation/](../../../src/fdai/core/conversation/) | [tests/core/conversation/](../../../tests/core/conversation/) |
| operator | Operator-console coordinator | [src/fdai/core/operator/](../../../src/fdai/core/operator/) | (integration in delivery/read_api) |
| console_request | Operator re-request policy for the write-direction console path (Scenario B deny-override) | [src/fdai/core/console_request/](../../../src/fdai/core/console_request/) | [tests/core/console_request/](../../../tests/core/console_request/) |
| notifications | Channel-routing layer over the matrix | [src/fdai/core/notifications/](../../../src/fdai/core/notifications/) | [tests/notifications/](../../../tests/notifications/) |
| report_feed | Rendered report subscriptions | [src/fdai/core/report_feed/](../../../src/fdai/core/report_feed/) | [tests/core/report_feed/](../../../tests/core/report_feed/) |
| reporting | Report composers + formatters | [src/fdai/core/reporting/](../../../src/fdai/core/reporting/) | [tests/core/reporting/](../../../tests/core/reporting/) |
| views | Workflow-matched ViewSpec -> bounded RenderedView plus deterministic inventory architecture projection | [src/fdai/core/views/](../../../src/fdai/core/views/) | [tests/core/views/](../../../tests/core/views/) and read-API architecture-view tests |
| rbac | Human RBAC for the read API | [src/fdai/core/rbac/](../../../src/fdai/core/rbac/) | [tests/core/](../../../tests/core/) |
| stewardship | Human <-> agent handover map, deterministic diff/notification, scheduled identity health, idempotent draft PR, and signed merge audit | [src/fdai/core/stewardship/](../../../src/fdai/core/stewardship/) and [src/fdai/delivery/stewardship/](../../../src/fdai/delivery/stewardship/) | [tests/core/stewardship/](../../../tests/core/stewardship/) and [tests/delivery/stewardship/](../../../tests/delivery/stewardship/) |

## Rule catalog, deploy, and platform

| Subsystem | Responsibility | Source | Tests |
|-----------|----------------|--------|-------|
| rule_catalog_profiles | Profile / pack layer + `extends` overrides | [src/fdai/core/rule_catalog_profiles/](../../../src/fdai/core/rule_catalog_profiles/) | [tests/core/rule_catalog_profiles/](../../../tests/core/rule_catalog_profiles/) |
| deploy_preflight | Pre-deployment feasibility probes | [src/fdai/core/deploy_preflight/](../../../src/fdai/core/deploy_preflight/) | [tests/core/deploy_preflight/](../../../tests/core/deploy_preflight/) |
| onboarding | Tenant / environment onboarding flow | [src/fdai/core/onboarding/](../../../src/fdai/core/onboarding/) | [tests/core/](../../../tests/core/) |
| readiness | Grounded readiness reports | [src/fdai/core/readiness/](../../../src/fdai/core/readiness/) | [tests/core/readiness/](../../../tests/core/readiness/) |
| assurance_twin | Read-only ontology twin (never executes) | [src/fdai/core/assurance_twin/](../../../src/fdai/core/assurance_twin/) | [tests/core/assurance_twin/](../../../tests/core/assurance_twin/) |
| architecture_review | Architecture-review manifest -> governed ontology projection | [src/fdai/core/architecture_review/](../../../src/fdai/core/architecture_review/) | [tests/core/architecture_review/](../../../tests/core/architecture_review/) |
| workflow | Compile and run version-pinned WorkflowDefinition records with principal bindings, Process journal, and projection retry | [src/fdai/core/workflow/](../../../src/fdai/core/workflow/) | [tests/core/workflow/](../../../tests/core/workflow/) |
| scheduler | Create/pause/resume/edit/run-now/cancel lifecycle, cron dispatch, run history, blueprints, and scoped continuations ([design](../interfaces/scheduled-result-continuations.md)) | [src/fdai/core/scheduler/](../../../src/fdai/core/scheduler/) | [tests/core/scheduler/](../../../tests/core/scheduler/) |
| metering | Usage metering counters | [src/fdai/core/metering/](../../../src/fdai/core/metering/) | [tests/core/metering/](../../../tests/core/metering/) |
| measurement | Phase-4 continuous measurement, including MTTR and four DORA measures | [src/fdai/core/measurement/](../../../src/fdai/core/measurement/) | [tests/core/measurement/](../../../tests/core/measurement/) |
| mscp_profile | Level-neutral `mscp-operational-v1` provenance, pure effect/cycle/integrity checks, and optional ControlLoop shadow observation ([design](mscp-operational-profile.md)) | [src/fdai/core/mscp_profile/](../../../src/fdai/core/mscp_profile/) | [tests/core/mscp_profile/](../../../tests/core/mscp_profile/) |
| security | Security-signal producers | [src/fdai/core/security/](../../../src/fdai/core/security/) | [tests/core/security/](../../../tests/core/security/) |
| platform | Platform-primitive facade | [src/fdai/core/platform/](../../../src/fdai/core/platform/) | [tests/core/](../../../tests/core/) |
| verticals | Resilience / Change Safety / Cost | [src/fdai/core/verticals/](../../../src/fdai/core/verticals/) | [tests/core/verticals/](../../../tests/core/verticals/) |

## Agent pantheon

The 15 named agents. Every file lives flat under `src/fdai/agents/`;
framework helpers live under `_framework/`. See
[.github/instructions/agent-pantheon.instructions.md](../../../.github/instructions/agent-pantheon.instructions.md)
for the fork-locked role bindings and change contract.

| Agent | Role | Source | Design doc |
|-------|------|--------|------------|
| Odin | Master planner + tie-breaker | [odin.py](../../../src/fdai/agents/odin.py) | [agent-pantheon.md](../agents/agent-pantheon.md) |
| Thor | Sole privileged executor / dispatcher | [thor.py](../../../src/fdai/agents/thor.py) | agent-pantheon.md |
| Forseti | Judge (verdict issuer) | [forseti.py](../../../src/fdai/agents/forseti.py) | agent-pantheon.md |
| Huginn | Event collector | [huginn.py](../../../src/fdai/agents/huginn.py) | agent-pantheon.md |
| Heimdall | Observer / signal gatherer | [heimdall.py](../../../src/fdai/agents/heimdall.py) | agent-pantheon.md |
| Var | HIL approval principal | [var.py](../../../src/fdai/agents/var.py) | agent-pantheon.md |
| Vidar | Recovery / rollback / DR | [vidar.py](../../../src/fdai/agents/vidar.py) | agent-pantheon.md |
| Bragi | Narrator (translator only, never judge) | [bragi.py](../../../src/fdai/agents/bragi.py) | agent-pantheon.md |
| Saga | Auditor + handoff-to-issue | [saga.py](../../../src/fdai/agents/saga.py) | agent-pantheon.md |
| Mimir | Rule steward | [mimir.py](../../../src/fdai/agents/mimir.py) | agent-pantheon.md |
| Norns | Learner | [norns.py](../../../src/fdai/agents/norns.py) | agent-pantheon.md |
| Muninn | Memory | [muninn.py](../../../src/fdai/agents/muninn.py) | agent-pantheon.md |
| Njord | Cost specialist (advisory) | [njord.py](../../../src/fdai/agents/njord.py) | agent-pantheon.md |
| Freyr | Capacity specialist (advisory) | [freyr.py](../../../src/fdai/agents/freyr.py) | agent-pantheon.md |
| Loki | Chaos specialist (advisory) | [loki.py](../../../src/fdai/agents/loki.py) | agent-pantheon.md |

## Delivery adapters (outbound)

| Adapter | Purpose | Source |
|---------|---------|--------|
| azure | Azure operations, inventory, typed commands, metrics, bounded KQL, App Insights evidence, the development Function gateway `DirectApiExecutor`, and the pinned-template Container Apps Job backend | [src/fdai/delivery/azure/](../../../src/fdai/delivery/azure/) |
| shell | Bash no-exec checks, private Git workspaces, and the credential-free bubblewrap command runner | [src/fdai/delivery/shell/](../../../src/fdai/delivery/shell/) |
| execution_backend | Lifecycle adapters that preserve bubblewrap and VM-task sandbox authority | [src/fdai/delivery/execution_backend/](../../../src/fdai/delivery/execution_backend/) |
| programmatic_pipeline | Local isolated child runner and broker transport | [src/fdai/delivery/programmatic_pipeline/](../../../src/fdai/delivery/programmatic_pipeline/) |
| browser | Optional isolated async Playwright capture with GET/HEAD interception and no general browser handle | [src/fdai/delivery/browser/](../../../src/fdai/delivery/browser/) |
| trajectory | Deterministic streaming exporter, PostgreSQL metadata/quarantine store, Owner-only read projection, and offline CLI | [src/fdai/delivery/trajectory/](../../../src/fdai/delivery/trajectory/), [postgres_trajectory.py](../../../src/fdai/delivery/persistence/postgres_trajectory.py), [trajectory_datasets.py](../../../src/fdai/delivery/read_api/routes/trajectory_datasets.py), [deployment_cli/trajectory.py](../../../src/fdai/deployment_cli/trajectory.py) |
| azure_devops | Azure DevOps PR / pipeline gate | [src/fdai/delivery/azure_devops/](../../../src/fdai/delivery/azure_devops/) |
| github | GitHub App / Checks API | [src/fdai/delivery/github/](../../../src/fdai/delivery/github/) |
| gitops_pr | PR-native remediation packager | [src/fdai/delivery/gitops_pr/](../../../src/fdai/delivery/gitops_pr/) |
| chatops | Teams / Slack Adaptive Cards | [src/fdai/delivery/chatops/](../../../src/fdai/delivery/chatops/) |
| notifications | Channel dispatch plus PagerDuty/ServiceNow incident lifecycle and PagerDuty roster adapters | [notifications/](../../../src/fdai/delivery/notifications/), [incident_platform/](../../../src/fdai/delivery/incident_platform/) |
| read_api | Console read-only HTTP surface; route-owned background, busy-input, and skill runtime helpers | [src/fdai/delivery/read_api/](../../../src/fdai/delivery/read_api/) |
| provisioning | Terraform / IaC apply driver | [src/fdai/delivery/provisioning/](../../../src/fdai/delivery/provisioning/) |
| persistence | Postgres + pgvector stores, including durable conversation delivery, execution submissions/attempts, LLM metering, report-signal projections, skill-source state, and programmatic pipeline receipts/aggregates | [src/fdai/delivery/persistence/](../../../src/fdai/delivery/persistence/) |
| document_index | Structure-aware document chunking and local embedding retrieval | [src/fdai/delivery/document_index/](../../../src/fdai/delivery/document_index/) |
| behavior_knowledge | Localized object and architecture behavior seeds, hybrid/comparison retrieval, tracked-source freshness, and a 20-question quality gate ([design](../interfaces/behavior-knowledge.md)) | [src/fdai/delivery/behavior_knowledge/](../../../src/fdai/delivery/behavior_knowledge/) |
| pgvector | Persistent document and behavior vector-index adapters | [src/fdai/delivery/pgvector/](../../../src/fdai/delivery/pgvector/) |
| datadog | Datadog metric / event adapter (`DatadogMetricProvider` in `metric.py`) | [src/fdai/delivery/datadog/](../../../src/fdai/delivery/datadog/) |
| prometheus | Prometheus scrape adapter (`PrometheusMetricProvider` in `metric.py`) | [src/fdai/delivery/prometheus/](../../../src/fdai/delivery/prometheus/) |
| splunk | Splunk log adapter (`SplunkMetricProvider` in `metric.py`) | [src/fdai/delivery/splunk/](../../../src/fdai/delivery/splunk/) |
| jira | Jira issue adapter (`JiraToolExecutor` in `tool.py`) | [src/fdai/delivery/jira/](../../../src/fdai/delivery/jira/) |
| mcp | Model Context Protocol seam | [src/fdai/delivery/mcp/](../../../src/fdai/delivery/mcp/) |
| webhook | Generic outbound webhook + inbound `WebhookIngress` for the optional `POST /webhook` route | [src/fdai/delivery/webhook/](../../../src/fdai/delivery/webhook/) |
| working_context | Delivery-side context assembly | [src/fdai/delivery/working_context/](../../../src/fdai/delivery/working_context/) |
| chaos (delivery) | Live chaos-inject adapters used when a `Chaos` runbook step goes enforce - CSP-neutral `live_injectors.py` + `chaos_mesh.py` (Chaos Mesh CRDs) + `mysql_load.py` (MySQL benchmark load) | [src/fdai/delivery/chaos/](../../../src/fdai/delivery/chaos/) |
| investigation (delivery) | Governed on-demand investigation ToolExecutor over the shared MetricProvider | [src/fdai/delivery/investigation/](../../../src/fdai/delivery/investigation/) |
| irp (delivery) | Alert handler + EventBus proposal router that re-enters recommendations into the typed pipeline | [src/fdai/delivery/irp/](../../../src/fdai/delivery/irp/) |
| remediation (delivery) | Concrete `DirectApiExecutor` for direct-API remediation (`live_direct_api.py`); the Protocol is defined in `shared/providers/` | [src/fdai/delivery/remediation/](../../../src/fdai/delivery/remediation/) |
| scheduler_tick_cli | Standalone entry point that drives the scheduler tick from a cron / Container Apps Job (single module, not a package) | [src/fdai/delivery/scheduler_tick_cli.py](../../../src/fdai/delivery/scheduler_tick_cli.py) |
| analyzer_tick_cli | Inventory-driven metric analyzer entry point that publishes findings and persists report signals | [src/fdai/delivery/analyzer_tick_cli.py](../../../src/fdai/delivery/analyzer_tick_cli.py) |

## Shared plumbing (`src/fdai/shared/`)

| Package | Purpose | Source |
|---------|---------|--------|
| contracts | Cross-package Pydantic contracts, including optional ObjectType lifecycle criteria | [src/fdai/shared/contracts/](../../../src/fdai/shared/contracts/) |
| ontology | Domain ontology (ObjectType / LinkType / ActionType) | [src/fdai/shared/ontology/](../../../src/fdai/shared/ontology/) |
| providers | Provider Protocols including `ExecutionBackend`, non-cached ephemeral typed-command output with bounded diagnostic receipts, process-local EventBus, bounded SSE, isolated programmatic pipeline runners, [access-scoped conversation search](../interfaces/conversation-search.md), and [structured behavior knowledge](../interfaces/behavior-knowledge.md) | [src/fdai/shared/providers/](../../../src/fdai/shared/providers/) |
| config | Config loader, schema, and shared runtime activation flags | [src/fdai/shared/config/](../../../src/fdai/shared/config/) |
| streaming | Kafka / Event Hub abstraction | [src/fdai/shared/streaming/](../../../src/fdai/shared/streaming/) |
| resilience | Retry / circuit-breaker helpers | [src/fdai/shared/resilience/](../../../src/fdai/shared/resilience/) |
| telemetry | Structured logging + metrics helpers | [src/fdai/shared/telemetry/](../../../src/fdai/shared/telemetry/) |

## Composition and catalog

| Path | Purpose |
|------|---------|
| [src/fdai/composition/\_\_init\_\_.py](../../../src/fdai/composition/__init__.py) | Facade + `default_container` + `default_container_from_env`. |
| [src/fdai/composition/_helpers.py](../../../src/fdai/composition/_helpers.py) | `Container`, `LlmBindings`, `LlmBindingsUnavailableError`. |
| [src/fdai/composition/wire_llm.py](../../../src/fdai/composition/wire_llm.py) | Azure OpenAI LLM binder (composition-time model resolution). |
| [src/fdai/composition/wire_azure.py](../../../src/fdai/composition/wire_azure.py) | Fork-wire container + `AzureWireOverrides`. |
| [src/fdai/composition/wire_change_feed.py](../../../src/fdai/composition/wire_change_feed.py) | Change-feed factory wiring (Azure DevOps / GitHub change producers). |
| [src/fdai/composition/wire_metric_provider.py](../../../src/fdai/composition/wire_metric_provider.py) | `MetricProvider` binder (Azure Monitor Logs auto-bind when `FDAI_MONITOR_WORKSPACE_ID` is set); split out of `wire_azure` to hold the LOC ceiling (G-4). |
| [src/fdai/composition/wire_trajectory.py](../../../src/fdai/composition/wire_trajectory.py) | Binds authorization-first source joins, dataset metadata, quarantine export, and read-only administration without enabling the feature in the default container. |
| [src/fdai/composition/wire_execution_backends.py](../../../src/fdai/composition/wire_execution_backends.py) | Validates server-selected profiles and binds required backends plus the durable ledger without enabling profiles by default. |
| [src/fdai/rule_catalog/](../../../src/fdai/rule_catalog/) | Loader for the `rule-catalog/` tree (YAML). |
| [rule-catalog/](../../../rule-catalog/) | The rule / policy / action-type catalog (data). |

## Developer entry points and slash commands

The repo ships a small set of scripts and Copilot slash commands to keep
local development, verification, and session hand-off consistent.

| Path | Purpose |
|------|---------|
| [scripts/verify.sh](../../../scripts/verify.sh) | Single local gate: fast text/lint and clean-checkout contracts by default; `--full` adds safety-core coverage plus console and CLI verification, while `--full <path>` runs a focused pytest target. |
| [tools/architecture-diagrams/](../../../tools/architecture-diagrams/) | Bilingual YAML-to-SVG/PNG architecture compiler plus the progressive site viewer; canonical specs live in [docs/diagrams/](../../diagrams/). |
| [scripts/lib/design-routes.json](../../../scripts/lib/design-routes.json) | Machine-readable path -> required instructions/design docs -> owning docs -> focused validation routes. |
| [scripts/agent/design_context.py](../../../scripts/agent/design_context.py) / [.github/hooks/design-context.json](../../../.github/hooks/design-context.json) | Records successful design-document reads per agent session and blocks edits when required context is missing or stale. |
| [check-design-doc-impact.py](../../../scripts/quality/architecture/check-design-doc-impact.py) / [check-document-size.py](../../../scripts/quality/architecture/check-document-size.py) | Docs-after enforcement plus the new-doc and legacy-growth size ratchet. |
| [check-fork-runtime-independence.py](../../../scripts/quality/architecture/check-fork-runtime-independence.py) | Rejects fork integrity markers from runtime/config/infra behavior. |
| [scripts/quality/ci/check-ci-contracts.py](../../../scripts/quality/ci/check-ci-contracts.py) | Clean-checkout, Docker build-context, live-DB skip-order, and Python test-partition regression checks shared by local verification and CI. |
| [scripts/quality/ci/run-python-tests.sh](../../../scripts/quality/ci/run-python-tests.sh) | Local `all` mode preserves coverage plus integration; CI selects deterministic no-coverage regression shards, a core-focused coverage run, or serial live-DB integration. Change-scope classification skips expensive Python jobs for docs-only and console-only changes. |
| [scripts/quality/ci/pytest_shard.py](../../../scripts/quality/ci/pytest_shard.py) / [resolve_test_scope.py](../../../scripts/quality/ci/resolve_test_scope.py) | Stable file-level shard assignment and Git-diff classification for expensive CI test jobs. |
| [scripts/quality/ci/run-operator-surfaces.sh](../../../scripts/quality/ci/run-operator-surfaces.sh) | Console and CLI tests, type checks, production build, and entry-bundle budget. |
| [scripts/deployment/local/dev-up.sh](../../../scripts/deployment/local/dev-up.sh) / [dev-down.sh](../../../scripts/deployment/local/dev-down.sh) / [dev-logs.sh](../../../scripts/deployment/local/dev-logs.sh) / [dev-status.sh](../../../scripts/deployment/local/dev-status.sh) | Local Docker Compose stack (pgvector + Redpanda) lifecycle. |
| [scripts/automation/tests-for-diff.sh](../../../scripts/automation/tests-for-diff.sh) | Run only the pytest files affected by the current diff. |
| [scripts/deployment/azure/genesis-up.sh](../../../scripts/deployment/azure/genesis-up.sh) | Stream `terraform apply` into the Day-1 Genesis surface via `delivery/provisioning`. |
| [scripts/deployment/azure/azd-up.sh](../../../scripts/deployment/azure/azd-up.sh) | `azd up` wrapper (safe-preview default). |
| [scripts/automation/resume.sh](../../../scripts/automation/resume.sh) | Session-resume snapshot for cross-session hand-off. |
| [.github/prompts/verify.prompt.md](../../../.github/prompts/verify.prompt.md) | `/verify` - run `scripts/verify.sh`. |
| [.github/prompts/critique-batch.prompt.md](../../../.github/prompts/critique-batch.prompt.md) | `/critique-batch` - critique-and-harden loop (paired with the `coding-hardening` skill). |
| [.github/prompts/harden-coverage.prompt.md](../../../.github/prompts/harden-coverage.prompt.md) | `/harden-coverage` - coverage hardening on low-coverage modules. |
| [.github/prompts/pantheon-safe-edit.prompt.md](../../../.github/prompts/pantheon-safe-edit.prompt.md) | `/pantheon-safe-edit` - guarded editing under `src/fdai/agents/**`. |
| [.github/prompts/resume-session.prompt.md](../../../.github/prompts/resume-session.prompt.md) | `/resume-session` - reload prior session context. |

## Related docs

| To learn about | Read |
|----------------|------|
| Module boundaries and DI seams | [project-structure.md](project-structure.md) |
| The 3-tier control loop | [../../../.github/instructions/architecture.instructions.md](../../../.github/instructions/architecture.instructions.md) |
| Agent roles and permissions | [../agents/agent-pantheon.md](../agents/agent-pantheon.md) |
| CSP-neutral contract seams | [csp-neutrality.md](csp-neutrality.md) |
| LLM tiering and grounding | [llm-strategy.md](llm-strategy.md) |
