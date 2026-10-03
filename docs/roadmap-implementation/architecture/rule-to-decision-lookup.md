# Rule-to-Decision Lookup implementation ledger

This delivery ledger tracks deterministic ontology dispatch, layered reuse, semantic signatures,
and audit lineage. Storage and reload behavior remain owned by the Rule Lookup Ontology Storage
document.

## Implementation status

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| Typed Rule dispatch declarations and catalog cross-references | implemented | `shared/contracts/models/rule.py`; `shared/contracts/rule/schema.json`; `rule-catalog/vocabulary/`; ontology catalog tests | Rule targets, signals, evaluated properties, policies, and ActionTypes resolve through typed declarations instead of text aliases. |
| Deterministic T0 index and pipeline-stage vocabulary | implemented | `core/tiers/t0_deterministic/index.py`; `core/tiers/t0_deterministic/models.py`; focused T0 and catalog tests | Exact type intersections and audit-stage vocabulary exist without granting mutation authority. |
| Layered learned-action, similarity, and cache lookup | implemented | `services/core-control-plane/tests/core/tiers/t1_lightweight/test_layered_replay_lineage.py`; `uv run pytest -q --no-cov services/core-control-plane/tests/core/tiers/t1_lightweight/test_layered_replay_lineage.py services/core-control-plane/tests/rule_catalog/test_objective_effect.py` (`8 passed`) | The focused replay traverses L1 catalog/T0, L2 learned-action reuse, L3 embedding similarity, L4 cache reuse, and L5 reasoning with a counting fake frontier model and in-memory audit sink. |
| Semantic signature and reuse audit lineage | implemented | `services/core-control-plane/src/fdai/core/control_loop/_audit_helpers.py`; `services/core-control-plane/src/fdai/core/control_loop/_learned_reuse.py`; `services/core-control-plane/tests/core/tiers/t1_lightweight/test_layered_replay_lineage.py`; targeted Ruff and strict mypy checks | T1 audit and terminal advisory rows now carry `reused_from`; the replay proves L2/L4 hits walk back to the originating L5 audit id and catalog, model-config, and mode changes invalidate signatures. |
| Runtime ontology storage and reload | implemented | [Rule Lookup Ontology Storage](../../roadmap/architecture/rule-lookup-ontology-storage.md) and its implementation ledger; `test_index.py` (`16 passed`); `test_catalog_lifecycle_integration.py` (`1 passed`) | The independently owned service-head migration, version-aware L2-L4 lifecycle, and atomic N/N-1 reload and rollback evidence are current. This row does not duplicate schema ownership or claim remote database evidence. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-08-24 | in-progress | Adopted a dedicated lookup owner from the prior LLM Strategy section; earlier lookup provenance was not reconstructed into this new ledger. | `current change`; rule contracts, T0 index, catalog declarations, and storage owner cited above. | Prove the complete layered lookup and reuse lineage exits below. |
| 2026-09-12 | implemented | Reconciled runtime storage and reload with its authoritative owner after verifying deterministic index lifecycle and the service-head PostgreSQL catalog lifecycle locally. | `current change`; `test_index.py` (`16 passed`); serial `test_catalog_lifecycle_integration.py` (`1 passed`). | Complete L1-L5 traversal and L2/L4 `reused_from` lineage evidence; storage schema ownership remains in its dedicated ledger. |
| 2026-10-04 | implemented | Added a focused deterministic L1-L5 replay and propagated `reused_from` into T1 reuse audit rows so terminal reuse lineage is walkable to the originating verified L5 outcome. | `current change`; `services/core-control-plane/tests/core/tiers/t1_lightweight/test_layered_replay_lineage.py`; `services/core-control-plane/src/fdai/core/control_loop/_audit_helpers.py`; `services/core-control-plane/src/fdai/core/control_loop/_learned_reuse.py`; `uv run pytest -q --no-cov services/core-control-plane/tests/core/tiers/t1_lightweight/test_layered_replay_lineage.py services/core-control-plane/tests/rule_catalog/test_objective_effect.py` (`8 passed`); targeted Ruff passed; `uv run mypy --strict services/core-control-plane/src/fdai/core/control_loop/_audit_helpers.py services/core-control-plane/src/fdai/core/control_loop/_learned_reuse.py services/core-control-plane/src/fdai/rule_catalog/schema/objective_effect.py` passed. | No local replay residual remains for the two completed items; deployed-runtime/production evidence remains outside this ledger's local replay scope. |

### Remaining work

- [x] Record a focused replay that traverses the applicable L1-L5 layers and proves only L5 invokes a frontier model while every terminal outcome remains audited. Evidence: `services/core-control-plane/tests/core/tiers/t1_lightweight/test_layered_replay_lineage.py`; `uv run pytest -q --no-cov services/core-control-plane/tests/core/tiers/t1_lightweight/test_layered_replay_lineage.py services/core-control-plane/tests/rule_catalog/test_objective_effect.py` (`8 passed`).
- [x] Prove each L2 and L4 reuse resolves `reused_from` to the originating verified outcome across catalog, model-config, and mode changes. Evidence: `services/core-control-plane/src/fdai/core/control_loop/_audit_helpers.py`, `services/core-control-plane/src/fdai/core/control_loop/_learned_reuse.py`, and `services/core-control-plane/tests/core/tiers/t1_lightweight/test_layered_replay_lineage.py`; targeted Ruff, strict mypy, and the focused replay test passed.
- [x] Align runtime storage and reload evidence with the Rule Lookup Ontology Storage ledger without
  duplicating schema ownership (`16 passed`, `1 passed`).
