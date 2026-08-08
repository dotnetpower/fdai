---
title: Operator Console - Narrator, DI Seams, and Session Model
---

# Operator Console - Narrator, DI Seams, and Session Model

> Focused owner document extracted from [operator-console.md](operator-console.md) sections 1.2 and 4-6.

## Runtime settings boundary

Settings can manage a bounded runtime policy without turning the console into an execution
surface. Readers can inspect a sanitized projection of availability, the environment ceiling,
the persisted override, and the effective value. Owners can update only allowlisted policy fields
through an optimistic revision check. Each accepted update writes the new state and its audit entry
atomically.

The settings route never receives the executor identity and never changes cloud resources. A
runtime consumer reads the same durable policy before applying a behavior that supports dynamic
configuration. Environment and infrastructure values remain a ceiling: a stored preference cannot
enable an unavailable capability, promote an ActionType or Workflow, weaken risk or approval
checks, or select a test-only adapter. Secrets, endpoints, tenant identifiers, and managed identity
identifiers are represented only by configured or unavailable status.

The initial allowlist covers bounded investigation, inventory freshness, analyzer budgets, Incident
auto-open policy, case history retention, and logging detail. Incident policy exposes enablement,
minimum severity, repeat threshold, and repeat window; all four require restart because Heimdall is
constructed at process startup. Each field declares its type, minimum and maximum, restart
requirement, and availability reason. The console shows current, proposed, and effective values,
the revision, the last actor and update time, and any validation conflict. A stale revision returns
a conflict and requires the operator to review the latest state before retrying.

## 4. Narrator - LLM tier model

The narrator is the console's LLM translator layer. Core/CLI use the `Narrator` Protocol, while
web progressive-answer generation uses a separate Operator API backend seam. Azure binding is selected
from `resolved-models.json` and environment composition, never a fixed account name.

### 4.1 Three tiers (mirrors the trust router)

| Tier | Model | Handles | Default? |
|------|-------|---------|----------|
| **Chat T0** | none (regex / keyword intent) | Direct-hit tool calls: `list_hil`, `explain_verdict <id>`, `explore_catalog <keyword>`. | Yes (LLM not invoked when a T0 intent matches with confidence >= configured threshold) |
| **Chat T1** | `t1.judge` (mini reasoner) | Standard turns: natural language ↔ tool_calls, most read-only investigations, one-hop follow-ups. | **Yes (mini always active)** |
| **Chat T2** | `t2.reasoner.primary` (frontier) | Escalation only (see §4.2). | No (opt-in via escalation trigger) |

**Deterministic-first still holds.** Chat T0 (regex / keyword intent, no
LLM) is tried first on every turn and is expected to satisfy the bulk of
repeat operator verbs (`list_hil`, `explain_verdict <id>`,
`explore_catalog <keyword>`). The design target is that Chat T0 resolves a
majority of turns and Chat T2 stays a small minority (~5-10% of turns,
mirroring the event-side tier split) - but this is a **target to validate
against a measured baseline**, not a guarantee. The console emits per-tier
turn counts to the telemetry surface
([goals-and-metrics.md](../architecture/goals-and-metrics.md)) so the split is measured,
never asserted. `t1.judge` being "always active" means it is the fallback
for non-T0 turns, not that the LLM runs when a confident T0 intent matches.

Public-web intent uses the same tier shape. T0 keeps high-confidence explicit-search and local-scope
patterns. For eligible turns that remain `none`, an Azure Responses candidate uses a dedicated
system prompt plus strict JSON schema to return route, classification confidence, reason code, and
a bounded English search query. Alternative discovery also returns a goal, comparison subject, and
two to eight capabilities; the coordinator rebuilds the actual query from those capabilities. It
never receives the current screen snapshot or history. Alternative retrieval accepts direct product
pages only and uses medium search context to request at least three distinct products before
filtering: self references, generic homepages, conceptual guidance, editorial or blog pages,
documentation indexes, and duplicate product identities are removed before evidence reaches Bragi.
Invalid, low-confidence, or unavailable output stays `none`; it cannot override local or
sensitive-data denials. For non-alternative goals, extra model-generated subject or capability
fields are discarded because they do not affect routing; malformed required fields still fail closed.
The bounded candidate output budget applies to classification so reasoning tokens cannot truncate a
valid structured decision. This classifier prompt is separate from Bragi's answer-generation prompt.

Public retrieval never borrows `narrator_candidates`. The resolver selects `t1.web_search` into
`web_search_candidates`, and startup sends one actual managed-tool request per candidate before the
Operator API serves traffic. Failed candidates are excluded. If none remain, Settings preserves the
enabled preference but reports `available=false` with a bounded reason and disables management.
Settings also shows the sanitized provider, whether the Foundry project is configured, agent name,
model deployment, provisioning status, and real-tool readiness. It never exposes the project
endpoint, Azure resource ID, tenant identity, or credentials.

### 4.1.1 Cross-process agent introspection

The core runtime remains the only Pantheon owner. A separate Operator API reaches Bragi through two
bounded logical service topics multiplexed over `aw.pantheon.objects`; it never embeds another
agent runtime. A server-echo probe confirms the response consumer, reuses the same joining consumer
across retries, and allows 20 seconds for the initial Event Hubs group join. A request carries a
2,000-character maximum question with no silent truncation plus process-secret salted SHA-256 user/session references. The response is
limited to a 16 KiB answer and a 64 KiB result, waits at most 20 seconds, validates fixed agent
names and exact target ownership, scans the complete normalized result for sensitive values, and
retains only a charter hash and tool manifest that match the fixed target `AgentSpec`.
The full-charter hash covers role fields, tool purpose/fact scopes, and multilingual routing
examples; answered turns without exact versioned policy attribution fail closed. Facts are
round-tripped through bounded JSON before crossing the process boundary. The client caps pending
requests at 256, rejects conflicting request-id replay, expires cached replay after five minutes,
and ignores late or unmatched responses. Failure produces an attention-state
handoff to Bragi and never claims that the selected agent contributed evidence. These service
topics grant no action, judgment, approval, or executor authority. Final narration treats charter
metadata as provenance only, keeps Bragi's identity, and uses content-addressed agent-state refs
from direct or tool-routed normalized facts instead of presenting the static agent specification
as runtime evidence.

### 4.2 Escalation triggers (T1 -> T2)

The coordinator escalates to Chat T2 on any of:

- The narrator's T1 response has `finish_reason=abstain` or the aggregated
  confidence falls below the configured threshold. **Confidence is derived,
  not model-self-reported:** for a write-class turn it is the verifier
  result (§7.2); for a read-only turn - where the verifier does not run -
  it is composed from the Chat-T0 intent-match score, whether every
  proposed `tool_call` validated against its `argument_schema`, and
  whether the tool returned `status=ok`. A read-only turn whose tool calls
  all validate and succeed is high-confidence and never escalates on
  confidence alone.
- The verifier rejects the proposed tool_call sequence (see §7).
- The requested tool is `simulate_change`, `approve_hil`, `run_runbook`,
  or `activate_break_glass` **and** the turn required more than one tool
  hop to resolve arguments.
- The multi-turn hop count in the current session exceeds a configured
  limit (default 5) - a signal the intent is novel.
- The user explicitly asks for deeper analysis (natural-language marker
  patterns, configurable).

Escalation is **one-way per session**: once a session hits T2 the same
turn's continuation stays on T2, but subsequent turns start again at T1.
The audit entry records `tier`, `escalation_trigger`, and the T1 output
that triggered it.

### 4.3 What the narrator is not allowed to do

- **Assert execution eligibility.** Only the verifier does that (§7).
- **Bypass the RBAC gate.** The coordinator applies the floor **before**
  invoking the narrator, so the tool schema handed to the model only
  contains callable tools.
- **Read the audit log directly.** The narrator sees only what tool
  results provide; the audit store is behind a Protocol seam.
- **Emit natural-language "commands" the coordinator treats as tool
  calls.** Only structured `tool_calls` from the model's function-calling
  response count. Prose is prose; it never runs.
- **Treat tool-argument content as instructions.** Operator-supplied
  argument values (a `restart_reason`, a free-text filter) are untrusted
  input and a prompt-injection surface, exactly like T2 event payloads
  ([architecture.instructions.md § LLM Quality Gate](../../../.github/instructions/architecture.instructions.md#llm-quality-gate-required-for-t2)).
  They are (a) schema-validated at the coordinator boundary, (b) never
  concatenated into the system prompt as trusted text, and (c) for
  write-class tools, re-checked by the verifier (§7.2) which is the
  authority - not any instruction the argument text may contain.
  Redaction (§5.2 of action-ontology) strips secrets; it is not the
  injection defense - the verifier re-check is.

### 4.4 Cost and rate limits

Per D12: mini (t1.judge) is always on and the operator budget assumption
is that this is the normal-cost surface. The upstream default ships a
**generous-but-finite** per-turn token budget and per-session hop cap
(config keys `console.max_completion_tokens_per_turn`, default 4096, and
`console.max_tool_hops_per_turn`, default 8) - a product whose Cost
Governance vertical polices spend cannot ship its own console with an
unbounded LLM surface. There is no per-user *rate* limit by default; a
fork MAY add one via config. Every measured LLM invocation records its
tier, model deployment id, workload scope, and prompt/completion token
counts in the metering stream.

**Shipped usage view.** T1 and T2 adapters record measured provider
`usage` through a `MeteringSink`. The narrator uses the same stream with
the explicit `operator_chat` scope; other calls use `control_plane`.
`LlmCostPanel` retains the compatibility path `GET /kpi/llm-cost`, but
its public projection contains token usage only. It returns totals by
scope, model, mode, conversation (`correlation_id`), day, and month, plus
a bounded newest-first invocation ledger with model and capability on
every row. The console renders this as the read-only **LLM usage** panel.

Derived price isn't exposed by the Operator API or console because regional,
currency, and negotiated rates can make a configured estimate differ
from the provider invoice. A deployment can still use its configured
price table for an internal budget gate. Because the headless core and
Operator API are separate processes, production uses the durable Postgres
`llm_invocation` store; the single-process development harness shares one
`InMemoryMeteringSink` between narrator calls and the panel.

The panel returns nullable `latest_occurred_at` from measured invocation
records. The LLM usage screen uses that timestamp as the Deck snapshot's
`capturedAt` and doesn't replace stale metering freshness with browser
time. An empty metering source returns `null`. Emission remains
best-effort: a metering failure is logged and doesn't interrupt the
decision or chat path.

### 4.5 Routed turn deadline

The routed web narrator applies one total wall-clock deadline to a turn. The
default is 30 seconds and deployments can set
`FDAI_NARRATOR_TURN_TIMEOUT_SECONDS` from 1 through 300 seconds. Each candidate
receives an equal share of the remaining deadline, so one slow deployment can't
consume the failover budget for every other candidate. A timeout before the
first streamed token can fail over. A timeout after a token is visible stops the
stream and never combines text from another model.

## 5. DI seams

Every seam is a Protocol; the composition root wires the concrete
implementation. `core/` imports Protocols only
([coding-conventions.instructions.md § Provider Protocols](../../../.github/instructions/coding-conventions.instructions.md#safety)).

### 5.1 `Narrator` and the web generation backend

```python
class Narrator(Protocol):
    def translate(
        self,
        *,
        utterance: str,
        tools: Sequence[ToolSchema],
        principal_role: str,
    ) -> str | None: ...
```

- The core narrator receives only RBAC-visible tool descriptors and returns a canonical verb line
  or abstention. Coordinator parsing and tool RBAC remain authoritative.
- `AzureOpenAINarratorModel` owns its strict translator prompt in adapter code.
- Web `/chat` and `/chat/stream` use a separate asynchronous backend for AnswerPlan, evidence
  resolution, generation, and progressive verification; the synchronous Protocol is not a
  multi-turn generation API.
- Long read-only investigations emit cumulative `activity` rows and bounded Bragi `milestone`
  messages before the verified terminal answer. Activity rows update by stable id, stay out of
  narrator history, and preserve completed summaries across a tab reload.

The upstream default is
`AzureOpenAINarratorModel` under
[`services/operator-service/src/fdai_operator_service/`](../../../services/operator-service/src/fdai_operator_service/)
It calls Azure OpenAI chat completions as a strict one-line translator; composition supplies the
resolved endpoint and deployment.

### 5.2 `ConsoleTool`

```python
class SystemConsoleTool(Protocol):
    name: str
    description: str
    rbac_floor: Role
    side_effect_class: SideEffectClass

    def call(
        self,
        *,
        arguments: Mapping[str, Any],
        principal: Principal,
    ) -> ToolResult: ...
```

- `call()` receives coordinator-parsed arguments and the authenticated principal, then applies its
  own typed bounds. A web tool requiring history uses a separate asynchronous Operator API provider.
- `ToolResult` is a typed dataclass with `data` (serialisable), `preview`
  (short human-readable string the narrator gets to summarise), and
  optional `evidence_refs` (audit ids, PR urls, ARG resource ids) the
  narrator MUST cite verbatim.

### 5.3 `ConversationChannelAdapter`

```python
class ConversationChannelAdapter(Protocol):
  channel_kind: ConversationChannelKind
  def receive(self) -> AsyncIterator[InboundTurn]: ...
  async def send(
    self, response: OutboundResponse
  ) -> ChannelDeliveryReceipt | None: ...
```

- One adapter per vendor wire. Teams uses Bot Framework activities; Slack uses the signed HTTP
  Events API; web uses authenticated JSON/SSE Operator API routes. The CLI calls the shared Operator API
  and is not another vendor adapter.
- `InboundTurn` validates bounded channel, message, sender, thread, and text fields before the
  coordinator sees them. `ConversationChannelGateway` denies unresolved senders and suppresses
  duplicate message ids before any tool can run.
- Push-direction adapters
  ([channels-and-notifications.md](channels-and-notifications.md)) are
  **not** merged with pull adapters; they share credentials via config
  only. This keeps `send-only` and `receive-plus-send` blast-radius
  distinct.

### 5.4 Conversation work progress

Web, Slack, and Teams consume one ordered work-progress projection. The projection contains
bounded narrator milestones and stable activity updates; a channel changes presentation only. A
milestone closes the preceding activity group and states observed facts plus the next bounded
operation. It never exposes hidden reasoning or grants tool, approval, or execution authority.

The server selects the smallest sufficient presentation from actual work, never from prompt wording:

| Presentation | Selection | Channel behavior |
|--------------|-----------|------------------|
| None | No activity, handoff, or background task | Render only the answer. |
| Compact | One terminal read activity with no failure, retry, or handoff | Keep the compact session header and observed step visible, merge its linked source marker into the step, and fold only raw output and timestamps. |
| Timeline | Multiple activities, any handoff, failure, retry, code or file change, or non-read authority | Interleave milestones and activity groups in causal order. |
| Detached | The execution policy selects a durable background task | Render a durable task summary and deliver later progress or completion in the originating thread. |

Web keeps the current and completed activity group shells visible. A milestone or terminal frame
settles the preceding group without removing its observed steps; raw output and timestamps remain
folded and can be reopened without replaying work. Slack and Teams edit one acknowledged message with cumulative snapshots. Updates are
monotonic by revision and activity count, preserve redacted evidence, and finish with the canonical
answer. Provider limits can omit older detail but cannot reorder work, remove truncation markers,
or replace the accountable actor. A restart or delivery retry uses the stored immutable snapshots
and never reruns a tool.

## 6. Session model + memory

A `ConversationSession` is a bounded working projection over the
principal-scoped `ConversationHistoryStore`. PostgreSQL `conversation` and
`conversation_turn` rows are the memory of record in production; the browser
and in-process session hold disposable caches so the coordinator can recover
on any node without replaying raw text from the audit log.

### 6.1 Session fields

```python
@dataclass(frozen=True)
class ConversationSession:
  session_id: str
  principal: Principal
    channel_id: str                # channel adapter's channel identifier
    started_at: datetime
  turns: list[Turn]              # bounded core/CLI working projection
```

- `Turn` = `{turn_id, role, content, tool_calls?, tool_results?, tier,
  audit_entry_id}`.
- Production web history uses principal-scoped `ConversationHistoryStore` as its memory of record;
  the core session object is a disposable working projection.

### 6.2 Persistence rules

- **Conversation record**: inbound and terminal assistant turns append to
  `conversation_turn` with a stable request idempotency key. The audit and
  generic ontology projections retain ids, hashes, routing metadata, and
  evidence references, not raw conversation bodies.
- **User context**: `UserPreferenceStore` holds locale, verbosity, timezone,
  and learner consent. `UserMemoryStore` accepts only explicitly confirmed
  facts with source-turn provenance and optional expiry. `operator_memory`
  remains a separate store for approved resource-scoped operational knowledge.
- **Optimistic concurrency**: preference and policy writes require the current
  revision, using `0` only for creation. Policy and briefing-subscription deletes
  also require the current revision, so a stale Settings tab receives `409`.
- **Learner consent**: learner-facing turn projection is metadata-only by
  default. A raw turn body is available only when the same principal has an
  explicit `share_with_learner: true` preference.
- **Post-turn review**: after both conversation turns are persisted, the chat route submits a bounded
  envelope to a non-blocking queue. Bragi publishes it on `object.turn`; Norns performs deterministic
  eligibility and optional mixed-family review outside response latency. The Reader-visible `post-turn-reviews`
  panel is GET-only and exposes durable status, evidence references, proposal state, and aggregate acceptance without proposal bodies or approval controls. A materialized operator-memory proposal has a restrictive foreign key to its retained entry; conversation reuse also rechecks that exact entry is active and still cites the proposal.
- **Retention and projection cleanup**: the scheduler removes inactive
  conversations and old briefing runs after 90 days and removes memory facts
  at their explicit expiry. Each PostgreSQL source deletion atomically queues
  the corresponding ontology object ids. A leased worker deletes those
  metadata-only projections with bounded exponential retry, so a transient
  ontology failure cannot silently leave a permanent copy.
- **Projection consistency boundary**: preference, memory, policy, and briefing
  subscription writes enqueue source references in the same transaction as the
  source record. The scheduler replays those upserts with leased, bounded
  exponential retries. After five failed attempts it dead-letters the job for
  operator diagnostics instead of retrying forever. Ontology projections can
  be reconstructed from the source records.
- **Proactive behavior**: allowlisted `ConversationPolicy` records compile to
  fixed narrator prompt fragments. Opening and scheduled briefings share a
  deterministic `BriefingSpec`; durable subscriptions use IANA timezones and
  store each grounded `BriefingRun` for the owning principal.
- **Web conversation navigation**: the Console SPA renders a conversation
  list and a **New conversation** control. The list is a principal-scoped
  `localStorage` index over isolated transcript caches, so switching threads,
  reloading the tab, or reopening the browser restores completed turns without
  mixing agent-scoped and general conversations. Environments that block persistent
  browser storage fall back to `sessionStorage`. Operators can search the loaded transcript and
  move between matching turns. Default conversations are isolated by a
  non-identifying user hash and normalized URL pathname; query-only filter
  changes reuse the pathname session, while a different menu or analytical
  detail URL starts or restores its own transcript. The default narrator is
  **Bragi**, and both its reply header and conversation row use the Bragi agent
  icon rather than the generic Deck label. **Clear cache** and **Remove cached
  conversation** delete browser copies only; they never delete durable server
  history. Selecting `Ask <agent>` from an agent card creates a new user-scoped
  conversation on every click and stores that agent as the target before the first turn. It never
  restores or appends to an earlier agent transcript. Earlier conversations remain selectable from
  history. An incident-bound conversation keeps its stable incident identity for explicit resume.
  This browser index is navigation state only. Each user-scoped conversation key is also its stable
  server conversation id. On a cache miss, the Command Deck reloads principal-scoped turns from the
  server and mirrors them back into browser-local storage. At authenticated startup, it also merges
  up to 1,000 server-owned conversation metadata records into the browser index; transcript bodies
  still load only when selected. A legacy conversation with
  an earlier random id remains selectable and restores its title from the first operator turn when
  opened. A floating Deck remains open across route navigation and
  live screen re-renders. In full-workspace mode, an Activity Bar group closes it and
  opens that group's first visible child page; otherwise explicit close or `Escape` dismisses it.
  L3 response language follows the current turn: a Korean prompt renders a
  Korean answer even when the console display locale is English. Otherwise,
  the operator's configured locale controls the answer language. Before returning localized
  prose, the narrator proofreads only its own surrounding prose for malformed or nonsensical
  words, accidental character sequences, duplicated fragments, and accidental language mixing.
  It never corrects, normalizes, translates, or rewrites quoted evidence values, identifiers,
  code, or tool output.
  Before evidence verification, terminal-answer integrity rejects Unicode replacement characters,
  unpaired surrogate code points, disallowed C0/C1 controls, and bidirectional override or isolate
  controls. The route returns a localized unverified answer instead of persisting malformed text.
  Newlines, tabs, and script-shaping zero-width joiners remain allowed.
  Verification compares trimmed answers in Unicode NFC form so canonically equivalent Korean text
  does not create a false correction revision. The returned canonical evidence text is not rewritten.
  Model-generated Korean answers receive one bounded post-generation review before terminal
  evidence verification. The route masks exact snapshot values, identifiers, URLs, and code as
  ordered placeholders; the reviewer can pass the draft, rewrite narrator-authored prose, or reject
  an unrepairable draft. A rewrite is accepted only when every placeholder appears exactly once in
  its original order, then the route restores the original evidence byte-for-byte. An explicit
  rejection becomes a localized unverified answer. Reviewer outage, invalid JSON, placeholder
  mismatch, English output, and deterministic evidence fast paths add no second model dependency and
  continue through the existing factual verifier. JSON and SSE expose bounded `answer_quality`
  metadata; SSE replaces a changed visible draft through the existing `revision` frame.
  The navigation list groups conversations as **Current screen**, **Other
  screens**, and **Agents**. Each pathname owns one non-removable default
  screen conversation. **New conversation** creates an ephemeral empty thread
  for the current pathname; it enters the index only after the first operator
  turn, using that prompt as its normalized title. Closing or navigating away
  before the first turn discards the empty thread. A screen thread's origin
  pathname and label are immutable. Selecting a thread under **Other screens**
  navigates to its origin before restoring the transcript, so prior turns are
  never combined with evidence from a different screen. Agent conversations
  remain in their own group and retain their explicit agent scope.
- **Operational memory**: `operator_memory` stores approved, resource-scoped
  notes such as exceptions and runbook hints. It requires a distinct approver
  and never doubles as personal narrator memory.
- **Month 1+**: recurring investigation patterns detected across sessions
  become discovery-loop signals (§9). Still not narrator memory - a rule
  candidate in the catalog is the resulting artifact.

### 6.3 What we deliberately do not store

- The narrator's raw generation trace, per-token logs, or embedding
  vectors of the operator's prompts. The audit entry contains the tool
  calls and the *summary* the narrator returned; the model's internal
  chain is not persisted.
- Any secret redacted at the channel boundary. The redactor lives in the
  channel adapter (same policy as
  [channels-and-notifications.md § 8 - redaction](channels-and-notifications.md#8-redaction)).

### 6.4 Working context assembly (no turn limit)

The session transcript is the **memory of record**: every turn is
persisted in `ConversationHistoryStore` until the retention policy removes it, so the
session remembers everything that happened. What the narrator receives on
a given turn is a separate, **bounded** projection - the *working
context* - re-assembled every turn under a token budget so a long session
never blows up the prompt. Memory (lossless, `O(L)` in session length)
and prompt (bounded, constant ceiling) are deliberately distinct.

The JSON and SSE chat routes resolve history from the durable store by the authenticated
`(principal_id, conversation_id)` pair before follow-up planning. They never use client-provided
history when that store is configured. The resolver reads the complete transcript without a turn
limit and preserves every character while the history remains within the default 160,000-byte
budget. Above that budget it compacts older chunks with two bounded attempts while retaining the
newest 20 turns word-for-word. A read timeout, compaction timeout, provider error, or excessive
compaction fan-out degrades to a second principal-scoped read of the newest 20 turns. If that read
also fails, the route uses empty history instead of accepting a browser copy that could cross the
authorization boundary.

Content-policy decisions are typed, non-retryable outcomes rather than provider outages. A blocked
history-compaction chunk is split under bounded depth and probe budgets until only the triggering
turn is omitted from model context; its durable transcript row remains unchanged. The prompt gets a
content-free omission marker, while the operator and assistant turns retain `history_mode`, omitted
count, and policy stage metadata. No digest derived from blocked content reaches the provider,
browser, logs, or durable metadata. A final narrator input block retries once with policy-safe
compacted history and once with empty history under one 30-second recovery deadline; an output block
is never retried or routed to another model. An unrecoverable block writes a body-free SYSTEM
receipt with one idempotent retry and no assistant turn.

Assembly is the pure
[`compose_working_context`](../../../services/core-control-plane/src/fdai/core/working_context/composer.py)
policy. It never caps the *number of turns*; it caps *tokens*, across four
tiers drawn from a
[`ContextBudget`](../../../services/core-control-plane/src/fdai/core/working_context/types.py):

- **Pinned** - standing operator constraints and unresolved decisions;
  always included, and fail-closed (a `WorkingContextError`) if they alone
  overflow the budget, never silently dropped.
- **Typed facts** - deterministic, no-LLM context projected from the typed
  pipeline (audit entries, T0 verdicts) and HIL-approved operator memory
  (preferences, override notes, forbidden actions, runbook hints via
  `operator_memory_to_entries`); injected as `trusted` ground truth and never
  summarised. Forbidden-action notes are `pinned` so budget pressure never
  drops a safety constraint. This is how standing operator knowledge reaches
  the prompt - as an auditable, scope-tagged trusted layer, not opaque
  narrator memory (section 1).
- **Verbatim recent** - the newest turns word-for-word, filling a ratio of
  the history budget (token-based, not a turn count).
- **Relevance retrieval** - older turns pulled back in by similarity to
  the current utterance (`t1.embedding` + pgvector), so a turn outside the
  verbatim window still returns when it matters.
- **Hierarchical summary** - everything else folded into rolling summaries
  (level 1 folds turns, level 2 folds level-1 summaries), so the summary
  tier grows `O(log L)` in session length `L`. The pure
  [`plan_summarization`](../../../services/core-control-plane/src/fdai/core/working_context/planner.py)
  policy decides which turns fold into which level - full `fold_factor`
  chunks only, so a turn is never folded alone then re-folded - and the
  [`SummarizationOrchestrator`](../../../services/core-control-plane/src/fdai/core/working_context/orchestrator.py)
  drives the plan against the `TranscriptSummarizer` seam so each planned
  fold runs off the hot path with a stable order.

Unused budget in a higher-priority tier spills to the next, so a short
session fills with verbatim turns rather than padding with summaries. The
two I/O seams -
[`TranscriptSummarizer`](../../../services/core-control-plane/src/fdai/core/working_context/summarizer.py)
(mini-model folding, `t1.judge`) and `TranscriptRetriever` (pgvector) -
are DI Protocols with deterministic no-LLM fakes shipped upstream. Every
assembly writes a `context_manifest` to the turn audit (verbatim ids,
summary hashes, retrieved ids, dropped ids, per-tier tokens) so any prompt
is reconstructable from the memory of record.

The end-to-end [`assemble_turn_context`](../../../services/core-control-plane/src/fdai/core/conversation/context_bridge.py)
combines session verbatim, operator memory, retrieval, and summaries into one bounded context. With
no retriever, it uses `session_to_working_context` plus operator memory.

The unchanged `deterministic-tiered-v1@1.0.0` default now passes through the mandatory
`ContextSelectionPolicy` validator. Bounded candidates stay outside request latency; the GET-only
comparison view has no lifecycle controls. See [Context Selection Policy](../decisioning/context-selection-policy.md).

**Same mechanism for agents.** The agent conversational port
(agent-to-agent introspection) uses the same composer over a
correlation-scoped transcript. Typed-pipeline events flow in as trusted
`typed-fact` entries, keeping the no-LLM deterministic history and the LLM
conversation on one timeline without crossing the trust boundary -
external or model-generated content stays `trusted="false"` and is wrapped
as data, exactly as the T2 quality gate treats event payloads.
