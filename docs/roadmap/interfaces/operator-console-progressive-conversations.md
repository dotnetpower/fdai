---
title: Operator Console Progressive Conversations
---
# Operator Console Progressive Conversations

This document owns the channel-neutral branch lifecycle, ordered reduction, verified revision, and
bounded progress contract for progressive Operator Console conversations.

## Implementation status

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| Web progressive stream reduction | implemented | [`backend-stream.ts`](../../../console/src/deck/backend-stream.ts), [`backend-stream-fallback.test.ts`](../../../console/src/deck/backend-stream-fallback.test.ts), [`backend-stream-v1-contract.test.ts`](../../../console/src/deck/backend-stream-v1-contract.test.ts) | Focused tests cover ordered frames, replay rejection, branch lifecycle, confirmed revisions, and partial turns. This row does not claim Teams or Slack runtime validation. |
| Drawer presentation and new-conversation identity | in-progress | [`use-command-deck-sessions.ts`](../../../console/src/deck/use-command-deck-sessions.ts), [`console-routes.spec.ts`](../../../console/tests/live-e2e/console-routes.spec.ts) | The Console creates a fresh session independently of persisted drawer visibility, and the live test now isolates the request in a new conversation. A passing authenticated runtime receipt is still required. |
| Governed four-stage ontology receipt | in-progress | [`console-routes.spec.ts`](../../../console/tests/live-e2e/console-routes.spec.ts) | The request-to-Console assertion exists, but no new retained passing artifact supports `validated`. |
| Semantic clarification presentation | implemented | [`verification-presentation.ts`](../../../console/src/deck/verification-presentation.ts), [`verification-presentation.test.ts`](../../../console/src/deck/verification-presentation.test.ts) | `semantic_clarification_required` renders as `Context required`; the focused Console suite passed 12 tests. An authenticated retained receipt remains open. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-08-13 | in-progress | Adopted the implementation ledger; earlier provenance was not reconstructed. Stabilized the live receipt setup for persisted-open and fresh-conversation states. | Current change in [`console-routes.spec.ts`](../../../console/tests/live-e2e/console-routes.spec.ts) and this document pair; Console typecheck and targeted Playwright discovery passed. | Capture a passing authenticated four-stage receipt, then retain the seeded bilingual assurance artifact before promoting runtime assurance. |
| 2026-08-13 | implemented | Classified bounded semantic clarification as missing context instead of an unsupported claim. | `current change`; [`verification-presentation.ts`](../../../console/src/deck/verification-presentation.ts), [`verification-presentation.test.ts`](../../../console/src/deck/verification-presentation.test.ts), and the focused Console suite passed 12 tests. | Capture the authenticated four-stage receipt already listed below before claiming runtime validation. |

### Remaining work

- [ ] Retain a passing authenticated request-to-Console four-stage ontology receipt at a new
  repository path.
- [ ] Retain a passing seeded `0x0fda1` 100-case English/Korean randomized-assurance artifact
  without replacing the 2026-08-11 baseline.
- [ ] Record governed Teams and Slack reduction receipts before claiming channel-wide runtime
  validation.

## Branch contract

After deterministic scope and authority routing, the coordinator can start eligible independent
read branches concurrently. A branch is an immutable evidence operation, not a nested narrator
session or direct agent call. The presentation translator remains the conversational identity. The
accountable tool or agent owns branch evidence, while deterministic verification owns confirmed
answer segments.

| Field | Contract |
|-------|----------|
| `branch_id` | Stable within the request and derived from request id plus canonical branch kind. |
| `branch_kind` | One allowlisted read source such as `tool`, `operational`, `agent`, or `public_web`. |
| `parent_branch_id` | Optional dependency reference; independent top-level branches use `null`. |
| `status` | Monotonic `pending`, `running`, then `completed`, `unavailable`, `failed`, `timed_out`, or `cancelled`. |
| `summary` | Bounded redacted progress or terminal summary. It is not evidence authority. |
| `started_at`, `completed_at`, `duration_ms` | Optional observed timing; completion never precedes start. |
| `evidence_refs` | Bounded canonical references emitted only at terminal branch state. |

The server emits branch lifecycle frames in request `seq` order. Completion order can vary, but the
join merges immutable results in canonical branch-kind order. Rejected untrusted input becomes
`unavailable` without a traceback. Unexpected exceptions remain `failed` with warning evidence.
Successful siblings remain available. An authoritative conflict preserves both evidence sets and
marks the answer unverified. Concurrent branches never write shared context.

The first wave uses one bounded task group for eligible tool, operational, explicitly selected
agent, read-investigation agent, and deterministic public-web reads. Work whose eligibility depends
on an earlier authority result runs in a bounded follow-up wave. JSON and SSE use the same merge
helper.

## Confirmed revisions

Draft `token` frames remain provisional narration. A `confirmed` frame contains only a complete
segment rendered from evidence that passed its deterministic verifier. It includes a monotonic
segment index, answer revision, evidence references, and replacement range for a later verified
correction. A confirmed segment never cites a running branch. The terminal `done` frame is
canonical and is the only answer persisted to conversation history. An interrupted stream remains
partial and draft text never becomes confirmed content. A semantic POST stream waits for its
durable projection until the request deadline; no projection closes as a persisted typed hold,
never as an empty successful stream.

The Web reducer validates branch kind, monotonic status, timing, evidence-reference, and text bounds
before rendering. It renders each branch as a numbered investigation stage with expandable bounded
evidence. Observed command and output details stay collapsed by default. Confirmed content applies
only after queued token paint and correction revisions drain.

Token and confirmed frames match the current canonical revision. A frame from a superseded or
unannounced revision consumes its sequence position but cannot append text, replace canonical
content, invoke confirmation callbacks, or increment confirmation metrics. Confirmed revisions
advance strictly. A missing `seq` makes the turn partial even when a later `done` arrives.

Drawer visibility is presentation state and remains independent from conversation identity. A
persisted open drawer does not replay a prior turn as a new request. Starting a new conversation
creates empty canonical history and new request and idempotency identities without requiring the
operator to close and reopen the drawer.

## Channel reduction

Web, Teams, and Slack consume the same ordered event reduction:

- **Web** keeps compact branch summaries beside the in-progress answer. Details and canonical
  redacted command or output evidence stay collapsed until expanded.
- **Teams and Slack** post one response in the originating thread and apply monotonic edits. The
  final edit contains the canonical verified answer and a bounded folded branch summary.
- **Capability fallback** sends one complete terminal response when a vendor cannot edit. It does
  not describe precomputed chunks as streaming and does not change answer authority.

## Cancellation, bounds, and replay

Stream close, operator interruption, or request deadline cancels and awaits every child branch.
Cancellation remains authoritative when an optional progress observer fails; the observer error is
logged without changing the branch to failed.

Per-branch deadlines, queue capacity, branch count, event size, activity count, text bytes, and
vendor payloads stay bounded. Command and output evidence requires `redacted=true`. Summaries never
expose credentials, tenant identifiers, customer resource identifiers, or raw untrusted web
content. Durable replay stores the canonical terminal answer and revision state without rerunning a
completed read or duplicating a provider message.

## Metrics

Progress metrics retain aggregate counts and latency only: time to first progress and confirmed
content, branch kind, outcome, duration, correction, truncation, terminal completion, replay, queue
saturation, sequence gap, suppressed retry, and ambiguous channel update. They retain no prompt,
answer, branch id, channel id, principal id, or resource identifier.

Failed and timed-out reads are not retried inside the turn. Metrics are recorded only after the
bounded stream queue accepts the event. A cancellation-only lifecycle frame is not first evidence
progress. Idempotent terminal replay contributes observed time-to-first-confirmed latency and replay
count while skipping evidence retrieval, narration, and post-turn review. The browser counts
sequence gaps and partial terminals because the server cannot observe missing client frames.

## Related docs

| To learn about | Read |
|----------------|------|
| Evidence authority, replay, and stream recovery | [Console evidence and resilience](console-evidence-and-resilience.md) |
| Cross-screen evidence authority | [Operator Console view snapshot](operator-console-view-snapshot.md) |
| Conversation module ownership | [Operator Console module map](operator-console-module-map.md) |
