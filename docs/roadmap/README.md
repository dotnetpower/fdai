# AIOpsPilot Roadmap

Detailed, phased plan to build the autonomous cloud operations control plane — an **AIOps**
approach whose initial verticals are **Resilience**, **Change Safety**, and **Cost
Governance**. Other AIOps domains (posture management, SRE/SLO, etc.) fit the same
architecture and are future scope. This folder expands the short-form principles in
[copilot-instructions.md](../../.github/copilot-instructions.md) and the
control-loop design in
[architecture.instructions.md](../../.github/instructions/architecture.instructions.md) into an
actionable engineering roadmap: from goals and structure through deployment and scale-out.

> Scope reminder: this repo is **generic and customer-agnostic**. Everything here is
> parameterized; per-customer values live in a fork. See
> [generic-scope.instructions.md](../../.github/instructions/generic-scope.instructions.md).
>
> **Implementation focus:** Azure is the only implemented target. Non-Azure providers and
> Phase 4 multi-cloud expansion are **TBD** — the CSP-neutral abstractions in these docs
> exist so a future adapter is additive, not a delivery commitment. See
> [copilot-instructions.md](../../.github/copilot-instructions.md#implementation-focus-must).

## How to Read This Folder

Reference docs (1–13) describe the system; phase docs (P0–P4) sequence the build. Read the
reference docs first, then the phases in order.

| # | Document | What it covers |
|---|----------|----------------|
| 1 | [goals-and-metrics.md](goals-and-metrics.md) | success criteria, KPIs, measurement-first rule |
| 2 | [project-structure.md](project-structure.md) | repo layout, module boundaries, control-loop wiring |
| 3 | [tech-stack.md](tech-stack.md) | languages, frameworks, data stores, event bus |
| 4 | [csp-neutrality.md](csp-neutrality.md) | wire-level contracts (event bus / runtime / secret / workload identity) that keep the core CSP-neutral |
| 5 | [llm-strategy.md](llm-strategy.md) | which models per tier, mixed-model gate, abstraction |
| 6 | [security-and-identity.md](security-and-identity.md) | least-privilege identity, secrets, safety invariants |
| 7 | [deployment.md](deployment.md) | IaC, CI/CD, environments, release/rollback |
| 8 | [rule-catalog-collection.md](rule-catalog-collection.md) | where rules/checklists/baselines come from and their YAML shape |
| 9 | [rule-governance.md](rule-governance.md) | how admins author, scope, enable, and exempt rules (Azure Policy-like) |
| 10 | [observability-and-detection.md](observability-and-detection.md) | event correlation, anomaly detection, forecasting, and root-cause analysis |
| 11 | [deploy-and-onboard.md](deploy-and-onboard.md) | concrete Azure resource inventory, bootstrap sequence, fork ↔ core split |
| 12 | [startup-and-lifecycle.md](startup-and-lifecycle.md) | cold start, day-zero catalog, shadow-first rollout, discovery-loop kickoff |
| 13 | [operating-and-verification.md](operating-and-verification.md) | self-health signals, canary event, smoke tests, alert routing, runbooks |
| 14 | [cost-model.md](cost-model.md) | illustrative monthly cost envelope for the minimum resource inventory, T2 LLM cost split, traffic scaling triggers |
| 15 | [user-rbac-and-identity.md](user-rbac-and-identity.md) | human user roles (Reader/Contributor/Approver/Owner + Break-Glass), Entra ID artifacts, console→PR identity flow |
| 16 | [channels-and-notifications.md](channels-and-notifications.md) | non-web-UI channels (Teams / Slack / email / webhook / pager / SMS), category & trust-tier matrix, routing policy |
| 17 | [risk-classification.md](risk-classification.md) | auto vs HIL vs deny classification: dimensions, initial rule table, environment detection, change process |

## Design at a Glance

Deterministic-first, event-driven, risk-gated. A 3-tier trust router resolves repeatable events
with rules and policies (T0) and lightweight similarity reuse (T1), reserving frontier-model
reasoning (T2) for the ambiguous residual. The T0/T1 coverage share and every autonomy
multiplier are **design targets that require a measured baseline** before they can be claimed
(see [goals-and-metrics.md](goals-and-metrics.md) and
[architecture.instructions.md](../../.github/instructions/architecture.instructions.md)).

## Phase Timeline

```mermaid
timeline
    title AIOpsPilot Delivery Phases
    P0 Instrumentation : KPI telemetry : Baseline vs reference agent : Unblock identity and policy
    P1 Rule Catalog and T0 : Normalize checklists : Policy-as-code gate : Auto remediation PR : Out-of-band detection
    P2 Quality and T1 : Continuous rule update : LLM quality gate and mixed-model : Embedding pattern reuse : Shadow to enforce
    P3 Integrated Loop : Unified control loop : DR-Chaos scheduler and DB DR : FinOps auto-actions
    P4 Scale : Continuous measurement : Pattern-library and model tracking : Scalability : Multi-cloud expansion (TBD)
```

Phases are **strictly sequential** — P0 → P1 → P2 → P3 → P4 — and each phase doc names its
predecessor in a *Dependencies* section. Vertical coverage lands incrementally: Change Safety
in P1, Resilience and Cost Governance in P3. **Multi-cloud is TBD in P4** (Azure is the only implemented
target — see
[Implementation Focus](../../.github/copilot-instructions.md#implementation-focus-must)).

## Phase Summary

The exit column is each phase's **primary gate**; every phase doc lists the complete exit
criteria and its dependencies.

| Phase | Goal | Key deliverables | Primary exit gate |
|-------|------|------------------|-------------------|
| **[P0](phases/phase-0-instrumentation.md)** | Instrument & unblock | KPI dashboard, baseline report, identity/policy blockers resolved | reproducible baseline exists |
| **[P1](phases/phase-1-rule-catalog-t0.md)** | Deterministic core | rule catalog, T0 engine, policy gate, remediation PRs | Change gate runs in shadow |
| **[P2](phases/phase-2-quality-and-t1.md)** | Quality & lightweight tier | rule-update pipeline, LLM quality gate (guards T2), T1 similarity reuse | auto-resolution rate validated vs P0 baseline |
| **[P3](phases/phase-3-integrated-loop.md)** | Integrated autonomy | unified loop, DR/chaos scheduler, cost auto-actions | autonomous MVP across all 3 verticals |
| **[P4](phases/phase-4-scale.md)** | Scale out (Azure) | continuous measurement, pattern-library and model tracking, scalability; **multi-cloud adapters TBD** | guard metrics stable on the Azure baseline |

## Guardrails Applied Throughout

- **Measurement first**: no autonomy without telemetry; no multiplier or coverage claim without a measured baseline.
- **Shadow before enforce**: every new action ships judge-only, then is promoted per-action explicitly; regressions demote automatically.
- **Fail toward safety**: low confidence, verification failure, or budget/rate overflow degrades to HIL — never to an ungated auto-action.
- **Safety invariants on every action**: stop-condition, rollback path, blast-radius limit, and audit-log entry ([security-and-identity.md](security-and-identity.md)).
- **Idempotent actions**: re-delivered events and retried actions never double-apply.
- **Separation of duties**: approval and execution are distinct principals; the console is read-only ([security-and-identity.md](security-and-identity.md)).
- **English-only, customer-agnostic artifacts** ([generic-scope.instructions.md](../../.github/instructions/generic-scope.instructions.md)); Korean only in maintainer chat.
