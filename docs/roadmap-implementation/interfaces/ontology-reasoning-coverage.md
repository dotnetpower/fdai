# Ontology Reasoning Coverage implementation ledger

This delivery ledger preserves reviewable implementation scope, append-only transitions,
and resumable work while the roadmap owner remains focused on normative design.

## Implementation status

The Owner directed implementation of the
[owner design](../../roadmap/interfaces/ontology-reasoning-coverage.md) on 2026-09-28; its listed
decisions still await individual approval records. The structural descriptor gate, a deterministic
reasoning coverage receipt with a ratchet gate, and the bilingual cohort with fixture-graph tests
are implemented. The capacity, catalog, and live L1 measurements came from session-local runs over
the active release and the local development graph and are not retained as repository evidence.

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| D1 declaration descriptors | implemented | [`check-ontology-query-coverage.py`](../../../scripts/quality/architecture/check-ontology-query-coverage.py) passes with 10 deterministic fixture questions and `production_ready=false` | Proves descriptor accounting only; it does not prove that questions about a declaration compile or answer. |
| Reasoning coverage receipt and exclusion governance | in-progress | [`semantic_reasoning_coverage.py`](../../../services/core-control-plane/src/fdai/core/conversation/semantic_reasoning_coverage.py); [`check-reasoning-coverage.py`](../../../scripts/quality/architecture/check-reasoning-coverage.py) with [`reasoning-coverage-baseline.json`](../../../scripts/quality/architecture/reasoning-coverage-baseline.json) | 427 closed factor cells record `compiled`, `unsupported`, `clarify`, or `inadmissible` with typed reasons, and any change needs a reviewed baseline refresh. Per-dimension D1 through D8 accounting, the exclusion budget, and the audit are not implemented. |
| L1a and L1b contracts and capacity | not-started | Terminal cap in [`semantic_turn.py`](../../../packages/service-contracts/src/fdai_service_contracts/semantic_turn.py); ObjectSet limits in [`models.py`](../../../services/core-control-plane/src/fdai/core/ontology_platform/models.py); execution bounds in [`query_execution.py`](../../../services/core-control-plane/src/fdai/core/ontology_platform/query_execution.py) | Typed evidence manifests, aggregate and path pushdown with non-interference, qualified mentions, output and deadline budgets, and handle paging are absent. |
| L2 catalog completion | not-started | [`rule-catalog/vocabulary/`](../../../rule-catalog/vocabulary/) | ObjectType and LinkType declarations carry no Korean terms; most LinkTypes lack traits and roles; FunctionTypes declare no literal-argument provenance or anchor applicability. |
| L3 readers and data | not-started | Design only | Incident collection, alerts, forecasts, capacity forecasts, cost observations, workload mappings, topology history publishing, and `Resource.location` are missing for conversation. |
| L4a, L4b, and L4c closure, assurance, and parity | in-progress | [`reasoning-cohort.v1.json`](../../../eval/ontology-reasoning/reasoning-cohort.v1.json); `test_semantic_reasoning_cohort.py`; [`question_universe.py`](../../../services/core-control-plane/src/fdai/core/conversation/question_universe.py) enforces the 10,000-case bound | A 60-case bilingual cohort with gold forms and fixture-graph outcomes exists. Independent annotation of the question bank, the locked holdout, universe sharding, the admission lattice, restatement checks, and the SRE Agent parity baseline are absent. |
| L5 legacy removal | not-started | Descriptor selection in [`semantic_query_descriptor_selector.py`](../../../services/core-control-plane/src/fdai/composition/semantic_query_descriptor_selector.py) | Selector-dependent judgment, lexical signal matching, regular-expression extraction, and template answer renderers remain on the current path. |
| Conversation grounding rules and parity procedure | implemented | [`conversation-grounding.instructions.md`](../../../.github/instructions/conversation-grounding.instructions.md); [`sre-agent-parity`](../../../.github/skills/sre-agent-parity/SKILL.md); `python3 scripts/quality/architecture/check-design-routes.py` passed; `python3 scripts/quality/architecture/check-chat-semantic-routing.py` passed | The existing routing gate rejects new lexical semantic modules, including the new reasoning modules; no gate yet counts template answer renderers. |
| M2 SRE Agent parity | not-started | [Comparison ledger](../../internals/sre-agent-comparison-ledger.md) holds 39 earlier matched runs | No run yet compares the question, derivation, and answer under the M2 gate. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-09-28 | not-started | Adopted the coverage plan and this ledger after a capacity and catalog review of the approved compiler design and an independent critique. The review measured descriptor selection, the judgment capability byte bound, judgment attempts, the terminal evidence cap, plan and execution bounds, wire and presentation bounds, ObjectSet and traversal limits, duplicate names, lexical group membership, relation semantics, language terms, instance sources, function contracts, and the question-universe bound. The critique's findings replaced one closure claim with accounted guarantees, exclusion governance, non-interference, typed evidence manifests, a calibration lattice, and per-family lanes. Earlier provenance for this scope was not reconstructed. | `current change`; `docs/roadmap/interfaces/ontology-reasoning-coverage.md`; `docs/roadmap/interfaces/ontology-reasoning-coverage-ko.md`; `uv run python scripts/quality/architecture/check-ontology-query-coverage.py` passed; changed-path documentation gates | Obtain approval for the eight coverage decisions, then start lane L4a before compiler round R0. |
| 2026-09-28 | not-started | Applied the Owner directives: no hard-coded or template answers, no lexical meaning, nothing dropped by a bound, and at least Azure SRE Agent quality. Added the binding conversation grounding instruction and the SRE Agent parity skill, the exhaustive bounded-processing rules, model-owned grounding and composition responsibilities, the M2 parity guarantee, and the assurance and parity section with parity rubric v1; evaluation ownership moved here from the compiler design. An independent critique of the new rules was revised in: identity, scope, and authority stay bound by code, only catalog notices and verified data views render without the model, V-CLAIM checks full propositions, stages reserve budgets before work with pinned continuations, and the parity skill requires Owner-named scope, read-only access, deadlines, and private expiring captures. | `current change`; `docs/roadmap/interfaces/ontology-reasoning-coverage.md`; `docs/roadmap/interfaces/ontology-reasoning-coverage-ko.md`; `.github/instructions/conversation-grounding.instructions.md`; `.github/skills/sre-agent-parity/SKILL.md`; changed-path documentation and route gates | Approve the coverage decisions, then run the SRE Agent parity baseline in lane L4a. |
| 2026-09-28 | in-progress | Implemented the deterministic reasoning coverage receipt over 427 closed question-form factor cells with a ratchet gate, and the 60-case bilingual reasoning cohort with gold forms, a generic fixture graph, and L2 tests that compile and execute every gold form. Live L1 rounds on the local fixture graph, with the question-form and concept-selection calls answered by the resolved T1 model, raised single-run cohort outcome agreement from 30 of 60 to 49 of 60, and a final two-repeat round agreed on 103 of 120 runs with all 51 executed compiled answers equal to gold; every remaining miss is an explicit clarification, typed unsupported reason, or inadmissible form. | `current change`; `services/core-control-plane/src/fdai/core/conversation/semantic_reasoning_coverage.py`; `scripts/quality/architecture/check-reasoning-coverage.py`; `eval/ontology-reasoning/reasoning-cohort.v1.json`; `uv run python scripts/quality/architecture/check-reasoning-coverage.py` passed; `uv run pytest -q --no-cov services/core-control-plane/tests/conversation/test_semantic_reasoning_cohort.py` passed | Lock a holdout, record the SRE Agent parity baseline in lane L4a, and add per-dimension accounting and the exclusion budget to the receipt. |

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
- [ ] Run the SRE Agent parity baseline over the reasoning cohort and the ledger seed catalog in
  batches of at most 10 questions, with redacted ledger runs that compare question, derivation, and
  answer, and record M2 per family and locale.
- [ ] Add a focused gate that rejects new regular-expression, keyword-table, and template-answer code
  in conversation paths, with an explicit allowlist of the existing debt that only shrinks.
