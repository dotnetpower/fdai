---
title: Operator Console - View Snapshot Contract
---

# Operator Console - View Snapshot Contract

> Focused owner document extracted from [operator-console.md](operator-console.md) section 13.4.

### 13.4 View snapshot - self-describing screen contract (web deck)

The read-only console SPA captures what the operator currently sees as a
`ViewSnapshot` and posts it as the `view_context` of `POST /chat`
(`console/src/deck/context.tsx`). The snapshot is a screen *model*, not just a
value digest, so the narrator can explain the screen and its vocabulary and
answer "why did this happen" without a per-screen answerer:

```jsonc
{
  "routeId": "agent-activity",
  "routeLabel": "Agent activity",
  "purpose": "What this screen is for and what an operator does here.",
  "glossary": [
    {
      "term": "correlation id",
      "plain": "the investigation key grouping related steps and evidence; not proof of an Incident",
      "tech": "correlation_id",   // precise internal token (optional)
      "seeAlso": "trace",          // route to dig deeper (optional)
      "match": "correlation_id"    // records column whose values this term explains (optional)
    }
  ],
  "facts": [{ "key": "rows", "label": "Visible rows", "aliases": ["visible rows", "표시 행"], "value": 5, "group": "page" }],
  "records": {
    "activity": [
      { "correlation_id": "corr-j", "detail": "...why this happened...", "outcome": "..." }
    ]
  },
  "capturedAt": "2026-07-06T11:12:30Z"
}
```

An interactive screen should publish a complete operator model, not only KPI
counters. In addition to `purpose`, `glossary`, and `facts`, its `records`
should contain:

- `sections`: the visible regions and what each region means.
- `controls`: available inputs and commands, current values, options, and
  enabled state. Each control should include an operator-facing `label` and
  `detail`; an unavailable control should include `disabled_reason`.
- `constraints`: limits, prerequisites, safety boundaries, and reasons an
  operation is unavailable.
- Domain record collections: the actual visible rows needed for lookup and
  causal explanation.

A route may delegate this contract to `*.view.ts`. Its optional `explanations` envelope standardizes
selection, relationships, lifecycle criteria, deduplication, and provenance; absent metadata means
"not declared", never a guess. Ontology and Agent Activity are the first adopters; other routes reuse
the envelope incrementally. The server bounds it and the verifier hashes entries used by claims.

#### 13.4.1 Cross-screen operational evidence

`ViewSnapshot` is authoritative only for the rendered route. On the ontology route, a bare
`Issue` or problem noun remains a current-screen domain reference. Explicit recency, incident, outage, failure, or cause
language invokes `OperationalEvidenceResolver` against the server-owned `ConsoleReadModel`; it
never trusts operational evidence supplied by the browser. The resolver searches at most 12 recent incidents and at most
100 correlated audit rows per candidate, then injects a compact
`_operational_evidence` block into both `/chat` and `/chat/stream`.

The block has fail-closed states: `matched`, `ambiguous`, `none`, or
`unavailable`. `matched` includes the selected incident, bounded audit
observations, response plan, and only RCA hypotheses that are grounded, carry
a cause, and cite evidence. Bragi MUST NOT state an incident cause from an
abstained or uncited hypothesis. `ambiguous` lists candidates and asks the
operator to choose; `none` and `unavailable` explicitly prohibit guessing.
The extra system directive is injected only when operational evidence is
present, so ordinary screen questions retain the lean prompt budget.

For other cross-screen questions, the web adapter uses this authority order:

1. `OperationalEvidenceResolver` for incident and root-cause questions.
2. Server-owned inventory/read-model tools for Azure resources, KPI, pending approval, audit, and
  incident lists. Inventory questions take a deterministic `query_inventory` fast path; broad health uses the same KPI authority but
  take a deterministic `read-model-health` path before model synthesis. The
  answer reports the observed event sample, approval backlog, execution-mode
  mix, and evidence time; it does not infer that every component is healthy.
3. `PantheonChatDelegate` for agent-owned domains. Bragi routes to the primary
  agent and calls at most three matching contributors with bounded timeouts.
4. The canonical FDAI glossary for concept definitions. English concept turns
  use a deterministic `concept-glossary` fast path; localized turns receive
  the same selected entries as server-owned translation evidence.
5. The browser `ViewSnapshot` for the current screen.

The server removes any client-supplied `_operational_evidence`,
`_tool_evidence`, or `_agent_evidence` before resolving the turn. The browser
sends the authenticated bearer token on chat health, JSON, streaming, and
action requests. A client session id is bounded and namespaced by the validated
principal before Bragi stores it, so two users cannot share conversational
state by choosing the same id. The JSON and streaming responses return bounded
delegation metadata so the deck labels the reply with the actual primary agent.
The terminal claim verifier includes tool, agent, and selected glossary
evidence in its hashed manifest, so it does not compare a server-grounded
answer against an unrelated empty screen.

#### 13.4.2 Progressive answer verification

The web deck MUST separate response latency from answer trust. It streams one
assistant turn immediately as a **provisional** answer, then verifies it and
updates that same turn rather than appending a contradictory second answer.
The server owns the state machine and emits ordered SSE events:

```text
evidence_resolving -> generating -> provisional -> verifying
  -> verified | consistent | corrected | unverified
```

The `evidence_resolving` status includes a bounded preview of the current
screen source. After server-side resolution, the `generating` status replaces
it with the actual read-only tool, operational, agent, or glossary sources
selected for the turn. Client-supplied internal evidence is removed before
this second preview is built. The deck keeps the retrieval trace visible until
text is ready and for a minimum of 420 ms, then changes the same pending
surface into the streaming answer. The two surfaces share width and alignment,
with short entry motion and staggered source rows. Text received during that
interval enters an adaptive visual queue that drains one to three paced deltas
per display frame according to backlog; it is never dumped as one large first
paint. When the answer first appears and when its terminal revision renders,
the transcript moves to the newest content even if the operator scrolled upward
during preparation. The completed reply labels manifest entries as evidence
references, not as independent sources. A bounded correction that removes
unsupported sentences and passes re-verification uses the verified visual
treatment.

The reply renderer supports ATX headings, emphasis, strong text,
strikethrough, unordered and ordered lists, read-only task lists, blockquotes,
thematic breaks, safe `http` / `https` / relative links, tables, fenced code,
and chart blocks. Open code fences render as stable plain previews while
streaming and are highlighted only after closure. Executable or otherwise
unsafe link schemes remain plain text.

The deck opens as a 440 px right sidebar when no display preference exists.
Header controls preserve the same conversation while switching to a movable
floating panel or the full workspace. Dragging the floating header title moves
the panel. Its left and top edges keep a 12 px guard, while the right and bottom
edges may move beyond the viewport. The sidebar's left separator supports
pointer and arrow-key resizing from 340 to 720 px. Right-sidebar mode reduces
the shell body by that same current width, so it does not cover navigation or
page content. Floating and dock modes remain non-modal and do not trap focus or
block page interaction; full workspace retains the modal focus trap. The
selected mode and sidebar width persist in browser local storage, so closing
and reopening the deck or browser restores the last display. Compact mobile
viewports use the full-screen geometry without replacing the stored preference.

- `verified` means the terminal answer was rendered from server-owned
  operational or inventory evidence.
- `consistent` means the answer was checked against the browser's current
  screen snapshot but was not independently verified by a server projection.
- `corrected` means the provisional model text was replaced by a deterministic
  answer derived from the evidence result.
- `unverified` means verification could not complete; it MUST NOT render the
  same trust check used for `verified`.

When a delegated agent's provisional prose remains `consistent`, the reply
header keeps that agent. When verification replaces the prose with a
`corrected` or `unverified` terminal answer, the header returns to **Bragi**,
the final narrator. The original `primary_agent` remains in delegation and
trace metadata; it is not presented as the author of verifier-generated text.

Every event carries a monotonic `seq`; answer-changing events also carry a
monotonic `revision`. The client ignores stale revisions and events after the
terminal event. A correction replaces the text for the existing turn id,
preserving conversation order and accessibility focus. Only the terminal
canonical revision is persisted or supplied as history to a later turn.

The first shipped verifier uses no second model call. For cross-screen
operational and Azure inventory questions it deterministically renders the terminal answer from
the typed evidence state (`matched`, `ambiguous`, `none`, or `unavailable`),
so model prose cannot change the selected incident, search scope, RCA cause,
or absence claim. `none`, `ambiguous`, `unavailable`, and `matched` without a
grounded RCA take a deterministic fast path: the server streams the canonical
answer immediately after evidence lookup and does not invoke a model. A
`matched` result with grounded RCA MAY stream model prose provisionally, then
replace it with the canonical verified cause when needed. Screen-only answers
terminate as `consistent`. For a localized glossary answer, one bounded rewrite
may remove unsupported scope-only addenda and re-run deterministic verification;
other unsupported claims still end in abstention. For a complete screen
snapshot with a partial claim mismatch, one bounded rewrite may remove the
entire sentences that contain unsupported claims and verify the remaining
answer again. Facts may publish bounded localized `aliases`; duplicate values bind to the nearest
matching `label` or alias and remain ambiguous without a match. This correction requires at least one supported claim before and after the rewrite. A `0/N` result, truncated snapshot, or extraction overflow still ends in abstention.

Latency targets are: first progress event within 100 ms of request admission,
fast-path terminal answer within 500 ms p95 after evidence lookup completes,
normal model TTFT within 2.5 s p95, first verification event within 100 ms of
the provisional completion, and provisional-to-terminal verification within
1 s p95. Progress reports completed checks, never a fabricated percentage.
Incremental SSE deltas render without client-side delay. Only a large single
frame or a same-tick queue burst is grouped into paint-sized chunks with a
short cosmetic cadence; deterministic fallback prose keeps its separate,
slower typewriter cadence.

Screen-only provisional answers additionally produce an atomic claim artifact
without a second model call. The deterministic extractor recognizes IDs,
numbers, percentages, timestamps, causal assertions, and bounded-scope claims;
each claim records its source span, normalized value, support state, and exact
snapshot evidence references, including fact aliases used for matching. An `evidence_manifest` records route, capture
time, completeness, source paths, and a canonical content hash. It contains
only entries used by claims, not a duplicate of the full snapshot.

Bounded-scope extraction covers explicit absence such as `no`, `none`, or
"not shown on this screen". Positive universal prose such as `all`, `always`,
`모든`, or `전부` remains qualitative and is left to the optional semantic
shadow verifier. A universal word by itself never turns a routine screen
description into a deterministic global-scope claim.

Every extracted claim MUST be supported by an unambiguous snapshot entry. If
all claims pass, the answer remains `consistent` (never `verified`, because the
browser snapshot is not an independent server projection). If no checkable
claim exists, the answer remains `consistent` with an explicit
`screen_no_checkable_claims` reason. Any unsupported or ambiguous claim,
truncated snapshot, malformed artifact, or extraction overflow replaces the
whole provisional answer with a localized abstention and terminates
`unverified`; partial sentence deletion is prohibited. Final persistence and
the grounding UI carry only the terminal claims and manifest.

A frozen, customer-neutral claim corpus gates this deterministic surface in
CI. The initial corpus covers supported and unsupported IDs, numbers,
percentages, timestamps, causal assertions, bounded absence, ambiguity, and
claim-free prose. Promotion requires both unsupported-claim escape rate and
clean-answer rejection rate to remain exactly `0.0`; metric accounting is
tested independently so an empty or inverted label set cannot pass silently.
This gate does not claim semantic verification of qualitative prose: an answer
with no extractable structured claim is labeled `consistent` with
`screen_no_checkable_claims`, never `verified`.

The optional local semantic verifier was removed after its measured retention
gate failed on 2026-07-17. A pinned MIT-licensed multilingual MiniLM ONNX model
ran against 200 customer-neutral English/Korean cases. It caught `0.0%` of the
contradiction set at the configured `0.8` threshold and returned `unknown` for
`80.0%` of all cases. Clean-answer false positives and authority changes both
remained `0`, warm p95 latency was `10.05 ms`, cold start was `1126 ms`, peak
RSS was about `571 MiB`, and model plus tokenizer footprint was `124498008`
bytes. Unknown outcomes count as no benefit, so the measured result selected
removal rather than promotion.

The `local-nli` dependency group, ONNX provider, Settings toggle, request flag,
response metadata, and related runtime tests were removed together. The
deterministic evidence and atomic-claim verifier remain authoritative and
unchanged. Qualitative prose remains explicitly not verified unless a future
proposal supplies a new measured design with material contradiction benefit.

#### 13.4.2.1 Deterministic AnswerPlan

Every Command Deck turn now receives a typed `AnswerPlan` before prose generation. The
pure `core/conversation/answer_plan.py` parser classifies English and Korean requests as
definition, why, procedure, comparison, diagnosis, status, list, summary, proposal, or
open question. It also records explicit current-turn detail, format, evidence, and
audience modifiers. When two explicit modifiers conflict, the later instruction in the
same turn wins. Stored preferences cannot override the current turn.

The plan supplies intent-specific sections, a bounded word target, format, and evidence
requirement. It is injected as server-owned snapshot metadata, returned in both JSON and
SSE terminal responses, persisted additively with the transcript, and rendered as a
compact localized `Bragi / intent / detail` label. The browser discards the plan's subject
text and never exposes prompts or hidden reasoning.

Phase B adds an explicit, principal-scoped response preference profile through the existing
`UserPreferenceStore` seam. Settings lets an operator inspect and edit the default
`brief`/`standard`/`deep` detail level, choose a default response format, disable application
without deleting the profile, or reset both the account projection and browser-local display
preferences. The profile also reserves validated per-intent detail and format maps. Reads use
the authenticated principal only, and the server discards client-supplied `_answer_plan`
metadata before constructing its own plan.

Stored defaults apply only when the current turn does not request a conflicting shape. An
explicit modifier such as `briefly`, `step by step`, `짧게`, or `표로` still wins. A one-off
modifier is recorded in bounded turn metadata but is not promoted into the stored profile.
Automatic preference learning remains off; future shadow measurement can evaluate repeated
explicit signals without changing current answers. Locale resolution is unchanged.

#### 13.4.2.2 Shadow Answer Planning Round

Phase C adds a read-only `AnswerPlanningRound` behind a dedicated provider seam. It runs in
shadow for eligible `why`, `comparison`, and `diagnosis` turns, plus explicit multi-perspective
requests. A brief request, definition, status, list, direct tool result, or route with no
complementary contributor does not create a planning task. Eligible plans carry
`discuss=shadow`; all other plans keep `discuss=skip`.

The round selects at most two contributors in deterministic score and agent-name order and
calls their read-only conversational ports in parallel. Contributors return typed
`AnswerContribution` records with grounded facts, vouched-for evidence references, suggested
sections, caveats, and confidence. The production pantheon adapter excludes Bragi, Norns, and
Odin from routine collection. Saga participates only for audit, history, issue, or handoff
questions. Action-shaped requests abstain through the existing typed-pipeline guard.

The shipping limits are fixed at two contributors, one round, `1200 ms`, and `800` estimated
added tokens, with nested rounds disabled. Timeout, exception, abstention, agent mismatch, or
token overflow becomes bounded degraded metadata. It never blocks or changes an otherwise
supported answer. Contributor facts do not enter the narrator snapshot in Phase C, so the
primary-only answer remains the terminal answer.

JSON and SSE terminal responses, durable turn metadata, and the browser transcript carry the
same bounded shadow record: status, consulted agents, evidence references, suggested sections,
failure kinds, elapsed time, token estimate, effective budget, section coverage, and unique or
duplicate evidence counts. They do not carry the prompt, free-form contributor reasoning, or
hidden chain-of-thought. Structured logs emit counts and latency only. Answer-plan coverage
and contributor utility remain separate from deterministic answer trust status.

Phase D selective activation and Phase E cross-domain conflict handling remain unpromoted.
Promotion requires the frozen bilingual evaluation set, zero unsupported-claim escapes and
authority violations, no clean-answer regression, and measured latency, token-cost, unique-
evidence, correction-rate, and follow-up-rate gates from this shadow baseline.

#### 13.4.3 Live observation contract

The read-only SPA exposes **Now > Live** as the current-state entry point. It
answers three bounded questions: whether observation is connected, which
control-loop work needs attention now, and where the recorded evidence lives.
It does not replace Incidents, Approvals, Audit, Trace, Agents, or Control
Assurance.

- **Queue is the default view.** It sorts failed work, work over its published
  latency budget, pending approvals, denied work, active work, and recent
  completions in that order. `correlation_id` is the investigation key.
- **Flow is a secondary view.** The fixed-slot activity swarm visualizes
  throughput and stage progression but does not determine priority.
- **Stuck is authoritative.** A tile is marked stuck only when the stage stream
  carries a positive `latency_budget_ms` and the observed age exceeds it. A
  missing budget renders no stuck claim; the browser does not invent a
  threshold.
- **Mode is recorded, not inferred.** The control loop publishes the actual
  `Action.mode` on stage frames. Reaching `execute` does not imply shadow mode.
- **Observation source is recorded, not inferred.** Live and Agent Activity
  frames carry top-level `source`: `synthetic-dev`, `replay`,
  `runtime-observed`, or `unknown`. Legacy or unfamiliar values normalize to
  `unknown`; conflicting known values in one browser connection render as
  `mixed`. The browser never derives source from dev mode, authentication mode,
  or endpoint URL. `runtime-observed` describes the producer path and is not an
  Azure-health or execution attestation.
- **Terminal state is authoritative.** Per-finding gate frames may report
  different decisions for one event. The terminal `audit.done` frame carries
  the event-level outcome and decision, which replace any intermediate value.
  The browser retains every observed ActionType and labels a multi-finding
  event as a set of actions instead of presenting the last action as the whole
  event.
- **Replay is safe.** A repeated terminal frame updates the existing tile but
  does not increment throughput, gate mix, tier mix, or recent outcomes again.
- **Freeze affects presentation only.** The stream remains connected, received
  frames are counted while the view is frozen, and History remains the record
  of every terminal outcome.
- **Retention is bounded.** Completed approval tiles stay visible longer than
  ordinary outcomes, then leave the 60-slot presentation pool. The Approvals
  route owns the complete queue, so old Live state cannot starve new events.
  The selected tile stays pinned only while its detail drawer is open so an
  operator's evidence does not disappear during inspection.
- **Drill-down is explicit.** The detail drawer shows the observed stage trace,
  agent ownership, mode, decision, and correlation key, then links to Trace,
  Audit, and Architecture. It offers no execute or approval control.
- **Drill-down is keyboard-contained.** The drawer is an accessible modal
  dialog. Focus moves to its close control, Tab stays within the drawer,
  Escape closes it, and focus returns to the row or tile that opened it.

The Live header reports only facts available from the stream: connection
state, last observed event age, configured environment posture, and frozen-vs-
following presentation state. Canary health, kill-switch state, stream-drop
counts, and measured guard metrics require server-owned read-model fields; the
browser shows them as unavailable until that contract exists. CFR,
false-positive rate, rollback rate, and policy-violation escapes belong in
Control Assurance with their measurement window, baseline, and sample size.
