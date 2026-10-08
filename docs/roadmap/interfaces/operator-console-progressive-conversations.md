---
title: Operator Console Progressive Conversations
---
# Operator Console Progressive Conversations

This document owns the channel-neutral branch lifecycle, ordered reduction, verified revision, and
bounded progress contract for progressive Operator Console conversations.

Screen conversations in the Command Deck receive a route-scoped `ViewSnapshot`. Every registered panel
provides its identity and purpose as a fallback during loading, error, and transition states. Routes
that expose verified visible evidence can replace that fallback with bounded facts and records.
Every specialized snapshot declares a shared-catalog glossary alongside its purpose so route context
stays self-describing without browser-inferred terminology.
When a typed incident binding owns an automatic investigation prompt, the Deck omits the active
panel's facts, records, glossary, and headline from that submission. It retains only minimal locale,
route, and principal metadata plus the exact server-verified incident binding, so current-screen
context cannot appear as incident evidence.

Conversation restoration reads the principal-scoped semantic request/result journal as well as
legacy conversation rows. A cached transcript ending with an unanswered operator turn is
incomplete and must not suppress that read. Recovery renders the stored terminal through the
same validated presenter; it never resends the question, creates a model call, or rewrites history.
New input or a session switch invalidates an in-flight restoration before it can replace the view.
The local CLI uses the same bounded `POST /chat/stream` SSE contract and accepts only one final
validated `done` terminal. It preserves multiline `data:` fields, normalizes CRLF framing, validates
UTF-8 and timestamps, counts limits in bytes, and cancels malformed streams. An error or second
terminal, oversized stream, missing terminal, or mismatched content type fails closed instead of
interpreting the proposal-only `POST /chat` response as an answer. The Live hub assigns sequence and
offers each nonblocking delivery under one lock so concurrent publishers cannot invert cursor order.

Typed test-context drafts retain exact targets, expected bounds, aware intervals, and source receipts
through HTTP, streaming, and replay. Strict decoding rejects extra authority fields and invalid dates;
only an `action_draft` result carries this candidate. The Deck displays the candidate and permits a
separate read-only lookup of the requesting principal's existing command status. That receipt is
not bound to the displayed draft, and historical application is not current authorization.
Scope/policy selection and authenticated submission controls remain unavailable pending the reviewed
mapping and independent proof issuer; see [case-history delivery](../rules-and-detection/prediction-learning-and-case-history.md).
Operator composition imports the unchanged test-context worker through its existing durable-outbox
facade; this grouping changes neither worker identity, readiness, publication, nor authority.
Replay regression fixtures generate synthetic UUIDv4 identities at test time; the production
receipt parser still rejects invalid identity shapes and never treats fixture identifiers as evidence.

Validated advisory terminals render their complete canonical text immediately. They do not replay
an artificial typewriter after the server has already completed review. Ordinary streamed deltas
retain their pacing and ordering, and malformed advisory metadata cannot select this fast path.

The Operator signals waiting streams after a terminal result is validated and durably committed.
Bounded terminal markers prevent a commit-before-wait race from adding the one-second replay poll.
The signal carries no answer or authority: readers still load the authoritative result, and polling
remains the recovery path when notifications are absent.

## Implementation status

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| Test-context draft propagation | implemented | `console/src/deck/test-context.test.ts`; owning draft/advisory/transcript/stream checks: 128 passed; production and test TypeScript compilers passed | Candidate-only data survives server and local replay without gaining authority. |
| Test-context candidate display and principal-owned command status | in-progress | `console/src/deck/test-context-review.tsx`, `test-context-status.ts`, focused decoder and synthetic browser checks | Exact draft fields and a separate receipt lookup are displayed. No reviewed scope/policy selection, submission, independent review, or current-authority projection exists. |
| Adaptive answer source and replay presentation | implemented | `adaptive-answer.test.ts` passed 33 cases; `turn-history.test.ts` and `command-deck.session.test.ts` passed 20 cases; Console typecheck and build passed | General knowledge has no blanket query receipt. Goal-local support and separate draft explanations survive streaming and restoration; malformed streams clear unverified text. Browser runtime validation is separate. |
| General starter immediate submission | implemented | `general-conversation-intro.tsx`; `command-deck-view.tsx`; `conversation-entry.spec.ts` | All three bilingual starters submit the displayed question through the normal context-aware path on pointer or keyboard activation. Tooltips explain immediate submission. Six starter cases and both existing entry scenarios pass with synthetic responses, not live model calls. |
| Web progressive stream reduction | implemented | Operator `semantic_turn_runtime.py`; [`backend-stream.ts`](../../../console/src/deck/backend-stream.ts); [`use-command-deck-lifecycle.test.ts`](../../../console/src/deck/use-command-deck-lifecycle.test.ts); focused Operator and Console stream checks | Verified answered projections emit at most 64 cumulative receipt-bound confirmed segments before `done`. Raw tokens stay hidden until terminal agreement, and receipt, text, revision, malformed-frame, interruption, error, and sequence failures retract preterminal content. Cancellation preserves observed investigation activity and evidence while retracting only provisional answer text and confirmation. This row does not claim Browser, Teams, or Slack runtime validation. |
| Direct-response lifecycle suppression | implemented | [`semantic_turn_runtime.py`](../../../services/operator-service/src/fdai_operator_service/families/conversation/semantic_turn_runtime.py), [`command-deck-view.tsx`](../../../console/src/deck/command-deck-view.tsx), [`retrieval-trace.tsx`](../../../console/src/deck/retrieval-trace.tsx), [`use-command-deck-submit.ts`](../../../console/src/deck/use-command-deck-submit.ts), and focused Operator and Console checks | Operator does not inspect operator text or predict terminal disposition when a stream opens. A model-selected typed direct response emits `done` alone. Console shows an ephemeral compact pending row immediately after submit, expands to the detailed preparation trace only after an observed progress frame, and removes both on a direct terminal response. The browser interpolates only presentation geometry and terminal-only text reveal; it does not invent lifecycle content. |
| Contract-backed starter questions | implemented | `intro-suggestions.ts`; bilingual Console catalogs; `semantic_operational_summary_planning.py`; question-bank artifacts; focused Core, Console, and question-bank checks | The empty Deck exposes five reviewed Resource state, Resource Health, and Service Health questions. An accepted unambiguous typed function intent can reuse a deterministic verified frame without a second model call. Unimplemented screen-summary, tier-mix, approval, failure-cause, and opportunity questions are not presented as ready examples. |
| Incident-bound context isolation | implemented | `incident-attention.tsx`; `use-incident-attention-stream.ts`; `grounded-reply.tsx`; `command-deck.tsx`; `use-command-deck-events.ts`; Operator semantic-turn boundary; focused Console and Operator checks; authenticated Browser Entra request inspection | The attention stream rejects non-string identity and status fields before rendering a selectable incident. A malformed explicit binding is rejected before session switching or automatic submission, and Operator requires both `incident_id` and `correlation_id` before forwarding the bound context. Each explicit top-bar or answer-candidate selection starts a fresh incident-bound conversation even when another conversation retains a draft. Its Incident label remains stable, and the default narrator is not sent as an explicit target agent; only a validated `selectedAgent` requests an agent-bound conversation. The submitted investigation includes the exact incident binding without Dashboard facts or records. The verified answer reads `query.incident_evidence`; route metadata remains presentation context and never becomes answer evidence. |
| General and current-screen conversation separation | implemented | `conversation-context.ts`; `general-conversation-intro.tsx`; `command-deck.tsx`; `navigation-shell.tsx`; `conversation-entry.spec.ts`; focused Deck checks | The Activity Bar opens or resumes the tab's general conversation, while the bottom and keyboard launchers select the current screen's separate conversation. General questions omit screen evidence unless explicitly attached. Drafts, captured context, and layout preferences remain separate. Action drafts retain the signed-in review hint and separate executor authority. |
| Operator conversation SSE shutdown | implemented | [`shutdown.py`](../../../services/operator-service/src/fdai_operator_service/streaming/shutdown.py), [`factory.py`](../../../services/operator-service/src/fdai_operator_service/families/conversation/factory.py), [`test_stream_shutdown.py`](../../../services/operator-service/tests/test_stream_shutdown.py) | Application shutdown and caller cancellation both cancel and await the in-flight source read before the stream closes. An idle source cannot block graceful shutdown or keep a detached read task alive. |
| Channel-neutral terminal reduction | implemented | [`conversation_channel.py`](../../../services/core-control-plane/src/fdai/shared/providers/conversation_channel.py), [`test_rich_contract.py`](../../../services/core-control-plane/tests/delivery/channels/test_rich_contract.py) | Focused contract tests passed 36 cases. Teams and Slack preserve the same canonical answer, limitations, evidence references, `execution_authority=false`, and monotonic confirmed update through durable replay. No production A3 publisher or governed channel runtime receipt is claimed. |
| Drawer presentation and new-conversation identity | in-progress | [`use-command-deck-sessions.ts`](../../../console/src/deck/use-command-deck-sessions.ts), [`command-deck-header.tsx`](../../../console/src/deck/command-deck-header.tsx), [`console-routes.spec.ts`](../../../console/tests/live-e2e/console-routes.spec.ts) | The Console creates a fresh session independently of persisted drawer visibility, and the live test now isolates the request in a new conversation. Header model selection uses the shared accessible Tooltip instead of a browser-native title bubble. A passing authenticated runtime receipt is still required. |
| Proactive ownership handover conversation | implemented | `handover_runtime.py`; `handover_binding.py`; `console/src/handover-*`; Command Deck session and document-upload paths; focused Operator and Console checks | A live accountable ownership match can open one fatigue-bounded agent conversation. The server verifies and durably binds principal, goal, session, and agent, suppresses invitations while incident or approval work is active, and marks goals stale when admitted evidence is later unavailable. Deployment receipts remain open. |
| Governed four-stage ontology receipt | in-progress | [`console-routes.spec.ts`](../../../console/tests/live-e2e/console-routes.spec.ts) | The external Browser Entra harness requires the exact Operator API origin, uses an unambiguous queryable-type request for its success path, reveals the request-and-projection-bound receipt, and binds the artifact to source, workspace patch, and run-configuration digests. A non-answered receipt stops before answer-only UI assertions. No new retained passing artifact supports `validated`. |
| Bilingual randomized release gate | in-progress | [`ontology-query-assurance-readiness.ts`](../../../console/tests/live-e2e/ontology-query-assurance-readiness.ts), [`ontology-query-assurance.test.ts`](../../../console/tests/live-e2e/ontology-query-assurance.test.ts) | Focused assurance tests passed 49 cases. Every governed run now requires a bounded run id and derives a stable question-scoped backend session id, so checkpoint resume preserves identity while a new run cannot reuse another run's durable semantic projection. A full cohort cannot report `production_ready=true` without evidence-complete answered turns in both English and Korean. A new passing 100-case artifact remains required. |
| Semantic clarification presentation | implemented | [`verification-presentation.ts`](../../../console/src/deck/verification-presentation.ts), [`grounded-reply.tsx`](../../../console/src/deck/grounded-reply.tsx), and focused Console tests | `semantic_clarification_required` renders as `Context required` while preserving a bounded server-authored question as the primary answer. A malformed or absent question uses the localized fallback. Classification covers only reason codes the control plane emits. An authenticated retained receipt remains open. |
| Typed evidence-hold presentation | validated | [`backend-stream.ts`](../../../console/src/deck/backend-stream.ts), [`grounded-reply.tsx`](../../../console/src/deck/grounded-reply.tsx), focused stream and Console tests, Core partial-causal presentation checks, and authenticated standard-Console browser evidence | `semantic_evidence_held` and `semantic_evidence_incomplete` preserve the bounded canonical terminal answer only when verification names a nonempty server authority, completed checks retain nonempty evidence, and a same-request held receipt reports `authoritative_evidence_unavailable` with matching reason, plan, execution, and no-authority digests. Derived function receipts preserve their typed authority inputs so Operator can validate the exact source lineage instead of relabeling a valid hold as an unsupported claim. Its assurance observation must also record a performed read, read-only authority, and a non-fresh evidence posture. When incomplete evidence also contains recorded conflicts, the Web footer keeps incompleteness as the primary blocker and displays the conflict as a separate secondary fact. An unresolved exact name may display same-type observed suggestions, while clearly stating that no candidate was selected automatically. The verification reason identifies a typed-hold claim before receipt validation, so a missing, cross-request, mismatched, or authority-free receipt cannot bypass rejection. Missing or whitespace-only canonical terminal text is rejected before queued tokens flush; a monotonic unverified revision and pump-generation invalidation retract any already painted draft and stop locally buffered burst tokens before the localized fallback. |
| Conversation assurance review identity | implemented | `backend-normalizers.ts`; `backend-stream.ts`; `command-deck-session.ts`; `grounded-reply.tsx`; focused stream, restoration, and reply checks | A terminal answer carries a strictly validated server assessment identity through live reduction and durable replay. The answer-quality link uses that identity instead of the browser-only presentation turn id. |
| Semantic model transparency | implemented | `semantic_planning.py`; `semantic_planning_cascade.py`; Azure semantic planning adapter; `semantic_turn_processor.py`; `semantic_turn_presentation.py`; focused Core and Operator checks | Every completed semantic judgment, frame, and plan model call retains bounded measured model, duration, and token metadata for presentation. Request and response content is projected only when the request opts in, remains deterministically redacted and bounded, and never becomes planning evidence or execution authority. |
| Live semantic query progress | implemented | `SemanticQueryProgress`; `query_execution.py`; Core semantic consumer; Operator semantic bridge; focused progress cohort (`25 passed`) | Core emits only actual verified query-node start and terminal observations on a separate best-effort topic. Operator renders the real internal query and discards transient progress when the authoritative terminal receipts arrive. Progress remains bounded, read-only, and fixed to `execution_authority=false`. An authenticated Command Deck receipt remains open. |
| Verified semantic answer presentation | validated | [`semantic_turn_processor.py`](../../../services/core-control-plane/src/fdai_core_service/semantic_turn_processor.py), [`semantic_turn_presentation.py`](../../../services/operator-service/src/fdai_operator_service/families/conversation/semantic_turn_presentation.py), [`semantic_turn_runtime.py`](../../../services/operator-service/src/fdai_operator_service/families/conversation/semantic_turn_runtime.py), [`semantic-answer-presentation.spec.ts`](../../../console/tests/live-e2e/semantic-answer-presentation.spec.ts), `.fdai/live-validation/semantic-answer-presentation-244d003ef77bd37dc0041f0b6a29634cdbaacb91-post-validation/` | The bounded authenticated Web/Korean path is validated at centrally validated source revision `244d003ef` with an explicit workspace patch digest. The first and regenerated turns retained five observed phases, the same incident and technical-output digests, read-only evidence collection, no primary JSON, and `execution_authority=false`. This state does not claim Teams, Slack, the four-stage ontology runner, or the bilingual 100-case cohort. |
| Deterministic cross-channel presentation planning | implemented | `semantic_presentation_semantics.py`; `semantic_turn_processor.py`; `presentation_rows.py`; `presentation_planner.py`; `presentation_artifact_v2.py`; `presentation.py`; Console artifact and module registry; focused semantic presentation (`137 passed`), Console deck (`693 passed`), and chart browser (`4 passed`) checks | Core derives renderer-neutral semantics from verified terminal rows. Operator revalidates shape-specific roles and row invariants before selecting one of ten visualizations. Web and channel artifact boundaries apply the same bounded schema. Legacy and v2 paths preserve readable rows and exact technical values. The model cannot select a chart component. |
| Current-screen context publication | implemented | [`context.tsx`](../../../console/src/deck/context.tsx), [`app.tsx`](../../../console/src/app.tsx), [`view-contract.test.ts`](../../../console/src/routes/view-contract.test.ts), focused Console context and route checks, desktop browser inspection | Every registered panel identifies itself during loading, unavailable, error, and route-transition states. Specialized publishers can replace the fallback with bounded visible facts and a shared-catalog glossary without carrying a previous route's snapshot forward. |
| Work progress contract parsing | implemented | [`work-progress-contract.ts`](../../../console/src/deck/work-progress-contract.ts), [`trajectory-detail.ts`](../../../console/src/deck/trajectory-detail.ts), [`conversation-trajectory-presentation.ts`](../../../console/src/deck/conversation-trajectory-presentation.ts), [`adaptive-investigation-fixtures.test.ts`](../../../console/src/deck/adaptive-investigation-fixtures.test.ts); Console deck suite (`1045 passed`) and typecheck | The Console accepts optional `work_progress_shape`, `turn_budget`, and `context_receipts` fields, drops only a malformed field, lets a contradicting pinned shape fall back to the timeline, and replays milestones as recorded. The shared synthetic fixtures in `mocks/ui/fixtures/adaptive/` parse losslessly. |
| Server emission of work progress fields | implemented | [`semantic_work_progress.py`](../../../packages/service-contracts/src/fdai_service_contracts/semantic_work_progress.py), [`work_progress.py`](../../../services/core-control-plane/src/fdai/core/conversation/work_progress.py), [`semantic_work_progress_projection.py`](../../../services/core-control-plane/src/fdai_core_service/semantic_work_progress_projection.py), [`semantic_progress_relay.py`](../../../services/operator-service/src/fdai_operator_service/families/conversation/semantic_progress_relay.py), [`semantic_work_progress_presentation.py`](../../../services/operator-service/src/fdai_operator_service/families/conversation/semantic_work_progress_presentation.py), [`semantic_trajectory_presentation.py`](../../../services/operator-service/src/fdai_operator_service/families/conversation/semantic_trajectory_presentation.py); focused contract, Core, and Operator work progress tests (`54 passed`) and the Console golden round trip | Core pins the verified read plan before it runs, publishes the pin ahead of the first node progress, and persists the pin, the enforcing adaptive turn budget, and the applied model-tier receipt. Operator sends one `work_progress` frame before the first query activity and keeps the Console envelope. No authenticated runtime receipt is claimed. |
| Console work progress consumption and investigation roles | implemented | [`backend-stream.ts`](../../../console/src/deck/backend-stream.ts), [`use-command-deck-submit.ts`](../../../console/src/deck/use-command-deck-submit.ts), [`investigation-turn-state.ts`](../../../console/src/deck/investigation-turn-state.ts), [`investigation-roles.tsx`](../../../console/src/deck/investigation-roles.tsx), [`investigation-timeline.tsx`](../../../console/src/deck/investigation-timeline.tsx), [`use-command-deck-lifecycle.ts`](../../../console/src/deck/use-command-deck-lifecycle.ts), [`transcript-store.ts`](../../../console/src/deck/transcript-store.ts); [`deck-conversation-layer.spec.ts`](../../../console/tests/e2e/deck-conversation-layer.spec.ts) | The Console accepts the live pin before the first read, holds the answer across a pause between waves until the planned reads are observed, names the plan on the lead panel, and shows the budget and context receipts only after the answer settles. A stop is recorded on the panels, so an unfinished read is shown as stopped instead of unavailable. Wave rows stay unrendered because reads don't carry their planned wave. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-10-08 | implemented | Stopped the running-step spinner from sinking and bouncing, and aligned table answers. The step mark centered itself with `transform: translateY(-50%)`, which the spin animation's `transform: rotate()` replaced, so a running mark sat 8 px low and jumped while it spun; it now centers with the independent `translate` property. A table answer's prose kept a 72ch measure while its table broke out to 1080 px; the table now fits the reading column with cells wrapping between words, and prose beside a table uses the table's width. This supersedes the earlier table breakout. | `current change`; `console/src/styles.css` and `command-deck-workspace-visual.test.ts`; `npx vitest run src` (3776 passed); Console typecheck; on the local Console, 24 samples of a running mark kept a 0 px vertical offset at the completed marks' x; the answer, prose, table wrapper, and preceding turn shared x and width at 1440x900 (323, 840 px), 993x641 (116, 808 px), 390x844, and docked (401 px), with no cell split mid-word and no overflow. | None for these layout repairs. |
| 2026-10-08 | implemented | Explained why a partial state answer's Resource scope is incomplete. The answer showed only the code `resource_scope_incomplete`, because the state function dropped the snapshot's typed source reason and the code had no reviewed explanation. The function now reports `resource_scope_incomplete+inventory_observation_pending` and similar pairs, and both parts render in the operator's language with the exact code kept. | `current change`; `resource_state_queries.py`, `semantic_source_limitations.py`, and their tests; `eval/golden-dataset/corpus-manifest.json` regenerated; Core ontology-platform, conversation, semantic, and prompt tests (4952 passed). | None for this explanation. |
| 2026-10-08 | implemented | Kept a full-workspace answer in the reading column. An answer with a wide record table widened the whole turn to 1080 px, so its prose started 120 px left of the question and the work panel. Only the table wrapper now breaks out, centered and bounded by the transcript container. | `current change`; `console/src/styles.css` and `command-deck-workspace-visual.test.ts`; `npx vitest run src` (3776 passed); Console typecheck; on the local Console the answer turn matched the preceding turn's x and width at 1440x900 (323, 840 px), 993x641 (116, 808 px), and 390x844 (24, 332 px), with the table at 1080 px and 889 px and no overflow. | None for this layout repair. |
| 2026-10-08 | implemented | Stopped the work panel from shifting while an answer is planned. A running activity opened its detail panel, so every running model call showed a lifecycle panel with no evidence beyond its row, and its status appeared both beside the title and in the meta column. Model-call rows now render as one static row, and every row names its status once. The work header now follows the `deck-transcript` container width, so a docked deck on a wide screen no longer wraps it into a stranded chevron. | `current change`; `console/src/deck/investigation-timeline.tsx`, its test, and `console/src/styles.css`; `npx vitest run src/deck src/shared-style-tokens.test.ts` (1098 passed); Console typecheck; on the local Console at 1440x900, no detail panel opened during a running turn, model-call status marks aligned with the other rows at the same x, a docked 401 px header rendered as a grid with no overflow while running and settled, the full workspace kept its one-line 44 px header, and 390x844 showed no overflow. | None for this layout repair. |
| 2026-10-08 | implemented | Kept the work panel running while only planning model calls have been observed. Between two calls every activity looked settled and no plan was pinned yet, so the Console opened the answer draft and settled the panel as `Partial` with `0 ms` mid-planning. Model-call-only work without a pin now stays open until a read, a token, or the validated terminal reply arrives. | `current change`; `console/src/deck/investigation-turn-state.ts` and its test; `npx vitest run src/deck` (1090 passed); Console typecheck; a local Console turn stayed running through eight model calls and settled as Verified 4/4 at 6.9 s. | None for this gating repair. |
| 2026-10-08 | implemented | Streamed each semantic planning model call as a live `model_call` activity, so the wait before the first read names the stage, deployment, elapsed time, and outcome instead of only "Determining the answer path". Core reports calls through the shared provider call gate as `semantic-model-call-progress` `1.0.0`; Operator relays them as live-only activities; the Console badges them `MODEL` and excludes them from density and read counting. Reports are on in the local launcher and off by default elsewhere. | `current change`; `semantic_model_call_progress.py` and its `1.0.0` schema; Core `model_call_progress.py`, `adaptive_call_scope.py`, and `semantic_turn_consumer.py`; Operator `semantic_progress_relay.py`, `semantic_turn_runtime.py`, and `semantic_model_call_presentation.py`; `console/src/deck/conversation-trajectory-presentation.ts` and `investigation-timeline.tsx`; focused contract, Core, Operator, and Console tests passed; a local Console turn showed seven completed model-call rows before two verified reads. | Enable reports in deployed venues after every Operator that consumes the progress topic understands the record. |
| 2026-10-08 | implemented | Shortened the terminal-only answer reveal from at most 60 to at most 24 display frames, because the full answer has already arrived and a one-second replay added to the measured turn latency. The reveal still reproduces the canonical text byte for byte, and hidden tabs and reduced motion still finish immediately. | `current change`; `console/src/deck/stream-paint.ts`; `npx vitest run src/deck/stream-paint.test.ts` (17 passed). | None for this pacing change. |
| 2026-10-01 | implemented | Consumed the live work progress pin in the Console and rendered the adaptive investigation roles. The stream accepts the first valid pin before the first read. A pause between waves no longer starts an empty answer or settles the panel early, because the answer waits until the planned reads are observed, a token arrives, or the terminal reply is validated. The lead panel names the plan and, once the answer settles, states the turn budget as used-of-maximum facts and shows the context receipts. Milestones read as one quiet progress line. A stop is recorded on the activity panels instead of rewriting reads as unavailable, so unfinished reads are shown as stopped and the stale start note is hidden. | `current change`; `console/src/deck/backend-stream.ts`, `use-command-deck-submit.ts`, `investigation-turn-state.ts`, `investigation-roles.tsx`, `investigation-timeline.tsx`, `command-deck-presenters.tsx`, `use-command-deck-lifecycle.ts`, `transcript-store.ts`, the Deck-scoped `console/src/deck/i18n/investigation.{en,ko}.json` catalog, and their focused tests; `npm --prefix console test` (`3880 passed`); Console typecheck; `npm --prefix console run check:entry` (`149829` gzip bytes, unchanged); `npm --prefix console run test:e2e:quick -- tests/e2e/deck-conversation-layer.spec.ts` (investigation plan, settled limits, context receipt, wave gating, and stop cases) | Render wave rows once reads carry their planned wave; decide whether semantic preflight joins the enforcing turn budget. |
| 2026-09-28 | implemented | Emitted the work progress fields from the semantic path ([#1629](https://github.com/dotnetpower/fdai/issues/1629)). Core pins the one verified read plan before it runs, publishes the pin as `semantic-work-progress` `1.0.0` ahead of the first node progress, and persists it with the enforcing adaptive turn budget and the applied model-tier receipt; adaptive evidence reads stay unpinned. Operator relays one `work_progress` frame before the first query activity in live and replay streams, copies the validated fields into `trajectory_detail`, and keeps at most eight activities within 60 KiB. | `current change`; `packages/service-contracts/src/fdai_service_contracts/semantic_work_progress.py` and its `1.0.0` schema; Core `work_progress.py`, `adaptive_service.py`, `semantic_runtime.py`, `semantic_turn_processor.py`, `semantic_turn_consumer.py`, and `semantic_work_progress_projection.py`; Operator `semantic_progress_relay.py`, `semantic_turn_runtime.py`, `semantic_trajectory_presentation.py`, and `semantic_work_progress_presentation.py`; `uv run pytest -q --no-cov packages/service-contracts/tests/test_semantic_work_progress.py services/core-control-plane/tests/test_semantic_work_progress.py services/operator-service/tests/test_semantic_work_progress.py` (`54 passed`); the diff-selected Python suites (`37838 passed`; three database tests that need `FDAI_DATABASE_URL` fail identically on `origin/main`); `npm --prefix console test -- --run src/deck` (`1036 passed`) and Console typecheck | Consume the live frame and render the investigation roles in the Console; decide whether semantic preflight joins the enforcing turn budget. |
| 2026-09-28 | implemented | Added the work progress contract: presentation density from typed observations, bounded waves without replanning, workflow-only milestones, turn budget telemetry, context receipts, continuation, findings that are not drafts, and separated authority display. The Console now parses the optional fields fail-closed per field and marks replayed milestones as recorded instead of completed. | `current change`; `console/src/deck/backend-types.ts`, `work-progress-contract.ts`, `trajectory-detail.ts`, `conversation-trajectory.ts`, `conversation-trajectory-presentation.ts`, `conversation-trajectory-view.tsx`, and their focused tests; `mocks/ui/fixtures/adaptive/`; `npm --prefix console test -- --run src/deck src/shared-style-tokens.test.ts src/components/mock-visual-boundary.test.ts` (`1045 passed`); Console typecheck | Emit the fields from the server and render the adaptive investigation roles in the Console. |
| 2026-09-27 | in-progress | Displayed source-grounded context candidates and separated existing principal-scoped command delivery, audited application, and unevaluated current authorization. Kept writes unavailable rather than accepting browser scope or policy claims. | `current change`; `console/src/deck/test-context-review.tsx`, `test-context-status.ts`, `console/tests/e2e/test-context-candidate.spec.ts`, focused Console and Operator checks. | Reviewed principal/policy mapping, independent proof production, proposal/review/revocation controls, and connected authentication remain open. |
| 2026-09-15 | in-progress | Added strict no-authority test-context draft decoding and propagation through HTTP, streaming, turn state, and server/local replay. Rejected normalized invalid calendar dates and untyped authority fields. | `current change`; four owning Console test files: 128 passed; production and test typechecks passed. | Complete authenticated scope/policy selection and submission/status presentation; no visual or live qualification was performed. |
| 2026-09-14 | validated | Removed the automatic-only idle gate from the explicit top-bar Incident selection. The click now opens a fresh bound conversation, preserves the prior screen draft, omits screen evidence and a default target agent, and submits the exact Incident binding. | Focused Console tests passed, the synthetic browser regression passed, and the authenticated standard-port Console rendered an `Answer ready` terminal with three verified correlated audit records and `plan_source=bound_incident`. | No remaining implementation work for this bounded entry-path repair. |
| 2026-09-08 | implemented | Added receipt-bound progressive semantic answer segments from the already durable verified projection. Console reveals only a matching answered receipt and retracts on terminal receipt, text, revision, sequence, error, interruption, or malformed-frame failure. Large answers remain within the 64-segment contract. | `current change`; Operator semantic bridge passed 151 tests and Console stream safety passed 76 tests. | Retain authenticated standard-port evidence before raising this path to validated. |
| 2026-09-08 | implemented | Added a localized lifecycle-state column so deferred and disputed assessments remain visibly distinct from completed assessments. | `current change`; focused route and catalog checks passed 11 cases, Console typecheck passed, and catalog parity passed. | Retain authenticated browser validation separately. |
| 2026-09-08 | implemented | Added a truthful unavailable state and explicit refresh action when an assessment deep link has no principal-scoped record. | `current change`; focused route and catalog tests passed 10 cases, Console typecheck passed, and catalog parity passed. | Retain authenticated browser validation separately. |
| 2026-09-08 | implemented | Made the assurance route selector accept the authoritative assessment identity carried by current replies while retaining legacy turn-id links. | `current change`; the focused Conversation assurance route test passed 6 cases. | Validate route selection against an authenticated live assessment. |
| 2026-09-08 | implemented | Propagated the authoritative conversation assessment identity through live and restored Web turns so the answer-quality link selects the matching assessment. | `current change`; focused Console stream, session, and grounded-reply checks passed 43 tests, and Console typecheck passed. | Validate the exact deep link in an authenticated Browser Entra session. |
| 2026-09-08 | implemented | Kept incomplete source coverage as the primary grounded-reply blocker while preserving a separately recorded conflict indicator in the compact Web footer. | `current change`; `npm --prefix console test -- --run src/deck/grounded-reply.test.ts src/deck/grounded-sources.test.ts` passed 60 tests. | Retain authenticated Browser Entra validation as separate evidence. |
| 2026-09-06 | implemented | Restored principal-bound semantic terminals through the existing history route and hydrated caches ending with an unanswered operator turn without resubmitting model work. | `current change`; 162 focused Python checks, 81 Console checks, and two bilingual recovery browser tests passed. Read-only recovery of the reported stored comparison returned its 744-character answer, which became visible in the authenticated session browser. | This repairs terminal recovery; the observed 51.4-second author/review/refine/verify latency remains a separate optimization boundary. |
| 2026-09-06 | implemented | Aligned legacy regression fixtures with hidden direct/advisory route badges and the explicit unknown dialogue relationship contract. | `current change`; 44 presenter/advisory tests and 15 provider-free semantic roundtrip tests passed; all 10 synthetic conversation-entry browser tests passed on the integrated main code. | Live model quality, local startup, and exact-SHA CI remain separate evidence. |
| 2026-09-06 | implemented | Hardened adaptive source disclosure and restored general-history context. Missing legacy context metadata is recovered from the explicit general namespace, never the title or creation route; resumed requests do not inherit Dashboard facts. | `current change`; 209 focused Console checks, type checks/build, and all 10 isolated conversation-entry E2E scenarios passed. Both locales passed desktop-first 1440/993/390 checks, keyboard disclosure, saved-history restoration, and unscoped follow-up submission. | Browser evidence is synthetic and isolated, not a live Browser Entra or model-validation receipt. |
| 2026-09-06 | implemented | Added projection 1.6 advisory presentation, localized goal support, selected-agent identity, and replay-safe draft explanations without replacing governed confirmation fields. | `current change`; 33 adaptive answer cases, 20 session/history cases, Console typecheck and production build passed. | Complete connected critique evidence and retain separately authorized browser runtime evidence. |
| 2026-09-06 | implemented | Registered structured conversation-key restoration as a reviewed non-semantic boundary without changing runtime routing or weakening the lexical detector. | `current change`; `chat-semantic-routing-baseline.json`; semantic-routing tests: 10 passed; session/navigation tests: 33 passed; Console typecheck. | Exact published CI evidence is separate from these focused checks. |
| 2026-09-06 | implemented | Changed general starter buttons from draft-only insertion to immediate normal submission and added bilingual send-preview tooltips. | `current change`; `conversation-entry.spec.ts`: 8 passed; focused chat/catalog checks: 48 passed; Console typecheck. | No live model or resource-execution validation was requested or performed. |
| 2026-09-06 | implemented | Completed the general welcome and explicit screen-context UX. Reopening preserves separate drafts, general history never navigates, both submission paths use the selected snapshot, and regeneration preserves an unscoped request. | `current change`; `conversation-context.test.ts`, `conversation-navigation.test.ts`, `command-deck.session.test.ts`, `conversation-entry.spec.ts`; focused unit and synthetic browser checks. | Model answers and resource execution were not invoked by this UI validation. |
| 2026-09-06 | implemented | Separated general and current-screen Deck entry, prevented route snapshots from entering general submissions, and exposed the signed-in account plus server revalidation boundary on action drafts. | `current change`; focused Deck, navigation, grounded-reply, catalog, and type checks. | Retain an authenticated Browser receipt for both entry modes before claiming deployed validation. |
| 2026-09-06 | implemented | Excluded the active panel snapshot from automatic incident-bound investigation requests while retaining the exact incident binding and minimal request metadata. | `current change`; `command-deck.tsx`; `use-command-deck-events.ts`; focused Console checks passed 38 cases; authenticated Browser Entra request inspection returned verified incident evidence. | No remaining work for this bounded context-isolation change. |
| 2026-09-05 | implemented | Added the proactive web ownership-handover conversation, revisioned goal controls, mapped-agent follow-up routing, and governed document evidence association. | `current change`; focused Operator and Console tests, Console typecheck, and Console build. | Retain an authenticated deployment receipt and add server-owned incident and approval suppression. |
| 2026-09-05 | implemented | Moved handover target selection from browser-authored prompt routing to a server-verified principal, goal, and session binding, and required authoritative document admission before evidence review. | `current change`; focused Operator, Console, and migration inventory tests passed. | Retain an authenticated deployment receipt and add server-owned incident and approval suppression. |
| 2026-09-05 | implemented | Added fail-closed incident and approval suppression and read-time document evidence staleness propagation. | `current change`; focused Operator tests passed. | Retain an authenticated deployment receipt. |
| 2026-09-05 | implemented | Restored the Knowledge overview and connector snapshots to the self-describing screen contract by publishing a shared-catalog glossary and a catalog-backed route label. | `current change`; `console/src/routes/knowledge-sources.tsx`; focused Console catalog and view-contract checks passed 47 cases; isolated Console typecheck and production build passed. | No additional implementation work remains for this bounded contract repair. |
| 2026-09-03 | implemented | Replaced unassessed starter examples with five bilingual function-backed questions, added high-confidence typed-frame reuse, defaulted aggressive T2 recovery off, and included completed frame and plan calls in model latency evidence. | `current change`; focused semantic planning, Azure adapter, runtime settings, Console intro, and question-bank checks. | Retain a new authenticated bilingual runtime receipt before raising the starter set or latency treatment to `validated`. |
| 2026-08-31 | implemented | Preserved typed partial-evidence hold answers in the Console so completed measurements, named unresolved hypotheses, exact gaps, and `execution_authority=false` remain visible. Preservation requires canonical terminal text, non-empty evidence, and a same-request matching verification and semantic receipt. A missing or invalid receipt or a missing or whitespace-only terminal answer invalidates the active token-pump generation, clears queued and accumulated draft text before flush, and sends a monotonic retraction. | `current change`; focused grounded-reply and stream checks passed 52 cases and Console typecheck passed. | Retain one authenticated desktop and mobile typed-hold receipt on the exact committed revision. |
| 2026-08-29 | implemented | Hardening round 10 reviewed 25 Console evidence and stream lenses and replaced label-derived retrieval-stage keys with fixed semantic ids. SSE progress labels now update the active row without remounting it or resetting animation and focus state. | `current change`; focused retrieval-trace tests and Console typecheck. | Retain governed visual evidence for the live progress stream. |
| 2026-08-27 | implemented | Added a panel-derived fallback screen snapshot and route-transition isolation so the Command Deck recognizes every registered screen before or without a specialized publisher. | `current change`; `console/src/app.tsx`; `console/src/deck/context.tsx`; focused Console checks (`58 passed`); desktop inspection of forecast learning, browser evidence, and configuration baselines. | Retain authenticated deployed evidence before promoting this bounded behavior to `validated`. |
| 2026-08-26 | implemented | Added real-time semantic query-node progress without changing terminal result authority. The executor observes actual node start and receipt completion, Core publishes a separate bounded no-authority record, and Operator streams stable query activities before `done`. Slow or failed progress publication is bounded and cannot change query execution. Reconnect and terminal completion continue to use the existing durable receipts as authority. | `current change`; shared contract and schema, Core executor and consumer, Operator relay and Kafka adapter; focused progress cohort (`25 passed`); Ruff, formatting, and strict mypy passed. | Retain an authenticated Command Deck run that shows the exact AKS current-state ObjectSet and Function steps changing from running to completed before the verified terminal answer. |
| 2026-08-26 | implemented | Extended measured semantic-judgment transparency from typed direct responses to ordinary answers, clarifications, holds, and unsupported outcomes. Core preserves the bounded authority-free observation across planning, processor extensions merge it with query evidence, and Operator includes it in the terminal without changing verification. Request and response bodies remain opt-in only. | `current change`; focused planning, processor, and Operator suites passed 544 cases; strict mypy and Ruff passed; an authenticated ordinary resource turn displayed one model call, 5,398 measured tokens, bounded redacted request and response content, and unchanged no-authority evidence state. | No implementation work remains for this bounded transparency defect. |
| 2026-08-26 | implemented | Kept a multi-step settled investigation open. A settled trajectory collapsed regardless of what it observed, and the semantic path emits every plan step only at terminal time, so a verified investigation's per-step provenance appeared after the answer and was already closed. A single observed read still collapses because it adds nothing the answer does not already state. | `current change`; [`investigation-timeline.tsx`](../../../console/src/deck/investigation-timeline.tsx); the focused timeline, trajectory presentation, and workspace visual checks passed 47 cases; an authenticated Console turn rendered both executed query nodes with their scope, receipts, and timings without an extra click. | Live per-step progress during the run remains open because Core still publishes one terminal projection for the semantic path. |
| 2026-08-26 | implemented | Preserved a bounded server-authored question for `semantic_clarification_required` instead of replacing every semantic clarification with the generic context prompt. Malformed questions and other unverified reasons retain the existing localized fallback, and the machine reason remains unchanged. | `current change`; `grounded-reply.tsx`; focused Console checks passed 12 cases. | Retain an authenticated receipt for the repaired exact-target question; no additional implementation work remains for this presentation defect. |
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
| 2026-09-08 | implemented | Corrected the ObjectSet Run record boundary that exposed row counts but reduced the verified query input to a capability name. Completed receipt-backed activities now show the exact bounded ObjectSet definition beside its row-count and completeness metadata. Running progress remains capability-only, and invalid or contradictory counts retain the reduced record. | `current change`; [Issue #241](https://github.com/dotnetpower/fdai/issues/241); 153 focused Operator tests, Ruff, formatting, strict source mypy, Console typecheck, the three-viewport fixture, and the authenticated desktop, constrained-desktop, and mobile Run record scenario passed. | None for the ObjectSet Run record and horizontal-overflow criteria. |

### Remaining work

- [ ] Render test-context drafts with authenticated scope/policy choices, proposal/review/revocation,
  and separately labeled delivery/application status before calling that workflow complete.
- [ ] Retain an authenticated Command Deck receipt where the exact AKS current-state ObjectSet and
  Function activities become running and completed before the authoritative terminal answer.
- [ ] Retain a passing authenticated request-to-Console four-stage ontology receipt at a new
  repository path.
- [ ] Retain a passing seeded `0x0fda1` 100-case English/Korean randomized-assurance artifact with
  evidence-complete answered turns in both locales, without replacing the 2026-08-11 baseline.
- [ ] Record governed Teams and Slack reduction receipts before claiming channel-wide runtime
  validation.
- [x] Emit `work_progress_shape` before the first branch and persist `turn_budget` and
  `context_receipts` in the semantic turn's trajectory detail: focused contract, Core, and Operator
  tests (`54 passed`) cover pin order, persistence, and the Console envelope, and the Operator
  golden in `services/operator-service/tests/fixtures/` round-trips through `parseTrajectoryDetail`.
- [x] Render the adaptive investigation roles from `investigation-timeline.tsx` with
  `ui/calm-slate-deck-conversation.css`, pin live density from the `work_progress` frame, and record
  passing Console Deck tests for wave gating, stop, and settled-only budget telemetry:
  `console/tests/e2e/deck-conversation-layer.spec.ts` streams a pinned two-wave investigation and a
  stopped one, and `work-progress-stream.test.ts`, `investigation-turn-state.test.ts`,
  `investigation-roles.test.ts`, and `transcript-store.test.ts` cover the pin window, the
  planned-read gate, the budget text, and replay.
- [ ] Render one row per planned wave. A 2026-10-01 design critique found that adding each read's
  `wave` to Operator activities isn't enough: replay omits skipped and unavailable reads, so a row
  could call a wave completed or not started when it wasn't. Version `semantic-work-progress` with
  the planned reads per wave, derive each read's `wave` from one shared plan derivation in the live
  and replay streams, keep the rows to single-panel semantic turns, and record passing contract,
  Operator, and Console Deck tests. The Console already holds the answer across a pause between
  waves.
- [ ] Settle a read under its own activity id when the terminal projection arrives before its last
  progress. Live reads are tracked by plan step index, but the terminal path renumbers verified reads
  after it omits skipped ones, so a read still marked running can be emitted again as a separate
  completed step without execution evidence. Record a focused Operator test.
- [ ] Accept the `<sequence>:goal:<n>` event ids of terminal query activities as replay cursors, or
  stop emitting them as resumable ids. The cursor parser accepts only lifecycle phases, so a client
  that resumes from one receives `invalid_replay_cursor`. The Console doesn't send `Last-Event-ID`.
- [ ] Decide whether semantic preflight joins the enforcing turn budget. Either charge it and
  record focused Core tests proving `turn_budget` counts every model call of the turn, or keep the
  documented adaptive-budget scope and record that decision here.
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

The Activity Bar opens a general conversation in the full workspace by default. Its empty state
shows "How can I help?", one composer, and three compact examples that send their question on click
or keyboard activation. Their tooltips preview the question and explain immediate submission.
Examples use the normal context-aware send path, including attachment and duplicate-submit checks.
The bottom launcher and `Ctrl+K` or `/` open a separate current-screen conversation in the right dock.
The dock transcript is the only scroller, so expanding a run record or moving focus inside a turn
never shifts the conversation or leaves a blank band above the composer.
Each entry remembers its own layout choice. General conversations never inherit route evidence.
An explicit Add current screen control captures a snapshot; a removable Reference screen chip shows
that selection. Removing it affects future questions, not messages already sent.

Reopening the general entry resumes the tab's general conversation and unsent text. New conversation
allocates a fresh user-scoped general key; history selection remains explicit, and agent and incident
entries retain their bindings. Switching entries preserves separate drafts, history, and captured
screen context. Route navigation never retargets an open floating conversation. General history does
not navigate to its creation screen. After a sent turn, the composer returns to the transcript bottom.
The header separates conversation identity from context and keeps search and history compact.
Screen context remains a hint: the server still owns evidence, authorization, and execution checks.
The workspace aligns operator and Bragi turns to one 840 px reading axis while keeping the operator
bubble right-aligned inside that axis. Korean and Latin text share one synthesized-font-free stack,
recorded time stays inside the operator bubble, and operational stages use stable icon, label,
status, and check columns. Desktop controls keep a 32 px target; mobile controls keep a 44 px touch
target and arrange identity, model selection, search, history, and window actions in two rows.
Turn groups retain a 20 px vertical gap so the shared reading axis remains visually scannable.

Conversation history restores its entry mode from structured conversation identifiers and metadata,
not from the operator's question. Principal and route normalization plus namespace decoding are a
reviewed `retain` boundary in the semantic-routing baseline. Question text supplies only the display
title; even action-like wording or namespace text cannot select an agent, incident binding, or mode.

## Semantic terminal presentation plan

`advisory_response` is carried by projection `1.6.0`, separately from social `direct_response`
and verified operational `answered`. The Console renders its canonical answer and goal-local
knowledge, verified-example, or unavailable labels without inventing a whole-response receipt.
Optional example failure does not replace the explanation with a source-failure answer. A reviewed
explanation can also accompany an existing `action_draft`; the canonical draft text and any supplied
confirmation fields remain intact. Stream, JSON, local cache, and durable restoration preserve the
same adaptive metadata. No new confirmation or execution authority is inferred from advisory text.
Limitation details use a localized disclosure rather than a raw diagnostic token as the primary
label. Restored general conversations keep their general context even when an older local index
omits the explicit mode field; neither titles nor creation routes add screen evidence.

A typed `direct_response` is separate from a verified query answer. It carries one closed answer
intent, bounded locale-bound text authored by the semantic judgment model, and
`execution_authority=false`, but no query plan, evidence
reference, verification badge, presentation artifact, or execution trajectory. Web, Teams, and
Slack preserve that same validated claim-free terminal response. Core does not replace a successful
direct response with a fixed greeting or self-introduction template.

When a structured artifact includes content beyond its overview, the Console renders the canonical
verified natural-language answer first and the table, chart, timeline, or other component below it.
The client does not regenerate or reinterpret the summary. Verification, scope, truncation, and
limitation statements therefore remain identical to the canonical answer used by other channels.

### Receipt-bound answer authority

Core assigns answer authority when its server-owned function registry issues the execution receipt.
The receipt keeps the authority and its evidence references together as one immutable goal result.
The source classes remain distinct:

- `server_subscription_health` for subscription Service Health and Resource Health reads;
- `server_inventory_graph` for secured inventory and current-state graph reads;
- `server_metering` for measured LLM usage reads;
- `server_ontology_manifest` for exact principal-scoped ontology manifest reads.

Operator derives `verification.authority` only from completed goal receipts whose references exactly
cover the terminal semantic evidence. Model, prompt, client-context, semantic-answer, and technical
presentation authority text is ignored. Missing authority produces `unverified` with
`semantic_evidence_authority_missing`. Multiple authorities produce `unverified` with
`semantic_evidence_authority_conflict`, and the turn remains held. Intent-graph evidence v2 carries
the authority additively. Version 1 replay remains readable but cannot establish verified authority.

The current semantic path proves query execution and verification but stops before operator-facing
presentation. Core serializes the verified output into fenced JSON, Operator replays one `done`
event, and the Console correctly falls back to that canonical text because the terminal payload has
no `answer_plan`, `presentation_artifact`, or `trajectory_detail`. The existing `Preparing answer`
component is transient browser state. A compact row covers the interval between submit and the
first server frame without naming an unobserved stage. The detailed trace appears only after an
observed progress frame, so completed replay still relies on server lifecycle evidence to explain
what work occurred. When that frame arrives, the browser expands the detailed trace from the
compact row's height instead of inserting the full panel in one layout step. A terminal response
without token frames reveals the exact canonical text over at most 24 visible display frames.
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

## Multi-source answer presentation

Service Health answers lead with a deterministic `yes`, `no`, `partial`, or `unknown` conclusion.
They show the configured subscription scope, unique event count, unique impacted-resource count,
observation time, completeness, and source limitation before the event timeline. Event identity is
separate from evidence identity, so one event expanded into several impact rows is counted once.
Incomplete evidence never becomes a verified numeric zero.

Mixed resource-condition answers display a per-condition conclusion and separate power-state and
Resource Health sections. The schema-v2 verification object carries ordered
`source_verifications`. Each entry retains its exact authority, evidence references, completeness,
and limitation; no synthetic combined authority is created. Single-source responses keep their
existing wire shape.

Held answers lead with what cannot be determined, the supported scope, exact limitations, and the
next safe read step. Internal query mechanics remain in technical details. A partial answer explains
each reviewed limitation code in the operator's language, including the source reason behind an
incomplete Resource scope, and keeps the exact code visible.

When no canonical answer exists, the Console maps the bounded terminal reason to an exact
operator-facing explanation. Offline transport, missing model configuration, authentication or
role denial, provider throttling or outage, content-policy refusal, evidence hold, and response
integrity failure remain distinct. The fallback never presents partial text as an answer, invents
evidence, or exposes provider response content. Unknown reasons use one generic verified-answer
unavailable statement while preserving the bounded machine reason in the source detail.

In the full workspace, an answer keeps the same reading column as the question and the work panel,
and a wide record table fits that column with cells wrapping between words; an unusually wide
table scrolls inside its wrapper. Prose beside a record table uses the table's width rather than
the narrower reading measure, so the table, the prose, and the rest of the conversation align.

## Deterministic cross-channel presentation design

The semantic presentation planner receives only a verified intent and a typed evidence-shape
analysis. The analysis records cardinality, field roles, numeric units, denominator verification,
timestamp order, missing values, truncation, limitations, and evidence references. It never reads
Markdown to infer a chart, and a model can neither name a component nor change a field role. The
planner returns a block decision; the compiler copies exact values from immutable evidence into the
versioned artifact.

Schema v1 and v2 artifacts keep the established `stack` layout for replay compatibility. Schema v3
adds server-selected `operational_brief` and `markdown_document` layouts only for verified typed
outputs. Each v3 artifact binds its localized label, exact section count, allowlisted input
categories, and complete render-affecting content to a SHA-256 assembly digest. It never carries raw
system prompts or operator-memory content. Console renders the server decision without classifying
answer prose, while malformed or modified artifacts fall back to canonical Markdown.

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

Draft `token` frames remain provisional narration. A `confirmed` frame contains only a cumulative
complete segment rendered from a durable answered projection and carries that projection's parsed
semantic receipt and evidence references. The browser checks the receipt request, disposition,
reason, no-authority fields, answer revision, and monotonic segment index before revealing it. The
terminal `done` frame remains canonical and is the only answer persisted to conversation history.
A terminal with different text, revision, or receipt retracts the preterminal segment. An interrupted
or malformed stream retracts provisional text, while a receipt-bound confirmed segment never cites
a running branch. A semantic POST stream waits for its durable projection until the request
deadline; no projection closes as a persisted typed hold, never as an empty successful stream.

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

## Work progress contract

The same typed trajectory can appear as one compact answer or as a procedural investigation. The
choice is presentation density, not authority. Answer prose, an agent name, or the presence of an
action draft never selects it.

- **Density.** Each channel derives density from typed observations. The Console's
  `workProgressPresentation` shows one completed query read compactly and shows every multi-read,
  multi-wave, or milestone-bearing trajectory as a timeline. Operator's `semantic_turn` steps, which
  report the semantic turn's own lifecycle (evidence executed, verified, answer prepared) without an
  execution record, are workflow facts and don't change the density while they settle normally. A
  server that pins the shape emits a
  versioned `work_progress_shape` (`schema_version` 1, `density` `compact` or `procedural`, `waves`
  1 to 8, `planned_reads` 0 to 64) before the first branch and persists it for replay. A pinned
  shape that contradicts the observations falls back to the timeline.
- **Waves.** Independent reads form the first wave. Reads that depend on an earlier authority result
  form bounded follow-up waves. The compiler plans once, so an investigation never asks the model to
  replan between waves and the turn limits bound the whole procedure.
- **Milestones.** An `InvestigationMilestone` states a deterministic workflow fact, such as a branch
  completing or verification starting. It carries no evidence claim. An interim operational
  statement uses a receipt-bound confirmed segment and follows its revision and retraction rules.
  Replay shows a milestone as recorded, not completed.
- **Turn budget telemetry.** When the server reports it, `turn_budget` (`schema_version` 1) carries
  `used`, `reserved`, and `maximum` for model calls, tokens, and elapsed milliseconds, the `as_of`
  time, measurement completeness, and an optional exhaustion reason: `deadline`, `model_calls`,
  `tokens`, `rate_limited`, or `cancelled`. A measure ends above its maximum only when it is the
  exhaustion reason: observed tokens replace their reservation before the check, and a deadline is
  noticed after it passes. Model calls are reserved before each call and never exceed their
  maximum. Without the telemetry, clients show the policy limits and the observed values as
  separate facts and never draw a remaining-budget meter.
- **Context receipts.** An applied operator preference appears only as a `context_receipts` entry
  with a receipt id, the `operator_preference` kind, a SHA-256 digest, the observation time, a
  `fresh`, `stale`, or `superseded` freshness, and a bounded label. A receipt is context, not
  evidence or instructions. Stale or superseded context forces a fresh authoritative read or a
  partial result.
- **Continuation.** When a limit ends the turn, the answer is `partial` or `held_for_review` and
  names its unresolved goals. Continuing is a new typed request for a named gap with a new request
  identity, revalidated freshness and authorization, and a cumulative bound. It is never an
  automatic retry after a timeout or `429`.
- **Findings are not drafts.** A diagnosis or drift finding ends with the verified finding, the
  evidence gaps, and the next safe step. Drafting a remediation is a separate explicit typed request
  that rechecks scope, policy, and draft availability.
- **Authority display.** Each activity separates the operation (`read`, `simulate`, or `draft`),
  the authorization result (`allowed`, `denied`, or `unavailable`), the evidence authority, and the
  execution authority, which is always none. Risk appears only on a registered ActionType draft or
  approval surface.

The Console accepts these optional fields in the persisted trajectory detail and drops a malformed
field without discarding valid evidence. The server emits them within these bounds:

- **Pin.** Core derives the shape from the one verified read plan right before it runs. Planned
  reads are the plan's nodes, and waves are its longest dependency depth. A plan beyond 64 reads or
  8 waves isn't pinned. Core publishes the pin once on the best-effort progress topic as
  `semantic-work-progress` `1.0.0`, ahead of the plan's first node progress. It persists the same
  pin in the terminal payload, including a deadline or cancellation hold. Reads that an adaptive
  answer makes for an environment example are never pinned.
- **Frame order.** Operator sends at most one `work_progress` SSE frame per stream, before the first
  query `activity`. A live pin uses event id `0:planning`. A replay uses
  `<projection sequence>:planning` and skips the frame when the cursor already covers it. A
  persisted pin that no longer matches the stored intent graph is dropped.
- **Budget scope.** `turn_budget` reports the enforcing adaptive turn budget where one governed the
  turn: the governed path after adaptive planning, including its budget hold. Semantic preflight
  runs before that budget and appears only in the model trace. A directly verified turn has no call
  or token maximum, so it reports no budget. Charged but unmeasured tokens stay `reserved` and make
  the measurement incomplete. Tokens and elapsed time that both end over their maxima have no
  version 1 representation, so the budget is omitted.
- **Context receipts.** The per-conversation model tier that the request carries is the only
  operator preference Core applies to a semantic turn, so it is the only receipt. The account
  narrator preference in Settings isn't carried into semantic turns and produces no receipt.
- **Envelope.** Operator keeps at most eight leading activities within 60 KiB and counts the rest in
  `omitted.activities`. A pinned turn without read receipts keeps an empty base detail so its fields
  replay. A budget or receipt alone never creates a trajectory.

The Console consumes the live pin and the persisted fields with these rules:

- **Live pin.** The Console accepts the first valid `work_progress` frame that arrives before the
  first query read or branch. It ignores later or malformed pins, so density never changes during a
  turn. The pin stays on the turn's activity panels, so a stopped turn still names its plan after
  a reload.
- **Wave gating.** A pause between waves doesn't end the observed work. The answer starts only after
  every observed read has ended and one of these is true: the observed reads reach
  `planned_reads`, the first answer token has arrived, or the terminal reply is validated. Reads
  are counted by distinct identity, and lifecycle steps without query execution don't count.
- **Lead panel.** The first activity panel of a turn names the plan's waves and reads. After the
  answer settles, it states `turn_budget` as used-of-maximum facts, names any limit that ended the
  turn and any incomplete measurement, and shows the applied context receipts as a collapsed
  disclosure labeled as context. Later panels keep their own summary. Settled panels follow the
  [common answer presentation](operator-console.md#common-answer-presentation): completed work
  folds to its summary, and failed, partial, and unavailable work stays expanded.
- **Stop.** A stop is recorded on the activity panels, and each read keeps its last observed
  status. A read that never reported an end is shown as stopped. After any other interruption it
  is shown as not completed, never as running.

### Live model-call progress

Semantic planning makes several model calls before the first read, so the operator previously saw
only "Determining the answer path" for most of the wait. Core now reports each planning model call
as it happens:

- **Observation.** The shared provider call gate reports every physical request of a reviewed call
  stage, such as preflight, question form, constraint extraction, or concept selection, when it
  starts and when it ends. A report carries the stage, the model deployment, the start and end
  times, the elapsed milliseconds, the outcome, and token counts. It never carries a prompt, a
  response, quoted question text, or a reason the model gave.
- **Transport.** Core publishes `semantic-model-call-progress` `1.0.0` on the same best-effort
  progress topic as query progress, at most 64 updates for 32 calls per turn. A full queue drops
  the update, and a publication failure never affects the turn.
- **Stream.** Operator streams each update as an `activity` with kind `model_call`, a localized stage
  label, and the deployment and elapsed time as its detail. The Console marks the row with a `MODEL`
  badge instead of `EVENT` and renders it as one static row with a single status label; it opens no
  lifecycle panel, because the row already states the stage, deployment, elapsed time, and outcome.
  The activity is live only: it is not persisted in the trajectory detail,
  it never counts as a read, and it never changes density. While only model calls have been
  observed and no plan is pinned, the Console keeps the work panel running between calls, so the
  answer draft doesn't open until a read, a token, or the validated terminal reply arrives.
- **Activation.** `FDAI_SEMANTIC_MODEL_CALL_PROGRESS=1` enables the reports. The local launcher sets
  it; deployed venues keep it off until every Operator that consumes the progress topic understands
  the record, because an older Operator quarantines an unknown record.

| Critique finding | Revision |
|------------------|----------|
| A progress record could leak question or answer content | It carries only the closed stage, deployment, times, outcome, and token counts |
| Reporting could slow the model call it observes | The report is a non-blocking queue put on the consumer loop; failures are dropped |
| Leading model calls could push query reads out of the eight-activity envelope | Model-call activities are live only and never enter the persisted trajectory detail |
| A non-read step would flip compact answers to a timeline | The Console excludes `model_call` activities from density and read counting |
| Mixed-version rollout floods the dead-letter topic | Reports stay off in deployed venues until the Operator understands them |
| Running rows opened a lifecycle panel each and named their status twice, so several parallel calls pushed the transcript around | A model-call row never discloses a panel and states its status once |
| The work header followed the viewport width, so a docked deck on a wide screen wrapped it and stranded the disclosure chevron | The header follows the transcript container width |
| A pause between model calls looked like finished work, so the answer draft opened and the panel settled as partial mid-planning | Model-call-only work without a pin stays open until a read, a token, or the validated terminal reply |

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
