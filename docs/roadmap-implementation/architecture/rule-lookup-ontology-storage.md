# Rule Lookup Ontology Storage implementation ledger

This delivery ledger preserves reviewable implementation scope, append-only transitions,
and resumable work while the roadmap owner remains focused on normative design.

## Implementation status

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| Versioned ontology and Rule catalog artifacts | implemented | `rule-catalog/vocabulary/`; `rule-catalog/catalog/`; `test_ontology_catalog.py`; `test_rule_catalog.py` | Catalog loaders validate ObjectType, LinkType, ActionType, Rule references, and dispatch semantics before startup. |
| Relational ontology instances and exact release pinning | implemented | `alembic/versions/20260713_0011_ontology_instances.py`; `20260801_0067_ontology_release_pinning.py`; `20260813_0081_ontology_release_registry.py`; `test_postgres_ontology_instance.py` | PostgreSQL stores typed instances and exact release metadata with direction and compatibility guards. |
| Single-store L2-L4 persistence surfaces | in-progress | `service-migrations/branches/core-control-plane/versions/20260809_core_runtime_role.py`; current `learned_action`, `ontology_embedding`, and `t2_cache` tables | The tables and service ownership exist, but this document does not yet cite one focused lifecycle check proving promotion invalidation, expiry, and rollback together. |
| Boot, reload, and dispatch-index lifecycle | in-progress | [Boot and Reload](../../roadmap/architecture/rule-lookup-ontology-storage.md#boot-and-reload); catalog loader tests under `tests/rule_catalog/` | Startup compilation and exact catalog loading are implemented. A retained reload receipt proving atomic index replacement and N/N-1 behavior remains absent from this owner document. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-08-14 | in-progress | Adopted the implementation ledger without reconstructing earlier provenance and aligned the storage description with the current migration-owned schema. | `current change`; catalog, migration, and focused persistence evidence listed in the scope table. | Close the L2-L4 lifecycle and atomic reload evidence gaps below. |

### Remaining work

- [ ] Add one focused PostgreSQL lifecycle check that proves catalog-version invalidation, T2 cache expiry, learned-action retention, and rollback on the current service migration head.
- [ ] Retain an atomic catalog reload receipt showing that failed compilation preserves the prior dispatch indexes and that an accepted N/N-1 transition remains replayable.
- [ ] Replace or annotate any schema-sketch field that diverges from the authoritative Alembic head before treating the sketch as an exact operator reference.
