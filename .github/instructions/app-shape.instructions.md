---
description: Deployment topology, app shape, and anti-patterns.
applyTo: "**"
---

# App Shape

Not one big web app. The system is a **headless control plane + thin console + ChatOps**,
serving three initial verticals under an AIOps approach — Resilience, Change Safety, and
Cost Governance. A large always-on UI would contradict the "minimize human intervention"
goal.

The layers are **loosely coupled**: they communicate through the event bus and git, not
direct in-process calls, so any layer can fail or scale independently. See
[architecture.instructions.md](architecture.instructions.md) for the trust-routing control
loop and [../../docs/roadmap/deployment.md](../../docs/roadmap/deployment.md) for how the
shape maps to environments and CI/CD.

## Layers

| # | Layer | Shape | Scales to zero | Rationale |
|---|-------|-------|----------------|-----------|
| 1 | **Core engine** | headless, event-driven backend (no UI) — trust router, T0/T1/T2, risk gate, executor | yes | wakes on events; Azure adapter today, other CSPs TBD behind the same interface |
| 2 | **Action delivery** | GitOps / PR-native (GitHub App or Azure DevOps) — actions are remediation PRs/IaC | n/a (git-hosted) | audit, rollback, and approval already exist in git |
| 3 | **Operator console** | thin, read-only SPA — KPI dashboard, audit log, shadow results, HIL queue view | yes (static hosting) | minimal read surface; never executes actions itself |
| 4 | **Human channel** | ChatOps (Teams bot + Adaptive Cards) — high-risk HIL approvals and alerts | yes (event-driven) | reach operators where they already are |
| 5 | **Rule catalog** | catalog-as-code (git repo) — versioned rules | n/a (git-hosted) | the update pipeline lands rules via PR |

- **Brain = core engine (1); hands = action delivery (2); human touchpoints = console (3) +
  ChatOps (4); memory = rule catalog (5).**
- The core is **CSP-neutral by design**: cloud access sits behind adapters (policy in OPA,
  IaC in Terraform). **Azure is the only implemented target**; non-Azure providers are
  TBD (see [Implementation Focus](../copilot-instructions.md#implementation-focus-must)) and
  the neutral abstractions exist so a future adapter can be added without a core rewrite.
  See [../../docs/roadmap/tech-stack.md](../../docs/roadmap/tech-stack.md).

## Layer Boundaries (security)

- The **console is read-only**: it renders state and the HIL queue but issues no privileged
  calls. Approvals flow through ChatOps or PR, never console buttons.
- The **executor holds the only privileged identity** (user-assigned Managed Identity, scoped
  to an action whitelist). Console and ChatOps never share it.
- **Approval and execution are distinct principals** — no self-approval. See
  [../../docs/roadmap/security-and-identity.md](../../docs/roadmap/security-and-identity.md).

## Azure Mapping (draft — reconfirm preview services at adoption time)

Azure is the implemented target (see
[Implementation Focus](../copilot-instructions.md#implementation-focus-must)); the shape stays
CSP-neutral in design by rendering four wire-level contracts (event bus, runtime, secret,
workload identity) into Azure resources — see
[../../docs/roadmap/csp-neutrality.md](../../docs/roadmap/csp-neutrality.md). The mapping is
**minimum-cost-set first** — the concrete inventory, tiers, and rationale live in
[../../docs/roadmap/deploy-and-onboard.md](../../docs/roadmap/deploy-and-onboard.md#azure-resource-inventory-minimum-set).
Recommended mapping:

- Event bus: **Event Hubs Standard** consumed **only through its Kafka endpoint on `:9093`**
  (Kafka wire protocol is the CSP-neutral contract); Service Bus and Event Grid are **not**
  in the day-zero inventory. Where a native Azure signal is needed (Activity Log, resource
  events), it is forwarded into a Kafka topic on Event Hubs — the core sees Kafka only.
- Core consumer: **Azure Container Apps** (Consumption, KEDA scale + scale-to-zero) — **one
  app with sidecar containers** for the core subsystems (`event-ingest` primary, others as
  sidecars); AKS only if heavier scaling profiles emerge later. The app ships as an **OCI
  image + a Knative-compatible manifest subset**, rendered into `containerapp` resources by
  IaC. **Dapr sidecars and Envoy-specific ingress rules are prohibited** to keep the runtime
  contract portable.
- Light triggers: **Container Apps Jobs** in the same environment for out-of-band change
  detection and cost-anomaly probes (avoids provisioning a separate Functions plan); rendered
  from the same manifest as a K8s `CronJob` on non-Azure targets.
- Audit/state/KPI + T1 vectors: **PostgreSQL Flexible** (Burstable, 1 zone) with **pgvector**
  co-located; Cosmos DB only if RU-metering and geo-distribution outgrow a single primary.
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

- **Console down** — operations continue; core engine, PR gate, and ChatOps are unaffected.
- **ChatOps down** — high-risk HIL items queue and alert via a fallback; nothing auto-executes
  without approval.
- **Event-bus backpressure** — rely on ordering plus dead-letter queues; the core reprocesses,
  it does not drop events.
- **Any layer** that triggers a change still owes a stop-condition, rollback path,
  blast-radius limit, and audit entry (see coding-conventions and security-and-identity).

## Anti-Patterns (avoid)

- **Monolithic web app that does everything** — always-on cost, violates autonomy philosophy,
  hard to port across clouds.
- **UI buttons that execute actions** — forces custom audit/rollback and breaks least
  privilege; PR-native gets audit, rollback, and approval for free.
- **Always-on polling daemons** — conflicts with the event-driven, scale-to-zero principle.
- **Shared identity across layers** — a console or bot reusing the executor identity collapses
  the approval/execution boundary.
- **Actions without a rollback or audit path** — any change delivered outside git must still
  provide both, or it is incomplete.

> One line: brain = headless event-driven control plane, hands = GitOps/PR,
> human touchpoint = thin console + Teams bot.
