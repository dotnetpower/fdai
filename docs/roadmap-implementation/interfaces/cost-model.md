# Cost Model (Illustrative) implementation ledger

This delivery ledger preserves reviewable implementation scope, append-only transitions,
and resumable work while the roadmap owner remains focused on normative design.

## Implementation status

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| Minimum Azure inventory model | in-progress | `infra/`; [Current Terraform inventory reconciliation](../../roadmap/interfaces/cost-model.md#current-terraform-inventory-reconciliation) | Terraform declares the deployable inventory, but the historical price rows are not generated from the current plan. |
| LLM usage metering and budget enforcement | implemented | `services/core-control-plane/src/fdai/core/metering/`; `services/core-control-plane/tests/core/metering/` | Focused tests cover records, usage, pricing inputs, aggregation, sink behavior, and prospective budget denial. This proves budget mechanics, not an Azure invoice. |
| Current SKU and quantity reconciliation | not-started | [Per-resource estimate](../../roadmap/interfaces/cost-model.md#per-resource-estimate) | Rows still say `recalculate from current plan`; no checked-in plan-to-cost reconciliation artifact exists. |
| Price confirmation and deployment baseline | not-started | [Open decisions](../../roadmap/interfaces/cost-model.md#open-decisions) | No governed `pricing.confirmed_at`, Retail Prices or Calculator receipt, measured billing baseline, or variance alert evidence is retained. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-08-14 | in-progress | Adopted the implementation ledger; earlier provenance was not reconstructed. | `current change`; current infrastructure and metering evidence listed in the scope table. | Reconcile the current plan, confirm prices, and retain a measured deployment baseline. |

### Remaining work

- [ ] Export the enabled resources, SKUs, replica floors, storage, retention, and optional capabilities from a reviewed Terraform plan and reconcile every cost row to that exact plan digest.
- [ ] Record a dated `pricing.confirmed_at` receipt from the Azure Pricing Calculator or Retail Prices API for the selected region and currency, including assumptions and excluded discounts.
- [ ] Compare the reconciled estimate with one measured billing window and define an observable variance alert before replacing the historical envelope with a current estimate.
- [ ] Resolve the tier, graduation-trigger, model-budget, commitment, and confirmation-cadence decisions below with reviewed deployment evidence.
