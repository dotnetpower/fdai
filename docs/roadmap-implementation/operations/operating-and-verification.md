# Operating and Verification implementation ledger

This delivery ledger preserves reviewable implementation scope, append-only transitions,
and resumable work while the roadmap owner remains focused on normative design.

## Implementation status

### Migrated implementation notes

> **Implementation status**: The scheduler and measurement primitives exist, but upstream doesn't
> currently register the daily health/drift/deployment-baseline jobs or publish
> `console.recurrent_query`. The bullets below define the target stabilization composition.

Runtime health, startup readiness, transition telemetry, and the synthetic canary path are
implemented and covered by focused tests. The deployment smoke currently proves publisher job
completion only; complete alerting, round-trip verification, drills, and stabilization automation
remain incomplete, so no area is claimed as fully operationally validated.

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| Runtime `/live` and `/ready` endpoints plus startup-readiness evaluation, persistence, transitions, and guarded refresh | implemented | [`runtime/health.py`](../../../services/core-control-plane/src/fdai/runtime/health.py), [`runtime/readiness.py`](../../../services/core-control-plane/src/fdai/runtime/readiness.py), [`test_readiness.py`](../../../services/core-control-plane/tests/runtime/test_readiness.py), and [`test_startup_coordinator.py`](../../../services/core-control-plane/tests/core/readiness/test_startup_coordinator.py) | Process-critical failure closes readiness; degraded capabilities lower authority without raising it on recovery. |
| Bounded transition spans and metrics with secure OTLP configuration | implemented | [`transitions.py`](../../../services/core-control-plane/src/fdai/shared/telemetry/transitions.py) and [`test_transition_telemetry.py`](../../../services/core-control-plane/tests/shared/test_transition_telemetry.py) | Stable allowlisted attributes prevent payloads and provider errors from becoming telemetry labels. |
| Synthetic canary publisher, canonical consumer, no-op audit path, and scheduled Container Apps Job | implemented | [`canary_cli.py`](../../../services/core-control-plane/src/fdai/delivery/canary_cli.py), [`_canary.py`](../../../services/core-control-plane/src/fdai/core/control_loop/_canary.py), [`canary_job.tf`](../../../infra/modules/compute/container-apps/canary_job.tf), and focused canary tests | The canary is isolated from T0/T1/T2, risk, execution, incident, and learning paths. |
| Post-deploy promotion smoke | in-progress | [`deploy-dev.yml`](../../../.github/workflows/deploy-dev.yml) runs migrations, optional health checks, and the canary publisher Job | The workflow blocks on publisher failure but doesn't yet verify the consumed audit entry, fixture replay, kill-switch cycle, or human-approval dry-run. |
| Complete self-health exporters, alert-rule mapping, fallback delivery, and operational drills | in-progress | Transition telemetry, readiness, and canary sources above provide a subset of the required signals | No upstream configuration maps every signal in the health contract to an alert threshold, owner lane, fallback, and tested delivery receipt. |
| Correlation-based audit investigation and unified version/configuration exposure | in-progress | [`rule_fire_trace.py`](../../../services/core-control-plane/src/fdai/core/audit/rule_fire_trace.py), [`audit_rca.py`](../../../services/core-control-plane/src/fdai/core/reporting/datasources/audit_rca.py), and runtime state projections | Correlation and reporting primitives exist, but one public read surface doesn't yet expose every version, hash, rule effect, override, canary, kill-switch, and break-glass field listed below. |
| Pre-launch latency measurement and frozen-scenario replay | implemented | [`latency_budget.py`](../../../services/core-control-plane/src/fdai/core/measurement/latency_budget.py), [`baseline_run.py`](../../../tools/baseline_run.py), and focused tests | The primitives produce bounded measurements and release-gate results; an external load generator and deployment-specific budgets remain operator inputs. |
| Live Azure read-investigation scenarios | in-progress | [Azure Read Investigations](../interfaces/azure-read-investigations.md#implementation-status) | Four bounded read-only scenarios passed, while guest-event matching, an actual provider `429`, and cross-service parity receipts remain open release evidence. |
| ActionType operator-runbook schema and coverage | implemented | [`check-action-runbooks.py`](../../../scripts/quality/documentation/check-action-runbooks.py), [`incident-mitigation-and-rollback.md`](../../runbooks/incident-mitigation-and-rollback.md), and [`test_check_action_runbooks.py`](../../../tests/integration/scripts/test_check_action_runbooks.py) | Every shipped ActionType matches exactly one generic upstream runbook whose declared precondition, procedure, verification, rollback, and audit sections exist. Deployment-specific commands remain fork-owned. |
| Post-launch stabilization composition | in-progress | [`core/scheduler/`](../../../services/core-control-plane/src/fdai/core/scheduler) and measurement primitives | The daily health, drift, and deployment-baseline jobs and `console.recurrent_query` signal aren't registered upstream. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-08-14 | in-progress | Adopted the implementation ledger and separated tested self-observability primitives from incomplete operational evidence; earlier provenance wasn't reconstructed. | Current change; focused readiness, telemetry, canary, latency, and baseline-runner tests cited in the scope table. | Complete deployment round-trip evidence, alert and drill coverage, unified exposure, and stabilization bindings. |
| 2026-08-14 | implemented | Defined the operator-runbook front-matter schema and added CI coverage for every shipped ActionType. | Current change; `check-action-runbooks.py` and `test_check_action_runbooks.py`. | Keep deployment-owned commands and procedures aligned with the same required semantic sections. |

### Remaining work

- [ ] Extend deployment smoke to verify the consumed canary audit entry within a numeric latency
  budget, replay the frozen shadow fixtures, exercise kill-switch on/off, and complete a no-execute
  human-approval dry-run with linked audit receipts.
- [ ] Map every self-health signal to a concrete threshold, owner lane, fallback route, and tested
  delivery receipt, then record the governed operational evidence.
- [ ] Expose the complete version, configuration, rule-effect, override, discovery, canary,
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
[startup-and-lifecycle.md](../../roadmap/operations/startup-and-lifecycle.md#shipped-runtime-boundary) for probe budgets and
the registered-destination contract.

Signals emit via OpenTelemetry to the configured backend
([deployment.md#observability-slos-and-alerting](../../roadmap/deployment/deployment.md#observability-slos-and-alerting)).

`OTEL_EXPORTER_OTLP_ENDPOINT` enables OTLP/gRPC trace and metric export. HTTPS is required outside
loopback; credentials, query strings, and fragments are rejected in the endpoint. Without an
endpoint, local console spans and in-memory metrics remain the default.

Channel, extension, model, scheduler, and security lifecycle components emit the same
`fdai.transition` span and `fdai.transition.count` metric through a process-singleton emitter.
Attributes use bounded allowlisted domain, name, outcome, and component-specific scalar keys;
provider error text, payloads, credentials, and arbitrary labels are not accepted. Emission is
best-effort so exporter failure cannot block routing or safety decisions.
