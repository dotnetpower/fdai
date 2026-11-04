# AKS Outbound Connector Deployment Proposals Implementation Ledger

This ledger tracks the documentation ownership split for [AKS Outbound Connector Deployment Proposals](../../roadmap/architecture/aks-outbound-connector-deployment-proposals.md).

## Implementation status

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| Documentation ownership | not-applicable | `current change`; `docs/roadmap/architecture/aks-outbound-connector-deployment-proposals.md` and its Korean pair; document-size and translation checks | This structural split changes no runtime behavior. |
| First informational publication | implemented | `kubernetes_connector_projection.py`, `postgres_notification_delivery.py`; `test_notification_dispatch_plan_missing.py` passed | Only the typed missing-plan condition permits first publication; it grants no installation authority. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-11-04 | implemented | Distinguish an absent first dispatch plan from corrupt plans and storage failures without weakening duplicate-delivery checks. | `current change`; #2917; focused missing-plan regression passed. | Existing installation and live delivery acceptance remain separate. |
| 2026-09-20 | not-applicable | Split one oversized roadmap owner into a focused bilingual companion without changing its contract. | `current change`; `docs/roadmap/architecture/aks-outbound-connector-deployment-proposals.md` and its Korean pair | No runtime implementation work is introduced by this split. |

### Remaining work

- [x] Preserve the moved design content and pass the focused documentation gates.
