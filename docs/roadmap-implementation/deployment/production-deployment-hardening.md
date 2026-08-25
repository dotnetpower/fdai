# Production deployment hardening implementation ledger

This delivery ledger preserves reviewable implementation scope, append-only transitions,
and resumable work while the roadmap owner remains focused on normative design.

## Implementation status

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| Production plan gates and environment knobs | implemented | `infra/production-gates.tf`; `infra/envs/{staging,prod}.tfvars.example`; Terraform configuration tests | Missing signed image, private network, durability, monitoring, or cost inputs block a production plan. |
| Credential-free infrastructure and drift guards | implemented | `.github/workflows/infra-lint.yml`; `.github/workflows/infra-drift.yml`; CI contract tests | The checks cover all declared state roots and fail closed on a missing, unreadable, or changed root. |
| Exact-revision protected production apply evidence | in-progress | [Deploy and Onboard](deploy-and-onboard.md#implementation-status) | Code and plan guards exist, but this owner document does not retain one current production apply proving every control together. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-08-21 | in-progress | Moved the existing production hardening controls into a focused owner document without changing infrastructure behavior. | `current change`; document-size, translation, route, and link checks. | Retain one exact-revision protected production plan and apply receipt covering every required control. |
| 2026-08-25 | implemented | Required every exact service apply to start from a healthy active revision and retain one inactive revision, while allowing only the one-time legacy retention hardening from `0` to `1`. | `current change`; shared service module, recovery guard, plan guard, and focused deployment checks. | Retain one protected production apply and verified rollback receipt before raising exact-revision evidence to `validated`. |

### Remaining work

- [ ] Retain an exact-revision protected production plan and apply receipt proving resource locks,
  private networking, PostgreSQL durability, trusted image digest, notifications, monitoring, and
  the cost budget together, including one blocked negative plan.
