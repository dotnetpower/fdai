# Rule Lookup Ontology Storage implementation ledger

This delivery ledger preserves reviewable implementation scope, append-only transitions,
and resumable work while the roadmap owner remains focused on normative design.

## Implementation status

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| Versioned ontology and Rule catalog artifacts | implemented | `rule-catalog/vocabulary/`; `rule-catalog/catalog/`; `test_ontology_catalog.py`; `test_rule_catalog.py` | Catalog loaders validate ObjectType, LinkType, ActionType, Rule references, and dispatch semantics before startup. |
| Relational ontology instances and exact release pinning | implemented | `alembic/versions/20260713_0011_ontology_instances.py`; `20260801_0067_ontology_release_pinning.py`; `20260813_0081_ontology_release_registry.py`; `test_postgres_ontology_instance.py` | PostgreSQL stores typed instances and exact release metadata with direction and compatibility guards. |
| Single-store L2-L4 persistence surfaces | implemented | `service-migrations/branches/core-control-plane/versions/20260829_core_catalog_lifecycle.py`; `services/core-control-plane/tests/persistence/test_catalog_lifecycle_integration.py` | The current service head scopes learned actions by catalog version, permits same signatures in different versions, and expires T2 entries. The live test also covers legacy backfill, version invalidation, retention, and migration rollback when a local PostgreSQL adoption is available. |
| Boot, reload, and dispatch-index lifecycle | implemented | `services/core-control-plane/src/fdai/core/tiers/t0_deterministic/index.py`; `services/core-control-plane/tests/core/tiers/t0_deterministic/test_index.py`; [Boot and Reload](../../roadmap/architecture/rule-lookup-ontology-storage.md#boot-and-reload) | Catalog candidates compile before publication under a transition lock, failed compilation leaves the current and N-1 indexes unchanged, conflicting retained versions are rejected, and accepted N/N-1 indexes remain replayable. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-08-14 | in-progress | Adopted the implementation ledger without reconstructing earlier provenance and aligned the storage description with the current migration-owned schema. | `current change`; catalog, migration, and focused persistence evidence listed in the scope table. | Close the L2-L4 lifecycle and atomic reload evidence gaps below. |
| 2026-08-27 | implemented | Added the service-head catalog lifecycle migration, a live PostgreSQL lifecycle check, and an atomic dispatch-index lifecycle that retains N/N-1 for replay and rollback. Corrected the schema sketch to match the migration-owned columns. | `current change`; `test_catalog_lifecycle_integration.py`; `test_index.py`; service migration inventory and focused pytest checks. | A local PostgreSQL adoption is still required for the live receipt; no remote or Azure evidence is claimed. |
| 2026-08-27 | implemented | Serialized concurrent reload and rollback transitions, rejected conflicting content for a retained N-1 version, and made learned-action uniqueness version-aware with legacy backfill and safe downgrade checks. | `current change`; `test_index.py`; `test_catalog_lifecycle_integration.py`; service migration inventory and focused pytest checks. | A local PostgreSQL adoption is still required for the live receipt; no remote or Azure evidence is claimed. |
| 2026-08-27 | implemented | Added bounded catalog digest tombstones so evicted versions cannot be rebound to different rules, and made downgrade refuse cross-version signature collisions with an actionable preflight error. | `current change`; `test_index.py`; `test_catalog_lifecycle_integration.py`; focused PostgreSQL lifecycle check. | A local PostgreSQL adoption is still required for the live receipt; no remote or Azure evidence is claimed. |

### Remaining work

- [x] Internal implementation is complete: the service-head migration, focused lifecycle test, atomic reload and rollback behavior, and authoritative schema sketch are covered by the evidence in the scope and history tables. A live PostgreSQL receipt remains operational evidence rather than an unverified local claim.
