# Ontology Reasoning Compiler implementation ledger

This delivery ledger preserves reviewable implementation scope, append-only transitions,
and resumable work while the roadmap owner remains focused on normative design.

## Implementation status

The [owner design](../../roadmap/interfaces/ontology-reasoning-compiler.md) was approved on
2026-09-28 and is not yet implemented. The evidence column cites existing kernel primitives that the
design reuses; it does not claim that any part of the design is implemented. The 2026-09-28
reasoning probe was a session-local planning measurement and is not retained as repository
evidence.

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| Question logical form and admission | not-started | Design only; current proposal contract in [`semantic_judgment.py`](../../../packages/service-contracts/src/fdai_service_contracts/semantic_judgment.py) | `primary_intent`, target kind, and facets remain free tokens, so relational meaning has no typed carrier. |
| Domain-restricted concept resolution | not-started | `query.resource_class_closure` is bound in [`wire_semantic_query.py`](../../../services/core-control-plane/src/fdai/composition/wire_semantic_query.py) | No conversation compiler uses class closure for instance goals, and cross-domain matches are not clarified. |
| Two-phase anchor binding | not-started | Entity-resolution holds in [`query_source_handlers.py`](../../../services/core-control-plane/src/fdai/core/ontology_platform/query_source_handlers.py) | Current compilers derive identities with regular expressions in [`semantic_target_identity.py`](../../../services/core-control-plane/src/fdai/core/conversation/semantic_target_identity.py). |
| Relation compilation and reviewed path grammars | not-started | Typed-path endpoint verification in [`query_verification.py`](../../../services/core-control-plane/src/fdai/core/ontology_platform/query_verification.py); LinkType query sides, roles, and traits in the query manifest | The only schema path search is the Resource-to-BusinessService helper in [`semantic_impact_planning.py`](../../../services/core-control-plane/src/fdai/core/conversation/semantic_impact_planning.py). |
| Aggregation, history, versions, cause, verification, and diagnose operators | not-started | Aggregate, order, topology, and metric node handlers in [`wire_semantic_query.py`](../../../services/core-control-plane/src/fdai/composition/wire_semantic_query.py) | Traversal rows lack root lineage, link evidence is redacted, and diagnose recipes are selected without the bound resource type. |
| Follow-up result handles | not-started | Screen selection binding `BoundResourceContext` in [`semantic_planning_models.py`](../../../services/core-control-plane/src/fdai/core/conversation/semantic_planning_models.py) | Prior turns reach planning only as bounded text. |
| Coverage, provenance, level, and want verification | not-started | [`query_verification.py`](../../../services/core-control-plane/src/fdai/core/ontology_platform/query_verification.py); [`semantic_planning_alignment.py`](../../../services/core-control-plane/src/fdai/core/conversation/semantic_planning_alignment.py) | Current checks prove type safety and shape alignment, not preservation of the question. |
| Runtime epistemic status | not-started | Release-gate `EpistemicStatus` records in [`epistemic_coverage.py`](../../../services/core-control-plane/src/fdai/core/conversation/epistemic_coverage.py) | Turns hold on any incomplete receipt instead of reporting per-goal status. |
| Reasoning evaluation cohort and fixture graph | not-started | Design only | The existing 68-case gold scores a verified plan for a different question as a pass. |
| Data and catalog prerequisites | not-started | Design only | Retained topology history, workload mappings, reviewed composition and ownership traits, a declared location property, and a link-evidence allowlist are absent. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-09-28 | not-started | Adopted the proposed owner design and this ledger after a traced review of preflight, judgment, frame, plan, verification, execution, and rendering, a two-run bilingual 36-case planning probe, and an independent design critique whose findings were revised into the design. Earlier provenance for this scope was not reconstructed. | `current change`; `docs/roadmap/interfaces/ontology-reasoning-compiler.md`; `docs/roadmap/interfaces/ontology-reasoning-compiler-ko.md`; changed-path translation, punctuation, link, route, document-size, and roadmap tracking checks | Obtain approval for the listed decisions, then start round R0. |
| 2026-09-28 | not-started | Recorded Owner approval of the eight design decisions and revised the approved design after a capacity review: qualified mentions for shared names, atom-diff alternatives with a 6 KiB form cap, `compare_entities` and `impact` operations, `forecast` and `cost` measures, a `future` time kind, aggregate pushdown for inventory-wide counts, and evidence-manifest and pushdown contracts in round R1. The per-family coverage lanes in the companion coverage design now gate the rounds. | `current change`; `docs/roadmap/interfaces/ontology-reasoning-compiler.md`; `docs/roadmap/interfaces/ontology-reasoning-compiler-ko.md`; [coverage ledger](ontology-reasoning-coverage.md); changed-path documentation gates | Start round R0 together with coverage lane L4. |

### Remaining work

- [x] Record approval of the eight decisions listed in the owner design. Evidence: the owner
  design's `Approved decisions` section and the 2026-09-28 approval history row.
- [ ] Complete R0: commit the bilingual reasoning cohort with a locked holdout, a generic fixture
  graph, strict gold, and production-faithful function binding in the harness, and record baseline
  L1 and L2 receipts.
- [ ] Complete R1: land the form, admission, binding, handle, coverage-rule, evidence-manifest, and
  aggregate and path pushdown contracts with N/N-1 codec tests and no behavior change.
- [ ] Complete R2: enforce interim operand-provenance and instance-versus-schema checks on the
  current path, with zero invented identity literals and zero schema answers to instance targets on
  both corpora, and replace lexical `parent_id` group membership with `contains` closure from the
  exact group, matching that closure on the fixture graph.
- [ ] Complete R3 through R8 with the exit evidence in the owner delivery-round table, including
  reviewed trait and path grammar catalog changes, traversal root lineage, the location property,
  the link-evidence allowlist, and a result-handle threat review.
- [ ] Complete R9: record one promotion receipt per operation family, and retire frame and plan
  prompts only for promoted families.
- [ ] Complete R10: remove lexical re-derivation from promoted paths after replay equivalence and
  one stable rollback release.
- [ ] Before promoting any operation family in R9, record the coverage-lane exits that gate it in
  the [coverage ledger](ontology-reasoning-coverage.md).
