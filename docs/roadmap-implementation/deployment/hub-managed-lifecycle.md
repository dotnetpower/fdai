# Hub-Managed Lifecycle implementation ledger

This delivery ledger preserves reviewable implementation scope, append-only transitions,
and resumable work while the roadmap owner remains focused on normative design.

## Implementation status

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| Lifecycle Hub service and Hub PostgreSQL | implemented | `current change`; `lifecycle/hub/src/fdai_lifecycle_hub/`, `lifecycle/hub/tests/`; `FDAI_DATABASE_URL=<loopback> uv run --no-sync pytest lifecycle/hub/tests` passed on SQLite and loopback PostgreSQL; ruff, format, and strict mypy passed | One implementation serves central Hub cells and Target Hubs. Lifecycle I0 runs in shadow mode on loopback with no caller authentication, development keys, a trusted local catalog, and `create_all` schema creation instead of versioned migrations |
| Installation enrollment | not-started | Design only: Enrollment and migration section | Entities start unmanaged and become managed after review |
| Lifecycle agent inside the cluster | not-started | Design only: Architecture section | Installed first, independent of Core, Kubernetes rights in FDAI namespaces only |
| Infrastructure agent on the execution host | not-started | Design only: Architecture section | Reuses the existing exact-plan claim, apply, and verification-only recovery stages |
| Lifecycle Plans, constraints, and envelope checks | in-progress | `current change`; `packages/deployment-cli/src/fdai_deployment_cli/lifecycle_plan.py`, `packages/deployment-cli/src/fdai_deployment_cli/lifecycle_configuration.py`, `packages/deployment-cli/tests/test_lifecycle_plan.py`; focused pytest, ruff, format, and mypy checks | Pure local shadow-only checks only. No Hub service, installation agent, apply path, or receipt wiring exists |
| Plan authentication, replay rejection, and key lifecycle | in-progress | `current change`; `packages/deployment-cli/src/fdai_deployment_cli/lifecycle_plan.py`, `packages/deployment-cli/tests/test_lifecycle_plan.py`; focused pytest, ruff, format, and mypy checks | Admission verifies the injected signature over canonical Plan bytes for `plan_id`, `audience`, `hub_key_id`, `hub_key_epoch`, `source_state_digest`, `sequence`, `fencing_generation`, `plan_type`, target Release id and digest, configuration revision digest, Entity set, capability ids, release regions, rollback target Plan id, declared duration, envelope, and expiry. It requires those parsed fields to match the signed bytes, requires `verified is True`, and then rejects stale sequence, wrong audience, stale source-state digest, revoked or inactive Hub key id, Hub key epoch mismatch, fencing mismatch, expired or timezone-less Plan expiry, over-wide envelope, Entity set, duration, capability, or region outside the signed envelope, replayed payload retargeting, and invalid injected signature verification. It commits no key material and grants no authority |
| Local lifecycle authorization receipt and phase fencing | not-started | Design only: Lifecycle Plans section | The receipt stands in for the operator's invocation in the exact-plan stages |
| Dual-slot self-upgrade | not-started | Design only: Lifecycle Plans section | Covers both installation agents and Target Hubs |
| Reported state, drift, and reconciliation | not-started | Design only: Entities and reported state, and Failure, drift, and reconciliation sections | Agents report sub-state of the Core Entity |
| Commands with expiry | not-started | Design only: Commands and overrides section | No command raises authority |
| Operations-loop exclusion of FDAI-owned resources | not-started | Design only: Separation from the operations loop section | Ownership is proven by signed Foundation receipts and Terraform state identity, not by the `fdai:managed=true` tag |
| Workload rendering outside Terraform | not-started | Design only: `docs/roadmap/deployment/hub-managed-lifecycle.md` Workload rendering migration section | Design published with object ownership, render inputs, phases, ownership handoff, rollback, and render parity. No agent renderer, parity test, or handoff exists. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-10-02 | not-started | Adopted the ledger with the accepted ADR-0003 design. No implementation exists. | `current change`; `docs/roadmap/deployment/hub-managed-lifecycle.md`, `docs/roadmap/architecture/decisions/0003-hub-managed-lifecycle-and-operator-governance.md`; design-route, roadmap-tracking, constitution, translation, punctuation, and link checks | Every item below |
| 2026-10-05 | in-progress | Added pure deployment-cli Lifecycle Plan admission and constraint evaluators with deterministic tests. The checks are shadow-only and are not wired into any Hub, installation agent, apply stage, or receipt path. | `current change`; `packages/deployment-cli/src/fdai_deployment_cli/lifecycle_plan.py`, `packages/deployment-cli/src/fdai_deployment_cli/lifecycle_configuration.py`, `packages/deployment-cli/tests/test_lifecycle_plan.py`; `uv run --project packages/deployment-cli python -m pytest -c packages/deployment-cli/pyproject.toml -q --no-cov packages/deployment-cli/tests/test_lifecycle_plan.py`; `uv run --project packages/deployment-cli ruff check packages/deployment-cli/src/fdai_deployment_cli/lifecycle_plan.py packages/deployment-cli/src/fdai_deployment_cli/lifecycle_configuration.py packages/deployment-cli/tests/test_lifecycle_plan.py`; `uv run --project packages/deployment-cli ruff format --check packages/deployment-cli/src/fdai_deployment_cli/lifecycle_plan.py packages/deployment-cli/src/fdai_deployment_cli/lifecycle_configuration.py packages/deployment-cli/tests/test_lifecycle_plan.py`; `uv run --project packages/deployment-cli mypy --strict packages/deployment-cli/src/fdai_deployment_cli/lifecycle_plan.py packages/deployment-cli/src/fdai_deployment_cli/lifecycle_configuration.py` | Hub service, enrollment, lifecycle agents, exact-plan wiring, authorization receipts, drift reconciliation, commands, operations-loop exclusion, workload rendering migration, and governed runtime receipts remain open |
| 2026-10-07 | not-started | Published the workload rendering migration design for #1946: object ownership between the lifecycle agent and the infrastructure agent, three signed render inputs, Plan phases including the schema-expand Job, an ownership handoff through `removed` and `import` blocks in exact plans, rollback, and a render parity check. No implementation exists. | `current change`; `docs/roadmap/deployment/hub-managed-lifecycle.md` Workload rendering migration section; `infra/runtimes/aks/workloads/main.tf`, `infra/runtimes/aks/workloads/browser_gateway.tf`, and `packages/deployment-cli/src/fdai_deployment_cli/standalone_host.py` reviewed as the current rendering source; design-route, roadmap-tracking, translation, punctuation, and link checks | Agent renderer and workload template, render parity test, schema-expand Job, ownership handoff and rollback, and the migration identity's database role remain open |
| 2026-10-07 | not-started | Recorded the owner decisions on the design's two open questions: the schema-expand Job runs under a dedicated migration identity that reuses today's Key Vault database secret in the MVP, and the Terraform workloads root converges on agent-rendered manifests after the MVP is validated. No implementation exists. | `current change`; `docs/roadmap/deployment/hub-managed-lifecycle.md` Decisions on earlier open questions section; `packages/deployment-cli/src/fdai_deployment_cli/standalone_host.py` reviewed for the current migration secret; translation, punctuation, link, and roadmap-tracking checks | Agent renderer and workload template, render parity test, schema-expand Job, ownership handoff and rollback, the narrowed migration database role, and single-renderer convergence remain open |
| 2026-10-07 | not-started | Corrected the migration identity decision: today's migration secret holds the server administrator login, and migrations create service roles and backfill data, so a role without data access isn't achievable. The later target is a dedicated migration database role with only the privileges migrations need. | `current change`; `docs/roadmap/deployment/hub-managed-lifecycle.md` Decisions on earlier open questions section; `infra/modules/state-store/postgres-flex/outputs.tf`, `alembic/versions/`, and `service-migrations/branches/` reviewed; translation, punctuation, link, and roadmap-tracking checks | Agent renderer and workload template, render parity test, schema-expand Job, ownership handoff and rollback, the dedicated migration database role, and single-renderer convergence remain open |
| 2026-10-07 | not-started | Closed gaps found by checking the design against the current rendering code: no Executor Kubernetes-effect role in the FDAI namespace on the Hub path, the autoscaler owns replicas, the schema-expand Job uses the Core image and also materializes catalogs, the deployment CLI refuses legacy workload commands after the handoff, one-shot Jobs derive protected template digests from the render receipt, and parity checks external Service selectors. Recorded three open questions. | `current change`; `docs/roadmap/deployment/hub-managed-lifecycle.md` Workload rendering migration section; `infra/runtimes/aks/workloads/main.tf`, `packages/deployment-cli/src/fdai_deployment_cli/aks_workload_jobs.py`, `packages/deployment-cli/src/fdai_deployment_cli/standalone_host.py`, and `services/core-control-plane/docker/Dockerfile` reviewed; translation, punctuation, link, and roadmap-tracking checks | Agent renderer and workload template, render parity test, schema-expand Job, ownership handoff and rollback, the Executor role, autoscaler, legacy-command, and protected-template tests, the dedicated migration database role, single-renderer convergence, and three open questions remain open |
| 2026-10-07 | not-started | Corrected the ownership handoff for a Terraform constraint: a `removed` block addresses a whole resource without instance keys and requires its resource block to be absent, so the handoff first splits internal and external Services with `moved` blocks and the Release ships a Hub variant of the workloads root. Added the registry login server and topic names to the installation binding and recorded five implementation follow-ups. | `current change`; `docs/roadmap/deployment/hub-managed-lifecycle.md` Ownership handoff section; Terraform v1.9.8 `website/docs/language/resources/syntax.mdx` on `removed` blocks; `infra/runtimes/aks/workloads/main.tf` and `packages/deployment-cli/src/fdai_deployment_cli/standalone_host.py` reviewed; translation, punctuation, link, and roadmap-tracking checks | Agent renderer and workload template, render parity test, schema-expand Job, Service split and Hub variant root, ownership handoff and rollback, pruning, Console publication, agent RBAC, the Executor role, autoscaler, legacy-command, and receipt-based check tests, the dedicated migration database role, single-renderer convergence, and three open questions remain open |
| 2026-10-07 | not-started | Closed gaps from an independent design review against the code: schema expand runs only expand-classified revisions under one installation-wide migration lease, an infrastructure cleanup phase removes infrastructure only after dropped workloads are gone, a Hub ownership marker blocks every full-workloads-root entry point, adoption is per object and resumable, and rollback releases the agent before importing. | `current change`; `docs/roadmap/deployment/hub-managed-lifecycle.md` Phases and Ownership handoff sections; `service-migrations/branches/core-control-plane/versions/20260912_core_retire_resource_change_receipts.py`, `alembic/env.py`, `service-migrations/runtime/env.py`, `scripts/deployment/local/materialize-authoritative-catalogs.py`, `packages/deployment-cli/src/fdai_deployment_cli/standalone_application.py`, and `infra/runtimes/aks/workloads/main.tf` reviewed; translation, punctuation, link, and roadmap-tracking checks | Implementation of the whole migration design, migration classification and lease, Hub ownership marker, adoption receipts, infrastructure cleanup, and the earlier follow-ups and open questions remain open |
| 2026-10-07 | not-started | Narrowed migration classification to revisions added after an installation's enrollment baseline, and recorded that Kubernetes ActionTypes against FDAI's own workloads aren't available on the Hub path because the Executor holds no role in the FDAI namespace. | `current change`; `docs/roadmap/deployment/hub-managed-lifecycle.md` Object ownership and Phases sections; `services/core-control-plane/src/fdai/runtime/delivery.py` and `docs/roadmap/deployment/runtime-deployment-profiles.md` reviewed for the Executor Kubernetes binding; translation, punctuation, link, and roadmap-tracking checks | Implementation of the whole migration design and the earlier follow-ups and open questions remain open |
| 2026-10-07 | implemented | Added the Lifecycle Hub (#1949) under `lifecycle/hub/`, instead of the #1948 memo's `services/lifecycle-hub/`, because the Hub isn't one of the governed installation services. It plans from the oldest managed entity, picks the newest Release that passes every Release-specific check in `fdai-deployment-cli`, waits on a closed window or suppression without falling back, keeps an unchanged open Plan, signs with an Ed25519 development key, and serves the I0 agent API. The SQLAlchemy model follows the design's Hub data model: installation, entity, entity reported state, Plan, Plan events, constraint results per evaluation, execution reports, and a hash-chained audit. The Hub computes configuration digests from content and rejects an execution report whose `exact_plan_digest` doesn't match the stored Plan bytes. Added public `parse_runtime_release_manifest` and `compare_release_ids` to `runtime_release.py` without changing `load_runtime_release` behavior. | `current change`; `lifecycle/hub/`, `packages/deployment-cli/src/fdai_deployment_cli/runtime_release.py`, `packages/deployment-cli/tests/test_runtime_release.py`, root `pyproject.toml`, `scripts/quality/ci/resolve_test_scope.py`; `FDAI_DATABASE_URL=<loopback> uv run --no-sync pytest lifecycle/hub/tests packages/deployment-cli/tests/test_runtime_release.py packages/deployment-cli/tests/test_lifecycle_plan.py` passed; ruff, format, and strict mypy passed | Constraint results attach to an evaluation, not a `plan_id`, because a waiting or blocked recompute issues no Plan. Entities aren't revisioned yet. Versioned migrations, agent authentication, enrollment approval (#1950), and catalog signatures remain |
| 2026-10-07 | implemented | Hardened the Lifecycle Hub (#1949) input boundary: reported state is rejected unless every entity release id is canonical SemVer, health is one of four known values, the state digest is 64 lowercase hex characters, and the observation time is timezone-aware. Added `is_release_id` to `runtime_release.py`. Gave the Hub its own uv lock so `uv run fdai-lifecycle-hub` works from `lifecycle/hub/`, and added static sample Releases and an installation under `lifecycle/hub/samples/` with a README walkthrough. | `current change`; `lifecycle/hub/`, `packages/deployment-cli/src/fdai_deployment_cli/runtime_release.py`, `docs/roadmap/deployment/provisioning-execution-profiles.md`, `docs/roadmap/deployment/developer-workflow-assurance.md`; `FDAI_DATABASE_URL=<loopback> uv run --no-sync pytest -c pyproject.toml lifecycle/hub/tests packages/deployment-cli/tests/test_runtime_release.py packages/deployment-cli/tests/test_lifecycle_plan.py` passed (293); the README walkthrough ran end to end against SQLite | The agent must send the state digest as 64 hex characters and `exact_plan_digest` as `sha256:` plus 64 hex characters |
| 2026-10-08 | implemented | Added Lifecycle Hub suppressions as a follow-up to #1969: `suppress` and `unsuppress` commands accept `installation`, `entity:<id>`, or `plan:<type>` scopes, an active suppression withdraws the open Plan at once, and lifting it lets the next recompute issue a new Plan. Corrected the design's Hub data model to record the delivered `plan_evaluation` table and evaluation-keyed constraint results, and replaced its outdated statement that nothing is implemented. | `current change`; `lifecycle/hub/src/fdai_lifecycle_hub/`, `lifecycle/hub/tests/test_suppressions.py`, `docs/roadmap/deployment/hub-managed-lifecycle.md`; `FDAI_DATABASE_URL=<loopback> uv run --no-sync pytest -c pyproject.toml lifecycle/hub/tests` passed (97); the README walkthrough ran end to end against SQLite | Suppressions are stored on the installation without an actor; the revocable `lifecycle_command` record arrives with Hub commands |

### Remaining work

- [x] Add a Hub service with its PostgreSQL schema, and record a passing focused test that computes a
  Lifecycle Plan from a channel subscription, version range, configuration revision, and
  constraints with no Azure credential in its environment, in
  `lifecycle/hub/tests/test_no_azure_credentials.py` and `lifecycle/hub/tests/test_planning.py`.
- [ ] Replace the Hub's `create_all` schema creation with versioned migrations, and authenticate
  agent callers before the Hub API binds to anything other than loopback.
- [ ] Add installation enrollment, and record a test in which an unapproved registration receives
  no Plan and an approved one starts with unmanaged Entities only.
- [ ] Add the lifecycle agent, and record tests that prove it applies only signed Release images,
  refuses a change outside the Plan envelope, and holds Kubernetes rights in FDAI namespaces only.
- [ ] Add the infrastructure agent, and record a test in which the deletion or replacement of an
  existing Azure resource is held for confirmation while an in-envelope change applies through the
  existing exact-plan coordinator.
- [x] Record pure constraint tests for maintenance and suppression windows, version ranges, schema
  ranges, artifact availability, override coverage, data residency, and recall in
  `packages/deployment-cli/tests/test_lifecycle_plan.py`; these tests exercise shadow-only local
  evaluators and do not create a Hub, agent, apply path, or receipt.
- [x] Record pure Plan admission tests that reject a stale sequence, a wrong audience, a revoked
  Hub key, and an envelope wider than the locally derived maximum in
  `packages/deployment-cli/tests/test_lifecycle_plan.py`; these tests use an injected fake
  verifier and commit no key material.
- [ ] Record a test in which an automatic apply runs only under a local lifecycle authorization
  receipt bound to the exact plan digest, and a later phase waits for the earlier phase receipt.
- [ ] Record dual-slot self-upgrade tests for both agents and a Target Hub, including rollback to
  the old slot after a failed health check.
- [ ] Record a drift test in which a manual Deployment change produces a reconciliation Plan in the
  next matching window.
- [ ] Record a command test in which a break-glass change is reconciled to the approved revision at
  expiry and an authority-raising command is rejected.
- [ ] Record a risk-gate test that denies an operations-loop action targeting a resource with a
  signed Foundation ownership receipt, and a test in which a manually tagged customer resource
  doesn't become an FDAI-owned Entity.
- [x] Publish a migration design that moves workload rendering from the Terraform application stage
  to the lifecycle agent, with rollback, before any Hub-managed installation exists. Published in
  the Workload rendering migration section of `docs/roadmap/deployment/hub-managed-lifecycle.md`
  for #1946.
- [ ] Add the Release workload template and the lifecycle agent renderer, and record a render parity
  test in which the Terraform workloads root and the agent produce equal objects for the full input
  matrix, including protected CronJob template digests and external Service selectors that match the
  rendered pod labels.
- [ ] Add the installation binding that the infrastructure agent writes from its Terraform outputs,
  and record a test in which the renderer rejects an unknown key and any value source other than a
  literal, a configuration key, or a binding key.
- [ ] Add the schema-expand migration Job on the Core image with its dedicated migration
  ServiceAccount and managed identity, and record tests in which the Job runs the legacy migrations,
  the ordered service-owned migrations, and the authoritative catalog materialization, and no
  workload switches before the Job receipt exists.
- [ ] Record a test in which a Hub-managed installation binds no Executor Kubernetes-effect role in
  the FDAI namespace while Executor scale targets in other namespaces stay bound.
- [ ] Record a test in which the agent omits `spec.replicas` for a workload with a
  HorizontalPodAutoscaler and maps replica overrides to the autoscaler bounds.
- [ ] Record a local Hub ownership marker at handoff, and record a test in which every deployment CLI
  entry point that would plan the full workloads root, including the ordinary application stage,
  refuses to run or uses the Hub variant.
- [ ] Classify every legacy and service-owned migration revision added after an installation's
  enrollment baseline as expand or contract in the Release, and record tests in which the schema-expand Job rejects a dropping or renaming revision
  and runs under one installation-wide migration lease across all three steps and its receipt.
- [ ] Record handoff tests for per-object adoption receipts with UID, resource version, and render
  digest, forced conflicts only on Terraform-owned fields, resumption after interruption, and a
  rollback that releases the agent's reconciliation lease before any `import` plan.
- [ ] Record a test in which a Release that drops an external workload removes its external Service,
  API Management route, role grants, and federated identity credential only in the infrastructure
  cleanup phase, after workload absence readback.
- [ ] Record a test in which one-shot catalog review and initial inventory Jobs and the workload
  readiness contracts on the Hub path derive their expected values from the agent render receipt
  instead of Terraform input.
- [ ] Split the workloads root's Service resource into internal and external resources with `moved`
  blocks, ship the Hub variant of the workloads root with `removed` blocks in the Release, and record
  a zero-change plan for the split on every installation path.
- [ ] Record a test in which the agent prunes objects that carry its ownership label but are absent
  from the new render, and the infrastructure agent removes a dropped workload's federated identity
  credential only after its pods are gone.
- [ ] Assign Console static content publication to the infrastructure agent, and record a test in
  which a Hub-managed upgrade publishes the Release's Console bundle.
- [ ] Record a test in which the infrastructure agent grants the lifecycle agent's own Kubernetes
  role and the lifecycle agent can't create or change any role binding.
- [ ] Decide which component runs Trial activation, the initial inventory, and catalog review after
  a Hub-managed workload phase, and record the decision in the Hub-Managed Lifecycle design.
- [ ] Decide how the infrastructure agent keeps running with the execution host's optional daily
  auto-shutdown, and which agent owns the in-cluster PostgreSQL namespace for `postgres-aks`.
- [ ] Move database object ownership from the server administrator to a dedicated migration
  database role, switch the migration identity to that role, and record a grant readback in which
  the role holds only the privileges migrations need and no workload uses it.
- [ ] After the MVP is validated, make the Terraform workloads root apply agent-rendered manifests,
  and record that every installation path renders through one renderer before retiring the parity
  test.
- [ ] Record an ownership handoff test in which shadow parity passes, a `removed` exact plan shows no
  destroy or update, server-side apply adoption renders zero changes, and an `import` rollback plans
  zero changes without recreating any running object.
- [ ] Retain one governed connected-installation receipt and one offline Target Hub receipt that
  show an automatic upgrade, independent readback, and a second zero-change plan.
