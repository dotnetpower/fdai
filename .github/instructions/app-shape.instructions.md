---
description: "Use when changing the console, read API, local launch, runtime topology, deployment, or layer boundaries. Covers app shape and local/deployed parity."
applyTo: ".vscode/**,console/**,src/fdai/delivery/read_api/**,src/fdai/runtime/**,infra/**,azure.yaml"
---

# App Shape

Not one big web app. The system is a **headless control plane + thin console + ChatOps**,
serving three initial verticals under an AIOps approach - Resilience, Change Safety, and
Cost Governance. A large always-on UI would contradict the "minimize human intervention"
goal.

The layers are **loosely coupled**: they communicate through the event bus and git, not
direct in-process calls, so any layer can fail or scale independently. See
[architecture.instructions.md](architecture.instructions.md) for the trust-routing control
loop and [../../docs/roadmap/deployment/deployment.md](../../docs/roadmap/deployment/deployment.md) for how the
shape maps to environments and CI/CD.

## Layers

| # | Layer | Shape | Scales to zero | Rationale |
|---|-------|-------|----------------|-----------|
| 1 | **Core engine** | headless, event-driven backend (no UI) - trust router, T0/T1/T2, risk gate, executor | not yet | current Azure baseline keeps one replica until a credential-free Kafka-lag scaler is verified; scheduled jobs scale to zero |
| 2 | **Action delivery** | GitOps / PR-native (GitHub App or Azure DevOps) - actions are remediation PRs/IaC | n/a (git-hosted) | audit, rollback, and approval already exist in git |
| 3 | **Operator console** | thin, read-only SPA - KPI dashboard, audit log, shadow results, HIL queue view | yes (static hosting) | minimal read surface; never executes actions itself |
| 4 | **Human channel** | ChatOps (Teams bot + Adaptive Cards) - high-risk HIL approvals and alerts | yes (event-driven) | reach operators where they already are |
| 5 | **Rule catalog** | catalog-as-code (git repo) - versioned rules | n/a (git-hosted) | the update pipeline lands rules via PR |

- **Brain = core engine (1); hands = action delivery (2); human touchpoints = console (3) +
  ChatOps (4); memory = rule catalog (5).**
- The core is **CSP-neutral by design**: cloud access sits behind adapters (policy in OPA,
  IaC in Terraform). **Azure is the only implemented target**; non-Azure providers are
  TBD (see [Implementation Focus](../copilot-instructions.md#implementation-focus-must)) and
  the neutral abstractions exist so a future adapter can be added without a core rewrite.
  See [../../docs/roadmap/architecture/tech-stack.md](../../docs/roadmap/architecture/tech-stack.md).

## Layer Boundaries (security)

- The **console is read-only**: it renders state and the HIL queue but issues no privileged
  calls. Approvals flow through ChatOps or PR, never console buttons.
- The console uses **clean History API URLs** for operator-facing navigation. Paths use
  lowercase `kebab-case` with no spaces or underscores (for example,
  `/operating-outcomes/change-lead-time` and `/verticals/change-safety`). Internal API
  routes and serialized values keep their canonical machine names. Static hosting MUST
  rewrite non-asset application paths to `index.html`; a missing navigation fallback is
  a deployment defect because direct links and refresh would fail.
- Every aggregate shown on Overview MUST link to either an analytical detail route or a
  filtered evidence route. A detail page shows provenance, measurement window, baseline
  or threshold, breakdown, and supporting records when those projections exist; missing
  evidence renders unavailable rather than being inferred in the browser.
- **Overview drill-down is the default for every data-bearing item.** Posture summaries,
  evidence metadata, success metrics, unavailable metric states, distribution segments and
  legends, attention facts, vertical statistics, and operational-evidence counts MUST each be
  a native link or belong to one keyboard-accessible semantic link container. Section headings
  and explanatory copy are the only non-data exceptions. A destination MUST preserve the
  narrowest available metric, tier, mode, outcome, vertical, status, source, window, or audit
  sample filter; a generic landing route is allowed only when no narrower owned route exists.
  An unavailable datum still links to its owning detail route, where the missing source or
  insufficient evidence is explained. Nested interactive controls are prohibited.
- The **executor holds the only privileged identity** (user-assigned Managed Identity, scoped
  to an action whitelist). Console and ChatOps never share it.
- **Approval and execution are distinct principals** - no self-approval. See
  [../../docs/roadmap/architecture/security-and-identity.md](../../docs/roadmap/architecture/security-and-identity.md).

## Local Console Port Contract (MUST)

- [../../.vscode/launch.json](../../.vscode/launch.json) is the source of truth for the
  local `Console Web: Full Stack` topology: console SPA `5273` and read API `8010`.
  Port `8011` remains reserved for the isolated test ingestion gateway, but that synthetic
  gateway MUST NOT be part of the interactive full-stack compound. Documents remain
  unavailable until an Azure-backed ingestion adapter is configured.
- Vite production preview uses `4173`; it MUST NOT replace the `5273` development origin
  in launch configurations, Entra SPA redirects, or local-development documentation.
- `5173` is not an FDAI standard console port. A custom frontend port MAY be used only when
  each local API receives that exact HTTP(S) origin through its documented CORS environment
  variable. Wildcard origins are prohibited.
- Port changes MUST update the launch configuration, Vite configuration, local API CORS
  defaults, tests, Entra redirect examples, and paired English/Korean documentation together.

## Local Azure Truth Contract (MUST)

- The standard interactive profile uses browser Entra sign-in and verifies the same JWT, audience,
  issuer, lifetime, and App Roles as deployment (`FDAI_READ_API_LOCAL_ENTRA=1`). The server's
  current Azure CLI session supplies short-lived credentials only to Azure read/provider adapters.
  It never replaces the browser principal or Thor's executor identity.
- `FDAI_READ_API_LOCAL_AZURE_CLI=1` plus `VITE_LOCAL_AZURE_CLI_AUTH=1` is an explicit CLI-principal
  debug alternative with a fixed role ceiling. `FDAI_READ_API_DEV_MODE=1`, `VITE_DEV_MODE=1`, and
  synthetic fixtures are pytest/mock-only and MUST NOT be used by the VS Code full-stack profile.
- Interactive local routes MUST NOT seed or synthesize audit rows, Incidents, Approvals,
  agent activity, live control-loop frames, findings, inventory, scope, blast-radius graphs,
  scheduler runs, cost records, promotion evidence, security assessments, or Process runs.
- A local panel MUST read its authoritative Azure-backed source. When the corresponding FDAI
  Azure data plane is not deployed, not configured, unreachable, or unauthorized, the panel
  MUST render unavailable or an explicitly sourced empty state. It MUST NOT substitute demo
  data, catalog-shaped resource templates, generated narratives, or an in-memory fallback and
  present them as observed state.
- Repository catalogs and schemas remain valid local sources for catalog/reference screens;
  they are configuration-as-code, not runtime evidence. Runtime claims MUST carry their actual
  source and MUST NOT be inferred from catalog declarations.
- Synthetic fixtures remain permitted only inside automated tests, mocks, and examples. A
  test-only fixture builder MUST be explicit and MUST fail if invoked by an interactive local
  process.
- Offline development without Azure access is fail-closed: reference/catalog screens may load,
  but Azure runtime screens remain unavailable. There is no synthetic offline mode for the
  interactive Console.

## Local Runtime Parity Contract (MUST)

- Execution venue, deployment environment, evidence profile, promotion state, human identity,
  executor identity, and upstream/fork distribution are independent axes. The canonical decision
  is [ADR-0002](../../docs/roadmap/architecture/decisions/0002-independent-runtime-axes.md).
- Interactive local starts the same 15-agent Pantheon by default. An unset
  `FDAI_START_PANTHEON` means enabled; only `0`, `false`, `no`, or `off` disables it. Event Hubs
  settings select the Azure transport but do not activate the runtime. Without them, the local
  in-process EventBus adapter carries agent messages and SSE state without fabricating Azure
  evidence or binding an executor.
- Local and deployed read the same Workflow allowlist, ActionType promotion state, risk table,
  approval policy, Process transitions, and stage events. Local execution MUST NOT force a promoted
  capability back to shadow or promote an unpromoted capability.
- A local process never receives Thor's privileged identity. Mutation proposals enter the
  development event bus and execute behind the deployed Managed Identity boundary. Test-only
  recording, VM-task, HIL, state, or executor fakes MUST NOT enter interactive composition.

## Console Visual Boundary (MUST)

- Every route, panel, and bounded content region in a loading state **MUST render a skeleton from
  its first loading frame**. Spinner-only, progress-text-only, and blank loading surfaces are not
  supported. A route-specific skeleton SHOULD approximate the final layout's stable dimensions;
  the shared skeleton is the fallback when no owned shape exists. Skeletons are presentation only:
  they MUST expose one `role=status` / `aria-busy=true` loading label, hide decorative blocks from
  assistive technology, never resemble real values, and stop shimmer animation under
  `prefers-reduced-motion: reduce` while remaining visibly present.
- Every console card with data, status, evidence, a count, or a summarized record **MUST drill
  down** to its narrowest owning route or filtered evidence view. Prefer a whole-card native link;
  a card with independent controls MUST expose a visible primary detail link. Unavailable values
  still link to their owner, generic routes are fallback-only, and nested interactions are banned.
- A container without a detail destination is not a card: groups, forms, editors, callouts, and
  tools use section/panel semantics. Typed card APIs and contract tests MUST require destinations.
- Console cards, panels, page sections, callouts, workflow nodes, table rows, and list rows
  **MUST NOT use a colored top edge or colored left edge as decoration or status**. This
  prohibition includes thick `border-top` / `border-left`, inset edge shadows, absolutely
  positioned bars, ribbons, rails, and `::before` / `::after` strips at the top or left.
- Status and selection **MUST** use content-local cues instead: text, icons, badges, neutral
  full borders, subtle whole-surface background tint, or an outline around the complete
  control. A semantic color belongs on the status datum itself, never on the container edge.
- Do not reintroduce the edge-accent pattern from static prototypes. Prototype palette and
  information hierarchy may be reused, but colored card rails and top stamps are not part of
  the production console design.
- Exceptions are limited to non-content mechanics whose meaning depends on position: the
  Activity Bar's active-navigation marker, drag-and-drop insertion indicators, loading
  spinners, charts, graph edges, progress meters, and focus outlines. These exceptions MUST
  NOT be repurposed as card or panel decoration.

## Azure Mapping (draft - reconfirm preview services at adoption time)

Azure is the implemented target (see
[Implementation Focus](../copilot-instructions.md#implementation-focus-must)); the shape stays
CSP-neutral in design by rendering five wire-level contracts (event bus, runtime, secret,
workload identity, inventory) into Azure resources - see
[../../docs/roadmap/architecture/csp-neutrality.md](../../docs/roadmap/architecture/csp-neutrality.md). The mapping is
**minimum-cost-set first** - the concrete inventory, tiers, and rationale live in
[../../docs/roadmap/deployment/deploy-and-onboard.md](../../docs/roadmap/deployment/deploy-and-onboard.md#azure-resource-inventory-minimum-set).
Recommended mapping:

- Event bus: **Event Hubs Standard** consumed **only through its Kafka endpoint on `:9093`**
  (Kafka wire protocol is the CSP-neutral contract); Service Bus is not in the day-zero
  inventory. Event Grid MAY exist only as a managed-identity transport bridge from Azure
  subscription resource-write/delete signals into a raw Event Hub. It is not a core contract,
  broker, or decision surface. Huginn normalizes those records after Kafka ingress, so the core
  still sees Kafka only. Event Hubs local authentication remains disabled.
- Core consumer: **Azure Container Apps** (Consumption) - **one app with one modular Python
  process** that composes the core subsystems behind internal interfaces. The current
  Terraform baseline keeps `minReplicas = 1`; scale-to-zero remains blocked until an
  Event Hubs Kafka-lag scaler can authenticate without adding a long-lived secret. AKS is
  reserved for a measured heavier profile. The app ships as an **OCI
  image + a Knative-compatible manifest subset**, rendered into `containerapp` resources by
  IaC. **Dapr sidecars and Envoy-specific ingress rules are prohibited** to keep the runtime
  contract portable.
- Light triggers: **Container Apps Jobs** in the same environment for out-of-band change
  detection and cost-anomaly probes (avoids provisioning a separate Functions plan); rendered
  from the same manifest as a K8s `CronJob` on non-Azure targets.
- Audit/state/KPI + T1 vectors: **PostgreSQL Flexible** with **pgvector** co-located. Dev uses
  Burstable with HA disabled; production requires zone-redundant HA plus geo-redundant backup.
  Cosmos DB is considered only if RU-metering and geo-distribution outgrow this boundary.
- Secrets: the app reads **environment variables only**; **Key Vault** is bridged in via
  **Container Apps native secret + Key Vault reference** (K8s targets use External Secrets
  Operator). The app never calls a secret SDK.
- PR gate: **GitHub App** (Checks API) or Azure DevOps service hooks.
- HIL approval: **Bot Framework / Teams** Adaptive Cards (Azure Bot Free tier).
- Execution identity: **user-assigned Managed Identity** + action whitelist (least privilege),
  exposed to the core as an **OIDC token** via a `WorkloadIdentity` interface so IRSA / GCP
  Workload Identity / SPIRE slot into the same contract later. `DefaultAzureCredential()` and
  similar SDK entry points are confined to the Azure adapter, never `core/`.
- Observability: **Log Analytics** workspace with **App Insights bound to it** (no separate
  APM resource); default 30-day retention, UI-configurable.

## Failure Modes

- **Console down** - operations continue; core engine, PR gate, and ChatOps are unaffected.
- **ChatOps down** - high-risk HIL items queue and alert via a fallback; nothing auto-executes
  without approval.
- **Event-bus backpressure** - rely on ordering plus dead-letter queues; the core reprocesses,
  it does not drop events.
- **Any layer** that triggers a change still owes a stop-condition, rollback path,
  blast-radius limit, and audit entry (see coding-conventions and security-and-identity).

## Anti-Patterns (avoid)

- **Monolithic web app that does everything** - always-on cost, violates autonomy philosophy,
  hard to port across clouds.
- **UI buttons that execute actions** - forces custom audit/rollback and breaks least
  privilege; PR-native gets audit, rollback, and approval for free.
- **Always-on polling daemons** - conflicts with the event-driven, scale-to-zero principle.
- **Shared identity across layers** - a console or bot reusing the executor identity collapses
  the approval/execution boundary.
- **Actions without a rollback or audit path** - any change delivered outside git must still
  provide both, or it is incomplete.

> One line: brain = headless event-driven control plane, hands = GitOps/PR,
> human touchpoint = thin console + Teams bot.
