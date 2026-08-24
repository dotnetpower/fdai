# Behavior Knowledge for Command Deck implementation ledger

This delivery ledger preserves reviewable implementation scope, append-only transitions,
and resumable work while the roadmap owner remains focused on normative design.

## Implementation status

The service extraction retained the provider contracts but removed the concrete retrieval,
Operator API, PostgreSQL, seed, and test implementations. In-memory retrieval and tracked-source
freshness validation are restored; the Operator answer path, persistence, and seeds are not. The
design remains authoritative; the ledger below separates that target from the current executable
surface.

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| Structured behavior contracts | in-progress | [`behavior_knowledge.py`](../../../services/core-control-plane/src/fdai/shared/providers/behavior_knowledge.py) | `BehaviorSpec`, localized content, source metadata, freshness results, and index protocols remain, but no current focused tests exercise them. |
| In-memory retrieval and tracked-source freshness validation | in-progress | [`behavior_index.py`](../../../services/core-control-plane/src/fdai/core/knowledge/behavior_index.py), [`test_behavior_index.py`](../../../services/core-control-plane/tests/knowledge/test_behavior_index.py) | `InMemoryBehaviorKnowledgeIndex` restores idempotent upsert, exact-alias/exact-identifier/hybrid ordering, authority ordering, reciprocal-rank fusion, the retrieval floor, comparison withholding, and Korean token retrieval. `TrackedSourceFreshnessValidator` marks untracked and stale citations. The 13 reference seeds are not restored. |
| 13 reference seeds | not-started | Service extraction commit `0988b1552` and current tracked-tree audit | No seed set, seed precision test, or holdout corpus exists under the current service topology. |
| Server-owned resolver, renderer, and verifier | not-started | Service extraction commit `0988b1552` and current tracked-tree audit | No current Operator API behavior-evidence capability imports or binds the retained contracts. |
| PostgreSQL/pgvector persistence and production binding | not-started | Service extraction commit `0988b1552` and current tracked-tree audit | The prior adapter was removed; no behavior-specific migration, composition binding, or sync command exists in the current tree. |
| Focused verification and runtime evidence | not-started | Current tracked-tree audit | The former unit, chat, pgvector parity, and holdout checks are absent. No current runtime receipt validates this design. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-08-13 | in-progress | Adopted the implementation ledger and corrected the stale post-extraction status; earlier implementation provenance was not reconstructed. | `current change`; this bilingual document pair; current provider-contract audit; `git diff-tree --no-commit-id --name-status -r 0988b1552`; roadmap, translation, punctuation, Hangul, size, and link checks. | Restore the concrete retrieval and answer path, persistence, focused tests, and governed runtime evidence below. |
| 2026-08-16 | in-progress | Restored the in-memory behavior index and the tracked-source freshness validator under the current service topology. | `pytest services/core-control-plane/tests/knowledge/test_behavior_index.py` passed 14 focused tests covering idempotent upsert, match-class and authority ordering, stale and untracked citations, Korean paraphrase retrieval, comparison withholding, all-stale comparison abstention, the retrieval floor, and citation-only exposure. | Restore the 13 reference seeds, bind the server-owned Operator answer path, add persistence, and record governed runtime evidence. |

### Remaining work

- [x] Restore the in-memory index and tracked-source freshness validator under the current service
  topology, with focused tests proving ordering, stale-source handling, localization, comparison,
  and source-body exclusion.
- [ ] Restore the 13 reference seeds against tracked repository sources, with a whole-seed precision
  test that fails on a stale path, blob, or symbol line range.
- [ ] Bind a server-owned resolver, deterministic renderer, and verifier in the Operator API, with
  focused tests proving client evidence replacement, authority-path fallback, and localized answer
  structure.
- [ ] Add a behavior-specific PostgreSQL migration, pgvector adapter, production composition
  binding, and incremental sync command, then record passing in-memory/database parity evidence.
- [ ] Re-run the 20-question holdout and latency benchmark against the restored current topology,
  and record the governed runtime receipt without treating the pre-extraction baseline as current
  validation.
