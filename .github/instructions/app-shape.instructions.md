---
description: "Use when changing the console, Operator API, local launch, runtime topology, deployment, or layer boundaries. Covers app shape and local/deployed parity."
applyTo: ".vscode/**,console/**,services/operator-service/src/fdai_operator_service/**,services/core-control-plane/src/fdai/runtime/**,infra/**,azure.yaml"
---

# App Shape
Not one big web app. The system is a **headless control plane + thin console + ChatOps**, serving Resilience, Change Safety, and Cost Governance. SRE is their operating model and ARB is cross-domain governance. A large always-on UI would contradict the "minimize human intervention" goal.

The layers communicate through the event bus and git, not direct in-process calls, so they fail and scale independently. See [Architecture](architecture.instructions.md) for trust routing and
[Deployment](../../docs/roadmap/deployment/deployment.md) for environment and CI/CD mapping.

## Layers

| # | Layer | Shape | Scales to zero | Rationale |
|---|-------|-------|----------------|-----------|
| 1 | **Core engine** | headless, event-driven backend (no UI) - trust router, T0/T1/T2, risk gate, audit, and recovery; executor remains co-located only until the tracked cutover | not yet | current Azure baseline keeps one replica until a credential-free Kafka-lag scaler is verified; scheduled jobs scale to zero |
| 2 | **Action delivery** | GitOps / PR-native (GitHub App or Azure DevOps) - actions are remediation PRs/IaC | n/a (git-hosted) | audit, rollback, and approval already exist in git |
| 3 | **FDAI Console** | thin SPA - query projections plus bounded operational requests | yes (static hosting) | one product surface; never executes managed-resource actions itself |
| 4 | **Human channel** | ChatOps (Teams bot + Adaptive Cards) - high-risk HIL approvals and alerts | yes (event-driven) | reach operators where they already are |
| 5 | **Rule catalog** | catalog-as-code (git repo) - versioned rules | n/a (git-hosted) | the update pipeline lands rules via PR |

- **Brain = core engine (1); hands = action delivery (2); human touchpoints = console (3) + ChatOps (4); memory = rule catalog (5).**
- The core is **CSP-neutral by design**: cloud access sits behind adapters (policy in OPA, IaC in Terraform).
  **Azure is the only implemented target**; non-Azure providers are TBD (see [Implementation Focus](../copilot-instructions.md#implementation-focus-must)), and the neutral abstractions let a future adapter
  be added without a core rewrite.
  See [../../docs/roadmap/architecture/tech-stack.md](../../docs/roadmap/architecture/tech-stack.md).

## Layer Boundaries (security)

- The **Operator API is the non-privileged, not-GET-only backend for FDAI Console and operator clients**.
  It renders authoritative projections and MAY submit typed requests through server-owned RBAC,
  revision, idempotency, and audit. It and the SPA MUST NOT receive Thor's identity, mutate managed
  resources, derive browser authorization, or bypass agent, quality, risk, approval, recovery, or audit. See
  [../../docs/roadmap/interfaces/console-operations.md](../../docs/roadmap/interfaces/console-operations.md).
- `/provisioning` MAY submit a typed, content-addressed intent to the protected deployment executor,
  but browser/API MUST NOT run Terraform, mutate Azure, hold deploy identity, or read state; plan, approval, apply, rollback, and independent readback stay separate audited stages.
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

- [../../.vscode/launch.json](../../.vscode/launch.json) is the source of truth for the local `Console Web: Full Stack` topology: console SPA `5273`, Manual Studio `5474`, Operator API `8010`, Document Ingestion API `8011`, Document Processing Worker health `8012`, and isolated Executor health `8013`; the compound MUST start all five independently packaged backend services, the SPA, and Manual Studio.
  It MUST NOT restore a co-host, retired top-level package, or fixture gateway.
- The same managed full-stack supervisor MUST also keep the local analyzer, inventory
  reconciliation, and observation campaign loops alive. These loops add no browser port or service
  distribution; they provide local parity for the deployed scheduled jobs and MUST participate in
  readiness so a projection-only stack cannot be reported as detection-ready. Analyzer readiness
  requires a clean first tick after the latest managed start; process presence or an older ready
  marker is insufficient. A failed tick MUST clear readiness while the managed local loop retries
  at the next bounded interval.
- An inventory-backed analyzer MUST retain the ontology `Resource.id` in findings, Events, receipts,
  and Incidents. It MAY use the exact provider reference from the active service-owned inventory
  snapshot only to scope the provider metric query. Missing, mismatched, or ambiguous provider
  identity MUST fail the analyzer tick instead of querying with a sanitized logical id.
- Live or full-stack Console validation MUST target the standard `http://localhost:5273` SPA origin and the `127.0.0.1:8010` Operator API listener. The frontend process remains bound to IPv4 loopback; `localhost` is the canonical browser origin so OAuth cache, conversation state, response preferences, and screen context do not split across loopback hostnames. When an authenticated Browser Entra page is shared with the agent, the agent MUST verify that page's origin, rendered Console shell, and signed-in state, then reuse its browser context before seeking a separate Playwright storage-state artifact. If no authenticated context is available, obtain one through the approved interactive sign-in flow; never weaken authentication or request secrets.
- The isolated Playwright harness and any ad hoc alternate ports are test-only environments. They MUST NOT be reported as Browser Entra full-stack evidence or substituted merely because a standard port is occupied. Diagnose the owner of the occupied port and preserve an already-running standard full stack unless the user explicitly requests a different topology.
- Vite production preview uses `4173`; it MUST NOT replace the `5273` development origin in launch configurations, Entra SPA redirects, or local-development documentation.
- `5173` is not an FDAI standard console port. A custom frontend port MAY be used only when each local API receives that exact HTTP(S) origin through its documented CORS environment variable. Wildcard origins are prohibited.
- Port changes MUST update the launch configuration, Vite configuration, local API CORS defaults, tests, Entra redirect examples, and paired English/Korean documentation together.

## Local Azure Truth Contract (MUST)

- The standard interactive profile uses browser Entra sign-in and verifies the same JWT, audience, issuer, lifetime, and App Roles as deployment (`FDAI_OPERATOR_API_LOCAL_ENTRA=1`). The server's current Azure CLI session supplies short-lived credentials only to Azure read/provider adapters. It never replaces the browser principal or Thor's executor identity.
- `FDAI_OPERATOR_API_LOCAL_AZURE_CLI=1` plus `VITE_LOCAL_AZURE_CLI_AUTH=1` is an explicit
  CLI-principal debug alternative with a fixed role ceiling. `FDAI_OPERATOR_API_DEV_MODE=1`,
  `VITE_DEV_MODE=1`, and
  synthetic fixtures are pytest/mock-only and MUST NOT be used by the VS Code full-stack profile.
- Interactive local routes MUST NOT seed or synthesize audit rows, Incidents, Approvals, agent activity, live control-loop frames, findings, inventory, scope, blast-radius graphs, scheduler runs, cost records, promotion evidence, security assessments, or Process runs.
- The Overview Dashboard and analysis routes plus every route registered in the Operations group
  MAY expose one explicit operator-selected `Sample` presentation mode. It MUST default to `Live`,
  use dedicated URL and tab-session state, label the entire page as sample data that is not
  operational evidence, use only generic deterministic fixtures, and never activate from an empty
  or failed live response. Sample mode MUST use a GET-only fixture boundary, block or remove
  mutation controls, and MUST NOT mix with live values, create runtime records, acquire a provider
  token, or grant authority. Unsupported interactive routes remain authoritative-only, and
  selecting one hides Sample presentation without changing its live data.
- A local panel MUST read its authoritative Azure-backed source. When the corresponding FDAI
  Azure data plane is not deployed, not configured, unreachable, or unauthorized, the panel
  MUST render unavailable or an explicitly sourced empty state. It MUST NOT substitute demo
  data, catalog-shaped resource templates, generated narratives, or an in-memory fallback and
  present them as observed state.
- An unavailable or empty local surface is correct only while its authoritative source is genuinely
  absent. It MUST NOT stand in for a producer, ingress, job, or capability flag that the local
  profile simply never bound. Diagnose which authoritative binding is missing and bind it.
- Repository catalogs and schemas remain valid local sources for catalog/reference screens;
  they are configuration-as-code, not runtime evidence. Runtime claims MUST carry their actual
  source and MUST NOT be inferred from catalog declarations.
- Synthetic fixtures remain permitted only inside automated tests, mocks, and examples. A
  test-only fixture builder MUST be explicit and MUST fail if invoked by an interactive local
  process.
- Offline development without Azure access is fail-closed: reference/catalog screens may load,
  but Azure runtime screens remain unavailable. There is no synthetic offline mode for the
  interactive Console.
- Local preparation enables optional web search only when the resolved-model artifact contains at
  least one usable `web_search_candidates` entry. Missing candidates leave web search unavailable;
  launch tasks MUST NOT override that capability decision.

## Local Runtime Parity Contract (MUST)

- **Execution venue does not change control-plane behavior**
  ([Constitution, Article 1](../../docs/roadmap/architecture/fdai-constitution.md)). Every venue
  binds the same authoritative sources, ingress path, contracts, control-loop stages, and surfaces;
  only credentials, endpoints, scale, and provider scope may differ. A capability flag, scheduled
  job, or forwarding path that deployment enables MUST be enabled for interactive local too, and a
  divergence MUST be justified by a venue-specific provider constraint recorded in
  [dev-and-deploy-parity.md](../../docs/roadmap/deployment/dev-and-deploy-parity.md), never by
  convenience or by an unimplemented local binding.
- Execution venue, deployment environment, evidence profile, promotion state, human identity,
  executor identity, and upstream/fork distribution are independent axes. The canonical decision
  is [ADR-0002](../../docs/roadmap/architecture/decisions/0002-independent-runtime-axes.md).
- Interactive local starts the same 15-agent Pantheon by default. An unset
  `FDAI_START_PANTHEON` means enabled; only `0`, `false`, `no`, or `off` disables it. Event Hubs
  settings select the Azure transport but do not activate the runtime. Without them, the local
  in-process EventBus adapter carries agent messages and SSE state without fabricating Azure
  evidence or binding an executor.
- The process launcher MUST set `FDAI_EXECUTION_VENUE=local` for the interactive profile and `FDAI_EXECUTION_VENUE=deployed` for Azure services; this axis is independent from `RUNTIME_ENV`, evidence profile, promotion state, identity, and distribution.
- Local stateful services MUST use loopback Docker PostgreSQL with exact service-owned roles, Redpanda for inter-service transport, and ClamAV for document scanning; deployed services MUST use service-owned Azure PostgreSQL DSNs, Event Hubs Kafka, and managed identities, and a venue change MUST NOT reuse the other venue's DSN.
- The local isolated Executor MUST be a durable shadow consumer of local PostgreSQL and Redpanda without managed-resource identity; authority cutover MUST fail startup, and the process proves the independent receipt path without applying an effect.
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
  a card with independent controls MUST expose a visible primary detail link. Missing values use a
  typed neutral evidence state and still link to their owner; only actual failures use error styling.
- A container without a detail destination is not a card: groups, forms, editors, callouts, and
  tools use section/panel semantics. Typed card APIs and contract tests MUST require destinations.
- Console cards, panels, page sections, callouts, workflow nodes, table rows, and list rows
  **MUST NOT use a persistent colored top edge or colored left edge as decoration or status**.
  This prohibition includes thick `border-top` / `border-left`, inset edge shadows, absolutely
  positioned bars, ribbons, rails, and persistent `::before` / `::after` strips at the top or left.
- Status and selection **MUST** use content-local cues instead: text, icons, badges, neutral
  full borders, subtle whole-surface background tint, or an outline around the complete
  control. A semantic color belongs on the status datum itself, never on the container edge.
- A card whose authoritative visible content changes in place after its first render **SHOULD use
  the shared top-edge shimmer** as transient update feedback. The effect MUST be a single neutral
  blue sweep no more than 2 px high and 1.5 seconds long. It MUST NOT encode success, failure,
  freshness, severity, selection, or agent state. Primitive shared KPI cards derive their update
  key from visible values; complex cards MUST supply an explicit semantic update key.
- The top-edge shimmer MUST skip first render, unchanged parent rerenders, filter or selection
  changes, and clock-, age-, or timestamp-only updates. Rapid semantic updates coalesce while one
  sweep is active. The shared implementation MUST stop the animation under
  `prefers-reduced-motion: reduce`; routes MUST NOT create local color or timing variants.
- Do not reintroduce the edge-accent pattern from static prototypes. Prototype palette and
  information hierarchy may be reused, but colored card rails and top stamps are not part of
  the production console design.
- Exceptions are limited to non-content mechanics whose meaning depends on position: the
  Activity Bar's active-navigation marker, drag-and-drop insertion indicators, loading
  spinners, charts, graph edges, progress meters, focus outlines, and the shared transient
  content-update top-edge shimmer. These exceptions MUST NOT be repurposed as card or panel
  decoration.

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
- Runtime services: **AKS Standard** is the new-install default for the five packaged services.
  Core stays non-privileged and only internal Executor may hold effect authority. Prebuilt, signed,
  digest-pinned OCI images and runtime-neutral specs render to Kubernetes `Deployment`, `Service`,
  `ServiceAccount`, HPA, PDB, `NetworkPolicy`, and `CronJob`; tenant provisioning MUST NOT build or
  capture images. Existing Container Apps installations are compatibility/migration sources. See
  [../../docs/roadmap/architecture/service-decomposition-execution-plan.md](../../docs/roadmap/architecture/service-decomposition-execution-plan.md).
- Light triggers: AKS `CronJob` resources use the portable schedule contract.
- Audit/state/KPI + T1 vectors: **PostgreSQL Flexible** with **pgvector** co-located. Dev uses Burstable
  without HA; production requires zone-redundant HA plus geo-redundant backup. Cosmos DB is considered
  only if RU-metering and geo-distribution outgrow this boundary.
- Secrets: apps read env/mounted Secrets only; AKS uses managed Key Vault CSI with workload identity, never an app secret SDK.
- PR gate: **GitHub App** (Checks API) or Azure DevOps service hooks.
- HIL approval: **Bot Framework / Teams** Adaptive Cards (Azure Bot Free tier).
- Execution identity: **user-assigned Managed Identity** + action whitelist (least privilege), exposed
  as an **OIDC token** via `WorkloadIdentity` so IRSA / GCP Workload Identity / SPIRE remain additive.
  `DefaultAzureCredential()` and similar SDK entry points stay in the Azure adapter, never `core/`.
- Observability: **Log Analytics** + **App Insights**; default 30-day retention, UI-configurable.

### AKS Basic and Private-Network Stages

- Basic deployment reserves workload and API-server subnets, enables API Server VNet Integration and workload identity, and keeps authenticated, policy-restricted public management access.
- After baseline health, `/provisioning` MAY request peering, private endpoints/DNS, private-cluster mode, public-access removal, and egress controls through the protected executor.
- Before closing the last public path, the executor MUST prove routes, DNS, TLS, identities, AKS API, registry, state, Key Vault, PostgreSQL, Event Hubs, and rollback.
- Policy-required day-zero privacy MUST use an eligible internal host and exact private plan, never weakened policy.

## Failure Modes

- **Console down** - operations continue; core engine, PR gate, and ChatOps are unaffected.
- **ChatOps down** - high-risk HIL items queue and alert via fallback; nothing auto-executes without approval.
- **Event-bus backpressure** - use ordering plus dead-letter queues; the core reprocesses without dropping events.
- **Any layer** that triggers a state change owes all seven safeguards (see coding conventions and security/identity).

## Anti-Patterns (avoid)

- **Monolithic web app that does everything** - always-on cost, violates autonomy, hard to port.
- **UI buttons that execute actions** - breaks least privilege; PR-native supplies audit, rollback, and approval.
- **Always-on polling daemons** - conflicts with the event-driven, scale-to-zero principle.
- **Shared identity across layers** - a console or bot reusing the executor identity collapses
  the approval/execution boundary.
- **Actions without a rollback or audit path** - any change delivered outside git must still
  provide both, or it is incomplete.
