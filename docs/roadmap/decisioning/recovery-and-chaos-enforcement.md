---
title: Recovery and Chaos Enforcement
---
# Recovery and Chaos Enforcement

This document defines how FDAI turns a grounded causal hypothesis into a recoverable action plan
and how an approved chaos experiment can run in enforcement mode without exceeding its impact
scope. Recovery and experiment execution reuse the existing ActionType, workflow, safety check,
approval, executor, and audit contracts.

> **Authority boundary:** Impact analysis can preserve or lower autonomy. It cannot promote an
> action, approve an experiment, or replace the authoritative promotion registry.
>
> **Chaos boundary:** Loki proposes experiments and every chaos enforcement run requires human
> approval. Thor remains the sole privileged executor, Var remains the independent approver, and
> Vidar owns rollback and recovery control.
>
## Implementation status

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| Impact analysis and envelope compilation | implemented | [`impact_analysis`](../../../services/core-control-plane/src/fdai/core/impact_analysis), [`test_impact_analysis.py`](../../../services/core-control-plane/tests/core/impact_analysis/test_impact_analysis.py) | Bounded traversal, feature calculation, incomplete-evidence refusal, and impact caps have focused coverage. |
| Recovery-plan contracts and state transitions | implemented | [`test_recovery_plan.py`](../../../services/core-control-plane/tests/core/verticals/test_recovery_plan.py), [Ontology contract](#ontology-contract) | Versioned plans and recovery transitions exist; this does not prove a live recovery outcome. |
| Continuous guard and independent verification | implemented | [`test_impact_analysis.py`](../../../services/core-control-plane/tests/core/impact_analysis/test_impact_analysis.py), [Runtime state machine](#runtime-state-machine) | Guard and verification mechanics fail closed on stale, incomplete, or over-envelope evidence. |
| Governed catalog execution path | in-progress | [`governed.py`](../../../services/core-control-plane/src/fdai/delivery/chaos/governed.py), [`test_governed.py`](../../../services/core-control-plane/tests/delivery/chaos/test_governed.py), [`test_governed_recovery.py`](../../../services/core-control-plane/tests/delivery/chaos/test_governed_recovery.py), [`test_mutation_scope.py`](../../../services/core-control-plane/tests/delivery/chaos/test_mutation_scope.py), [`test_reference_sweep.py`](../../../services/core-control-plane/tests/core/chaos/test_reference_sweep.py), [`test_run_catalog_scenario.py`](../../../tests/integration/scripts/test_run_catalog_scenario.py), [`test_chaos_raw_path_guard.py`](../../../tests/integration/scripts/test_chaos_raw_path_guard.py), [Governed execution path](#governed-execution-path) | Catalog CLI runs delegate only through the injected adapter, which enforces the distributed target lock, durable target claims that only verified outcomes or a separate audited Var closure decision release, the exclusive injection claim, the tier ceiling, exact per-target mutation scope, and separate detection verdicts. The reference sweep is now one governed selection on the same path. The CLI still calls the adapter directly instead of the Core proposal, risk, Var, and Thor pipeline, the detection-latency driver only refuses, and no deployment provider, promotion, or live evidence exists. |
| S1-S14 governed chaos campaign and executor binding | in-progress | [`constitution-traceability.json`](../../../config/constitution-traceability.json), [Delivery status](#delivery-status) | Scenario taxonomy exists, but constitutional domain coverage remains incomplete and no governed live executor campaign is retained. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-08-14 | in-progress | Adopted the implementation ledger without reconstructing earlier provenance and separated tested mechanics from operational enforcement evidence. | `current change`; current source, focused tests, and constitutional traceability listed in the scope table. | Bind the governed executor and complete the frozen recovery and chaos campaign. |
| 2026-09-28 | implemented | Replaced the catalog runner's direct `FaultInjectionHarness` enforce path with `GovernedChaosExecutionAdapter`, which delegates each typed `tool.run-chaos-experiment` request to `GovernedChaosRunner` over a Saga-audited run store. Deployment-owned `GovernedChaosBindings` supply promotion, Var approval verification, the run plan, Thor recovery dispatch, independent recovery evidence, and target locks; an unbound checkout refuses with a structured report. No scenario, ActionType, or Workflow was promoted. | `current change` in `services/core-control-plane/src/fdai/delivery/chaos/governed*.py`, `scripts/catalog/run-catalog-scenario.py`, and the linked focused tests; `uv run pytest -q --no-cov services/core-control-plane/tests/delivery/chaos/test_governed.py services/core-control-plane/tests/delivery/chaos/test_governed_recovery.py tests/integration/scripts/test_run_catalog_scenario.py` passed 47 tests for success, denial, duplicate, forced-stop, rollback, and restart; Ruff and strict mypy passed. | Supply a deployment provider and runtime binding, collect shadow-only evidence on an approved disposable target, then complete promotion and the S1-S14 campaign. |
| 2026-09-28 | in-progress | Hardened the governed catalog path after independent review. Bindings now require a distributed target lock; a durable per-target claim denies new runs while any non-terminal run holds the target; only the writer whose compare-and-swap applies `injecting` may run the harness; catalog targets are the canonical identities of the resources each scenario mutates, and every factory-built injector declares its mutation scope; the ActionType tier ceiling denies T1 and T2 requests; and recovery and detection are reported separately, so an undetected fault fails the run. The raw reference-sweep and detection-latency drivers now refuse every live run, so the protected scenario-lab sweep fails closed until they are ported. | `current change` in `services/core-control-plane/src/fdai/core/chaos/`, `services/core-control-plane/src/fdai/delivery/chaos/`, `scripts/catalog/`, and the linked tests; `uv run pytest -q --no-cov services/core-control-plane/tests/delivery/chaos services/core-control-plane/tests/core/chaos tests/integration/scripts/test_run_catalog_scenario.py tests/integration/scripts/test_chaos_raw_path_guard.py tests/integration/infra/test_scenario_lab.py` passed 331 tests, including 200-seed concurrent-interleaving and orphaned-run tests; Ruff and strict mypy passed. | Route catalog submissions through the Core pipeline with the adapter bound in `runtime/delivery.py`, port the raw drivers, supply a deployment provider, then collect shadow-only evidence before any promotion. |
| 2026-09-28 | in-progress | Closed the re-review findings. A target claim now passes to another run only after the holder recovered, was denied, or failed without injecting (the outcome record retains `injected`); escalated, failed-after-injection, orphaned, and unknown holders keep it until an audited, create-only closure approved by a distinct Var approver through the injected verifier releases it, and `run-catalog-scenario.py --close` exposes that closure by target. The BlockChaos body now selects the workload pods its scope declares, and every target must be exactly the one resource its injection mutates. | `current change` in `services/core-control-plane/src/fdai/delivery/chaos/`, `scripts/catalog/run-catalog-scenario.py`, and the linked tests; `uv run pytest -q --no-cov services/core-control-plane/tests/delivery/chaos services/core-control-plane/tests/core/chaos tests/integration/scripts/test_run_catalog_scenario.py tests/integration/scripts/test_chaos_raw_path_guard.py tests/integration/infra/test_scenario_lab.py` passed 357 tests, including rollback-failed, escalated, failed-without-injection, orphan, and self-approval closure cases; Ruff and strict mypy passed. | Route catalog submissions through the Core pipeline, port the raw drivers, supply a deployment provider, then collect shadow-only evidence before any promotion. |
| 2026-09-28 | in-progress | Closed the round-3 review findings. Closure is now a separate decision: `verify_closure` must return `closure`-intent evidence for the exact run and target digests, the CLI reads it from `FDAI_CHAOS_CLOSURE_APPROVAL_REF`, and each run binds its enforce-approval digest so that approval can never close it; enforce approvals with the `closure` intent or another run id are rejected. An injection call that raises now counts as injected, so the harness rolls it back and the run is released only after recovery and independent verification. Closing a run before `injecting` denies it through a compare-and-swap, and the exclusive `injecting` transition re-checks closure. | `current change` in `services/core-control-plane/src/fdai/core/chaos/harness.py`, `services/core-control-plane/src/fdai/delivery/chaos/`, `scripts/catalog/run-catalog-scenario.py`, and the linked tests; `uv run pytest -q --no-cov services/core-control-plane/tests/delivery/chaos services/core-control-plane/tests/core/chaos tests/integration/scripts/test_run_catalog_scenario.py tests/integration/scripts/test_chaos_raw_path_guard.py tests/integration/infra/test_scenario_lab.py` passed 368 tests, including enforce-approval reuse, applied-then-timeout, and mid-flight closure with a non-excluding lock; Ruff and strict mypy passed. | Route catalog submissions through the Core pipeline, port the raw drivers, supply a deployment provider, then collect shadow-only evidence before any promotion. |
| 2026-09-28 | implemented | Ported the reference sweep onto the governed adapter and removed the retired raw driver. `run-catalog-scenario.py --run` now accepts a reference scenario id, `--run-sweep` selects the reference sweep in demo order, and `scripts/deployment/scenario-lab/run-reference-sweep.sh` calls only that command. `fdai.core.chaos.reference_sweep` maps each reference scenario to the `mild` catalog entry with the same `expected_signal`, so the reviewed entry's parameters, caps, and rollback note govern the run. Governed runs that produced a measured experiment now also write the importable `enforce-report.json`, so the durable report feed can resume from a governed run. Selection grants no authority; an unpromoted or unbound sweep still refuses with exit status 3 before substrate access. | `current change` in `services/core-control-plane/src/fdai/core/chaos/reference_sweep.py`, `services/core-control-plane/src/fdai/delivery/chaos/enforce_report.py`, `services/core-control-plane/src/fdai/delivery/chaos/governed_outcome.py`, `scripts/catalog/run-catalog-scenario.py`, `scripts/deployment/scenario-lab/run-reference-sweep.sh`, and the linked tests; `uv run pytest -q --no-cov services/core-control-plane/tests/delivery/chaos services/core-control-plane/tests/core/chaos services/core-control-plane/tests/delivery/test_enforce_report.py services/core-control-plane/tests/core/report_feed/test_feed.py tests/integration/scripts/test_run_catalog_scenario.py tests/integration/scripts/test_chaos_raw_path_guard.py tests/integration/scripts/test_fork_runtime_independence.py tests/integration/infra/test_scenario_lab.py` passed 428 tests, including reference selection, sweep ordering, unpromoted-sweep refusal, and measured-report presence and absence; an unbound checkout refused with `governed_execution_unbound`; Ruff, Ruff format, strict mypy, and shell syntax passed. No scenario, ActionType, or Workflow was promoted, and no Azure or substrate operation was performed. | Route catalog submissions through the Core pipeline, port the detection-latency measurement, give `db`, `llm_endpoint`, and `lb` targets a canonical identity, supply a deployment provider, then collect shadow-only evidence before any promotion. |
| 2026-09-28 | implemented | Gave the remaining reference scenarios an approved target. The injector reference now decides the approved identity before the `target_type` default, because an entry's target type names what a fault is about rather than what the injection writes to: `kubectl:scale` and `kubectl:set-image` act on the Deployment, and `mysql:query-load` and `aoai:rate-limit` act on the service account. A shared target type no longer borrows another injector's identity, so the `db` Cosmos failover stays refused while MySQL load resolves. New `substrate_bindings.py` binds the optional MySQL and model substrate only when its complete environment is present, and the database password is read from its file inside the connection factory, never into the context. | `current change` in `services/core-control-plane/src/fdai/delivery/chaos/mutation_scope.py`, `services/core-control-plane/src/fdai/delivery/chaos/substrate_bindings.py`, `scripts/catalog/run-catalog-scenario.py`, `infra/scenario-lab/outputs.tf`, `scripts/deployment/scenario-lab/prepare-runner.sh`, and the linked tests; focused chaos, mutation-scope, substrate-binding, catalog-runner, and scenario-lab suites passed, including a regression proving all ten reference scenarios resolve to a scope-matched target and that an absent substrate value is still refused. | Decide the in-fault observation question before the detection-latency port, route catalog submissions through the Core pipeline, supply a deployment provider, then collect shadow-only evidence before any promotion. |

### Remaining work

- [ ] Supply a deployment-owned `GovernedChaosBindings` provider, including a distributed target
  lock, for the protected catalog runner and prove startup refuses enforcement when the binding or
  required authority is absent.
- [ ] Route catalog CLI submissions through the Core proposal, risk gate, Var approval, Thor, and
  `tool.run-chaos-experiment` pipeline with `GovernedChaosExecutionAdapter` bound in
  `runtime/delivery.py`, instead of calling the adapter directly, as required by
  [#94](https://github.com/dotnetpower/fdai/issues/94).
- [ ] Decide whether the governed harness may observe the expected signal *during* the fault hold,
  then port the detection-latency driver (`scripts/catalog/measure-detection-latency.py`) onto
  `GovernedChaosExecutionAdapter`. It refuses every live run until then. The blocker is structural,
  not a missing field: `FaultInjectionHarness` injects, holds for the authored duration while the
  impact guard polls only stop conditions, and probes the expected signal once afterwards, so the
  only interval it can report is the hold itself. Measuring latency honestly requires in-fault
  polling, which adds probe traffic to the fault window, interacts with the guard loop, and changes
  what `detected` means, so it needs an owner design rather than a new timestamp field
  ([#94](https://github.com/dotnetpower/fdai/issues/94)).
- [ ] Collect shadow-only governed chaos evidence on one registered disposable target at a time,
  without promoting `tool.run-chaos-experiment`, a scenario, an ActionType, or a Workflow, as
  directed in [#94](https://github.com/dotnetpower/fdai/issues/94).
- [ ] Execute the frozen S1-S14 campaign with approved impact envelopes, continuous stop guards,
  independent recovery verification, and retained replayable receipts.
- [ ] Close the missing constitutional scenario dimensions for recovery and Chaos Engineering before
  claiming domain validation or enforce readiness.

## Design at a glance

FDAI calculates an expected impact scope from the ontology graph, compiles a recovery plan before
any mutation, and asks for one decision covering injection, stop, rollback, and verification. The
runtime then compares observed impact with the approved envelope continuously. Exceeding any bound
stops the experiment and starts the already authorized recovery path.

![Design at a glance. The main stages are Grounded causal hypothesis, DecisionCase, Fresh ontology graph, ImpactEnvelope, RecoveryPlan, Dry run and approval, Thor executes, Continuous impact guard, Verify expected effect, Vidar recovery control, Thor compensation actions, ObservedOutcome and audit.](../../diagrams/generated/fdai-roadmap-decisioning-recovery-and-chaos-enforcement-01.en.svg)

## Ontology contract

The design reuses `DecisionCase`, `ActionOption`, `ExpectedEffect`, `Experiment`, `Process`,
`ActionRun`, `ObservedOutcome`, `RecoveryObjective`, `ServiceObjective`, `Resource`, and
`Workload`. It adds two immutable objects.

### `ImpactEnvelope` ObjectType

`ImpactEnvelope` is the approved upper bound for one action or experiment. Forseti owns the
accepted envelope because it is decision evidence; Loki can propose inputs but cannot approve its
own predicted impact.

| Property | Type | Meaning |
|----------|------|---------|
| `id` | string | Stable id from decision, graph revision, target set digest, and envelope version. |
| `decision_case_id` | string | Immutable decision context that accepted the envelope. |
| `graph_revision` | string | Inventory and operating-model revision used for impact traversal. |
| `target_set_digest` | string | Digest of the allowed direct targets. |
| `affected_set_digest` | string | Digest of the maximum direct and indirect affected set. |
| `max_affected_resources` | integer | Hard resource-count ceiling. |
| `max_dependency_depth` | integer | Maximum ontology traversal depth. |
| `max_duration_seconds` | integer | Hard time in the mutated state. |
| `objective_bounds` | json | Typed SLI degradation bounds and evaluation windows. |
| `required_signals` | json | Signals that should appear if the mechanism is correct. |
| `forbidden_signals` | json | Signals that immediately stop the run. |
| `telemetry_requirements` | json | Required providers, freshness, and sample cadence. |
| `uncertainty` | number | Residual uncertainty in `[0, 1]`; unknown values use `1`. |
| `expires_at` | datetime | Time after which topology and readiness should be evaluated again. |

The digests do not replace the bounded resource list retained in the decision evidence store. They
provide stable audit and replay handles without placing a large topology snapshot on the event bus.

### `RecoveryPlan` ObjectType

`RecoveryPlan` is a compiled, version-pinned sequence that returns the target to an acceptable
state. Vidar owns the plan and its readiness status. Every mutation still executes through Thor.

| Property | Type | Meaning |
|----------|------|---------|
| `id` | string | Stable id from decision, target, workflow version, and catalog digest. |
| `strategy` | string | `rollback`, `compensate`, `state_forward`, `failover`, or `restore`. |
| `status` | string | `draft`, `ready`, `stale`, `executing`, `verifying`, `recovered`, `escalated`, or `failed`. |
| `workflow_ref` | string | Versioned workflow used for recovery. |
| `action_type_refs` | json | Ordered recovery ActionTypes and pinned versions. |
| `compensation_order` | json | Reverse dependency order for already applied steps. |
| `impact_envelope_id` | string | Envelope that bounds both injection and recovery. |
| `recovery_objective_ref` | string | RTO/RPO objective the plan should satisfy. |
| `verification_probes` | json | Independent health, SLI, and state checks. |
| `last_rehearsed_at` | datetime | Latest successful rehearsal using the same mechanism version. |
| `expires_at` | datetime | Readiness expiration based on topology and provider drift. |

A plan marked `ready` has resolved every ActionType, validated arguments, completed dry-run, fresh
verification probes, and a tested stop condition. A free-form runbook cannot become a ready plan.

### Recovery and impact LinkTypes

| LinkType | Endpoints | Meaning |
|----------|-----------|---------|
| `envelope_bounds_experiment` | ImpactEnvelope -> Experiment | Approved impact boundary for a chaos run. |
| `envelope_bounds_action_option` | ImpactEnvelope -> ActionOption | Approved boundary for an ordinary recovery option. |
| `envelope_protects_objective` | ImpactEnvelope -> ServiceObjective | Objective whose degradation is bounded. |
| `recovery_addresses_hypothesis` | RecoveryPlan -> CausalHypothesis | Grounded cause the plan is intended to reverse. |
| `recovery_targets_resource` | RecoveryPlan -> Resource | Direct recovery target. |
| `recovery_realized_as_process` | RecoveryPlan -> Process | Durable execution journal for the plan. |
| `outcome_evaluates_envelope` | ObservedOutcome -> ImpactEnvelope | Independent comparison of observed and approved impact. |

Each physical declaration has one concrete source and target ObjectType. Conceptual unions compile
to explicit LinkType names rather than an untyped relationship.

## Impact analysis

Impact analysis runs before dry-run and again immediately before execution. It starts from the
ActionType's declared blast-radius traversal and adds operating context.

### Affected-set traversal

The traversal computes four sets:

1. **Direct targets:** Resources the executor can mutate.
2. **Runtime dependents:** Reverse `depends_on`, `runs_on`, and `implemented_by` paths that may
   observe the mutation.
3. **Protected services:** Business services and objectives reachable from those workloads.
4. **Control dependencies:** Telemetry, identity, audit, lock, and recovery resources required to
   keep the run safe.

The traversal is bounded by link allowlist, depth, node count, edge count, byte size, and deadline.
A stale, conflicted, or truncated graph makes the envelope incomplete and blocks chaos enforcement.

### Impact feature vector

The safety check records these inputs rather than collapsing them into one unexplained score:

| Feature | Source | Safety use |
|---------|--------|------------|
| Environment and service criticality | Operating ontology | Raises approval and quorum requirements. |
| Direct and indirect resource count | Graph traversal | Enforces the hard affected-set cap. |
| Dependency fan-out and critical path position | Typed links | Detects cascade potential. |
| Error-budget and objective headroom | ServiceObjective observations | Limits allowed degradation and duration. |
| Data-plane and stateful-resource exposure | ActionType and Resource interfaces | Requires stronger recovery and approval. |
| Recovery readiness and rehearsal age | RecoveryPlan | Blocks execution when recovery is stale. |
| Telemetry completeness and lag | Evidence providers | Blocks execution when guard observations cannot arrive in time. |
| Concurrent changes, incidents, and experiments | Operating context | Prevents ambiguous or compounding interventions. |
| Graph freshness and traversal truncation | Inventory projection | Lowers authority or blocks execution. |
| Prediction uncertainty | Impact model receipt | Lowers authority as uncertainty grows. |

The existing risk table remains authoritative. These features feed never-raising ceiling axes and
preconditions; they do not create a second decision engine.

## Recovery plan compilation

Vidar compiles a plan from one selected ActionOption and its grounded hypothesis. Compilation pins:

- the exact ActionType and workflow versions;
- pre-action state or snapshot reference needed by the rollback contract;
- forward and compensation dependencies;
- per-step idempotency keys and resource locks;
- stop conditions and maximum execution time;
- verification probes, expected ranges, and observation windows;
- escalation target when the primary recovery cannot meet RTO/RPO.

Compensation order follows reverse topological order over applied steps, not merely reverse YAML
order. A cycle, unresolved dependency, missing inverse action, or untested stateful restore keeps
the plan out of `ready`.

### Pre-authorized recovery

An approved experiment decision covers the bounded injection plus its stop, rollback,
compensation, and verification sequence. This lets Vidar start recovery immediately when a stop
condition fires without waiting for another human response while the fault is active.

Pre-authorization is valid only inside the same target set, ActionType versions, time box, and
impact envelope. A recovery that needs a wider scope, a destructive action, a different failover
target, or an expired plan pauses and requests a new approval.

## Chaos enforcement eligibility

Chaos can run in enforcement mode after every gate below passes. "Enforcement" means the approved
experiment injects a real fault; it does not mean autonomous experiment approval.

| Gate | Required evidence |
|------|-------------------|
| Catalog | Scenario schema valid, source provenance present, injector and probe registered. |
| Promotion | Scenario and every mutation ActionType are promoted by the authoritative registry. |
| Causal purpose | Named hypothesis, mechanism, expected signals, and refutation query. |
| Target | Explicit inventory targets, supported environment, owner, and maintenance window. |
| Graph | Fresh, complete, bounded impact traversal with no unresolved critical link. |
| Objectives | Sufficient error-budget and recovery-objective headroom. |
| Recovery | `RecoveryPlan.status=ready`, rehearsal fresh, rollback evidence available. |
| Telemetry | Baseline samples present and continuous guard latency below the stop budget. |
| Concurrency | No conflicting action, incident response, experiment, or protected change. |
| Safety | Dry-run receipt, locks, idempotency, kill switch, stop conditions, and audit ready. |
| Approval | Var records distinct-principal approval; production or stateful scope requires quorum 2. |

The upstream posture keeps every chaos experiment human-approved. A deployment can promote the
execution mechanics from shadow to enforce, but it cannot promote Loki into self-approval.

## Runtime state machine

An enforcement run follows a monotonic state machine:

```text
planned -> impact_checked -> dry_run_verified -> approved -> injecting
injecting -> observing -> verified -> recovering -> verifying -> recovered
injecting|observing -> stop_triggered -> recovering
verifying -> recovered|escalated|failed
```

Each transition is compare-and-swap, append-only, safe to retry, and keyed by the experiment and
target set. A process restart resumes from the last committed state and never repeats an injection
whose receipt already exists.

## Continuous impact guard

Heimdall evaluates the approved envelope throughout injection and recovery. It checks:

- observed affected resources remain a subset of the approved set;
- required telemetry remains fresh enough to enforce the stop budget;
- objective burn, latency, error rate, saturation, and availability stay within bounds;
- no forbidden signal, unexpected dependency failure, or security event appears;
- the injector and recovery backends remain reachable;
- elapsed time remains below the hard duration.

Any unknown value on a required guard is unsafe because FDAI can no longer prove containment. The
guard publishes a typed stop event. Vidar owns recovery control, and Thor executes the already
authorized recovery ActionTypes.

## Recovery verification

Stopping the injector is not recovery. Heimdall independently checks all declared postconditions:

1. The mutation or injected fault is absent.
2. Direct target health returned to its accepted range.
3. Protected service objectives recovered within the declared window.
4. Indirect affected resources no longer show the predicted propagated symptoms.
5. No compensation or rollback step remains partial.
6. The recurrence window closes without the same causal fingerprint.

The terminal outcome is `recovered`, `partially_recovered`, `not_recovered`, or `unscorable`.
Only `recovered` with complete telemetry can count as positive promotion evidence.

## Promotion and automatic demotion

Promotion evidence keeps mechanics, detection, containment, and recovery separate:

| Measure | Example acceptance criterion |
|---------|------------------------------|
| Detection | Expected signal observed within its declared latency budget. |
| Containment | Zero resources outside the envelope and zero forbidden objective breaches. |
| Recovery | Recovery completed within RTO with every verification probe passing. |
| Repeatability | Minimum samples and days met across the frozen scenario set. |
| Decision quality | False-positive, missed-stop, and policy-escape rates within configured limits. |

The criteria are configuration and should be set before the observation period. Any policy escape,
out-of-envelope impact, missed stop, rollback failure, stale graph, or material detector regression
automatically returns the scenario and affected ActionTypes to shadow mode.

## SRE scenario application

The design supports the S1-S14 pack without hard-coding those identifiers into core:

- **Kubernetes faults:** The envelope follows workload, service, ingress, and objective links;
  recovery verifies replicas, rollout, endpoints, and service-level signals.
- **VM stress and network delay:** The envelope includes host dependents and control-plane access;
  recovery verifies process exit, queue discipline, memory, CPU, and dependency latency.
- **Database saturation:** The plan protects data integrity, stops load, cleans test data, and
  verifies credits, throughput, latency, and connection recovery.
- **Rate limiting:** The hypothesis distinguishes demand, quota, provider, and deployment changes;
  recovery can stop load, apply backoff, switch a promoted route, or request quota action.
- **Gateway cascade:** The graph predicts downstream propagation and verifies both backend health
  and external service objectives.
- **Bad deployment:** Recovery pins the prior revision, performs forward rollback, and verifies the
  rollout plus dependent service health.
- **Drift and alert triggers:** Non-fault scenarios use the same hypothesis and recovery contracts
  but do not require an Experiment or injector.

## Governed execution path

Live catalog runs from `scripts/catalog/run-catalog-scenario.py --run`, `--run-sweep`, or
`--run-all` go only through `GovernedChaosExecutionAdapter`, the implementation of the chaos tool's
`GovernedChaosExecution` seam. The command submits the same typed `tool.run-chaos-experiment`
request that the chaos tool's enforce path delegates, but it still calls the adapter directly.
Routing it through the Core proposal, risk gate, Var approval, and Thor pipeline remains open. The
raw reference-sweep driver was removed, and the detection-latency driver refuses every live run
until its measurement is ported onto the adapter.

- **Selection:** `--run` accepts a catalog id or a reference scenario id, and `--run-sweep` selects
  the reference sweep in demo order. `fdai.core.chaos.reference_sweep` maps each reference scenario
  to the `mild` catalog entry that raises the same `expected_signal`, and the catalog entry's
  parameters, blast-radius cap, and rollback note govern the run. Selection grants no authority: an
  unpromoted, unbound, or target-unresolvable selection refuses like any other enforce request.

- **Bindings:** A deployment supplies `GovernedChaosBindings` through exactly one
  `fdai.governed_chaos` entry point named `catalog-scenario`. The bindings name the durable state
  store, the ActionType mode source, the scenario promotion ledger, the Var approval verifier, the
  run planner for Vidar's recovery plan and Heimdall's guard, the Thor recovery dispatcher, the
  independent recovery evidence collector, and a distributed logical-target lock. Upstream ships
  no provider, so an unbound checkout refuses enforcement with exit status 3 and a structured
  refusal report before substrate access.
- **Targets:** Each run targets the canonical identity of the resource its `target_type` mutates:
  the VM for `vm` and the workload pods for `pod`, `disk`, and `dns`. Other target types are
  refused. Every factory-built injector declares the resources it mutates, and each target must be
  exactly the one resource its injection mutates, so a run with an unapproved mutation or a surplus
  target is denied and no resource is injected twice.
- **Authority:** The adapter derives promotion, approval, the ActionType tier ceiling, locks,
  idempotency, and audit readiness from their authoritative sources, and the deterministic
  eligibility check decides. Catalog runs are T0 requests, the `shadow_only` ceilings for T1 and T2
  deny enforcement, and a request without a recognized tier is denied. A request-supplied approval
  reference is only a claim that the verifier must confirm.
- **Concurrency and restart:** The run id binds the request idempotency key, scenario, and target
  set. Only the writer whose compare-and-swap applies `injecting` may inject. A durable per-target
  claim denies a new run until the holder verifiably left nothing live: it recovered, it was denied,
  or it failed without attempting an injection. An injection call that raises, such as a client
  timeout after the provider accepted the change, counts as injected: the harness rolls it back and
  the run passes through recovery, so the target is released only after independent verification.
  An escalated run, a run that failed after an attempted injection, and a run orphaned by a stopped
  process keep their targets. A terminal run replays its recorded outcome,
  an interrupted run resumes recovery without injecting again, and a catalog sweep halts after any
  run whose rollback is not verified.
- **Closure:** After manual recovery, `run-catalog-scenario.py --close <scenario> --confirm-closure
  --closure-reason <text>` releases a held target only through a separate closure decision. The
  approval comes from `FDAI_CHAOS_CLOSURE_APPROVAL_REF`, and the verifier's `verify_closure` must
  confirm a distinct Var approver with the `closure` intent for that exact run and its targets.
  Each run binds the digest of the enforce approval that admitted it, and that approval can never
  close it. Closure is addressed by target, so it also works for an orphan whose request can no
  longer be rebuilt. Closing a run before `injecting` denies it through a compare-and-swap, and the
  exclusive `injecting` transition re-checks closure, so a closed run can never inject. The closure
  record is create-only and audited, and a refused closure is audited.
- **Outcome:** Only verified recovery reports success, and detection is a separate verdict. A run
  passes only when it recovered and validated its expected signal, so an undetected fault makes the
  command exit non-zero. A run that produced a measured experiment also lands in the run's
  `enforce-report.json`, the importable contract the durable report feed reads; a refused,
  replayed, or errored run contributes no record, so the report never carries an unmeasured result.

Example: `--run <scenario> --confirm-enforce` without a current Var approval -> typed
`tool.run-chaos-experiment` request -> eligibility denial with `var_approval_required` -> audited
`denied` run transition -> no injection.

## Delivery status

The implementation is split into independently testable slices:

1. Add `ImpactEnvelope`, `RecoveryPlan`, and the seven typed LinkTypes.
2. Implement bounded affected-set traversal and persist its decision evidence.
3. Compile recovery workflows with reverse-topological compensation and readiness expiry.
4. Add the continuous impact guard and typed stop event.
5. Bind pre-authorized Vidar recovery control to Thor's registered recovery actions.
6. Add independent recovery verification and promotion/demotion evidence.
7. Run the S1-S14 disposable-substrate campaign in shadow, approved enforce, and forced-stop modes.

Slices 1-6 are implemented in core and covered by focused regression tests. Slice 7 is deployment
evidence: it requires promoted scenario and ActionType versions plus injected Thor, Vidar, Heimdall,
telemetry, inventory, and audit bindings. Enabling an environment flag does not substitute for
those bindings. The [governed execution path](#governed-execution-path) is the only seam that binds
them, and upstream ships no provider.

## Related docs

| To learn about | Read |
|----------------|------|
| Causal hypotheses and evidence grades | [Causal Incident Graph](../rules-and-detection/causal-incident-graph.md) |
| Shared service, objective, and outcome meaning | [FDAI Operating Ontology](../architecture/operating-ontology.md) |
| Action safety declarations | [Action Ontology](action-ontology.md) |
| Workflow journal and compensation | [Process Automation](process-automation.md) |
| Baseline safety classification | [Risk Classification](risk-classification.md) |
