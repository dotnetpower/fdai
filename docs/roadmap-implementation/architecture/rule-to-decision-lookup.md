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
| Layered learned-action, similarity, and cache lookup | in-progress | T1 lightweight tier, catalog search, learned-action, embedding, and cache providers referenced by this design | Individual layers exist, but one focused replay proving the complete L1-L5 chain and every reuse back-reference is not cited here. |
| Semantic signature and reuse audit lineage | in-progress | Signature, catalog version, model version, mode, and `reused_from` contracts documented by the owner | The design is bounded and replay-oriented; complete production write/read evidence across every layer remains open. |
| Runtime ontology storage and reload | in-progress | [Rule Lookup Ontology Storage](../../roadmap/architecture/rule-lookup-ontology-storage.md) and its implementation ledger | Storage is independently owned and remains subject to that document's evidence and remaining work. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-08-24 | in-progress | Adopted a dedicated lookup owner from the prior LLM Strategy section; earlier lookup provenance was not reconstructed into this new ledger. | `current change`; rule contracts, T0 index, catalog declarations, and storage owner cited above. | Prove the complete layered lookup and reuse lineage exits below. |

### Remaining work

- [ ] Record a focused replay that traverses the applicable L1-L5 layers and proves only L5 invokes a frontier model while every terminal outcome remains audited.
- [ ] Prove each L2 and L4 reuse resolves `reused_from` to the originating verified outcome across catalog, model-config, and mode changes.
- [ ] Align runtime storage and reload evidence with the Rule Lookup Ontology Storage ledger without duplicating its schema ownership.
