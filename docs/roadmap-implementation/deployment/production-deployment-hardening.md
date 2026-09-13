# Production deployment hardening implementation ledger

This delivery ledger preserves reviewable implementation scope, append-only transitions,
and resumable work while the roadmap owner remains focused on normative design.

## Implementation status

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| Production plan gates and environment knobs | implemented | `infra/production-gates.tf`; `infra/envs/{staging,prod}.tfvars.example`; Terraform configuration tests | Missing signed image, private network, durability, monitoring, or cost inputs block a production plan. |
| Manual production execution boundary | implemented | deployment CLI manual profile; standalone managed-host modules; focused package tests | Public workflow dispatch is removed. Operational production evidence remains open. |
| Credential-free infrastructure and drift guards | implemented | `.github/workflows/ci.yml`; `.github/workflows/infra-drift.yml`; CI contract tests | Required CI owns credential-free validation and path-scoped Terraform security scanning. Drift checks cover all declared state roots and fail closed on a missing, unreadable, or changed root. |
| Scenario-lab runner tool bootstrap | implemented | `.github/workflows/sre-demo-lab.yml`; focused scenario-lab and CI contract checks | The candidate runner receives checksum-pinned Helm and kubelogin in temporary storage before the workflow validates required commands. No Azure resource or runner image changes occur. |
| Exact-revision protected production apply evidence | in-progress | [Deploy and Onboard](deploy-and-onboard.md#implementation-status) | Code and plan guards exist, but this owner document does not retain one current production apply proving every control together. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-09-12 | implemented | Restricted production tenant execution to the standalone manual managed host and removed public workflow dispatch from the deployment CLI. | `current change`; deployment CLI contracts and focused package tests | Retain a production plan and apply receipt from the manual host before advancing validation state. |
| 2026-09-08 | implemented | Added checksum-pinned temporary Helm installation after the plan-only workflow failed on a candidate runner without Helm. | `current change`; 7 scenario-lab tests, 54 CI/workflow contract tests, actionlint, public archive checksum verification, and the complete Operator surface gate passed. | Reconcile and commit the shared branch before observing a new plan-only run; do not dispatch apply. |
| 2026-09-05 | implemented | Moved infrastructure validation and security scanning under the single required CI result while retaining path-scoped scanner execution and scenario-lab validation. | `current change`; CI workflow, scope resolver, and focused CI and scenario-lab contracts. | Retain the protected production and drift evidence required below. |
| 2026-08-21 | in-progress | Moved the existing production hardening controls into a focused owner document without changing infrastructure behavior. | `current change`; document-size, translation, route, and link checks. | Retain one exact-revision protected production plan and apply receipt covering every required control. |
| 2026-08-25 | implemented | Required every exact service apply to start from a healthy active revision and retain one inactive revision, while allowing only the one-time legacy retention hardening from `0` to `1`. | `current change`; shared service module, recovery guard, plan guard, and focused deployment checks. | Retain one protected production apply and verified rollback receipt before raising exact-revision evidence to `validated`. |

### Remaining work

- [ ] Retain an exact-revision protected production plan and apply receipt proving resource locks,
  private networking, PostgreSQL durability, trusted image digest, notifications, monitoring, and
  the cost budget together, including one blocked negative plan.
