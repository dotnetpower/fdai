# Subscription Genesis Provisioning implementation ledger

This delivery ledger preserves reviewable implementation scope, append-only transitions, and
resumable work while the roadmap owner remains focused on the normative zero-to-ready lifecycle.

## Implementation status

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| Packaged `fdaictl` subscription orchestration | implemented | `packages/deployment-cli`; focused package and productization tests | The installable distribution provides version, doctor, profile init/inspection, artifact verification, manifest compilation, status, and no-mutation guided rehearsal. Live protected dispatch remains open. |
| Private foundation and protected exact apply | in-progress | `infra/bootstrap/`; `.github/workflows/deploy-dev.yml`; deployment CLI manifest and resume contracts | Low-level apply and local orchestration contracts exist. Live foundation dispatch, remote state migration, run lease, and receipts remain open. |
| Database migrations and catalog projection | in-progress | `bootstrap-service-migrations.sh`; service migrations; Operator migration and catalog Jobs | Ordered mechanisms exist, but one bootstrap manifest and pre-runtime semantic readiness gate are missing. |
| Model resolution and capacity provisioning | in-progress | Resolver and Terraform modules; `fdai_deployment_cli.capacity`; focused capacity tests | Workload-derived TPM, sharing aggregation, reserve, current allocation, and missing-quota rejection are implemented locally. Azure quota race checks and quantitative live probes remain open. |
| Initial inventory and observable progress | in-progress | Inventory Job and coverage manifest; `fdai_deployment_cli.progress`; focused monotonicity and closure tests | Run totals and full-subscription independent closure are implemented locally. Durable provider progress publication and Console integration remain open. |
| Governed new-subscription validation | in-progress | `fdai_deployment_cli.simulation`; interruption and idempotent-rerun tests | The complete stage chain rehearses without Azure. Governed empty-subscription and rollback receipts remain open. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-08-30 | implemented | Refused resource-type subset promotion before it can replace the global active inventory snapshot or ontology projection, while preserving full-scope genesis collection. | `current change`; inventory source construction, sync coordinator, and focused subset-promotion checks | Complete durable provider progress publication and retain protected full-subscription evidence. |
| 2026-08-28 | in-progress | Adopted the implementation ledger without reconstructing earlier provenance and defined the dependency-ordered subscription genesis plan. | `current change`; owner document, current source paths, and focused documentation checks | Deliver P0-P7 and retain one governed new-subscription receipt. |
| 2026-08-29 | in-progress | Revised the plan after a separate 40-item adversarial assurance review and split cross-stage gates into a focused owner. | `current change`; subscription genesis provisioning and assurance owners plus their implementation ledgers | Implement G01-G40 and retain the governed acceptance receipts. |
| 2026-08-29 | implemented | Added the independent deployment CLI distribution and deterministic pre-login contracts for profiles, manifests, journals, model capacity, progress, inventory closure, signed artifacts, licenses, and full-stage rehearsal. | `current change`; `packages/deployment-cli`; focused package and productization tests passed 28 cases; Ruff and strict mypy passed | Complete protected Azure adapters, remote evidence, and user-facing progress integration. |
| 2026-08-29 | implemented | Completed the pre-login implementation and 75-round hardening campaign, including target-bound planning, concrete resource manifests, required/optional model capacity, signed artifact snapshots, and shipped-wheel offline execution. | Campaign commits from `dd28b64d9`; final Medium-or-higher review found none; successful network-isolated air-gap drill | Log in to the new subscription, run read-only target inspection, then collect protected plan/apply and live inventory/model evidence. |

### Remaining work

- [ ] Complete P1 Azure current-state classification and live preflight after the implemented
  source-install, profile safety, stable JSON, and no-mutation local inspection contracts.
- [ ] Complete P2 and P3 with exact-plan, wrong-target, approval, expiry, interruption,
  foundation-state reconstruction, apply-claim-safe resume, conflict, import, resource-manifest
  reconciliation, and zero-unrelated-destroy tests.
- [ ] Complete P4 with a versioned database bootstrap manifest and runtime-principal readback of
  migration heads, roles, extensions, ontology release, catalogs, defaults, and shadow-only state.
- [ ] Complete P5 Azure adapters for region ranking, quota recheck, private keyless bindings, and
  quantitative live probes on top of the implemented local capacity contract.
- [ ] Complete P6 durable provider progress publication plus Operator and Console integration on
  top of the implemented run totals and full-subscription closure contract.
- [ ] Complete P7 and retain an exact-revision protected new-subscription receipt plus a second-run
  no-change receipt before marking the lifecycle validated.
- [ ] Collect Azure-backed evidence for the controls that require a real subscription, private
  endpoints, managed identities, quota, database readback, and complete inventory observation.
