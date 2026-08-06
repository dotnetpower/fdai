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
  notifications, persistence, Operator API).
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
| tiers/t0_deterministic | Policy + checklist + what-if + drift, with audit attribution that distinguishes partial from total evaluator abstention | [src/fdai/core/tiers/t0_deterministic/](../../../src/fdai/core/tiers/t0_deterministic/) | [tests/core/tiers/](../../../tests/core/tiers/) | project-structure.md |
| tiers/t1_lightweight | Similarity reuse plus immutable operational-case context and current evidence verification | [src/fdai/core/tiers/t1_lightweight/](../../../src/fdai/core/tiers/t1_lightweight/) | [tests/core/tiers/](../../../tests/core/tiers/) | project-structure.md |
| tiers/t2_reasoning | Frontier-model reasoning (novel cases only), per-candidate call budgeting, bounded primary-to-secondary proposer failover, durable preferred-route selection, sanitized attempt receipts, and fail-closed HIL exhaustion; the money limb lives at the metering write | [src/fdai/core/tiers/t2_reasoning/](../../../src/fdai/core/tiers/t2_reasoning/) | [tests/core/tiers/](../../../tests/core/tiers/) | [llm-strategy.md](llm-strategy.md) |
| quality_gate | Mixed-model quorum over the normalized action type and parameters, plus verifier and grounding guards for T2 | [src/fdai/core/quality_gate/](../../../src/fdai/core/quality_gate/) | [tests/core/quality_gate/](../../../tests/core/quality_gate/) | [architecture.instructions.md § LLM Quality Gate](../../../.github/instructions/architecture.instructions.md#llm-quality-gate-required-for-t2) |
| risk_gate | Unified auto vs HIL vs deny authority. Requires indexed deterministic evidence for every declared ActionType precondition; missing or failed evidence routes to human approval. The runtime combines event evidence with Thor's durable active-run index and bounded ontology reads for effective `ChangeWindow` records. Missing indexed runs conflict, and truncated or malformed state cannot raise authority. Ceiling overrides render Rego, so every interpolated field is pattern-bound and escaped - a request MUST NOT be able to write policy. | [src/fdai/core/risk_gate/](../../../src/fdai/core/risk_gate/) | [tests/core/risk_gate/](../../../tests/core/risk_gate/) | [decisioning/](../decisioning/) |
| impact_analysis | Computes a bounded affected set and replay-stable `ChangeAssessment` for one normalized `Change`. Huginn carries identical evidence on the causal Event and owner topic; Forseti projects the result into Verdict and DecisionCase evidence. Stale, truncated, unmapped, over-cap, conflicting, failed, or incomplete planned-change evidence requires human review; it never grants execution authority. | [src/fdai/core/impact_analysis/](../../../src/fdai/core/impact_analysis/) | [tests/core/impact_analysis/](../../../tests/core/impact_analysis/) | [operating-ontology.md](operating-ontology.md) |
| execution_authorization | Resolve provider-neutral capability requirements against scoped customer policy and effective-access evidence before risk evaluation; manage a separate exact-plan access-grant lifecycle. | [src/fdai/core/execution_authorization/](../../../src/fdai/core/execution_authorization/) | [tests/core/execution_authorization/](../../../tests/core/execution_authorization/) | [execution-authorization-ontology.md](../decisioning/execution-authorization-ontology.md) |
| hil_resume | Park + resume on human decision. Principal identities compare case-insensitively, so recasing an object id cannot present one person as two and defeat the no-self-approval floor. Adds no-drop load plans, one-per-group initial dispatch, atomic expiry reaping, bounded reminders, durable decision delivery, and a CAS-owned shadow non-response ladder | [src/fdai/core/hil_resume/](../../../src/fdai/core/hil_resume/), [hil_registry.py](../../../src/fdai/shared/providers/hil_registry.py), and [hil_decision.py](../../../src/fdai/delivery/chatops/hil_decision.py) | [tests/core/hil_resume/](../../../tests/core/hil_resume/), [test_hil_callback.py](../../../tests/delivery/operator_api/test_hil_callback.py), and [test_hil_decision.py](../../../tests/delivery/test_hil_decision.py) | [channels-and-notifications.md](../interfaces/channels-and-notifications.md) |
| executor | Logical-target lock, idempotent apply, shared blast-radius ceiling, and PR-native content-addressed dry-run plus pre-effect/terminal audit lifecycle. An undeclared affected count is refused. | [src/fdai/core/executor/](../../../src/fdai/core/executor/) | [tests/core/executor/](../../../tests/core/executor/) | project-structure.md |
| execution_backend | Profile intersection, exact-version durable reconciliation that fails closed when a recorded profile disappears, and shadow health probes; no eligibility authority ([design](../interfaces/execution-backends.md)) | [src/fdai/core/execution_backend/](../../../src/fdai/core/execution_backend/) | [tests/core/execution_backend/](../../../tests/core/execution_backend/) | [execution-backends.md](../interfaces/execution-backends.md) |
| audit | Append-only hash-chained log. The chain rule (genesis, canonical form, chaining digest) lives once in `shared/providers/audit_hash.py` so both StateStore backends produce the same digest and a chain written by one verifies under the other. Startup readiness recomputes the persisted chain and blocks on a mismatch. Also owns nullable-stage correlation traces and KPI emission | [src/fdai/core/audit/](../../../src/fdai/core/audit/) | [tests/core/audit/](../../../tests/core/audit/) | [security-and-identity.md](security-and-identity.md) |
| control_loop | Pipeline orchestrator (Stage protocol) | [src/fdai/core/control_loop/](../../../src/fdai/core/control_loop/) | [tests/core/](../../../tests/core/) | project-structure.md |
| pipeline | Domain-group facade for the above | [src/fdai/core/pipeline/](../../../src/fdai/core/pipeline/) | (same as members) | project-structure.md |

## Detection, RCA, and incident lifecycle

| Subsystem | Responsibility | Source | Tests |
|-----------|----------------|--------|-------|
| detection | Anomaly and operational-insight producers, immutable positive/negative/abstained forecast episodes, event-time closure, publication outbox, and measured frozen configuration-baseline comparison with an immutable multi-scope version registry, conflict-checked full-report replay, preserved failed review attempts, durable revisioned readiness, and scoped read-only Azure evidence | [src/fdai/core/detection/](../../../src/fdai/core/detection/), [src/fdai/runtime/forecast_learning.py](../../../src/fdai/runtime/forecast_learning.py), and [src/fdai/delivery/persistence/postgres_forecast_episode.py](../../../src/fdai/delivery/persistence/postgres_forecast_episode.py) | [tests/core/detection/](../../../tests/core/detection/), [tests/runtime/test_forecast_learning.py](../../../tests/runtime/test_forecast_learning.py), and [tests/persistence/test_postgres_forecast_episode.py](../../../tests/persistence/test_postgres_forecast_episode.py) |
| case_history | Canonical case revisions, strict operational receipt compilation, action/incident artifact-first intake, StateStore-to-PostgreSQL shadow migration, full-chain generic-metadata backfill, retention, governed Norns analysis, and environment-independent failure fingerprints ([case-history design](../rules-and-detection/prediction-learning-and-case-history.md), [operational-learning design](../rules-and-detection/operational-learning-ontology.md)) | [src/fdai/core/case_history/](../../../src/fdai/core/case_history/), [src/fdai/shared/providers/case_history.py](../../../src/fdai/shared/providers/case_history.py), and [src/fdai/delivery/persistence/](../../../src/fdai/delivery/persistence/) | [tests/core/case_history/](../../../tests/core/case_history/), [tests/persistence/test_case_history_backfill.py](../../../tests/persistence/test_case_history_backfill.py), [tests/persistence/test_postgres_case_history.py](../../../tests/persistence/test_postgres_case_history.py), and [tests/agents/test_forecast_learning_chain.py](../../../tests/agents/test_forecast_learning_chain.py) |
| rca | Root-cause analysis plus a shadow runtime for leakage-safe lagged evidence, immutable hypotheses, support/refutation, and independent closure | [src/fdai/core/rca/](../../../src/fdai/core/rca/) | [tests/core/rca/](../../../tests/core/rca/) |
| incident | Incident lifecycle registry + state machine | [src/fdai/core/incident/](../../../src/fdai/core/incident/) | [tests/core/incident/](../../../tests/core/incident/) |
| slo | Workload SLO / burn-rate evaluator | [src/fdai/core/slo/](../../../src/fdai/core/slo/) | [tests/core/slo/](../../../tests/core/slo/) |
| irp | Incident response plan orchestrator | [src/fdai/core/irp/](../../../src/fdai/core/irp/) | [tests/core/irp/](../../../tests/core/irp/) |
| investigation | Bounded evidence-gathering runner | [src/fdai/core/investigation/](../../../src/fdai/core/investigation/) | [tests/core/investigation/](../../../tests/core/investigation/) |
| runbook | Linear runbook + on-failure branches | [src/fdai/core/runbook/](../../../src/fdai/core/runbook/) | [tests/core/](../../../tests/core/) |
| postmortem | LLM-optional PIR draft | [src/fdai/core/postmortem/](../../../src/fdai/core/postmortem/) | [tests/core/postmortem/](../../../tests/core/postmortem/) |
| chaos | Resilience and chaos probes; impact envelopes, continuous guards, and pre-authorized recovery are the target contract in [recovery-and-chaos-enforcement.md](../decisioning/recovery-and-chaos-enforcement.md) | [src/fdai/core/chaos/](../../../src/fdai/core/chaos/) | [tests/core/chaos/](../../../tests/core/chaos/) |
| capacity | Capacity + forecast findings | [src/fdai/core/capacity/](../../../src/fdai/core/capacity/) | [tests/core/capacity/](../../../tests/core/capacity/) |
| oncall | On-call rotation reader (read-only) | [src/fdai/core/oncall/](../../../src/fdai/core/oncall/) | [tests/core/](../../../tests/core/) |

## Knowledge, memory, and prompts

| Subsystem | Responsibility | Source | Tests |
|-----------|----------------|--------|-------|
| knowledge | Long-term knowledge store seam | [src/fdai/core/knowledge/](../../../src/fdai/core/knowledge/) | [tests/core/knowledge/](../../../tests/core/knowledge/) |
| document_ingestion | Agent-gated upload lifecycle with independent API/worker roles, durable claims, Forseti/Saga decisions, Var HIL, Muninn indexing, and gated-state recovery ([design](../interfaces/document-ingestion-agent-ownership.md)) | [src/fdai/core/document_ingestion/](../../../src/fdai/core/document_ingestion/) and [src/fdai/delivery/ingestion_gateway/](../../../src/fdai/delivery/ingestion_gateway/) | [tests/core/document_ingestion/](../../../tests/core/document_ingestion/) and [tests/delivery/ingestion_gateway/](../../../tests/delivery/ingestion_gateway/) |
| operator_memory | HIL-approved operator note store | [src/fdai/core/operator_memory/](../../../src/fdai/core/operator_memory/) | [tests/core/operator_memory/](../../../tests/core/operator_memory/) |
| learning | Consent-gated off-path post-turn eligibility, mixed-family consensus, deduplication, and inert proposal routing ([design](../decisioning/post-turn-improvement-review.md)) | [src/fdai/core/learning/](../../../src/fdai/core/learning/) | [tests/core/learning/](../../../tests/core/learning/) |
| conversation_assurance | Deterministic terminal checks, exact failure attribution, hold-first ontology adequacy review, independent model scoring, append-only assessments and disputes, subscription posterior learning, and chat-policy promotion/rollback ([design](../decisioning/conversation-assurance.md)) | [src/fdai/core/conversation_assurance/](../../../src/fdai/core/conversation_assurance/), [conversation_assurance.py](../../../src/fdai/delivery/azure/llm/conversation_assurance.py), and [postgres_conversation_assurance.py](../../../src/fdai/delivery/persistence/postgres_conversation_assurance.py) | [tests/core/conversation_assurance/](../../../tests/core/conversation_assurance/), [test_conversation_assurance.py](../../../tests/delivery/operator_api/test_conversation_assurance.py), and focused adapter/runtime tests |
| trajectory | Authorization-first immutable source join, versioned observable envelope, deterministic JSONL export, offline validation/replay, retention/legal hold, and reviewed-only Norns aggregate intake ([design](../interfaces/governed-trajectory-datasets.md)) | [src/fdai/core/trajectory/](../../../src/fdai/core/trajectory/) and [src/fdai/shared/providers/trajectory.py](../../../src/fdai/shared/providers/trajectory.py) | [tests/core/trajectory/](../../../tests/core/trajectory/), [tests/delivery/trajectory/](../../../tests/delivery/trajectory/), and focused API/persistence/agent tests |
| task_worker | Isolated depth-one read-only investigations with attenuated capabilities, durable branch state, and untrusted parent synthesis ([design](../agents/bounded-task-workers.md)) | [src/fdai/core/task_worker/](../../../src/fdai/core/task_worker/) | [tests/core/task_worker/](../../../tests/core/task_worker/) |
| background_task | Durable detached read-only sessions with lease/CAS ownership, server-clock quotas, coalesced progress, atomic completion outbox, bounded handoff retry, process-loss reconciliation, and gated retention purge ([design](../interfaces/background-task-sessions.md)) | [src/fdai/core/background_task/](../../../src/fdai/core/background_task/) | [tests/core/background_task/](../../../tests/core/background_task/) |
| read_investigation | Verified typed current/activity resource queries, observed-facet deterministic compilation, exact-resource follow-ups, 30-day Activity Log history, bounded parallel evidence, RG-scoped subscription health, durable latency profiles, owner-scoped direct/stream replay, honest cost usage, SSE heartbeats, and stream-close cancellation ([design](../interfaces/azure-read-investigations.md)) | [src/fdai/core/read_investigation/](../../../src/fdai/core/read_investigation/), [chat_inventory_query.py](../../../src/fdai/delivery/operator_api/routes/chat_inventory_query.py), [chat_inventory_compiler.py](../../../src/fdai/delivery/operator_api/routes/chat_inventory_compiler.py), [chat_inventory_activity.py](../../../src/fdai/delivery/operator_api/routes/chat_inventory_activity.py), [chat_resource_context.py](../../../src/fdai/delivery/operator_api/routes/chat_resource_context.py), and [src/fdai/delivery/azure/read_investigation/](../../../src/fdai/delivery/azure/read_investigation/) | [tests/core/read_investigation/](../../../tests/core/read_investigation/), [tests/delivery/azure/read_investigation/](../../../tests/delivery/azure/read_investigation/), [test_chat_inventory_query.py](../../../tests/delivery/operator_api/test_chat_inventory_query.py), [test_chat_inventory_compiler.py](../../../tests/delivery/operator_api/test_chat_inventory_compiler.py), and focused Operator API/persistence tests |
| briefing | Deterministic opening and scheduled briefings over the report feed | [src/fdai/core/briefing/](../../../src/fdai/core/briefing/) | [tests/core/briefing/](../../../tests/core/briefing/) |
| busy_input | Durable queue, interrupt, and safe-boundary steer arbitration shared by web, Slack, and Teams conversations ([design](../interfaces/busy-input-modes.md)) | [src/fdai/core/conversation/](../../../src/fdai/core/conversation/) | [tests/conversation/](../../../tests/conversation/) |
| durable_delivery | Verified principal bindings, persisted outbound responses and typed cumulative channel updates, bounded recovery, and adapter breakers ([design](../interfaces/durable-conversation-delivery.md)) | [src/fdai/core/conversation/](../../../src/fdai/core/conversation/) | [tests/conversation/](../../../tests/conversation/) and [tests/persistence/](../../../tests/persistence/) |
| conversation_progress | Deterministic `none` / `compact` / `timeline` / `detached` presentation selection, ordered redacted activity snapshots for Web/Slack/Teams, and bounded aggregate progress counters and latency without request or identity payloads | [conversation_channel.py](../../../src/fdai/shared/providers/conversation_channel.py), [channel_gateway.py](../../../src/fdai/core/conversation/channel_gateway.py), [publishers.py](../../../src/fdai/delivery/channels/publishers.py), and [conversation_progress.py](../../../src/fdai/shared/telemetry/conversation_progress.py) | [test_channel_gateway.py](../../../tests/conversation/test_channel_gateway.py), [test_publishers_and_routes.py](../../../tests/delivery/channels/test_publishers_and_routes.py), [test_rich_contract.py](../../../tests/delivery/channels/test_rich_contract.py), [test_conversation_progress_metrics.py](../../../tests/shared/test_conversation_progress_metrics.py), and focused Web recovery tests |
| user_context_projection | Metadata-only user context and workflow binding projection into the runtime ontology | [src/fdai/core/user_context_projection.py](../../../src/fdai/core/user_context_projection.py) | [tests/core/test_user_context_projection.py](../../../tests/core/test_user_context_projection.py) |
| working_context | Per-turn prompt assembly, invariant validation, capability-gated policy lifecycle, bounded shadow comparison, and approved-fixture replay ([design](../decisioning/context-selection-policy.md)) | [src/fdai/core/working_context/](../../../src/fdai/core/working_context/) | [tests/core/working_context/](../../../tests/core/working_context/) |
| operational_context | Replay-stable snapshots with typed evidence paths, effective-time and provenance projection, source-freshness receipts, fail-closed truncation, atomic provider-owned subgraph replacement, and stale deletion ([design](operating-ontology.md)) | [src/fdai/core/operational_context/](../../../src/fdai/core/operational_context/), [shared/providers/operating_model.py](../../../src/fdai/shared/providers/operating_model.py), [delivery/operating_model/](../../../src/fdai/delivery/operating_model/), and [runtime/operating_model.py](../../../src/fdai/runtime/operating_model.py) | [tests/core/operational_context/](../../../tests/core/operational_context/), [tests/delivery/operating_model/](../../../tests/delivery/operating_model/), and [test_operating_model.py](../../../tests/runtime/test_operating_model.py) |
| decision_case | Shared reliability, ARB, and cost options with protected-objective selection, Forseti/Odin/Thor/Var propagation, and `ResponseOutcome` closure | [src/fdai/core/decision_case/](../../../src/fdai/core/decision_case/) | [tests/core/decision_case/](../../../tests/core/decision_case/) and [test_decision_case_e2e.py](../../../tests/agents/test_decision_case_e2e.py) |
| operational_planning | Immutable specialist contributions, hard-constraint eligibility, bounded Pareto pruning, exact logic/simulation receipt lineage, and ordered Process child phases; planning remains A0 and grants no execution authority ([design](../decisioning/operational-planning.md)) | [src/fdai/core/operational_planning/](../../../src/fdai/core/operational_planning/) | [tests/core/operational_planning/](../../../tests/core/operational_planning/) |
| operational_learning | Classify sealed operational cases, require one fingerprint and ActionType with balanced verified-success and negative/control evidence, cite immutable revisions, and emit deduplicated inert Norns mappings through existing consensus and rate limits. Raw response outcomes remain held. | [src/fdai/core/operational_learning/](../../../src/fdai/core/operational_learning/) | [tests/core/operational_learning/](../../../tests/core/operational_learning/), [test_norns_operating_pattern.py](../../../tests/agents/test_norns_operating_pattern.py), and [test_operating_pattern_learning_e2e.py](../../../tests/agents/test_operating_pattern_learning_e2e.py) |
| prompts | Catalog-as-code prompt composer | [src/fdai/core/prompts/](../../../src/fdai/core/prompts/) | [tests/core/](../../../tests/core/) |
| skills | Progressive disclosure, governed bundles, and durable approved-source quarantine ([bundle design](../decisioning/governed-skill-bundles.md), [source design](../interfaces/skill-source-management.md)) | [src/fdai/core/skills/](../../../src/fdai/core/skills/) and [src/fdai/core/supply_chain/](../../../src/fdai/core/supply_chain/) | [tests/core/skills/](../../../tests/core/skills/), [tests/core/supply_chain/](../../../tests/core/supply_chain/), and [tests/persistence/](../../../tests/persistence/) |
| programmatic_pipeline | Reviewed bounded read-only tool loops with run capabilities, durable receipts, isolated runners, and compact results ([design](../interfaces/programmatic-tool-pipelines.md)) | [src/fdai/core/programmatic_pipeline/](../../../src/fdai/core/programmatic_pipeline/) | [tests/core/programmatic_pipeline/](../../../tests/core/programmatic_pipeline/) and [tests/delivery/programmatic_pipeline/](../../../tests/delivery/programmatic_pipeline/) |
| browser_evidence | Origin and DNS policy, redaction, immutable artifacts, evidence-only surfaces, and shadow comparison ([design](../interfaces/browser-evidence.md)) | [src/fdai/core/browser_evidence/](../../../src/fdai/core/browser_evidence/) | [tests/core/browser_evidence/](../../../tests/core/browser_evidence/) and [tests/delivery/browser/](../../../tests/delivery/browser/) |
| tools | T2 file, package, and composite tool registries + ToolExecutor + typed command catalog | [src/fdai/core/tools/](../../../src/fdai/core/tools/) | [tests/core/tools/](../../../tests/core/tools/) |
| web_search | Last-resort web-search seam | [src/fdai/core/web_search/](../../../src/fdai/core/web_search/) | [tests/core/web_search/](../../../tests/core/web_search/) |
| capability_catalog | Additive capability packages with typed bindings, optional reasoning-tool metadata, providers, and disabled-first extension lifecycle | [src/fdai/core/capability_catalog/](../../../src/fdai/core/capability_catalog/) | [tests/core/capability_catalog/](../../../tests/core/capability_catalog/) |
| licensing | Signed capability entitlement for an image-delivered distribution: crypto-free token contract, availability-only resolution, and fail-safe degradation ([design](../fork-and-sequencing/capability-licensing.md)) | [src/fdai/core/licensing/](../../../src/fdai/core/licensing/) | [tests/core/licensing/](../../../tests/core/licensing/) and [tests/scripts/test_issue_license.py](../../../tests/scripts/test_issue_license.py) |
| ontology_explorer | Deterministic Mermaid renderer for the loaded ObjectType / LinkType catalog (single module, not a package) | [src/fdai/core/ontology_explorer.py](../../../src/fdai/core/ontology_explorer.py) | [tests/core/](../../../tests/core/) |
| ontology_platform | Exact releases, semantic interfaces, bounded ObjectSets, mutation planning, typed functions, projection and reconciliation, proposal-only SDK generation | [src/fdai/core/ontology_platform/](../../../src/fdai/core/ontology_platform/) | [tests/core/ontology_platform/](../../../tests/core/ontology_platform/) |

Provider-wide Azure discovery, sanitized reproduction commands, and explicit coverage receipts are
the target design in [Azure Resource Discovery Command Coverage](../interfaces/azure-resource-discovery-commands.md).
They extend the implemented `read_investigation` row above and are not yet a shipped subsystem.

## Operator surfaces and notifications

| Subsystem | Responsibility | Source | Tests |
|-----------|----------------|--------|-------|
| conversation | NL turn -> bounded read tools. Channel pairing and cross-channel identity links require a distinct approver decided on normalised identities, so recasing an id does not make an operator their own approver; model-free Bragi current-screen T0 answers; bounded cross-process agent introspection; principal-timezone server-clock answers; exact-argument contextual follow-up translation; all-before-execution 2-3 step read planning with identity-scoped conflict blocking; role-scoped zero-execution clarification; AnswerPlan/tool/evidence/history-composed grounded narration with exact-ref, canonical-ID, numeric, timestamp, and freshness fallback; hybrid T0 plus strict semantic public-search intent and query normalization; current-screen evidence walkthrough; per-turn agent prompt-layer manifest carried into narrator constraints; deterministic bilingual read-tool planning that gathers scoped owned evidence before the answering turn, capped in count and depth, bounded by one prefetch budget and a bounded ownership route, and attached only to the owner that answered; evidence-preserving Korean prose review | [src/fdai/core/conversation/](../../../src/fdai/core/conversation/) with [agent_introspection_bus.py](../../../src/fdai/delivery/agent_introspection_bus.py), pure argument parsing in [tool_arguments.py](../../../src/fdai/core/conversation/tool_arguments.py), [chat_screen_data.py](../../../src/fdai/delivery/operator_api/routes/chat_screen_data.py), [chat_current_time.py](../../../src/fdai/delivery/operator_api/routes/chat_current_time.py), [chat_web_search_intent.py](../../../src/fdai/delivery/operator_api/routes/chat_web_search_intent.py), [chat_prompt.py](../../../src/fdai/delivery/operator_api/routes/chat_prompt.py), [chat_prompt_ontology.py](../../../src/fdai/delivery/operator_api/routes/chat_prompt_ontology.py), and [chat_answer_quality.py](../../../src/fdai/delivery/operator_api/routes/chat_answer_quality.py) | [tests/core/conversation/](../../../tests/core/conversation/), [test_agent_introspection_bus.py](../../../tests/delivery/test_agent_introspection_bus.py), [test_chat_screen_data.py](../../../tests/delivery/operator_api/test_chat_screen_data.py), [test_chat_current_time.py](../../../tests/delivery/operator_api/test_chat_current_time.py), [test_chat_web_search.py](../../../tests/delivery/operator_api/test_chat_web_search.py), [test_chat_prompt.py](../../../tests/delivery/operator_api/test_chat_prompt.py), and [test_chat_answer_quality.py](../../../tests/delivery/operator_api/test_chat_answer_quality.py) |
| conversation_attachments | Explicit attachment purpose, protected Slack/Teams fetch, web document refs, and optional OCR ([design](../interfaces/conversation-attachments.md)) | [src/fdai/core/conversation/attachment_directive.py](../../../src/fdai/core/conversation/attachment_directive.py), [src/fdai/delivery/channels/](../../../src/fdai/delivery/channels/), and [document_ocr.py](../../../src/fdai/delivery/azure/document_ocr.py) | [tests/delivery/channels/](../../../tests/delivery/channels/), [test_document_ocr.py](../../../tests/delivery/azure/test_document_ocr.py), and focused chat tests |
| operator | Operator-console coordinator ([surface](../interfaces/operator-console.md), [module map](../interfaces/operator-console-module-map.md), [progressive conversations](../interfaces/operator-console-progressive-conversations.md), [narrator routing](../interfaces/narrator-routing-and-latency.md)) | [src/fdai/core/operator/](../../../src/fdai/core/operator/) | (integration in delivery/operator_api) |
| runtime_settings | Allowlisted environment defaults plus revisioned, audited StateStore overrides | [src/fdai/delivery/runtime_settings.py](../../../src/fdai/delivery/runtime_settings.py) and [runtime_settings.py](../../../src/fdai/delivery/operator_api/routes/runtime_settings.py) | [test_runtime_settings.py](../../../tests/delivery/test_runtime_settings.py) and [test_runtime_settings.py](../../../tests/delivery/operator_api/test_runtime_settings.py) |
| console_request | Operator re-request policy for the write-direction console path (Scenario B deny-override) | [src/fdai/core/console_request/](../../../src/fdai/core/console_request/) | [tests/core/console_request/](../../../tests/core/console_request/) |
| notifications | Channel-routing layer over the matrix | [src/fdai/core/notifications/](../../../src/fdai/core/notifications/) | [tests/notifications/](../../../tests/notifications/) |
| report_feed | Rendered report subscriptions | [src/fdai/core/report_feed/](../../../src/fdai/core/report_feed/) | [tests/core/report_feed/](../../../tests/core/report_feed/) |
| reporting | Report composers + formatters | [src/fdai/core/reporting/](../../../src/fdai/core/reporting/) | [tests/core/reporting/](../../../tests/core/reporting/) |
| views | Workflow-matched ViewSpec -> bounded RenderedView plus deterministic inventory architecture projection | [src/fdai/core/views/](../../../src/fdai/core/views/) | [tests/core/views/](../../../tests/core/views/) and Operator API architecture-view tests |
| rbac | Human RBAC for the Operator API. Principal identities compare case-insensitively, so a requester cannot approve their own access request under another spelling. | [src/fdai/core/rbac/](../../../src/fdai/core/rbac/) | [tests/core/](../../../tests/core/) |
| human_assignment | Immutable role/duty intent, independent review, revisioned effects, shadow-first Entra apply, and restart-safe handover goals with fatigue budgets and evidence-only review | [src/fdai/core/human_assignment/](../../../src/fdai/core/human_assignment/), [human_assignments.py](../../../src/fdai/delivery/operator_api/routes/human_assignments.py), [handover_goals.py](../../../src/fdai/delivery/operator_api/routes/handover_goals.py), [identity/](../../../src/fdai/delivery/identity/), and [human_access.py](../../../src/fdai/runtime/human_access.py) | [tests/core/human_assignment/](../../../tests/core/human_assignment/), [test_human_assignments.py](../../../tests/delivery/operator_api/test_human_assignments.py), [test_handover_goals.py](../../../tests/delivery/operator_api/test_handover_goals.py), [tests/delivery/identity/](../../../tests/delivery/identity/), and [settings-iam-assignments.test.tsx](../../../console/src/routes/settings-iam-assignments.test.tsx) |
| stewardship | Human <-> agent handover map, authoritative structured assignment extraction, deterministic diff/notification, scheduled identity health, persisted idempotent draft-PR receipt, and signed merge audit | [src/fdai/core/stewardship/](../../../src/fdai/core/stewardship/) and [src/fdai/delivery/stewardship/](../../../src/fdai/delivery/stewardship/) | [tests/core/stewardship/](../../../tests/core/stewardship/) and [tests/delivery/stewardship/](../../../tests/delivery/stewardship/) |

The `conversation` owner-tool detail is causal, not a post-processing attachment. Bragi completes
the final T0/T1 owner route, runs one uniquely highest-scoring owned read, and uses that completed
result as the primary answer. A selected read failure hands off without generic or contributor
fallback. The delivery adapter never adds unrelated tool evidence to a completed answer.

Inventory scope-only follow-ups are isolated in
[`chat_inventory_followup.py`](../../../src/fdai/delivery/operator_api/routes/chat_inventory_followup.py).
The helper reuses only the latest user inventory intent, while `chat.py` and `chat_stream.py` apply
the same deterministic planning bypass and subscription-root provider scope.

Measured LLM usage and its server-owned analytical continuation live in [`chat_llm_usage.py`](../../../src/fdai/delivery/operator_api/routes/chat_llm_usage.py). The resolver reads `MeteringReader`, emits a bounded `analysis_context` only after terminal verification, and re-runs a period, grouping, or presentation refinement without trusting browser history.
Focused coverage lives in [`test_chat_llm_usage.py`](../../../tests/delivery/operator_api/test_chat_llm_usage.py).

Presentation intent is typed in
[`answer_plan.py`](../../../src/fdai/core/conversation/answer_plan.py). Explicit table and chart
formats and strict shape-only model selection in
[`presentation/`](../../../src/fdai/delivery/operator_api/projections/conversation/presentation/)
remain request-local read projections behind the explicit package facade and flow through terminal
verification into deterministic inventory rendering, while
`chat_evidence_enrichment.py` projects the verifier-accepted typed query and snapshot provenance
into a channel-neutral query activity row without fabricating provider commands.

## Rule catalog, deploy, and platform

| Subsystem | Responsibility | Source | Tests |
|-----------|----------------|--------|-------|
| rule_catalog_profiles | Profile / pack layer + `extends` overrides | [src/fdai/core/rule_catalog_profiles/](../../../src/fdai/core/rule_catalog_profiles/) | [tests/core/rule_catalog_profiles/](../../../tests/core/rule_catalog_profiles/) |
| deploy_preflight | Pre-deployment feasibility probes | [src/fdai/core/deploy_preflight/](../../../src/fdai/core/deploy_preflight/) | [tests/core/deploy_preflight/](../../../tests/core/deploy_preflight/) |
| onboarding | Tenant / environment onboarding flow | [src/fdai/core/onboarding/](../../../src/fdai/core/onboarding/) | [tests/core/](../../../tests/core/) |
| runtime_bootstrap | Process composition and long-running task orchestration, including durable T2 recovery receipts, legacy backfill, reconciliation, grounded chat visibility, and a StateStore-backed proposer route registry whose approved mutations and rollbacks remain owned by Thor and Vidar | [src/fdai/runtime/bootstrap.py](../../../src/fdai/runtime/bootstrap.py), [src/fdai/runtime/t2_recovery.py](../../../src/fdai/runtime/t2_recovery.py), [src/fdai/runtime/t2_route_registry.py](../../../src/fdai/runtime/t2_route_registry.py), and [src/fdai/runtime/bootstrap_lifecycle.py](../../../src/fdai/runtime/bootstrap_lifecycle.py) | [tests/runtime/test_bootstrap_config.py](../../../tests/runtime/test_bootstrap_config.py), [tests/runtime/test_t2_recovery.py](../../../tests/runtime/test_t2_recovery.py), and [tests/runtime/test_t2_route_registry.py](../../../tests/runtime/test_t2_route_registry.py) |
| readiness | Operational handoff, deterministic Best Practice checklists, startup probes with synthetic per-attempt correlation, agent-owned monitored-target readiness, and due-gated scheduled discovery repair with fail-closed reduction, evidence expiry, authority ceilings, and durable transitions ([design](../operations/startup-and-lifecycle.md)) | [src/fdai/core/readiness/](../../../src/fdai/core/readiness/), [src/fdai/runtime/readiness.py](../../../src/fdai/runtime/readiness.py), [src/fdai/delivery/startup_probe.py](../../../src/fdai/delivery/startup_probe.py), [src/fdai/delivery/analyzer_tick_cli.py](../../../src/fdai/delivery/analyzer_tick_cli.py), [src/fdai/delivery/inventory_sync_cli.py](../../../src/fdai/delivery/inventory_sync_cli.py), and [src/fdai/delivery/persistence/postgres_inventory_snapshot.py](../../../src/fdai/delivery/persistence/postgres_inventory_snapshot.py) | [tests/core/readiness/](../../../tests/core/readiness/), [tests/agents/test_detection_readiness.py](../../../tests/agents/test_detection_readiness.py), [tests/runtime/test_readiness.py](../../../tests/runtime/test_readiness.py), [tests/delivery/test_inventory_reconciliation_gate.py](../../../tests/delivery/test_inventory_reconciliation_gate.py), and [tests/delivery/test_analyzer_tick_cli.py](../../../tests/delivery/test_analyzer_tick_cli.py) |
| assurance_twin | Read-only ontology twin with scalar and graph active/challenger effect models, required active-trajectory invariants, durable StateStore trajectory episodes, independent off-path closure, challenger-only updates, and shadow audit (never executes or promotes) | [src/fdai/core/assurance_twin/](../../../src/fdai/core/assurance_twin/) | [tests/assurance_twin/](../../../tests/assurance_twin/) |
| architecture_review | Architecture-review manifest -> governed ontology projection | [src/fdai/core/architecture_review/](../../../src/fdai/core/architecture_review/) | [tests/core/architecture_review/](../../../tests/core/architecture_review/) |
| workflow | Compile and run version-pinned WorkflowDefinition records. Durable approval decisions bind the exact role, normalized principal, and attempt through revision CAS, survive projection interruption, heal sibling slot closure, hide expired slots, and feed the Process journal. Approval expiry outranks late quorum, timely quorum survives delayed resume, timeout is terminal only when its latest-revision CAS wins, and terminal approval states are monotonic. `workflow_resume.py` reconstructs audit-safe inputs. `workflow_cancellation.py` stops only at safe boundaries and hands applied work to compensation. `workflow_retry.py` admits allowlisted effect-free `failed` attempts and admits `timed_out` only for terminal approval timeout, all under a server cap. Action proposal and Process step identities include a positive attempt so separate attempts cannot deduplicate each other. A contextual guard resolves reviewed ChangeWindow evidence for the exact target and time. Enforce action steps wait for independently verified outcome receipts; partial failure records intent and original params before reverse typed compensation. Recovery-incomplete closure writes a durable target hold. The RiskGate denies ordinary actions and permits only exact Process-bound compensation through human approval; all verified compensation receipts and a CAS hold release are required before `compensated`. | [src/fdai/core/workflow/](../../../src/fdai/core/workflow/) | [tests/core/workflow/](../../../tests/core/workflow/) |
| scheduler | Create/pause/resume/edit/run-now/cancel lifecycle, cron dispatch, run history, blueprints including inert configuration-review handoff, and scoped continuations with idempotent lifecycle audit and CAS winner-only expiry audit ([design](../interfaces/scheduled-result-continuations.md)) | [src/fdai/core/scheduler/](../../../src/fdai/core/scheduler/) | [tests/core/scheduler/](../../../tests/core/scheduler/) |
| metering | Usage metering counters and the shared model budget every LLM path is measured against, charged at the single point where an invocation is recorded; totals survive ledger eviction, per-correlation limbs do not, and a failed metering write still charges; the gate is an atomic reservation that validates exact prospective call and microUSD increments, not a read-then-write; the ledger accounts in microUSD and leaves a foreign-currency price uncharged | [src/fdai/core/metering/](../../../src/fdai/core/metering/) | [tests/core/metering/](../../../tests/core/metering/) |
| measurement | MTTR, DORA, pattern growth, Dynamic challenger learning, and audited immutable operational-promotion receipts. Live-only observation windows and Wilson confidence prevent clock or small-sample promotion | [src/fdai/core/measurement/](../../../src/fdai/core/measurement/) | [tests/core/measurement/](../../../tests/core/measurement/) |
| mscp_profile | Level-neutral `mscp-operational-v1` provenance, pure effect/cycle/integrity checks, and optional ControlLoop shadow observation ([design](mscp-operational-profile.md)) | [src/fdai/core/mscp_profile/](../../../src/fdai/core/mscp_profile/) | [tests/core/mscp_profile/](../../../tests/core/mscp_profile/) |
| security | Security-signal producers | [src/fdai/core/security/](../../../src/fdai/core/security/) | [tests/core/security/](../../../tests/core/security/) |
| platform | Platform-primitive facade | [src/fdai/core/platform/](../../../src/fdai/core/platform/) | [tests/core/](../../../tests/core/) |
| verticals | Resilience / Change Safety / Cost, including immutable control-plane recovery plans, record codec, epoch-fenced reducer, and durable CAS coordinator with action-bound approval verification ([design](../deployment/control-plane-disaster-recovery.md)) | [src/fdai/core/verticals/](../../../src/fdai/core/verticals/) | [tests/core/verticals/](../../../tests/core/verticals/) |

## Agent pantheon

The 15 named agents. Every file lives flat under `src/fdai/agents/`;
framework helpers live under `_framework/`. See
[.github/instructions/agent-pantheon.instructions.md](../../../.github/instructions/agent-pantheon.instructions.md)
for the fork-locked role bindings and change contract.

Conversation charter text lives in `_framework/charters.py`; `_framework/pantheon.py` binds each
agent and `AgentSpec` inserts the exact role and budget contract. Per-turn composition lives in
`_framework/conversation_prompt.py`. Bounded T1/T2 discussion contracts live in
`_framework/deliberation.py` and are orchestrated by Bragi through `PantheonRuntime.deliberate`.
See [conversational-deliberation.md](../agents/conversational-deliberation.md).
Bounded cost, capacity, and chaos trigger parsing lives in `_framework/specialist_ingress.py`;
domain agents consume those canonical Events before publishing their owned advisory topics.

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
| trajectory | Deterministic streaming exporter, PostgreSQL metadata/quarantine store, Owner-only read projection, and offline CLI | [src/fdai/delivery/trajectory/](../../../src/fdai/delivery/trajectory/), [postgres_trajectory.py](../../../src/fdai/delivery/persistence/postgres_trajectory.py), [trajectory_datasets.py](../../../src/fdai/delivery/operator_api/routes/trajectory_datasets.py), [deployment_cli/trajectory.py](../../../src/fdai/deployment_cli/trajectory.py) |
| case_history | StateStore CAS metadata plus managed-identity Azure Blob artifacts | [state_store_case_history.py](../../../src/fdai/delivery/persistence/state_store_case_history.py), [case_history_artifacts.py](../../../src/fdai/delivery/azure/case_history_artifacts.py), and [runtime/case_history.py](../../../src/fdai/runtime/case_history.py) |
| azure_devops | Azure DevOps PR / pipeline gate | [src/fdai/delivery/azure_devops/](../../../src/fdai/delivery/azure_devops/) |
| github | GitHub App / Checks API | [src/fdai/delivery/github/](../../../src/fdai/delivery/github/) |
| gitops_pr | PR-native remediation packager | [src/fdai/delivery/gitops_pr/](../../../src/fdai/delivery/gitops_pr/) |
| chatops | Teams / Slack Adaptive Cards | [src/fdai/delivery/chatops/](../../../src/fdai/delivery/chatops/) |
| notifications | Channel dispatch plus PagerDuty/ServiceNow incident lifecycle and PagerDuty roster adapters | [notifications/](../../../src/fdai/delivery/notifications/), [incident_platform/](../../../src/fdai/delivery/incident_platform/) |
| operator_api | Console read-only HTTP surface; production optional-service builders plus route-owned chat request, cursor-paged conversation summaries, principal-scoped complete-history and knowledge-context assembly, bounded terminal timing, trajectory-detail replay, application-owned terminal verification, background, busy-input, skill, and read-investigation helpers | [src/fdai/delivery/operator_api/](../../../src/fdai/delivery/operator_api/), [application/conversation/verification/](../../../src/fdai/delivery/operator_api/application/conversation/verification/), [user_context_conversations.py](../../../src/fdai/delivery/operator_api/routes/user_context_conversations.py), [production/knowledge_context.py](../../../src/fdai/delivery/operator_api/production/knowledge_context.py), [production/python_tasks.py](../../../src/fdai/delivery/operator_api/production/python_tasks.py), [chat_history_context.py](../../../src/fdai/delivery/operator_api/routes/chat_history_context.py), [chat_knowledge_context.py](../../../src/fdai/delivery/operator_api/routes/chat_knowledge_context.py), [chat_stream_request.py](../../../src/fdai/delivery/operator_api/routes/chat_stream_request.py), [chat_stream_setup.py](../../../src/fdai/delivery/operator_api/routes/chat_stream_setup.py), [chat_stream_terminal.py](../../../src/fdai/delivery/operator_api/routes/chat_stream_terminal.py), [chat_trajectory_detail.py](../../../src/fdai/delivery/operator_api/routes/chat_trajectory_detail.py), [chat_vision_prompt.py](../../../src/fdai/delivery/operator_api/routes/chat_vision_prompt.py), [read_investigation_payload.py](../../../src/fdai/delivery/operator_api/routes/read_investigation_payload.py), and [read_investigation_execution.py](../../../src/fdai/delivery/operator_api/routes/read_investigation_execution.py) |
| provisioning | Terraform / IaC apply driver | [src/fdai/delivery/provisioning/](../../../src/fdai/delivery/provisioning/) |
| persistence | Postgres + pgvector stores, including focused background-task completion/serialization and read-investigation run serialization modules alongside durable delivery, execution, metering, projection, and receipt stores | [src/fdai/delivery/persistence/](../../../src/fdai/delivery/persistence/), [postgres_background_task_completion.py](../../../src/fdai/delivery/persistence/postgres_background_task_completion.py), [postgres_background_task_serialization.py](../../../src/fdai/delivery/persistence/postgres_background_task_serialization.py), and [postgres_read_investigation_run_serialization.py](../../../src/fdai/delivery/persistence/postgres_read_investigation_run_serialization.py) |
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
| contracts | Cross-package Pydantic contracts, including ObjectType lifecycle criteria and shared structured stop-condition value objects used by ActionType declarations and runtime Actions | [src/fdai/shared/contracts/](../../../src/fdai/shared/contracts/) |
| ontology | Domain ontology (ObjectType / LinkType / ActionType) | [src/fdai/shared/ontology/](../../../src/fdai/shared/ontology/) |
| providers | Provider Protocols including `ExecutionBackend`, non-cached ephemeral typed-command output with bounded diagnostic receipts, strictly decoded, count-, character-, and secret-scanned durable channel-neutral handoff/execution activities, a process-local EventBus with serialized same-group leases and independent group progress, bounded SSE, isolated programmatic pipeline runners, [access-scoped conversation search](../interfaces/conversation-search.md), and [structured behavior knowledge](../interfaces/behavior-knowledge.md) | [src/fdai/shared/providers/](../../../src/fdai/shared/providers/) |
| config | Config loader, schema, and shared runtime activation flags | [src/fdai/shared/config/](../../../src/fdai/shared/config/) |
| streaming | Kafka / Event Hub abstraction | [src/fdai/shared/streaming/](../../../src/fdai/shared/streaming/) |
| resilience | Retry / circuit-breaker helpers | [src/fdai/shared/resilience/](../../../src/fdai/shared/resilience/) |
| telemetry | Structured logging + metrics helpers | [src/fdai/shared/telemetry/](../../../src/fdai/shared/telemetry/) |

## Benchmark integration

| Path | Purpose |
|------|---------|
| [evaluation-sdk/](../../../evaluation-sdk/) | Independently packageable neutral contracts, public Protocols, workspace values, and bounded runner. |
| [src/fdai/evaluation/](../../../src/fdai/evaluation/) | Public host implementation, capability attenuation, artifact custody, workspace policy, typed ingress, pre-judgment evidence observation, and result receipts. |
| [src/fdai/core/ontology_platform/](../../../src/fdai/core/ontology_platform/) | Frozen diagnostic-ledger validation, 61-mechanism catalog projection, 427 immutable validation receipts, and content-addressed finding evidence. |
| [src/fdai/delivery/kubernetes/](../../../src/fdai/delivery/kubernetes/) | Shared Kubernetes reducers, 22 exact-release ontology functions, and cluster-scoped UID topology projection. |
| [src/fdai/delivery/evaluation/](../../../src/fdai/delivery/evaluation/) | Registry-backed evidence providers and receipt-verified Kubernetes ontology observation before judgment. |
| [src/fdai/benchmarking/](../../../src/fdai/benchmarking/) | Temporary `0.1.x` compatibility facade for legacy benchmark callers. |
| [benchmarks/](../../../benchmarks/) | Independently packaged SREGym and CyberGym drivers; see the [benchmark adapter design](../interfaces/benchmark-adapters.md). |

## Optional extension packages

| Path | Purpose |
|------|---------|
| [extensions/code-assurance/](../../../extensions/code-assurance/) | Independent shadow-first wheel with bounded read-only GitHub pull-request code/security review, self-contained capability bindings, and governed skill assets. |

## Composition and catalog

| Path | Purpose |
|------|---------|
| [src/fdai/composition/\_\_init\_\_.py](../../../src/fdai/composition/__init__.py) | Facade + `default_container` + `default_container_from_env`. |
| [src/fdai/composition/_helpers.py](../../../src/fdai/composition/_helpers.py) | `Container`, `LlmBindings` including optional conversation T2 synthesis bound together with the metering, pricing, and model key its spend is charged against, `LlmBindingsUnavailableError`. |
| [src/fdai/composition/wire_llm.py](../../../src/fdai/composition/wire_llm.py) | Azure OpenAI LLM binder (composition-time model resolution). |
| [src/fdai/composition/wire_distiller.py](../../../src/fdai/composition/wire_distiller.py) | Atomically validates and binds the exact-version, three-family ontology extraction council to `Container.distiller`; zero council records preserve abstention and partial records fail startup. |
| [src/fdai/composition/wire_capabilities.py](../../../src/fdai/composition/wire_capabilities.py) | Installs validated capability bundles and binds the server-pinned, read-only configuration drift capability. Callers use the `fdai.composition` facade. |
| [src/fdai/composition/wire_azure.py](../../../src/fdai/composition/wire_azure.py) | Fork-wire container + `AzureWireOverrides`. |
| [src/fdai/composition/wire_change_feed.py](../../../src/fdai/composition/wire_change_feed.py) | Change-feed factory wiring (Azure DevOps / GitHub change producers). |
| [src/fdai/composition/wire_metric_provider.py](../../../src/fdai/composition/wire_metric_provider.py) | `MetricProvider` binder (Azure Monitor Logs auto-bind when `FDAI_MONITOR_WORKSPACE_ID` is set); split out of `wire_azure` to hold the LOC ceiling (G-4). |
| [src/fdai/composition/wire_trajectory.py](../../../src/fdai/composition/wire_trajectory.py) | Binds authorization-first source joins, dataset metadata, quarantine export, and read-only administration without enabling the feature in the default container. |
| [src/fdai/composition/wire_execution_backends.py](../../../src/fdai/composition/wire_execution_backends.py) | Validates server-selected profiles and binds required backends plus the durable ledger without enabling profiles by default. |
| [src/fdai/rule_catalog/](../../../src/fdai/rule_catalog/) | Strict loaders for rules, Best Practices, governance artifacts, promoted Rule semantic surfaces, held-out retrieval evidence, and the remaining `rule-catalog/` YAML tree. |
| [src/fdai/delivery/catalog_search/](../../../src/fdai/delivery/catalog_search/) | Deterministic Rule manifests, concept-first `catalog.search_rules`, atomic in-memory/PostgreSQL generations, OPA-free API reference loading, and safe lexical degradation. |
| [src/fdai/rule_catalog/pipeline/distill/](../../../src/fdai/rule_catalog/pipeline/distill/) | Build-time manual compilation plus the `DocumentEnvelope` provenance bridge, normalized cross-format graph comparison, review-only ontology proposals, partition release gates, provider conformance, and lifecycle/evaluation plans; local parser resource ceilings live in `shared/providers/local/document_limits.py`, and the content-free pinned corpus manifest drives `scripts/evaluation/document_ontology_public_corpus.py`. |
| [rule-catalog/](../../../rule-catalog/) | The rule, Best Practice, policy, rule-set, and action-type catalog (data). |

## Developer entry points and slash commands

The repo ships a small set of scripts and Copilot slash commands to keep
local development, verification, and session hand-off consistent.

| Path | Purpose |
|------|---------|
| [scripts/verify.sh](../../../scripts/verify.sh) | Single local gate: fast text/lint and clean-checkout contracts by default; `--full <path>` runs focused pytest, while explicit `--all` adds whole-repository coverage plus console and CLI verification. |
| [check-readable-hangul.py](../../../scripts/quality/localization/check-readable-hangul.py) | Rejects opaque Hangul escapes in source, offers a mechanical UTF-8 fixer, and permits only exact rationale-bearing code-point exceptions. |
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
