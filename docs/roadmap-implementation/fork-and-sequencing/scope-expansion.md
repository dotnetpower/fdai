# Scope Expansion and Structural Gaps implementation ledger

This delivery ledger preserves reviewable implementation scope, append-only transitions,
and resumable work while the roadmap owner remains focused on normative design.

## Implementation status

### Migrated implementation notes

> **Implementation status (2026-07-21).** Incident, all eight telemetry wire contracts,
> workload SLO, runbook, on-call, postmortem, and vertical registry from section 3 are shipped.
> Its `Problem` paragraphs preserve the historical gaps at adoption time. T2 candidate Action
> construction and unified risk/HIL routing are also shipped; only handing a risk-eligible T2
> Action to the executor remains.

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| Incident lifecycle, proposals, ticket linkage, and storm coordination | implemented | `services/core-control-plane/src/fdai/core/incident/`; `services/core-control-plane/src/fdai/shared/contracts/incident/schema.json`; `services/core-control-plane/tests/core/incident/test_incident_lifecycle.py`; `services/core-control-plane/tests/core/incident/test_storm.py` (`40 passed`) | Durable state transitions, conversational proposals, idempotent ticket linkage, and deterministic storm wave sequencing pass focused checks. |
| Eight Layer-0 wire contracts and telemetry ingestion seams | implemented | `services/core-control-plane/src/fdai/shared/providers/`; `services/core-control-plane/src/fdai/delivery/azure/metric_logs.py`; `services/core-control-plane/tests/delivery/azure/test_metric_logs.py` (`22 passed`) | `MetricProvider`, `LogQueryProvider`, and `TraceQueryProvider` protocols and the Azure Monitor Logs metric adapter are implemented and default to no-op locally. |
| Runbook orchestration, on-call schedule, and postmortem knowledge extraction | implemented | `services/core-control-plane/src/fdai/core/runbook/`; `services/core-control-plane/src/fdai/shared/providers/oncall_schedule.py`; `services/core-control-plane/src/fdai/core/postmortem/`; `services/core-control-plane/tests/core/runbook/test_runbook_runner.py`, `services/core-control-plane/tests/providers/test_oncall_schedule.py`, `services/core-control-plane/tests/core/oncall/test_resolver.py`, `services/core-control-plane/tests/core/postmortem/test_postmortem_draft.py`, and `services/core-control-plane/tests/core/postmortem/test_postmortem_learning.py` (`69 passed`) | Per-step safeguard enforcement, static/PagerDuty on-call schedule resolution with role fallback, and fail-closed postmortem lesson extraction pass focused tests. |
| Vertical registry onboarding seam | implemented | `services/core-control-plane/src/fdai/core/verticals/registry.py`; `services/core-control-plane/tests/verticals/test_registry.py` (`13 passed`) | `VerticalRegistry` validates ASCII identifiers, non-empty rule sources for enabled verticals, and shadow-first onboarding defaults. |
| T1/T2 ControlLoop routing and executor handoff | in-progress | `services/core-control-plane/src/fdai/core/control_loop/`; `services/core-control-plane/tests/core/control_loop/test_change_safety_evidence.py`; `services/core-control-plane/tests/core/control_loop/test_readiness_remediation.py` (`6 passed`) | T1 shadow reuse, T2 quality-gated proposal logging, candidate `Action` construction, and unified risk/HIL routing are implemented; handing an `auto`-eligible T2 `Action` to the executor with terminal receipt verification remains open. |
| Workload SLO scheduled evaluation | implemented | `fdai/delivery/slo_burn_cli.py`; `infra/modules/compute/container-apps/slo_burn_job.tf`; focused CLI and infrastructure tests | A deployment can opt into one bounded pass over a non-empty workload SLO catalog with a real metric provider and the normal event ingress. Operational workload evidence remains installation-specific. |

#### Migrated legacy status detail


### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-08-24 | in-progress | Migrated the legacy status into the delegated ledger without reconstructing earlier provenance. | current change; preserved owner status from `docs/roadmap/fork-and-sequencing/scope-expansion.md`. | Replace the legacy summary with bounded evidence-backed scope rows and observable exits. |
| 2026-10-15 | implemented | Added the fail-closed one-shot SLO burn entry point and optional single-replica Container Apps schedule under the read-only inventory identity. | `current change`; SLO CLI and infrastructure cohorts (`37 passed`), Terraform format check. | Enable the job only with deployment-owned SLO definitions, then retain workload-specific freshness and burn receipts. |
| 2026-11-02 | in-progress | Replaced the `Migrated legacy status` placeholder row with bounded, evidence-backed scope rows covering incident lifecycle, telemetry seams, runbook/on-call/postmortem, vertical registry, and T1/T2 ControlLoop routing, and added an explicit remaining-work exit for T2 executor handoff. | `current change`; `test_incident_lifecycle.py`, `test_storm.py`, `test_metric_logs.py`, `test_runbook_runner.py`, `test_oncall_schedule.py`, `test_resolver.py`, `test_postmortem_draft.py`, `test_postmortem_learning.py`, `test_registry.py`, `test_change_safety_evidence.py`, and `test_readiness_remediation.py` (`150 passed`); `python3 scripts/quality/architecture/check-roadmap-implementation-tracking.py`. | Hand an `auto`-eligible T2 `Action` to the selected executor only after promotion, and retain installation-bound workload SLO receipts. |

### Remaining work

- [x] Replace the migrated legacy summary with bounded evidence-backed scope rows and observable remaining-work exits (`docs/roadmap-implementation/fork-and-sequencing/scope-expansion.md`).
- [ ] Hand a quality-gated T2 `Action` whose unified risk decision is `auto` to the selected executor and record its terminal effect-verification receipt once a T2 path is promoted beyond shadow.
- [ ] In a selected installation, bind a non-empty workload SLO catalog and authoritative metric
	provider, enable `slo_burn_cron_expression`, and retain one complete and one insufficient-data
	run receipt without treating the latter as healthy.
