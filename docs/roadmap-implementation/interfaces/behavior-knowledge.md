# Behavior Knowledge for Command Deck implementation ledger

This delivery ledger preserves reviewable implementation scope, append-only transitions,
and resumable work while the roadmap owner remains focused on normative design.

## Implementation status

The service extraction retained the provider contracts but removed concrete retrieval, Operator
API, PostgreSQL, seed, and test implementations. In-memory retrieval, tracked-source freshness
validation, and the 13 read-only reference seeds now exist. The Operator answer path, persistence,
holdout checks, and governed runtime evidence do not. The ledger separates the target design from
the current executable surface.

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| Structured behavior contracts | implemented | [`behavior_knowledge.py`](../../../services/core-control-plane/src/fdai/shared/providers/behavior_knowledge.py); [`test_behavior_knowledge.py`](../../../services/core-control-plane/tests/providers/test_behavior_knowledge.py) (`16 passed`) | Focused contract tests cover repository-relative source coordinates, ordered line ranges, citation minimization, stable identity fields, required aliases and sources, embedding dimensions, test backing, and localized search text. |
| In-memory retrieval and tracked-source freshness validation | implemented | [`behavior_index.py`](../../../services/core-control-plane/src/fdai/core/knowledge/behavior_index.py); [`test_behavior_index.py`](../../../services/core-control-plane/tests/knowledge/test_behavior_index.py) (`14 passed`) | `InMemoryBehaviorKnowledgeIndex` provides idempotent upsert, exact-alias/exact-identifier/hybrid ordering, authority ordering, reciprocal-rank fusion, retrieval floors, comparison withholding, Korean token retrieval, and stale or untracked citation handling. Production binding remains separate work. |
| 13 reference seeds | implemented | [`behavior_seeds.py`](../../../services/core-control-plane/src/fdai/delivery/behavior_knowledge/behavior_seeds.py), [`behavior_seed_generation.py`](../../../services/core-control-plane/src/fdai/delivery/behavior_knowledge/behavior_seed_generation.py), [generated source commitments](../../../services/core-control-plane/src/fdai/delivery/behavior_knowledge/behavior_seeds.generated.json), and [`test_behavior_seeds.py`](../../../services/core-control-plane/tests/delivery/behavior_knowledge/test_behavior_seeds.py); focused tests (`46 passed` with contract/index tests); `generate-behavior-seeds.py --check` (`13 verified`) | All 13 have stable historical identities, English/Korean fields, unique bounded tracked citations, exact current symbol ranges and Git blobs. Eleven cite implementation and test sources; the Console identity and local evidence contracts cite design instructions and carry `designed`, not runtime-validated, status. No holdout corpus or Operator binding is claimed. |
| Server-owned resolver, renderer, and verifier | not-started | Service extraction commit `0988b1552` and current tracked-tree audit | No current Operator API behavior-evidence capability imports or binds the retained contracts. |
| PostgreSQL/pgvector persistence and production binding | not-started | Service extraction commit `0988b1552` and current tracked-tree audit | The prior adapter was removed; no behavior-specific migration, composition binding, or sync command exists in the current tree. |
| Focused verification and runtime evidence | in-progress | Focused provider, index, and whole-seed tests (`46 passed`); historical extraction audit | Current contract, index, and whole-seed checks pass. Operator chat, pgvector parity, holdout, and governed runtime checks remain absent; there is no current runtime receipt. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-08-13 | in-progress | Adopted the implementation ledger and corrected the stale post-extraction status; earlier implementation provenance was not reconstructed. | `current change`; this bilingual document pair; current provider-contract audit; `git diff-tree --no-commit-id --name-status -r 0988b1552`; roadmap, translation, punctuation, Hangul, size, and link checks. | Restore the concrete retrieval and answer path, persistence, focused tests, and governed runtime evidence below. |
| 2026-08-16 | in-progress | Restored the in-memory behavior index and the tracked-source freshness validator under the current service topology. | `pytest services/core-control-plane/tests/knowledge/test_behavior_index.py` passed 14 focused tests covering idempotent upsert, match-class and authority ordering, stale and untracked citations, Korean paraphrase retrieval, comparison withholding, all-stale comparison abstention, the retrieval floor, and citation-only exposure. | Restore the 13 reference seeds, bind the server-owned Operator answer path, add persistence, and record governed runtime evidence. |
| 2026-09-12 | implemented | Added direct provider-contract coverage and reconciled the already-tested in-memory retrieval and freshness implementation without restoring removed seeds or production bindings. | `current change`; provider contract and in-memory index tests (`30 passed`). | Restore tracked reference seeds, the server-owned answer path, PostgreSQL parity, and governed runtime evidence. |
| 2026-09-27 | implemented | Restored 13 read-only reference seeds against current tracked code, tests, schema, and design instructions; preserved historical identities, downgraded two design-only records, and moved duplicate inline status into this authoritative ledger. | `current change`; `services/core-control-plane/src/fdai/delivery/behavior_knowledge/`, `scripts/quality/architecture/generate-behavior-seeds.py`, `services/core-control-plane/tests/delivery/behavior_knowledge/test_behavior_seeds.py`, the English/Korean owner pair, and regenerated `services/system-knowledge-service/src/fdai_system_knowledge_service/data/catalog.json`; `uv run pytest -q --no-cov services/core-control-plane/tests/delivery/behavior_knowledge/test_behavior_seeds.py services/core-control-plane/tests/knowledge/test_behavior_index.py services/core-control-plane/tests/providers/test_behavior_knowledge.py` (`46 passed`); `PYTHONPATH=services/core-control-plane/src uv run python scripts/quality/architecture/generate-behavior-seeds.py --check` (`13 verified`). | Bind and test the server-owned Operator answer path; add PostgreSQL parity, holdout, and governed runtime evidence without treating reference metadata as live observations. |

### Remaining work

- [x] Restore the in-memory index and tracked-source freshness validator under the current service
  topology, with focused tests proving ordering, stale-source handling, localization, comparison,
  and source-body exclusion.
- [x] Restore the 13 reference seeds against tracked repository sources. The whole-seed precision
  test and generator check reject a missing path or symbol, stale blob or line range, overlaps,
  unsafe citations, and duplicate identities (`46 passed`; `13 verified`).
- [ ] Bind a server-owned resolver, deterministic renderer, and verifier in the Operator API, with
  focused tests proving client evidence replacement, authority-path fallback, and localized answer
  structure.
- [ ] Add a behavior-specific PostgreSQL migration, pgvector adapter, production composition
  binding, and incremental sync command, then record passing in-memory/database parity evidence.
- [ ] Re-run the 20-question holdout and latency benchmark against the restored current topology,
  and record the governed runtime receipt without treating the pre-extraction baseline as current
  validation.
