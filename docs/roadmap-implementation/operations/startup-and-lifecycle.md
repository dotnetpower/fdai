# Startup and Lifecycle implementation ledger

This delivery ledger preserves reviewable implementation scope, append-only transitions,
and resumable work while the roadmap owner remains focused on normative design.

## Implementation status

### Migrated implementation notes

> **Implementation status**: The current reference Terraform deploys one `core` container with
> `min_replicas = 1` and no KEDA scaling rule. Protected deployment runs the model resolver and a
> proposal-only weekly lifecycle reconciler. The collector job has a configurable deployment
> schedule, and discovery activation is a fail-closed runtime decision. The Human approval callback
> bootstrap is implemented with deterministic local evidence; governed deployment evidence remains
> separate.

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
| Human approval bootstrap | implemented | `fdai_operator_service/families/iam/hil_callback*.py`, `families/iam/hil_teams_callback.py`, `families/iam/hil_decision_outbox.py`; `scripts/operations/run-hil-bootstrap-canary.py`; focused Operator callback, Teams receiver, outbox replay, PostgreSQL, Kafka, workflow, governance, and canary tests | Teams and Slack use independent complete destinations. A Teams `Action.Execute` click returns through an Operator Bot activity receiver that authenticates the Bot service token and a delegated OBO actor token; the signed HMAC route serves internal relays only. Signed time anchors decisions, exact retries preserve first audit timestamps, workflow slots carry bounded context, and a lease-fenced worker redrives a failed publication so delivery is marked only after broker acceptance. |
| Bootstrap and lifecycle automation | in-progress | [`llm_resolver_cli.py`](../../../services/core-control-plane/src/fdai/rule_catalog/schema/llm_resolver_cli.py), `.github/workflows/deploy-dev.yml`, `.github/workflows/model-lifecycle-reconcile.yml`, and focused lifecycle tests | Protected model resolution, proposal-only reconciliation, collector scheduling, governed discovery activation, and the local Human approval bootstrap are implemented. Governed runtime receipts remain separate. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-08-13 | implemented | Reused each successful T2 cross-check startup proof for later process-local readiness refreshes instead of resampling every five minutes. Failed and concurrent attempts remain retry-safe. | Current change in `startup_model_probe.py` and `test_startup_probe.py`; focused startup probe tests: `18 passed`. | Capture governed deployed-runtime metering evidence and complete the broader lifecycle workflows below. |
| 2026-08-19 | implemented | Ran deterministic live model resolution before protected Terraform planning, sealed its exact manifests and digests through apply, and added a weekly provider-failure-abstaining draft-PR reconciler. | `current change`; focused lifecycle, protected-plan verifier, Operator narrator, Terraform, and CI security contracts. | Retain a governed reconciler run and complete the independent collector and Human approval workflows. |
| 2026-08-19 | implemented | Scheduled the verified collector through a configurable Container Apps Job and bound a default-off discovery activation reducer to Norns' inert candidate publication boundary. Missing, stale, failed, duplicate, or unavailable evidence closes the gate with sanitized reason codes; policy disablement never changes the catalog. | `current change`; focused readiness activation, collector Job/CLI, runtime settings, collection/watcher, Norns, bootstrap, and infrastructure checks. | Retain governed collector and activation-transition receipts; complete the independent Human approval workflow. |
| 2026-08-31 | implemented | Completed the local Human approval callback with stable decision time, idempotent audit phases, proposal-first recovery, bounded workflow context, durable Kafka publication, and independent Teams/Slack destinations without a provider call. | `current change`; focused callback, PostgreSQL, Kafka, composition, workflow, and deployment checks (`456 passed`, one optional PDF skip); governance authority checks (`31 passed`); the local canary reported Slack approval, Teams rejection, timeout fail-closed, tampered-card refusal, eight audit records before teardown, two broker publications, zero retained records, and zero live calls. | Retain governed deployed Teams, broker-acceptance, and trusted governance-App receipts before runtime validation. |
| 2026-08-31 | implemented | Made the human approval loop complete without operator intervention. `hil_teams_callback.py` accepts a Teams `invoke` activity, verifies the Bot Framework service token with the existing channel-edge verifier, binds the configured tenant, team, and channel, and requires a delegated OBO actor token before the shared decision service runs. `HilDecisionOutboxBridge` runs a lease-fenced replay worker inside the Operator application lifecycle and readiness probe, so a broker failure or a crash after the durable write is redriven and delivery is marked only after broker acceptance. | `current change`; focused Operator IAM, Teams receiver, outbox replay, PostgreSQL, composition, and canary checks. | Retain governed deployed Teams and broker-acceptance receipts; the local canary reports `local_dry_run_no_network` and is not a live proof. |

### Remaining work

- [x] Complete the deterministic local Human approval bootstrap with focused callback, authority,
   timeout, duplicate, audit, governance, and canary checks.
- [x] Compose the Teams Bot activity receiver and the lease-fenced decision outbox replay
   worker so a card click and a failed broker publication both complete autonomously.
- [ ] Retain governed deployed Teams and trusted governance-App receipts on a pinned revision.
- [ ] Record governed deployed-runtime metering that shows one successful T2 startup sample set per
   candidate and no additional T2 calls from later five-minute readiness refreshes in that process.
