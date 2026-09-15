---
title: Live Cockpit Metrics Implementation
---
# Live Cockpit Metrics Implementation

This ledger tracks the bounded [Live metric contract](../../roadmap/interfaces/live-cockpit-metrics.md).
It separates local UI evidence from deployment and operational qualification.

## Implementation status

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| SSE throughput and gate/tier windows | implemented | `console/src/routes/live.metrics.ts`; `live.metrics.test.ts` 8 passed; Console typecheck | Unique business messages, event-time expiry, bounded retention, and explicit classification boundaries. |
| KPI presentation and freeze | validated | `console/tests/live-e2e/live-card-parity.spec.ts` KPI scenario 1 passed on the standard local stack | Sample update, freeze, and 1440/993/390 overflow checks; observed Live source messages were separate evidence. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-09-15 | implemented | Added source-read throughput and rolling explicit gate/tier facts, then extracted the contract from the oversized Console owner during delivery. | #1034; task commit `8a6c27b5d`; 8 focused metric tests; KPI browser scenario; typecheck. | No deployed-revision qualification is claimed. |

### Remaining work

- [x] Verify unique messages, replay exclusion, expiry, partial windows, and KPI updates with
  the focused tests and local browser scenario listed above.
- [ ] Retain exact deployed-revision evidence for source-only and control-loop metric windows
  through the governed deployment workflow.
