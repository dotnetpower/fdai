# Operator Console - View Snapshot Contract implementation ledger

This delivery ledger preserves reviewable implementation scope, append-only transitions,
and resumable work while the roadmap owner remains focused on normative design.

## Implementation status

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| ViewSnapshot contract and deterministic screen answering | implemented | `console/src/deck/context.tsx`; `console/src/deck/answerer.ts`; `console/src/deck/answerer.test.ts`; `console/src/routes/view-contract.test.ts` | Focused Console tests cover bounded facts and records, route contracts, unsupported fields, and deterministic fallback. |
| Answer planning and qualification | implemented | `services/core-control-plane/src/fdai/core/conversation/answer_plan.py`; `answer_planning.py`; `answer_planning_qualification.py`; `scripts/evaluation/answer-planning-qualification.py`; focused conversation and CLI tests | Bounded plans, shadow records, strict measured-batch ingestion, and readiness-only receipts exist without activation authority. The CLI cannot generate measurements or activate planning. |
| Shadow contributor collection | in-progress | Answer-planning source and terminal metadata paths; [`test_answer_planning_conflicts.py`](../../../services/core-control-plane/tests/core/conversation/test_answer_planning_conflicts.py) | Phase C shadow records exist, and retained Phase E conflict cases prove that contradictory contributors preserve both evidence sets, never pick a winner, cannot change the primary agent, and carry no authority field. Phase D selective activation remains unpromoted. |
| Live observation presentation | implemented | Console Live models, routes, and focused tests; [Live observation contract](../../roadmap/interfaces/operator-console-view-snapshot.md#1343-live-observation-contract) | Queue and Flow presentation, source and mode handling, replay dedupe, freeze, retention, and drill-down behavior are implemented in the browser. |
| Governed cross-screen runtime receipt | in-progress | Console live E2E harness and route tests | Focused tests prove contracts, but this owner document retains no current authenticated receipt binding snapshot hydration, observed work, terminal verification, and navigation. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-08-14 | in-progress | Adopted the implementation ledger; earlier provenance was not reconstructed. | `current change`; ViewSnapshot, planning, Live, and focused test evidence listed in the scope table. | Retain governed cross-screen and shadow-qualification evidence before promotion. |
| 2026-08-14 | implemented | Added a deterministic CLI that validates one externally measured, sealed bilingual planning batch and emits a byte-stable, no-authority qualification receipt. | `current change`; `answer-planning-qualification.py`; focused CLI tests passed 5 cases. | Supply the real 100-case EN/KO batch and retain its separate review before selective activation. |
| 2026-08-16 | in-progress | Added retained Phase E conflict cases and the explicit authority-free shadow record key contract. | `pytest services/core-control-plane/tests/core/conversation/` passed 111 focused tests, including six new conflict cases covering preserved evidence sets, no confidence winner, unchanged primary agent, authority-free record keys, cross-domain conflict, and plan-bounded sections. | Complete Phase D selective activation review and retain the governed cross-screen receipt. |

### Remaining work

- [ ] Retain one authenticated cross-screen receipt that binds the visible snapshot digest, server evidence, branch lifecycle, terminal verification, stale transition, and route navigation.
- [ ] Supply and run a real sealed 100-case bilingual answer-planning batch through
  `scripts/evaluation/answer-planning-qualification.py --require-ready`, retain its immutable
  receipt with zero unsupported-claim and authority escapes, and complete a separate selective
  activation review.
- [x] Add and retain Phase E conflict cases proving that contradictory contributors preserve both evidence sets and cannot change the primary verified answer or grant authority.
- [ ] Retain Live reconnect, replay, freeze, stuck-budget, source-mixing, terminal replacement, and keyboard-contained drill-down evidence from the standard full stack.
