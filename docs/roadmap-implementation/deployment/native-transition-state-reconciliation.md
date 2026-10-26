# Native transition state reconciliation implementation

This ledger tracks the bounded reconciliation implementation owned by
[Native transition state reconciliation](../../roadmap/deployment/native-transition-state-reconciliation.md).

## Implementation status

### Implementation scope

The implementation covers Hub approval, Agent state locking, immutable receipt verification,
canonical state replacement, rollback backup, audited submission, exact retry, and planning
resumption. It does not authorize general state repair.

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| Hub approval and completion | implemented | Focused API/store tests | Exact installation row lock |
| Agent atomic reconciliation | implemented | Advancing-clock, restart, rollback and retry tests | Current state only |
| Dual canonical receipt validation | implemented | Exact retained live receipt fixture plus digest, timestamp, field, restart and retry regressions | Immutable and regenerated receipt digests stay independently verified |
| Legacy precision bounds | implemented | Exact millisecond/full-precision canonical digest regressions | Positive delta no greater than one millisecond |
| Legacy artifact inventory compatibility | implemented | Exact retained live fixture; duplicate, order, wrong-digest, strict-target and retry regressions | Legacy source bytes and digest remain unchanged; the target is uniquely sorted |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-10-27 | implemented | Added bounded legacy transition state reconciliation without changing immutable transition receipts. | Focused tests 116 passed; PostgreSQL cohort 16 passed; strict mypy, Ruff and repository gates passed. | Deliver and verify the live reconciliation and subsequent Plan admission. |
| 2026-10-27 | implemented | Corrected reconciliation for an immutable full-precision receipt whose embedded state digest is millisecond-canonical while the audited Hub completion binds the regenerated full-precision receipt. | Current change; focused Agent, Hub and deployment CLI tests: 53 passed; isolated PostgreSQL reconciliation cohort: 20 passed; strict source mypy, Ruff, design-route, roadmap, translation, punctuation, and Hangul gates passed. | Deliver and verify the live reconciliation and subsequent Plan admission. |
| 2026-10-27 | implemented | Added a reconciliation-only legacy reported-state contract that preserves artifact order and duplicates, validates the stored digest, compares legacy inventories as multisets, and derives a strict uniquely sorted target without mutating the source digest. | Current change; deployment CLI contract tests: 6 passed; Agent reconciliation tests: 15 passed; Hub PostgreSQL reconciliation tests: 22 passed; strict source mypy and Ruff passed. | Deliver and verify the live reconciliation and subsequent Plan admission. |

### Remaining work

- [ ] Record one successful live reconciliation and the first admitted Plan that uses the reconciled
  source-state digest.
