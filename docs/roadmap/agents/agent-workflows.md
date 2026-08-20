---
title: Agent Workflows
---

# Agent Workflows

The thirteen cross-agent workflows that the pantheon composes into product-level
capabilities. Each workflow names its participating agents, its trigger,
its end-to-end sequence, and its exit criteria. Every workflow ships in
shadow mode first ([agent-pantheon-implementation.md § Wave 7](agent-pantheon-implementation.md#11-wave-7---cross-agent-workflows-in-shadow))
and is promoted per-workflow after Wave 8 measures its KPIs.

> **Scope:** the workflows are customer-agnostic. Concrete resource names
> in examples are placeholders
> ([generic-scope.instructions.md](../../../.github/instructions/generic-scope.instructions.md)).
>
> **Contract:** every step is a pub/sub event on a schema-checked topic
> (see [agent-pantheon.md § 6.1](agent-pantheon.md#61-typed-port)). No
> workflow uses direct RPC between agents. HIL steps go through Var; audit
> goes through Saga. There are no shortcuts.
>
> **Machine-readable form.** Shipped executable workflows live under
> [`rule-catalog/workflows/`](../../../rule-catalog/workflows). This design
> inventory is broader than the current catalog and does not imply one file per
> section. The schema, `Process` ObjectType, and compile-to-Runbook wiring are
> defined in [process-automation.md](../decisioning/process-automation.md).

## Implementation status

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| Thirteen-workflow metadata registry | implemented | `services/core-control-plane/src/fdai/agents/_framework/workflows.py`; `services/core-control-plane/tests/agents/test_wave7_workflows.py` | All registered workflows default to `shadow`; the registry is metadata and does not by itself prove a deployed end-to-end workflow. |
| Executable shadow trace references | implemented | `services/core-control-plane/tests/agents/test_wave7_workflows.py`; `services/core-control-plane/tests/composition/test_readiness_service.py`; `services/core-control-plane/tests/core/test_control_loop_operator_request.py`; `services/core-control-plane/tests/agents/test_detection_readiness.py` | Focused tests cover the registered trace paths. They are implementation evidence, not retained operational traces. |
| Published workflow sequence diagrams | validated | `docs/diagrams/fdai-agent-workflows-*.diagram.yaml`; `tools/architecture-diagrams/test/agent-workflows.test.ts`; exact-SHA CI and Pages runs; live bilingual geometry checks | All twelve published diagrams show complete sender and receiver names plus the typed message in centered bilingual cards. This presentation adds no direct call, workflow state, authority, or promotion evidence. |
| Machine-readable workflow catalog | in-progress | `rule-catalog/workflows/`; `docs/roadmap/decisioning/process-automation.md` | The executable catalog is intentionally narrower than this design inventory and is not a one-file-per-section projection. |
| Measured promotion gates | not-started | Promotion thresholds in this document and `services/core-control-plane/src/fdai/agents/_framework/workflows.py` | No retained evidence demonstrates the required shadow durations, KPI baselines, or per-workflow gate results. |
| Enforce-mode promotion | not-started | `default_mode="shadow"` in `services/core-control-plane/src/fdai/agents/_framework/workflows.py` | Promotion remains independent per workflow; retrospective what-if is inherently shadow and is not eligible for enforcement. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-08-20 | validated | Retained exact-source CI, Pages deployment, and live bilingual geometry evidence for the corrected workflow diagrams. Every one of the 24 deployed SVGs exposes a message body for every node, centers the sequence with zero delta, and has zero text overflow or node overlap; the English and Korean routes also have no page or diagram-host overflow at desktop, constrained-desktop, or mobile widths. | Commit `c22ea624b`; [CI run 32336843459](https://github.com/dotnetpower/fdai/actions/runs/32336843459); [Pages run 32336843527](https://github.com/dotnetpower/fdai/actions/runs/32336843527); live `1440x900`, `993x641`, and `390x844` checks. | None for the published sequence-diagram regression. Runtime promotion evidence remains separately open. |
| 2026-08-20 | implemented | Corrected the published sequence presentation after live review found that every workflow collapsed into a narrow left-aligned actor chain, hid typed messages from the visible cards, and truncated return-arrow senders such as Njord. Sequence cards now expose bounded message bodies, center the ordered chain, and preserve complete participant aliases. | `current change`; twelve bilingual workflow specs and mirrored assets; 95 diagram compiler tests, typecheck, artifact freshness, 35-pair public migration, 10 focused site contracts, and direct EN/KO geometry checks passed with zero text overflow or node overlap. | Retain exact-source Pages deployment evidence before closing the visual regression. Runtime promotion evidence remains separately open. |
| 2026-08-13 | implemented | Adopted the implementation ledger and reconciled the workflow inventory with the metadata registry and focused shadow tests. Earlier implementation provenance was not reconstructed. | current change; focused workflow tests | Complete catalog projection where required, retain operational shadow evidence, and evaluate promotion gates independently. |

### Remaining work

- [ ] Decide which design-inventory workflows require machine-readable catalog entries and preserve the documented non-1:1 boundary.
- [ ] Retain per-workflow shadow-duration, KPI-baseline, policy-escape, and trace evidence from an operating environment.
- [ ] Evaluate and record each eligible workflow's promotion result independently; do not promote retrospective what-if.

## 0. Workflow shape

Every workflow declaration follows the same structure:

- **Purpose** - what business capability the workflow delivers.
- **Trigger** - the event or schedule that starts the flow.
- **Agents** - primary and supporting, with role labels.
- **Sequence** - a mermaid diagram showing typed-port messages.
- **Exit criteria** - measurable conditions for shadow trace success.
- **Promotion gate** - the KPI thresholds required for enforce mode.
- **Anti-scope** - what the workflow deliberately does not do.

Workflows do not add new ontology types or ActionTypes; they consume the
existing catalog under `rule-catalog/action-types/` and the object types
under `rule-catalog/vocabulary/object-types/`. A workflow that needs new
types is a signal to open an upstream doc PR first.

## 1. Cost-aware fix

**Purpose.** Every SRE remediation carries an attached cost impact so the
verdict reflects both reliability and finance. Prevents automation from
saving one dollar of on-call time by spending ten dollars of compute.

**Trigger.** Heimdall publishes `object.drift` (declared vs actual state
mismatch) or `object.anomaly` on a resource with an existing rule match.

**Agents.** Heimdall (initiator), Njord (cost advisor), Forseti (judge),
Thor (executor), Saga (auditor).

![1. Cost-aware fix. The main stages are object.drift {resource, delta}, typed query {proposed_action, target_resource}, cost_estimate {monthly_delta_usd, confidence}, verdict = auto|hil|deny + cost_annotation, object.verdict {risk_verdict, cost_annotation}, dispatch by risk_verdict, object.action-run {result, cost_actual (post-execute)}, attribution event (async).](../../diagrams/generated/fdai-agent-workflows-01.en.svg)

**Exit criteria.**

- Verdict emits with `cost_annotation.monthly_delta_usd` and
  `cost_annotation.confidence`.
- Post-execute audit records `cost_actual` when settlement data available
  (T+24h).
- No auto verdict issued when `cost_annotation.monthly_delta_usd >
  fork_config.cost_ceiling` without HIL.

**Promotion gate.** 14 days shadow; Njord cost forecast MAPE < 20% on
this workflow's audit sample; zero missing cost_annotation on remediations.

**Anti-scope.** Not a budget enforcement (Njord already emits
`CostAnomaly` for that separately); this only annotates SRE actions with
cost.

## 2. Predictive scale

**Purpose.** Scale proactively before Freyr's forecast trips a threshold
instead of reactively after Heimdall detects saturation.

**Trigger.** Freyr recurring forecast run (hourly). When the forecast
predicts threshold breach within `fork_config.predictive_horizon`
(default 2 hours).

**Agents.** Freyr (initiator), Heimdall (early-signal cross-check), Njord
(cost check), Odin (arbitration if cost blocks scale), Forseti, Thor.

![2. Predictive scale. The main stages are proposed_action {scale_out, target, size}, typed query {resource, recent_signals}, signal_confirm {leading_indicators, confidence}, cost_impact query, cost_estimate, arbitration_request {sre_intent, cost_block}, arbitration_response, verdict {scale_out, size}, dispatch (auto if under ceiling).](../../diagrams/generated/fdai-agent-workflows-02.en.svg)

**Exit criteria.**

- Scale action lands >30 min before Heimdall reactive detection would
  have fired (measured against a paired reactive baseline).
- Odin arbitration invoked when cost blocks: exactly once per conflict.
- Zero false-positive scale (verified by post-hoc reactive baseline
  showing no threshold breach).

**Promotion gate.** 30 days shadow; Freyr forecast MAPE < 15% on this
workflow's samples; false-positive scale rate < 5%.

**Anti-scope.** Not autoscale rules (existing platform autoscale keeps
running); this triggers *deliberate* scale actions attributable to
Freyr's forecast.

## 3. DR drill orchestration

**Purpose.** Regular disaster-recovery rehearsal without waiting for a
real incident. Verifies Vidar's rollback paths, DR failover mechanics,
and observability all still work.

**Trigger.** Loki schedule (weekly by default, fork-configurable).

**Agents.** Loki (planner), Forseti (judge), Var (approver), Vidar (execution),
Heimdall (observation), Norns (learning), Saga.

![3. DR drill orchestration. The main stages are proposed_action {dr_drill, scope, blast_radius}, verdict = hil (drills are always HIL), approval, verdict {execute_drill}, execute rollback / failover in shadow env, observe_request, observations, object.rollback {result, observations, recovery_time}, audit signal, compare to baseline, emit drift signal if MTTR degraded.](../../diagrams/generated/fdai-agent-workflows-03.en.svg)

**Exit criteria.**

- Drill completes within Loki's declared blast_radius.
- Post-drill MTTR reported; comparison to previous drill baseline saved.
- Any MTTR degradation > 20% raises `RuleCandidate` for capacity or
  path change.

**Promotion gate.** 3 successful drills in shadow; drill duration <
declared budget; zero unplanned production side-effects (measured by
Heimdall's blast-radius audit).

**Anti-scope.** Not real DR - this is rehearsal only. Real DR
failover uses the same Vidar action type but with a different trigger
(incident-classified emergency).

## 4. Override -> Discovery

**Purpose.** Every human override of a rule verdict becomes a signal
for rule refinement. Frequent overrides on the same rule mean the rule
is either wrong, over-scoped, or missing a critical exception.

**Trigger.** Var records `Approval` where the operator's decision differs
from Forseti's proposed verdict (approve on deny, reject on auto, etc.).

**Agents.** Var (initiator), Saga (aggregator), Norns (learner), Mimir
(rule steward).

![4. Override -> Discovery. The main stages are object.approval {rule_id, override_signal}, signal (batched), rolling count per rule_id, threshold check, object.rule-candidate {rule_id, override_pattern, proposed_revision}, shadow evaluation on override cases.](../../diagrams/generated/fdai-agent-workflows-04.en.svg)

**Exit criteria.**

- Every override recorded with structured `override_signal`.
- Rule with override rate > threshold produces exactly one
  `RuleCandidate` per rolling window (dedup).
- Candidate references specific overrides so Mimir can review context.

**Promotion gate.** 60 days shadow; override-to-candidate conversion
rate matches expected pattern (i.e., not every override becomes a
candidate); false-candidate rate < 10% (Mimir reject rate).

**Anti-scope.** Does not auto-modify rules. Every candidate goes through
Mimir's normal promotion pipeline.

## 5. Security escalation

**Purpose.** Formalizes the privilege-escalation monitoring flow from
[agent-pantheon.md § 9](agent-pantheon.md#9-security-and-privilege-escalation-monitoring)
as a first-class workflow with promotion gate.

**Trigger.** Forseti emits `object.security-event` with
`type: privilege_escalation_attempt`.

**Agents.** Forseti (initiator), Heimdall (correlator), Odin (critical
severity path), Var (admin notification delivery via ChatOps), Saga.

![5. Security escalation. The main stages are object.security-event {initiator, action, severity_hint}, audit, correlate with recent events (rolling window), classify severity: low|medium|high|critical, propose notify_admin_privilege_violation, verdict = auto (governance notification), audit (card sent), escalate {evidence}, page on-call security channel.](../../diagrams/generated/fdai-agent-workflows-05.en.svg)

**Exit criteria.**

- Every RBAC-deny produces exactly one `SecurityEvent`.
- Severity classification is deterministic (counter + table only).
- Alert dedup: same-user same-action within 1h collapse to one card.
- Per-user rate limit: >5 cards/hour digest.

**Promotion gate.** 30 days shadow; zero false negatives on injected
critical patterns; false-positive rate on high < 5%.

**Anti-scope.** Does not implement permission-upgrade flow (that is
future work, see pantheon § 9.5).

## 6. Handoff -> Capability

**Purpose.** Every unhandled request (Handoff) is a capability gap.
Repeated handoffs of the same fingerprint should convert into new
rules or new agent capabilities.

**Trigger.** Saga writes `object.issue` (via `escalate_to_github_issue`
action). Norns aggregates by fingerprint.

**Agents.** Saga (initiator), Norns (aggregator), Mimir (rule steward),
Bragi (updated on capability delivery).

![6. Handoff -> Capability. The main stages are object.issue (open), aggregate by fingerprint (rolling), object.rule-candidate {source: handoff, evidence}, shadow evaluation, rule promoted, close_issue signal, comment on GitHub issue + close, capability update (visible in operator briefing).](../../diagrams/generated/fdai-agent-workflows-06.en.svg)

**Exit criteria.**

- Handoff fingerprint occurrence count monotonically tracked.
- RuleCandidate emitted when threshold exceeded (dedup: one candidate
  per fingerprint per rolling window).
- Auto-close after promotion + 24h regression clean.
- Closing comment links promoting PR.

**Promotion gate.** 90 days shadow; conversion rate (handoff ->
promoted rule) baseline captured; false-close rate < 2%.

**Anti-scope.** Does not auto-write rule text. Candidates carry
evidence and a proposed shape; Mimir + humans review and refine.

## 7. Agent health degradation

**Purpose.** When an agent itself is failing, the system detects it,
adjusts portfolio priority, and briefs operators - not silently
degrading and only surfacing when a workflow breaks.

**Trigger.** Heimdall recurring agent-health probe (per-minute
heartbeat + KPI compare vs baseline). Detects heartbeat gap, high
error rate, or KPI drift.

**Agents.** Heimdall (detector), Odin (portfolio re-planner), Bragi
(operator briefing), Saga.

![7. Agent health degradation. The main stages are probe each agent (heartbeat + KPI), audit event, agent_health_signal {agent, severity, evidence}, apply degradation policy per pantheon 11, briefing_update {impact, mitigation_active}, proactive card to admins.](../../diagrams/generated/fdai-agent-workflows-07.en.svg)

**Exit criteria.**

- Every agent probed at declared frequency.
- Degradation policy activation matches [pantheon anti-patterns table](agent-pantheon.md#11-anti-patterns)
  (e.g., Saga down -> mutations refused).
- Bragi briefing delivered within 60 seconds of detection.

**Promotion gate.** 30 days shadow; every declared degradation policy
tested by injected failure at least once; briefing latency p99 < 60s.

**Anti-scope.** Not self-heal - Heimdall does not restart failing
agents. Recovery is a separate operator action (ideally through Vidar
if a rollback path exists).

## 8. Judgment coherence audit

**Purpose.** Verifies that Forseti's verdicts remain consistent over
time - the same input should produce the same verdict, absent rule
change. Catches model drift, rule catalog corruption, and
non-determinism bugs.

**Trigger.** Forseti recurring self-test (daily). Samples recent
verdicts, re-runs them, compares.

**Agents.** Forseti (self-tester), Muninn (audit sample), Norns (drift
analyzer), Mimir (reviews if drift is caused by rule change), Saga.

![8. Judgment coherence audit. The main stages are fetch recent audit sample (N=1000), re-run judgment on same inputs, coherence_report {mismatches}, classify: rule_change | model_drift | non_determinism, confirm rule delta explains mismatch, object.rule-candidate {type: coherence_alert}, audit alert.](../../diagrams/generated/fdai-agent-workflows-08.en.svg)

**Exit criteria.**

- Daily coherence run completes within budget (< 15 min).
- Mismatch classification is deterministic.
- Any unexplained mismatch produces exactly one candidate + one audit
  alert.

**Promotion gate.** 60 days shadow; mismatch rate baseline captured;
false-drift-alert rate < 5%.

**Anti-scope.** Does not roll back rule changes automatically. Any
alert is investigatory.

## 9. Rollback rehearsal

**Purpose.** Proactively test that rollback paths declared in
ActionType `rollback_contract` actually work. Prevents finding out at
incident time that rollback is broken.

**Trigger.** Loki schedule (monthly). Picks a subset of ActionTypes
based on `fork_config.rollback_rehearsal_scope`.

**Agents.** Loki (planner), Forseti (judge), Var (approver), Vidar (rehearser),
Heimdall (observer), Saga.

![9. Rollback rehearsal. The main stages are proposed_action {rehearse_rollback, action_type_id}, verdict = hil (all rehearsals HIL), approval, verdict {execute}, apply mutation in shadow env, invoke rollback per rollback_contract, observe post-rollback state, state matches pre-mutation baseline?, audit {rehearsal_result, deviation}.](../../diagrams/generated/fdai-agent-workflows-09.en.svg)

**Exit criteria.**

- Rollback path executes without error.
- Post-rollback state matches pre-mutation baseline (deviation report
  attached).
- Any deviation raises `RuleCandidate` (rollback_contract needs
  update).

**Promotion gate.** 3 successful rehearsals per ActionType before that
type is eligible for enforce mode outside shadow. Rehearsal cadence
enforced by Loki schedule.

**Anti-scope.** Not production rollback (that uses the real path when
Vidar responds to a real failure).

## 10. Retrospective what-if

**Purpose.** Given a past incident (in audit log), re-play judgment
under different rule configurations to answer "if we had had this
rule at the time, would the incident have been prevented?" - crucial
for Mimir's rule promotion decisions.

**Trigger.** Manual (operator via Bragi) or scheduled (post-incident).

**Agents.** Saga (data source), Forseti (re-judge), Norns (delta
analysis), Mimir (rule evaluation), Bragi (report).

![10. Retrospective what-if. The main stages are if rule X existed on 2026-07-01, what would have happened?, fetch audit slice, fetch rule X (shadow overlay), replay with overlay, what-if verdicts, delta analysis, diff summary, report.](../../diagrams/generated/fdai-agent-workflows-10.en.svg)

**Exit criteria.**

- Replay is judge-only (never re-executes).
- Overlay is scoped (only replay events + only the added rule).
- Result reproducible (same input + same overlay = same output).

**Promotion gate.** Not applicable (this workflow is inherently
shadow - it never executes changes).

**Anti-scope.** Does not modify Saga audit log. Overlay is a
read-time projection.

## 11. Operational readiness handoff

**Purpose.** Gate the dev-to-ops boundary: before a dev-owned scope becomes
the operations team's responsibility, review its accumulated governance,
security, RBAC, and reliability posture and return one verdict
(`clear` / `needs_review` / `blocked`). Catches gaps a per-change review
misses - an over-privileged workload identity, a guest holding Owner, missing
backup - that no single diff introduced. Full design:
[operational-readiness.md](../operations/operational-readiness.md).

**Trigger.** Huginn normalizes an `ownership_transfer` signal (a handoff PR
label, a `lifecycle-stage: handoff` tag, or an operator `request_ops_handoff`)
carrying the target scope, submitter, and target environment.

**Agents.** Huginn (collector), Mimir (applicable rule set), Forseti (judge /
ReadinessReport), Var (HIL approver on blocked handoff + proposed fixes), Thor
(executor of approved fixes), Saga (auditor).

![11. Operational readiness handoff. The main stages are object.ownership-transfer {scope, submitter, environment}, applicable rules for scope, rule set (+ profile mode), run assurance-twin + deploy-preflight over scope, compose ReadinessReport (clear|needs_review|blocked), audit {verdict, blocks_handoff}, request approval + shadow remediation-PR proposals, approved fixes, object.action-run {result}.](../../diagrams/generated/fdai-agent-workflows-11.en.svg)

**Exit criteria.**

- Every `ownership_transfer` signal produces exactly one `ReadinessReport`.
- The verdict is truthful; `blocks_handoff` is true only in enforce mode.
- A promotion into `prod` treats any `critical` finding as blocking.
- Every finding cites a rule; an ungroundable finding abstains.
- A stale inventory refuses to certify rather than certify on stale state.

**Promotion gate.** 30 days shadow per environment; zero false negatives on
injected critical identity patterns; false-positive rate on blocking findings
< 5%.

**Anti-scope.** Does not execute fixes itself (proposes only; RBAC fixes route
to HIL via `remediate.right-size-role`). Does not define the environment model
(consumes [scope-expansion.md](../fork-and-sequencing/scope-expansion.md)). Not a per-deploy check
(that is [deployment-preflight.md](../deployment/deployment-preflight.md)).

## 12. Scheduled governed Python task

**Purpose.** Run an immutable generated Python artifact on one inventory-selected
GPU VM without giving the authoring surface a VM identity or accepting shell text.

**Trigger.** Strict five-field cron schedule materialized by the scheduler with a
target Resource and `PythonTask` artifact binding.

**Agents.** Bragi owns authoring translation, Forseti owns the risk verdict,
Var owns Owner HIL approval, Thor owns Managed Run Command execution, and Saga
owns the audit record. The current runtime maps these responsibilities to the
authoring API, scheduler plus `EventIngest`, unified risk gate, HIL resume
coordinator, and tool executor. The optional Pantheon consumer remains a shadow
observer and does not execute the proposal.

![12. Scheduled governed Python task. The main stages are raw operator_request {artifact_ref, target}, canonical Event plus trusted inventory context, validate ActionType, capability, freshness, blast radius, Owner HIL request, approval, tool.run-python-on-vm, stage, rehash cache, preflight, bounded execute, VmTaskRun receipt.](../../diagrams/generated/fdai-agent-workflows-12.en.svg)

**Exit criteria.** Every guest invocation rechecks the artifact files; the
target is an active inventory `compute.vm`; GPU tasks run only on a GPU-capable
target; retries reuse the same Managed Run Command; polling failure attempts a
remote cancel; every terminal result is audited.

**Promotion gate.** 14 days and 30 shadow plans; accuracy >= 99%; zero policy
escapes; explicit Owner review before `FDAI_VM_TASK_ENFORCE=1`.

**Anti-scope.** Does not provision VMs, install packages or drivers, accept shell
commands, pass source through the event bus, or bypass the risk gate.

## 13. Workflow catalog summary

| # | Name | Trigger | Primary agent | Enforce prerequisite |
|---|------|---------|---------------|----------------------|
| 1 | Cost-aware remediation | Drift / anomaly | Heimdall + Njord | Cost forecast MAPE < 20% |
| 2 | Predictive scale | Freyr forecast (hourly) | Freyr | Forecast MAPE < 15%, FP < 5% |
| 3 | DR drill orchestration | Loki schedule (weekly) | Loki | 3 shadow drills clean |
| 4 | Override -> Discovery | Var override event | Var | Conversion rate baseline |
| 5 | Security escalation | Forseti RBAC deny | Forseti | Zero critical FN, FP < 5% |
| 6 | Handoff -> Capability | Saga issue creation | Saga | Conversion baseline, FC < 2% |
| 7 | Agent health degradation | Heimdall probe | Heimdall | Every degradation tested |
| 8 | Judgment coherence audit | Forseti self-test | Forseti | Drift-alert FP < 5% |
| 9 | Rollback rehearsal | Loki schedule (monthly) | Loki | 3 rehearsals per ActionType |
| 10 | Retrospective what-if | Operator or post-incident | Bragi | (inherently shadow) |
| 11 | Operational readiness handoff | `ownership_transfer` signal | Forseti | 30d shadow/env, zero critical FN, FP < 5% |
| 12 | Scheduled governed Python task | Strict cron schedule | Forseti + Thor | 30 plans, >= 99% accuracy, zero escapes, Owner HIL |
| 13 | Detection readiness assurance | `detection.readiness.observed` | Heimdall | 30d shadow/target, zero false-ready, stale p99 < 15m |
## Next steps

| To learn about | Read |
|----------------|------|
| The pantheon roles referenced above | [agent-pantheon.md](agent-pantheon.md) |
| The wave plan that lands each workflow | [agent-pantheon-implementation.md § Wave 7](agent-pantheon-implementation.md#11-wave-7---cross-agent-workflows-in-shadow) |
| ActionType schema each workflow consumes | [action-ontology.md](../decisioning/action-ontology.md) |
| Risk classification each verdict resolves against | [risk-classification.md](../decisioning/risk-classification.md) |
