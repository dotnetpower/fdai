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
| Unified shadow loop, cross-resource lock, and terminal audit | implemented | `services/core-control-plane/src/fdai/agents/_framework/cross_vertical_candidates.py`; `services/core-control-plane/tests/agents/test_cross_vertical_composition.py`; `services/core-control-plane/tests/scenarios/phase3/v2026.08-cross-vertical-shadow.json`; focused Story #349 regression passed 103 cases | The three owner-authenticated candidates join on one resource and cutoff, Odin records `win`/`defer`/`hil`, Saga audits the decision and verdict, and Thor remains the only `ActionRun` publisher. This is local frozen shadow evidence, not a live outcome. |
| Cross-vertical precedence resolver | implemented | `services/core-control-plane/src/fdai/core/risk_gate/precedence.py`; `services/core-control-plane/src/fdai/agents/_framework/vertical_precedence.py`; focused Story #349 regression passed 103 cases | Runtime composition applies fixed initial-vertical precedence before the reviewed weighted objective fallback. Duplicate, reordered, concurrent, timeout, rollback, and partial-subscriber cases fail closed in focused tests. |
| Resilience scheduler and DB-DR verifier primitives | implemented | `services/core-control-plane/src/fdai/core/verticals/resilience/`; DB-DR and experiment provider contracts; `uv run pytest -q --no-cov services/core-control-plane/tests/core/verticals/test_resilience.py services/core-control-plane/tests/verticals/test_resilience_execution.py services/core-control-plane/tests/verticals/test_db_dr_verifier.py` passed 65 cases | Local schedule, restore, integrity, smoke, teardown, and verdict mechanics pass without claiming a live drill. |
| Scheduled Phase 3 job entrypoints | implemented | `delivery/scheduler_tick_cli.py`; `delivery/db_dr_drill_cli.py`; `delivery/azure/db_dr_restore.py`; `delivery/db_dr_postgres.py`; Container Apps Job Terraform; focused CLI, adapter, verifier, and infrastructure tests | Both jobs invoke importable delivery entrypoints. The scheduler composes durable claims and Event Bus publication. DB-DR composes Azure restore, PostgreSQL integrity and smoke, teardown, and durable verifier audit. Distinct non-executor identities carry only job-specific permissions. No live run receipt is claimed. |
| Change Safety integrated response | in-progress | `services/core-control-plane/src/fdai/core/verticals/change_safety/`; `uv run pytest -q --no-cov services/core-control-plane/tests/core/verticals/test_change_safety.py services/core-control-plane/tests/verticals/test_change_safety_detector.py` passed 32 cases | Classification and Activity Log shadow reconcile pass locally. Auto/HIL terminal workflow and effect verification are not integrated end to end. |
| FinOps guardrails and optional package jobs | in-progress | `services/core-control-plane/src/fdai/core/verticals/cost_governance/finops.py`; `extensions/cost-governance/`; `uv run pytest -q --no-cov services/core-control-plane/tests/core/verticals/test_finops.py extensions/cost-governance/tests/test_resources.py extensions/cost-governance/tests/test_runtime.py extensions/cost-governance/tests/test_validation.py extensions/cost-governance/tests/test_jobs.py` passed 58 cases | Guardrails, resources, job entrypoint contracts, identity, serialization, and disabled defaults pass locally. The optional package remains observation-only and no realized-savings receipt is claimed. |
| Assurance Twin report and review primitives | in-progress | `services/core-control-plane/src/fdai/core/assurance_twin/report.py`; `review.py`; `uv run pytest -q --no-cov services/core-control-plane/tests/assurance_twin/test_report.py services/core-control-plane/tests/assurance_twin/test_review.py` passed 32 cases | Bounded report and review mechanics pass. Ambient publisher, Operator API, Console panel, and governed runtime receipt are unbound. |
| Per-vertical identity catalog pass-through and optional-job Terraform | implemented | `infra/main.tf`; Container Apps scheduler and DB-DR jobs; `tests/integration/infra/test_scheduler_db_dr_jobs.py`; Terraform validation | Root composition creates separate scheduler and DB-DR identities. Neither job receives the executor identity. Governed apply evidence remains separate. |
| Phase 3 measured operational outcomes | not-started | Phase 3 exit criteria; no retained exact-revision cohort found | No repository-safe governed receipts prove measured RPO/RTO, lead time, realized savings, live cross-vertical composition, or zero policy escapes. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-08-31 | implemented | Composed the three initial vertical candidates through the existing typed Pantheon bus. Owner-authenticated candidate identities remain separate, fixed precedence and reviewed objective evidence produce audited per-candidate dispositions, and only Thor can publish the shadow ActionRun. | `current change`; cross-vertical accumulator, Forseti/Odin/Saga wiring, frozen `v2026.08` scenario, and focused 103-case regression. | Retain live-authoritative measured outcomes separately under issue #348; no live mutation or promotion is claimed here. |
| 2026-08-31 | implemented | Completed the two Phase 3 scheduled entrypoints. Scheduler retains durable duplicate suppression and governed Event Bus publication. The delivery-owned DB-DR CLI now composes Azure restore, deterministic PostgreSQL checks, rolled-back smoke, teardown, and verifier audit. Root Terraform assigns separate non-executor identities and blocks enabled jobs with incomplete bindings. | `current change`; delivery scheduler/DB-DR modules, compute and root Terraform, focused adapter/CLI/verifier/infrastructure checks. | Retain protected apply and successful/failed scheduled-run receipts under issue #348; no live receipt is claimed here. |
| 2026-08-29 | in-progress | Replaced the placeholder scope row with bounded Phase 3 areas and reran unified-loop, precedence, Resilience/DB-DR, Change Safety, FinOps, Assurance Twin, and Terraform identity slices. The audit separated local primitives and deployment definitions from integrated runtime and measured outcome claims. | `current change`; exact commands and outcomes are recorded in the scope rows: 58, 9, 65, 32, 58, 32, and 1 cases passed. | Complete the integrated loop, executable job entrypoints, Assurance surface, and authoritative outcome evidence below. |
| 2026-08-24 | in-progress | Migrated the legacy status into the delegated ledger without reconstructing earlier provenance. | current change; preserved owner status from `docs/roadmap/phases/phase-3-integrated-loop.md`. | Replace the legacy summary with bounded evidence-backed scope rows and observable exits. |

### Remaining work

- [x] Replace the migrated placeholder scope row with bounded rows and rerun all seven focused local validation slices.
- [x] Make the scheduler and DB-DR Container Apps Job entrypoints executable under [issue #347](https://github.com/dotnetpower/fdai/issues/347), then pass focused CLI, adapter, verifier, and Terraform contract checks.
- [x] Integrate cross-vertical precedence, identities, Change Safety, Resilience, and FinOps through one shadow control-loop path under [issue #349](https://github.com/dotnetpower/fdai/issues/349), with a passing same-resource WIN/DEFER/HIL frozen scenario and fail-closed replay matrix.
- [ ] Bind the Assurance Twin ambient review, authenticated Operator API, and Console panel under [issue #350](https://github.com/dotnetpower/fdai/issues/350), then pass focused Core, API, Console, accessibility, and bilingual catalog checks plus one governed report receipt.
- [ ] Retain an exact-revision governed cohort under [issue #348](https://github.com/dotnetpower/fdai/issues/348) that records RPO/RTO, lead time, realized savings, cross-vertical arbitration, rollback, and zero policy escapes with sample sizes and confidence intervals.
