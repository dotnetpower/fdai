---
title: Phase 4 - Scale (Azure); Multi-Cloud (TBD)
---
# Phase 4 - Scale (Azure); Multi-Cloud (TBD)

**Goal**: keep the Azure baseline honest as the system scales - continuous measurement,
pattern-library growth, model cost/quality tracking, and performance/scalability - so the
target multipliers stay **validated against the measured baseline** rather than asserted. No
multiplier is claimed here; Phase 4 keeps the Phase 0 evidence current as the system scales.
**Multi-cloud expansion is deferred (TBD)**; the sections below marked *TBD (deferred)* are
retained as forward-looking design and are not built in this roadmap until a non-Azure target
is explicitly scoped (see
[Implementation Focus](../../../.github/copilot-instructions.md#implementation-focus-must)).

This phase builds on the Phase 0-3 core and does not change it. It realizes the CSP-neutral
principles in
[architecture.instructions.md](../../../.github/instructions/architecture.instructions.md) and
[app-shape.instructions.md](../../../.github/instructions/app-shape.instructions.md) as
**design invariants** (adapter surfaces, normalized schemas) so a future non-Azure adapter is
additive; it reuses the stack and adapter boundaries in [tech-stack.md](../architecture/tech-stack.md), is
measured strictly by [goals-and-metrics.md](../architecture/goals-and-metrics.md), and inherits the identity
and shadow-mode rules in [security-and-identity.md](../architecture/security-and-identity.md).

## Deliverables

The module reference lists the primary Python package that carries the deliverable in
[`src/fdai/`](../architecture/project-structure.md); every module listed here is
customer-agnostic and Azure-only in intent (multi-cloud deliverables below stay TBD).

- Continuous measurement/improvement loop on the Azure baseline with automatic regression
  demotion.
  Module:
  [core/measurement/regression.py](../../../src/fdai/core/measurement/regression.py).
- Pattern-library (T1) growth with anti-overfitting guards.
  Module:
  [core/measurement/pattern_growth.py](../../../src/fdai/core/measurement/pattern_growth.py).
- Model cost/quality tracking with measurement-driven swaps.
  Module:
  [core/measurement/model_tracking.py](../../../src/fdai/core/measurement/model_tracking.py).
- Scalability/performance validation on Azure (per-tier latency budgets, event-driven
  scale-to-zero preserved).
  Module:
  [core/measurement/latency_budget.py](../../../src/fdai/core/measurement/latency_budget.py).
- Scheduled runners that wire the two library-only measurement components into Container
  Apps Jobs - an automated-baseline regression runner (daily replay of the P0 scenario set,
  auto-demotes on regression) and a pattern-growth intake runner (drains the audit stream,
  ingests accepted patterns in shadow only, never auto-promotes).
  Module:
  [core/measurement/runners.py](../../../src/fdai/core/measurement/runners.py).
  Infra:
  [infra/modules/measurement-runners/](../../../infra/modules/measurement-runners).
- **TBD (deferred)**: multi-cloud expansion of policy and execution via **provider adapters**
  (no new core), cross-CSP rule-catalog normalization, per-CSP execution identity, and the
  multi-cloud event-bus decision (OD-3 in [tech-stack.md](../architecture/tech-stack.md)). These items
  remain as design shape only until non-Azure work is scoped.

## Provider Adapter Boundary (TBD - deferred)

> This section is retained as **design invariant** for a future non-Azure target. It is
> **not built in this phase**; see
> [Implementation Focus](../../../.github/copilot-instructions.md#implementation-focus-must).

The core engine stays CSP-neutral; a new cloud would be added by implementing adapters, never
by forking the core. The adapter surface is fixed and each adapter is added behind an existing
interface (see [project-structure.md](../architecture/project-structure.md)):

- **Policy adapter** - evaluates the same OPA/Rego policies with provider-parameterized inputs;
  no per-cloud policy fork.
- **IaC / executor adapter** - applies remediation via Terraform/OpenTofu providers; emits the
  remediation PR, honoring the four safety invariants (stop-condition, rollback, blast-radius,
  audit) per CSP.
- **Identity adapter** - supplies the scoped execution principal (see below).
- **Event-source / bus adapter** - normalizes provider events into the versioned internal
  schema at ingress.
- **State-store adapter** - keeps audit/pattern-library/KPI storage portable.

Rigor requirements (apply when a non-Azure adapter is eventually scoped):

- No vendor SDK is imported by the core engine; SDK calls live only inside an adapter, per
  [coding-conventions.instructions.md](../../../.github/instructions/coding-conventions.instructions.md).
- Every adapter ships with **contract/parity tests** proving identical externally observable
  behavior (same normalized event → same tier decision → same action shape) across CSPs.
- Provider selection is configuration, not code branches in the core.

## Multi-Cloud Rule Catalog (TBD - deferred)

> Deferred until a non-Azure target is scoped. Azure remains the only implemented catalog
> target; see [rule-catalog-collection.md](../rules-and-detection/rule-catalog-collection.md).

- Add sources: **AWS** (Well-Architected, Config managed rules, CIS AWS) and **GCP**
  (Recommender, Policy Controller / Gatekeeper constraints, CIS GCP), alongside the existing
  Azure and OSS sources from
  [phase-1-rule-catalog-t0.md](phase-1-rule-catalog-t0.md).
- **Normalize** every rule to the common CSP-neutral schema
  (`id, version, source, severity, category, resource-type, check-logic, remediation,
  provenance`) so a rule reads the same regardless of origin cloud.
- **Cross-CSP conflict handling**: when rules from different clouds or sources match one event,
  deduplicate by `id`, resolve precedence by severity then source priority, and **escalate ties
  to HIL** rather than auto-picking. Provenance records the originating source and version so a
  rule change is traceable and reversible.
- New sources flow through the existing update pipeline
  (`source watcher → collect → shadow eval → regression → promote / rollback`,
  [phase-2-quality-and-t1.md](phase-2-quality-and-t1.md)); promotion requires the regression
  suite to pass with zero policy-violation escapes.

## Per-CSP Identity and Least Privilege (TBD - deferred)

> Deferred; Azure identity model applies today (user-assigned Managed Identity, action
> whitelist, distinct approval/execution principals - see
> [security-and-identity.md](../architecture/security-and-identity.md)).

- Each cloud gets its **own scoped execution identity** (e.g. Azure user-assigned Managed
  Identity, AWS IAM role, GCP service account), each restricted to an action whitelist. No
  identity is shared across clouds or across layers.
- **Approval and execution remain distinct principals** in every cloud - no self-approval - per
  [security-and-identity.md](../architecture/security-and-identity.md).
- Blast-radius limits (scope/batch/rate caps) are enforced per CSP; a misconfigured adapter
  cannot exceed the whitelist.

## Event Bus Portability (TBD - deferred)

> Deferred; on Azure the bus is Event Hubs through its Kafka endpoint (see
> [tech-stack.md](../architecture/tech-stack.md#od-3-multi-cloud-event-bus-phase-4--tbd)).

- Decide OD-3 only when a non-Azure target is scoped. Validate which managed Kafka or other
  log implementation preserves the existing Kafka-wire ordering, replay, and DLQ contract.
- Decision criteria: **ordering, dead-letter, replay, and idempotency parity** across clouds,
  operational cost, and CSP neutrality - the bus adapter must preserve per-resource ordering and
  at-least-once + idempotent processing regardless of backend.
- Record the non-Azure outcome as a decision record and update
  [tech-stack.md](../architecture/tech-stack.md) OD-3.

## Safety and Shadow-First Rollout

- Any newly added capability ships in **shadow mode** (judge-and-log, no execution) until its
  shadow accuracy is measured with zero policy-violation escapes; promotion to enforce is
  explicit and per-action, matching
  [architecture.instructions.md](../../../.github/instructions/architecture.instructions.md).
  When a non-Azure adapter is eventually scoped (TBD), the same shadow-first rule applies to
  the adapter's first actions.
- Any regression demotes the affected action back to shadow automatically.

## Continuous Measurement and Improvement

- Re-run **baseline vs treatment** periodically on the frozen, versioned scenario set; a
  **regression** is a guard-metric breach or a success-metric drop beyond the reported
  confidence interval, and it triggers automatic demotion to shadow
  ([goals-and-metrics.md](../architecture/goals-and-metrics.md)).
- Guard metrics (CFR, false-positive/negative, rollback rate, and the **exactly-0**
  policy-violation escapes) are evaluated on the same measurement window and scenario-set
  version as the success metrics, so a gain and a breach are never compared across different
  data.
- Watch leading indicators **per environment** (per-tier coverage drift, mixed-model
  disagreement, verifier abstain/fail) so regressions are caught before a lagging guard
  metric moves. Per-cloud breakdown is a **TBD** design invariant, activated only when a
  non-Azure adapter is scoped.
- Re-baseline on every scenario-set version bump so targets track a current, fair reference.

## Pattern Library Growth (T1)

- Feed the pattern library only from **auto-resolved, non-rolled-back, verified** production
  outcomes; failed, reverted, or HIL-overridden actions must not become reusable patterns.
- New patterns enter in **shadow** and are shadow-evaluated before they can drive a T1 action -
  the library cannot self-promote.
- Guard against feedback-loop overfitting: validate candidate patterns on a temporal holdout
  (patterns learned before a cutoff, tested after) and monitor the T1 false-positive rate as a
  guard; a rising rate demotes the offending patterns. Growth must raise auto-resolution
  **without** regressing guard metrics.

## Model Cost/Quality Tracking

- Track per-model cost and quality over time from the cost/usage and telemetry sources in
  [goals-and-metrics.md](../architecture/goals-and-metrics.md); swap the T2 reasoner models by **measured
  results, not assumption**, keeping model IDs and thresholds as config per
  [llm-strategy.md](../architecture/llm-strategy.md).
- Flag model deprecation/price changes and re-validate the mixed-model cross-check on the
  scenario set before any swap reaches enforce.

## Scalability and Performance

- Preserve per-tier latency budgets and the event-driven, scale-to-zero posture on Azure as
  event volume grows. Multi-cloud performance parity is TBD (deferred).
- Graduate T1 vector search from pgvector to a dedicated vector store when the corpus or
  recall/latency targets demand it (criteria in [tech-stack.md](../architecture/tech-stack.md)); the state
  adapter keeps this transparent to the core.
- For **hyperscale tenants (300 subscriptions across dozens of landing zones)**, the scale-out
  topology (cell-based streaming, policy-driven fan-in, two-plane logging, CQRS audit
  indexing, and selectable **standard / sovereign** deployment profiles) is specified in
  [hyperscale-cell-architecture.md](../architecture/hyperscale-cell-architecture.md). It is entered only
  when a tenant crosses the hyperscale trigger and preserves every safety invariant and all
  eight CSP-neutral contracts.

## Runtime Scale-Out (AKS) - Deferred

> **Container Apps is the default runtime** (min-cost day-zero and the `standard` hyperscale
> profile). AKS is **deferred** - adopted only by the `sovereign` profile (self-host
> observability + region-in LLM + confidential nodes) or a heavy cell that presses Container
> Apps limits. Portability is guaranteed by the runtime contract (OCI image +
> Knative-compatible manifest subset, no Dapr / no Envoy-specific ingress in
> [csp-neutrality.md](../architecture/csp-neutrality.md#2-runtime-contract---oci-image--knative-compatible-manifest)),
> so an AKS move is an `infra/modules/runtime/aks/` render, never a `core/` rewrite.

- **When AKS:** the `sovereign` profile needs it (LGTM / ClickHouse / region-in LLM run as AKS
  workloads; confidential SEV-SNP nodes; private cluster), or a heavy cell needs node-level
  control (spot / GPU / large-memory SKUs), DaemonSet collection, or partition-sticky
  StatefulSet consumers. The full rationale and profile matrix live in
  [hyperscale-cell-architecture.md § Runtime](../architecture/hyperscale-cell-architecture.md#runtime).
- **Scope:** a new `infra/modules/runtime/aks/` sub-module renders the same OCI image and
  Knative-compatible manifest subset to AKS (KEDA scaler preserved); Container Apps Jobs render
  to K8s CronJobs and native secrets to External Secrets Operator, matching
  [app-shape.instructions.md](../../../.github/instructions/app-shape.instructions.md).
- **Non-goal:** AKS does not change the control loop, the safety invariants, or any wire
  contract; it is a deployment target, not a new autonomy surface. Dapr and Envoy-specific
  ingress stay prohibited to keep the runtime contract portable.

## Exit Criteria

- Continuous measurement shows **no regression** in any guard metric on the stated Azure
  measurement window, with policy-violation escapes held at exactly 0.
- Multiplier targets (metrics 1-4) are **demonstrated with statistical evidence** (sample
  size, confidence interval, scenario-set version) against the Azure baseline - reported as
  multipliers plus absolute values, never asserted.
- Pattern-library growth raises auto-resolution **without** regressing guard metrics on the
  temporal holdout.
- **Multi-cloud portability is not an exit criterion for this phase** - it is deferred (TBD)
  and will be scoped in a future phase (see
  [Implementation Focus](../../../.github/copilot-instructions.md#implementation-focus-must)).

## Open Questions

- Vector-store graduation criteria and migration path (pgvector → dedicated store).
- Regression-window and confidence-interval settings for the continuous measurement loop on
  Azure.
- **TBD (deferred)**: which second cloud to onboard first and its shadow-to-enforce
  sequencing; event-bus migration path if OD-3 later selects a new backend; cross-CSP cost
  attribution and currency normalization for metric 1.

## Dependencies

- P3 integrated autonomous MVP with safety invariants enforced across all three verticals
  ([phase-3-integrated-loop.md](phase-3-integrated-loop.md)).
