---
title: Implementation Compatibility Record (2026-07-06 Standard Set)
---

# Implementation Compatibility Record (2026-07-06 Standard Set)

This document preserves identifiers from the 2026-07-06 standard-set proposal that are still cited
by source, schemas, and tests. It is not a current implementation plan. Current behavior and future
work belong to the linked subsystem owner documents.

> **Scope:** R1, R2, R3, R4, R6, and R7 are historical proposal identifiers. The reconciliation
> below decides how to interpret them. The M1.2 probe list remains an executable compatibility
> contract because a focused test checks it against the shipped catalog.

## Implementation status

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| Historical standard-set decisions R1, R2, R3, R6, and R7 | not-applicable | [Current reconciliation](#current-implementation-reconciliation) and linked owner documents | These proposals were not adopted and don't define current runtime behavior. |
| Historical R4 shared projection proposal | not-applicable | [`projection.py`](../../../services/core-control-plane/src/fdai/shared/providers/projection.py), [Assurance Twin](../operations/assurance-twin.md), [Deployment Preflight](../deployment/deployment-preflight.md) | A shared protocol exists, but the two consumers retain different current abstractions. Their owner documents track implementation. |
| M1.2 starter probe compatibility set | implemented | [`test_probe_catalog.py`](../../../services/core-control-plane/tests/rule_catalog/test_probe_catalog.py), [`rule-catalog/probes/`](../../../rule-catalog/probes/) | The focused test enforces exact bidirectional parity between the four identifiers below and the shipped catalog. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-08-19 | implemented | Adopted the implementation ledger without reconstructing earlier provenance, classified the rejected standard-set proposals as historical compatibility identifiers, and retained the tested M1.2 probe set. | `current change`; current owner documents and the focused catalog parity test listed above. | No implementation is owned by this historical record; active work remains in the linked owner documents. |

### Remaining work

- [x] No implementation remains in this historical record. Current owners track active work, and
  `test_probe_catalog.py` enforces the retained M1.2 compatibility set.

## Current implementation reconciliation

| Decision | Current status | Current authority |
|----------|----------------|-------------------|
| R1 | Not adopted | Axis A is the baseline. Independent static-blast and environment axes may lower authority. [`ceiling.py`](../../../services/core-control-plane/src/fdai/core/risk_gate/ceiling.py) and [Execution Model](../decisioning/execution-model.md) are authoritative. |
| R2 | Not adopted | `ConversationCoordinator` receives an explicit `SystemConsoleTool` registry. ActionTypes provide discovery evidence rather than automatic write-tool projection. [Operator Console](../interfaces/operator-console.md) owns the surface. |
| R3 | Not adopted | `LlmBindings` aggregates role-specific protocols and adapters. [Prompt Composition](../decisioning/prompt-composition.md) owns current composition. |
| R4 | Partially implemented outside this record | `ScratchProjection` and the Assurance Twin consumer exist. Deployment Preflight retains `FeasibilityProbe` and `PreflightAnalyzer`. |
| R6 | Not adopted | `operator_memory` remains an independent append-and-supersede store. [Prompt Composition](../decisioning/prompt-composition.md#operator-memory-pipeline) owns the current contract. |
| R7 | Not adopted | `ExecutionPath` retains `pr_manual`, `pr_native`, `direct_api`, and `tool_call`; no `require_manual_merge` field exists. [Execution Model](../decisioning/execution-model.md) is authoritative. |

## Historical standard set identifiers

These short records explain old references. They do not override the reconciliation above.

### 2.1 R1 - Axes D and G derive from Axis A

R1 proposed deriving static-blast and environment results from Axis A. The proposal was not adopted;
the current risk gate evaluates independent axes that can only preserve or lower authority.

### 2.2 R2 - ConsoleTool projects the ActionType catalog

R2 proposed deriving write tools automatically from ActionTypes. The proposal was not adopted;
current composition injects an explicit system tool registry and uses ActionTypes as separate
discovery and action evidence.

### 2.3 R3 - Unified LlmBinding

R3 proposed one adapter shape for every model role. The proposal was not adopted; current
composition keeps role-specific protocols and resolved capability bindings.

### 2.4 R4 - Shared projection primitive

R4 proposed one projection abstraction for Assurance Twin and Deployment Preflight. A shared
`ScratchProjection` protocol exists, but current consumers retain separate behavior and ownership.

### 2.5 R6 - Operator memory as an audit materialized view

R6 proposed deriving operator memory from the audit log. The proposal was not adopted;
operator-memory entries retain their own approval, scope, expiry, and supersession lifecycle.

### 2.6 R7 - Manual merge as a flag

R7 proposed replacing `pr_manual` with a flag on `pr_native`. The proposal was not adopted;
execution paths remain distinct serialized contract values.

## Historical Wave M1 compatibility

Only the M1.2 catalog set remains a current compatibility boundary. Historical sequencing and
completed delivery narration are available in git history and are not a backlog.

### M1.2 Starter probes

The starter probe catalog contains exactly these ids:

- `vm_traffic_last_5m`
- `storage_access_log`
- `lb_backend_health`
- `blast_radius_classifier`

[`test_probe_catalog.py`](../../../services/core-control-plane/tests/rule_catalog/test_probe_catalog.py)
checks both directions: every identifier above has a YAML declaration, and the starter catalog has no
extra identifier absent from this list.

## Related docs

| To learn about | Read |
|----------------|------|
| Current authority calculation | [Execution Model](../decisioning/execution-model.md) and [Risk Classification](../decisioning/risk-classification.md) |
| Current operator tool boundary | [Operator Console](../interfaces/operator-console.md) |
| Current model composition | [Prompt Composition](../decisioning/prompt-composition.md) |
| Current projection consumers | [Assurance Twin](../operations/assurance-twin.md) and [Deployment Preflight](../deployment/deployment-preflight.md) |
| Current action schema and execution paths | [Action Ontology](../decisioning/action-ontology.md) |
