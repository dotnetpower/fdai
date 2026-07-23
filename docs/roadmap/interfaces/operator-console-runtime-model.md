---
title: Operator Console - Narrator, DI Seams, and Session Model
---

# Operator Console - Narrator, DI Seams, and Session Model

> Focused owner document extracted from [operator-console.md](operator-console.md) sections 4-6.

## 4. Narrator - LLM tier model

The narrator is the console's LLM translator layer. Core/CLI use the `Narrator` Protocol, while
web progressive-answer generation uses a separate read API backend seam. Azure binding is selected
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
sensitive-data denials. This classifier prompt is separate from Bragi's answer-generation prompt.

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

Derived price isn't exposed by the read API or console because regional,
currency, and negotiated rates can make a configured estimate differ
from the provider invoice. A deployment can still use its configured
price table for an internal budget gate. Because the headless core and
read API are separate processes, production uses the durable Postgres
`llm_invocation` store; the single-process development harness shares one
`InMemoryMeteringSink` between narrator calls and the panel.

The panel returns nullable `latest_occurred_at` from measured invocation
records. The LLM usage screen uses that timestamp as the Deck snapshot's
`capturedAt` and doesn't replace stale metering freshness with browser
time. An empty metering source returns `null`. Emission remains
best-effort: a metering failure is logged and doesn't interrupt the
decision or chat path.

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
[`src/fdai/delivery/azure/llm/narrator.py`](../../../src/fdai/delivery/azure/llm/narrator.py)
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
  own typed bounds. A web tool requiring history uses a separate asynchronous read API provider.
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
  Events API; web uses authenticated JSON/SSE read API routes. The CLI calls the shared read API
  and is not another vendor adapter.
- `InboundTurn` validates bounded channel, message, sender, thread, and text fields before the
  coordinator sees them. `ConversationChannelGateway` denies unresolved senders and suppresses
  duplicate message ids before any tool can run.
- Push-direction adapters
  ([channels-and-notifications.md](channels-and-notifications.md)) are
  **not** merged with pull adapters; they share credentials via config
  only. This keeps `send-only` and `receive-plus-send` blast-radius
  distinct.

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
  panel is GET-only and exposes durable status, evidence references, proposal state, and aggregate acceptance without proposal bodies or approval controls.
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
  list and a **New conversation** control. The list is a tab-scoped
  `sessionStorage` index over isolated transcript caches, so switching threads
  or reloading the tab restores completed turns without mixing agent-scoped
  and general conversations. Operators can search the loaded transcript and
  move between matching turns. Default conversations are isolated by a
  non-identifying user hash and normalized URL pathname; query-only filter
  changes reuse the pathname session, while a different menu or analytical
  detail URL starts or restores its own transcript. The default narrator is
  **Bragi**, and both its reply header and conversation row use the Bragi agent
  icon rather than the generic Deck label. **Clear cache** and **Remove cached
  conversation** delete browser copies only; they never delete durable server
  history. This browser index is navigation state only. On a cache miss, the
  Command Deck reloads principal-scoped turns from the server and mirrors them
  back into `sessionStorage`. A floating Deck remains open across route navigation and
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

Assembly is the pure
[`compose_working_context`](../../../src/fdai/core/working_context/composer.py)
policy. It never caps the *number of turns*; it caps *tokens*, across four
tiers drawn from a
[`ContextBudget`](../../../src/fdai/core/working_context/types.py):

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
  [`plan_summarization`](../../../src/fdai/core/working_context/planner.py)
  policy decides which turns fold into which level - full `fold_factor`
  chunks only, so a turn is never folded alone then re-folded - and the
  [`SummarizationOrchestrator`](../../../src/fdai/core/working_context/orchestrator.py)
  drives the plan against the `TranscriptSummarizer` seam so each planned
  fold runs off the hot path with a stable order.

Unused budget in a higher-priority tier spills to the next, so a short
session fills with verbatim turns rather than padding with summaries. The
two I/O seams -
[`TranscriptSummarizer`](../../../src/fdai/core/working_context/summarizer.py)
(mini-model folding, `t1.judge`) and `TranscriptRetriever` (pgvector) -
are DI Protocols with deterministic no-LLM fakes shipped upstream. Every
assembly writes a `context_manifest` to the turn audit (verbatim ids,
summary hashes, retrieved ids, dropped ids, per-tier tokens) so any prompt
is reconstructable from the memory of record.

The end-to-end [`assemble_turn_context`](../../../src/fdai/core/conversation/context_bridge.py)
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
