# Ontology Reasoning Coverage implementation ledger

This delivery ledger preserves reviewable implementation scope, append-only transitions,
and resumable work while the roadmap owner remains focused on normative design.

## Implementation status

The [owner design](../../roadmap/interfaces/ontology-reasoning-coverage.md) is a proposed plan whose
decisions await approval. Only the existing structural descriptor gate is implemented. The
2026-09-28 capacity and catalog measurements came from session-local probes over the active
release and the local development graph and are not retained as repository evidence.

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| D1 declaration descriptors | implemented | [`check-ontology-query-coverage.py`](../../../scripts/quality/architecture/check-ontology-query-coverage.py) passes with 10 deterministic fixture questions and `production_ready=false` | Proves descriptor accounting only; it does not prove that questions about a declaration compile or answer. |
| Reasoning coverage receipt and exclusion governance | not-started | Design only | No per-dimension `supported`, `excluded`, `missing`, or `not_applicable` accounting, exclusion budget, or audit exists. |
| L1a and L1b contracts and capacity | not-started | Terminal cap in [`semantic_turn.py`](../../../packages/service-contracts/src/fdai_service_contracts/semantic_turn.py); ObjectSet limits in [`models.py`](../../../services/core-control-plane/src/fdai/core/ontology_platform/models.py); execution bounds in [`query_execution.py`](../../../services/core-control-plane/src/fdai/core/ontology_platform/query_execution.py) | Typed evidence manifests, aggregate and path pushdown with non-interference, qualified mentions, output and deadline budgets, and handle paging are absent. |
| L2 catalog completion | not-started | [`rule-catalog/vocabulary/`](../../../rule-catalog/vocabulary/) | ObjectType and LinkType declarations carry no Korean terms; most LinkTypes lack traits and roles; FunctionTypes declare no literal-argument provenance or anchor applicability. |
| L3 readers and data | not-started | Design only | Incident collection, alerts, forecasts, capacity forecasts, cost observations, workload mappings, topology history publishing, and `Resource.location` are missing for conversation. |
| L4a, L4b, and L4c closure and assurance | not-started | [`question_universe.py`](../../../services/core-control-plane/src/fdai/core/conversation/question_universe.py) enforces the 10,000-case bound | Taxonomy annotation, factor and interaction tables, universe sharding, the admission lattice, and restatement checks are absent. |
| L5 legacy removal | not-started | Descriptor selection in [`semantic_query_descriptor_selector.py`](../../../services/core-control-plane/src/fdai/composition/semantic_query_descriptor_selector.py) | Selector-dependent judgment and lexical signal matching remain on the current path. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-09-28 | not-started | Adopted the coverage plan and this ledger after a capacity and catalog review of the approved compiler design and an independent critique. The review measured descriptor selection, the judgment capability byte bound, judgment attempts, the terminal evidence cap, plan and execution bounds, wire and presentation bounds, ObjectSet and traversal limits, duplicate names, lexical group membership, relation semantics, language terms, instance sources, function contracts, and the question-universe bound. The critique's findings replaced one closure claim with accounted guarantees, exclusion governance, non-interference, typed evidence manifests, a calibration lattice, and per-family lanes. Earlier provenance for this scope was not reconstructed. | `current change`; `docs/roadmap/interfaces/ontology-reasoning-coverage.md`; `docs/roadmap/interfaces/ontology-reasoning-coverage-ko.md`; `uv run python scripts/quality/architecture/check-ontology-query-coverage.py` passed; changed-path documentation gates | Obtain approval for the eight coverage decisions, then start lane L4a before compiler round R0. |

### Remaining work

- [ ] Record approval or revision of each of the eight decisions listed in the owner design, with
  the approving review reference.
- [ ] Complete L4a: two independent annotators label all 400 question-bank questions with a route
  class, and the adjudicated cohort, holdout, and fixture graph are committed before R0.
- [ ] Complete L1a: review the evidence-manifest, pushdown, qualified-mention, output-budget, and
  handle contracts with a recorded threat model before R1.
- [ ] Emit a `ReasoningCoverageReceipt` per release, role, purpose, and locale with support ratios,
  zero `missing` cells, a zero new-exclusion budget, and a recorded audit of 10% of exclusions.
- [ ] Pass the factor and interaction closure tests with per-family unsupported budgets and no
  regression, and shard the question universe under a root receipt.
- [ ] Pass capacity tests on a synthetic graph at ten times the local graph with pushdown, typed
  evidence manifests, critical-path budgets, and no silent truncation, plus differential
  non-interference tests between principals that differ only in hidden data.
- [ ] Reach zero `missing` D2, D3, D5, and D6 cells per family through reviewed catalog revisions.
- [ ] Bind the readers in the owner design with one accountable agent each, reaching zero `missing`
  D4 and D7 cells per family.
- [ ] Publish the admission backoff lattice and restatement check, keep confirm-first at or below 15%
  of admitted turns per promoted family, and report G3b as `0/n` with its upper bound.
