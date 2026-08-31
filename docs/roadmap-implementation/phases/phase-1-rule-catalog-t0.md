# Phase 1 - Rule Catalog and T0 Deterministic Engine implementation ledger

This delivery ledger preserves reviewable implementation scope, append-only transitions,
and resumable work while the roadmap owner remains focused on normative design.

## Implementation status

### Migrated implementation notes

> **Implementation status**: Authored rule, Rego, and remediation seeds; the ActionType catalog;
> T0 engine; OPA evaluator; control-loop orchestration; GitOps draft-PR adapter; Azure inventory
> snapshot/delta primitives; and frozen-scenario replay are implemented. This document's
> "shadow only" language is the phase boundary when P1 first lands, not the current mode of the
> whole runtime. The repository now also contains later-phase promotion, risk/HIL, and
> enforce-capable adapters. Production inventory and GitOps delivery require deployment-specific
> provider and credential bindings.
> Rego evaluation now pins the exact `data.<package>.deny` decision path, OPA version, source and
> normalized AST semantic digests, canonical input digest, and result digest. T0 retains receipts
> for both allow and deny outcomes in the audit hint; denied findings carry the same receipt.

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| Catalog loaders, resource vocabulary, and ActionTypes | implemented | `services/core-control-plane/src/fdai/rule_catalog/schema/`; `rule-catalog/vocabulary/resource-types.yaml`; `rule-catalog/action-types/`; `uv run pytest -q --no-cov services/core-control-plane/tests/rule_catalog/test_rule_catalog.py services/core-control-plane/tests/rule_catalog/test_action_type_catalog.py services/core-control-plane/tests/rule_catalog/test_resource_type_registry.py` passed 120 cases | Resource, rule, policy, remediation, and ActionType references fail closed, and every shipped ActionType defaults to shadow. |
| Base authored rules, Rego, and remediation templates | in-progress | `rule-catalog/catalog/`; `policies/`; `rule-catalog/remediation/`; `extensions/cost-governance/src/fdai_cost_governance/resources/` | The current base catalog is broader than the historical five-seed list, but the VMSS right-size seed now belongs to the optional Cost Governance extension. Scope reconciliation remains open under issue #338. |
| Collector, parser, and runtime-catalog promotion | in-progress | `services/core-control-plane/src/fdai/rule_catalog/pipeline/collect_cli.py`; `services/core-control-plane/tests/rule_catalog/pipeline/test_parse.py` | Collectors retain and verify source snapshots, but some parsers remain unsupported and no governed stage promotes snapshots into the runtime catalog. |
| T0 rule index, OPA evaluation, and exact receipts | implemented | `services/core-control-plane/src/fdai/core/tiers/t0_deterministic/`; `uv run pytest -q --no-cov services/core-control-plane/tests/core/tiers/t0_deterministic/test_engine.py services/core-control-plane/tests/core/tiers/t0_deterministic/test_index.py services/core-control-plane/tests/core/tiers/t0_deterministic/test_opa_evaluator.py` passed 47 cases | Deterministic ordering, exact policy entrypoints, bounded OPA execution, and digest-bound allow/deny receipts pass locally. Staging and production still require the OPA binary. |
| What-if and configuration-drift integration | implemented | `services/core-control-plane/src/fdai/core/control_loop/change_safety_evidence.py`; `_process.py`; `services/core-control-plane/src/fdai/core/executor/action_builder.py`; focused evidence, ActionBuilder, risk-ceiling, and control-loop checks (`174 passed`) | Out-of-band findings are preserved while missing, stale, conflicting, failed, future, mismatched, synthetic, or incomplete evidence holds before authorization and risk. Valid what-if count feeds the existing risk axis; dry-run prediction remains distinct from effect verification. |
| Shadow executor and GitOps adapter | implemented | `services/core-control-plane/src/fdai/core/executor/`; `services/core-control-plane/src/fdai/delivery/gitops_pr/`; `services/core-control-plane/tests/core/executor/test_executor.py`; `services/core-control-plane/tests/delivery/gitops_pr/test_adapter.py`; included in the 165-case executor, adapter, and pipeline command below | Local safeguards, idempotency, draft shadow labels, and terminal audit pass. Real publishing remains deployment-gated. |
| P1 control-loop orchestration | in-progress | `services/core-control-plane/src/fdai/core/control_loop/`; `uv run pytest -q --no-cov services/core-control-plane/tests/core/executor/test_executor.py services/core-control-plane/tests/delivery/gitops_pr/test_adapter.py services/core-control-plane/tests/pipeline/test_control_loop_e2e.py` passed 165 cases | Event ingest, routing, T0, action build, shadow execution, and audit pass locally. The accepted Phase 1 what-if and drift integration remains open. |
| Change Safety out-of-band detection | implemented | `services/core-control-plane/src/fdai/core/verticals/change_safety/detector.py`; `services/core-control-plane/src/fdai/core/control_loop/_process.py`; `services/core-control-plane/src/fdai/composition/_helpers.py`; focused detector, metrics, control-loop, and risk checks (`193 passed`) | Phase 1 supports Azure Activity Log only. Declared unsupported kinds are explicit audited outcomes. Inventory freshness gates action authority after finding formation and cannot suppress findings or authorize stale-target execution. |
| Azure inventory full-scan and fallback seams | implemented | `services/core-control-plane/src/fdai/delivery/azure/inventory.py`; `services/core-control-plane/src/fdai/delivery/azure/arg_query.py`; `services/core-control-plane/src/fdai/delivery/azure/arm_inventory.py`; `services/core-control-plane/src/fdai/composition/wire_inventory.py`; `uv run pytest -q --no-cov services/core-control-plane/tests/delivery/azure/test_inventory.py services/core-control-plane/tests/delivery/azure/test_arg_query.py services/core-control-plane/tests/delivery/azure/test_arm_inventory.py` passed 25 cases | Provider-neutral full scan, ARG and ARM fallback, and composition pass locally. No production generation receipt is claimed. |
| Frozen scenario replay | implemented | `services/core-control-plane/tests/scenarios/test_v2026_07_replay.py`; `services/core-control-plane/tests/scenarios/manifests/v2026.07.json`; `uv run pytest -q --no-cov services/core-control-plane/tests/scenarios/test_v2026_07_replay.py` passed 16 cases | The shipped catalog replays through the real control loop. Constitutional capability coverage remains incomplete under issue #76. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-08-31 | implemented | Narrowed the Phase 1 out-of-band detector to its implemented Azure Activity Log source, added explicit audited unsupported-signal outcomes, and exposed the detector through the provider-neutral Container binding. Documented inventory freshness as an authority gate after finding formation. | `current change`; 193 focused detector, metrics, control-loop, and risk checks passed. | Add another signal only with an authoritative completeness/freshness contract and focused parity checks. |
| 2026-08-31 | implemented | Added the audited Change Safety pre-authority join after Action construction and before execution authorization and risk. Removed the success-shaped graph-derived count fallback; only current typed what-if evidence can populate the affected count. | `current change`; 45 focused evidence/ActionBuilder/risk checks plus 129 control-loop regression checks passed. | Bind an authoritative provider in deployment; unbound out-of-band actions remain held. |
| 2026-08-29 | in-progress | Replaced the placeholder scope row with bounded evidence-backed areas while preserving the migrated narrative note, then reran the current catalog, T0, executor/GitOps/control-loop, Change Safety, Azure inventory, and frozen replay slices. | `current change`; exact commands and outcomes are recorded in the corresponding scope rows: 120 catalog, 47 T0, 165 executor/GitOps/control-loop, 87 Change Safety, 25 Azure inventory, and 16 frozen replay cases passed. | Resolve the scope and integration issues below, then retain exact-revision live evidence before any validation claim. |
| 2026-08-24 | in-progress | Migrated the legacy status into the delegated ledger without reconstructing earlier provenance. | current change; preserved owner status from `docs/roadmap/phases/phase-1-rule-catalog-t0.md`. | Replace the legacy summary with bounded evidence-backed scope rows and observable exits. |

### Remaining work

- [x] Replace the migrated placeholder scope row with bounded rows and rerun the six focused local validation slices.
- [ ] Reconcile the historical base-catalog seed list with optional Cost Governance ownership under [issue #338](https://github.com/dotnetpower/fdai/issues/338).
- [ ] Decide and implement or defer collector snapshot promotion into the runtime catalog under [issue #340](https://github.com/dotnetpower/fdai/issues/340).
- [x] Bind what-if and configuration-drift evidence into one audited Phase 1 T0 path, or narrow the integration claim, under [issue #342](https://github.com/dotnetpower/fdai/issues/342).
- [x] Resolve the supported Change Safety signal set and inventory-before-verdict boundary under [issue #339](https://github.com/dotnetpower/fdai/issues/339).
- [ ] Complete constitutional capability-pack coverage under [issue #76](https://github.com/dotnetpower/fdai/issues/76).
- [ ] Retain exact-revision live Azure inventory and shadow GitOps evidence under [issue #341](https://github.com/dotnetpower/fdai/issues/341).
