---
title: Goals and Metrics
---
# Goals and Metrics

The roadmap optimizes for **autonomy with proof**. Every autonomy claim is backed by a
measured baseline; nothing is asserted from estimation. Improvement factors below (`5×`,
`large reduction`, `1/5`) are **targets**, not achieved results - they may only be stated as
achieved once both the reference baseline and the FDAI treatment have been measured on
the same scenario set (see the [measurement-first rule](#measurement-first-rule)).

This document is the source of truth for KPIs. It aligns with the tier coverage targets in
[architecture.instructions.md](../../../.github/instructions/architecture.instructions.md) and is
operationalized by [phase-0-instrumentation.md](../phases/phase-0-instrumentation.md).

## Implementation status

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| Deterministic KPI and guard-metric aggregation | implemented | `core/measurement/mttr.py`; `dora.py`; `regression.py`; focused tests under `tests/core/measurement/` | MTTR, change, regression, latency, model, and pattern metrics have executable reducers and fail-closed checks. |
| Promotion and operational evidence evaluation | implemented | `core/measurement/promotion_gate.py`; `operational_promotion.py`; focused promotion tests | Promotion evaluation binds revision, scenario, samples, confidence, guards, and outcome evidence. A result can be ready only when a current shared decision-evidence admission matches the complete batch. Legacy stored receipts remain readable but cannot authorize promotion without receipt and verification-bundle digests. |
| Governed operational coverage claim contract | implemented | `packages/service-contracts/src/fdai_service_contracts/operational_coverage.py`; `packages/service-contracts/tests/test_operational_coverage.py` | Immutable denominator, terminal disposition, freshness, exact basis-point, zero-tolerance, and digest checks prevent an incomplete universe from becoming a 99% claim. The receipt grants no execution authority. |
| Canonical decision-critical evidence envelope | implemented | `packages/service-contracts/src/fdai_service_contracts/decision_evidence.py`; `schemas/decision-critical-evidence/1.0.0.json`; focused contract tests | The envelope binds the evidence and its authentication proof, authority, scope, purpose, exact producer and method, time, policy-derived freshness, completeness proof, conflict disposition, provenance, and synthetic status. Claim preflight can only reject input or pass it to separate authoritative verification; it never claims live readiness. Existing decision boundaries still require migration. |
| Independent decision-evidence verification | implemented | `decision_evidence_verification.py`; `core/readiness/decision_evidence.py`; `shared/providers/decision_evidence_verifier.py`; `delivery/azure/decision_evidence.py`; focused contract, readiness, and Azure adapter tests | Five content-addressed proofs cover authentication, evidence, completeness, conflict, and freshness policy. Core emits a short-lived no-authority admission only after a current trusted bundle passes. ChatOps qualification, operational promotion, secured ontology query consumption, operational-context state evidence, analyzer target selection, and startup readiness now rebind that admission to their complete inputs. Runtime provider composition and the remaining operational-readiness and direct-state boundary migrations remain open. |
| Frozen scenario-set accounting | in-progress | `tests/scenarios/manifests/v2026.07.json`; `test_frozen.py`; `test_v2026_07_replay.py` | The SRE pack now has four executable dimensions. Successful full-loop and cross-objective conflict evidence remain open, and the other four packs are also incomplete. |
| Live KPI baseline, treatment, and dashboard closure | in-progress | [Data Collection and Telemetry](#data-collection-and-telemetry); `config/constitution-traceability.json` requirement `FDAI-CONST-002` | Runtime records and jobs exist, but no retained full live baseline/treatment cohort proves all success and zero-threshold guard metrics on one pinned revision. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-08-29 | implemented | Migrated startup readiness before persistence and transition publication. The coordinator binds the complete reduced report and probe-set revision to a current admission. Missing or rejected admission changes a non-blocked result to `DEGRADED`, caps every capability at `SHADOW`, and persists the rejection reasons instead of a `READY` claim. | `current change`; readiness models, coordinator, runtime composition, focused coordinator and runtime tests; Ruff and strict mypy. | Bind the startup coordinator to the production verifier registry and retain one live report bundle. Migrate operational-readiness and remaining direct-state boundaries. |
| 2026-08-29 | implemented | Migrated analyzer target selection when a projected Resource carries state metadata. The resolver derives exact state and resource-scope digests, requests a trusted admission, and skips the target with `unverified_state_fact` when the provider is absent or the admission does not match. Resources with identity and type but no state claim preserve the existing eligible path. | `current change`; analyzer target resolver and focused routed-tick tests; Ruff and strict mypy. | Bind the analyzer job to the trusted admission provider and migrate the remaining direct-state consumers. |
| 2026-08-29 | implemented | Migrated operational-context state evidence to the shared admission. Each bundle retains the admission in its replay identity, recomputes the exact state-item and scope digests without a circular commitment, and lowers to `SHADOW_ONLY` with an explicit hold when admission is absent, mismatched, or expired. | `current change`; operational evidence models, identity, builder, shared admission mapping, and focused bundle/materializer checks; Ruff and strict mypy. | Bind an authoritative state admission producer and migrate direct state consumers. Readiness and runtime composition remain open. |
| 2026-08-29 | implemented | Migrated secured ontology query consumption to the shared admission contract. Query results may still be retained for diagnosis, but dependency resolution and decision-critical FunctionType verification require a current admission bound to the exact projected result, scope, purpose, ontology release, and source generation. The production admission-provider seam is unbound and therefore fails closed. | `current change`; query authority, source handlers, semantic composition, and focused query and composition checks; Ruff and strict mypy. | Bind the production query admission provider to the trusted verifier registry and retain a cross-service receipt and bundle. Migrate readiness and state boundaries. |
| 2026-08-29 | implemented | Migrated operational promotion readiness to the shared decision-evidence admission. The evaluator binds the exact batch, revision, scenario, ActionType, purpose, and validity window, persists both receipt and verification-bundle digests, and cannot produce a ready receipt without them. Storage reads legacy 1.0 receipts for diagnosis, while both the registry and direct executor reject them for enforcement. | `current change`; operational promotion evaluator, risk registry, persistence codec, direct executor, and focused promotion tests; Ruff and strict mypy. | Bind the production promotion evidence source to the independent verifier registry. Migrate the remaining readiness, query, and state boundaries. |
| 2026-08-29 | implemented | Added a short-lived no-authority admission emitted only by successful independent decision-evidence verification, then migrated ChatOps qualification to derive exact batch evidence and scope digests and fail closed on an absent, mismatched, or expired admission. The standalone qualification CLI remains diagnostic and cannot claim qualification without a verifier binding. | `current change`; shared verifier seam, Core readiness gate, ChatOps qualification reducer, focused unit and CLI checks, Ruff, and strict mypy. | Bind the verifier registry in runtime composition and migrate the remaining readiness, query, state, and promotion decision boundaries. Retain a production qualification receipt and bundle before claiming a validated cohort. |
| 2026-08-29 | implemented | Added the independent verifier contract and readiness gate for all five decision-critical proof classes. Versioned verifier bindings now carry trust anchors, validity windows, and revocation state. Verification fails closed for an absent or stale binding, producer self-verification, receipt or subject mismatch, expired proof, timeout, and synthetic evidence. The Azure adapter authenticates authoritative readback with Managed Identity and never returns or stores the access token. | `current change`; service-contract model and registered Draft 2020-12 schema, provider-neutral verifier seam, Core readiness gate, Azure adapter, and focused contract, readiness, and Azure adapter tests. | Bind the verifier registry in runtime composition and migrate each existing readiness, query, state, promotion, and qualification boundary before changing FDAI-CONST-002 from `partial`. |
| 2026-08-29 | implemented | Added the provider-neutral `DecisionCriticalEvidenceReceipt` foundation required by FDAI-CONST-002. Its canonical digest binds the evidence payload, authentication proof, authority class, source, scope, purpose, producer and method versions, source revision, event and recorded time, policy-derived freshness, completeness and conflict proofs, provenance, synthetic status, and no-authority flag. Review blocked a positive live-eligibility result from self-attested fields, so the contract now only rejects invalid claims or passes them to a separate authoritative verifier. The registered schema boundary also runs the semantic model checks that JSON Schema cannot express. | `current change`; service-contract model, Draft 2020-12 schema plus semantic validation, package registry and exports, traceability record, and focused contract tests. | Implement trusted authentication, evidence, completeness, conflict, and policy verifiers while migrating readiness, query, state, promotion, and qualification boundaries before changing FDAI-CONST-002 from `partial`. |
| 2026-08-29 | in-progress | Added truthful A3-E non-applicability evidence for `sre.slo-signal-source-unmapped.002`. The replay now proves the routing terminal produces no finding or T2 Action, never enters execution-authorization evaluation, emits no execution result or PR, and records the abstain. Review rejected two proposed claims: a publisher's own in-memory record is dispatch evidence rather than independent SRE effect verification, and hand-authored candidates sent directly to `PrecedenceResolver` do not prove runtime arbitration. Those tests and manifest claims were removed before commit. | `current change`; `services/core-control-plane/tests/scenarios/test_v2026_07_replay.py`; `manifests/v2026.07.json`; focused scenario, manifest, Ruff, and strict mypy checks. | `successful_full_loop` still requires independent authoritative recovery and recurrence-closure evidence. `cross_objective_conflict` still requires competing actions produced and audited through the scenario runtime and production arbitration path. The non-synthetic baseline and treatment also remain open. |
| 2026-08-29 | implemented | Hardening round 1 reviewed 22 coverage-contract lenses and normalized all receipt timestamps to UTC before digesting, so equivalent instants with different offsets share one replay identity. | `current change`; focused operational coverage tests. | Bind authoritative producers and retain governed receipts. |
| 2026-08-28 | implemented | Added one provider-neutral operational coverage receipt for asset inventory, governance evaluation, operating scope, incident diagnosis, remediation effects, and knowledge grounding. It keeps policy outcome separate from evaluability, retains every uncovered item in the denominator, and makes claim eligibility a deterministic result of complete accounting, freshness, an exact basis-point threshold, and zero-tolerance dispositions. | `current change`; `operational_coverage.py`; focused contract tests passed 13 cases; Ruff and strict mypy passed. | Bind each producer to its authoritative denominator and retain governed receipts before making a 99% operational claim. |
| 2026-08-19 | implemented | Regenerated the committed reference baseline, which still described a 9-scenario frozen set after three `sre.*` scenarios made it 12. Every published metric, sample size, and confidence interval therefore described a set that no longer existed; `routed_correctly_rate` was 0.111 and is 0.083. The baseline test now derives the scenario count and the t2 economics from the set instead of pinning `9` and "exactly one t2 scenario", so the next addition fails loudly at the artifact rather than silently in the numbers. | `current change`; `docs/baselines/v2026.07.{json,md}` and the Korean pair regenerated by `tools.baseline_run`; the core and shared-package suites passed 11913 cases with 131 skips, including the previously red `test_baseline_runner` and `test_models_facade_only`. | The baseline remains `synthetic-harness` evidence and is not claim eligible; a live baseline and treatment cohort is still the open item below. |
| 2026-08-19 | in-progress | Gave the `sre` pack its third coverage dimension with asserted evidence rather than a manifest entry. A dedicated test replays `sre.cluster-diagnostics-missing.001` against a publisher that drops the first request, so the effect outcome is genuinely unknown, then proves the run closes a terminal `publish_outcome_unknown` audit entry before the error escapes, records no PR, caches nothing, and that a retry over the same executor publishes exactly one shadow PR. This is the first `partial_failure_recovery` evidence in any pack. | `current change`; `tests/scenarios` and `test_shadow_eval.py` passed 116 focused cases; the new test is mutation-verified - making `_close_unknown_publish` a no-op fails it with `assert 0 == 1`. | `successful_full_loop`, `cross_objective_conflict`, and `a3e_or_non_applicability` remain unevidenced for `sre`. A full-loop claim needs independent effect verification, which shadow execution does not provide, and an A3-E claim needs the unwired standing-authority evaluator. The manifest check still only proves a cited test exists, not that it asserts its dimension. |
| 2026-08-14 | in-progress | Adopted the implementation ledger without reconstructing earlier provenance and separated executable measurement mechanics from unproven outcome claims. | `current change`; measurement source, focused tests, scenario manifest, and constitutional register cited above. | Complete scenario coverage and retain a live baseline/treatment cohort with authoritative outcome closure. |
| 2026-08-18 | in-progress | Gave the `sre` capability pack its first scenarios, so no pack is `missing`. Three frozen scenarios replay through the real control loop with the shipped catalog: an observability precondition that fires `kubernetes-cluster.diagnostic-settings-required` and opens a shadow PR, an error-budget burn on an unmodelled target that abstains and publishes nothing, and telemetry retention above the reviewed ceiling. One scenario per existing domain keeps the balance check satisfied. Only `unknown_or_deny` and `deterministic_replay_with_evidence` are claimed, because the remaining four dimensions have no evidence yet; the pack stays `partial` and the set stays `incomplete`. | `current change`; `tests/scenarios` passed 98 focused cases, including all three new replays through `ControlLoop.process` against the shipped rules, policies, and ActionTypes. | Author the successful-full-loop, cross-objective-conflict, partial-failure-recovery, and A3-E-or-non-applicability cases for every pack. A full-loop claim additionally needs independent effect verification, which shadow execution does not provide. |

### Remaining work

- [ ] Complete SRE `successful_full_loop` with independent authoritative recovery and recurrence-closure evidence, and `cross_objective_conflict` with scenario-produced competing actions audited through production arbitration.
- [ ] Complete the ARB / Change Safety, FinOps / Cost Governance, DR, and Chaos Engineering packs with all six executable constitutional dimensions.
- [ ] Retain one reference baseline and FDAI treatment on the identical frozen scenario set with sample sizes, confidence intervals, absolute values, and no unsupported multiplier claim.
- [ ] Bind live incident, change, cost, human-touchpoint, and independently verified outcome records into the KPI projection, then prove all zero-threshold guards remain zero.
- [ ] Bind the independent verifier registry in runtime composition, adopt `DecisionCriticalEvidenceReceipt` and `DecisionEvidenceVerificationBundle` at every remaining operational-readiness and direct-state decision boundary, retain production startup, qualification, promotion, query, and state bundles, then prove synthetic or incomplete evidence cannot satisfy a live claim.
- [x] Define the provider-neutral `OperationalCoverageReceipt` and prove its denominator,
  disposition, freshness, threshold, zero-tolerance, and digest invariants with focused tests.

## Primary Objective

Minimize human intervention in cloud operations across three initial verticals under an
AIOps approach - Resilience, Change Safety, and Cost Governance - by resolving most events
deterministically (T0/T1) and reserving LLM inference (T2) for the residual ambiguous
minority, **without regressing the guard metrics**. Autonomy that improves a success metric
while degrading a guard metric is a failure, not a win.

SRE is the operating model across the three verticals. Disaster recovery and Chaos Engineering
are Resilience capabilities, Architecture Review Board governance applies across domains, and
FinOps is the Cost Governance discipline.

### Accuracy contract

FDAI does not claim that every novel diagnosis is correct. It targets **100% contract-conformant
behavior**: an agent either produces a schema-valid, evidence-supported, authorized result or
records an explicit unknown, no-op, denial, rollback, or human-review outcome. The platform target
is zero unsafe guesses, not forced answers.

The following violations have a release threshold of exactly zero:

- action against the wrong object identity or stale target revision;
- execution outside the registered ActionType, standing authority, or impact scope;
- success claimed from a broker/API receipt without independent effect verification;
- external state asserted from an ontology write rather than an authoritative observation;
- learning output that raises authority without review and promotion evidence.

### Coverage claim contract

FDAI reports operational coverage with one immutable `OperationalCoverageReceipt` per governed
universe. Supported domains are asset inventory, governance evaluation, operating scope, incident
diagnosis, remediation effects, and knowledge grounding.

Each receipt pins the scope, denominator, and evidence by digest. Every denominator item receives
one terminal coverage disposition: `covered`, `unknown`, `stale`, `unsupported`, `inaccessible`,
`conflicting`, or `invalid`. A governance result can be compliant or noncompliant and still be
`covered`; policy outcome is separate from whether FDAI evaluated the item with current evidence.

The receipt computes coverage in integer basis points. It can meet a target only when all
denominator items are accounted for, the evidence is fresh at evaluation time, the covered count
meets the configured threshold, and every configured zero-tolerance disposition has count zero.
The receipt is measurement evidence only and grants no approval, mutation, or execution authority.

### Autonomy before human review

An unresolved event does not immediately become a human task. Within its bounded deadline, FDAI
tries fresh evidence acquisition, an alternate authoritative source, deterministic reevaluation,
verified pattern reuse, a smaller safe plan, no-op, or pre-authorized recovery. Human review begins
only when ambiguity remains, policy mandates approval, or risk exceeds standing authority. Every
attempt shares the event correlation and contributes no additional human touchpoint.

## Definitions

Terms used across all metrics, fixed here to avoid ambiguity:

- **Event**: one normalized, deduplicated item entering the control loop (post `event-ingest`),
  identified by its stable idempotency key. All per-event rates are computed over this unit.
- **Scenario set**: a frozen, versioned collection spanning SRE, ARB / Change Safety, FinOps / Cost
  Governance, DR, and Chaos Engineering capability packs, used identically for baseline and
  treatment. Each release records the scenario-set and per-pack versions (e.g. `v2026.07`).

> **Current coverage gap:** `services/core-control-plane/tests/scenarios/manifests/v2026.07.json` assigns every fixture to SRE,
> ARB / Change Safety, FinOps, DR, or Chaos. A coverage dimension counts only when it cites a
> scenario owned by that pack and an existing executable test. The set remains `incomplete`: SRE
> has four executable dimensions but still lacks successful full-loop and cross-objective conflict
> evidence, while each of the other four packs also lacks one or more required cases.
> FDAI must not claim complete domain coverage until all five packs are complete.
- **Reference agent**: the fixed comparison system (documented, single-model, no tiering)
  measured in Phase 0. Its version is pinned per baseline run.
- **Human touchpoint**: any action requiring a human decision or input (HIL approval, manual
  edit, manual rollback). Each uniquely identified action or approval counts once, while repeated
  lifecycle rows for the same action or approval don't add another touchpoint. One event can
  contribute more than one touchpoint. Read-only viewing of the console is **not** a touchpoint.
- **Auto-resolved event**: an event that reaches a terminal, correct outcome with zero human
  touchpoints and no post-hoc rollback within the measurement window. An executor dispatch is
  pending, not resolved, until an explicit `measurement.action_outcome.v1` record closes the
  observation with enforce mode, passed verification, an auto decision, and no rollback.
- **Measurement window**: the fixed observation period per run (default: 30 days rolling, or
  one full scenario-set replay), stated with every reported figure.
- **Contract-conformant outcome**: one terminal result whose target, evidence, authority, action,
  effect verification, and audit records satisfy their exact versioned contracts. An explicit
  unknown or safe no-op is conformant; an unsupported success is not.

## Success Metrics

Each metric fixes a unit, formula, and reporting window. Targets are relative to the reference
agent on the same scenario-set version and are directional targets pending measurement.

| # | Metric | Precise definition | Unit | Direction | Target vs baseline |
|---|--------|--------------------|------|-----------|--------------------|
| 1 | Cost per unit | total attributable spend ÷ units processed, computed separately as `$/incident`, `$/change`, `$/optimization` | USD/unit | lower is better | large reduction (state factor only when measured) |
| 2 | Auto-resolution rate | auto-resolved events ÷ total events, in `[0, 1]` | ratio | higher is better | 5× the baseline ratio (capped at 1.0) |
| 3a | MTTR | mean(resolve_time − detect_time) over resolved incidents | seconds | lower is better | 5× shorter (0.2× baseline) |
| 3b | Change lead time | mean(merge_time − change_request_time) over changes | seconds | lower is better | 5× shorter (0.2× baseline) |
| 4 | Human intervention | human touchpoints ÷ (total events ÷ 100) | touchpoints / 100 events | lower is better | 0.2× baseline (i.e. 1/5) |

Notes:
- Metric 1 cost includes model inference, compute, storage, and event-bus spend attributable to
  processing; it excludes fixed platform overhead shared with non-FDAI workloads.
- MTTR and lead time are reported as **median and p90** alongside the mean, because latency
  distributions are skewed and a mean alone hides tail regressions.
- A `5×` target on a ratio (metric 2) is bounded: report both the multiplier and the absolute
  ratios, since a multiplier is meaningless once the baseline is already high.

## Guard Metrics (must not regress)

Guard metrics veto a promotion: any breach demotes the action from enforce back to shadow. Each
has an explicit threshold, not just a direction.

| Guard metric | Definition | Threshold |
|--------------|------------|-----------|
| Change failure rate (CFR) | changes causing incident/rollback ÷ total changes | ≤ baseline CFR (no increase) |
| False-positive rate | incorrect actions ÷ actions taken | ≤ baseline; alert if > baseline + 1pp |
| False-negative rate | missed true events ÷ true events | ≤ baseline; alert if > baseline + 1pp |
| Rollback rate | actions rolled back ÷ actions executed | ≤ baseline rollback rate |
| Policy-violation escapes | autonomous actions that violate policy and reach enforce | **exactly 0** (any escape blocks release) |
| Wrong-target or stale-revision execution | actions applied to a different object or revision than the approved plan | **exactly 0** |
| Unauthorized execution | actions outside registered type, identity, standing authority, or impact scope | **exactly 0** |
| Unverified success claims | actions reported successful without independent expected-effect closure | **exactly 0** |

Thresholds are evaluated on the same measurement window and scenario-set version as the success
metrics, so a gain and a guard breach are never compared across different data.

## Leading vs Lagging Indicators

Success metrics 1-4 are **lagging** (observable only after enough events resolve). Promotion
decisions also watch **leading** indicators that predict guard-metric health earlier:

- per-tier coverage share (T0 70-80%, T1 15-20%, T2 5-10%) drifting out of band,
- mixed-model disagreement rate (T2 quality gate) trending up,
- verifier abstain/fail rate rising,
- shadow-vs-enforce decision divergence for a candidate action.

Leading indicators trigger investigation before a lagging guard metric regresses.

## Measurement-First Rule

- No autonomy ships without telemetry to measure its effect (metrics 1-4 and all guard metrics).
- Phase 0 establishes the KPI dashboard and the reference baseline **before** any tier goes live
  ([phase-0-instrumentation.md](../phases/phase-0-instrumentation.md)).
- Multiplier claims (2-4) are only stated after the baseline and the treatment are both measured
  under the identical, frozen scenario-set version.
- **Statistical validity**: report each factor with a sample size (event count), a confidence
  interval, and the scenario-set version. Differences within the confidence interval are
  reported as "no measured change", not as an improvement. A zero-sample Wilson interval is
  `[0, 1]` (unknown), never evidence that accuracy is exactly zero.
- **Operational promotion evidence**: bind frozen benchmark and live-shadow samples to one full
  FDAI revision, ActionType digest, scenario case, and authoritative measurement unit. Latest
  corrections replace prior rows without changing cohort, scenario, observation time, or causal
  lineage. Separate frozen/live Wilson 95% lower bounds, distinct live days, zero escapes,
  executed-action rollback and complete recurrence windows, verified causal receipts, and Dynamic
  review must pass. A closed causal receipt counts only with confirmed closure. Raw metrics cannot
  promote; a verified receipt permits a separate review only.
- **Fairness**: baseline and treatment run the same scenarios, the same input distribution, and
  the same measurement window; the reference agent is not deliberately handicapped.

## Data Collection and Telemetry

Every metric maps to a concrete telemetry source so the dashboard is buildable, not aspirational:

- **Structured events + traces** (OpenTelemetry) carry `event_id`, `tier`, `decision`,
  `mode` (shadow/enforce), and timestamps - sourcing metrics 2, 3a/3b, and leading indicators.
- **Append-only audit log** sources human touchpoints (metric 4), rollbacks, and policy escapes.
- **Outcome finalization records** (`measurement.action_outcome.v1`) are the authority for
  auto-resolution. Dispatch-only events remain pending, verified non-rollback outcomes enter the
  finalized denominator, and rollback/adverse outcomes remain visible without becoming successes.
  When an action has corrected finalization rows, only its highest audit sequence is authoritative;
  an explicit verification failure remains a rejected observation rather than disappearing.
- **Explicit metric observations** use the latest row for each `event_id` and metric key. A retry
  or correction for one event replaces that event's earlier value instead of adding statistical
  weight; observations from different events remain independent samples.
- **MTTR (metric 3a)** is computed by the pure aggregator
  [`core/measurement/mttr.py`](../../../services/core-control-plane/src/fdai/core/measurement/mttr.py), which folds resolved
  incidents (`resolved_at - opened_at`) into **mean, median, and p90** seconds; unresolved and
  integrity-violating incidents are counted but excluded, never contributing a `0` or a
  negative duration. The delivery-layer wiring that feeds it live incidents (replacing the
  synthetic dev value in the `/kpi/autonomy` panel) is tracked as follow-up.
- **Cost/usage records** (model tokens, compute time, storage, bus throughput) source metric 1;
  attribution keys spend to the originating `event_id`. Repeated lifecycle rows for one action
  contribute the latest observed savings value once rather than weighting or summing retries.
- All metric inputs are English, secret-free, and customer-agnostic per the repo scope rules.

## Review Cadence

- **Per promotion**: no action moves shadow → enforce without a passing metrics + guard review.
- **Weekly**: dashboard review of leading indicators and guard-metric drift.
- **Per scenario-set version bump**: full baseline re-measurement so targets track a current,
  fair reference rather than a stale one.

## Where the Target Multipliers Would Come From

The mechanisms below are the **hypothesized** sources of the targeted gains; each is only
credited once measured against the baseline. Framing is intentionally "uses the LLM less", not
"a smarter LLM".

| Target | Hypothesized mechanism |
|--------|------------------------|
| Auto-resolution ↑ | T0/T1 deterministically close the ~85-90% majority of events; fewer escalations to T2/HIL. |
| MTTR / lead time ↓ | T0/T1 have no LLM round-trip (ms-s); auto-remediation PRs remove human wait time. |
| Human intervention ↓ | risk gate auto-approves low-risk actions; learned T1 actions avoid repeat human touch. |
| Cost per unit ↓ | only ~5-10% of events reach a frontier model; OSS/CSP-neutral stack; event-driven scale-to-zero. |

> Core insight: the gains are hypothesized to come from a structure that **uses the LLM less**,
> not from a smarter LLM - and this claim stands or falls on the Phase 0 measurement.

## Next steps

| To learn about | Read |
|----------------|------|
| How the baseline is instrumented | [phases/phase-0-instrumentation.md](../phases/phase-0-instrumentation.md) |
| Per-tier coverage targets and the trust router | [../../.github/instructions/architecture.instructions.md](../../../.github/instructions/architecture.instructions.md) |
| Safety invariants that guard-metrics enforce | [../../.github/instructions/coding-conventions.instructions.md](../../../.github/instructions/coding-conventions.instructions.md) |
| The KPI dashboard shipped with P0 | [../dashboards/phase-0-kpi.json](../../dashboards/phase-0-kpi.json) |
