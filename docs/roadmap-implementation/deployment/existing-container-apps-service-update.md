# Existing Container Apps Service Update Implementation

This ledger tracks implementation and operational evidence for the existing-development Operator
service update. The canonical design remains in [Existing Container Apps Service Update](../../roadmap/deployment/existing-container-apps-service-update.md).

## Implementation status

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| Live input recovery | implemented | `recover_operator_tfvars.py`; focused recovery tests | ARM and platform state reconstruct current Operator inputs without reading secret values and fail closed on binding drift. |
| Platform secret prerequisite | implemented | `infra/operator-platform-prerequisite`; `manual_operator_platform.py`; `drift_contract.py`; focused exact-address, state-recovery, plan-scope, and drift tests; Terraform format and validation; canonical provider lock match; Ruff | The focused root uses the canonical counted addresses in the existing platform backend, admits only three creates, claims before apply, and verifies the secret reference and exact role assignment. It reads the tracked Operator identity directly when an older state lacks the newer root output. Ambiguous apply remains state-forward and cannot repeat automatically. |
| Exact plan, approval, and claim | implemented | `manual_operator_update.py`; `manual_operator_update_contract.py`; focused coordinator and transition tests; Ruff | Public attestation, private planning, Entra human approval, UAMI execution, saved-plan validation, and pre-effect claim are separate stages. The manual boundary verifies only the exact Operator pseudonym key secret and environment adoption, normalizes that addition, and then reuses the unchanged shared service guard for the image update. |
| Effect verification and rollback | implemented | `manual_operator_update.py`; claim-order and failed-apply regressions | Candidate success requires a new ready revision. Failure copies and verifies the captured previous revision. |
| Existing dev rollout | in-progress | Issue #1342 and current source implementation | Protected merge, exact platform and service plans, apply, service health, peer readback, and authenticated Dashboard evidence remain open. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-10-08 | implemented | The platform prerequisite now recovers the exact tracked Key Vault resource id when the legacy state predates the root `key_vault_id` output, matching the existing exact-address Operator identity recovery and never inferring a resource name. | `current change`; blocked prerequisite plan under issue #1886; `manual_operator_platform.py`, `drift_contract.py`, and focused state-recovery tests | Regenerate the exact prerequisite plan, apply it, and retain the Operator root plus scheduled evidence under issue #1886. |
| 2026-10-08 | implemented | The platform prerequisite now recovers the exact tracked legacy Operator principal when the toggle-gated `runtime_identity_bindings.operator` output is absent, without inferring an Azure resource name or widening the three-resource plan. | `current change`; `manual_operator_platform.py`, `drift_contract.py`, and focused manual platform and drift contract tests | Apply the exact prerequisite, reconcile the Operator service root, and retain the scheduled evidence under issue #1886. |
| 2026-10-04 | implemented | The service plan guard and the manual Operator Cost adoption check admit exactly one environment transition: a plain `FDAI_API_AUDIENCE` or `FDAI_CHANNEL_ATTACHMENT_API_AUDIENCE` changing from `api://<client-id>` to that client ID. The reverse direction, another application, a custom App ID URI, and secret-backed bindings still fail as drift. | `current change`; `test_service_deploy.py` and `test_manual_operator_update.py` (272 passed; the new admit cases fail without the change); Ruff; `guard_plan.py` stays within its file-size cap. | Unchanged: retain the exact dev apply and authenticated Dashboard evidence. |
| 2026-10-04 | implemented | Live Operator recovery now canonicalizes a recovered `api://<client-id>` audience to the fdai-api client ID that v2 access tokens carry, so the service-root audience validation from #1893 doesn't block existing installations. Any other value still reaches Terraform and is rejected. | `current change`; `test_recover_operator_tfvars.py` and `test_service_tfvars_materialization.py` (134 passed; the new cases fail without the change); Ruff. | Unchanged: retain the exact dev apply and authenticated Dashboard evidence. |
| 2026-09-19 | implemented | Restored compatibility with the internal host's Python 3.10 runtime without changing plan, approval, claim, apply, or rollback semantics. | `current change`; system Python 3.10 imports passed; 21 focused tests; Ruff check and format passed. | Retain the exact dev apply and authenticated Dashboard evidence. |
| 2026-09-19 | implemented | Added the manual existing-host Operator exact-plan path after the retired workflow transport left no admissible service update coordinator. | `current change`; task-owned scripts and 21 focused tests; Ruff. | Merge the source and retain the exact dev apply and authenticated Dashboard evidence. |

### Remaining work

- [ ] Merge the implementation through protected main with required checks passing.
- [ ] Apply the exact existing-development platform secret prerequisite and Operator saved plan
  from the eligible host; retain deployed image, healthy revision, and unchanged peer evidence.
- [ ] Verify service health and the authenticated Console Dashboard without the autonomy schema
  error, then link the repository-safe evidence under issue #1342.
