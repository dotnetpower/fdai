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
| Direct-response lifecycle suppression | implemented | [`semantic_turn_runtime.py`](../../../services/operator-service/src/fdai_operator_service/families/conversation/semantic_turn_runtime.py), [`command-deck-view.tsx`](../../../console/src/deck/command-deck-view.tsx), [`retrieval-trace.tsx`](../../../console/src/deck/retrieval-trace.tsx), [`use-command-deck-submit.ts`](../../../console/src/deck/use-command-deck-submit.ts), and focused Operator and Console checks | Operator does not inspect operator text or predict terminal disposition when a stream opens. A model-selected typed direct response emits `done` alone. Console shows an ephemeral compact pending row immediately after submit, expands to the detailed preparation trace only after an observed progress frame, and removes both on a direct terminal response. The browser interpolates only presentation geometry and terminal-only text reveal; it does not invent lifecycle content. |
| Operator conversation SSE shutdown | implemented | [`shutdown.py`](../../../services/operator-service/src/fdai_operator_service/streaming/shutdown.py), [`factory.py`](../../../services/operator-service/src/fdai_operator_service/families/conversation/factory.py), [`test_stream_shutdown.py`](../../../services/operator-service/tests/test_stream_shutdown.py) | Application shutdown and caller cancellation both cancel and await the in-flight source read before the stream closes. An idle source cannot block graceful shutdown or keep a detached read task alive. |
| Channel-neutral terminal reduction | implemented | [`conversation_channel.py`](../../../services/core-control-plane/src/fdai/shared/providers/conversation_channel.py), [`test_rich_contract.py`](../../../services/core-control-plane/tests/delivery/channels/test_rich_contract.py) | Focused contract tests passed 36 cases. Teams and Slack preserve the same canonical answer, limitations, evidence references, `execution_authority=false`, and monotonic confirmed update through durable replay. No production A3 publisher or governed channel runtime receipt is claimed. |
| Drawer presentation and new-conversation identity | in-progress | [`use-command-deck-sessions.ts`](../../../console/src/deck/use-command-deck-sessions.ts), [`console-routes.spec.ts`](../../../console/tests/live-e2e/console-routes.spec.ts) | The Console creates a fresh session independently of persisted drawer visibility, and the live test now isolates the request in a new conversation. A passing authenticated runtime receipt is still required. |
| Governed four-stage ontology receipt | in-progress | [`console-routes.spec.ts`](../../../console/tests/live-e2e/console-routes.spec.ts) | The external Browser Entra harness requires the exact Operator API origin, uses an unambiguous queryable-type request for its success path, reveals the request-and-projection-bound receipt, and binds the artifact to source, workspace patch, and run-configuration digests. A non-answered receipt stops before answer-only UI assertions. No new retained passing artifact supports `validated`. |
| Bilingual randomized release gate | in-progress | [`ontology-query-assurance-readiness.ts`](../../../console/tests/live-e2e/ontology-query-assurance-readiness.ts), [`ontology-query-assurance.test.ts`](../../../console/tests/live-e2e/ontology-query-assurance.test.ts) | Focused assurance tests passed 49 cases. Every governed run now requires a bounded run id and derives a stable question-scoped backend session id, so checkpoint resume preserves identity while a new run cannot reuse another run's durable semantic projection. A full cohort cannot report `production_ready=true` without evidence-complete answered turns in both English and Korean. A new passing 100-case artifact remains required. |
| Semantic clarification presentation | implemented | [`verification-presentation.ts`](../../../console/src/deck/verification-presentation.ts), [`verification-presentation.test.ts`](../../../console/src/deck/verification-presentation.test.ts) | `semantic_clarification_required` renders as `Context required`; the focused Console suite passed 13 tests. Classification covers only reason codes the control plane emits. An authenticated retained receipt remains open. |
| Verified semantic answer presentation | validated | [`semantic_turn_processor.py`](../../../services/core-control-plane/src/fdai_core_service/semantic_turn_processor.py), [`semantic_turn_presentation.py`](../../../services/operator-service/src/fdai_operator_service/families/conversation/semantic_turn_presentation.py), [`semantic_turn_runtime.py`](../../../services/operator-service/src/fdai_operator_service/families/conversation/semantic_turn_runtime.py), [`semantic-answer-presentation.spec.ts`](../../../console/tests/live-e2e/semantic-answer-presentation.spec.ts), `.fdai/live-validation/semantic-answer-presentation-244d003ef77bd37dc0041f0b6a29634cdbaacb91-post-validation/` | The bounded authenticated Web/Korean path is validated at centrally validated source revision `244d003ef` with an explicit workspace patch digest. The first and regenerated turns retained five observed phases, the same incident and technical-output digests, read-only evidence collection, no primary JSON, and `execution_authority=false`. This state does not claim Teams, Slack, the four-stage ontology runner, or the bilingual 100-case cohort. |
| Deterministic cross-channel presentation planning | implemented | `semantic_presentation_semantics.py`; `semantic_turn_processor.py`; `presentation_rows.py`; `presentation_planner.py`; `presentation_artifact_v2.py`; `presentation.py`; Console artifact and module registry; focused semantic presentation (`137 passed`), Console deck (`693 passed`), and chart browser (`4 passed`) checks | Core derives renderer-neutral semantics from verified terminal rows. Operator revalidates shape-specific roles and row invariants before selecting one of ten visualizations. Web and channel artifact boundaries apply the same bounded schema. Legacy and v2 paths preserve readable rows and exact technical values. The model cannot select a chart component. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-08-26 | implemented | Made completed source disclosure inspectable and unverified turns conversational. `SCREEN` and `RECORDS` badges retain a bounded 60 px label, record sources show row count plus at most four scalar values from the first browser-visible row, and typed unverified reasons render as localized clarification questions. The canonical terminal answer and reason remain unchanged in the turn, assurance, and run-record paths. | `current change`; focused Console checks passed 30 cases; catalog parity passed. Authenticated desktop and 390 px Browser checks showed complete badges, representative values, the Korean source-scope question, and zero row, panel, or document overflow. | No remaining implementation work for this bounded source-disclosure and clarification slice. |
| 2026-08-26 | implemented | Corrected the preparation source row after a shared 38 px source-kind column let `PROVENANCE` paint outside its badge and crowd the source title. Command Deck now owns a 64 px bounded kind column with ellipsis while preserving the exact source kind for assistive technology. | `current change`; focused source-slot visual contract passed; Console typecheck, production build, and entry bundle passed. Authenticated desktop and 390 px Browser checks measured zero badge-to-text overlap, row overflow, and document overflow. | No remaining work for this source-row regression. |
| 2026-08-26 | implemented | Smoothed browser-only answer transitions without changing the ordered event or evidence contract. An observed preparation trace expands from the compact pending height over 440 ms, and a terminal-only canonical answer reveals one bounded chunk per display frame for at most 60 frames. Hidden or unfocused tabs still finish synchronously, and reduced-motion preferences use a jump cut. | `current change`; `console/src/deck/stream-paint.ts`, `console/src/deck/use-command-deck-submit.ts`, `console/src/styles.css`, and focused Console checks passed 36 cases. The authenticated session reproduced the prior 70 px to 260 px preparation jump and confirmed that a hidden tab pauses presentation animation without changing the terminal answer. | Retain a focused authenticated active-tab observation in the broader governed Browser assurance artifact. |
| 2026-08-26 | implemented | Aligned the direct-response cleanup source contract with the shared typed source helper. The test still requires transient investigation activity removal and no longer depends on an obsolete inline string comparison. | `current change`; focused Command Deck event checks passed 11 cases. | No remaining implementation work for this regression correction. |
| 2026-08-26 | implemented | Added immediate compact Bragi feedback between submit and the first backend frame. The row is browser-local, carries no inferred phase or evidence claim, expands to the existing detailed trace only after observed progress, and is replaced by the terminal answer. Direct greetings retain no pending, retrieval, or investigation row after completion. | `current change`; focused Console visual, stream, and presenter checks passed 69 cases; typecheck passed; authenticated Browser observation saw the compact row before a 6.6-second ordinary terminal and zero pending, retrieval, or investigation rows after a direct greeting. | Retain the interaction in the governed browser assurance artifact; no additional lifecycle frame or backend intent classifier is required. |
| 2026-08-25 | implemented | Removed Operator's direct-response text classifier and all speculative acceptance and planning events. The bridge now waits for the Core projection, emits `done` alone for a model-selected direct response, and derives query progress only from a verified answered terminal. This prevents a relay from becoming a second intent owner. | `current change`; focused direct, answered, delayed-terminal, replay, and query-execution stream checks passed 8 cases. | Restart the current-source stack and retain authenticated direct and answered stream evidence. |
| 2026-08-25 | implemented | Extended direct-response lifecycle suppression from greetings to the typed `self_introduction` intent. Operator uses the same shared whole-utterance classifier as Core, validates the identity-focused answer plan and no-authority receipt, and emits no investigation frames before the terminal response. | `current change`; focused Operator presentation and lifecycle checks passed 3 cases, and Console strict receipt parsing passed 53 cases. | Restart the local stack and retain an authenticated self-introduction showing only the operator turn and direct answer. |
| 2026-08-25 | implemented | Removed the transient investigation presentation for exact greetings. Terminal cleanup was too late because Operator had already emitted acceptance and planning frames, while Console also treated `inFlight` alone as permission to render `Preparing answer`. Operator now suppresses those frames from the shared exact-greeting classification, and Console requires observed progress before rendering the preparation trace. | `current change`; focused Operator direct and ordinary lifecycle checks passed 3 cases, and focused Console stream and visual checks passed 58 cases. | Restart the local stack and retain an authenticated greeting showing only the operator turn and direct answer. |
| 2026-08-21 | implemented | Aligned the v1 browser stream regression with the existing fail-closed binding contract. A mismatched request id or missing sequence discards the rejected payload and renders the shared unavailable response rather than a sequence-gap partial answer. | `current change`; `backend-stream-v1-contract.test.ts`; focused Console contract checks passed 31 cases with the workflow authoring correction. | None for this regression correction. |
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
| 2026-08-15 | implemented | Corrected the preceding assurance evidence boundary after its ledger text landed in `6bb17dffe9f2` before the implementation files. The run-scoped session identity now lands with this history correction. | `current change`; the three ontology assurance paths cited above; focused assurance tests passed 49 cases, Console typecheck passed, and Playwright discovered the exact live test. | Retain a new exact-source 14-cell artifact, then run and retain the seeded bilingual 100-case cohort. |
| 2026-08-16 | implemented | Made Operator conversation SSE shutdown observable while the source is idle and hardened caller cancellation to cancel and await both internal wait tasks before closing the source. This prevents a detached `anext` task from racing `aclose` after client disconnect. | `current change`; `shutdown.py`, `factory.py`, and `test_stream_shutdown.py`; focused stream, conversation-family, and presentation checks passed 25 cases; Ruff and strict mypy passed. | No remaining implementation work for conversation stream shutdown cleanup. |
| 2026-08-17 | implemented | Stopped the incident candidate picker from submitting a prompt the answer cannot satisfy. Choosing a candidate opens the same incident-bound conversation as the attention badge, yet it still asked for a root cause while that answer always reports causal analysis as unimplemented. Both entry points now ask what the evidence establishes, what is missing, and the next safe read-only step. | `current change`; `messages.{en,ko}.json`; a focused test pins both prompt keys in both locales; Console i18n and grounded-reply checks passed 17 cases and typecheck passed; restoring the cause wording fails that test. | None for the incident prompt contract. |
| 2026-08-17 | implemented | Corrected the incident-candidate regression test that still expected the retired root-cause question after the catalog and both entry points adopted the evidence-bounded prompt. | `current change`; `incident-candidates.test.ts`; the focused candidate-selection test passed 4 cases. | None for this regression correction. |
| 2026-08-17 | implemented | Corrected the authenticated incident presentation gate, which still pinned the three blocks that shipped before the recorded-activity timeline existed. It now derives the expected blocks from the correlated evidence the same terminal carries, so a dropped timeline fails and an incident read that returned no rows still passes. | `current change`; `console/tests/live-e2e/semantic-answer-presentation.spec.ts`; the live Console answer observed today renders `overview`, `records`, `limitations`, and `findings`; Console typecheck passed. | Run the gate against an authenticated external stack. |
| 2026-08-18 | implemented | Made a verified list answer readable at a glance. A complete categorical result renders a bounded bar distribution, a truncated result states how many of the verified total are listed and where the rest stay, named readable fields lead the table ahead of the opaque identifier, and the summary grid fits its item count instead of leaving empty cells beside a single value. An incomplete or capped result renders no chart, so a partial count cannot read as the whole population. | `current change`; [Issue #184](https://github.com/dotnetpower/fdai/issues/184); `semantic_turn_presentation.py`, `console/src/deck/structured-reply.css`; focused Operator checks passed 394 cases with two new chart regressions; Console typecheck, Ruff, and strict mypy passed. | Retain the governed request-to-Console and bilingual randomized evidence for the chart and row-bound notice. |
| 2026-08-18 | implemented | Emitted the semantic turn's observed phases as addressable steps. The Console already renders a stepped observed-process timeline from `activity` events, but a semantic turn emitted only `status` and `verification`, so the deck held one frozen line for the whole turn. Each observed phase now also emits a bounded step, the waiting step reports running until a terminal projection exists, and it is settled before the terminal event for every disposition. No unobserved timing is synthesized and replay event ids are unchanged. | `current change`; [Issue #187](https://github.com/dotnetpower/fdai/issues/187); `semantic_turn_runtime.py`; focused Operator checks passed 394 cases with the lifecycle, held, delayed-terminal, and resume regressions updated; Ruff and strict mypy passed; a live turn rendered the stepped timeline with a running waiting step and five completed steps. | Core still publishes one terminal projection, so planning substages stay unobserved by the stream. |
| 2026-08-18 | implemented | Gave the evidence step its command detail. The Console already renders a per-step tool badge, read-only label, copyable command block, and collapsible output, but a semantic step carried no execution record so every step was a bare label. The evidence step now carries the verified query and the row counts the same terminal projection already holds; a step that executed nothing carries none, and a plan with more than one goal reports no command rather than naming one goal as the executed query. | `current change`; [Issue #188](https://github.com/dotnetpower/fdai/issues/188); `semantic_turn_runtime.py`; focused Operator checks passed 396 cases with two new execution regressions; Ruff and strict mypy passed; a live turn rendered the ObjectSet definition and its `returned_rows`/`total_rows` as JSON code blocks. | Steps still report no duration, so the execution record carries no observed interval. |
| 2026-08-19 | in-progress | Accepted the deterministic cross-channel presentation design after critique. The revision keeps v1 replay intact, makes v2 additive, separates evidence analysis from layout planning, and prevents a model or browser prose heuristic from selecting a component. | `current change`; this owner document pair. | Implement the analyzer, planner, v2 compiler, compatibility checks, and cross-channel parity tests before changing the scope state. |
| 2026-08-19 | implemented | Implemented the pure evidence-shape analyzer, deterministic decision matrix, verified-frame metadata projection, and additive v2 compiler. Unknown typed context, missing values, mixed units, unclear denominators, low cardinality, truncation, and incomplete verification degrade to exact records, a limitation, or canonical text without inventing zero. | `current change`; [Issue #234](https://github.com/dotnetpower/fdai/issues/234); focused planner, compiler, and producer/Console contract checks passed 33 cases; Ruff, formatting, and strict mypy passed. | Implement and verify the pure Teams, Slack, and injected custom capability renderers. |
| 2026-08-20 | implemented | Reused one readable-row projection in both legacy and v2 paths and extended it over the actual two-level Resource property shape. The artifact now leads with name, type, and location while preserving opaque identity and the untouched evidence row in technical details; nested tags and provider payloads never become display columns. | `current change`; [Issue #241](https://github.com/dotnetpower/fdai/issues/241); focused v2 compiler, planner, and semantic bridge checks passed 94 cases; Ruff, formatting, and strict mypy passed. | Retain authenticated desktop, constrained-desktop, and mobile evidence after the Operator restart. |
| 2026-08-20 | implemented | Corrected the preceding readable-row policy after authenticated review showed that trailing `id` and `object_type` columns still flattened the useful hierarchy. Readable tables now display operator-facing facts without those columns, identity-only results retain a visible fallback, and untouched exact rows remain available in technical details. | `current change`; `presentation_rows.py`; focused Operator presentation checks passed 82 cases, Command Deck visual checks passed 19 cases, and Console typecheck and production build passed. | Retain authenticated desktop, constrained-desktop, and mobile evidence after restarting the Operator API on this source. |
| 2026-08-21 | implemented | Extended deterministic presentation planning from broad block choice to ten ontology-grounded visualization choices. Strict v2 artifacts carry additive hints or typed scatter and heatmap blocks; Console renders the shared chart primitives, while Slack and Teams reduce them to exact facts. Unknown cross-kind hints fail closed, and older v2 artifacts round-trip without synthesized fields. | `current change`; planner and compiler checks passed 67 cases, Console artifact and registry checks passed 28 cases, channel renderer checks passed 5 cases, and Console typecheck passed. | Retain authenticated Web and governed Slack/Teams runtime receipts before raising this capability to `validated`. |
| 2026-08-22 | implemented | Wired renderer-neutral semantic metadata into the Core terminal producer and hardened the complete selection boundary. Explicit comparison roles now precede generic temporal fields; semantic field-role maps are exact per shape; ranking, part-to-whole, cumulative, and matrix variants require row-level proof; duplicate matrix coordinates and decreasing cumulative values fall back without inventing meaning. | `current change`; focused Core projector/wiring and Operator planner/compiler checks passed 90 cases, Console parser/registry/primitive checks passed 45 cases, channel reduction checks passed 13 cases, Ruff and Console typecheck passed. | Retain authenticated Web and governed Slack/Teams runtime receipts before raising this capability to `validated`. |
| 2026-08-22 | implemented | Completed three independent adversarial reviews with more than 48 checks and repeated focused hardening until no confirmed Medium-or-higher residual remained. Accepted fixes fail closed on over-bound evidence references and exact cells, require semantic labels and shared RFC 3339 ordering, and align Web with Slack/Teams for chart values, tones, roles, references, tables, text bounds, slots, envelope types, item schemas, v1 integers, and control characters. The bounded six-column readable table, valid negative comparison/scatter domains, and sparse heatmap placeholder were rechecked and retained. | `current change`; focused semantic presentation checks passed 137 cases; Console deck passed 693 cases; desktop/mobile chart Playwright passed 4 cases; Ruff, strict mypy, Console typecheck, and production build passed. | Only Low display tradeoffs remain: sparse heatmap gaps use an explicit `-`, and some safe chart fallbacks use a generic reason. Exact technical rows remain available. Governed Web and Slack/Teams runtime receipts remain required for `validated`. |

### Remaining work

- [ ] Retain a passing authenticated request-to-Console four-stage ontology receipt at a new
  repository path.
- [ ] Retain a passing seeded `0x0fda1` 100-case English/Korean randomized-assurance artifact with
  evidence-complete answered turns in both locales, without replacing the 2026-08-11 baseline.
- [ ] Record governed Teams and Slack reduction receipts before claiming channel-wide runtime
  validation.
- [x] Complete at least 20 independent visualization critiques and repeat focused hardening until
  no confirmed Medium-or-higher residual remains; 48 checks, 137 focused Python cases, 693 Console
  deck cases, and four desktop/mobile browser cases provide the current evidence.
- [x] Implement and focused-test the deterministic evidence-shape analyzer and v2 planner decision
  matrix, including v1 replay, chart fallback, and malformed or unbound artifact rejection.
- [x] Replace fenced machine JSON as the primary semantic answer with localized, deterministic
  operator-facing content while keeping the exact payload available under collapsed technical
  details and preserving the terminal verification receipt.
- [x] Emit and replay monotonic semantic lifecycle frames so detailed `Preparing answer` content
  reflects observed acceptance, planning, evidence, verification, and presentation work before
  `done`. Before the first frame, show only an ephemeral compact pending row; exact typed direct
  responses omit lifecycle frames and retain no progress row after completion.
- [x] Retain a governed authenticated Browser artifact for the completed semantic presentation and
  regeneration path, then run and retain the Korean equivalent.

## Command Deck workspace lifecycle

Full-workspace web chat opens transcript-first. A fresh empty conversation centers one composer
with the current route, screen-grounding statement, operating-domain quick starts, and bounded
suggestions. After the first operator turn or an explicit durable restore, the composer returns to
the bottom of the transcript. Conversation history is a compact header action rather than a
permanent column, and starting a new conversation closes it. The current-screen snapshot remains
internal answer grounding and doesn't render as a separate operator panel.

A general Deck open starts a fresh user-scoped conversation. Past conversations restore only after
explicit selection, while agent and incident entry points retain their bound session. The Deck
header leads with the active conversation title and route context, exposes transcript search only
when turns exist, and reduces healthy connectivity to a tooltip-backed status datum. The screen
header keeps the route context visible without repeating snapshot counts or freshness controls.
The composer keeps only attachments, question entry, and send or stop.

## Semantic terminal presentation plan

A typed `direct_response` is separate from a verified query answer. It carries one closed answer
intent, localized canonical text, and `execution_authority=false`, but no query plan, evidence
reference, verification badge, presentation artifact, or execution trajectory. Web, Teams, and
Slack preserve that same claim-free terminal response.

The current semantic path proves query execution and verification but stops before operator-facing
presentation. Core serializes the verified output into fenced JSON, Operator replays one `done`
event, and the Console correctly falls back to that canonical text because the terminal payload has
no `answer_plan`, `presentation_artifact`, or `trajectory_detail`. The existing `Preparing answer`
component is transient browser state. A compact row covers the interval between submit and the
first server frame without naming an unobserved stage. The detailed trace appears only after an
observed progress frame, so completed replay still relies on server lifecycle evidence to explain
what work occurred. When that frame arrives, the browser expands the detailed trace from the
compact row's height instead of inserting the full panel in one layout step. A terminal response
without token frames reveals the exact canonical text over at most 60 visible display frames.
Background tabs complete synchronously, and reduced-motion preferences skip both transitions.

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

## Deterministic cross-channel presentation design

The semantic presentation planner receives only a verified intent and a typed evidence-shape
analysis. The analysis records cardinality, field roles, numeric units, denominator verification,
timestamp order, missing values, truncation, limitations, and evidence references. It never reads
Markdown to infer a chart, and a model can neither name a component nor change a field role. The
planner returns a block decision; the compiler copies exact values from immutable evidence into the
versioned artifact.

### Decision table

| Evidence and intent | Selected block | Required checks | Safe fallback |
|---------------------|----------------|-----------------|---------------|
| Two through eight scalar KPIs or short states | `summary` | Unique labels and exact values | `list` |
| Exact identifiers, heterogeneous columns, row comparison, audit rows, or precision-sensitive values | `table` | Closed columns and bounded rows | `list` |
| A few heterogeneous records or label/value records | `list` | Bounded records and no required cross-row comparison | `table` |
| Observed, baseline, threshold, and status | `threshold_table` | Compatible units and explicit threshold direction | `table` plus `callout` |
| Two through twelve categorical or ranked values | `bar` | One unit, complete values, and no truncation | `table` |
| Composition or coverage | `coverage` | Verified non-zero denominator and complete numerator semantics | `table` plus `callout` |
| Three or more ordered observations of one metric | `time_series` | RFC 3339 timestamps, strict ordering, one metric, one unit, and no missing values | `table` |
| Baseline/current/target or before/after | `comparison` | Explicit roles, compatible units, and complete compared values | `table` |
| Incident events, observed activities, or handoffs | `timeline` | Ordered timestamps or an explicit verified sequence | `table` or `list` |
| Limitation, unavailable state, partial evidence, or approval boundary | `callout` | Exact reason and no inferred zero | Canonical text |
| Citation, provenance, receipt, or exact source reference | `evidence` | Reference belongs to the terminal verification receipt | Canonical text |

A chart that improves scanning while exact values remain important is followed by a collapsed
table block with the same evidence references. Unit mismatch, a missing value, an unclear
denominator, low cardinality, truncation, or incomplete verification blocks chart selection.
`unavailable` stays unavailable and never becomes zero.

### Ontology-grounded visualization selection

The ontology describes semantic roles and relationships, not chart library names. The Core
terminal producer derives one closed `semantic_shape` plus bounded field-role bindings from the
verified operation, output shape, and exact rows. It omits metadata when the relationship is not
proven. The deterministic planner maps that meaning to a visualization hint. A model may propose
typed intent for later verification, but it cannot emit a component name, override a field role,
or change a fallback.

| Verified semantic shape | Visualization hint | Artifact block | Exact fallback |
|-------------------------|--------------------|----------------|----------------|
| Ordered observations of one metric | `line` | `time_series` | Exact table |
| Ordered magnitude or accumulated change | `area` | `time_series` | Exact table; values must be nondecreasing |
| Comparable categorical values | `bar` | `bar` | Exact table |
| Ranked categorical values | `bar_list` | `bar` | Exact table; positive unique ordered ranks required |
| Parts of one verified whole | `donut` | `bar` | Exact table; one positive total and matching part sum required |
| Verified numerator and denominator | `category_bar` | `coverage` | Exact table and limitation when invalid |
| Baseline, current, target, before, or after roles | `comparison_bar` | `comparison` | Exact table |
| Ordered events or activities | `tracker` | `timeline` | Exact table or list |
| Two bound numeric axes | `scatter` | `scatter` | Exact table |
| Two categorical dimensions and one numeric value | `heatmap` | `heatmap` | Exact table; coordinates must be unique |

The planner selects `line` instead of `area` when the verified semantics do not establish
magnitude or accumulation. It selects `bar` instead of `donut` when the records do not establish
parts of one whole. A correlation shape permits a scatter plot but never upgrades correlation to
causation.

Operator treats `presentation_semantics` as a claim to verify, not as renderer authority. Only
`label/x/y` are accepted for correlation and only `row/column/value` for a matrix; the other eight
shapes accept no field-role map. Invalid roles, duplicate bindings, missing proof fields, or failed
row invariants retain the exact table and select the safer generic visualization or no chart.

### Version and failure contract

`presentation_artifact` v1 remains byte-for-byte replay compatible. Version 2 adds typed
`time_series`, `comparison`, `timeline`, `scatter`, and `heatmap` blocks plus explicit chart
descriptions, units, and additive visualization hints. A v2 consumer validates exact keys,
kind-specific hint allowlists, per-kind bounds, ordered timestamps, finite values, compatible
units, unique slots, and receipt-bound evidence references. An absent hint on an older v2 artifact
keeps its existing wire shape and deterministic renderer default. An unknown version, block,
field, hint, or reference rejects the complete artifact and renders the readable canonical text.
It never renders raw JSON as the primary answer.

Every chart block carries a semantic description and an adjacent exact-value table unless the
block itself is already an accessible table. Web can show the full module. Teams and Slack reduce
the same verified artifact through their capability renderer. A custom channel injects the same
renderer protocol rather than adding a vendor branch to the planner or core.

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

Intent-graph goal arguments stay bounded at 128 nodes and six nesting levels on both sides of the
contract. Six levels is the depth an object-set membership predicate needs: arguments, definition,
predicates, one predicate, its values array, and one value. A shallower bound silently held every
answer whose plan filtered by membership.

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
