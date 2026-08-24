# Operator Console Public Web Evidence implementation ledger

This delivery ledger preserves reviewable implementation scope, append-only transitions,
and resumable work while the roadmap owner remains focused on normative design.

## Implementation status

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| Core web-search policy, provider seam, and sanitizer | implemented | `services/core-control-plane/src/fdai/core/web_search/`; `services/core-control-plane/tests/core/web_search/` | Focused tests cover allowlists, sensitive-input denial, bounded evidence, sanitization, and no execution authority. |
| Operator classifier, resolver, and Azure adapter paths | not-started | Current tracked-tree audit; `grep -rn web_search services/operator-service/src` matches only the IAM settings family | The classifier, resolver, and Azure search adapter modules this row previously cited are absent from the current service tree. Only the deployment-level enablement setting remains in the Operator IAM settings family. |
| Local-evidence precedence and current-screen fast paths | implemented | Operator conversation application and Console answerer; focused conversation and Console tests | Deterministic screen and local-tool precedence exist and prevent speculative public-web fallback from replacing authoritative local evidence. |
| Frozen English and Korean regression corpus | implemented | `tests/integration/evaluation/web_evidence_route_corpus.v1.json`; `scripts/evaluation/web_evidence_route_corpus.py`; `tests/integration/scripts/test_web_evidence_route_corpus.py` | The versioned ten-case corpus declares route, provider-call, normalized-query, sensitive, current-screen, and alternative-discovery expectations with balanced English and Korean coverage. The loader rejects any case whose provider-call, denial, screen, or discovery expectation contradicts its route. It is an acceptance contract only; it performs no routing and calls no provider. |
| Held-out multilingual and live provider evidence | not-started | [Regression rubric](../../roadmap/interfaces/operator-console-web-evidence.md#public-web-evidence) | No governed English, Spanish, French, and Japanese held-out receipt or alternative-discovery relevance artifact is retained. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-08-14 | in-progress | Adopted the implementation ledger and clarified that the frozen regression corpus is not yet materialized; earlier provenance was not reconstructed. | `current change`; current Core and Operator web-search paths and focused checks listed in the scope table. | Materialize the corpus, close focused orchestration coverage, and retain governed live evidence. |
| 2026-08-16 | implemented | Materialized the versioned bilingual ten-case route and provider-call corpus with a strict loader that rejects contradictory route, provider-call, sensitive, screen, and alternative-discovery expectations. | `current change`; `tests/integration/evaluation/web_evidence_route_corpus.v1.json`; `pytest tests/integration/scripts/test_web_evidence_route_corpus.py` (16 passed). | Replay the corpus through the production classifier and provider seam, then retain governed held-out and live receipts. |
| 2026-08-16 | not-started | Corrected the Operator classifier row. Its cited `application/conversation/capabilities/web_search/` and `adapters/conversation/web_search/` paths do not exist in the current service tree, so `in-progress` overstated the executable surface. | `current change`; `grep -rn web_search services/operator-service/src` matches only `families/iam/`. | Reimplement or rebind the Operator classifier, resolver, and provider adapter under the current topology. |

### Remaining work

- [x] The versioned ten-case English and Korean route and provider-call corpus exists at `tests/integration/evaluation/web_evidence_route_corpus.v1.json` with explicit local, web, none, sensitive, current-screen, and alternative-discovery expectations. `python scripts/evaluation/web_evidence_route_corpus.py` prints its content-free coverage summary and `tests/integration/scripts/test_web_evidence_route_corpus.py` proves the contract (`16 passed`).
- [ ] Add a focused Operator suite that proves eligibility ordering, exact local precedence, classifier bounds, normalized query, provider-call suppression, candidate diversity, and partial comparison rendering against this corpus.
- [ ] Retain a governed held-out multilingual receipt and alternative-discovery relevance artifact with exact model, policy, allowlist, source, and revision provenance.
- [ ] Retain local and deployed failure, failover, unavailable, sanitization, citation, and no-authority receipts before claiming runtime validation.
