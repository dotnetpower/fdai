# Observability and Detection

How AIOpsPilot turns raw telemetry into **findings** the control loop can act on:
**event correlation**, **anomaly detection**, **predictive / forecasting**, and
**root-cause analysis (RCA)**. These are the detection signals an AIOps platform is expected to
provide — added here **without breaking deterministic-first**: every signal emits a normalized
finding that flows through the existing `trust-router → tiers → risk-gate → executor → audit`
path, never a side channel, and nothing auto-executes outside the risk gate and the four safety
invariants.

Reference: control loop, tiers, and the quality gate in
[architecture.instructions.md](../../.github/instructions/architecture.instructions.md);
measurement and guard metrics in [goals-and-metrics.md](goals-and-metrics.md); rule/signal
sources in [rule-catalog-collection.md](rule-catalog-collection.md); module placement and DI
seams in [project-structure.md](project-structure.md); the prompt-injection threat model in
[security-and-identity.md](security-and-identity.md). Correlation and out-of-band detection are
introduced in [phase-1-rule-catalog-t0.md](phases/phase-1-rule-catalog-t0.md); FinOps
cost-anomaly and DR RPO/RTO forecasting land in
[phase-3-integrated-loop.md](phases/phase-3-integrated-loop.md). Customer-agnostic; all examples
are synthetic.

## Design Stance (deterministic-first, not ML-first)

- Detection is **explainable and evidence-backed first**: statistical baselines, thresholds,
  and correlation rules resolve most signals with no model call. Models (T1 similarity, T2
  reasoning) enter only for fuzzy correlation and novel RCA — the same 5–10% budget.
- A detection signal is a **finding**, not an action. It is routed and risk-gated like any
  event; a prediction or anomaly **never auto-remediates on its own** — it raises a
  shadow-mode finding or a remediation PR that the risk gate and HIL govern.
- New detectors ship in **shadow mode** and are promoted per the shadow→enforce rule; their
  accuracy and false-positive rate are measured against the Phase 0 baseline.

## 1. Event Correlation

A stage in `event-ingest`, immediately after normalize + deduplicate (see
[project-structure.md](project-structure.md) and
[phase-1-rule-catalog-t0.md](phases/phase-1-rule-catalog-t0.md)): group related raw events into a
single **incident** so downstream tiers reason about one thing, not a storm.

- **Deterministic-first**: correlate by shared keys (resource id, deployment id,
  trace/correlation id, causal parent) within a bounded **time window**, using rules; fall back
  to **T1 embedding similarity** only for fuzzy grouping.
- **Grouping, not causation**: correlation only asserts events *belong together*; a shared window
  can be coincidental. Assigning the *cause* is RCA's job (section 4), never correlation's.
- **Windowing and late arrival**: the correlation window is configured per signal class; a
  late/out-of-order event matching an open incident's keys is attached to it (or, past the
  window, opens a linked follow-on incident) — events are never silently dropped, and the
  per-resource ordering from
  [architecture.instructions.md](../../.github/instructions/architecture.instructions.md) is
  preserved.
- **Idempotent grouping**: the incident id is derived deterministically from the correlation
  keys, so reprocessing the same members yields the same incident regardless of arrival order.
- **Noise reduction**: a burst of alerts from one root event collapses to one incident. This is
  reported as a **measured** noise-reduction ratio (incidents ÷ raw alerts), not an asserted
  gain, and no data is lost — members stay linked in the audit.
- **Output**: one correlated incident event carrying its member event ids and a stable
  idempotency key; ordering/idempotency keys are preserved.

## 2. Anomaly Detection

Generalizes the existing FinOps cost-anomaly hook (see
[phase-3-integrated-loop.md](phases/phase-3-integrated-loop.md)) to **any metric stream** —
performance, reliability, security, and cost.

- **Method**: statistical baselines (rolling and/or seasonal, with the seasonality window as
  config) and deviation thresholds (e.g. z-score or robust percentile bands), computed per signal
  class. Deterministic and explainable; the baseline, the deviation magnitude, and its
  **direction** (over/under) are recorded so a human can see *why* it fired.
- **Cold-start**: a detector without enough baseline history to be reliable **abstains** (stays
  in shadow and emits no finding) rather than firing on a thin baseline; the cold-start
  suppression is counted as a metric, not hidden.
- **Categories**: findings normalize to the canonical `category` enum
  (`security | reliability | cost | config-drift`) shared with the rule catalog — performance
  signals (latency/error-rate/saturation) and replication lag map to `reliability`, unusual
  access patterns to `security`, spend run-rate to `cost`. Severity derives from deviation
  magnitude.
- **Change-aware suppression**: anomalies coincident with an in-flight change/maintenance window
  are correlated with the originating change event and suppressed or annotated, so a deploy does
  not manufacture false positives.
- **False-positive and false-negative control**: debounce/settling windows plus a measured
  false-positive rate *and* false-negative (missed-anomaly) rate that a new detector must not
  regress — both map to guard metrics in [goals-and-metrics.md](goals-and-metrics.md).
- **Output**: an anomaly finding that re-enters `event-ingest` (for an idempotency key and
  dedup) and then the trust router like any event.

## 3. Predictive / Forecasting

Proactive detection: forecast a threshold breach **before** it happens — the AIOps "predict
capacity bottlenecks and service failures" use case — kept deterministic-first.

- **Method**: trend extrapolation on a measured series (linear/seasonal fit) to a configured
  **forecast horizon**, raising a finding when the projected value crosses a configured
  threshold. Every forecast carries its horizon and a **confidence interval**; it is a projection
  with stated uncertainty — **not deterministic truth and not an LLM oracle** — and it never
  grants execution eligibility.
- **Targets**: capacity/quota exhaustion, replication-lag drift toward RPO breach, cost run-rate
  vs budget, certificate/secret expiry, backup-retention drift. RPO/RTO and FinOps targets are
  owned by [phase-3-integrated-loop.md](phases/phase-3-integrated-loop.md).
- **Backtesting before promotion**: a forecaster must **backtest** on historical series (predict
  known past breaches) and clear an accuracy bar in shadow before it may leave shadow mode.
- **Drift**: forecast error is tracked over time; measured degradation (drift) automatically
  **demotes** the forecaster back to shadow.
- **Safety**: a prediction **raises a finding** (shadow-mode by default) or a proactive
  remediation PR; it never auto-executes on its own. Acting on a forecast still passes the risk
  gate and carries all four safety invariants.
- **Measurement**: define **lead time** = `actual_breach_time − finding_time` (a valid
  prediction has positive lead time above an actionable minimum) and score **precision/recall**,
  where a true positive is a predicted breach whose actual breach occurs within the horizon. A
  missed breach is a false negative (guard metric); a poor forecaster stays in shadow.

## 4. Root-Cause Analysis

Make RCA a first-class output of the tiers instead of an implicit side effect.

| Tier | RCA role |
|------|----------|
| **T0** | direct cause: the matched rule/policy names the violated control and its remediation |
| **T1** | correlation cause: match the incident to a prior **resolved** incident and reuse its identified root cause + learned action (with provenance and re-verification) |
| **T2** | reasoning cause: for novel/ambiguous incidents, produce a grounded root-cause hypothesis that **cites evidence** (rules, correlated events, telemetry) and passes the quality gate |

- RCA output is a **hypothesis with citations**, not an authoritative verdict; **execution
  eligibility is still granted by deterministic verification** (verifier + policy re-check),
  never by the RCA text or a forecast alone.
- Telemetry and correlated events feeding T2 RCA are **untrusted input** and may carry prompt
  injection; per [security-and-identity.md](security-and-identity.md) the verifier and policy
  re-check are authoritative over any model text.
- T1 reuse of a prior resolved incident's root cause must **re-verify** that the prior cause and
  its learned action still apply (with provenance), and any resulting action runs what-if before
  the risk gate — a stale learned action is never replayed blindly.
- An RCA that cannot be grounded **abstains** and routes to HIL.
- The correlated incident (section 1) is the RCA input, so RCA reasons over one incident, not a
  storm of duplicates.

## Plugging Into the Control Loop

Correlation runs inside `event-ingest`. Anomaly and forecast detectors are **out-of-band
producers** (e.g. event-driven Functions per
[app-shape.instructions.md](../../.github/instructions/app-shape.instructions.md) and phase-1
out-of-band detection) that publish findings onto the bus; those findings **re-enter
`event-ingest`** to get an idempotency key and dedup, so a flapping detector cannot inject
duplicate work. No detector is a new autonomy surface:

```text
telemetry / metrics
  -> anomaly / forecast detectors emit findings ---.               # sections 2-3
  raw events -------------------------------------- +-> event-ingest
                                                       (normalize + dedup + correlate)   # section 1
  -> trust-router -> T0 | T1 | (T2 -> quality-gate)                                       # RCA per tier, section 4
  -> risk-gate -> auto -> executor -> delivery (PR) | HIL | abstain/deny -> audit
```

- A **finding** is a first-class, versioned event type in `shared/contracts` with a stable
  idempotency key (e.g. `detector-id + metric + window-bucket`, or the incident id), so repeated
  evaluation ticks deduplicate instead of piling up.
- Detectors are configuration-driven (baselines, thresholds, horizons, correlation keys, and
  model bindings are config, not hard-coded), honor shadow-before-enforce, and every finding and
  decision is audited.

## AIOps Alignment

What we adopt from the general AIOps model, and where we intentionally differ:

| AIOps capability | Our stance |
|------------------|-----------|
| Incident detection & alerting | Adopt — correlation + anomaly emit findings |
| Root-cause analysis | Adopt — first-class RCA per tier (section 4) |
| Anomaly detection | Adopt — statistical, explainable (section 2) |
| Predictive analytics | Adopt — trend + threshold forecast, with uncertainty (section 3) |
| Alert-noise reduction / fewer false positives | Adopt — correlation + measured FP rate |
| Less manual work / faster resolution | Adopt — risk-gated auto-remediation |
| Audit trails / compliance | Adopt — append-only audit is already core |
| **ML/NLP as the primary engine** | **Differ** — deterministic-first; models are the 5–10% residual |
| **Opaque / black-box anomaly scoring** | **Differ** — explainable-first; a finding records its baseline, deviation, and direction |
| **Model recommends *and* executes** | **Differ** — execution eligibility is from deterministic verification, not the model |
| **Vendor-platform lock-in** | **Differ** — CSP-neutral; observability platforms are telemetry *sources*, not the brain |

## Configuration and Safety

- Baselines, deviation thresholds, forecast horizons, correlation keys, and model bindings are
  **configuration**; a fork overrides them via the DI seams in
  [project-structure.md](project-structure.md), never by editing core.
- Detectors validate their config at startup and **fail closed** — a broken detector, an
  insufficient/cold-start baseline, or stale telemetry makes the detector **abstain** rather than
  emit a false finding or auto-act.
- Detection findings are **untrusted input**; any LLM use (fuzzy correlation, T2 RCA) passes the
  quality gate ([architecture.instructions.md](../../.github/instructions/architecture.instructions.md))
  and the prompt-injection threat model in
  [security-and-identity.md](security-and-identity.md).
- Emit detector metrics — fire rate, false-positive rate, false-negative/missed-breach rate,
  abstain and cold-start-suppression counts, forecast lead time, and RCA groundedness — to the
  KPI dashboard.

## Open Decisions

- [ ] Anomaly method per signal class (z-score vs robust percentile vs seasonal decomposition).
- [ ] Forecast model family and default horizons per target (capacity, lag, cost, expiry).
- [ ] Correlation key set and time-window defaults; when to escalate fuzzy correlation to T1.
- [ ] Cold-start policy: minimum baseline history per signal class before a detector may fire.
- [ ] Backtesting cadence and the accuracy bar a forecaster must clear to leave shadow.
- [ ] Change-window suppression: how anomalies are correlated with in-flight change events.
- [ ] Whether RCA hypotheses are surfaced in the console (read-only) in P2 or P3.
