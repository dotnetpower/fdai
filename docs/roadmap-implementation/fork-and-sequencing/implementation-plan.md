# Implementation Compatibility Record (2026-07-06 Standard Set) implementation ledger

This delivery ledger preserves reviewable implementation scope, append-only transitions,
and resumable work while the roadmap owner remains focused on normative design.

## Implementation status

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| Historical standard-set decisions R1, R2, R3, R6, and R7 | not-applicable | [Current reconciliation](../../roadmap/fork-and-sequencing/implementation-plan.md#current-implementation-reconciliation) and linked owner documents | These proposals were not adopted and don't define current runtime behavior. |
| Historical R4 shared projection proposal | not-applicable | [`projection.py`](../../../services/core-control-plane/src/fdai/shared/providers/projection.py), [Assurance Twin](../../roadmap/operations/assurance-twin.md), [Deployment Preflight](../../roadmap/deployment/deployment-preflight.md) | A shared protocol exists, but the two consumers retain different current abstractions. Their owner documents track implementation. |
| M1.2 starter probe compatibility set | implemented | [`test_probe_catalog.py`](../../../services/core-control-plane/tests/rule_catalog/test_probe_catalog.py), [`rule-catalog/probes/`](../../../rule-catalog/probes) | The focused test enforces exact bidirectional parity between the four identifiers below and the shipped catalog. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-08-19 | implemented | Adopted the implementation ledger without reconstructing earlier provenance, classified the rejected standard-set proposals as historical compatibility identifiers, and retained the tested M1.2 probe set. | `current change`; current owner documents and the focused catalog parity test listed above. | No implementation is owned by this historical record; active work remains in the linked owner documents. |

### Remaining work

- [x] No implementation remains in this historical record. Current owners track active work, and
  `test_probe_catalog.py` enforces the retained M1.2 compatibility set.
