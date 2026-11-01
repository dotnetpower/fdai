# Cost Model (Illustrative) implementation ledger

This delivery ledger preserves reviewable implementation scope, append-only transitions,
and resumable work while the roadmap owner remains focused on normative design.

## Implementation status

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| Minimum Azure inventory model | implemented | `infra/`; `config/cost-model-sku-reconciliation.json`; `scripts/quality/architecture/check-cost-model-reconciliation.py`; `tests/integration/scripts/test_cost_model_reconciliation.py` (`2 passed`) | Terraform inventory resources, SKUs, replica floors, storage, retention, and optional capabilities are exported and reconciled to the deterministic Terraform inventory digest. |
| LLM usage metering and budget enforcement | implemented | `services/core-control-plane/src/fdai/core/metering/`; `services/core-control-plane/tests/core/metering/` | Focused tests cover records, usage, pricing inputs, aggregation, sink behavior, and prospective budget denial. This proves budget mechanics, not an Azure invoice. |
| Current SKU and quantity reconciliation | implemented | `config/cost-model-sku-reconciliation.json`; `scripts/quality/architecture/check-cost-model-reconciliation.py`; `tests/integration/scripts/test_cost_model_reconciliation.py` (`2 passed`) | All 10 cost-model rows reconcile to the exact Terraform inventory digest with explicit SKUs, replica floors, storage, retention, and optional capability bindings. |
| Price confirmation and deployment baseline | not-started | [Open decisions](../../roadmap/interfaces/cost-model.md#open-decisions) | No governed `pricing.confirmed_at`, Retail Prices or Calculator receipt, measured billing baseline, or variance alert evidence is retained. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-08-14 | in-progress | Adopted the implementation ledger; earlier provenance was not reconstructed. | `current change`; current infrastructure and metering evidence listed in the scope table. | Reconcile the current plan, confirm prices, and retain a measured deployment baseline. |
| 2026-08-25 | implemented | Removed the retired legacy-root replica input and aligned this estimate with the independent Core service scaling contract. | `current change`; `infra/services/core-control-plane/variables.tf`; Terraform validation and TFLint. | Reconcile the current plan, confirm prices, and retain a measured deployment baseline. |
| 2026-11-01 | implemented | Exported the enabled Terraform resources, SKUs, replica floors, storage, retention, and optional capabilities into `config/cost-model-sku-reconciliation.json` and added `check-cost-model-reconciliation.py` to verify all 10 cost rows against the exact Terraform inventory digest; migrated the owner status to this authoritative ledger. | `current change`; `config/cost-model-sku-reconciliation.json`; `scripts/quality/architecture/check-cost-model-reconciliation.py`; `tests/integration/scripts/test_cost_model_reconciliation.py` (`2 passed`). | Live price confirmation (`pricing.confirmed_at`) and measured billing baseline remain open. |

### Remaining work

- [x] Export the enabled resources, SKUs, replica floors, storage, retention, and optional capabilities from a reviewed Terraform plan and reconcile every cost row to that exact plan digest (`config/cost-model-sku-reconciliation.json`; `check-cost-model-reconciliation.py`; `test_cost_model_reconciliation.py`: `2 passed`).
- [ ] Record a dated `pricing.confirmed_at` receipt from the Azure Pricing Calculator or Retail Prices API for the selected region and currency, including assumptions and excluded discounts.
- [ ] Compare the reconciled estimate with one measured billing window and define an observable variance alert before replacing the historical envelope with a current estimate.
- [ ] Resolve the tier, graduation-trigger, model-budget, commitment, and confirmation-cadence decisions below with reviewed deployment evidence.
