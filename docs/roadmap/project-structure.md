---
title: Project Structure
---
# Project Structure

The system is a **headless control plane + thin console + ChatOps**, not one web app
(see [app-shape.instructions.md](../../.github/instructions/app-shape.instructions.md)).
The repository layout mirrors that shape and keeps the core engine UI-agnostic and portable.
Module names and the control loop follow
[architecture.instructions.md](../../.github/instructions/architecture.instructions.md).

## Monorepo Layout

```text
fdai/
├── src/fdai/            # Python (3.12+, src-layout); one language across the monorepo
│   ├── core/                  # headless control plane (no UI, no direct cloud SDK imports)
│   │   ├── event_ingest/       # bus consumers; normalize to event schema; dedup by idempotency key; correlate related events into incidents
│   │   ├── trust_router/       # routes each event to T0 | T1 | T2 by computed confidence
│   │   ├── tiers/
│   │   │   ├── t0_deterministic/    # deterministic-engine: policy, checklist, what-if, drift eval
│   │   │   ├── t1_lightweight/      # embedding similarity, learned-action reuse, small-model classify
│   │   │   └── t2_reasoning/        # frontier-model reasoning for novel/ambiguous cases only
│   │   ├── prompts/            # catalog-as-code prompt composer (loads `rule-catalog/prompts/`, supplies T2)
│   │   ├── tools/              # T2 tool-catalog registry + `ToolExecutor` (shadow-mode gated)
│   │   ├── web_search/         # last-resort web-search seam (`NoOpWebSearchProvider` default; domain allowlist + sanitizer)
│   │   ├── operator_memory/    # HIL-approved operator memory injected as untrusted `<operator_note>` data
│   │   ├── quality_gate/       # mixed-model cross-check, verifier, grounding (guards T2)
│   │   ├── rca/                # root-cause analysis (T0 deterministic + T2 reasoner behind seam; grounding-gated)
│   │   ├── risk_gate/          # unified authority: risk score + auto vs HIL vs deny; enforces the four safety invariants
│   │   ├── rbac/               # human RBAC for the read API (5-role matrix, resolver, enforcer)
│   │   ├── hil_resume/         # HIL approval round-trip: park, push to channel, resume on decision
│   │   ├── executor/           # per-resource lock, idempotent apply via delivery adapters
│   │   ├── audit/              # append-only, hash-chained audit log + KPI/metric emission
│   │   ├── notifications/      # channel-routing layer over the notifications matrix
│   │   ├── detection/          # out-of-band anomaly / forecast finding producers (re-enter event-ingest)
│   │   ├── incident/           # incident lifecycle registry + state machine (open → triaging → mitigated → resolved → closed)
│   │   ├── slo/                # workload SLO / burn-rate evaluator (distinct from control-plane SLOs)
│   │   ├── runbook/            # runbook orchestrator (linear sequence + on-failure branch)
│   │   ├── workflow/           # process automation: compile a catalog Workflow into a Runbook (+ saga-compensation map)
│   │   ├── postmortem/         # LLM-optional postmortem / PIR draft generator
│   │   ├── rule_catalog_profiles/  # profile / pack layer - named rule bundles with `extends` chains + overrides
│   │   ├── measurement/        # Phase-4 continuous measurement (regression, pattern growth, model tracking, latency budget, prompt probe, runners)
│   │   ├── deploy_preflight/   # pre-deployment feasibility probes → grounded readiness report
│   │   ├── assurance_twin/     # read-only ontology twin: text-to-query review / Q&A / assessment (proposes, never executes)
│   │   ├── conversation/       # operator-console coordinator (Layer 2): NL turn → one read-only tool call
│   │   ├── verticals/          # Resilience / Change Safety / Cost Governance (P3 integration surface)
│   │   ├── control_loop.py     # P1 pipeline orchestrator: event_ingest → trust_router → T0 → executor → audit
│   │   └── ontology_explorer.py    # deterministic Mermaid renderer for the loaded ObjectType / LinkType catalog
│   ├── shared/                # cross-cutting; MUST NOT import from core/
│   │   ├── contracts/          # models.py + registry.py + validation.py + JSON Schemas
│   │   │   ├── event/          # event/schema.json
│   │   │   ├── action/         # action/schema.json
│   │   │   ├── rule/           # rule/schema.json
│   │   │   ├── ontology/       # object-type / link-type / action-type JSON Schemas
│   │   │   └── workflow/       # workflow/schema.json (process-automation catalog)
│   │   ├── ontology/           # runtime ontology helpers (ACL, audit purposes, purpose taxonomy)
│   │   ├── providers/          # CSP-neutral cloud provider interfaces (adapters implement them)
│   │   │                       #   event_bus.py, secret_provider.py, state_store.py,
│   │   │                       #   workload_identity.py, inventory.py + LLM / channel / RBAC / feasibility-probe seams
│   │   │                       # `providers/local/` = dev-mode fakes (`EnvSecretProvider`, `LocalWorkloadIdentity`, `FileFixtureInventory`);
│   │   │                       # `providers/testing/` = in-memory fakes used across the test suite (never bound in prod)
│   │   ├── streaming/          # `SseBroadcaster` + `StagePublisher`: relay EventBus topics → SSE channels
│   │   ├── telemetry/          # structured logging, tracing, metric helpers
│   │   └── config/             # config schema + startup validation (fail-fast)
│   ├── delivery/              # action delivery adapters (behind one shared interface)
│   │   ├── gitops_pr/          # remediation-pr adapter: GitHub App / Azure DevOps, Checks API
│   │   ├── chatops/            # channel adapters (Teams / Slack / email / webhook / pager / SMS)
│   │   ├── notifications/      # per-channel senders (email HTTP, HIL sink) wired by `shared/providers` seams
│   │   ├── persistence/        # Postgres / pgvector concrete implementations of `shared/providers` state seams
│   │   ├── azure/              # Azure-specific SDK adapters (the only tree allowed to import `azure-*`)
│   │   └── read_api/           # thin GET-only ASGI (`/audit`, `/kpi`, `/hil-queue`, `/healthz`, live control-loop, ontology graph, promotion-gates, ...) + opt-in SSE fan-out (`/live/stream` via `live_stream.py`)
│   ├── rule_catalog/          # rule-catalog PIPELINE code
│   │   ├── schema/             # rule + ontology (ObjectType / LinkType / ActionType) schemas + validation
│   │   ├── sources/            # per-source collectors (WAF, CIS, OPA, IaC scanners, ...)
│   │   ├── pipeline/           # watch → collect → shadow eval → regression → promote/rollback
│   │   └── codegen/            # authoring helpers (`new_action_type`, `new_object_type`) - generate scaffolds, never mutate the live catalog
│   ├── agents/                # pantheon runtime - 15 named agent modules (odin / thor / forseti / huginn / heimdall / ...), typed topics + bus, adapters + registry; see [agent-pantheon.md](agent-pantheon.md)
│   ├── composition.py         # composition root: `default_container()` binds every seam
│   └── __main__.py            # entry point (starts the P1 control loop)
├── rule-catalog/              # catalog-as-code DATA (YAML) - no Python; pipeline lives in src/fdai/rule_catalog/
│   ├── schema/                 # JSON Schema definitions (data)
│   ├── vocabulary/             # canonical CSP-neutral vocabularies: resource-types.yaml, object-types/, link-types/
│   ├── action-types/           # upstream ontology ActionType instances (shadow-default, promotion_gate-required)
│   ├── action-types-custom/    # fork-only ActionType additions (deny-listed in upstream CI)
│   ├── action-types-overrides/ # scoped overrides to upstream ActionTypes (≤ resource-group scope)
│   ├── profiles/               # named rule packs (upstream)
│   ├── profiles-overrides/     # fork overlay for profiles
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
│   │   ├── preflight-toggles/       # feature-flag surface mapping preflight blockers → Terraform toggles
│   │   └── console/                 # Static Web App hosting for the read-only SPA
│   │       └── static-web-app/      # default
│   ├── local/                       # local-dev IaC (docker-compose, testcontainers wiring; not applied to Azure)
│   └── envs/                        # per-env tfvars (git-ignored; never committed)
│       ├── dev/
│       ├── staging/
│       └── prod/
├── console/                   # thin read-only SPA (Vite + Preact) - KPI, audit, HIL queue
│   ├── src/                    # main.tsx, app.tsx, api.ts, auth.ts (MSAL.js), routes/
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
├── tests/                     # cross-subsystem regression suites + shared fixtures (unit tests colocate)
├── docs/roadmap/              # this roadmap and design docs
├── pyproject.toml             # single manifest for the Python monorepo
└── .github/                   # instructions/ and workflows/ (CI: lint, secret-scan, coverage)
```

> Directory names are the canonical vocabulary. Keep module names aligned with the domain
> terms in [language.instructions.md](../../.github/instructions/language.instructions.md)
> (`trust-router`, `deterministic-engine`, `rule-catalog`, `risk-gate`, `remediation-pr`,
> `shadow-mode`, `HIL`). Python identifier rules require `snake_case` on disk
> (`event_ingest`, `trust_router`, `rule_catalog`); the kebab-case names above are the
> **logical vocabulary** used in docs, rule ids, config keys, and audit records. Unit
> tests colocate with each subsystem; `tests/` holds only cross-subsystem regression and
> property suites.

## Module Boundaries

Dependency direction is strict and one-way; a violation is a review blocker.

- **core is portable**: it MUST NOT import any cloud SDK directly. Cloud specifics enter
  only through the CSP-neutral interfaces in `shared/providers/`, whose implementations live
  in `delivery/` and `infra/` and are injected at composition time. This keeps a second cloud
  a matter of adding an adapter, never editing `core/`.
- **allowed imports**: `core/` may import `shared/` (contracts, providers, telemetry, config)
  only; `delivery/`, `infra/`, and `console/` may depend on `shared/` contracts but not on
  `core/` internals; `shared/` imports nothing from `core/` (no cycles).
- **policies and rules are data, not code paths**: T0 loads `rule-catalog/` entries and
  `policies/` at runtime; adding a rule or policy never requires an engine change. Rules
  describe intent and remediation; policies are the executable OPA/Rego the verifier re-checks.
  How sources are collected and normalized into that YAML is in
  [rule-catalog-collection.md](rule-catalog-collection.md).
- **delivery is swappable**: `gitops-pr` and `chatops` are adapters behind one interface, so
  the executor emits an abstract action and the adapter renders it (remediation-pr, Adaptive
  Card). The executor holds the only privileged identity; adapters never share it.
- **console is read-only**: it visualizes state, audit, shadow results, and the HIL queue but
  issues no privileged calls and executes no actions. HIL approvals flow through ChatOps or
  the remediation-pr, never through console buttons
  (see [security-and-identity.md](security-and-identity.md)).

## Customization via Dependency Injection

This repository is the **main project**. Per-customer customization is supplied by **dependency
injection**, never by editing `core/` or maintaining a divergent copy of it. The upstream repo
defines the interfaces and ships generic default implementations; a fork **registers its own
implementations** at a composition root, so customization is additive and upstream sync stays
clean (see the fork model in
[generic-scope.instructions.md](../../.github/instructions/generic-scope.instructions.md)).

> **Fork maintainers**: start with the procedural walkthrough in
> [downstream-fork-guide.md](downstream-fork-guide.md). This section is the seam catalog
> that guide operationalizes.

- **Composition root**: `core/` depends only on the CSP-neutral interfaces in `shared/`. A thin
  composition root (outside `core/`) binds concrete implementations at startup. `core/` never
  news-up a concrete adapter; it receives its dependencies. The upstream default binder is
  [`fdai.composition.default_container`](../../src/fdai/composition.py); a fork's
  entry point calls its own factory that wraps or replaces those bindings. Concrete adapter
  classes (e.g. `PackageResourceSchemaRegistry`, `JsonSchemaContractValidator`) are
  **not** re-exported from public sub-packages; they must be imported directly from their
  submodule, and only by a composition root, so `core/` cannot depend on a concrete by
  accident.
- **Config-driven binding**: which implementation binds to which interface is selected by
  configuration, so a fork overrides a binding by supplying its own package + config, not by
  patching core. Invalid or missing bindings **fail fast** at startup (Configuration Model).
- **Default implementations upstream**: the main repo provides working generic defaults for
  every seam so it runs standalone; a fork replaces only the seams it needs.

### Injectable Seams

The five seams marked **CSP-neutrality contract** below realize the wire-level contracts in
[csp-neutrality.md](csp-neutrality.md). `core/` sees only the interface; a fork or a future
non-Azure phase registers a new implementation at the composition root without editing `core/`.

| Seam | Interface (in `shared/`) | Contract | Default (upstream) | Fork override example |
|------|--------------------------|----------|--------------------|-----------------------|
| Event bus | `EventBus` (Kafka producer/consumer) | **CSP-neutrality contract** - [event bus](csp-neutrality.md#1-event-bus-contract--kafka-wire-protocol) | librdkafka-based client with SASL/OAUTHBEARER (Entra token source) | AWS IAM SigV4 auth, GCP IAM auth, Confluent SASL/PLAIN, self-hosted Kafka mTLS |
| Runtime | `RuntimeAdapter` (renders OCI + Knative-compatible manifest) | **CSP-neutrality contract** - [runtime](csp-neutrality.md#2-runtime-contract--oci-image--knative-compatible-manifest) | Container Apps IaC renderer (Bicep/Terraform) | Cloud Run YAML, App Runner service, Knative Service on any K8s |
| Secret & config | `SecretProvider` / `ConfigProvider` | **CSP-neutrality contract** - [secret](csp-neutrality.md#3-secret-contract--environment--k8s-secret) | env + Container Apps KV-reference bridge | ESO + Key Vault / AWS Secrets Manager / GCP Secret Manager / HashiCorp Vault |
| Workload identity | `WorkloadIdentity` (audience-scoped OIDC token) | **CSP-neutrality contract** - [workload identity](csp-neutrality.md#4-workload-identity-contract--oidc-token) | user-assigned Managed Identity (IMDS → Entra token) | IRSA, GCP Workload Identity Federation, SPIFFE/SPIRE SVID |
| Inventory | `Inventory` (CSP-neutral resource-graph adapter emitting `Resource` + `contains` / `attached_to` / `depends_on` link records via `full_snapshot()` and `delta()`) | **CSP-neutrality contract** - [inventory](csp-neutrality.md#5-inventory-contract--resource-graph) | Azure Resource Graph adapter: parallel full-scan sharded by `resource_type` + Activity-Log-driven delta consumed off the event bus | AWS Config + Resource Explorer adapter; GCP Cloud Asset Inventory adapter; K8s `apiserver` list-watch translator |
| Cloud provider | provider client | (uses the five above) | reference/generic Azure adapter | a specific CSP adapter |
| **Schema source** | `SchemaRegistry` (raw JSON Schema loader) | - | `PackageResourceSchemaRegistry` (schemas ship inside the package) | remote schema-registry adapter; snapshot pinned by content hash |
| **Boundary validation** | `ContractValidator` / `EventValidator` (fail-closed input check) | - | `JsonSchemaContractValidator` + `JsonSchemaEventValidator` (draft-2020-12) | fork MAY layer domain-specific checks (e.g. source allowlist) without editing `core/` |
| Rule / policy source | rule-catalog + `policies/` loader | - | bundled generic rules | customer rule set / thresholds |
| **Ontology ObjectType / LinkType** | `load_object_type_catalog(root, *, schema_registry)` and `load_link_type_catalog(root, *, schema_registry, object_types=...)` in `src/fdai/rule_catalog/schema/` | - | four upstream ObjectTypes (`Resource`, `Rule`, `Signal`, `Finding`) and the shipped LinkTypes under `rule-catalog/vocabulary/{object-types,link-types}/`, loaded into `Container.ontology_object_types` / `Container.ontology_link_types` by the entry point | fork ships additional YAML under a fork-local directory (e.g. `fork/vocabulary/object-types/ArchitectureProposal.yaml`), loads both roots at its composition root, and passes the concatenated tuples via `dataclasses.replace(container, ontology_object_types=..., ontology_link_types=...)`. Duplicate `name` across roots fails-closed. See [downstream-fork-seam-recipes.md § 5.8a](downstream-fork-seam-recipes.md#58a-ontology-object-type--link-type-additions). |
| **Workflow catalog (process automation)** | `load_workflow_catalog(root, *, schema_registry, action_type_names, rule_ids=...)` in `src/fdai/rule_catalog/schema/workflow.py`; `compile_workflow(...)` in `src/fdai/core/workflow/` | - | shadow-first Workflows under `rule-catalog/workflows/`, loaded into `Container.workflows` by the entry point after the ActionType + rule catalogs; every step cross-references an `ActionType` and (when set) a Rule id, fail-closed at startup | fork ships additional Workflow YAML under a fork-local `fork/workflows/` directory, loads it at its composition root with the concatenated ActionType / rule sets, and passes the tuple via `dataclasses.replace(container, workflows=...)`. Duplicate `name` across roots fails-closed. See [process-automation.md](process-automation.md). |
| Delivery adapter | delivery interface | - | `gitops-pr` / `chatops` | a different PR host / chat channel |
| Risk scoring & thresholds | risk-gate config | - | generic thresholds | customer risk policy |
| Model provider | model client (per capability) | - | configured default endpoints | customer-approved models |
| **Real-time outbound stream** | `SseSink` (async publish + async-iterator subscribe over an SSE-shaped payload) | - | `InMemorySseSink` (test/dev); HTTP `text/event-stream` adapter lands with the console read-only surface | replace with a WebSocket adapter for a two-way surface; a webhook-only variant for headless observers. `shared/streaming/SseBroadcaster` relays `EventBus` topics into channels. |
| **Pipeline stage publisher** | `StagePublisher` (in `shared/providers/stage_publisher.py`) with `emit(StageEvent)` | - | `NullStagePublisher` (discards; keeps stage code side-effect-free by default) | in-process dev / single-replica: `SseSinkStagePublisher` fans out directly onto `SseSink`. Multi-replica prod: `EventBusStagePublisher` writes to a Kafka topic (default `aw.pipeline.stages`) and the existing `SseBroadcaster` relays that topic to the SSE channel every replica consumes. Pipeline stages (`event_ingest`, `trust_router`, T0/T1/T2, `risk_gate`, `executor`, `audit`) accept the Protocol so wiring is fully backward-compatible - the upstream default emits nothing. |
| **Console read panel** | `ReadPanel` (in `delivery/read_api/panels.py`) | - | core routes only (`/audit`, `/kpi`, `/hil-queue`); `ExampleFinOpsPanel` ships as reference but is **not** registered, so the upstream UI stays minimal | fork adds vertical dashboards (FinOps cost, drift board, DR-drill history) via `ReadApiConfig.extra_panels` (each wrapped as a GET-only route, path validated at build) + a matching entry in the console `panels.tsx` registry |
| **Infra module** | `infra/modules/<seam>/` (Terraform sub-module selected by `var.<seam>_kind`) | - | Container Apps + PostgreSQL Flex + Event Hubs Kafka + Key Vault + Log Analytics | pick a different sub-module per [csp-neutrality.md § Approved Alternative Azure Implementations](csp-neutrality.md#approved-alternative-azure-implementations); the module's output contract stays fixed |

Because every seam is an injected interface, adding a customer or a second cloud is a matter of
registering an implementation - the strict one-way dependency direction above is preserved.

**Concurrency posture**: the five **I/O provider Protocols** - `EventBus`, `StateStore`,
`SecretProvider`, `WorkloadIdentity`, `Inventory` - are **async by default**. Their concrete
implementations (Kafka client, asyncpg, Key Vault HTTP, OIDC token exchange, ARG/HTTP
inventory queries) block the event loop if forced to be sync. The **CPU / startup seams** - `SchemaRegistry`,
`ContractValidator` / `EventValidator`, `ConfigProvider` - stay **sync**: they run once at
startup, or are pure CPU boundary validation with no I/O, so an async wrapper would only add
noise. Tests use `pytest-asyncio` with `asyncio_mode = "auto"` so a plain `async def
test_...` runs without a per-test marker.

## Control-Loop Wiring

Every terminal path-including reject, HIL timeout, abstain, and deny-writes an audit entry.
T2 output reaches the risk-gate only after clearing the quality-gate.

```mermaid
flowchart LR
    EV[events] --> NORM["event-ingest<br/>normalize + dedup"]
    NORM --> ROUTER[trust-router]
    ROUTER -->|rule match| T0[t0-deterministic]
    ROUTER -->|similar| T1[t1-lightweight]
    ROUTER -->|novel| T2[t2-reasoning]
    T2 --> QG[quality-gate]
    T0 --> RG[risk-gate]
    T1 --> RG
    QG --> RG
    RG -->|low risk| EX[executor]
    RG -->|high risk| HIL["HIL approval<br/>via chatops"]
    RG -->|abstain / deny| NOOP[no-op]
    HIL -->|approve| EX
    HIL -->|reject / timeout| NOOP
    EX --> DEL["delivery: gitops-pr / chatops"]
    EX --> AUD[audit]
    DEL --> AUD
    NOOP --> AUD
    AUD --> LIB[(pattern library)]
    LIB --> T1
```

## Configuration Model

- Everything environment-specific is **configuration**, injected at runtime (env vars,
  secret store references, config files). No customer, tenant, or environment values in source.
- Config is validated against the `shared/config/` schema at startup; the process **fails fast**
  on invalid or missing required config rather than starting in a degraded state.
- Secrets are read through an injected provider, never a global import-time read, and never
  written to logs, audit entries, or error messages.
- A fork supplies its own config and secret-store layer without editing `core/`.
- Feature flags gate new capabilities so they ship in **shadow-mode** (judge-and-log only)
  and are promoted to enforce per-action, in a separate reviewed change.

## Repository Conventions

- **Python (3.12+) is the single core runtime language** for the whole monorepo; all
  executable code lives under `src/fdai/` (Python "src layout"). Rationale and the
  historical choice matrix are in [tech-stack.md § OD-1](tech-stack.md#od-1-core-runtime-language).
  Non-Python trees are: [rule-catalog/](../../rule-catalog/) (YAML data), [policies/](../../policies/)
  (Rego), and [infra/](../../infra/) (Terraform HCL).
- **One lockfile** at the repo root (`uv.lock` or equivalent); CI installs from the lockfile
  only. The subsystem-per-lockfile guidance in earlier drafts assumed a multi-language
  layout and is retired for the Python monorepo. Boundaries between subsystems are enforced
  by an import-lint gate in CI, not by separate package installs.
- Contracts (event, action, rule schemas, and ontology `ObjectType` / `LinkType` /
  `ActionType` definitions) live in `src/fdai/shared/contracts/` (types) and
  `rule-catalog/schema/` (per-kind JSON Schema), carry a **semver** version, and change
  only in a backward-compatible way within a major version; breaking changes bump the
  major and ship a migration note. Runtime instance storage for those types is covered in
  [llm-strategy.md § Ontology Storage Layout](llm-strategy.md#ontology-storage-layout).
- Tests for `src/fdai/core/tiers/t0_deterministic` (the deterministic-engine) and
  `src/fdai/core/risk_gate` are the safety core: they hold a ≥ 90% coverage gate
  and include property-based tests asserting "high-risk never auto-executes", "shadow-mode
  never mutates", and "re-applying an action is a no-op". Every action path also has a
  shadow-mode test and a rollback test.
- Rule and policy changes ship with a regression test; the
  `src/fdai/rule_catalog/pipeline/` promotion gate blocks on a failing regression
  suite or any policy-violation escape.
- CI enforces the gates referenced above-formatter/linter, secret scanning, dependency audit,
  coverage, and regression-before review; see
  [coding-conventions.instructions.md](../../.github/instructions/coding-conventions.instructions.md).
