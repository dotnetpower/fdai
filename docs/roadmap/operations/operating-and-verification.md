---
title: Operating and Verification
---
# Operating and Verification

How to know FDAI is **alive, correct, and behaving** - from a freshly provisioned
deployment onward. This document is **self-observability**: how the system reports on
itself. It is distinct from
[observability-and-detection.md](../rules-and-detection/observability-and-detection.md), which is what the system
**detects about the environment it watches**. Presentation / dashboard layout is out of scope
for this document.

Complements [deploy-and-onboard.md](../deployment/deploy-and-onboard.md) (provisioning) and
[startup-and-lifecycle.md](startup-and-lifecycle.md) (bootstrap). Azure focus: non-Azure
providers are TBD (see
[Always-On Rules](../../../.github/copilot-instructions.md#fdai-core-principles-must)).

## Self-Health Signals

Signals a healthy deployment MUST emit continuously. Every signal maps 1:1 to an alert rule
(see the [alert-routing contract](#alert-routing)).

| Signal | Purpose | Failure mode caught |
|--------|---------|---------------------|
| **Liveness probe** (per container) | container process alive | crash loop |
| **Readiness probe** (per container) | dependencies reachable | boot without Kafka broker / Key Vault reference / DB |
| **Adapter healthcheck** (per provider adapter) | Kafka broker reachable (Event Hubs `:9093`), Key Vault reference resolvable, Diagnostic-Settings forwarders healthy, catalog loaded in OPA, T2 model endpoints reachable | silent dependency drop |
| **Event lag** (ingest to first tier decision) | per-tier latency | ingress backpressure |
| **DLQ depth** (per queue / topic) | dead-letter accumulation | poison message, consumer failure |
| **Cold-start rate + duration** | scale-to-zero warm-up cost | deadline misses (routes to HIL) |
| **Verifier failure rate** | T2 verifier abstain / fail rate | drift in verifier accuracy |
| **Mixed-model disagreement rate** | cross-check disagreement | model degradation |
| **Rollback rate** | actions later reverted | miscalibrated rules or actions |
| **Override rate** | override create / modify per rule | poor-fit rules (feeds the discovery loop) |
| **Discovery loop pass rate** | candidate → quality gate pass % | loop drift |
| **Kill-switch state** | on / off | contained emergency posture |
| **Canary result** | synthetic loop round-trip | silent ingress death |
| **Time since last successful canary** | staleness | monitor of the monitor |

### Local source bindings

The production composition reads liveness from the opened health listener, readiness from the
same guarded state used by `/ready`, and kill-switch state from its authoritative StateStore key.
The configuration field identifies the validated runtime-policy values consumed at bootstrap,
not a claim that pending restart-required settings have taken effect. The version field identifies
the installed Core distribution, not a deployment or source-revision attestation.
These process-local observations do not establish health for other replicas or services.

Cold-start duration measures this Core process from runtime entry to its first observed guarded
ready state after bootstrap composition. It uses monotonic elapsed time and retains the original
UTC observation time and an opaque process-instance source id. Before that observation, after shutdown, or without the lifecycle binding,
the signal is unavailable. Recollection never renews the observation's freshness. This single
process sample supplies neither a fleet cold-start rate nor a complete installation-wide window.

#### Consumed-canary age

The age source reads the latest committed successful `control_loop.canary` audit from the
configured Core store in append-sequence order, with one row and an 8 KiB entry-transfer ceiling.
A dedicated partial index keeps that read bounded;
the oldest-first migration reader is not a substitute. It validates the canonical actor, event,
correlation, outcome, timestamps, latency and selected-row hash before measuring elapsed seconds.
Missing, malformed, future or unreachable evidence stays unavailable, with no older-row fallback.

Age uses the original UTC `recorded_at`, captured before audit append, so it can conservatively
overstate time since completion. Exact Decimal construction, independent of caller precision,
preserves the 600-second policy boundary.
The observation time is the current age measurement, not a renewed canary success. Repeated reads
therefore increase age and eventually alert instead of refreshing old evidence into Healthy.
This source does not establish the latest attempt result, round-trip latency, complete audit history
or execution authority. `canary_result` and the canary operational-state field remain unavailable.

| Initial option | Critique | Source boundary |
|---|---|---|
| Use publisher or startup broker success | Neither proves consumption through the canary path | Read the independently persisted consumed-canary audit |
| Read an oldest-first audit prefix | A prefix cannot identify the latest successful canary | Use an indexed latest-success query |
| Reuse an old success as a fresh boolean | It can hide a stalled canary indefinitely | Measure increasing age from the original timestamp; keep latest-attempt status separate |

The catalog's unqualified `adapter_healthcheck` remains the configured-adapter aggregate.
A source id cannot narrow that aggregate to `t1.embedding`; without complete authoritative
adapter coverage the catalog signal remains unavailable. The earlier single-adapter binding
was withdrawn after a two-configured-adapter counterexample produced a false global Healthy.
Actual model observations are now exposed separately in typed `model_provider_scope` and
`model_provider_registration` siblings of the existing response's unchanged `snapshot`.
The startup registration preserves every configured model role, including unobserved roles.
The existing Operator reader verifies the independent registration, exact role/binding set,
parent snapshot digest, time, coverage, and freshness before returning this optional sub-scope.
Missing registration or any missing/unknown role keeps scoped health unknown; no model sub-scope
can substantiate global adapter Healthy. This is not replica or installation-wide coverage.
The producer observes every logical embedding invocation. Overlapping invocations form one
cohort, closed only when all its invocations settle. All members must pass the existing HTTP and
finite-vector checks for success; a fully known cohort with any HTTP/response failure is unhealthy.
Cancellation, pre-provider failure, or local post-call failure makes the cohort unavailable even
if another concurrent call succeeds. It emits no rate or inferred denominator, and adds no probe or retry.
Only the latest completed cohort observation is retained. Any in-flight invocation, missing observation,
closed client, or expired catalog freshness bound keeps the source unavailable. A newly bound
adapter starts unobserved and cannot reuse the old instance's results. API-contract success is
not semantic quality or readiness. The original `OperationalStateSnapshotV1` schema and digest
are unchanged; the optional scoped evidence uses a separate typed contract and digest.

Source collection runs at half the shortest catalog freshness bound, independently of expensive
startup probe refreshes. It never invokes models, changes a kill switch, or executes an action.
Missing, malformed, or unreachable source records remain unavailable with bounded reason codes;
an existing stale or future-dated observation retains its original freshness decision.
Source failure codes include `source_missing`, `source_malformed`, `source_unreachable`, `source_incomplete`, `source_stale`, and `source_from_future`.
Provider error text never becomes a projection reason.

Other bindings remain explicitly unavailable until their owning source can supply the required
observation. Broker queue depth and ingest-to-decision lag need broker/consumer observations;
cold-start rate needs a complete lifecycle window and denominator; verifier, disagreement, rollback,
override, and discovery rates need time-bounded numerators and denominators. Complete adapter
health needs the registered dependency checks, and canary result/state still needs a complete
latest-attempt source. The new age reader does not provide that result. The existing oldest-first
audit migration reader cannot establish the latest canary.
Rule-effect, override, discovery, canary, and break-glass fields still need their owning projections.

### Remaining source boundaries

Five of 15 signals and three of eight fields have qualified runtime source bindings. The
indexed latest-success age reader does not establish the latest scheduled attempt or complete
canary state. Ten signals and five fields remain unavailable; missing observations or
denominators are never zero failures or a successful result. Publication counters do not prove
broker depth, startup duration does not prove fleet cold-start rate, and promotion records do
not prove executed rollback or per-rule override rates.

## Implementation status

Runtime health, startup readiness, transition telemetry, and the synthetic canary path are
implemented and covered by focused tests. The deployment workflow now requires the exact consumed
canary audit row and a 30-second numeric latency budget after publisher completion. A retained live
receipt, complete alerting, fixture replay, drills, and stabilization automation remain incomplete,
so no area is claimed as fully operationally validated.

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| Stabilization scheduler numeric input integrity | implemented | #2254; shared schedule model, compatibility tools and actual creation-command tests; 110 focused checks, model/tool branch-inclusive coverage 92.62%/97.63% | Invalid non-finite intervals cannot be stored or replace a valid task; valid cadence and normal due dispatch remain unchanged. This hardens a prerequisite, not daily-job registration or stabilization qualification. |
| Runtime `/live` and `/ready` endpoints plus startup-readiness evaluation, persistence, transitions, and guarded refresh | implemented | [`runtime/health.py`](../../../services/core-control-plane/src/fdai/runtime/health.py), [`runtime/readiness.py`](../../../services/core-control-plane/src/fdai/runtime/readiness.py), [`test_readiness.py`](../../../services/core-control-plane/tests/runtime/test_readiness.py), and [`test_startup_coordinator.py`](../../../services/core-control-plane/tests/core/readiness/test_startup_coordinator.py) | Process-critical failure closes readiness; degraded capabilities lower authority without raising it on recovery. |
| Bounded transition spans and metrics with secure OTLP configuration | implemented | [`transitions.py`](../../../services/core-control-plane/src/fdai/shared/telemetry/transitions.py) and [`test_transition_telemetry.py`](../../../services/core-control-plane/tests/shared/test_transition_telemetry.py) | Stable allowlisted attributes prevent payloads and provider errors from becoming telemetry labels. |
| Synthetic canary publisher, canonical consumer, no-op audit path, and scheduled Container Apps Job | implemented | [`canary_cli.py`](../../../services/core-control-plane/src/fdai/delivery/canary_cli.py), [`_canary.py`](../../../services/core-control-plane/src/fdai/core/control_loop/_canary.py), [`canary_job.tf`](../../../infra/modules/compute/container-apps/canary_job.tf), and focused canary tests | The canary is isolated from T0/T1/T2, risk, execution, incident, and learning paths. |
| Post-deploy promotion smoke | in-progress | [`deploy-dev.yml`](../../../.github/workflows/deploy-dev.yml); `scripts/deployment/azure/verify_canary_audit.py`; focused verifier tests | The workflow gives the publisher a deterministic slot, then requires one exact Core audit row within 30 seconds. The verifier rejects ambiguous, malformed, unsettled, future-dated, or over-budget rows without exposing database credentials. A retained live receipt, fixture replay, kill-switch cycle, and human-approval dry-run remain open. |
| Complete self-health signal policy and routing map | implemented | `config/self-health-signals.yaml`; `core/readiness/self_health.py`; production startup binding; focused self-health and readiness tests | All 15 required signals map to one metric, threshold direction, freshness bound, generic owner lane, notification route, and fail-closed fallback. Missing coverage or route drift blocks startup. Decisions grant no execution authority. |
| Consumed-canary age source | implemented | #2250; `delivery/self_health_canary.py`; `delivery/persistence/postgres_canary.py`; concurrent partial-index Core migration; 99 focused checks including four actual isolated PostgreSQL cases | Latest successful consumed audit, selected-row hash/time/identity checks, exact 600-second and 8192/8193-byte boundaries, indexed plan beyond a 512-row oldest prefix, default readiness composition and non-destructive index rollback are locally tested. Caller Decimal precision cannot round away a threshold breach. This is conservative age, not latest-attempt result or operational qualification. |
| Complete self-health exporter registry, alert delivery, and operational drills | in-progress | Complete signal policy; exact 15-signal and eight-field exporter registry; runtime sources; typed model-role registration/scope; durable operational-state snapshot; authenticated Operator read route | Five catalog signal slots and three fields are source-bound; ten slots and five fields remain unavailable. Consumed-canary age is separate from canary result/state. Actual embedding observations remain a typed sub-scope, never proof of aggregate adapter health. Other sources and complete delivery/drill receipts remain open. |
| Correlation-based audit investigation and unified version/configuration exposure | implemented | [`rule_fire_trace.py`](../../../services/core-control-plane/src/fdai/core/audit/rule_fire_trace.py), [`audit_rca.py`](../../../services/core-control-plane/src/fdai/core/reporting/datasources/audit_rca.py), `core/readiness/self_health_runtime.py`, and authenticated `GET /operations/runtime-state` | One sanitized contract now exposes version, configuration, rule effect, override, discovery, canary, kill-switch, break-glass, and all self-health states. Each field includes source, freshness, and an explicit unavailable state; the route grants no approval or execution authority. |
| Pre-launch latency measurement and frozen-scenario replay | implemented | [`latency_budget.py`](../../../services/core-control-plane/src/fdai/core/measurement/latency_budget.py), [`baseline_run.py`](../../../tools/baseline_run.py), and focused tests | The primitives produce bounded measurements and release-gate results; an external load generator and deployment-specific budgets remain operator inputs. |
| Live Azure read-investigation scenarios | in-progress | [Azure Read Investigations](../interfaces/azure-read-investigations.md#verification-and-release-evidence) | Four bounded read-only scenarios passed, while guest-event matching, an actual provider `429`, and cross-service parity receipts remain open release evidence. |
| ActionType operator-runbook schema and coverage | implemented | [`check-action-runbooks.py`](../../../scripts/quality/documentation/check-action-runbooks.py), [`incident-mitigation-and-rollback.md`](../../runbooks/incident-mitigation-and-rollback.md), and [`test_check_action_runbooks.py`](../../../tests/integration/scripts/test_check_action_runbooks.py) | Every shipped ActionType matches exactly one generic upstream runbook whose declared precondition, procedure, verification, rollback, and audit sections exist. Deployment-specific commands remain fork-owned. |
| Post-launch stabilization composition | in-progress | [`core/scheduler/`](../../../services/core-control-plane/src/fdai/core/scheduler) and measurement primitives | The daily health, drift, and deployment-baseline jobs and `console.recurrent_query` signal aren't registered upstream. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-10-19 | withdrawn | Withdrew this topic's earlier six-signal/four-field claim and its receipt-only canary result/state exporters when integrating protected #2253. A fresh last-success receipt cannot establish the latest scheduled attempt or complete canary state. Reused the stronger indexed age producer instead of maintaining a competing implementation. | Earlier local `adcbf54cc6`/`c7a7a8bdfa` receipt tests established receipt validity only; protected main `3917df4297` supplies the indexed, byte-bound, hash-checked age source. No independently owned latest-attempt window exists. | Current source coverage is five of 15 signals and three of eight fields. Latest-attempt result/state, ten signal producers and five fields remain open; fixture passes are not operational qualification. |
| 2026-10-19 | implemented | Aligned the ephemeral CI database's host port and service DSNs with canonical isolated validation port 5433 instead of relaxing the new source-regression guards. Added static CI-contract coverage for both accepted 5433 and rejected runtime-port 5432 configurations. Container-internal PostgreSQL still uses 5432. | Current change; CI `39196349170` attempt 1, exact head `50bd2a1bffe10edcb29c0700445470ee8299f42d`, completed integration job `117879915744` step 9 reported fourteen fixture-port errors; no database outage or flaky-test claim. `check-ci-contracts.py` and the 159-case CI/artifact/fast-scope selection pass locally; the actual source-backend tests retain their loopback-5433 checks. | Repaired-head CI remains authoritative. This changes test infrastructure only, not runtime databases, deployed health, H01 coverage or operational qualification. |
| 2026-10-19 | implemented | Connected canonical consumed canary audit evidence to result, last-success age, and the canary field, with one bounded read-only latest-row query, complete-history fallback, exact receipt validation, preserved result freshness, and explicit source failure. Coverage is now six of 15 signal bindings and four of eight field bindings, not H01 completion. | `current change`; `delivery/self_health_canary.py`; `delivery/self_health_sources.py`; `tests/delivery/test_self_health_canary.py`; focused pytest with source/runtime/monitor regressions: 65 passed and 100% branch-inclusive canary-source coverage; Ruff and strict mypy passed. | Nine catalog producers and four complete field projections remain missing as listed in Remaining source boundaries. Scheduled-attempt completeness, primary/fallback delivery, and recovery-drill receipts remain open; no live or database integration validation was run. |
| 2026-10-19 | implemented | Added actual PostgreSQL regression evidence for the latest-canary reader without changing runtime bindings. Latest sequence, invalid latest evidence, empty history, and least-data bounded reads pass in isolated test schemas; the driver confirms read-only mode and the configured statement timeout. | `current change`; `tests/persistence/test_self_health_canary_postgres.py`; the single-file pytest selector through `scripts/automation/with-local-test-database.py`: four passed on loopback validation port `5433`; Ruff lint and format passed. | Signal coverage remains six of 15 and field coverage four of eight. The prior row's no-database-integration limitation is superseded only for this local query regression, not for deployment, notification delivery, or operational drills. |
| 2026-10-19 | implemented | Hardened shared scheduled-task interval validation before attaching daily stabilization jobs. Invalid NaN/Infinity and oversized conversion no longer enter schedule state or escape as unhandled compatibility-tool failures. | `current change`; #2254; 14 regressions failed before repair; 110 focused cases, actual creation command/reviewed-blueprint materialization, exact 60-second boundary, no-mutation updates, healthy due-cycle and RBAC/isolation controls passed; model/tool coverage 92.62%/97.63%. | Daily health/drift/deployment-baseline registration, recurrent-query signal, operating policy and operational receipts remain open; no authority or mode is raised. |
| 2026-10-19 | implemented | Bound the existing canary-age metric to the latest committed successful Core audit through a byte-bounded indexed PostgreSQL reader, without publisher/startup or oldest-prefix substitution. Reproduced and removed caller-precision rounding that hid a one-microsecond threshold breach. | `current change`; #2250; 99 focused checks including four actual isolated PostgreSQL cases; source and query branch-inclusive coverage 100%; natural partial-index plan, exact Decimal and byte boundaries, real Core producer and default readiness composition, concurrent index SQL and official Core migration validation. | Five signal slots/three fields are source-bound; ten/five remain unavailable. Apply the service-owned index before operational qualification. Latest-attempt result/state, complete audit history, delivery/drill and live receipts remain open. |
| 2026-10-19 | withdrawn | Withdrew `e58fbf5674`'s single embedding observation mapping to global `adapter_healthcheck` and its five-slot coverage claim. A configured embedding success plus an unobserved reasoner reproduced false aggregate Healthy. | Current correction; failing-then-passing collector regression; actual SDK producer, complete startup role registration, and strict Operator scope-consumer checks. | Global source coverage is four slots/three fields with 11/five unavailable. Model sub-observations are separately typed; complete adapter and replica coverage remain unimplemented. |
| 2026-10-19 | implemented | Connected a producer of actual normal embedding SDK outcomes to the registered-role and binding-qualified per-adapter slot. Overlapping calls must all settle; cancellation and incomplete outcomes cannot be overwritten by another success. | `current change`; embedding producer; `provider_observations.py`; focused actual MockTransport-call-to-existing-snapshot/reader-contract tests. | Five signal slots and three fields are source-bound; the adapter is `t1.embedding` only, while other roles and replicas remain unknown. Ten signals and five fields are unavailable. No rate, semantic quality, overall readiness, or deployment evidence is claimed. |
| 2026-10-19 | implemented | Bound actual runtime entry to first post-composition guarded-ready duration with monotonic elapsed time, frozen observation time, opaque process-instance identity, unavailable initial/shutdown states, and no additional probes. | `current change`; `runtime/startup_observation.py`; bootstrap/resources/readiness/source composition; focused startup, collection, shutdown, and bootstrap tests. | Four signals and three fields are source-bound; 11 signals and five fields remain unavailable. Model-health cooldowns and rolling latency samples lack outcome-rate denominators and cannot establish full adapter health. Fleet cold-start rate and deployed alert/drill evidence remain open. |
| 2026-10-17 | implemented | Added an exact exporter registry for all 15 self-health signals and eight unified operational-state fields. Runtime persists one source-qualified, freshness-checked snapshot, and the Operator exposes it only through the existing authenticated Reader-role projection boundary. Production uses explicit unavailable bindings until each accountable source adapter is composed, so missing telemetry never appears healthy. | `current change`; service contracts, Core monitor, production bootstrap, Operator projection and route; 171 focused checks and strict mypy. | Replace every explicit unavailable binding with its source-specific production exporter, then retain primary/fallback delivery and recovery-drill receipts. |
| 2026-10-15 | implemented | Added bounded read-only post-deploy verification for the exact consumed canary audit and its numeric latency budget. Publisher completion alone can no longer satisfy this smoke stage. | `current change`; `verify_canary_audit.py`; deploy workflow binding; 10 focused tests. | Retain a passing deployed receipt and add frozen fixture replay, kill-switch engage/disengage, and no-execute HIL dry-run evidence. |
| 2026-10-15 | implemented | Added the complete 15-signal self-health policy catalog, fail-closed freshness and threshold evaluation, notification-route fallback validation, and mandatory production startup binding. | `current change`; self-health catalog, decision core, readiness/bootstrap binding, and focused tests. | Bind every metric exporter and retain primary/fallback delivery plus recovery-drill evidence. |
| 2026-08-14 | in-progress | Adopted the implementation ledger and separated tested self-observability primitives from incomplete operational evidence; earlier provenance wasn't reconstructed. | Current change; focused readiness, telemetry, canary, latency, and baseline-runner tests cited in the scope table. | Complete deployment round-trip evidence, alert and drill coverage, unified exposure, and stabilization bindings. |
| 2026-08-14 | implemented | Defined the operator-runbook front-matter schema and added CI coverage for every shipped ActionType. | Current change; `check-action-runbooks.py` and `test_check_action_runbooks.py`. | Keep deployment-owned commands and procedures aligned with the same required semantic sections. |
| 2026-10-18 | implemented | Bound actual local health-listener, guarded readiness, persisted kill-switch, installed version, and consumed policy sources. Added serialized 30-second source refresh independent of slow startup probes, sanitized source failure reasons, and cancellation cleanup without execution authority. | `current change`; `delivery/self_health_sources.py`; `runtime/health.py`; `runtime/readiness.py`; `runtime/bootstrap_core.py`; `tests/delivery/test_self_health_sources.py`; `tests/runtime/test_self_health_sources.py`; 92 focused pytest checks passed; Ruff lint/format passed; strict mypy passed for six changed source files. | Twelve signal sources and five operational-state sources still require their owning observations or projections. Primary/fallback notification delivery and live recovery-drill receipts remain open. |

### Remaining work

- [x] Require the exact consumed canary audit entry within a 30-second numeric latency budget after
  publisher completion, rejecting ambiguous, malformed, unsettled, future-dated, or over-budget rows.
- [ ] Retain a passing deployed canary receipt, replay the frozen shadow fixtures, exercise
  kill-switch on/off, and complete a no-execute human-approval dry-run with linked audit receipts.
- [x] Map every self-health signal to a concrete threshold, generic owner lane, notification route,
  and fail-closed fallback, and validate the complete catalog during production startup.
- [ ] Bind every catalog signal to its runtime exporter and retain primary/fallback delivery and
  recovery-drill receipts in one governed deployment.
- [x] Bind process-local liveness, guarded readiness, and persisted kill-switch state plus installed
  version and consumed runtime policy, and test periodic refresh without repeating startup probes.
- [x] Observe actual runtime entry to first guarded-ready duration per process without inventing a
  cold-start rate, renewing freshness, or performing another model, network, or database probe.
- [x] Expose the complete version, configuration, rule-effect, override, discovery, canary,
  kill-switch, and break-glass state through one authorized read surface and test field freshness.
- [x] Define a required runbook schema and add a check proving every automated ActionType has a
  generic upstream or deployment-owned runbook with verification and rollback instructions.
- [ ] Register the daily stabilization jobs and recurrent-query signal, then prove the window opens,
  lowers authority on guard-metric breach, and closes only after its configured exit conditions.
- [ ] Complete the live Azure guest-event, provider-throttling, and cross-service parity evidence
  tracked by the Azure read-investigation owner document.

### Startup readiness response

Use `/live` to determine whether the process can answer, and use `/ready` to determine whether it
may process events. A `503` response means a process-critical startup probe is missing, stale,
timed out, crashed, or failed. Don't restart consumers or the Pantheon manually while `/ready`
remains closed.

1. Read the sanitized latest report at the StateStore key
  `runtime:startup-readiness:latest`. Start with `decision`, `missing_probe_ids`,
  `stale_probe_ids`, and each result's `failure_class`.
2. Correlate a decision change with the `startup_readiness.transition` audit record and the
  schema-validated `readiness_transition` event. A publish failure has its own
  `startup_readiness.transition_publish_failed` audit record.
3. Repair the named dependency or capability outside the FDAI process. Avoid placing provider
  error text, endpoint values, tokens, or customer identifiers into the report or an operator
  note.
4. Wait for the configured periodic refresh. A recovered process-critical probe reopens `/ready`
  and restarts guarded workers. A recovered capability does not raise authority above its
  deployment promotion state.

For `degraded`, keep `/ready` open but inspect `authority_ceilings`. `shadow`, `human_approval`,
`deterministic_fallback`, and `disabled` are expected safety responses, not permission to bypass
the quality gate or promotion registry. See
[startup-and-lifecycle.md](startup-and-lifecycle.md#shipped-runtime-boundary) for probe budgets and
the registered-destination contract.

Signals emit via OpenTelemetry to the configured backend
([deployment.md#observability-slos-and-alerting](../deployment/deployment.md#observability-slos-and-alerting)).

`OTEL_EXPORTER_OTLP_ENDPOINT` enables OTLP/gRPC trace and metric export. HTTPS is required outside
loopback; credentials, query strings, and fragments are rejected in the endpoint. Without an
endpoint, local console spans and in-memory metrics remain the default.

Channel, extension, model, scheduler, and security lifecycle components emit the same
`fdai.transition` span and `fdai.transition.count` metric through a process-singleton emitter.
Attributes use bounded allowlisted domain, name, outcome, and component-specific scalar keys;
provider error text, payloads, credentials, and arbitrary labels are not accepted. Emission is
best-effort so exporter failure cannot block routing or safety decisions.

## Synthetic Canary Event

A mostly event-driven system has a specific silent failure mode: **no events arrive -> looks
healthy**. Mitigation: a periodic canary on a separately authorized topic.

- A **synthetic event** is emitted every five minutes from a Container Apps Job into
  `fdai.control.canary` on the same Event Hubs namespace.
- A dedicated UAMI can only pull the image and send to Event Hubs. The core's separate canary
  consumer accepts only `source=fdai.canary-job` and `event_type=fdai.control.canary`.
- The canary path records ingest, route, and audit stages plus a no-op audit entry. It never
  enters T0/T1/T2, the risk gate, execution, IRP, or the learning loop.
- The **full loop** - `ingest → correlation → tier decision → audit entry` - MUST complete
  within a bounded budget; a failure to complete raises an SLO-burn alert on the
  [operational alert-routing lane](#alert-routing).
- The canary is **versioned**, **rate-capped**, and its idempotency key is distinguishable
  from a real event's so canary samples cannot corrupt regression measurement or the
  autonomous discovery loop's observe stage.
- Each five-minute slot derives a stable UUID and `canary:<slot>` idempotency key. Container Apps
  caps publisher execution at 120 seconds and the audit row records measured latency.

> The deployment workflow now blocks when an immediate canary publisher run fails or its exact
> consumed Core audit row is absent, ambiguous, malformed, unsettled, future-dated, or over the
> 30-second latency budget. A retained live receipt and scheduled kill-switch on/off drill remain
> production-readiness evidence items.

## Post-Deploy Smoke Test Contract

The target automated suite runs against the live deployment after every promotion. A failing
smoke test should **abort the promotion and roll traffic back**
([deployment.md#release-and-rollback](../deployment/deployment.md#release-and-rollback)).

1. **Adapter reachability** - Kafka round-trip (Event Hubs `:9093` produce + consume on a
   probe topic), Key Vault reference resolution, DB write + delete on a probe table, T2 model
   endpoint low-cost ping (per model, including cross-check target).
2. **Config load** - the deployed image reports its version, catalog ref, and config hash;
   values match the expected release manifest.
3. **Canary round-trip** - fire one synthetic event, verify the audit entry lands within
   budget.
4. **Shadow decision correctness** - a fixture set of representative events is fed in shadow
   mode; verdicts match golden expectations (regression suite).
5. **Kill-switch check** - toggle kill-switch **on**, verify all actions abstain during the
   window (probing with the canary); toggle **off**, verify normal decisions resume. Both
   states leave audit entries.
6. **HIL dry-run** - a synthetic high-risk finding is routed to the HIL channel, an approver
   approves (in a dry-run harness that does not execute), the audit trail records both hops.

The current apply workflow verifies schema migrations, optional HTTP health endpoints, publisher
completion, and the exact consumed canary audit within a 30-second budget. A retained live receipt,
fixture replay, kill-switch drill, and HIL dry-run remain required before production promotion.

## Alert Routing

Two independent lanes, each with an owner and a channel. Concrete channel names / ownership
matrix is fork responsibility. Channel selection, trust tiering, and fallback rules are
defined in [channels-and-notifications.md](../interfaces/channels-and-notifications.md); this section is
the alert-side view of that model.

| Lane | Signal source | Route |
|------|---------------|-------|
| **Operational** | SLO burn, DLQ depth, verifier failure rate, cold-start deadline miss, adapter unhealthy, canary miss, IaC drift, secret near expiry | on-call rotation (paging channel) |
| **HIL** | high-risk finding, enforce-promotion request, override request, exemption-expiry warning, break-glass request | Teams HIL channel |

Rules that apply to every alert:

- Alerts MUST be **actionable**: each alert links to (a) its dashboard panel, (b) its
  runbook, (c) the correlated audit id if applicable.
- **De-duplication**: correlated alerts collapse per the correlation rules in
  [observability-and-detection.md](../rules-and-detection/observability-and-detection.md); an alert storm from one
  root cause is one page, not many.
- **Fallback channel**: if the primary channel (Teams / paging) is unreachable, HIL items
  queue in the state store and alert via a secondary channel; nothing auto-executes on the
  fallback path.

> **Open decision**: Choose the concrete channel-ownership matrix and fallback channel per fork.

## Audit Investigation Flow

Given a correlation id or audit id, the operator walks a fixed path. Each hop is a **stored
link captured at write time**, not a search - the walk is O(1) lookups.

![Audit Investigation Flow. The main stages are Audit id or correlation id, Event lookup, Tier decision plus confidence, Cited rules and their versions, Risk-gate decision auto or HIL, Approver identity when HIL, Action outcome plus idempotency key, Rollback reference when applicable.](../../diagrams/generated/fdai-operating-and-verification-01.en.svg)

The audit record is append-only and hash-chained per
[security-and-identity.md](../architecture/security-and-identity.md); the same walk works for shadow and
enforce events (mode is recorded on every entry).

## Runbook Set

Every automated action should have an operator-facing runbook. Upstream ships generic operational
runbooks under `docs/runbooks/`; deployment-specific values and procedures stay in a fork-local
runbook set per
[generic-scope.instructions.md](../../../.github/instructions/generic-scope.instructions.md).
The `fdai_runbook` front-matter block declares the schema version, covered ActionType patterns, and
the headings that provide preconditions, procedure, verification, rollback, and audit guidance.
`check-action-runbooks.py` fails CI when a shipped ActionType has no runbook, matches more than one
runbook, or a declared required heading is absent.

| Runbook | Purpose | Trigger |
|---------|---------|---------|
| **Kill-switch drill** | halt all auto-execution, verify all paths abstain | operational incident, scheduled drill |
| **DLQ drain** | inspect, replay, or discard dead-lettered events (with idempotency-key guards) | DLQ depth alert |
| **Drift reconciliation** | reconcile IaC drift via a PR (never silent apply) | scheduled drift alert |
| **Application rollback** | shift traffic back to the previous container revision | SLO burn, error spike, smoke-test fail |
| **Action rollback** | revert a per-action change (git revert, snapshot restore, replica-promotion undo) | rollback request, auto-demotion |
| **DR failover** | fail the control plane to an alternate region from state + backups | region outage |
| **Override withdrawal** | remove an active override, re-enable the underlying rule on that scope | rule revised, risk changed |
| **Catalog rollback** | revert to the previous rule-catalog version | bad rule set promoted |
| **Break-glass** | grant scoped emergency access under audit + auto-expiry | verified emergency |

Every runbook MUST state:

- **Preconditions** (permissions, prerequisite alerts).
- **Exact commands** (or the exact console navigation), copy-pasteable.
- **Verification** (what to check that proves it worked).
- **Rollback of the runbook itself** (undo of the operator step).
- The **audit trail** the runbook leaves.

> **Deployment boundary**: The upstream schema and generic procedure are enforced in CI. A fork
> supplies provider commands, exact resource values, and any narrower deployment-owned runbooks.

## Version and Configuration Exposure

The system MUST expose, at any time, machine- and human-readable, without special access:

- Deployed image **digest** and semantic version tag.
- Rule catalog **version tag + content hash**.
- **Config hash** (a stable sum over live runtime configuration; secrets excluded).
- Per-rule **effect + enforcement flag** - "what is currently enforced" for each rule /
  scope.
- Per-scope **override count** (linked to a list view).
- **Autonomous discovery loop state** (enabled / disabled, last cycle timestamp, last cycle
  pass rate).
- **Time since last successful canary** round-trip.
- **Kill-switch state** and **break-glass usage** in the current window.

Content only; presentation / dashboard layout is defined separately.

## Pre-Launch Verification (performance + integration)

Before a service opens, FDAI is most useful run **in shadow alongside a
performance / integration test** of the workload it will watch. FDAI does not
generate the load - an external load generator (Azure Load Testing, k6,
JMeter) drives the traffic - but while that traffic runs, the control plane
proves its detection and judgment against realistic conditions without acting:

- **Shadow judgment under real load.** New rules and actions run judge-and-log
  only ([architecture.instructions.md § Shadow -> Enforce](../../../.github/instructions/architecture.instructions.md#seven-autonomous-action-safeguards)),
  so the load test exercises the deterministic tiers and the T2 quality gate
  and every verdict is recorded, none executed.
- **Detection latency measured against budget.** The events the load generates
  feed the per-tier `LatencyBudgetMonitor`
  ([`core/measurement/latency_budget.py`](../../../services/core-control-plane/src/fdai/core/measurement/latency_budget.py)),
  so a tier that misses its p95 budget under load surfaces before go-live, not
  after.
- **Canary + smoke round-trip.** The [synthetic canary](#synthetic-canary-event)
  and the [post-deploy smoke test contract](#post-deploy-smoke-test-contract) confirm the full
  `ingest -> tier -> gate -> audit` loop completes within budget on the loaded
  environment.
- **Scenario replay.** `tools/baseline_run.py` replays the frozen scenario set
  ([goals-and-metrics.md](../architecture/goals-and-metrics.md)) so routing and
  auto-vs-HIL accuracy are quantified on the same build that will ship.

The result is a body of shadow evidence - accuracy, latency, zero
policy-violation escapes - that an operator reviews **before** promoting any
action from shadow to enforce.

## Azure read-investigation release evidence

Live checks use existing resources and a reader credential. They do not create, update, start,
stop, or delete an Azure resource. Repository tests use synthetic, customer-neutral payloads for
failure paths that are not safe to induce against a live subscription.

| Scenario | Evidence class | Result |
|----------|----------------|--------|
| Successful caller attribution | Live | Passed. Exact resolution and projected Activity Log reads matched user and service-principal actors while retaining only opaque actor and correlation references. |
| Resource Health | Live | Passed. An empty ARG projection fell back to the current Resource Health REST endpoint and returned normalized availability evidence. |
| Unauthorized scope | Live | Passed. An inaccessible scope became `unavailable` with a failed bounded receipt. |
| Ambiguous resource name | Live | Passed. One duplicate name returned four bounded candidates, no exact resource binding, and no history query. |
| Guest OS shutdown | Live and contract | Incomplete. Sixteen accessible workspaces contained no retained Event or Syslog shutdown record across their available history. Live missing-workspace behavior returned `unavailable`; matched Event and Syslog normalization passed contract tests only. |
| Provider throttling | Contract | Behavior passed. Synthetic `429` responses exercised bounded retry and terminal failure. An actual live `429` was not induced because deliberate throttling would violate the bounded-read policy. |
| Insufficient retention | Contract | Passed. Lookbacks beyond configured Activity Log or guest-log retention fail before HTTP and normalize as unavailable through the provider boundary. |

The incomplete guest-event row and missing naturally occurring live `429` remain release evidence,
not implementation defects. Keep the issue open until the dedicated validation environment can
produce those observations without an Azure change.

## Post-Launch Stabilization Window

After a service opens, FDAI is most useful **left running for the first few
days** at a heightened observation intensity - the stabilization window. It is
the leading edge of the 30-day
[measurement window](../architecture/goals-and-metrics.md#definitions), not a
separate mode, and it composes existing primitives:

> **Implementation status**: The scheduler and measurement primitives exist, but upstream doesn't
> currently register the daily health/drift/deployment-baseline jobs or publish
> `console.recurrent_query`. The bullets below define the target stabilization composition.

- **Shadow-first stays the default.** Newly introduced actions remain in shadow
  through the window; promotion to enforce waits until the stabilization
  signals below are clean, so an unstable opening never auto-executes.
- **Scheduled comparison to baseline.** Scheduled tasks
  ([`core/scheduler`](../../../services/core-control-plane/src/fdai/core/scheduler)) run daily health
  checks, configuration-drift diffs, and deployment verification against a
  documented baseline (including an uploaded **resource plan** in the knowledge
  base) - exactly the "compare to baseline" checks the operator wants right
  after launch.
- **Pattern promotion from real traffic.** The Month-1 observation tools and
  the `console.recurrent_query` signal ([operator-console.md § 9.3](../interfaces/operator-console.md))
  turn a repeated investigation into a rule candidate, so the catalog grows
  from what the launch actually surfaced.
- **Close guard-metric watch.** Guard-metric drift
  ([goals-and-metrics.md § Guard Metrics](../architecture/goals-and-metrics.md#guard-metrics-must-not-regress))
  is watched tightly through the window; a breach demotes back to shadow
  automatically. When the signals settle, operation returns to the normal
  cadence.

The window absorbs the noisy opening period with minimal human intervention,
then hands off to steady-state operation once stabilization signals hold.

## Open Decisions

- [ ] Synthetic canary audit-freshness and numeric round-trip alert budget. The publisher cadence
  defaults to five minutes and the canonical payload/idempotency shape is implemented.
- [ ] Smoke-test suite composition (fixture set, per-step budgets, promotion-gate wiring).
- [ ] Alert channel ownership matrix (fork vs upstream) and the fallback channel selection.
- [x] Runbook template - required sections, format, and CI check that a runbook is present
      for every automated action.
- [ ] Retention window and query model for the audit investigation flow.
- [ ] Cold-start deadline value (shared with
      [startup-and-lifecycle.md](startup-and-lifecycle.md#cold-start-scale-to-zero-specifics)).
- [ ] Stabilization-window length after launch (default "a few days") and the
      concrete stabilization signals that end it (guard-metric quiescence,
      canary streak, scenario-replay pass).
- [ ] Pre-launch load-test integration surface (which load generator, what
      per-tier latency budgets to assert under load).
