# Goals and Metrics

The roadmap optimizes for **autonomy with proof**. Every autonomy claim is backed by a
measured baseline; nothing is asserted from estimation. Improvement factors below (`5×`,
`large reduction`, `1/5`) are **targets**, not achieved results — they may only be stated as
achieved once both the reference baseline and the AIOpsPilot treatment have been measured on
the same scenario set (see [Measurement-First Rule](#measurement-first-rule)).

This document is the source of truth for KPIs. It aligns with the tier coverage targets in
[architecture.instructions.md](../../.github/instructions/architecture.instructions.md) and is
operationalized by [phase-0-instrumentation.md](phases/phase-0-instrumentation.md).

## Primary Objective

Minimize human intervention in cloud operations across three initial verticals under an
AIOps approach — Resilience, Change Safety, and Cost Governance — by resolving most events
deterministically (T0/T1) and reserving LLM inference (T2) for the residual ambiguous
minority, **without regressing the guard metrics**. Autonomy that improves a success metric
while degrading a guard metric is a failure, not a win.

## Definitions

Terms used across all metrics, fixed here to avoid ambiguity:

- **Event**: one normalized, deduplicated item entering the control loop (post `event-ingest`),
  identified by its stable idempotency key. All per-event rates are computed over this unit.
- **Scenario set**: a frozen, versioned collection of Resilience, Change Safety, and Cost
  Governance cases used identically for baseline and treatment. Each release records the
  scenario-set version (e.g. `v2026.07`).
- **Reference agent**: the fixed comparison system (documented, single-model, no tiering)
  measured in Phase 0. Its version is pinned per baseline run.
- **Human touchpoint**: any action requiring a human decision or input (HIL approval, manual
  edit, manual rollback). Read-only viewing of the console is **not** a touchpoint.
- **Auto-resolved event**: an event that reaches a terminal, correct outcome with zero human
  touchpoints and no post-hoc rollback within the measurement window.
- **Measurement window**: the fixed observation period per run (default: 30 days rolling, or
  one full scenario-set replay), stated with every reported figure.

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
  processing; it excludes fixed platform overhead shared with non-AIOpsPilot workloads.
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
| Policy-violation escapes | autonomous actions that violate policy and reach enforce | **exactly 0** (any escape is a stop-ship) |

Thresholds are evaluated on the same measurement window and scenario-set version as the success
metrics, so a gain and a guard breach are never compared across different data.

## Leading vs Lagging Indicators

Success metrics 1–4 are **lagging** (observable only after enough events resolve). Promotion
decisions also watch **leading** indicators that predict guard-metric health earlier:

- per-tier coverage share (T0 70–80%, T1 15–20%, T2 5–10%) drifting out of band,
- mixed-model disagreement rate (T2 quality gate) trending up,
- verifier abstain/fail rate rising,
- shadow-vs-enforce decision divergence for a candidate action.

Leading indicators trigger investigation before a lagging guard metric regresses.

## Measurement-First Rule

- No autonomy ships without telemetry to measure its effect (metrics 1–4 and all guard metrics).
- Phase 0 establishes the KPI dashboard and the reference baseline **before** any tier goes live
  ([phase-0-instrumentation.md](phases/phase-0-instrumentation.md)).
- Multiplier claims (2–4) are only stated after the baseline and the treatment are both measured
  under the identical, frozen scenario-set version.
- **Statistical validity**: report each factor with a sample size (event count), a confidence
  interval, and the scenario-set version. Differences within the confidence interval are
  reported as "no measured change", not as an improvement.
- **Fairness**: baseline and treatment run the same scenarios, the same input distribution, and
  the same measurement window; the reference agent is not deliberately handicapped.

## Data Collection and Telemetry

Every metric maps to a concrete telemetry source so the dashboard is buildable, not aspirational:

- **Structured events + traces** (OpenTelemetry) carry `event_id`, `tier`, `decision`,
  `mode` (shadow/enforce), and timestamps — sourcing metrics 2, 3a/3b, and leading indicators.
- **Append-only audit log** sources human touchpoints (metric 4), rollbacks, and policy escapes.
- **Cost/usage records** (model tokens, compute time, storage, bus throughput) source metric 1;
  attribution keys spend to the originating `event_id`.
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
| Auto-resolution ↑ | T0/T1 deterministically close the ~85–90% majority of events; fewer escalations to T2/HIL. |
| MTTR / lead time ↓ | T0/T1 have no LLM round-trip (ms–s); auto-remediation PRs remove human wait time. |
| Human intervention ↓ | risk gate auto-approves low-risk actions; learned T1 actions avoid repeat human touch. |
| Cost per unit ↓ | only ~5–10% of events reach a frontier model; OSS/CSP-neutral stack; event-driven scale-to-zero. |

> Core insight: the gains are hypothesized to come from a structure that **uses the LLM less**,
> not from a smarter LLM — and this claim stands or falls on the Phase 0 measurement.
