# Continuous Operational Instance Graph Evidence Implementation Ledger

This ledger tracks the documentation ownership split for [Continuous Operational Instance Graph Evidence](../../roadmap/architecture/continuous-operational-instance-graph-evidence.md).

## Implementation status

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| Documentation ownership | not-applicable | `current change`; `docs/roadmap/architecture/continuous-operational-instance-graph-evidence.md` and its Korean pair; document-size and translation checks | This structural split changes no runtime behavior. |
| Reconciliation record-allocation admission | implemented | `delivery/inventory_json_budget.py`, collection/provider guards, and `test_inventory_json_budget.py`; 177 focused cases passed with 100% branch-inclusive preflight coverage | Refuses provably oversized records before copying or whole-string encoding; preserves exact byte accounting. Broader allocation and operational qualification remains under #2111. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-09-20 | not-applicable | Split one oversized roadmap owner into a focused bilingual companion without changing its contract. | `current change`; `docs/roadmap/architecture/continuous-operational-instance-graph-evidence.md` and its Korean pair | No runtime implementation work is introduced by this split. |
| 2026-10-20 | implemented | Linked the complete-reconciliation stage to its shared normalized-record preflight and retained exact encoding semantics and explicit limitations. | `current change`; eight pre-fix copying regressions; 177 focused inventory cases passed, 100% branch-inclusive preflight coverage, and two 4 MiB refusals below 128 KiB traced incremental allocation. | This is not process RSS, projection/SQL allocation, fleet-admission or installed qualification; #2111 remains open. |

### Remaining work

- [x] Preserve the moved design content and pass the focused documentation gates.
- [x] Reject oversized normalized records before copying and preserve exact existing byte accounting; the focused inventory selection passed 177 cases.
