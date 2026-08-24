---
title: Multi-Service Repository Layout
---
# Multi-Service Repository Layout

FDAI uses one development repository containing five independently packaged and deployed backend
services plus a shared service-contract SDK. The root coordinates tooling and integration tests;
it is not a monolithic runtime distribution, and no service imports another service's
implementation.

## Packaging contract

| Surface | Ownership contract |
|---------|--------------------|
| Five backend services | Each `services/*` root owns its `pyproject.toml`, source package, tests, image, process identity, and service migration branch. |
| Shared service contracts | `packages/service-contracts/` owns versioned wire types and schemas without importing a service implementation. |
| Repository root | Root `pyproject.toml` and `uv.lock` coordinate development tooling and cross-service integration; they do not publish an FDAI runtime distribution. |
| Service communication | Services exchange versioned contracts over PostgreSQL-owned projections and the event bus. One service never imports another service's implementation package. |

## Multi-Service Repository Layout

```text
fdai/
├── services/core-control-plane/src/fdai/            # Python (3.12+, src-layout); one independently packaged backend service
│   ├── core/                  # headless control plane (no UI, no direct cloud SDK imports). Domain-group facades cover `pipeline/`, `incident/`, `operator/`, `knowledge/`, `platform/`, and `verticals/`; both direct subsystem and grouped imports remain compatible.
│   │   ├── event_ingest/       # bus consumers; normalize to event schema; dedup by idempotency key; correlate related events into incidents
│   │   ├── trust_router/       # routes each event to T0 | T1 | T2 by computed confidence
│   │   ├── tiers/
│   │   │   ├── t0_deterministic/    # deterministic-engine: policy, checklist, what-if, drift eval
│   │   │   ├── t1_lightweight/      # embedding similarity and learned-action reuse; operational cases require persisted immutable context plus fresh graph, owner, policy, dry-run, and safety evidence
│   │   │   └── t2_reasoning/        # frontier-model reasoning plus budgeted proposer failover, durable route selection, sanitized attempt receipts, and an optional self-consistency cascade whose measured stability can only preserve or lower the tier outcome
│   │   ├── prompts/            # catalog-as-code prompt composer (loads `rule-catalog/prompts/`, supplies T2)
│   │   ├── tools/              # T2 tool-catalog registry + `ToolExecutor` (shadow-mode gated)
│   │   ├── web_search/         # last-resort web-search seam (`NoOpWebSearchProvider` default; domain allowlist + sanitizer)
│   │   ├── browser_evidence/   # read-only origin/DNS policy, redaction, immutable artifacts, custody, and shadow comparison
│   │   ├── operator_memory/    # HIL-approved operator memory injected as untrusted `<operator_note>` data; the second-approval step is bounded in time and replay-safe (entry id and recorded approver share one canonical form, so a redelivery refuses instead of duplicating and expiry is terminal)
│   │   ├── learning/           # consent-gated off-path turn eligibility, consensus, dedup ledger, and inert proposal routing
│   │   ├── conversation_assurance/ # deterministic-first completed-turn scoring, exact failure attribution, hold-first ontology adequacy review, mixed-family review, scoped disputes, subscription learning, chat-policy promotion/rollback, and the versioned 50-item hard-cap quality scorecard
│   │   ├── trajectory/         # authorization-first observable trajectory projection, reviewed aggregate, offline validation, and provider-neutral retention claim coordination
│   │   ├── case_history/       # canonical revisions, strict operational receipts, artifact-first intake, scoped retrieval, backfill, and retention
│   │   ├── task_worker/        # isolated depth-one read-only workers: capability attenuation, lifecycle, durable state, and parent synthesis
│   │   ├── background_task/    # durable detached reads: lease/CAS, atomic completion outbox, replay-idempotent handoff, bounded retry, process-loss, and retention purge
│   │   ├── read_investigation/ # exact-resource VM/network planning, evidence, immutable provider-vs-graph shadow comparison and its deterministic cross-source conflict adjudication, latency policy, owner-scoped direct/stream replay, honest cost usage, SSE heartbeats, and stream-close cancellation; no cloud SDK or execution authority
│   │   ├── briefing/           # deterministic opening/scheduled briefings over report-feed evidence
│   │   ├── scheduler/          # create/pause/resume/edit/run-now/cancel lifecycle, cron dispatch, run history, blueprints, and scoped continuations
│   │   ├── document_ingestion/ # upload lifecycle + split inspect/index worker; Forseti/Saga/Var/Muninn gates, durable stage lease/CAS claims, and replay-only gated-state recovery
│   │   ├── working_context/    # bounded per-turn prompt assembly: immutable selection policy + mandatory validator + shadow evidence/replay + planner/orchestrator folds + summarizer/retriever seams
│   │   ├── operational_context/ # atomic owned-subgraph replacement, time-consistent snapshots, and cutoff-bound graph+document evidence bundles with typed paths, provenance, source-freshness receipts, and fail-closed truncation
│   │   ├── decision_case/      # protected-objective options, deterministic selection, and response closure
│   │   ├── change_lineage/     # immutable replay-stable Change -> assessment -> decision -> action -> outcome join; no execution or promotion authority
│   │   ├── operational_planning/ # hard-constraint eligibility, Pareto pruning, Process planning phases, replay-stable plan identity, and exact kinetic proposal contracts; no execution authority
│   │   ├── operational_learning/ # sealed-case classification, fingerprint/action cohort gates, immutable citations, and inert candidate mappings
│   │   ├── rule_semantic_generation/ # agent-facing build/validation handler Protocols plus exact activation, durable closure, and publication; no execution authority
│   │   ├── quality_gate/       # mixed-model cross-check, verifier, grounding, and receipt-gated rubric mode; failed fan-out cancels and drains siblings (guards T2)
│   │   ├── rca/                # root-cause analysis (T0 deterministic + T2 reasoner behind seam; grounding-gated)
│   │   ├── risk_gate/          # unified authority: risk score + auto vs HIL vs deny; rejects malformed promotion metrics, enforces the seven safeguards, resolves the Axis-E live probe from a recorded catalog-probe-id reading, and audits the feature vector, catalog version, and remaining ceiling inputs for self-contained replay
│   │   ├── execution_authorization/ # ontology-driven pre-dispatch capability policy, grant lifecycle, and replay-stable decisions
│   │   ├── rbac/               # human RBAC for the Operator API (5-role matrix, resolver, enforcer)
│   │   ├── human_assignment/   # immutable role/duty intent, normalized review quorum, revisioned StateStore lifecycle, and effect receipts
│   │   ├── hil_resume/         # HIL park/resume, no-drop grouping, bounded reminders, and CAS-owned shadow non-response supervision
│   │   ├── executor/           # logical-target lock, idempotency, dry-run receipt, pre-effect/terminal audit, delivery adapters
│   │   ├── execution_backend/  # profile intersection, durable lifecycle coordination, and shadow probes; no judgment authority
│   │   ├── audit/              # append-only, hash-chained audit log + KPI/metric emission
│   │   ├── notifications/      # channel-routing layer over the notifications matrix
│   │   ├── detection/          # anomaly/forecast evaluation, immutable episodes, event-time closure, and outbox contracts
│   │   ├── incident/           # lifecycle + 32-key/1024-char identities, audit-backed ontology projection, evidence, severity, and notices
│   │   ├── slo/                # workload SLO / burn-rate evaluator (distinct from control-plane SLOs)
│   │   ├── runbook/            # runbook orchestrator (linear sequence + failure-only forward-only on-failure branch)
│   │   ├── workflow/           # version-pinned WorkflowDefinition + principal WorkflowBinding compilation; approval planner + shadow orchestrator + trigger index + event coordinator
│   │   ├── python_task/         # static validation for generated multi-file PythonTask artifacts and reviewed programmatic pipelines; never imports or executes task code
│   │   ├── programmatic_pipeline/ # capability-scoped read-only tool loops: immutable contracts, broker, receipts, compact result, and deterministic benchmark
│   │   ├── postmortem/         # LLM-optional postmortem / PIR draft generator
│   │   ├── rule_catalog_profiles/  # profile / pack layer - named rule bundles with `extends` chains + overrides
│   │   ├── measurement/        # Continuous measurement plus immutable revision/scenario operational-promotion receipts with confidence and guard gates
│   │   ├── mscp_profile/       # pure mscp-operational-v1 provenance, effect verification, cycle guard, runtime-integrity policies, and a never-raising authority ceiling; no execution authority
│   │   ├── deploy_preflight/   # pre-deployment feasibility probes → grounded readiness report
│   │   ├── readiness/          # operational handoff + startup, monitored-target, and rule-discovery activation contracts; fail-closed reducers, evidence expiry, and authority ceilings
│   │   ├── assurance_twin/     # read-only ontology twin: text-to-query, scalar/graph active-challenger models, required invariants, durable trajectory episodes, deterministic simulation, and off-path outcome closure (never executes or promotes)
│   │   ├── ontology_platform/   # exact releases, release-aware direction-shadow comparison, semantic interfaces, bounded object sets, secured purpose/ACL query receipts, incident audit evidence, shared exact-number property semantics, cluster-scoped network/Pod telemetry verification, immutable diagnostic ledger/result projection, mutation plans, typed functions, authenticated reconciliation with proposal-only terminal outbox, and proposal-only SDK generation
│   │   ├── conversation/       # Bragi-owned model-free screen T0 plus schema-constrained whole-turn semantic frame/query-plan shadowing, principal-manifest verification, intent-graph evidence projection, compatibility intent/tool coordination, grounded narration, per-turn isolation, durable delivery, and busy-input arbitration
│   │   ├── user_context_projection.py  # metadata-only principal context / workflow binding projection into runtime ontology
│   │   ├── console_request/    # operator-console write-direction re-request policy (Scenario B deny-override), a single pure `evaluate_operator_rerequest`
│   │   ├── verticals/          # Resilience / Change Safety / Cost Governance (P3 integration surface); Resilience includes the control-plane recovery plan, record codec, epoch-fenced reducer, and durable CAS coordinator; each vertical is a sub-package (G-6) with its own orchestrator + submodules, plus the shared `Vertical` Protocol in `base.py` and the `VerticalRegistry` seam
│   │   ├── control_loop/       # P1 pipeline: `orchestrator.py` (ControlLoop composition plus exact property-semantics injection), `_process.py` (ordered event stages), `_fallback.py` (T1/T2), `_execution.py` (governance/risk/dispatch), `_rca.py` (shadow RCA), `_boundary.py` (audit/notification/stage adapters), `models.py` (typed results), `operator_request.py` (authoritative proposal lifecycle), `_helpers.py` (pure utilities), and `stages/` (Stage Protocol scaffold); semantic metadata never raises authority
│   │   └── ontology_explorer.py    # deterministic Mermaid renderer for the loaded ObjectType / LinkType catalog
│   ├── shared/                # cross-cutting; MUST NOT import from core/
│   │   ├── contracts/          # per-domain models + shared safety values + versioned isolated-Executor command/receipt schemas + registry.py + validation.py
│   │   │   ├── event/          # event/schema.json
│   │   │   ├── action/         # action/schema.json
│   │   │   ├── response-outcome/ # expected-versus-observed action-effect outcome
│   │   │   ├── rule/           # rule/schema.json
│   │   │   ├── ontology/       # object/link/action schemas; ObjectType may declare lifecycle criteria + provenance
│   │   │   └── workflow/       # workflow/schema.json (process-automation catalog)
│   │   ├── ontology/           # runtime ontology helpers (ACL, audit purposes, purpose taxonomy)
│   │   ├── providers/          # CSP-neutral cloud provider interfaces, including OperatingModelProvider, backward-compatible Distiller conformance, and action-bound control-plane recovery approval verification (adapters implement them)
│   │   │                       #   event_bus.py, secret_provider.py, state_store.py, execution_backend.py,
│   │   │                       #   workload_identity.py, inventory.py, log_query.py, trace_query.py, incident_platform.py, behavior_knowledge.py, programmatic_pipeline.py + LLM / channel / RBAC seams
│   │   │                       # `providers/local/` = process-local transport adapters plus bounded document format adapters (`document_limits.py` immutable ceilings, `document_text.py` for Markdown/SGML, `document_structure.py` for OOXML, `document_pdf.py` for pypdf/OCR) and explicit offline helpers;
│   │   │                       # `providers/testing/` = in-memory fakes used across the test suite (never bound in prod)
│   │   ├── streaming/          # `SseBroadcaster` + `StagePublisher`: relay EventBus topics → SSE channels
│   │   ├── telemetry/          # structured logging, tracing, metric helpers
│   │   └── config/             # config schema + startup validation (fail-fast)
│   ├── delivery/              # action delivery adapters (behind one shared interface)
│   │   ├── agent_introspection_bus.py # bounded cross-process Bragi request/reply over the shared EventBus; no executor identity
│   │   ├── gitops_pr/          # remediation-pr adapter: GitHub App / Azure DevOps, Checks API
│   │   ├── channels/           # pure Teams/Slack presentation plus authenticated bounded A3 transports; no executor identity
│   │   ├── chatops/            # channel adapters (Teams / Slack / email / webhook / pager / SMS)
│   │   ├── notifications/      # per-channel senders; sibling `incident_platform/` provides PagerDuty/ServiceNow lifecycle and PagerDuty roster adapters
│   │   ├── persistence/        # Postgres / pgvector stores, including forecast episodes/outbox, relational case-history backfill, and atomic background-task completion audit markers
│   │   ├── operating_model/    # bounded JSON deployment operating-model adapter; startup-only and all-before-write
│   │   ├── runtime_settings.py  # allowlisted env defaults + revisioned StateStore overrides; no executor identity or promotion authority
│   │   ├── behavior_knowledge/ # in-memory hybrid behavior index, tracked-source freshness, and built-in behavior seeds
│   │   ├── catalog_search/     # candidate-only concrete semantic index; full/incremental Rule, ontology declaration, and eligible deployment-object generations; immutable staged-generation validation snapshots, independent validation, atomic activation, stale detection, and rollback; durable pgvector binding remains delivery work
│   │   ├── pgvector/           # persistent document and behavior vector indexes
│   │   ├── azure/              # Azure-specific adapters, including bounded logs/metrics/App Insights traces and strict operational-learning evidence over promoted inventory
│   │   │                       #   `case_history_artifacts.py` stores content-addressed case revisions in private Blob through workload identity
│   │   │                       #   `vm_task.py` uses Managed Run Command; `container_apps_job_backend.py` starts pinned Job templates; `llm/python_task_author.py` generates inert drafts
│   │   ├── vm_task/            # planning-only read adapter + ontology ToolExecutor bridge; no cloud SDK imports
│   │   ├── execution_backend/  # bubblewrap and VM-task lifecycle adapters over existing sandbox authority
│   │   ├── programmatic_pipeline/ # local isolated child runner; Azure strict submission adapter remains under delivery/azure
│   │   ├── browser/             # optional isolated async Playwright evidence capture; GET/HEAD only, no page handle
│   │   ├── trajectory/         # deterministic JSONL streaming export with quarantine and atomic partial-file cleanup
│   │   ├── kubernetes/         # shared operational Kubernetes semantics: exact quantities, cluster-scoped topology, UID-grounded owners, exact-release diagnostic functions, and hold-only findings
│   │   ├── chaos/              # live chaos-inject adapters when a `Chaos` runbook step goes enforce: `live_injectors.py` (CSP-neutral primitive fan-out) + `chaos_mesh.py` (Chaos Mesh CRDs) + `mysql_load.py` (MySQL benchmark load)
│   │   ├── remediation/        # concrete `DirectApiExecutor` for direct-API remediation (`live_direct_api.py`); the Protocol lives in `shared/providers/`
│   │   ├── operator_api/           # thin ASGI - `main.py` composes route modules, including principal-scoped complete-history and read-only knowledge-context assembly plus Owner-only observation assignment cases beside IAM. GET routes project bounded state; POST commands submit governed records or typed proposals and never call a privileged executor or human-access provisioner directly
│   │   ├── ingestion_gateway/  # independent public upload API + internal durable worker process; scoped refs, deletion, and optional handover governance
│   │   ├── provisioning/       # surface-A Genesis bootstrap: pure `terraform_bridge.py` (terraform `-json` → `provision.*`) + `serve.py` harness (`aiter_json_lines` + `pump_provision_events`, I/O injected, no subprocess)
│   │   └── scheduler_tick_cli.py  # standalone entry point that drives the scheduler tick from a cron / Container Apps Job
│   ├── rule_catalog/          # rule-catalog PIPELINE code
│   │   ├── schema/             # rule, Best Practice, governance, ontology, and semantic retrieval schemas + validation
│   │   ├── sources/            # per-source collectors (WAF, CIS, OPA, IaC scanners, ...)
│   │   ├── pipeline/           # watch -> collect -> shadow/regression; distill adds the DocumentEnvelope provenance bridge, cross-format equivalence, and review-only ontology gates
│   │   └── codegen/            # authoring helpers (`new_action_type`, `new_object_type`) - generate scaffolds, never mutate the live catalog
│   ├── agents/                # pantheon runtime - 15 named agents, typed topics, optional exact-proposal Verdict binding, v2 conversation charters, and bounded T1/T2 deliberation; see [agent-pantheon.md](../agents/agent-pantheon.md)
│   ├── composition/           # composition root package (G-3, tracker #14): `__init__.py` facade + `_helpers.py` Container/LlmBindings + `resolved_models.py` artifact loading/capability helpers + focused `wire_*` binders, including exact-release semantic query assembly with request-role executors and `wire_context_selection.py` for the bounded context-selection shadow runner that owns its durable comparison store
│   ├── runtime/               # headless lifecycle and composition, including reviewed alias-free metric-semantic catalog loading, exact Rule generation document snapshots and replay-identical reconciliation, versioned isolated Executor shadow/effect handling, stable-offset remote client, EventBus/DLQ/health supervision, production entry point, reversible authority probe, operating-model and diagnostic-catalog startup projection/status, durable T2 recovery observation/backfill, StateStore-backed proposer route selection with Thor/Vidar execution and rollback, semantic runtime availability/readiness binding with deadline-bounded durable projection replay, transport/identity bindings, startup readiness, worker gating, and post-turn review wiring into Norns
│   └── __main__.py            # entry point (starts the P1 control loop)
├── services/core-control-plane/{src/fdai_core_service,tests}/ # Core entry point and tests
├── services/{operator-service,document-ingestion-api,document-processing-worker,isolated-executor}/ and packages/service-contracts/ # independent packages, shared SDK, tests, type-stable semantic JSONB persistence, and process-owned semantic bridge health that does not depend on a projection row
├── evaluation-sdk/            # dormant independently packageable evaluation contracts and runner; preserved outside FDAI runtime dependencies
├── benchmarks/                # dormant external-harness driver packages plus an independent explicit CyberGym shadow runner
├── eval/golden-dataset/       # active bilingual semantic regression corpus and ontology traversal oracle; campaign binding remains open
├── extensions/                # independently packaged optional capabilities; not included in the FDAI wheel
│   └── code-assurance/         # read-only bounded GitHub PR code/security review + governed skill assets
├── rule-catalog/              # catalog-as-code DATA (YAML) - no Python; pipeline lives in services/core-control-plane/src/fdai/rule_catalog/
│   ├── schema/                 # JSON Schema definitions (data)
│   ├── vocabulary/             # canonical CSP-neutral vocabularies: resource-types.yaml, object-types/, link-types/, interface-types/, interface-implementations/
│   ├── action-types/           # upstream ontology ActionType instances (shadow-default, promotion_gate-required)
│   ├── action-types-custom/    # fork-only ActionType additions (deny-listed in upstream CI)
│   ├── action-types-overrides/ # scoped overrides to upstream ActionTypes (≤ resource-group scope)
│   ├── profiles/               # named rule packs (upstream)
│   ├── profiles-overrides/     # fork overlay for profiles
│   ├── best-practices/         # framework checklist controls with typed evidence requirements
│   ├── rule-sets/              # version-pinned governance initiatives for atomic rules
│   ├── prompts/                # catalog-as-code prompt fragments (task packs, tools, personas)
│   ├── remediation/            # remediation-plan artifacts
│   ├── operator-console/       # `SystemConsoleTool` descriptor bundles
│   ├── probes/                 # deploy-preflight feasibility-probe descriptors
│   ├── catalog/                # normalized rules (post-promotion, catalog-of-record)
│   ├── collected/              # raw upstream source snapshots pre-normalization
│   ├── exemptions/             # time-boxed audited exemption artifacts
│   ├── sources/                # per-source rule snapshots + provenance
│   ├── llm-registry.yaml       # per-capability LLM binding registry (data, resolved at composition time)
│   └── risk-classification.yaml # authoritative first-match risk-classification table (see risk-classification.md)
├── policies/                  # OPA/Rego policy-as-code consumed by T0 and the verifier
├── infra/                     # IaC: Terraform (HCL); entry command `terraform apply`
│   ├── modules/
│   │   ├── resource-group/          # rg-fdai; CAF-named per deploy-and-onboard.md
│   │   ├── identity/                # user-assigned Managed Identity for the executor
│   │   ├── compute/                 # runtime seam - alternates in siblings
│   │   │   └── container-apps/      # default (Consumption + KEDA)
│   │   ├── isolated-executor/       # opt-in internal shadow Container App; dedicated transport identity, no effect roles
│   │   ├── container-registry/      # ACR for the compute image
│   │   ├── state-store/             # audit + KPI + pgvector
│   │   │   └── postgres-flex/       # default
│   │   ├── event-bus/               # Kafka wire
│   │   │   └── event-hubs-kafka/    # default (Event Hubs, :9093)
│   │   ├── secret-store/            # env + Key Vault reference bridge
│   │   │   └── key-vault/           # default
│   │   ├── observability/           # Log Analytics + App Insights bound to it
│   │   │   └── log-analytics/       # default
│   │   ├── llm/                     # deployer-scoped LLM provisioning (dev-and-deploy parity contract)
│   │   │   └── azure-openai/        # default Azure OpenAI deployment set
│   │   ├── measurement-runners/     # Container Apps Jobs for automated regression + pattern-growth runners
│   │   ├── vm-task-host/             # cloud-init profile for custom Linux/GPU VMs
│   │   ├── vm-task-rbac/             # target-VM-scoped Managed Run Command RBAC
│   │   ├── preflight-toggles/       # feature-flag surface mapping preflight blockers → Terraform toggles
│   │   └── console/                 # Static Web App hosting for the read-only SPA
│   │       └── static-web-app/      # default
│   ├── local/                       # local-dev IaC (docker-compose, testcontainers wiring; not applied to Azure)
│   └── envs/                        # per-env tfvars (git-ignored; never committed)
│       ├── dev/
│       ├── staging/
│       └── prod/
├── console/                   # thin SPA (Vite + Preact) - operator views, owner-scoped background-task inspection, bounded governed commands, local display settings, and observation-only IAM Assignments
│   ├── src/                    # shell, panel registry, GET-only client, routes, browser-local preferences
│   ├── index.html              # Vite entrypoint
│   ├── package.json            # deps: preact, @azure/msal-browser
│   └── vite.config.ts          # build → console/dist/ (git-ignored)
├── cli/                       # operator-console CLI (Ink) - one view-model, many renderers
│   ├── src/view-model/         # presentation-neutral briefing contract + block IR + builder
│   ├── src/renderers/          # ink (terminal) / text / slack (Block Kit) / teams (Adaptive Card)
│   ├── src/cli.tsx             # entrypoint: build briefing once, render per --surface
│   └── package.json            # deps: ink, react (run with tsx, no build step)
├── site/                      # Astro / Starlight docs site (renders docs/**/*.md with i18n + search)
├── ui/                        # (future) static UI kit (Calm Slate theme) - placeholder
├── services/core-control-plane/tests/                     # subsystem-focused unit tests plus cross-subsystem regression suites and shared fixtures
├── docs/roadmap/              # this roadmap and design docs
├── pyproject.toml             # workspace/tooling manifest; not an installable runtime distribution
└── .github/                   # instructions/ and workflows/ (CI: lint, secret-scan, coverage)
```

Runtime bootstrap delegates semantic-turn readiness to `bootstrap_lifecycle.py`, exact Rule generation snapshots and durable requests to `rule_generation_documents.py`, and vertical workload identities to `bootstrap_bindings.py`, preserving bounded provider construction and the injectable identity-builder boundary used by tests and forks. Resource-state composition also binds a no-authority publisher to the shared stage topic after the authoritative Heimdall read; a bounded latency profile retains only its hashed correlation so durable and live activity share one identity without question text, resource identity, executor capability, or an added latency-audit field, and broker failure never rewrites the answer.

> Directory names follow the canonical vocabulary in [language.instructions.md](../../../.github/instructions/language.instructions.md):
> `trust-router`, `deterministic-engine`, `rule-catalog`, `risk-gate`, `remediation-pr`, `shadow-mode`, and `HIL`.
> Disk identifiers use `snake_case`; each package owns its tests, while cross-service and repository checks remain in `tests/integration/`.

## Related docs

| To learn about | Read |
|----------------|------|
| Module boundaries, extension seams, and composition | [Project Structure](project-structure.md) |
| Service extraction evidence and retired compatibility paths | [Service Decomposition Execution Plan](service-decomposition-execution-plan.md) |
| Service promotion and data ownership | [Service Graduation and Data Ownership](service-graduation-and-ownership.md) |
| Delivery status and remaining work | [Implementation ledger](../../roadmap-implementation/architecture/multi-service-repository-layout.md) |
