# Phase 3 - Integrated Control Loop (Resilience · Change Safety · Cost Governance) implementation ledger

This delivery ledger preserves reviewable implementation scope, append-only transitions,
and resumable work while the roadmap owner remains focused on normative design.

## Implementation status

### Migrated implementation notes

> **Implementation status**: Shared control-loop/risk/executor plumbing, cross-vertical
> precedence, Resilience/Change Safety/FinOps guardrail modules, scheduler/DR adapters, DB restore
> primitives, and Terraform per-vertical UAMIs are implemented. Production exit evidence for
> measured RPO/RTO, savings, and lead time across all three verticals, live auto-action
> composition, and the Assurance Twin ambient review/panel are incomplete. The automated behavior
> and Exit Criteria below are targets, not claims of current attainment.

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| Unified shadow loop, cross-resource lock, and terminal audit | in-progress | `services/core-control-plane/src/fdai/core/control_loop/`; `uv run pytest -q --no-cov services/core-control-plane/tests/pipeline/test_unified_control_loop.py services/core-control-plane/tests/pipeline/test_cross_vertical_lock.py services/core-control-plane/tests/pipeline/test_control_loop_e2e.py` passed 58 cases | The P1/P2 shadow path, lock, and audit pass. Phase 3 precedence and all three vertical owners are not yet composed into one runtime path. |
| Cross-vertical precedence resolver | implemented | `services/core-control-plane/src/fdai/core/risk_gate/precedence.py`; `uv run pytest -q --no-cov services/core-control-plane/tests/core/risk_gate/test_precedence.py` passed 9 cases | The pure resolver is deterministic and fail-closed. Runtime arbitration and deferral audit remain integration work. |
| Resilience scheduler and DB-DR verifier primitives | implemented | `services/core-control-plane/src/fdai/core/verticals/resilience/`; DB-DR and experiment provider contracts; `uv run pytest -q --no-cov services/core-control-plane/tests/core/verticals/test_resilience.py services/core-control-plane/tests/verticals/test_resilience_execution.py services/core-control-plane/tests/verticals/test_db_dr_verifier.py` passed 65 cases | Local schedule, restore, integrity, smoke, teardown, and verdict mechanics pass without claiming a live drill. |
| Scheduled Phase 3 job entrypoints | in-progress | `infra/modules/compute/container-apps/scheduler_job.tf`; `dr_drill_job.tf`; current scheduler and DB-DR source modules | Terraform defines opt-in jobs, but the scheduler module is absent and the DB-DR live runner is uncomposed. Enabling either path is not yet a successful runtime. |
| Change Safety integrated response | in-progress | `services/core-control-plane/src/fdai/core/verticals/change_safety/`; `uv run pytest -q --no-cov services/core-control-plane/tests/core/verticals/test_change_safety.py services/core-control-plane/tests/verticals/test_change_safety_detector.py` passed 32 cases | Classification and Activity Log shadow reconcile pass locally. Auto/HIL terminal workflow and effect verification are not integrated end to end. |
| FinOps guardrails and optional package jobs | in-progress | `services/core-control-plane/src/fdai/core/verticals/cost_governance/finops.py`; `extensions/cost-governance/`; `uv run pytest -q --no-cov services/core-control-plane/tests/core/verticals/test_finops.py extensions/cost-governance/tests/test_resources.py extensions/cost-governance/tests/test_runtime.py extensions/cost-governance/tests/test_validation.py extensions/cost-governance/tests/test_jobs.py` passed 58 cases | Guardrails, resources, job entrypoint contracts, identity, serialization, and disabled defaults pass locally. The optional package remains observation-only and no realized-savings receipt is claimed. |
| Assurance Twin report and review primitives | in-progress | `services/core-control-plane/src/fdai/core/assurance_twin/report.py`; `review.py`; `uv run pytest -q --no-cov services/core-control-plane/tests/assurance_twin/test_report.py services/core-control-plane/tests/assurance_twin/test_review.py` passed 32 cases | Bounded report and review mechanics pass. Ambient publisher, Operator API, Console panel, and governed runtime receipt are unbound. |
| Per-vertical identity catalog pass-through and optional-job Terraform | in-progress | `infra/modules/compute/container-apps/outputs.tf`; `tests/vertical_identities.tftest.hcl`; `terraform -chdir=infra/modules/compute/container-apps test` passed 1 case after `terraform init -backend=false -input=false` | The module passes supplied identity ids through its catalog. Enabled optional-job plans, root identity creation and attachment, role assignments, and applied runtime evidence are not proven by this test. |
| Phase 3 measured operational outcomes | not-started | Phase 3 exit criteria; no retained exact-revision cohort found | No repository-safe governed receipts prove measured RPO/RTO, lead time, realized savings, live cross-vertical composition, or zero policy escapes. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-08-29 | in-progress | Replaced the placeholder scope row with bounded Phase 3 areas and reran unified-loop, precedence, Resilience/DB-DR, Change Safety, FinOps, Assurance Twin, and Terraform identity slices. The audit separated local primitives and deployment definitions from integrated runtime and measured outcome claims. | `current change`; exact commands and outcomes are recorded in the scope rows: 58, 9, 65, 32, 58, 32, and 1 cases passed. | Complete the integrated loop, executable job entrypoints, Assurance surface, and authoritative outcome evidence below. |
| 2026-08-24 | in-progress | Migrated the legacy status into the delegated ledger without reconstructing earlier provenance. | current change; preserved owner status from `docs/roadmap/phases/phase-3-integrated-loop.md`. | Replace the legacy summary with bounded evidence-backed scope rows and observable exits. |

### Remaining work

- [x] Replace the migrated placeholder scope row with bounded rows and rerun all seven focused local validation slices.
- [ ] Make the scheduler and DB-DR Container Apps Job entrypoints executable under [issue #347](https://github.com/dotnetpower/fdai/issues/347), then pass focused CLI tests and a Terraform test with both jobs enabled and importable.
- [ ] Integrate cross-vertical precedence, identities, Change Safety, Resilience, and FinOps through one shadow control-loop path under [issue #349](https://github.com/dotnetpower/fdai/issues/349), then retain a passing same-resource WIN/DEFER/HIL end-to-end scenario.
- [ ] Bind the Assurance Twin ambient review, authenticated Operator API, and Console panel under [issue #350](https://github.com/dotnetpower/fdai/issues/350), then pass focused Core, API, Console, accessibility, and bilingual catalog checks plus one governed report receipt.
- [ ] Retain an exact-revision governed cohort under [issue #348](https://github.com/dotnetpower/fdai/issues/348) that records RPO/RTO, lead time, realized savings, cross-vertical arbitration, rollback, and zero policy escapes with sample sizes and confidence intervals.
