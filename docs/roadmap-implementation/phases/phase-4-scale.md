# Phase 4 - Scale (Azure); Multi-Cloud (TBD) implementation ledger

This delivery ledger preserves reviewable implementation scope, append-only transitions,
and resumable work while the roadmap owner remains focused on normative design.

## Implementation status

### Migrated implementation notes

> **Implementation status**: The regression, pattern-growth, model-tracking, and latency-budget
> libraries; two primary measurement runners plus one optional operational-promotion runner; runner
> CLI; and Terraform job module are implemented.
> Continuous production-schedule results, statistical Phase 4 exit evidence, and dedicated
> vector-store or AKS runtimes are incomplete. The reference Container Apps deployment currently
> uses `min_replicas = 1` without a KEDA scaling rule. Scale-to-zero is a target topology available
> only after a fork adds a lag-based rule.

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| Regression library and automatic demotion runner | implemented | `services/core-control-plane/src/fdai/core/measurement/regression.py`; `runners.py`; `uv run pytest -q --no-cov services/core-control-plane/tests/core/measurement/test_regression.py services/core-control-plane/tests/measurement/test_runners.py` passed 24 cases | Pure regression and durable demotion mechanics pass locally. No scheduled production receipt is claimed. |
| Pattern intake and temporal holdout | in-progress | `services/core-control-plane/src/fdai/core/measurement/pattern_growth.py`; `uv run pytest -q --no-cov services/core-control-plane/tests/core/measurement/test_pattern_growth.py` passed 10 cases | Intake and holdout policies pass separately, but the runner does not bind the temporal holdout outcome into ingestion and audit. |
| Model cost and quality swap policy | in-progress | `services/core-control-plane/src/fdai/core/measurement/model_tracking.py`; `uv run pytest -q --no-cov services/core-control-plane/tests/core/measurement/test_model_tracking.py` passed 10 cases | Pure swap policy passes locally. No runner, CLI, audit, or reviewed model-binding transition consumes it. |
| Per-tier latency budget policy | in-progress | `services/core-control-plane/src/fdai/core/measurement/latency_budget.py`; `uv run pytest -q --no-cov services/core-control-plane/tests/core/measurement/test_latency_budget.py` passed 8 cases | Pure budget evaluation passes locally. Measured runtime audit integration is absent. |
| Measurement runner CLI and delivery adapters | in-progress | `services/core-control-plane/src/fdai/delivery/measurement_runner_cli.py`; `services/core-control-plane/src/fdai/delivery/measurement/`; `uv run pytest -q --no-cov services/core-control-plane/tests/delivery/measurement/test_measurement_runner_cli.py services/core-control-plane/tests/core/measurement/test_runners_cli.py` passed 17 cases | Baseline, growth, and optional promotion entrypoint mechanics exist. Direct scenario-replayer and PostgreSQL-growth lifecycle coverage plus scheduled receipts remain incomplete. |
| T1 pgvector pattern storage | in-progress | `services/core-control-plane/src/fdai/delivery/persistence/pgvector_pattern_library.py`; `uv run pytest -q --no-cov services/core-control-plane/tests/persistence/test_pgvector_pattern_library.py` passed 14 cases and skipped 5 live-database cases because `FDAI_DATABASE_URL` was unset | Local adapter behavior passes; live PostgreSQL parity is not proven in this change. Dedicated vector-store graduation remains deferred. |
| Measurement runner Terraform | implemented | `infra/modules/measurement-runners/`; `tests/jobs.tftest.hcl`; `tests/integration/infra/test_measurement_runner_jobs.py`; focused Terraform and Python contract checks | Baseline, growth, and operational-promotion jobs are opt-in and use a dedicated non-executor identity. Plan assertions pin commands, secret references, schedules, retries, parallelism, CPU, memory, and nullable outputs. No applied job or run history is claimed. |
| Phase 4 statistical exit evidence | not-started | `docs/baselines/v2026.07.json`; `uv run pytest -q --no-cov services/core-control-plane/tests/tools/test_baseline_runner.py` passed 8 cases | The committed artifact remains `synthetic-harness` and `claim_eligible=false`; no no-regression, multiplier, or temporal-holdout outcome claim is supported. |
| Capacity-first graduation decision profile | implemented | `rule-catalog/capacity-graduation-policy.yaml`; `core/capacity/graduation.py`; Freyr-to-Forseti shadow chain; focused controller and agent checks; [issue #351](https://github.com/dotnetpower/fdai/issues/351) | Measured triggers, cost ceilings, rollback topology, and no-authority boundaries are executable as deterministic recommendation policy. Thor ignores the observation-only verdict, so no apply path exists. |
| Event-driven scale-to-zero | deferred | Phase 4 scalability section; [issue #351](https://github.com/dotnetpower/fdai/issues/351) | The reference Core keeps at least one replica. A KEDA lag rule requires measured cold-start, ordering, and zero-event safety evidence. |
| Dedicated vector-store graduation | deferred | Phase 4 scalability section; [issue #351](https://github.com/dotnetpower/fdai/issues/351) | T1 remains on pgvector until measured corpus, recall, or latency triggers justify a reversible migration. |
| AKS and hyperscale-cell runtime | deferred | Phase 4 runtime section; [issue #351](https://github.com/dotnetpower/fdai/issues/351) | Container Apps remains the reference runtime. AKS or cells require an approved profile trigger and runtime-contract parity. |
| Non-Azure provider expansion | deferred | Phase 4 provider section; [issue #351](https://github.com/dotnetpower/fdai/issues/351) | Azure remains the only implemented target until an approved provider and full contract-parity suite exist. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-08-31 | implemented | Made all three measurement jobs opt-in, replaced the shared executor identity with a dedicated minimum-permission measurement identity, and added plan-level assertions for each complete job contract plus root composition and importable entrypoint checks. | `current change`; `infra/modules/measurement-runners/`, root Terraform composition, and `tests/integration/infra/test_measurement_runner_jobs.py`; focused `terraform test`, Terraform validation, and Python checks. | Retain protected scheduled-run receipts under issue #352; no external receipt is claimed by this local transition. |
| 2026-08-30 | implemented | Implemented the capacity-first graduation profile without activating a topology change. One versioned provider-neutral policy and deterministic controller cover scale-to-zero, vector-store, AKS/cell, and non-Azure transitions. Freyr combines capacity evidence with Njord cost evidence, Forseti emits an observation-only judgment, and Thor cannot dispatch it. | `current change`; `capacity-graduation-policy.yaml`; `core/capacity/graduation.py`; focused controller checks passed 7 cases; focused Freyr-Forseti-Thor chain and specialist checks passed 30 cases; ontology/topic checks passed. | Retain exact-revision evidence and complete a reviewed migration ActionType separately before changing any runtime target. |
| 2026-08-29 | in-progress | Replaced the placeholder scope row with bounded Phase 4 areas and reran regression/runner, pattern, model, latency, pgvector, CLI, baseline, and Terraform validation slices. The audit separated pure policy mechanics, partial runner integration, deployment definitions, deferred topology, and unsupported statistical claims. It also corrected the owner to include the optional operational-promotion runner. | `current change`; exact commands and outcomes are recorded in the scope rows: 24, 10, 10, 8, 14 with 5 live skips, 17, and 8 Python cases; Terraform validation passed and the module had no tests. | Complete runner integration and retain claim-eligible Azure evidence before any Phase 4 exit claim. |
| 2026-08-24 | in-progress | Migrated the legacy status into the delegated ledger without reconstructing earlier provenance. | current change; preserved owner status from `docs/roadmap/phases/phase-4-scale.md`. | Replace the legacy summary with bounded evidence-backed scope rows and observable exits. |

### Remaining work

- [x] Replace the migrated placeholder scope row with bounded rows and rerun all focused local validation slices.
- [ ] Bind temporal holdout, model-swap, and latency policies into durable measured runners under [issue #353](https://github.com/dotnetpower/fdai/issues/353), then pass direct scenario-replayer, PostgreSQL-growth, restart, duplicate, stale, and rollback tests.
- [x] Add Terraform plan tests for all three measurement jobs under [issue #354](https://github.com/dotnetpower/fdai/issues/354).
- [ ] Retain protected scheduled-run receipts for all enabled measurement jobs under [issue #352](https://github.com/dotnetpower/fdai/issues/352).
- [ ] Retain a claim-eligible exact-revision Azure baseline/treatment cohort with statistical guard and multiplier evidence under [issue #352](https://github.com/dotnetpower/fdai/issues/352).
- [x] Approve the capacity-first measured graduation triggers, cost ceilings, rollback topology, and no-authority boundaries under [issue #351](https://github.com/dotnetpower/fdai/issues/351).
- [ ] Retain the exact-revision evidence required by each approved trigger and complete a separately reviewed migration before changing scale-to-zero, vector-store, AKS/cell, or provider topology.
