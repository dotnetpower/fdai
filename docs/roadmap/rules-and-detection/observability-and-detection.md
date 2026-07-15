---
title: Observability and Detection
---
# Observability and Detection

How FDAI turns raw telemetry into **findings** the control loop can act on:
**event correlation**, **anomaly detection**, **predictive / forecasting**, and
**root-cause analysis (RCA)**. These are the detection signals an AIOps platform is expected to
provide - added here **without breaking deterministic-first**: every signal emits a normalized
finding that flows through the existing `trust-router → tiers → risk-gate → executor → audit`
path, never a side channel, and nothing auto-executes outside the risk gate and the four safety
invariants.

Reference: control loop, tiers, and the quality gate in
[architecture.instructions.md](../../../.github/instructions/architecture.instructions.md);
measurement and guard metrics in [goals-and-metrics.md](../architecture/goals-and-metrics.md); rule/signal
sources in [rule-catalog-collection.md](rule-catalog-collection.md); module placement and DI
seams in [project-structure.md](../architecture/project-structure.md); the prompt-injection threat model in
[security-and-identity.md](../architecture/security-and-identity.md). Correlation and out-of-band detection are
introduced in [phase-1-rule-catalog-t0.md](../phases/phase-1-rule-catalog-t0.md); FinOps
cost-anomaly and DR RPO/RTO forecasting land in
[phase-3-integrated-loop.md](../phases/phase-3-integrated-loop.md). Customer-agnostic; all examples
are synthetic.

## Design Stance (deterministic-first, not ML-first)

- Detection is **explainable and evidence-backed first**: statistical baselines, thresholds,
  and correlation rules resolve most signals with no model call. Models (T1 similarity, T2
  reasoning) enter only for fuzzy correlation and novel RCA - the same 5-10% budget.
- A detection signal is a **finding**, not an action. It is routed and risk-gated like any
  event; a prediction or anomaly **never auto-remediates on its own** - it raises a
  shadow-mode finding or a remediation PR that the risk gate and HIL govern.
- New detectors ship in **shadow mode** and are promoted per the shadow→enforce rule; their
  accuracy and false-positive rate are measured against the Phase 0 baseline.

## 1. Event Correlation

A stage in `event-ingest`, immediately after normalize + deduplicate (see
[project-structure.md](../architecture/project-structure.md) and
[phase-1-rule-catalog-t0.md](../phases/phase-1-rule-catalog-t0.md)): group related raw events into a
single **incident** so downstream tiers reason about one thing, not a storm.

- **Deterministic-first**: correlate by shared keys (resource id, deployment id,
  trace/correlation id, causal parent) within a bounded **time window**, using rules; fall back
  to **T1 embedding similarity** only for fuzzy grouping.
- **Grouping, not causation**: correlation only asserts events *belong together*; a shared window
  can be coincidental. Assigning the *cause* is RCA's job (section 4), never correlation's.
- **Windowing and late arrival**: the correlation window is configured per signal class; a
  late/out-of-order event matching an open incident's keys is attached to it (or, past the
  window, opens a linked follow-on incident) - events are never silently dropped, and the
  per-resource ordering from
  [architecture.instructions.md](../../../.github/instructions/architecture.instructions.md) is
  preserved.
- **Idempotent grouping**: the incident id is derived deterministically from the correlation
  keys, so reprocessing the same members yields the same incident regardless of arrival order.
- **Noise reduction**: a burst of alerts from one root event collapses to one incident. This is
  reported as a **measured** noise-reduction ratio (incidents ÷ raw alerts), not an asserted
  gain, and no data is lost - members stay linked in the audit.
- **Output**: one correlated incident event carrying its member event ids and a stable
  idempotency key; ordering/idempotency keys are preserved.
- **Upstream implementation**: `core/event_ingest/correlator.py`
  (`EventCorrelator`) derives the incident anchor deterministically from
  an event's correlation-id (or resource ref) plus a time-window bucket
  via `incident_id_for`; a burst sharing a key in one window collapses to
  one incident and a new window opens a linked follow-on. An event with
  no anchor is reported `correlated=False` (never dropped). The keys feed
  `IncidentRegistry.open`, which accumulates membership idempotently.

## 2. Anomaly Detection

Generalizes the existing FinOps cost-anomaly hook (see
[phase-3-integrated-loop.md](../phases/phase-3-integrated-loop.md)) to **any metric stream** -
performance, reliability, security, and cost.

- **Method**: statistical baselines (rolling and/or seasonal, with the seasonality window as
  config) and deviation thresholds (e.g. z-score or robust percentile bands), computed per signal
  class. Deterministic and explainable; the baseline, the deviation magnitude, and its
  **direction** (over/under) are recorded so a human can see *why* it fired.
- **Cold-start**: a detector without enough baseline history to be reliable **abstains** (stays
  in shadow and emits no finding) rather than firing on a thin baseline; the cold-start
  suppression is counted as a metric, not hidden.
- **Categories**: findings normalize to the canonical `category` enum
  (`security | reliability | cost | config-drift`) shared with the rule catalog - performance
  signals (latency/error-rate/saturation) and replication lag map to `reliability`, unusual
  access patterns to `security`, spend run-rate to `cost`. Severity derives from deviation
  magnitude.
- **Change-aware suppression**: anomalies coincident with an in-flight change/maintenance window
  are correlated with the originating change event and suppressed or annotated, so a deploy does
  not manufacture false positives.
- **False-positive and false-negative control**: debounce/settling windows plus a measured
  false-positive rate *and* false-negative (missed-anomaly) rate that a new detector must not
  regress - both map to guard metrics in [goals-and-metrics.md](../architecture/goals-and-metrics.md).
- **Output**: an anomaly finding that re-enters `event-ingest` (for an idempotency key and
  dedup) and then the trust router like any event.
- **Upstream implementation**: `core/detection/anomaly.py`
  (`MetricAnomalyDetector`) ships the deterministic z-score baseline
  described above - cold-start abstain, flat-baseline safety, and
  severity from deviation magnitude - and normalizes each finding to an
  `Event(event_type="anomaly.finding")` in shadow mode via `to_event`,
  keyed by `detector + metric + window` so repeated ticks dedup.
- **Seasonality**: `core/detection/seasonal.py`
  (`SeasonalAnomalyDetector`) handles metrics with a periodic shape so a
  normal per-phase peak (a Monday-morning traffic spike, a nightly batch
  job) does not fire against a pooled 24x7 mean. It buckets history by a
  configured **phase** (`hour_of_day`, `day_of_week`, `hour_of_week`, or
  a custom function) and compares the observed sample only against past
  samples in the *same* phase. It is a thin wrapper over the base
  detector - it filters history to the phase and delegates the z-score,
  cold-start-abstain, flat-baseline, and event-normalization logic - so
  the two detectors cannot drift. Per-phase cold-start is independent (a
  thin Sunday baseline never borrows Monday's data), the phase is
  recorded on the finding's `window_bucket`, and the finding is still a
  shadow-mode event.
- **Multivariate fusion**: `core/detection/composite.py`
  (`CompositeAnomalyDetector`) is the compound-degradation signal an
  organization's on-call reads by hand - a real incident is *correlated*
  streams firing together (latency up **and** error-rate up **and**
  saturation high), not one noisy metric. It is a **fuser, not a new
  baseline**: it consumes the per-metric `AnomalyFinding` objects already
  produced for one resource + window and raises a
  `CompositeAnomalyFinding` (`event_type="anomaly.composite"`) only when a
  configured **quorum** of them fire. Below quorum it abstains (a single
  noisy stream is not a compound anomaly - false-positive suppression);
  at quorum and above it *amplifies* (severity escalates with both the
  breadth of concurrent members and their root-sum-square combined
  magnitude, so a compound degradation outranks any single member).
  Duplicate metrics collapse to their strongest occurrence so a re-emitted
  stream cannot inflate the quorum, a flat-baseline member contributes a
  fixed weight, and the fusion is deterministic regardless of member
  order. The composite is still a shadow-mode finding governed by the risk
  gate - it detects harder, it does not act.

## 3. Predictive / Forecasting

Proactive detection: forecast a threshold breach **before** it happens - the AIOps "predict
capacity bottlenecks and service failures" use case - kept deterministic-first.

- **Method**: trend extrapolation on a measured series (linear/seasonal fit) to a configured
  **forecast horizon**, raising a finding when the projected value crosses a configured
  threshold. Every forecast carries its horizon and a **confidence interval**; it is a projection
  with stated uncertainty - **not deterministic truth and not an LLM oracle** - and it never
  grants execution eligibility.
- **Targets**: capacity/quota exhaustion, replication-lag drift toward RPO breach, cost run-rate
  vs budget, certificate/secret expiry, backup-retention drift. RPO/RTO and FinOps targets are
  owned by [phase-3-integrated-loop.md](../phases/phase-3-integrated-loop.md).
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
- **Upstream implementation**: `core/detection/forecast.py`
  (`LinearForecastDetector`) ships a least-squares linear forecaster -
  cold-start and weak-fit (low R-squared) inputs abstain,
  direction-gated rising/falling breach projection, and a positive lead
  time (breach ETA) bounded by the horizon. Each forecast normalizes to
  an `Event(event_type="forecast.finding")` in shadow mode via
  `to_event`, keyed by `detector + metric + window` so repeated ticks
  dedup; severity scales with imminence (lead / horizon). It shares the
  `MetricSample` series type with the anomaly detector (`core/detection/series.py`).
- **Prediction-interval band (false-positive suppression)**:
  `core/detection/forecast_band.py` (`prediction_band`) adds the
  uncertainty band a point forecast lacks. A noisy series can cross the
  threshold on the center line yet stay inside normal variation; the band
  widens with the fitted `residual_std` **and** with how far into the
  future the projection reaches, and a breach is only **confident** when
  the pessimistic edge of the interval (the lower edge for a rising
  breach, the upper edge for a falling one) still crosses at a configured
  confidence level (`0.80`-`0.99`). It is a **suppressor, never an
  amplifier**: it can downgrade a point-estimate breach to "not confident"
  (hold in shadow / abstain, protecting the false-positive guard metric),
  but it never manufactures a breach the point forecast did not predict.
  A perfect fit (`residual_std == 0`) collapses the band to the point
  estimate; an unknown confidence level is rejected rather than silently
  defaulted.

## 4. Root-Cause Analysis

Make RCA a first-class output of the tiers instead of an implicit side effect.

| Tier | RCA role |
|------|----------|
| **T0** | direct cause: the matched rule/policy names the violated control and its remediation |
| **T1** | correlation cause: either (a) match the incident to a prior **resolved** incident and reuse its identified root cause + learned action (with provenance and re-verification), or (b) reconstruct a **deterministic causal chain** from the incident's own correlated events - identify the closest antecedent change / mutation that preceded the failure within a bounded window on a related resource (the "a deploy went out, then the error rate rose" chain) |
| **T2** | reasoning cause: for novel/ambiguous incidents, produce a grounded root-cause hypothesis that **cites evidence** (rules, correlated events, telemetry, free-form operator documents) and passes the quality gate |

- RCA output is a **hypothesis with citations**, not an authoritative verdict; **execution
  eligibility is still granted by deterministic verification** (verifier + policy re-check),
  never by the RCA text or a forecast alone.
- Telemetry and correlated events feeding T2 RCA are **untrusted input** and may carry prompt
  injection; per [security-and-identity.md](../architecture/security-and-identity.md) the verifier and policy
  re-check are authoritative over any model text.
- T1 reuse of a prior resolved incident's root cause must **re-verify** that the prior cause and
  its learned action still apply (with provenance), and any resulting action runs what-if before
  the risk gate - a stale learned action is never replayed blindly.
- An RCA that cannot be grounded **abstains** and routes to HIL.
- The correlated incident (section 1) is the RCA input, so RCA reasons over one incident, not a
  storm of duplicates.
- **Upstream implementation**: `core/rca/` ships the RCA contract
  (`RootCauseHypothesis` + `Citation`), the deterministic **T0** cause
  (`t0_root_cause`, grounded on the matched rule with confidence 1.0 and
  its remediation), and the **grounding gate** (`enforce_grounding`,
  which abstains to HIL on any ungrounded or below-confidence
  hypothesis). The **T2** reasoner is the `RcaReasoner` Protocol seam - a
  fork plugs a mixed-model, RAG-grounded producer (via `core/quality_gate`)
  behind it. Upstream ships `core/rca/llm.py` (`LlmRcaReasoner` + the
  `RcaModel` seam) whose deterministic parser refuses a malformed answer,
  a fabricated citation (prompt injection), or an ungrounded answer - the
  model proposes, the parser and grounding gate decide. The Azure T2
  binding is `delivery/azure/llm/rca_model.py` (`AzureOpenAIRcaModel`), an
  `RcaModel` adapter that calls Azure OpenAI over its managed-identity
  token and returns raw JSON for the upstream parser to validate. The
  composition root binds it from the `t2.rca` capability in
  `resolved-models.json` (`bind_azure_llm_bindings`), symmetric to the
  Critic and Judge bindings - a missing capability or prompt leaves
  `LlmBindings.rca_reasoner = None` so T2 RCA stays dark and only T0 RCA
  runs. `__main__` injects the resulting `RcaCoordinator` (and the
  `EventCorrelator`) into the `ControlLoop`. Its
  output still
  passes the grounding gate and the risk-gate verifier, never executing
  on the model's prose alone. The
  `RcaCoordinator` orchestrates all three tiers - T0, **T1**
  correlation-reuse (a prior resolved incident's cause, abstaining when
  it is stale against current evidence), and T2 (a citation outside the
  supplied evidence is refused as fabricated). It is wired into the
  `ControlLoop`, which appends one deterministic T0 `rca.hypothesis`
  audit entry per finding, carrying the correlated `incident_id` (from
  `EventCorrelator`, section 1) so an incident's findings tie together -
  the "why", never a new execution path. When a T2 reasoner is wired, a
  novel (T0 no-match) case additionally gets a grounded T2
  `rca.hypothesis` (or an abstain), reasoner-gated so a deployment
  without an LLM emits no T2 noise.
- **Free-form knowledge leg**: `core/rca/knowledge_evidence.py`
  (`KnowledgeEvidenceGatherer`) is the RCA consumer of the Knowledge Base
  ingestion seam (`shared/providers/knowledge.py` `KnowledgeSource` +
  `EmbeddingKnowledgeSource` / `PgvectorKnowledgeSource`). When bound, the
  `RcaCoordinator`'s T2 convenience wrappers search the operator's ingested
  documents (runbooks, architecture notes, **resource plans**) for chunks
  relevant to the incident summary and add each as a `CitationKind.KNOWLEDGE`
  candidate - so a document an operator uploads is actually referenced when
  T2 forms a hypothesis. Fail-safe (an unbound source, empty index, or
  provider outage contributes nothing and the gate abstains) and secret-safe
  (a citation ref is the opaque `knowledge:<source_ref>#<chunk_id>` handle,
  never the chunk body). The reasoner still cannot cite a chunk outside this
  vouched-for set, and the grounding gate + verifier remain authoritative.
- **T1 causal chain (deterministic)**: `core/rca/causal_chain.py`
  (`CausalChainAnalyzer`, driven by `core/rca/t1.py`'s `t1_causal_chain`)
  is the model-free form of T1 correlation (b). Given the incident's
  correlated events (each carrying a timestamp, a generic `resource_ref`,
  an `is_change` marker, and an optional `change_kind`), it reconstructs
  the most probable **multi-hop causal chain** ending at the failure -
  `root change -> symptom -> ... -> failure` - not merely the single
  closest antecedent. The **root MUST be a change** (a mutation can
  cause; a symptom only propagates), so a window of pure symptoms with no
  antecedent change **abstains** (returns `None`, deferring to T2).
  Reconstruction is **dependency-aware**: when a resource-dependency
  graph is supplied, a change on a resource the failure depends on
  (directly, or transitively within a bounded depth) outranks an
  unrelated one, and once a graph is given an unrelated resource cannot
  link at all; with no graph the engine stays permissive (any correlated
  resource may link - the cross-resource default). `same_resource_only`
  restricts every hop to the failing resource. Confidence is a
  weakest-link aggregate over the chain's hops (each hop weighted by
  temporal proximity, relationship strength, and change-kind),
  **ambiguity-discounted** when several distinct roots explain the
  failure about equally well, and bounded to the T1 band (`0.35`-`0.85`)
  - a temporal antecedent is a strong hint, never T0-style certainty.
  Strict temporal precedence makes the event set a DAG, so the chain is
  deterministic (the same events always yield the same chain) and cites
  every event in it; it passes the grounding gate and the risk-gate
  verifier before anything acts. `RcaCoordinator.analyze_t1_causal_chain`
  is the grounded entry point. Live wiring: the `ControlLoop` feeds it
  each matched incident's members through the `IncidentMemberSource` seam
  (`core/rca/member_source.py`; a fork's adapter marks which members are
  changes) and appends one shadow `rca.hypothesis` (tier t1) per event,
  bounded by the configured `causal_chain_window` and an optional
  resource-dependency graph. The hypothesis retains a transport-safe
  `causal_chain` (root/failure ids, ambiguity, and ordered hop evidence),
  and the control loop writes that structure into the append-only audit
  entry instead of collapsing it into prose. The upstream reference implementation
  `DeploymentHistoryMemberSource` (`core/rca/deployment_member_source.py`)
  bridges a real `DeploymentHistoryProvider` (e.g. the Azure Resource
  Graph adapter) plus an incident-record lookup into the antecedent
  `is_change=True` events, so a fork gets live change-history-driven
  chains without writing the source. Absent a source, T1 causal-chain RCA
  stays dark and only T0 (and T2, when wired) RCA runs
  (backward-compatible).
- **Read-only console surface**: the shadow `rca.hypothesis` audit entries
  are projected into a first-class **History > RCA** operator-console panel
  (`GET /rca?correlation=<id>`, pure projection in
  `delivery/read_api/routes/rca_projection.py`). Given an incident
  `correlation_id` it renders the tiered hypotheses, their citations, the
  structured T1 causal chain when recorded,
  grounding state (an abstained hypothesis shows as "insufficient grounding
  -> HIL", never a confident cause), and the linked response plan (verdict /
  action / mode / rollback) composed from the same correlated audit stream.
  The surface is strictly read-only and adds no new source of truth - see
  [operator-console.md](../interfaces/operator-console.md#1351-rca-view-root-cause-analysis).

## Plugging Into the Control Loop

Correlation runs inside `event-ingest`. Anomaly and forecast detectors are **out-of-band
producers** (e.g. event-driven Functions per
[app-shape.instructions.md](../../../.github/instructions/app-shape.instructions.md) and phase-1
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
| Incident detection & alerting | Adopt - correlation + anomaly emit findings |
| Root-cause analysis | Adopt - first-class RCA per tier (section 4) |
| Anomaly detection | Adopt - statistical, explainable (section 2) |
| Predictive analytics | Adopt - trend + threshold forecast, with uncertainty (section 3) |
| Alert-noise reduction / fewer false positives | Adopt - correlation + measured FP rate |
| Less manual work / faster resolution | Adopt - risk-gated auto-remediation |
| Audit trails / compliance | Adopt - append-only audit is already core |
| **ML/NLP as the primary engine** | **Differ** - deterministic-first; models are the 5-10% residual |
| **Opaque / black-box anomaly scoring** | **Differ** - explainable-first; a finding records its baseline, deviation, and direction |
| **Model recommends *and* executes** | **Differ** - execution eligibility is from deterministic verification, not the model |
| **Vendor-platform lock-in** | **Differ** - CSP-neutral; observability platforms are telemetry *sources*, not the brain |

## Configuration and Safety

- Baselines, deviation thresholds, forecast horizons, correlation keys, and model bindings are
  **configuration**; a fork overrides them via the DI seams in
  [project-structure.md](../architecture/project-structure.md), never by editing core.
- Detectors validate their config at startup and **fail closed** - a broken detector, an
  insufficient/cold-start baseline, or stale telemetry makes the detector **abstain** rather than
  emit a false finding or auto-act.
- Detection findings are **untrusted input**; any LLM use (fuzzy correlation, T2 RCA) passes the
  quality gate ([architecture.instructions.md](../../../.github/instructions/architecture.instructions.md))
  and the prompt-injection threat model in
  [security-and-identity.md](../architecture/security-and-identity.md).
- Emit detector metrics - fire rate, false-positive rate, false-negative/missed-breach rate,
  abstain and cold-start-suppression counts, forecast lead time, and RCA groundedness - to the
  KPI dashboard.

### Runtime delivery status

The Container Apps analyzer and scheduler jobs publish canonical, idempotent Events to the
configured Event Hubs ingest topic. They do not execute changes; findings and due tasks re-enter
the shared trust-router and risk-gate. Publish failure keeps the scheduled item retryable and
returns a non-zero job result.

The inventory job promotes a complete ARG/ARM snapshot atomically, then reads Azure Activity Log
deltas per subscription. Delta resources are forwarded as canonical Events, and each cursor
advances only after the stream emits its final fence. The control loop reads the active Postgres
snapshot age for graph-dependent ActionTypes; a missing, failed, or stale freshness lookup routes
the action to human review.

## Open Decisions

- [ ] Anomaly method per signal class (z-score vs robust percentile vs seasonal decomposition).
- [ ] Forecast model family and default horizons per target (capacity, lag, cost, expiry).
- [ ] Correlation key set and time-window defaults; when to escalate fuzzy correlation to T1.
- [ ] Cold-start policy: minimum baseline history per signal class before a detector may fire.
- [ ] Backtesting cadence and the accuracy bar a forecaster must clear to leave shadow.
- [ ] Change-window suppression: how anomalies are correlated with in-flight change events.
- [ ] Whether RCA hypotheses are surfaced in the console (read-only) in P2 or P3.
