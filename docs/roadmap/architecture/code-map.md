---
title: Code Map
---
# Code Map

A one-page index of the FDAI codebase so anyone (agent or human) can jump
from a subsystem name to its source, its tests, and its design doc in one
hop. This is the **scannable partner** to [project-structure.md](project-structure.md),
which explains the module boundaries and the DI seams in detail.

Use this doc when you need to answer "where does X live?" without opening
`list_dir` five times. The tables below cover the 46 core subsystem
directories (48 rows if you count the three `tiers/*` subdirs; the
companion [project-structure.md](project-structure.md) counts 41 by
excluding the five G-1 domain-group facades), the 15 pantheon agents, and
the delivery / shared plumbing packages.

## Design at a glance

- **`src/fdai/core/`** is the headless control plane. No UI, no direct cloud
  SDK imports. 46 subsystem directories plus the top-level
  `ontology_explorer.py` module, grouped by control-loop role below.
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
| audit | Append-only hash-chained log + KPI emission | [src/fdai/core/audit/](../../../src/fdai/core/audit/) | [tests/core/audit/](../../../tests/core/audit/) | [security-and-identity.md](security-and-identity.md) |
| control_loop | Pipeline orchestrator (Stage protocol) | [src/fdai/core/control_loop/](../../../src/fdai/core/control_loop/) | [tests/core/](../../../tests/core/) | project-structure.md |
| pipeline | Domain-group facade for the above | [src/fdai/core/pipeline/](../../../src/fdai/core/pipeline/) | (same as members) | project-structure.md |

## Detection, RCA, and incident lifecycle

| Subsystem | Responsibility | Source | Tests |
|-----------|----------------|--------|-------|
| detection | Anomaly / forecast producers (re-enter event-ingest) | [src/fdai/core/detection/](../../../src/fdai/core/detection/) | [tests/core/detection/](../../../tests/core/detection/) |
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
| working_context | Per-turn prompt assembly (token-bounded) | [src/fdai/core/working_context/](../../../src/fdai/core/working_context/) | [tests/core/](../../../tests/core/) |
| prompts | Catalog-as-code prompt composer | [src/fdai/core/prompts/](../../../src/fdai/core/prompts/) | [tests/core/](../../../tests/core/) |
| tools | T2 tool registry + ToolExecutor | [src/fdai/core/tools/](../../../src/fdai/core/tools/) | [tests/core/tools/](../../../tests/core/tools/) |
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
| rbac | Human RBAC for the read API | [src/fdai/core/rbac/](../../../src/fdai/core/rbac/) | [tests/core/](../../../tests/core/) |

## Rule catalog, deploy, and platform

| Subsystem | Responsibility | Source | Tests |
|-----------|----------------|--------|-------|
| rule_catalog_profiles | Profile / pack layer + `extends` overrides | [src/fdai/core/rule_catalog_profiles/](../../../src/fdai/core/rule_catalog_profiles/) | [tests/core/rule_catalog_profiles/](../../../tests/core/rule_catalog_profiles/) |
| deploy_preflight | Pre-deployment feasibility probes | [src/fdai/core/deploy_preflight/](../../../src/fdai/core/deploy_preflight/) | [tests/core/deploy_preflight/](../../../tests/core/deploy_preflight/) |
| onboarding | Tenant / environment onboarding flow | [src/fdai/core/onboarding/](../../../src/fdai/core/onboarding/) | [tests/core/](../../../tests/core/) |
| readiness | Grounded readiness reports | [src/fdai/core/readiness/](../../../src/fdai/core/readiness/) | [tests/core/readiness/](../../../tests/core/readiness/) |
| assurance_twin | Read-only ontology twin (never executes) | [src/fdai/core/assurance_twin/](../../../src/fdai/core/assurance_twin/) | [tests/core/assurance_twin/](../../../tests/core/assurance_twin/) |
| workflow | Compile catalog Workflow -> Runbook | [src/fdai/core/workflow/](../../../src/fdai/core/workflow/) | [tests/core/](../../../tests/core/) |
| scheduler | Cron-shaped triggers | [src/fdai/core/scheduler/](../../../src/fdai/core/scheduler/) | [tests/core/scheduler/](../../../tests/core/scheduler/) |
| metering | Usage metering counters | [src/fdai/core/metering/](../../../src/fdai/core/metering/) | [tests/core/metering/](../../../tests/core/metering/) |
| measurement | Phase-4 continuous measurement | [src/fdai/core/measurement/](../../../src/fdai/core/measurement/) | [tests/core/measurement/](../../../tests/core/measurement/) |
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
| azure | Azure resource operations + probes | [src/fdai/delivery/azure/](../../../src/fdai/delivery/azure/) |
| azure_devops | Azure DevOps PR / pipeline gate | [src/fdai/delivery/azure_devops/](../../../src/fdai/delivery/azure_devops/) |
| github | GitHub App / Checks API | [src/fdai/delivery/github/](../../../src/fdai/delivery/github/) |
| gitops_pr | PR-native remediation packager | [src/fdai/delivery/gitops_pr/](../../../src/fdai/delivery/gitops_pr/) |
| chatops | Teams / Slack Adaptive Cards | [src/fdai/delivery/chatops/](../../../src/fdai/delivery/chatops/) |
| notifications | Channel dispatch layer | [src/fdai/delivery/notifications/](../../../src/fdai/delivery/notifications/) |
| read_api | Console read-only HTTP surface | [src/fdai/delivery/read_api/](../../../src/fdai/delivery/read_api/) |
| provisioning | Terraform / IaC apply driver | [src/fdai/delivery/provisioning/](../../../src/fdai/delivery/provisioning/) |
| persistence | Postgres + pgvector store | [src/fdai/delivery/persistence/](../../../src/fdai/delivery/persistence/) |
| pgvector | Vector-index helpers | [src/fdai/delivery/pgvector/](../../../src/fdai/delivery/pgvector/) |
| datadog | Datadog metric / event adapter (`DatadogMetricProvider` in `metric.py`) | [src/fdai/delivery/datadog/](../../../src/fdai/delivery/datadog/) |
| prometheus | Prometheus scrape adapter (`PrometheusMetricProvider` in `metric.py`) | [src/fdai/delivery/prometheus/](../../../src/fdai/delivery/prometheus/) |
| splunk | Splunk log adapter (`SplunkMetricProvider` in `metric.py`) | [src/fdai/delivery/splunk/](../../../src/fdai/delivery/splunk/) |
| jira | Jira issue adapter (`JiraToolExecutor` in `tool.py`) | [src/fdai/delivery/jira/](../../../src/fdai/delivery/jira/) |
| mcp | Model Context Protocol seam | [src/fdai/delivery/mcp/](../../../src/fdai/delivery/mcp/) |
| webhook | Generic outbound webhook + inbound `WebhookIngress` for the optional `POST /webhook` route | [src/fdai/delivery/webhook/](../../../src/fdai/delivery/webhook/) |
| working_context | Delivery-side context assembly | [src/fdai/delivery/working_context/](../../../src/fdai/delivery/working_context/) |
| chaos (delivery) | Live chaos-inject adapters used when a `Chaos` runbook step goes enforce - CSP-neutral `live_injectors.py` + `chaos_mesh.py` (Chaos Mesh CRDs) + `mysql_load.py` (MySQL benchmark load) | [src/fdai/delivery/chaos/](../../../src/fdai/delivery/chaos/) |
| remediation (delivery) | Concrete `DirectApiExecutor` for direct-API remediation (`live_direct_api.py`); the Protocol is defined in `shared/providers/` | [src/fdai/delivery/remediation/](../../../src/fdai/delivery/remediation/) |
| scheduler_tick_cli | Standalone entry point that drives the scheduler tick from a cron / Container Apps Job (single module, not a package) | [src/fdai/delivery/scheduler_tick_cli.py](../../../src/fdai/delivery/scheduler_tick_cli.py) |

## Shared plumbing (`src/fdai/shared/`)

| Package | Purpose | Source |
|---------|---------|--------|
| contracts | Cross-package Pydantic contracts | [src/fdai/shared/contracts/](../../../src/fdai/shared/contracts/) |
| ontology | Domain ontology (ObjectType / LinkType / ActionType) | [src/fdai/shared/ontology/](../../../src/fdai/shared/ontology/) |
| providers | Provider Protocols (EventBus / StateStore / etc.) | [src/fdai/shared/providers/](../../../src/fdai/shared/providers/) |
| config | Config loader + schema | [src/fdai/shared/config/](../../../src/fdai/shared/config/) |
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
| [src/fdai/rule_catalog/](../../../src/fdai/rule_catalog/) | Loader for the `rule-catalog/` tree (YAML). |
| [rule-catalog/](../../../rule-catalog/) | The rule / policy / action-type catalog (data). |

## Developer entry points and slash commands

The repo ships a small set of scripts and Copilot slash commands to keep
local development, verification, and session hand-off consistent.

| Path | Purpose |
|------|---------|
| [scripts/verify.sh](../../../scripts/verify.sh) | Single pre-commit gate: fast text/lint gates by default, `--full [path]` runs pytest. |
| [scripts/dev-up.sh](../../../scripts/dev-up.sh) / [dev-down.sh](../../../scripts/dev-down.sh) / [dev-logs.sh](../../../scripts/dev-logs.sh) / [dev-status.sh](../../../scripts/dev-status.sh) | Local Docker Compose stack (pgvector + Redpanda) lifecycle. |
| [scripts/tests-for-diff.sh](../../../scripts/tests-for-diff.sh) | Run only the pytest files affected by the current diff. |
| [scripts/genesis-up.sh](../../../scripts/genesis-up.sh) | Stream `terraform apply` into the Day-1 Genesis surface via `delivery/provisioning`. |
| [scripts/azd-up.sh](../../../scripts/azd-up.sh) | `azd up` wrapper (safe-preview default). |
| [scripts/resume.sh](../../../scripts/resume.sh) | Session-resume snapshot for cross-session hand-off. |
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
