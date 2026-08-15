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
| Channel-neutral terminal reduction | implemented | [`conversation_channel.py`](../../../services/core-control-plane/src/fdai/shared/providers/conversation_channel.py), [`test_rich_contract.py`](../../../services/core-control-plane/tests/delivery/channels/test_rich_contract.py) | Focused contract tests passed 36 cases. Teams and Slack preserve the same canonical answer, limitations, evidence references, `execution_authority=false`, and monotonic confirmed update through durable replay. No production A3 publisher or governed channel runtime receipt is claimed. |
| Drawer presentation and new-conversation identity | in-progress | [`use-command-deck-sessions.ts`](../../../console/src/deck/use-command-deck-sessions.ts), [`console-routes.spec.ts`](../../../console/tests/live-e2e/console-routes.spec.ts) | The Console creates a fresh session independently of persisted drawer visibility, and the live test now isolates the request in a new conversation. A passing authenticated runtime receipt is still required. |
| Governed four-stage ontology receipt | in-progress | [`console-routes.spec.ts`](../../../console/tests/live-e2e/console-routes.spec.ts) | The external Browser Entra harness requires the exact Operator API origin, uses an unambiguous queryable-type request for its success path, reveals the request-and-projection-bound receipt, and binds the artifact to source, workspace patch, and run-configuration digests. A non-answered receipt stops before answer-only UI assertions. No new retained passing artifact supports `validated`. |
| Bilingual randomized release gate | in-progress | [`ontology-query-assurance-readiness.ts`](../../../console/tests/live-e2e/ontology-query-assurance-readiness.ts), [`ontology-query-assurance.test.ts`](../../../console/tests/live-e2e/ontology-query-assurance.test.ts) | Focused assurance tests passed 49 cases. Every governed run now requires a bounded run id and derives a stable question-scoped backend session id, so checkpoint resume preserves identity while a new run cannot reuse another run's durable semantic projection. A full cohort cannot report `production_ready=true` without evidence-complete answered turns in both English and Korean. A new passing 100-case artifact remains required. |
| Semantic clarification presentation | implemented | [`verification-presentation.ts`](../../../console/src/deck/verification-presentation.ts), [`verification-presentation.test.ts`](../../../console/src/deck/verification-presentation.test.ts) | `semantic_clarification_required` renders as `Context required`; the focused Console suite passed 13 tests. Classification covers only reason codes the control plane emits. An authenticated retained receipt remains open. |
| Verified semantic answer presentation | validated | [`semantic_turn_processor.py`](../../../services/core-control-plane/src/fdai_core_service/semantic_turn_processor.py), [`semantic_turn_presentation.py`](../../../services/operator-service/src/fdai_operator_service/families/conversation/semantic_turn_presentation.py), [`semantic_turn_runtime.py`](../../../services/operator-service/src/fdai_operator_service/families/conversation/semantic_turn_runtime.py), [`semantic-answer-presentation.spec.ts`](../../../console/tests/live-e2e/semantic-answer-presentation.spec.ts), `.fdai/live-validation/semantic-answer-presentation-244d003ef77bd37dc0041f0b6a29634cdbaacb91-post-validation/` | The bounded authenticated Web/Korean path is validated at centrally validated source revision `244d003ef` with an explicit workspace patch digest. The first and regenerated turns retained five observed phases, the same incident and technical-output digests, read-only evidence collection, no primary JSON, and `execution_authority=false`. This state does not claim Teams, Slack, the four-stage ontology runner, or the bilingual 100-case cohort. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-08-13 | in-progress | Adopted the implementation ledger; earlier provenance was not reconstructed. Stabilized the live receipt setup for persisted-open and fresh-conversation states. | Current change in [`console-routes.spec.ts`](../../../console/tests/live-e2e/console-routes.spec.ts) and this document pair; Console typecheck and targeted Playwright discovery passed. | Capture a passing authenticated four-stage receipt, then retain the seeded bilingual assurance artifact before promoting runtime assurance. |
| 2026-08-13 | implemented | Classified bounded semantic clarification as missing context instead of an unsupported claim. | `current change`; [`verification-presentation.ts`](../../../console/src/deck/verification-presentation.ts), [`verification-presentation.test.ts`](../../../console/src/deck/verification-presentation.test.ts), and the focused Console suite passed 12 tests. | Capture the authenticated four-stage receipt already listed below before claiming runtime validation. |
| 2026-08-14 | implemented | Restricted context classification to reason codes the control plane actually emits, replacing two speculative literals with the emitted `operational_case_context_missing`. | `current change`; [`verification-presentation.ts`](../../../console/src/deck/verification-presentation.ts), [`verification-presentation.test.ts`](../../../console/src/deck/verification-presentation.test.ts), and the focused Console suite passed 13 tests. | A console incident investigation prompt still resolves to clarification because the semantic query manifest exposes no incident competency; that capability gap needs its own design pass. |
| 2026-08-14 | in-progress | Recorded the verified semantic terminal presentation gap after an authenticated incident turn returned an evidence-bound receipt but exposed fenced JSON as the primary answer with no progressive server frames. | Current source paths in the scope table and the authenticated Browser observation; no runtime artifact was retained and no product code changed in this documentation update. | Complete the semantic presentation work packages and retain the exit evidence below. |
| 2026-08-14 | implemented | Split immutable semantic machine output from localized canonical answers, added replayable observed lifecycle frames, compiled receipt-bound incident presentation and answer plans, preserved exact output under collapsed run details, and retained verified incident identity across replay and regeneration. | Current source and focused checks in the scope table; an unretained authenticated Browser Entra observation showed `Preparing answer` from server-observed planning, then a verified three-record incident summary, explicit causal and evidence limitations, a read-only evidence-collection next step, collapsed exact JSON, and the same verified result after regeneration. | Retain a governed authenticated artifact, run the Korean equivalent, and record Teams and Slack reduction receipts before claiming channel-wide runtime validation. |
| 2026-08-14 | implemented | Propagated the canonical top-level locale, bounded regeneration history to the original question boundary, replayed the verified semantic request identity once, bound that identity to Operator idempotency, and added bounded retries for repeated Azure throttling or schema-invalid candidates. | `current change`; focused Console stream, normalizer, session, and event checks passed 128 cases; the Azure semantic-planning adapter passed 5 cases; Console typecheck and task-scoped Ruff passed. A retained authenticated Korean Browser working-tree run passed both turns with `request_identity_replayed=true` and exactly one five-stage Core planning cycle. | Commit and centrally validate this change, then retain an exact-source authenticated Browser artifact. Teams and Slack reduction receipts remain open. |
| 2026-08-14 | implemented | Deep-cloned the original view snapshot at submit time so route refresh cannot mutate the content bound to a verified request replay. | `current change`; the focused Console session suite passed 16 cases, Console typecheck passed, and the request snapshot mutation regression preserved nested fact and record values. | Retain a post-validation authenticated Browser artifact after provider capacity permits one clean first turn. |
| 2026-08-14 | validated | Retained the authenticated Korean semantic presentation and regeneration artifact after central validation of the implementation commits. | Source revisions `7f2b740b1` and `244d003ef` have central receipts. The retained post-validation artifact records `passed=true`, two protected requests, five progress phases, three presentation slots, matching request, binding, and technical-output digests, read-only authority, and one five-stage Core planning cycle. | Teams and Slack reduction receipts, the separate four-stage receipt, and the bilingual 100-case cohort remain open. |
| 2026-08-14 | implemented | Added explicit Teams and Slack parity coverage for the channel-neutral terminal reducer. | `current change`; [`test_rich_contract.py`](../../../services/core-control-plane/tests/delivery/channels/test_rich_contract.py) passed 36 focused cases and preserved canonical content, limitations, evidence references, no execution authority, and the final confirmed update for both channel kinds. | Implement and exercise the production A3 publishers before retaining governed Teams and Slack runtime receipts. |
| 2026-08-14 | in-progress | Closed a randomized-assurance false positive that classified a 100-case cohort with zero answered turns as production-ready. | `current change`; [`ontology-query-assurance.test.ts`](../../../console/tests/live-e2e/ontology-query-assurance.test.ts) passed 40 focused cases, including zero-answer and incomplete-evidence rejection. | Retain a new authenticated 100-case artifact with at least one evidence-bound answered turn before changing release readiness. |
| 2026-08-14 | in-progress | Strengthened the randomized release gate so a one-locale-only answer set cannot qualify as bilingual production readiness. | `current change`; [`ontology-query-assurance.test.ts`](../../../console/tests/live-e2e/ontology-query-assurance.test.ts) passed 41 focused cases, including missing-locale rejection. | Retain a new authenticated 100-case artifact with evidence-complete answered turns in both locales before changing release readiness. |
| 2026-08-14 | implemented | Bound four-stage receipt disclosure to the terminal semantic request instead of clicking translated nested summaries through progressive rerenders. | `current change`; focused Playwright discovery passed. Full Console typecheck remained blocked by concurrent incident-route working-tree errors outside this change. | Commit and centrally validate the selector repair, then retain a passing authenticated four-stage artifact. |
| 2026-08-14 | implemented | Strengthened the four-stage harness to bind both terminal request and projection identity, and to stop cloned SSE evidence capture at the first complete `done` frame instead of waiting for transport EOF after the application closes its reader. | `current change`; exact Playwright discovery and focused esbuild compilation passed. Authenticated probes advanced through terminal capture, but runtime restarts and an unavailable semantic planner prevented a retained passing artifact. | Retain a stable authenticated four-stage artifact after the current local Core and Operator processes remain ready for the bounded request. |
| 2026-08-14 | implemented | Made the four-stage harness stop immediately when a terminal semantic receipt is not answered, before answer-only UI assertions can obscure the hold. | `current change`; [`console-routes.spec.ts`](../../../console/tests/live-e2e/console-routes.spec.ts); exact Playwright discovery and focused esbuild compilation passed. The diagnostic includes the disposition, unavailable reason, request id, projection id, and semantic route. | Re-run the authenticated four-stage path on stable source and preserve only a passing, provenance-bound artifact. |
| 2026-08-14 | in-progress | Re-ran the authenticated four-stage path on stable source and confirmed that a typed hold stops before answered-only assertions. | Centrally validated source revision `48b5d12bd6d2610a09acd756447e5108384cecd6` and stable workspace patch digest `sha256:e509b6af05032a4875084e0978b2914c37bf2000a7ffafcfa58a8a0e50fd34d6`; the runner reported `disposition=held` and `unavailable_reason=semantic_planner_unavailable`. The Core plan candidate exhausted bounded retries after HTTP 429 responses. No failed artifact was retained. | Restore semantic-planning model capacity, then rerun the four-stage path and the 14-cell bilingual answer-coverage gate without weakening either contract. |
| 2026-08-14 | implemented | Made external four-stage evidence fail fast without an explicit Operator API origin, narrowed the success-path question to the complete queryable type set, and embedded source, workspace patch, and canonical run-configuration provenance in the artifact. | `current change`; [`console-routes.spec.ts`](../../../console/tests/live-e2e/console-routes.spec.ts); exact Playwright discovery, 52 focused assurance and provenance tests, and Console typecheck passed. | Obtain central validation, then retain a passing authenticated artifact before changing the scope state to `validated`. |
| 2026-08-15 | implemented | Stopped a presentation artifact from removing answer content. The general verified-query artifact now projects the returned rows and per-node results instead of only how many output nodes existed, and the reply keeps the Markdown answer when an artifact carries nothing beyond its overview summary. | `current change`; [`presentation-artifact.ts`](../../../console/src/deck/presentation-artifact.ts) and [`grounded-reply.tsx`](../../../console/src/deck/grounded-reply.tsx); focused Console deck tests passed 76 cases, Console typecheck passed, and the Operator bridge suite passed 48 cases. | Confirm the rendered result on the authenticated local Console. |
| 2026-08-15 | implemented | Bound each randomized assurance run and question to a unique backend session identity so a new run cannot consume a durable projection from an earlier run, while checkpoint resume keeps the same identity. | `current change`; [`ontology-query-assurance.ts`](../../../console/tests/live-e2e/ontology-query-assurance.ts), [`ontology-query-assurance.spec.ts`](../../../console/tests/live-e2e/ontology-query-assurance.spec.ts), and [`ontology-query-assurance.test.ts`](../../../console/tests/live-e2e/ontology-query-assurance.test.ts); focused assurance tests passed 49 cases, Console typecheck passed, and Playwright discovered the exact live test. | Retain a new exact-source 14-cell artifact, then run and retain the seeded bilingual 100-case cohort. |
| 2026-08-15 | implemented | Aligned the automatic incident prompt with what the system can answer and fixed the briefing's article agreement. The prompt requested a cause while incident answers hardcode causal analysis as unavailable, so every automatic investigation asked an unanswerable question; it now asks what the evidence establishes, what is missing, and the next safe read-only step. The briefing rendered `a unknown` for an unknown severity. | `current change`; focused Console incident attention and catalog tests passed 8 cases, catalog parity verified 16 pairs, and Console typecheck passed. | Verify the reworded automatic prompt on the authenticated local Console. |

### Remaining work

- [ ] Retain a passing authenticated request-to-Console four-stage ontology receipt at a new
  repository path.
- [ ] Retain a passing seeded `0x0fda1` 100-case English/Korean randomized-assurance artifact with
  evidence-complete answered turns in both locales, without replacing the 2026-08-11 baseline.
- [ ] Record governed Teams and Slack reduction receipts before claiming channel-wide runtime
  validation.
- [x] Replace fenced machine JSON as the primary semantic answer with localized, deterministic
  operator-facing content while keeping the exact payload available under collapsed technical
  details and preserving the terminal verification receipt.
- [x] Emit and replay monotonic semantic lifecycle frames so `Preparing answer` reflects observed
  acceptance, planning, evidence, verification, and presentation work before `done`.
- [x] Retain a governed authenticated Browser artifact for the completed semantic presentation and
  regeneration path, then run and retain the Korean equivalent.

## Semantic terminal presentation plan

The current semantic path proves query execution and verification but stops before operator-facing
presentation. Core serializes the verified output into fenced JSON, Operator replays one `done`
event, and the Console correctly falls back to that canonical text because the terminal payload has
no `answer_plan`, `presentation_artifact`, or `trajectory_detail`. The existing `Preparing answer`
component is transient browser state. It can show only while `inFlight` is true and receives no
semantic stage events, so completed replay cannot explain what work occurred.

The machine result remains authoritative and replayable, but it isn't the primary human answer.
Implement the correction in five bounded work packages:

| Work package | Required change | Exit evidence |
|--------------|-----------------|---------------|
| Machine and presentation split | Keep exact semantic outputs and digests as typed technical data. Compile a localized canonical Markdown answer from verified server-owned slots. Never ask a model to rewrite values or evidence references. | Contract tests prove the human answer contains only values present in the immutable result, while technical details round-trip the exact machine payload and receipt. |
| Honest progress | Emit additive, monotonic lifecycle frames for accepted, planning, evidence execution, verification, and presentation phases. Operator may report only locally observed acceptance or waiting until Core publishes a stage. Persist enough sequence state for reconnect replay without rerunning work. | Stream tests prove ordered status frames precede `done`, reconnect doesn't duplicate a phase, cancellation remains terminal, and no unobserved stage is fabricated. |
| Incident narrative | Render sections for verified facts, causal status, evidence gaps, and the next safe step. A missing causal contract says that root cause isn't available. Missing impact or citation evidence remains explicit. Evidence collection is the default next step; an action draft appears only when the operator explicitly requests a draft. | English and Korean fixtures prove no cause is inferred from an `rca.hypothesis` record, every gap is visible, and `execution_authority=false` remains unchanged. |
| Console and channel reduction | Render verified summary, limitation, evidence links, and optional table blocks through `presentation_artifact` v1. Put raw JSON and digests in collapsed technical details. Web, Teams, and Slack use the same canonical content; unsupported artifacts fall back to readable Markdown rather than raw JSON. | Console parser and renderer tests reject unknown or receipt-unbound blocks. Channel tests preserve the same facts, limitations, and authority while applying vendor bounds. |
| Authenticated assurance | Exercise a fresh bound incident turn, durable replay, reconnect, and Korean equivalent after the focused contract tests pass. | A governed Browser artifact shows `Preparing answer` before terminal completion, a readable verified final answer with no primary fenced JSON, collapsed technical details, explicit evidence gaps, no invented cause, and the same answer after replay. |

For the currently observed incident shape, a compliant final answer should explain that three
correlated audit records were verified, causal analysis isn't available, impact and grounded
citation evidence are missing, and the next safe step is to collect those missing evidence classes
before proposing a change. The exact identifiers, timestamps, records, and digests remain available
as technical evidence rather than leading the conversation.

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
