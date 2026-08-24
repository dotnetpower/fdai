# Prediction Learning and Case History implementation ledger

This delivery ledger preserves reviewable implementation scope, append-only transitions,
and resumable work while the roadmap owner remains focused on normative design.

## Implementation status

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| Forecast detector, agent pub/sub runtime, and single-writer enforcement | implemented | [Forecast outcome contract](../../roadmap/rules-and-detection/prediction-learning-and-case-history.md#forecast-outcome-contract), pantheon single-writer registry | Shadow findings only; no execution authority. |
| Governed trajectory serialization, scanning, checksum, and retention primitives | implemented | [Retention and deletion](../../roadmap/rules-and-detection/prediction-learning-and-case-history.md#retention-and-deletion) | Reused rather than reimplemented. |
| `ForecastOutcome` schema, episode closer, transactional outbox, and the positive, negative, and held-for-review ledger | implemented | [Learning and promotion](../../roadmap/rules-and-detection/prediction-learning-and-case-history.md#learning-and-promotion) | Held episodes stay inert. |
| StateStore authority, PostgreSQL shadow dual-write, and the episode, revision, chunk, migration-marker, and tombstone tables | implemented | [Target PostgreSQL hot index](../../roadmap/rules-and-detection/prediction-learning-and-case-history.md#target-postgresql-hot-index), [Immutable artifact](../../roadmap/rules-and-detection/prediction-learning-and-case-history.md#immutable-artifact) | Full-chain keyset backfill and the zero-mismatch cutover gate are included. |
| Operational receipt compiler and action/incident case intake | implemented | [Retrieval for analysis](../../roadmap/rules-and-detection/prediction-learning-and-case-history.md#retrieval-for-analysis) | |
| Azure private artifact adapter, mechanical forecast tick Job, and read-only console health view | implemented | [Immutable artifact](../../roadmap/rules-and-detection/prediction-learning-and-case-history.md#immutable-artifact) | Deployment stays opt-in. |
| Muninn case materialization, scheduled retention, fingerprint-keyed cohorts, and inert Norns candidate choreography | in-progress | [Learning and promotion](../../roadmap/rules-and-detection/prediction-learning-and-case-history.md#learning-and-promotion) | Implemented through O2; raw response outcomes remain insufficient mechanism evidence. |
| Durable `Pattern` publication | not-started | `PANTHEON_SPECS`; `agents/_framework/topics.py` | Norns owns `Pattern` and `object.pattern` is registered, but nothing publishes or subscribes it, so recurrence answers come from volatile in-memory counters. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-08-15 | in-progress | Adopted the implementation ledger from the existing status table without reconstructing earlier provenance, and renamed the owned learning object to `Pattern`. | Current source and the sections referenced in the scope table. | Complete the observable exit conditions below. |

### Remaining work

- [ ] Publish `Pattern` from Norns on `object.pattern` with a live consumer, or retire the object
  type and its topic, updating `PANTHEON_SPECS` and both pantheon documents in the same change.
- [ ] Supply mechanism evidence strong enough to promote raw response outcomes beyond O2.
