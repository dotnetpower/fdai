# Startup and Lifecycle implementation ledger

This delivery ledger preserves reviewable implementation scope, append-only transitions,
and resumable work while the roadmap owner remains focused on normative design.

## Implementation status

### Migrated implementation notes

> **Implementation status**: The current reference Terraform deploys one `core` container with
> `min_replicas = 1` and no KEDA scaling rule. Protected deployment runs the model resolver and a
> proposal-only weekly lifecycle reconciler. The collector job has a configurable deployment
> schedule, and discovery activation is a fail-closed runtime decision. End-to-end Human approval
> bootstrap remains incomplete.

> **Implementation status**: The headless runtime now assembles one deterministic
> `StartupReadinessReport` before it starts the Pantheon or event consumers. The standard probe
> inventory covers loaded config/catalog/policy, secret injection, workload identity, state,
> audit, kill-switch, Kafka round trip, embeddings, and every bound T2 cross-check candidate.
> Forks register enabled optional destinations through the same injected probe seam.

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| Startup readiness orchestration | implemented | [`runtime/readiness.py`](../../../services/core-control-plane/src/fdai/runtime/readiness.py), [`core/readiness/coordinator.py`](../../../services/core-control-plane/src/fdai/core/readiness/coordinator.py), and focused readiness tests | The runtime evaluates ordered phases, persists sanitized reports, and gates processing on the resulting decision. |
| T2 cross-check startup proof reuse | implemented | [`delivery/startup_model_probe.py`](../../../services/core-control-plane/src/fdai/delivery/startup_model_probe.py) and [`tests/delivery/test_startup_probe.py`](../../../services/core-control-plane/tests/delivery/test_startup_probe.py) | The first successful process-local proof uses the configured samples. Refreshes reuse it without another T2 request, while failures remain retryable. |
| Collector scheduling and governed discovery activation | implemented | [`rule_watcher_job.tf`](../../../infra/modules/compute/container-apps/rule_watcher_job.tf), [`rule_collector_job_cli.py`](../../../services/core-control-plane/src/fdai/delivery/rule_collector_job_cli.py), [`core/readiness/discovery_activation.py`](../../../services/core-control-plane/src/fdai/core/readiness/discovery_activation.py), [`runtime/discovery_activation.py`](../../../services/core-control-plane/src/fdai/runtime/discovery_activation.py), and focused collector, activation, Norns, runtime, and infrastructure tests | The configurable Job uses the non-effect inventory identity and records only validated provenance receipts. Runtime composition closes Norns publication until policy and every current prerequisite pass. |
| Bootstrap and lifecycle automation | in-progress | [`llm_resolver_cli.py`](../../../services/core-control-plane/src/fdai/rule_catalog/schema/llm_resolver_cli.py), `.github/workflows/deploy-dev.yml`, `.github/workflows/model-lifecycle-reconcile.yml`, and focused lifecycle tests | Protected model resolution and proposal-only reconciliation are implemented. Collector scheduling and governed discovery activation are implemented in the current change; end-to-end Human approval bootstrap remains incomplete. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-08-13 | implemented | Reused each successful T2 cross-check startup proof for later process-local readiness refreshes instead of resampling every five minutes. Failed and concurrent attempts remain retry-safe. | Current change in `startup_model_probe.py` and `test_startup_probe.py`; focused startup probe tests: `18 passed`. | Capture governed deployed-runtime metering evidence and complete the broader lifecycle workflows below. |
| 2026-08-19 | implemented | Ran deterministic live model resolution before protected Terraform planning, sealed its exact manifests and digests through apply, and added a weekly provider-failure-abstaining draft-PR reconciler. | `current change`; focused lifecycle, protected-plan verifier, Operator narrator, Terraform, and CI security contracts. | Retain a governed reconciler run and complete the independent collector and Human approval workflows. |
| 2026-08-19 | implemented | Scheduled the verified collector through a configurable Container Apps Job and bound a default-off discovery activation reducer to Norns' inert candidate publication boundary. Missing, stale, failed, duplicate, or unavailable evidence closes the gate with sanitized reason codes; policy disablement never changes the catalog. | `current change`; focused readiness activation, collector Job/CLI, runtime settings, collection/watcher, Norns, bootstrap, and infrastructure checks. | Retain governed collector and activation-transition receipts; complete the independent Human approval workflow. |

### Remaining work

- [ ] Complete end-to-end Human approval bootstrap with focused workflow tests cited in this
   ledger; retain governed collector and model reconciler runs separately.
- [ ] Record governed deployed-runtime metering that shows one successful T2 startup sample set per
   candidate and no additional T2 calls from later five-minute readiness refreshes in that process.
