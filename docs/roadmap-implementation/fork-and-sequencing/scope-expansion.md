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
| Migrated legacy status | in-progress | Legacy status detail below | The prior owner did not use the structured ledger shape. |
| Workload SLO scheduled evaluation | implemented | `fdai/delivery/slo_burn_cli.py`; `infra/modules/compute/container-apps/slo_burn_job.tf`; focused CLI and infrastructure tests | A deployment can opt into one bounded pass over a non-empty workload SLO catalog with a real metric provider and the normal event ingress. Operational workload evidence remains installation-specific. |

#### Migrated legacy status detail


### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-08-24 | in-progress | Migrated the legacy status into the delegated ledger without reconstructing earlier provenance. | current change; preserved owner status from `docs/roadmap/fork-and-sequencing/scope-expansion.md`. | Replace the legacy summary with bounded evidence-backed scope rows and observable exits. |
| 2026-10-15 | implemented | Added the fail-closed one-shot SLO burn entry point and optional single-replica Container Apps schedule under the read-only inventory identity. | `current change`; SLO CLI and infrastructure cohorts (`37 passed`), Terraform format check. | Enable the job only with deployment-owned SLO definitions, then retain workload-specific freshness and burn receipts. |

### Remaining work

- [ ] Replace the migrated legacy summary with bounded evidence-backed scope rows and observable remaining-work exits.
- [ ] In a selected installation, bind a non-empty workload SLO catalog and authoritative metric
	provider, enable `slo_burn_cron_expression`, and retain one complete and one insufficient-data
	run receipt without treating the latter as healthy.
