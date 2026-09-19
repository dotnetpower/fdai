# Existing Container Apps Service Update Implementation

This ledger tracks implementation and operational evidence for the existing-development Operator
service update. The canonical design remains in [Existing Container Apps Service Update](../../roadmap/deployment/existing-container-apps-service-update.md).

## Implementation status

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| Live input recovery | implemented | `recover_operator_tfvars.py`; focused recovery tests | ARM and platform state reconstruct current Operator inputs without reading secret values and fail closed on binding drift. |
| Platform secret prerequisite | implemented | `infra/operator-platform-prerequisite`; `manual_operator_platform.py`; focused exact-address, plan-scope, and drift tests; Terraform format and validation; canonical provider lock match; Ruff | The focused root uses the canonical counted addresses in the existing platform backend, admits only three creates, claims before apply, and verifies the secret reference and exact role assignment. Ambiguous apply remains state-forward and cannot repeat automatically. |
| Exact plan, approval, and claim | implemented | `manual_operator_update.py`; `manual_operator_update_contract.py`; focused coordinator and transition tests; Ruff | Public attestation, private planning, Entra human approval, UAMI execution, saved-plan validation, and pre-effect claim are separate stages. The manual boundary verifies only the exact Operator pseudonym key secret and environment adoption, normalizes that addition, and then reuses the unchanged shared service guard for the image update. |
| Effect verification and rollback | implemented | `manual_operator_update.py`; claim-order and failed-apply regressions | Candidate success requires a new ready revision. Failure copies and verifies the captured previous revision. |
| Existing dev rollout | in-progress | Issue #1342 and current source implementation | Protected merge, exact platform and service plans, apply, service health, peer readback, and authenticated Dashboard evidence remain open. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-09-19 | implemented | Added the manual existing-host Operator exact-plan path after the retired workflow transport left no admissible service update coordinator. | `current change`; task-owned scripts and 21 focused tests; Ruff. | Merge the source and retain the exact dev apply and authenticated Dashboard evidence. |

### Remaining work

- [ ] Merge the implementation through protected main with required checks passing.
- [ ] Apply the exact existing-development platform secret prerequisite and Operator saved plan
  from the eligible host; retain deployed image, healthy revision, and unchanged peer evidence.
- [ ] Verify service health and the authenticated Console Dashboard without the autonomy schema
  error, then link the repository-safe evidence under issue #1342.
