---
title: Scope Expansion and Structural Gaps
---
# Scope Expansion and Structural Gaps

FDAI is positioned as an autonomous cloud operations control plane
([copilot-instructions.md](../../.github/copilot-instructions.md)), but
the initial verticals - Change Safety, Resilience, Cost Governance -
cover only a subset of the operations duties an FDAI deployment is
expected to grow into. This document freezes the **scope decision**
for the P2/P3 axis expansion, so every subsequent structural change
lands against a stated design intent instead of an implicit one.

Reference: the roadmap-level duty list is enumerated in
[goals-and-metrics.md](goals-and-metrics.md) (KPI 1-4 + guard
metrics); the layered runtime shape lives in
[app-shape.instructions.md](../../.github/instructions/app-shape.instructions.md);
CSP-neutral wire contracts live in
[csp-neutrality.md](csp-neutrality.md); the trust-router / risk-gate /
control loop live in
[architecture.instructions.md](../../.github/instructions/architecture.instructions.md).

## 1. In-scope axes (kept + expanded)

| Axis | Position | Rationale |
|------|----------|-----------|
| **Change Safety** | Kept vertical. Foundational. | Deterministic-first ⇢ policy-gate ⇢ shadow → enforce is the strongest current story. |
| **Resilience (DR/Chaos)** | Kept vertical. Chaos Studio adapter shipped. | Prod-exclusion invariant + `chaos:opt-out` tag already give a safety floor that is rare in industry. |
| **Cost Governance (FinOps)** | Kept vertical. | Aligns with FinOps guardrail pattern that is well-established. |
| **Incident lifecycle** | **New first-class object.** See § 3.1. | Blocks postmortem, RCA depth, on-call handoff. Cannot ship those without this. |
| **Telemetry ingestion** | **Layer-0 seam expansion 5 → 8.** See § 3.2. | Metric / log / trace consumers are missing; anomaly + predictive + RCA are capped without them. |
| **Workload SLO / error budget** | **New subsystem.** See § 3.3. | Control-plane SLOs exist ([deployment.md § 157](deployment.md)); the workload-facing SLI/SLO/burn-rate abstraction that ranks incident priority does not. Kept separate from control-plane SLOs to avoid conflating the two identities. |
| **Runbook orchestration** | **New primitive layer.** See § 3.4. | Present ActionTypes are leaves; a runbook is a DAG over ActionTypes with a rollback branch. |
| **On-call schedule** | **New provider.** See § 3.5. | HIL routing today is role-based, not schedule-based. Break-glass pager exists but knows nothing about who is on shift. |
| **Postmortem draft** | **New core module.** See § 3.6. | Fed by Incident + audit trail. LLM-optional (template-based default). |
| **Full T1/T2 wiring into ControlLoop** | **T1 wired; T2 pending.** See § 3.7. | `ControlLoop.__init__` accepts an optional `t1_engine` and the loop runs `T0.abstain -> T1.reuse-log` (shadow-only). T2 remains: `core/tiers/t2_reasoning/` is still a stub, so there is no `t2_engine` yet. |

## 2. Explicitly-deferred axes (not in this expansion)

| Axis | Position | Rationale |
|------|----------|-----------|
| Multi-cloud (AWS / GCP) | Deferred to future phase. | Implementation focus stays Azure; the wire-contract seams (§ 3.2) keep an AWS adapter additive. |
| Predictive capacity / autoscaling | Deferred. | Depends on telemetry ingestion (§ 3.2) being real, not stubbed. Ship § 3.2 first, then this in a later phase. |
| Status page / stakeholder broadcast | Deferred. | The Incident object (§ 3.1) is the prerequisite; broadcast is a delivery-layer adapter and lands independently. |
| PagerDuty / OpsGenie integration | Deferred. | The `OnCallSchedule` provider (§ 3.5) defines the seam; specific vendor adapters land in the fork model, not upstream. |
| DORA metric ingestion (change-failure-rate, deploy-frequency) | Deferred. | MTTR + lead time already exist in [goals-and-metrics.md](goals-and-metrics.md); the two missing pieces need a git-history reader that is out of P2 scope. |

## 3. Structural changes (design contract)

Every subsystem below MUST honor the standing invariants in
[architecture.instructions.md § Safety Invariants](../../.github/instructions/architecture.instructions.md#safety-invariants):
every autonomous action carries a stop-condition, a rollback path, a
blast-radius limit, and an audit entry, and new capabilities ship in
shadow mode first.

### 3.1 Incident as a first-class object

**Problem.** Event correlation today produces an `incident_id` string
inside `event_ingest`, but there is no `Incident` dataclass, no state
machine, and no lifecycle hook. As a result:

- multiple findings against one correlated group are not siblings on
  one entity - they are just events sharing a key;
- there is nowhere to hang a postmortem, an on-call handoff, or an
  after-action review;
- audit queries by incident require full-scan filters, not an
  incident-indexed lookup.

**Design.**

- **Schema**: `shared/contracts/incident/schema.json` (JSON Schema
  2020-12) + pydantic `Incident` model in `shared/contracts/models.py`.
  Fields: `incident_id` (deterministic from correlation keys),
  `state`, `severity`, `opened_at`, `mitigated_at`, `resolved_at`,
  `closed_at`, `correlation_keys`, `member_event_ids`,
  `related_finding_ids`, `related_action_ids`, `assignee_oid`
  (Entra OID; distinct from submitter to preserve no-self-approval),
  `mitigation_summary`, `postmortem_ref`.
- **State machine**: `open → triaging → mitigated → resolved → closed`
  with reopen paths `resolved → triaging`. Illegal transitions raise
  `IncidentTransitionError`. Transitions are idempotent by
  `(incident_id, target_state, actor_oid)`.
- **Persistence**: extends `StateStore` with
  `append_incident_transition(entry: Mapping)`; the concrete Postgres
  adapter hash-chains transitions into the same audit stream (see
  [security-and-identity.md § Auditability](security-and-identity.md)),
  so nothing bypasses the append-only guarantee.
- **Ownership**: `core/incident/` (new package). Verticals emit
  candidate transitions; the incident module is the sole writer that
  can call `append_incident_transition`.

**Storm handling.** When one root fault fans out into many correlated
incidents, firing every remediation at once multiplies blast radius,
races on shared dependencies, and buries the operator. `core/incident/storm.py`
(`StormCoordinator`) is a deterministic, I/O-free incident-command
planner that a human commander's judgment is distilled into:

- **Storm detection** counts signals inside a sliding window; a count at
  or above the threshold is a storm.
- **Priority sequencing** orders remediations by severity (SEV1 first),
  then blast radius, then a stable id, so the plan is reproducible.
- **Concurrency cap** splits the ordered plan into capped waves; under a
  storm the cap tightens (default 1 = strictly serial) so a fan-out does
  not execute in parallel.
- **Dynamic HIL** returns a `StormPolicy` that, while a storm is active,
  raises the approval bar (escalate at or above a configured severity) so
  nothing high-impact auto-executes mid-storm.

The coordinator is advisory - the risk gate and executor consume its
`StormPolicy` and ordered plan; it never executes, holds a lock, or calls
a model, so it stays under the `core/` import rule.

### 3.2 Telemetry ingestion seam (Layer-0 expansion)

**Problem.** [csp-neutrality.md](csp-neutrality.md) declares five
wire-level contracts (event bus, state store, secret, workload
identity, inventory). OpenTelemetry emits control-plane traces, but
nothing consumes external metrics, logs, or traces. That caps the
`observability-and-detection.md` design at correlation only - anomaly,
forecast, and RCA cannot ground on real telemetry.

**Design.**

- **Three new async Protocols under `shared/providers/`**:
  - `MetricProvider.query(query: MetricQuery) -> AsyncIterator[MetricPoint]`
    (backed by Prometheus PromQL, Azure Monitor Logs, or CloudWatch;
    upstream ships local no-op + a documented shape).
  - `LogQueryProvider.query(query: LogQuery) -> AsyncIterator[LogRecord]`
    (backed by Log Analytics KQL, Loki LogQL, etc.).
  - `TraceQueryProvider.query(query: TraceQuery) -> AsyncIterator[Span]`
    (backed by App Insights, Tempo, Jaeger).
- Wire contract count grows **5 → 8**; [csp-neutrality.md](csp-neutrality.md)
  is updated in the same PR that introduces the seams.
- **Default upstream binding**: local no-op providers that return
  empty iterators. Real adapters (Azure Monitor, Log Analytics) land
  in `delivery/azure/` in a follow-up work item; the seam is enough
  for the anomaly / forecast / RCA subsystems to be authored against
  a stable interface.
- **Where the data flows**: providers produce structured records that
  become `Event` objects on the internal bus, so the trust-router and
  risk-gate stay the sole authority for what runs autonomously.

### 3.3 Workload SLO subsystem

**Problem.** [deployment.md § Observability, SLOs, and Alerting](deployment.md)
defines **control-plane** SLOs (FDAI's own latency, success rate,
console availability). The missing half is **workload-facing SLOs** -
the SLI/SLO/error-budget layer that ranks user-facing incident
priority and gates risky change during error-budget burn.

**Design.**

- **Schema**: `shared/contracts/slo/schema.json` for `SLI` (query +
  threshold + kind={availability, latency, correctness, freshness}),
  `SLO` (objective ratio + window), `ErrorBudget` (derived), and
  `BurnRate` (short + long window).
- **Module**: `core/slo/` with `SloRegistry` (load YAML SLOs from
  `rule-catalog/slo/`) and `BurnRateEvaluator` (multi-window
  multi-burn-rate alerting per Google SRE Chapter 5).
- **Wire back to control loop**: a burn-rate breach emits an
  `Event(event_type="slo.error_budget_burn")` that hits the same
  trust-router → risk-gate → executor path. No side channel.
- **What the SLO subsystem does NOT do**: it does not replace
  `goals-and-metrics.md`. That file measures **FDAI's own
  performance**; the SLO subsystem measures **the workloads FDAI
  operates on**. They coexist with clearly separated identities.

### 3.4 Runbook DAG orchestrator

**Problem.** `ActionType` in the ontology is a leaf action with a
`stop_condition`, `rollback_contract`, and `blast_radius`. A
real-world SRE runbook chains multiple ActionTypes (e.g. `db.failover`
→ `app.restart` → `healthcheck` → on-fail `db.rollback`). There is no
composition primitive today.

**Design.**

- **Schema**: `shared/contracts/runbook/schema.json` - an ordered
  sequence of `RunbookStep` entries, each pointing at an ActionType
  by name, plus an optional `on_failure` branch step id.
- **Runner**: `core/runbook/runner.py` with `RunbookRunner.run(runbook,
  context)` returning a `RunbookResult` (per-step outcomes + terminal
  state). The runner honors the four safety invariants **on every
  step** (not just the terminal one) - a failing step's rollback
  branch is itself audited before the runner short-circuits.
- **Minimum viable scope**: linear sequence + single `on_failure`
  branch (a real DAG is deferred until we have two callers who need
  it). Enough to encode "failover → restart → healthcheck → rollback".
- **Docs**: reuses [action-ontology.md](action-ontology.md)
  vocabulary; new sibling doc `docs/roadmap/runbook.md`.

### 3.5 On-call schedule provider

**Problem.** `HilChannel` routes approvals to a Teams channel; RBAC
picks approvers by role. Neither knows **who is on shift right now**.
At 3am the "same" approver bucket is 20 people asleep.

**Design.**

- **Protocol**: `OnCallSchedule.current(rotation: str) -> OnCallShift`
  in `shared/providers/oncall_schedule.py`, returning
  `OnCallShift(rotation, primary_oid, secondary_oid, until)`.
- **Default upstream implementation**: `StaticOnCallSchedule` reading
  a JSON list of shifts from config. Fork model wires PagerDuty /
  OpsGenie adapters.
- **Integration**: `HilChannel.dispatch(...)` accepts an optional
  `on_call_shift`; the coordinator layer consults `OnCallSchedule`
  before dispatching so the paged party is the shift-holder, not the
  role bucket.
- **Fail-closed**: if the schedule provider errors, the HIL request
  falls back to the whole role bucket (existing behavior) - never
  drops the request.

### 3.6 Postmortem draft generator

**Problem.** SRE culture demands a written PIR / postmortem after
every significant incident. FDAI has the raw material (audit log,
findings, actions) but no synthesizer.

**Design.**

- **Module**: `core/postmortem/` with a `PostmortemGenerator` that
  takes an `Incident` id + a `PostmortemLlm` optional binding and
  returns a `PostmortemDraft` (structured markdown: summary, timeline,
  impact, root cause, contributing factors, actions taken, follow-ups).
- **Fail-closed on LLM absence**: if `PostmortemLlm` is not bound,
  the generator returns a **template-based** draft from the audit
  timeline alone - no fabrication, no missing sections marked
  "TODO"; each section is filled with the actual audit data or an
  explicit "no evidence recorded" line.
- **Output persistence**: draft is written to a git-managed location
  under `rule-catalog/postmortems/<incident-id>.md` via the same
  PR-native delivery flow that ships remediation PRs, so review /
  approval reuses the existing gate. This intentionally reuses the
  `pr_native` execution path from
  [action-ontology.md](action-ontology.md).
- **Knowledge extraction (reusable lesson)**:
  `core/postmortem/learning.py` (`PostmortemKnowledgeExtractor`) mines a
  *resolved* incident plus its audit timeline into an inert
  `PostmortemLearning` candidate - the "when this pattern happened, this
  action resolved it" knowledge an organization otherwise keeps only in
  an engineer's head. It is deterministic and **fail-closed**: it emits a
  learning only when the audit trail carries a recorded root cause *and*
  at least one successfully executed (enforce-mode, success-outcome)
  action, and **abstains** otherwise - never fabricating a lesson. The
  learning generalizes away from specific resource ids (it anchors on
  correlation-key *prefixes*, so `resource:vm-a` contributes the reusable
  anchor `resource`, not `vm-a`), carries a deterministic `signature` so
  the discovery loop can deduplicate recurring patterns, and ships a
  grounded `provenance` so it clears the same `CandidateGuard` as any
  other rule candidate. The output is knowledge, not an action and not a
  catalog edit: it feeds the memory / discovery loop
  ([rule-catalog-collection.md](rule-catalog-collection.md)) and must
  clear the standard quality gate before it can influence the catalog.

### 3.7 T1 / T2 tiers wired into `ControlLoop`

**Status.** T1 is wired; T2 remains. `ControlLoop.__init__` accepts an
optional `t1_engine` (Protocol-typed `T1Tier`), and `process` runs
`T0.abstain -> T1.reuse-log`: a T1 similarity hit is recorded as
`T1_REUSE_LOGGED` and never executed in P1 (a reuse must clear the
verifier + risk-gate first, which is P2). Each tier hop writes its own
audit entry, so the decision stays reconstructable. What is **not** yet
built is T2: `core/tiers/t2_reasoning/` is a stub (no engine), so
`ControlLoop` has no `t2_engine` parameter.

**Remaining design (T2).**

- Build the `t2_reasoning` tier library first (it is a stub today).
- Add an optional `t2_engine` parameter to `ControlLoop.__init__`
  (Protocol-typed, no concrete class import in `core/control_loop.py`
  beyond the Protocol).
- Flow: `T1.abstain -> T2.propose + quality-gate -> risk-gate`. The
  quality gate (mixed-model cross-check, verifier, grounding) grants
  execution eligibility; the model never does.

**Scenario replay.** The frozen scenarios in
[tests/scenarios/v2026.07/](../../tests/scenarios/v2026.07/) are enriched
at T0 through overlays under
[tests/scenarios/enrichment/v2026.07/](../../tests/scenarios/enrichment/v2026.07/)
wherever a shipped rule maps - e.g.
`finops.stop-idle-dev-vm-off-hours.003` fires `compute.vm.idle-detected`.
Scenarios still lacking an overlay stay `xfail`:
`dr.chaos-experiment-novel.003` (needs T2),
`dr.replica-lag-degraded.001` (needs an authored overlay), and
`dr.backup-vault-restore-rehearsal.002` /
`change.drift-manual-portal-edit.003` (need a shipped rule authored).

### 3.8 Vertical registry (new-domain onboarding seam)

**Problem.** FDAI ships three verticals (Resilience, Change Safety, Cost
Governance), but "replace an organization" means the set must grow -
security posture, compliance, patch management - **without editing
`core/`**. Today the three are composed directly; there is no declared
seam for a fork to onboard a fourth.

**Design.**

- **Module**: `core/verticals/registry.py` with a `VerticalRegistry` that
  holds inert `VerticalDescriptor`s (`vertical_id`, `display_name`,
  `category`, `rule_source_ids`, `enabled`, `default_mode`). A fork
  registers a descriptor at the composition root; the control loop
  enumerates the registry instead of hard-coding the three.
- **Validating, not a plugin loader.** Registration rejects a
  misconfigured onboarding at once: a duplicate or non-ASCII
  `vertical_id`, an **enabled** vertical that names no rule source (a
  domain that detects nothing), or a descriptor that tries to onboard
  directly in enforce mode. `register_all` aborts on the first failure so
  a partial batch cannot half-register.
- **Shadow-first by construction.** `default_mode` defaults to
  `Mode.SHADOW` and MUST stay shadow at onboarding - promotion to enforce
  is a separate reviewed change, so onboarding can never silently enable
  autonomous action. Enumeration (`all`, `enabled`) is id-sorted and
  deterministic.

## 4. Rollout order and safety mode

Every subsystem above ships in **shadow mode** first
([architecture.instructions.md § Safety Invariants](../../.github/instructions/architecture.instructions.md#safety-invariants)).
Promotion to enforce is a separate change, gated on the shadow
accuracy the module's `promotion_gate` declares (mirroring the rule /
ActionType promotion contract).

Rollout order picks the strict prerequisite chain:

1. **§ 3.1 Incident** and **§ 3.2 Telemetry** are independent - both
   ship in the same phase, either order.
2. **§ 3.7 T1/T2 wiring** - T1 is already shipped; T2 depends on
   building the `t2_reasoning` tier library first.
3. **§ 3.3 SLO** depends on § 3.2 (real burn-rate needs metric
   ingestion).
4. **§ 3.6 Postmortem** depends on § 3.1.
5. **§ 3.5 On-call** is independent.
6. **§ 3.4 Runbook** is independent - it composes existing
   ActionTypes.

## 5. What this document is not

- Not a phase plan. Phases live under
  [docs/roadmap/phases/](phases/) and slot these subsystems in per
  the maintainer's schedule.
- Not a customer-facing spec. FDAI stays customer-agnostic; the
  wire contracts in § 3.2 keep the fork model
  ([generic-scope.instructions.md](../../.github/instructions/generic-scope.instructions.md))
  intact.
- Not a claim of complete operations coverage. The deferred axes in
  § 2 remain deliberately out of scope until a phase explicitly picks
  them up.

## 6. SRE Agent duty coverage

An honest map of the baseline duties an SRE agent is expected to cover
against the FDAI subsystem that implements each one. `Covered` means a
`core/` subsystem plus its rules/tests exist; `Partial` means the
subsystem exists but a declared dependency is still deferred; `Deferred`
means only the seam is designed (§ 2 / § 3), not wired.

| SRE duty | Status | Where |
|----------|--------|-------|
| Incident detection / triage / lifecycle | Covered | `core/incident/` (§ 3.1), `core/event_ingest/` |
| Root-cause analysis | Covered | `core/rca/`, [observability-and-detection.md](observability-and-detection.md) |
| Automated mitigation (risk-gated) | Covered | `core/risk_gate/`, `core/executor/`, [risk-classification.md](risk-classification.md) |
| Postmortem | Covered | `core/postmortem/` (§ 3.6) |
| Anomaly / forecast / correlation | Covered | `core/detection/`, [observability-and-detection.md](observability-and-detection.md) |
| Capacity planning | Covered | `core/capacity/` |
| Runbook orchestration | Covered | `core/runbook/` (§ 3.4) |
| Change safety / pre-deploy feasibility | Covered | `core/deploy_preflight/`, [deployment-preflight.md](deployment-preflight.md) |
| Posture review / architecture Q&A | Covered | `core/assurance_twin/`, [assurance-twin.md](assurance-twin.md) |
| **Dev-to-ops handoff (policy + RBAC review)** | Covered | [operational-readiness.md](operational-readiness.md) (ORR) |
| **Identity / RBAC least-privilege posture** | Covered | workload RBAC rule pack (`*.role-assignment.*`) + `remediate.right-size-role` |
| SLO / error budget | Partial | `core/slo/`: `MetricBurnRateSource` bridges the § 3.2 metric seam to the burn-rate evaluator and `SloBurnRunner.run_once` publishes `slo.error_budget_burn` events (fail-closed on missing data); only a real vendor `MetricProvider` adapter + an infra cron trigger remain |
| Monitoring / alerting (external signal ingestion) | Partial | `core/detection/` correlation shipped; the § 3.2 metric / log / trace Protocols + in-memory bindings exist, a real vendor adapter is not yet wired |
| On-call schedule / paging | Partial | § 3.5 `OnCallSchedule` seam + core `OnCallResolver` (fail-safe fallback) wired into HIL parking + audit (records who was on shift); a PagerDuty / OpsGenie vendor adapter and card DM-targeting land in a fork (§ 2) |
| Status page / stakeholder broadcast | Deferred | § 2 (Incident object is the prerequisite) |
| DORA change-failure-rate / deploy-frequency | Deferred | § 2 (needs a git-history reader) |

The two `Partial` rows now share a single remaining prerequisite - a real
vendor `MetricProvider` adapter bound at the composition root. The § 3.2
Protocols, their in-memory bindings, the `core/slo/` bridge that consumes them,
and the `SloBurnRunner` that publishes breach events all exist; only the
concrete backend and the out-of-band cron trigger that calls `run_once` are
left, and both land additively (a fork adapter + an infra job) without a
`core/` rewrite. The `Deferred` rows are seams by design, not gaps in the
control loop.

