# Continuous Operational Instance Graph Evidence Implementation Ledger

This ledger tracks the documentation ownership split for [Continuous Operational Instance Graph Evidence](../../roadmap/architecture/continuous-operational-instance-graph-evidence.md).

## Implementation status

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| Documentation ownership | not-applicable | `current change`; `docs/roadmap/architecture/continuous-operational-instance-graph-evidence.md` and its Korean pair; document-size and translation checks | This structural split changes no runtime behavior. |
| Reconciliation record-allocation admission | implemented | `delivery/inventory_json_budget.py`; original and expanded JSON-budget tests (`100 passed`, full branch-inclusive coverage); disposable loopback PostgreSQL chunk/restart/assessment cohort (`88 passed`) | Extends existing byte preflight to canonical Mapping/Sequence and bounded numeric/temporal forms before materialization. Exact encoding/hashes remain authoritative. Broader guarantees remain unclassified under #2111. |
| Explicit projection normalization-work admission | implemented | `core/ontology_platform/inventory_projection_bounds.py`; allocation, existing projection and runtime tests (`142 passed`, full guard branch-inclusive coverage) | Holds more than 2,000,000 expanded values or 16,777,216 string characters, cycles and excessive input depth before normalization. Dense records pass current generation/chunk byte allowances but require this independent work control. No weighted estimator or RSS guarantee. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-10-21 | implemented | Repaired canonical container/numeric expansion before existing record/chunk materialization and added explicit expanded-value/character admission before graph projection. Kept the authoritative concept classification partial rather than declaring unknown guarantees superseded. | #2111; `current change`; expanded-budget and original helper cohort (`100 passed`, 100% branch-inclusive coverage); core projection/runtime cohort (`142 passed`, 100% guard branch-inclusive coverage); real loopback-5433 chunk/restart/assessment cohort (`88 passed`); Resource Health/Static Web App suites (`62 passed`). | Independent issuer/whole-interval, broader durable-admission/reuse, SQL-buffer and operating-memory guarantees remain unclassified or unqualified. #2329 tracks durable-admission follow-up; this does not close #2111. |
| 2026-09-20 | not-applicable | Split one oversized roadmap owner into a focused bilingual companion without changing its contract. | `current change`; `docs/roadmap/architecture/continuous-operational-instance-graph-evidence.md` and its Korean pair | No runtime implementation work is introduced by this split. |
| 2026-10-20 | implemented | Linked the complete-reconciliation stage to its shared normalized-record preflight and retained exact encoding semantics and explicit limitations. | `current change`; eight pre-fix copying regressions; 177 focused inventory cases passed, 100% branch-inclusive preflight coverage, and two 4 MiB refusals below 128 KiB traced incremental allocation. | This is not process RSS, projection/SQL allocation, fleet-admission or installed qualification; #2111 remains open. |
| 2026-10-20 | implemented | Applied the same preflight at the existing 1 MiB durable-chunk bound, before normalizing properties or serializing oversized strings; kept canonical content, digest and continuation behavior. | `current change`; 189 focused source cases and 69 actual isolated PostgreSQL chunk/restart/replay cases passed. Eight production-limit pre-fix regressions failed; all measured refusals now stay below 128 KiB traced incremental allocation. | General projection/SQL memory, source authority and operational qualification remain separate under #2111. |

### Remaining work

- [x] Preserve the moved design content and pass the focused documentation gates.
- [x] Reject oversized normalized records before copying and preserve exact existing byte accounting; the focused inventory selection passed 177 cases.
- [x] Reject canonical Mapping/Sequence expansion and explicit projection work overflow before the affected materialization; focused source and disposable PostgreSQL evidence is listed above.
