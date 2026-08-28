# Subscription Genesis Provisioning implementation ledger

This delivery ledger preserves reviewable implementation scope, append-only transitions, and
resumable work while the roadmap owner remains focused on the normative zero-to-ready lifecycle.

## Implementation status

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| Packaged `fdaictl` subscription orchestration | not-started | `pyproject.toml`; [Installable Deployment CLI](../../roadmap/deployment/installable-deployment-cli.md) | No distribution currently registers the canonical command namespace, manifest compiler, or durable provisioning state machine. |
| Private foundation and protected exact apply | implemented | `infra/bootstrap/`; `.github/workflows/deploy-dev.yml`; existing focused bootstrap and workflow checks | The low-level mechanisms exist but are not composed behind the planned CLI lifecycle. |
| Database migrations and catalog projection | in-progress | `bootstrap-service-migrations.sh`; service migrations; Operator migration and catalog Jobs | Ordered mechanisms exist, but one bootstrap manifest and pre-runtime semantic readiness gate are missing. |
| Model resolution and capacity provisioning | in-progress | `llm-registry.yaml`; resolver and assessment modules; Azure OpenAI and Foundry Terraform modules | Requested capacity, quota-aware reduction, and readback exist in parts. Minimum capacity, utilization headroom, deterministic region ranking, and throughput acceptance are missing. |
| Initial inventory and observable progress | in-progress | Inventory Job, complete-generation coordinator, provider coverage manifest, and simple Console provisioning stream consumer | Complete promotion exists. Durable onboarding dispatch, total-aware progress, replay, and active-generation closure are missing. |
| Governed new-subscription validation | not-started | Acceptance criteria in the owner document | No retained empty-subscription zero-to-ready and idempotent-rerun receipt exists. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-08-28 | in-progress | Adopted the implementation ledger without reconstructing earlier provenance and defined the dependency-ordered subscription genesis plan. | `current change`; owner document, current source paths, and focused documentation checks | Deliver P0-P7 and retain one governed new-subscription receipt. |
| 2026-08-29 | in-progress | Revised the plan after a separate 40-item adversarial assurance review and split cross-stage gates into a focused owner. | `current change`; subscription genesis provisioning and assurance owners plus their implementation ledgers | Implement G01-G40 and retain the governed acceptance receipts. |

### Remaining work

- [ ] Complete P0 and P1 with source-install and isolated-wheel tests proving no-mutation inspection,
  profile safety, current-state classification, stable JSON, and redaction.
- [ ] Complete P2 and P3 with exact-plan, wrong-target, approval, expiry, interruption,
  foundation-state reconstruction, apply-claim-safe resume, conflict, import, resource-manifest
  reconciliation, and zero-unrelated-destroy tests.
- [ ] Complete P4 with a versioned database bootstrap manifest and runtime-principal readback of
  migration heads, roles, extensions, ontology release, catalogs, defaults, and shadow-only state.
- [ ] Complete P5 with quota fixtures and live-plan tests for the nonempty required baseline,
  workload-derived minimum capacity, target headroom, reserve, region ranking, degraded acceptance,
  private keyless bindings, and quantitative probes.
- [ ] Complete P6 with run-level totals, full-subscription object coverage, monotonic durable
  progress, reconnect replay, changing-denominator, no-progress, partial-generation, promotion,
  CLI, Operator, and Console tests.
- [ ] Complete P7 and retain an exact-revision protected new-subscription receipt plus a second-run
  no-change receipt before marking the lifecycle validated.
- [ ] Implement the cross-stage G01-G40 controls tracked by the
  [assurance ledger](subscription-genesis-assurance.md) before claiming zero-to-ready validation.
