# Deployment implementation ledger

This delivery ledger preserves reviewable implementation scope, append-only transitions,
and resumable work while the roadmap owner remains focused on normative design.

## Implementation status

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| Terraform plan/apply and supply-chain gates | implemented | `.github/workflows/deploy-dev.yml`, `.github/workflows/container-supply-chain.yml`, and focused workflow tests | Production inputs, image attestations, drift plans, and post-apply smoke checks are shipped. |
| Independent-service protected deployment | validated | `config/independent-service-live-evidence-manifest.json` and `config/independent-service-remote-evidence.json` | Protected plans bind source, backend, target, identities, and images; peer isolation and rollback evidence are retained. |
| Bounded database host binding | implemented | `.github/workflows/service-deploy.yml`, `guard_plan.py`, `plan_bundle.py`, and focused service-deploy tests in the current change | The sealed mode permits only the non-secret host binding. Governed apply evidence remains open. |
| Operator schema and catalog bootstrap | implemented | `infra/modules/operator-api/container-app/`, `.github/workflows/deploy-dev.yml`, and `tests/integration/scripts/test_service_deploy_workflow.py` in the current change | A successful Alembic Job gates a separate Core-image Job that writes immutable Rule and Ontology reference projections. |
| Browser-evidence retention Job | implemented | `infra/modules/compute/container-apps/browser_evidence_cleanup_job.tf`; focused Terraform contract checks (`4 passed`) and `terraform validate` | The opt-in scheduled Job uses a non-executor identity and bounded one-shot cleanup. Governed apply and run receipts are not retained. |
| Automated promotion and progressive delivery | not-started | Target design in this document | Automated dev -> staging -> prod promotion, traffic-split canaries, SLO rollback, and console blue/green are not implemented. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-08-13 | implemented | Adopted the implementation ledger without reconstructing earlier provenance and added deployed Operator catalog bootstrap after schema migration. | current change; focused deployment workflow and Terraform checks | Capture governed apply evidence for the catalog Job and implement the progressive-delivery targets. |
| 2026-08-14 | implemented | Corrected ingestion rollback guidance after the co-host compatibility path was retired. Rollback now restores exact prior independent API and worker revisions. | `current change`; focused Terraform validation and mocked ingestion tests passed 5 cases. | Keep deployment guides and mocked tests aligned with the independent service roots. |
| 2026-08-15 | implemented | Added an opt-in scheduled Container Apps Job for bounded browser-evidence retention with no executor identity or immediate platform retry. | `current change`; focused Terraform contract checks `4 passed`; `terraform validate`. | Capture the protected apply and successful and failed Job run receipts. |
| 2026-08-20 | implemented | Bounded every service migration connection, cross-service lock, and protected workflow stage after a stalled migration consumed the service job's full two-hour budget. Cleanup now preserves the original migration error. | `current change`; service migration and protected workflow contract checks passed 204 cases; Ruff and strict mypy passed. | Complete one protected exact apply and retain its migration, service health, and rollback-boundary evidence. |
| 2026-08-24 | implemented | Added a sealed database host binding mode, removed Core's duplicate host declaration, and retained an explicit legacy Operator name compatibility boundary for an in-place update. | `current change`; focused guard, bundle, workflow, naming, and Terraform validation checks. | Complete five zero-destroy plans and exact applies, then retain independent runtime and inventory evidence in Issue #262. |
| 2026-08-25 | implemented | Removed the completed Event Bus migration mode from platform and service workflows and deleted its helper API. Current deployments accept canonical `fdai.*` topic bindings without exposing a rerunnable one-time transition. | `current change`; focused deployment workflow, service helper, Terraform, and documentation checks | No remaining implementation work for the completed topic migration mode. |

### Remaining work

- [ ] Retain a repository-safe governed apply receipt showing that the Operator migration Job
  succeeds before the catalog Job and that both immutable projection keys are readable afterward.
- [ ] Retain a repository-safe protected apply and successful and failed execution receipts for the browser-evidence retention Job.
- [ ] Complete the five zero-destroy database host plans and exact applies in Issue #262, then
  retain workload environment presence, authoritative inventory, and independent endpoint evidence.
- [ ] Implement the documented automated artifact promotion, traffic-split canary, SLO rollback,
  and console blue/green flows with focused tests and governed runtime evidence.
