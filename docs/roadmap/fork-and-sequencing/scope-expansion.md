---
title: Scope Expansion and Structural Gaps
---
# Scope Expansion and Structural Gaps

FDAI is positioned as an autonomous cloud operations control plane
([copilot-instructions.md](../../../.github/copilot-instructions.md)), but
the initial verticals - Change Safety, Resilience, Cost Governance -
cover only a subset of the operations duties an FDAI deployment is
expected to grow into. This document freezes the **scope decision**
for the P2/P3 axis expansion, so every subsequent structural change
lands against a stated design intent instead of an implicit one.

Reference: the roadmap-level duty list is enumerated in
[goals-and-metrics.md](../architecture/goals-and-metrics.md) (KPI 1-4 + guard
metrics); the layered runtime shape lives in
[app-shape.instructions.md](../../../.github/instructions/app-shape.instructions.md);
CSP-neutral wire contracts live in
[csp-neutrality.md](../architecture/csp-neutrality.md); the trust-router / risk-gate /
control loop live in
[architecture.instructions.md](../../../.github/instructions/architecture.instructions.md).

> **Implementation status (2026-07-21).** Incident, all eight telemetry wire contracts,
> workload SLO, runbook, on-call, postmortem, and vertical registry from section 3 are shipped.
> Its `Problem` paragraphs preserve the historical gaps at adoption time. T2 candidate Action
> construction and unified risk/HIL routing are also shipped; only handing a risk-eligible T2
> Action to the executor remains.

## 1. In-scope axes (kept + expanded)

| Axis | Position | Rationale |
|------|----------|-----------|
| **Change Safety** | Kept vertical. Foundational. | Deterministic-first ⇢ policy-gate ⇢ shadow → enforce is the strongest current story. |
| **Resilience (DR/Chaos)** | Kept vertical. Chaos Studio adapter shipped. | Prod-exclusion invariant + `chaos:opt-out` tag already give a safety floor that is rare in industry. |
| **Cost Governance (FinOps)** | Kept vertical. | Aligns with FinOps guardrail pattern that is well-established. |
| **Incident lifecycle** | **Shipped.** See § 3.1. | Durable lifecycle, proposals, notifications, SLA, and storm coordination. |
| **Telemetry ingestion** | **Eight Layer-0 seams and Azure adapters shipped.** See § 3.2. | Metric/log/trace ground SLO, detection, and RCA. |
| **Workload SLO / error budget** | **Shipped.** See § 3.3. | Workload SLI/SLO/burn remains distinct from control-plane SLO. |
| **Runbook orchestration** | **Shipped.** See § 3.4. | Bounded step and rollback orchestration. |
| **On-call schedule** | **Shipped.** See § 3.5. | Static and PagerDuty schedules with role fallback. |
| **Postmortem draft** | **Shipped.** See § 3.6. | Template-first drafts and grounded learning candidates. |
| **Full T1/T2 wiring into ControlLoop** | **Action build + risk/HIL route shipped; eligible execution pending.** See § 3.7. | Quality-gated T2 candidates reach the unified risk gate as Actions. |

## 2. Explicitly-deferred axes (not in this expansion)

| Axis | Position | Rationale |
|------|----------|-----------|
| Multi-cloud (AWS / GCP) | Deferred to future phase. | Implementation focus stays Azure; the wire-contract seams (§ 3.2) keep an AWS adapter additive. |
| Predictive capacity / autoscaling | Deferred. | Depends on telemetry ingestion (§ 3.2) being real, not stubbed. Ship § 3.2 first, then this in a later phase. |
| Public status-page endpoint | Deferred. | Stakeholder briefings and multi-channel delivery shipped; only the public endpoint binding remains external. |

## 3. Structural changes (design contract)

Every subsystem below MUST honor the standing invariants in
[architecture.instructions.md § Safety Invariants](../../../.github/instructions/architecture.instructions.md#safety-invariants):
every autonomous action carries a stop-condition, a rollback path, a
blast-radius limit, and an audit entry, and new capabilities ship in
shadow mode first.

The `Problem` paragraphs below are historical adoption gaps; `Design` describes the landed
contract. Use the implementation status above and the section 6 coverage table for current status.

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
  `(incident_id, target_state, actor_oid)`. Severity can change only on the
  `resolved → triaging` reopen edge and is preserved in replay.
- **Persistence**: extends `StateStore` with
  `append_incident_transition(entry: Mapping)`; the concrete Postgres
  adapter hash-chains transitions into the same audit stream (see
  [security-and-identity.md § Auditability](../architecture/security-and-identity.md)),
  so nothing bypasses the append-only guarantee. The append returns
  `applied` or `duplicate`; stale expected state raises
  `IncidentWriteConflictError`. PostgreSQL holds a per-incident advisory lock,
  checks the persisted current state, and appends to the global audit hash
  chain in one transaction. A losing replica reloads the canonical audit
  projection before returning the conflict.
- **Ownership**: `core/incident/` (new package). Verticals emit
  candidate transitions; the incident module is the sole writer that
  can call `append_incident_transition`.
- **Lifecycle metadata**: assignment changes append `incident.assigned`; a
  successful GitHub/Jira/tool receipt appends `incident.ticket` with provider,
  external id, and an optional HTTPS URL. Both are idempotent, replay-safe,
  and visible through the same audit-backed incident roster. Vendor calls stay
  in delivery adapters; the registry only links their successful receipt.

**Built-in lifecycle workflow.** `IncidentLifecycleWorkflow` provides the
single creation and transition path above `IncidentRegistry`:

- An operator with the Contributor role can ask to open an incident in English
  or Korean. The deterministic parser requires an incident/open intent,
  severity, and target. It asks for missing fields instead of guessing. A
  complete request produces a 10-minute proposal and explains what will be
  created; only the same operator in the same conversation can confirm it.
- An allowlisted agent can open an incident without conversational
  confirmation only when it supplies at least one member event and a non-empty
  reason. This keeps autonomous creation grounded in observed evidence.
  Production passes Heimdall's repeated-event candidate hook to the same
  durable workflow before the pantheon starts consuming events.
- Open and same-state transition replays remain idempotent and do not send a
  duplicate notification. Every lifecycle audit row carries the deterministic
  incident id as its top-level `correlation_id`, so the console roster can
  project it without inferring an association from a resource name. New member
  events append `incident.members` rows so correlation growth survives restart.
- Creation, legal state changes, and requested roster summaries emit A2
  operational notifications through `RoutedIncidentLifecycleNotifier` wrapped
  by `DurableIncidentLifecycleNotifier`. Each lifecycle occurrence has a stable
  `audit_id`; a sent checkpoint prevents repeat delivery, and startup replay
  retries any audit row without a checkpoint. If no real channel adapter is
  bound, the production default routes the notice to the StateStore-backed HIL
  escalation sink instead of dropping it. Lifecycle messages omit free-form
  reasons and resource correlation keys; roster messages include at most 20
  incident ids and link to the full roster.

The in-process registry remains a projection, not the source of truth.
Production startup reads ordered `incident.open`, `incident.members`, and
`incident.transition` rows from Postgres and rebuilds the registry before the
API accepts traffic. Invalid ids, state ordering, or timestamps fail startup
without replacing the prior snapshot. Pending chat proposals use the async
`IncidentProposalStore`: local development binds a bounded in-memory store,
while production uses an atomic Postgres `DELETE ... RETURNING` consume so only
one replica can accept a confirmation. Persisted proposals store a hash of the
operator text, never the raw prompt. The local projecting store still makes a
chat-created incident appear in `/incidents` immediately.

**SLA escalation and metrics.** `IncidentSlaPolicy` accepts configured
acknowledgment and resolution seconds for every severity. The production
monitor is disabled until `FDAI_INCIDENT_SLA_POLICY_JSON` is supplied; when
enabled it derives the current state-entry timestamp from ordered audit rows,
emits a stable `sla_breach` A2 notice at the deadline, and relies on durable
notification checkpoints to suppress repeat scans. Resolved and closed
incidents do not alert. `project_incident_metrics` projects deduplicated audit
rows into creation totals (agent/operator), current state and severity counts,
assignment and ticket counts, reopen count, and mean acknowledgment/resolution
duration. These are measured facts suitable for KPI and briefing surfaces.
Successful `tool_call` ticket receipts pass through a receipt observer before
terminal executor success. Linkage failure stays retryable: the adapter ledger
returns `already_applied` on redelivery and only the incident link is retried.

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

**Problem.** [csp-neutrality.md](../architecture/csp-neutrality.md) declares five
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
- Wire contract count grows **5 → 8**; [csp-neutrality.md](../architecture/csp-neutrality.md)
  is updated in the same PR that introduces the seams.
- **Default upstream binding**: local no-op providers that return
  empty iterators. The first live `MetricProvider` adapter has landed -
  `delivery/azure/metric_logs.py` (`AzureMonitorLogsMetricProvider`,
  Log Analytics KQL over the query REST API), bound at the composition
  root via `bind_azure_monitor_logs` and defaulting to `Noop` in dev so
  the parity contract holds. The remaining `LogQueryProvider` /
  `TraceQueryProvider` adapters land in follow-up work items; the seam is
  enough for the anomaly / forecast / RCA subsystems to be authored
  against a stable interface.
- **Where the data flows**: providers produce structured records that
  become `Event` objects on the internal bus, so the trust-router and
  risk-gate stay the sole authority for what runs autonomously.

### 3.3 Workload SLO subsystem

**Problem.** [deployment.md § Observability, SLOs, and Alerting](../deployment/deployment.md)
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
- **Docs**: reuses [action-ontology.md](../decisioning/action-ontology.md)
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
  [action-ontology.md](../decisioning/action-ontology.md).
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
  ([rule-catalog-collection.md](../rules-and-detection/rule-catalog-collection.md)) and must
  clear the standard quality gate before it can influence the catalog.

### 3.7 T1 / T2 tiers wired into `ControlLoop`

**Status.** T1 and T2 are wired into the loop. T2 candidate Action construction, unified risk
evaluation, and deny/HIL routing are shipped; executor handoff for a risk-eligible candidate is the
remaining step. `ControlLoop.__init__` accepts optional `t1_engine`
(`T1Tier`) and `t2_engine` (`T2Tier`), both Protocol-typed. `process`
runs `T0.abstain -> T1.reuse-log -> T2.propose + quality-gate`, and each
tier hop writes its own audit entry so the decision stays
reconstructable. T1 reuse remains **shadow-only**. T2 candidate outcomes are recorded as
`T2_PROPOSED_LOGGED` / `T2_ESCALATED` / `T2_DENIED` / `T2_ABSTAINED`, and a proposed candidate
may continue through Action construction and risk/HIL routing. T2 output clears the `QualityGate` (mixed-model
cross-check + verifier + grounding) before it is even eligible.

**Remaining design (T2 execution).**

- Hand a T2 Action whose unified risk decision is `auto` to the selected executor and record its
  terminal receipt. Action construction and risk routing are complete.
- Only a gate `ELIGIBLE` verdict may reach the risk-gate; `ESCALATE` /
  `DENIED` / `ABSTAIN` never auto-execute. Execution eligibility is
  granted by the deterministic gate, never the model.

**Scenario replay.** The frozen scenarios in
[tests/scenarios/v2026.07/](../../../tests/scenarios/v2026.07) are enriched
at T0 through overlays under
[tests/scenarios/enrichment/v2026.07/](../../../tests/scenarios/enrichment/v2026.07)
wherever a shipped rule maps - e.g.
`finops.stop-idle-dev-vm-off-hours.003` fires `compute.vm.idle-detected`
and `dr.replica-lag-degraded.001` fires
`postgresql-server.high-availability` (HIL via the risk-gate).
Scenarios still lacking an overlay stay `xfail`:
`dr.chaos-experiment-novel.003` (needs T2) and
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
([architecture.instructions.md § Safety Invariants](../../../.github/instructions/architecture.instructions.md#safety-invariants)).
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
  [docs/roadmap/phases/](../phases) and slot these subsystems in per
  the maintainer's schedule.
- Not a customer-facing spec. FDAI stays customer-agnostic; the
  wire contracts in § 3.2 keep the fork model
  ([generic-scope.instructions.md](../../../.github/instructions/generic-scope.instructions.md))
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

The detailed comparison now tracks 51 atomic Azure SRE Agent capabilities, official Microsoft
Learn sources, runtime parity status, and exact FDAI evidence in
[the SRE Agent parity audit](../../internals/sre-agent-parity-audit.md). The table below remains the
short duty-level summary.

| SRE duty | Status | Where |
|----------|--------|-------|
| Incident detection / triage / lifecycle | Covered | `core/incident/` (§ 3.1), `core/event_ingest/` |
| Root-cause analysis | Covered | `core/rca/`, [observability-and-detection.md](../rules-and-detection/observability-and-detection.md) |
| Automated mitigation (risk-gated) | Covered | `core/risk_gate/`, `core/executor/`, [risk-classification.md](../decisioning/risk-classification.md) |
| Postmortem | Covered | `core/postmortem/` (§ 3.6) |
| Anomaly / forecast / correlation | Covered | `core/detection/`, [observability-and-detection.md](../rules-and-detection/observability-and-detection.md) |
| Capacity planning | Covered | `core/capacity/` |
| Runbook orchestration | Covered | `core/runbook/` (§ 3.4) |
| Change safety / pre-deploy feasibility | Covered | `core/deploy_preflight/`, [deployment-preflight.md](../deployment/deployment-preflight.md) |
| Posture review / architecture Q&A | Covered | `core/assurance_twin/`, [assurance-twin.md](../operations/assurance-twin.md) |
| **Dev-to-ops handoff (policy + RBAC review)** | Covered | [operational-readiness.md](../operations/operational-readiness.md) (ORR) |
| **Identity / RBAC least-privilege posture** | Covered | workload RBAC rule pack (`*.role-assignment.*`) + `remediate.right-size-role` |
| SLO / error budget | Covered | `core/slo/` plus routed Prometheus, Azure Monitor Metrics, and KQL providers; `SloBurnRunner` remains fail-closed on missing data |
| Monitoring / alerting (external signal ingestion) | Covered | metrics, bounded KQL, App Insights traces, Activity Log, diagnostic stream, anomaly, forecast, and RCA telemetry grounding |
| On-call schedule / paging | Covered | fail-safe `OnCallResolver`, PagerDuty roster adapter with explicit Entra mapping, PagerDuty Events v2 paging, and role fallback |
| Status page / stakeholder broadcast | Covered | stakeholder briefing composer plus Teams, Slack, email, webhook, PagerDuty, and SMS channels; a public status-page endpoint remains an external binding |
| DORA change-failure-rate / deploy-frequency | Covered | `core/measurement/dora.py` computes all four DORA measures from normalized deployment observations with explicit invalid/coverage counts |

Deployment credentials and endpoints remain external configuration, not repository gaps. An
unconfigured adapter reports unavailable or uses the documented role fallback; it never substitutes
fixtures or promotes autonomy. Direct write CLI and global auto-approval are intentionally replaced
by FDAI's typed action, policy, risk, approval, rollback, lock, idempotency, and audit path.
