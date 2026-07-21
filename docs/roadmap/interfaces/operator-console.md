---
title: Operator Console (Conversational)
---

# Operator Console (Conversational)

How a human operator talks *back to* FDAI through a conversational
interface across the CLI, Teams, Slack, and web chat. This
document is authoritative for the **conversational surface**: the layered
architecture, the tool catalog, the LLM tier model, session persistence,
per-tool RBAC, safety invariants, and current rollout status.

Push-direction notifications (system → human) live in
[channels-and-notifications.md](channels-and-notifications.md); the read-only
console SPA lives under
[project-structure.md § console/](../architecture/project-structure.md#console-static-web-app).
The SPA resolves display locale from the operator's console preference and renders reusable
English-source messages through the main catalog or a complete route-local English/Korean catalog
pair. Machine values, identifiers, and provider payloads stay unchanged; presentation helpers map
known values to localized labels. Static key coverage, catalog parity, route-local fallback tests,
and the full console test suite prevent untranslated display text from returning.
This doc covers the **pull direction** - the operator asks, simulates,
approves - across every channel the notification doc already ships adapters
for. Push and pull share the same channel credentials and the same audit
contract, but they are distinct integration surfaces.

> Customer-agnostic: every channel id, LLM deployment name, resource id, and
> group name below is a placeholder. A fork supplies concrete values via
> config
> ([generic-scope.instructions.md](../../../.github/instructions/generic-scope.instructions.md)).

## 1. Framing - what this is (and what it is not)

The operator console does **not** carry judgment authority. FDAI's
judgment stays where it already is - the deterministic engine (T0),
the quality gate (T2 verifier), the risk gate, and the shipped Rego
policies. The console is the **conversational surface** through which
an operator inspects that judgment, simulates change, and approves
what the system has already queued.

Three properties follow directly:

- **LLM is a translator, not a judge.** Natural language in, tool calls out;
  tool results in, natural language out. The LLM never grants execution
  eligibility - only the verifier does
  ([architecture.instructions.md § Design Principles](../../../.github/instructions/architecture.instructions.md#design-principles)).
- **Tools expose pipeline stages, not primitive data sources.** Instead of
  `query_log()` + `query_metric()` + `read_config()` that the LLM must
  compose into a diagnosis, the console exposes
  `describe_event()`, `explain_verdict()`, `simulate_change()`. The system
  has already done the reasoning; the operator asks about the result.
- **Growth is catalog growth, not model memory growth.** Recurring
  investigation patterns become new rule candidates via the discovery loop
  ([architecture.instructions.md § Rule Catalog](../../../.github/instructions/architecture.instructions.md#rule-catalog)) -
  not opaque LLM session memory. Every state that persists across
  conversations lives in `audit_log` + `operator_memory` where it is
  auditable, exportable, and CSP-neutral.

### 1.1 Vocabulary added to the shared glossary

The following tokens are added to the shared vocabulary in
[architecture.instructions.md](../../../.github/instructions/architecture.instructions.md)
and are used consistently by every referring doc:

- **operator-console** - the layered surface documented here.
- **narrator** - the LLM tier of the operator console (translator role;
  never a judge). Distinct from the T2 quality-gate role, which is a
  domain reasoner over a proposed action.
- **operator-conversation** - one bounded exchange between an operator and
  the console (multi-turn, RBAC-scoped, audited).
- **console-tool** - one exposed pipeline stage or catalog view the narrator
  may call.

## 2. Three-layer architecture

```mermaid
flowchart TD
  subgraph L3["Layer 3 — Channel (thin adapter)"]
    CLI["CLI REPL"]
    TEAMS_PULL["Teams (pull)"]
    SLACK_PULL["Slack (pull)"]
    WEB["Web chat (Console SPA)"]
  end
  subgraph L2["Layer 2 — Conversation Coordinator"]
    NARR["Narrator (LLM)\nt1.judge default\nt2.reasoner escalation"]
    INTENT["Intent classify\n(read | simulate | approve | breakglass)"]
    RBAC["RBAC gate\n(per-tool role floor)"]
    VERIF["Verifier re-check\n(no auto-execute)"]
    SESS["Session state\n(audit-log-backed)"]
  end
  subgraph L1["Layer 1 — Existing deterministic core (unchanged)"]
    CL["ControlLoop"]
    RULES["RuleIndex / T0Engine"]
    QG["QualityGate"]
    EXEC["ShadowExecutor / RiskGate"]
    INV["Inventory / StateStore"]
  end
  CLI --> INTENT
  TEAMS_PULL --> INTENT
  SLACK_PULL --> INTENT
  WEB --> INTENT
  INTENT --> RBAC --> NARR --> VERIF --> SESS
  NARR -.tool call.-> CL
  NARR -.tool call.-> RULES
  NARR -.tool call.-> QG
  NARR -.tool call.-> EXEC
  NARR -.tool call.-> INV
```

- **Layer 3 (Channel)** is thin. Every channel adapter converts one turn
  from the wire format (stdin / Teams Activity / Slack event / authenticated HTTP request and SSE)
  frame) into a `ConversationTurn` and back. No judgment lives here.
- **Layer 2 (Coordinator)** owns intent classification, RBAC gating, tool
  dispatch, verifier re-check, and session bookkeeping. Core translation uses the `Narrator`
  Protocol; web generation uses the read API backend seam, so deployments can bind providers.
- **Layer 1 (Core)** is exactly the deterministic core that already ships.
  The console adds no new judgment path, no new persistence store, and no
  new execution vector. A console tool call resolves to a call the
  existing pipeline already knows how to make.

### 2.1 Module map

- [`src/fdai/core/conversation/`](../../../src/fdai/core/conversation)
  - `coordinator.py` - `ConversationCoordinator` (Layer 2 orchestrator).
  - `tools.py` - `SystemConsoleTool` Protocol + per-tool implementations that
    delegate to Layer 1 modules only.
  - `narrator.py` - synchronous `Narrator` Protocol, deterministic verb schemas, and RBAC-scoped descriptors.
  - `session.py` - disposable core/CLI `ConversationSession` projection. Principal-scoped
    `ConversationHistoryStore` owns production web transcripts.
- [`cli/`](../../../cli)
  - `src/repl.ts` - IME-safe stdin/stdout channel for the shared `POST /chat`
    coordinator.
  - `src/cockpit.ts` - live SSE presentation that publishes a
    self-describing screen snapshot to the same coordinator.
- [`src/fdai/core/conversation/channel_gateway.py`](../../../src/fdai/core/conversation/channel_gateway.py)
  - authenticates senders, claims message idempotency keys, calls the existing coordinator, and
    persists the complete response before provider send when durable delivery is configured.
    Verified bindings and recovery follow [durable delivery](durable-conversation-delivery.md).
- [`src/fdai/delivery/channels/`](../../../src/fdai/delivery/channels)
  - `teams.py` - normalizes Bot Framework activities after bearer-token verification and uses an
    injected publisher for replies. It never trusts a payload-supplied reply URL.
  - `slack.py` - verifies timestamped Slack request signatures, rejects replayed or bot-authored
    events, normalizes messages, and uses an injected publisher for replies.
  - Web chat continues to use the authenticated read-console chat API. A dedicated WebSocket
    adapter remains optional future transport work.
- Scheduler Runs, Automation Blueprints, Scheduled Continuations, [governed trajectory datasets](governed-trajectory-datasets.md), and [execution backend status](execution-backends.md) expose read-only metadata. These views have no enable, submit, retry, cancel, cleanup, execute, or approval controls; omit credentials and Thor's identity; and keep commands outside the SPA.
- [`tools/chat.py`](../../../tools/chat.py) - headless JSONL development harness
  for the core coordinator. It is not a second policy implementation.

The CSP-neutral rule stays intact: `core/conversation/` imports **only**
Protocols. All Azure SDK / httpx / Bot Framework calls live under
`delivery/`.

## 3. Tool catalog

Tools are **pipeline-stage views**. A core tool has a stable name, bounded `argument_hint`, RBAC
floor, side-effect class, and documented failure surface. Web/provider-specific tools can add
their own typed request contracts. New tools are additive; they never override a rule or policy.

`RuntimeToolDiscovery` provides search and describe over installed narrator schemas. It
intersects schema metadata with the actually installed tool names, applies the same RBAC ladder as
the coordinator, and returns only name, verb, description, argument hint, RBAC floor, and
side-effect class. A lower-role principal cannot discover a higher-role tool, and descriptors
contain no handler or invocation capability. Discovery improves navigation; it grants no new
authority.

The same projection is available through the deterministic channel verbs `search_tools` and
`describe_tool`, and typed read RPC methods `tools.search` and `tools.describe`. Channel calls use
the resolved `Principal`; RPC calls derive the role from server-authorized scopes, never from a
caller-supplied role parameter. Both surfaces return descriptors only and cannot invoke the target.

### 3.1 Day-1 tool set (read-only + explain)

| Tool | Purpose | RBAC floor | Delegates to |
|------|---------|-----------|--------------|
| `describe_event(payload)` | Run one event through `EventIngest → TrustRouter → T0Engine` in memory (no PR, no audit write); return the resulting routing decision + candidate rule ids. | Reader | `EventIngest`, `TrustRouter`, `T0Engine` |
| `explain_verdict(event_id)` | Read the audit trail for one already-processed event; return the tier, decision, citing rule ids, verifier report, mode. | Reader | `StateStore.query_audit()` |
| `explore_catalog(query)` | Search the shipped rule catalog / action-type catalog / ontology vocabulary by id, keyword, or resource_type. | Reader | Loaded catalogs (no I/O) |
| `query_audit(filters)` | Structured audit query: by event id, actor, decision, mode, time window. Paginated. | Reader | `StateStore.query_audit()` |
| `query_inventory(resource_type, filter)` | Server-owned Azure inventory-view count, list, type, location, resource-group, name, status, and relationship queries. Returns bounded allowlisted fields plus active view and snapshot source/freshness; local VM state comes from `az vm list --show-details`; provider failure renders unavailable. | Reader | `InventoryGraphProvider` |
| `capture_browser_evidence(policy_id, policy_version, source_url, stable_selectors)` | Submit a credential-free bounded capture under an exact server-owned policy. Returns an immutable artifact receipt; never returns a page or interaction API. | Reader | `BrowserEvidenceCaptureService` |

**Reader-floor tools are provably side-effect-free.** `describe_event`
runs `EventIngest -> TrustRouter -> T0Engine` **in memory only**: it does
not invoke T1 embedding lookups, T2 models, external adapters, or any
mutation surface, and it writes no PR and no audit entry. Its
`side_effect_class` is `read`, and a shadow-mode test asserts it never
touches the executor, the PR adapter, or the state store. This is what
keeps it safe at the Reader floor. Browser capture follows [Browser evidence collection](browser-evidence.md); Bragi never receives a browser handle.

### 3.2 Week-1 additions (write / approve / runbook)

| Tool | Purpose | RBAC floor | Notes |
|------|---------|-----------|-------|
| `simulate_change(scenario)` | End-to-end `ControlLoop.process()` in **shadow** mode; return the executor outcome + generated PR intent without publishing. | Contributor | Shadow-only; still writes an audit entry so the operator can find it in `query_audit`. |
| `approve_hil(approval_id, decision, justification)` | Resolve one queued HIL item. Verifier + `no_self_approval` invariant re-checked. | Approver | Approver group; same principal as PR gate enforcement in [security-and-identity.md](../architecture/security-and-identity.md). |
| `list_hil()` | Return currently queued HIL items visible to the caller's role. | Approver | Reader-visible would leak intent to non-approvers; kept Approver-scoped. |
| `run_runbook(name, params, dry_run)` | Execute one runbook under `docs/runbooks/`. `dry_run=true` requires Contributor; `dry_run=false` requires Owner. | Contributor / Owner | Concrete runbook adapters (e.g. `db_dr_drill_cli`) are already shipped; this tool routes by name. |
| `activate_break_glass(reason, expiry)` | Validate TTL/reason and create Owner-page and audit receipts. | Reader | The current implementation does not change the session principal/role or grant elevation. |

Two clarifications on the write set:

- **`simulate_change` writing an audit entry does not violate "shadow
  never mutates".** The audit log is append-only; recording *that a
  simulation ran* is not a mutation of any managed resource. The
  shadow-mode property test asserts no executor / PR / state-store write,
  and explicitly allows the audit append.
- **`list_hil` (Approver) vs the read-console HIL view (Reader) are
  different surfaces.** The read-only Console SPA shows Reader the
  *existence and count* of queued HIL items (dashboard tile); `list_hil`
  returns the *full item detail* (target, proposed action, requester),
  which can reveal sensitive intent, so it stays Approver-scoped. The two
  are intentionally not the same visibility.

### 3.3 Month-1 additions (observation depth)

| Tool | Purpose | RBAC floor | Depends on |
|------|---------|-----------|-------------|
| `query_log(query, window)` | Bounded, single-workspace Log Analytics KQL query. | Reader | new `AzureMonitorAdapter` |
| `query_metric(namespace, metric, window, aggregation)` | Azure Monitor metrics API. | Reader | new `AzureMonitorAdapter` |
| `query_deployments(window)` | Git + ARM deployment-history join. | Reader | new `DeploymentHistoryAdapter` |
| `correlate_incident(incident_id)` | Multi-signal correlation over ingest events + audit + inventory + logs + metrics for one incident id. | Reader | Above three + `event_ingest` |

The Month-1 additions bring the console close to a multi-signal
incident-response experience, but they still surface
**already-correlated** results; the correlator lives in Layer 1, not
inside the narrator.

### 3.4 Tool discovery contract

Each tool declares:

- `name` - CLI-friendly snake_case verb (no `describe-*` / `explore-*`
  prefix taxonomy; the verb itself is the category).
- `description` - one sentence, English, no marketing language.
- `argument_hint` - bounded argument shape expected by the canonical verb parser. Each tool
  reapplies typed and bounded validation before invocation; invalid arguments never become a
  partial call.
- `rbac_floor` - the lowest role that MAY call the tool.
- `side_effect_class` - `read` / `simulate` / `approve` / `execute` /
  `breakglass`. The audit entry carries this class so downstream analytics
  can slice cheaply.
- `failure_modes` - typed error surface documented in the tool's docstring.

`RuntimeToolDiscovery` and `tools.search`/`tools.describe` return descriptors without handlers or
invocation capability. The narrator sees only the same descriptors allowed by the principal role.

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
  the operator's configured locale controls the answer language.
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

## 7. Safety invariants (chat does not weaken them)

The four autonomy invariants from
[coding-conventions.instructions.md § Safety](../../../.github/instructions/coding-conventions.instructions.md#safety)
apply unchanged. Chat adds three of its own on top.

### 7.1 The four existing invariants

Every write-class tool call (`simulate_change` in enforce mode -
disallowed today - `approve_hil`, `run_runbook --live`) MUST carry:

1. **Stop-condition** - the underlying ActionType already declares one;
   the console does not add or remove.
2. **Rollback path** - reused from the ActionType's `rollback_contract`.
3. **Blast-radius limit** - reused from the ActionType's
   `blast_radius` block; the operator cannot widen it via natural
   language.
4. **Audit entry** - written by the coordinator before the tool actually
   dispatches.

### 7.2 Three chat-specific invariants

5. **Verifier re-check on every write-class tool call.** After the
   narrator emits a `tool_calls` frame that targets a write-class tool,
   the coordinator re-runs the T0Engine + policy-as-code check against
   the tool arguments. On abstain / deny, the tool call is dropped and
   the turn falls through to HIL (see §7.4). This is the mechanical
   guarantee behind "the LLM never grants execution eligibility".
6. **No self-approval, chat-scoped.** `approve_hil` refuses when the
   caller's Entra `oid` matches the requester recorded on the queued
   item, even if the caller holds Owner. This is the same invariant as
   the PR gate ([security-and-identity.md](../architecture/security-and-identity.md));
   chat adds the invariant name to the audit reason on refusal.
7. **A BreakGlass request must be time-boxed and explicit.** `activate_break_glass`
   requires `(reason, expiry <= 4h)` and pages every configured Owner via
   the push-direction Slack/Teams adapter
   ([channels-and-notifications.md](channels-and-notifications.md)). No
  silent elevation. **The request is fail-closed on notification:** if the
   primary pager channel is down, the coordinator tries the configured
  fallback channel; if *no* channel confirms delivery, the request is
   **refused** (a break-glass with no audit witness is more dangerous than
   a delayed emergency), and the refusal is itself audited so an Owner can
  see the attempt. The shipped tool returns pager and audit receipts only; it does not change
  `ConversationSession`, `Principal`, or the RiskGate role axis, so it raises no approval
  eligibility. Until a session-scoped grant store and dispatch integration exist, no elevation
  occurs. A future grant must never return `auto` or permit self-approval (invariant 6). The exact
   eligibility semantics are defined in
   [user-rbac-and-identity.md § 2](user-rbac-and-identity.md#2-role-model-4-tiers--break-glass)
   and mirrored by the RiskGate role axis
   ([execution-model.md § 2.5](../decisioning/execution-model.md#25-axis-f---role-rbac)).

### 7.3 BreakGlass request receipt

The current `ActivateBreakGlassTool` result contains `activated_at`, `expires_at`, a redacted
reason, `pager_receipt`, and `audit_id`. Its `max_ttl_seconds` default and ceiling are `14400`; a
larger adapter setting is rejected. This result is not an authorization grant record, and no
persistent store currently enforces session-end or expiry revocation. No downstream path may use
the receipt as elevation evidence.

### 7.4 HIL fall-through when the LLM proposes a write

The narrator MAY, when the operator says "just fix it", emit a
`tool_call` for `run_runbook(dry_run=false)` or `approve_hil`. On the
verifier re-check (invariant 5):

- If verifier passes AND RBAC is satisfied → the tool call proceeds.
- If verifier abstains or RBAC is under the floor → the coordinator
  substitutes an `enqueue_hil(...)` call that files a review item in the
  existing HIL queue and returns "I filed a HIL item, id X" to the
  operator.
- Under no circumstance does the write happen without an audit entry
  before dispatch.

## 8. Channel integration (push vs pull)

The channel abstraction ([channels-and-notifications.md](channels-and-notifications.md))
already handles push (system → human). Pull uses **separate adapters and configuration contracts**.
A deployment can reuse a secret provider or workload identity, but it does not derive inbound
conversation enablement from the outbound notification matrix. This separation preserves the
different trust posture and blast radius of send-only and receive-plus-send surfaces.

The shared pull-direction contract, gateway, Slack signed ingress, Teams authenticated activity
normalizer, bounded Starlette routes, Slack Web API publisher, and Teams Bot Framework publisher
are implemented. The Slack route verifies timestamped signatures. The Teams route calls an
injected bearer authenticator before parsing activity JSON. Reply publishers use only configured
HTTPS endpoints, injected app/workload credentials, and server-owned conversation resolution.
`ProductionChannelRuntime` binds the concrete Bot Framework JWT verifier, Teams principal resolver,
Slack secrets/app credentials, fixed-endpoint publishers, and background gateway lifecycle.
Missing required credentials or identity bindings fail startup before traffic. Those bindings stay
in `delivery/`; they do not change the coordinator.

`ChannelAccessService` is the sender-access foundation for those principal resolvers. Each channel
selects `disabled`, `allowlist`, or `pairing`. Unknown senders resolve to no principal and never
reach the coordinator. Pairing mode issues a bounded, expiring challenge, stores only its SHA-256
digest, caps pending requests per channel, requires a separately authorized approver, verifies the
code in constant time, and maps the approved sender to an existing FDAI principal. Disabled and
allowlist modes never self-enroll a sender. The PostgreSQL store now enforces the pending cap and
approval transition atomically across replicas. Native challenge delivery replies in the originating
thread and conditionally removes the pending digest when delivery fails. The code is never stored or
placed in response metadata.

`CrossChannelIdentityLinkService` records an explicit relationship only after both channel senders
are independently paired to the same principal. It rejects same-channel links, self-approval,
unapproved endpoints, and any attempt to relate two distinct principals. The durable link is
idempotent and does not merge principal records, roles, sessions, or audit histories.

| Channel | Push (existing) | Pull (this doc) | Shared config |
|---------|-----------------|-----------------|---------------|
| Teams | A1 HIL and outbound notification adapters | `TeamsBotChannel` + authenticated bounded activity route + workload-identity reply publisher + principal binding | Deployments can reuse selected identity/secret providers. |
| Slack | `SlackWebhookChannel` and A1 adapter | `SlackBotChannel` + signed Events API route + fixed-endpoint Web API reply publisher | Deployments can reuse selected secret providers. |
| Email | send-only | (not planned; asynchronous, ill-suited to interactive) | n/a |
| Webhook | send-only | (not planned; caller must own an interactive protocol themselves) | n/a |
| Pager (PagerDuty) | send-only | (not planned) | n/a |
| SMS | send-only | (not planned) | n/a |
| Web chat | n/a | Authenticated `POST /chat` and `POST /chat/stream` SSE | Console SPA/read API config |
| CLI | n/a | stdin/stdout UI calling the shared read API `/chat` | local auth/read API config |

### 8.1 Separate channel configuration

[`config/notifications-matrix.yaml`](../../../config/notifications-matrix.yaml) owns outbound
notification routing only. Conversation channels use separate enablement, secret references,
Teams identity/principal bindings, and queue-capacity settings. Sharing a credential backend does
not merge configuration ownership.

## 9. Growth model (catalog + operator memory)

The console gets better over time via three deterministic mechanisms.
Model-side learning is **not** one of them.

### 9.1 Day 1

The Day-1 console can answer:

- "What rules apply to `network.nsg` in `example-rg`?"
  → `query_inventory` + `explore_catalog`.
- "Why did event `<id>` route to HIL?" → `explain_verdict`.
- "Show me every audit entry for `object-storage.public-access.deny` in
  the last 24h." → `query_audit`.
- "If I create a storage account with public access enabled, what would
  the loop do?" → `describe_event`.

No writes, no runbooks, no approvals - just orientation.

### 9.2 Week 1

Adds `simulate_change`, `approve_hil`, `run_runbook --dry-run`, and the
Teams / Slack pull adapters. The console can now:

- Preview a change end-to-end in shadow.
- Resolve queued HIL items with the same identity gate the PR flow uses.
- Trigger the shipped runbooks
  ([docs/runbooks/](../../runbooks)) from any channel.

### 9.3 Month 1

Adds the observation-depth tools (§3.3) and the discovery-loop hook:

- The coordinator publishes a `console.recurrent_query` signal to the
  discovery-loop input stream when the same tool-argument shape appears
  N times across distinct principals in a rolling window (N configured;
  default 5 / week).
- The rule-candidate generator
  ([rule-governance.md](../rules-and-detection/rule-governance.md)) receives that signal like
  any other; the resulting rule ships shadow-first through the same
  promotion pipeline.

The result is that a common investigation pattern in chat becomes a
first-class rule in the catalog - **the console grows the catalog, not
itself**.

## 10. Rollout reconciliation

The original Day/Week/Month sequence is historical implementation context, not the current
availability source.

| Slice | Current status |
|-------|----------------|
| Core/CLI translator | `Narrator`, `AzureOpenAINarratorModel`, coordinator, read tools, Python headless harness, and shared-API TypeScript CLI ship. |
| Write/approval tools | Simulation, HIL, runbook, and proposal routes ship. Break-glass stops at the pager/audit request receipt in §7.3 and grants no elevation. |
| Teams/Slack conversation | `ProductionChannelRuntime`, authenticated ingress, principal resolution, publishers, and optional durable replies ship; environment-owned enablement and credentials remain required. |
| Web chat and memory | JSON/SSE chat, principal-scoped history/preferences/memory, AnswerPlan, and progressive verification ship. |
| Observation/discovery | Azure observation tools and recurrent-query hooks require bound providers and measured evidence. Catalog presence alone proves neither provider health nor promotion. |

Live Azure completion evidence and capability promotion remain governed by deployment verification
and the authoritative registry, never inferred from phase names in this document.

## 11. Testability

- **Coordinator** - property tests: "verifier re-check runs on every
  write-class tool call", "RBAC floor is enforced before the narrator
  sees the tool schema", "audit entry precedes every tool dispatch",
  "escalation records tier and trigger".
- **Narrator adapter** - contract tests using `httpx.MockTransport` for the strict Azure OpenAI
  translator and resolved deployment binding.
- **Tools** - each tool has a shadow-mode test showing it never mutates
  when its `side_effect_class == read | simulate`; a `write` /
  `approve` test showing the verifier re-check gate.
- **Channels** - CLI REPL golden transcript, Teams Bot Framework activity/JWT, Slack signed HTTP
  Events API, and publisher receipts.
- **RBAC matrix** - table-driven test over every (Role × Tool) cell to
  prove the floor from §3.1-§3.3 is applied.
- **Break-glass** - tests prove `activate_break_glass` refuses `expiry > 4h`, requires Owner
  notification and audit receipts, and does not mutate the session principal. Persistent grants
  and session-end revocation are not shipped contracts.
- **Determinism** - two runs of the same CLI transcript through a fake
  `Narrator` produce byte-identical audit trails (given fixed
  timestamps and idempotency keys).
- **Session recovery** - principal-scoped `ConversationHistoryStore` reloads prior turns by session
  id, while stable request idempotency prevents duplicate appends. Audit/ontology retain hashes and
  references rather than raw transcripts.

## 12. Failure modes

- **Narrator unavailable** - fall through to Chat T0 direct-hit; if the
  turn does not match a T0 pattern, respond with a canned "reasoning
  layer is temporarily unavailable; here is the direct query surface"
  and expose the tools list.
- **Verifier abstain on write-class tool** - substitute
  `enqueue_hil(...)` (see §7.4), return the HIL id, audit reason
  `verifier_abstained`.
- **Channel adapter disconnects** - when durable delivery is configured, the complete response and
  terminal/ambiguous state remain in the ledger. The direct path still resumes durable conversation
  history by session id but does not claim exactly-once provider send.
- **Break-glass request receipt** - the coordinator does not interpret the receipt as elevated
  capability. A future grant integration must recheck TTL before every privileged tool call.
- **Tool implementation raises** - the tool's typed error surface (§3.4)
  is wrapped as a `ToolResult(status=error)`; the narrator sees a
  structured error, not an exception traceback.

## 13. Data + wire contracts

### 13.1 Audit entry - `console.turn` action_kind

```json
{
  "action_kind": "console.turn",
  "session_id": "…",
  "turn_id": "…",
  "principal": {"kind": "user|cli|bot", "id": "…", "role": "Reader|…"},
  "channel": "cli|teams|slack|web",
  "direction": "inbound|outbound|tool_call|tool_result",
  "tier": "T0|T1|T2",
  "escalation_trigger": "…",
  "tool_name": "…",
  "arguments": {…},
  "result_preview": "…",
  "evidence_refs": ["…"],
  "verifier_verdict": "pass|abstain|deny|n/a",
  "model_deployment_id": "…",
  "prompt_tokens": 0,
  "completion_tokens": 0,
  "started_at": "…",
  "finished_at": "…"
}
```

### 13.2 CLI REPL wire contract

- stdin: one operator utterance per line.
- stdout: JSON-Lines when `--json` flag is set; formatted text otherwise.
- stderr: coordinator log lines (structured; separate stream so the
  formatted view stays clean).
- Exit code: `0` on clean session end; `2` on invalid config; `3` on
  unrecoverable channel error.

### 13.3 Read-API approval callback (Week 1)

- `POST /hil/{approval_id}/decision`
- Body: `{"decision": "approve|reject|defer", "justification": "..."}`
- Headers: `X-FDAI-Signature: sha256=<hex>`,
  `X-FDAI-Timestamp: <RFC3339>`.
- Signature material: `HMAC-SHA256(secret, timestamp . approval_id . body)`
  where the three parts are joined by a literal `.` separator. Binding
  the URL path `approval_id` into the digest blocks a captured valid
  message from being replayed against a different pending item (URL
  swap). The bot MUST include the same `approval_id` it puts in the URL.
- Response: `200 {"queued": true, "audit_entry_id": "..."}`.

This is a documented write-route exception to the read API's GET-only
projection surface. The invariant test allow-lists this callback explicitly.
This does **not**
break the "console never executes" rule from
[app-shape.instructions.md](../../../.github/instructions/app-shape.instructions.md):
the endpoint only *records an approval decision* into the existing HIL
queue (a signal), which a separate executor principal later acts on. The
API process never holds the executor Managed Identity and never calls a
mutation surface itself; approval and execution stay distinct principals.
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
      { "correlation_id": "corr-j", "detail": "…why this happened…", "outcome": "…" }
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

The deck opens as a movable, resizable floating panel by default so operators
can inspect the source screen while chatting. Dragging the header title moves
the panel. Its left and top edges keep a 12 px guard, while the right and bottom
edges may move beyond the viewport. Header controls preserve the same
conversation while switching to a right sidebar or to the full workspace. The
sidebar starts at 440 px; its left separator supports pointer and arrow-key
resizing from 340 to 720 px and stores the width for the tab. Right-sidebar
mode reduces the shell body by that same current width, so it does not cover
navigation or page content. Floating and dock modes remain non-modal and do
not trap focus or block page interaction; full workspace retains the modal
focus trap. The selected mode is tab-scoped, and compact mobile viewports use
the full-screen geometry.

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

The first shipped verifier uses no second model call. For read-source provenance, ontology browse,
cross-screen operational, and Azure inventory questions it deterministically renders the terminal
answer from typed evidence. Ontology browse requires both an ontology target and a browse verb,
forwards only allowlisted identity fields with 256-character prompt values, and renders duplicate
or malformed count and selection facts unavailable instead of quoting them. Operational states
remain typed as `matched`, `ambiguous`, `none`, or `unavailable`,
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

### 13.5 Incident roster and remediation history

The read-only SPA exposes a first-class **Now > Incidents** panel. It is the
roster-first entry point for incident response: an operator can find active or
resolved incidents before knowing a correlation id, select one, and inspect
its remediation history. The existing Audit and Trace panels remain the
record-level and end-to-end drill-down surfaces.

The API contract is:

| Route | Purpose |
|-------|---------|
| `GET /incidents?status=active|resolved|all&limit=<n>&cursor=<opaque>` | Return incident summaries newest activity first. |
| `GET /audit?correlation_id=<id>&limit=<n>&cursor=<opaque>` | Return the selected incident's append-only history. |
| `GET /audit/{correlation_id}/trace` | Reconstruct the ordered pipeline trace. |
| `POST /chat/action` | Prepare or confirm an incident creation request on the authenticated write-direction chat path. |

The incident roster stays read-only. Incident creation uses the separate
authenticated chat action route and never adds a mutation button to the panel.
For a recognized incident-open request, the route behaves as follows:

1. It requires Contributor capability, severity, and a target correlation key.
2. It returns `incident_confirmation_required` with a human-readable summary
  and a 10-minute expiry. No incident exists at this point.
3. A `confirm` or `확인` message from the same principal and `session_id`
  creates the audited incident and returns its id and initial `open` state.

The pending proposal is bounded by a 200-character `session_id`. Oversized
session or idempotency keys are rejected rather than truncated, preventing two
distinct identifiers from collapsing to the same confirmation. Production
stores the proposal in Postgres and consumes it atomically, so confirmation can
land on another replica. The persisted record contains a SHA-256 of the source
prompt, not the raw operator text.

Missing values return `incident_details_required`; cancellation returns
`incident_creation_cancelled`. An unrelated action command continues through
the existing Bragi-to-Huginn typed proposal path. An allowlisted agent uses the
same built-in workflow with member-event evidence and a reason, but does not
impersonate an operator or bypass the incident registry.

The same authenticated route accepts only exact lifecycle command grammar;
it does not guess from free-form status prose:

- `transition incident <uuid> to <state>` or
  `incident <uuid> 상태 <state>으로 변경`
- `assign incident <uuid> to <oid>` or
  `incident <uuid> 담당자 <oid> 지정`

Both require a nonblank conversation `session_id`, Contributor capability, and
the registry's persisted expected-state check. Illegal edges, unknown ids, and
cross-replica conflicts return `incident_lifecycle_rejected` without changing
the canonical incident.

`correlation_id` is the investigation key used to join evidence; it does not by
itself prove that an Incident lifecycle record exists. The projection can attach a row without
a top-level correlation only when its `event_id` equals an already-known
correlation, or when an explicit incident lifecycle link resolves to exactly
one correlation. Ambiguous rows stay unattached; the read model never invents
an association from a resource name. For a pending HIL item, the projection
may read its server-owned park record to recover rule severity and category;
it does not rewrite the append-only audit row. Lifecycle state is authoritative
when present. Otherwise the projection derives `open`, `in_progress`, or
`resolved` from audit stages. A denied, abstained, or failed remediation does
not by itself claim that the underlying incident is resolved.
Local read-API audit fixtures carry explicit sample provenance and stay visible
in Audit, Trace, and Agent activity. They are excluded from the operational
Incident roster, so a normal or within-threshold monitoring sample cannot look
like an opened Incident.

Each incident summary includes `involved_agents`, derived server-side from the
recorded `producer_principal`, canonical action owner, and stage ownership. The
Agents surface hydrates this durable incident snapshot first, then applies
newer `/agents/stream` stage deltas. This keeps a newly opened tab consistent
with Incidents while preserving live stage transitions.

The roster returns summaries only. It does not embed every audit row, and the
cursor bounds each server-side page. Selection performs a separate filtered
GET for history. Every route is Reader-gated and returns `405` for mutating
verbs. The panel provides links to Audit and Trace but no execute, approve, or
rollback button; those operations remain in remediation PRs and ChatOps.

Incident creation, each legal state change, and requested roster summaries are
eligible for A2 operational notification. Replayed opens and same-state
transitions do not notify twice. Lifecycle messages contain the incident id,
severity, and normalized state, but omit free-form reason text and resource
correlation keys. A roster notification is bounded to 20 ids and links back to
the complete `/incidents` view. Event-specific `audit_id` values keep channel
idempotency from suppressing later transitions. Durable sent checkpoints and
startup replay retry any notice missed by a crash. Before delivery, replicas
compete for an atomic claim token with a bounded lease; only one sends, and
only that token can mark the notice sent or release it after failure.
Unresolved channels fall back to the HIL escalation sink.

Incident alert subscription follows the channel-as-audience contract in
[channels-and-notifications.md](channels-and-notifications.md): membership in
the configured A2 operations channel determines who continuously receives
open, transition, roster, and SLA-breach notices. The console does not create
per-user direct-message subscriptions. Assignment and external ticket linkage
remain authenticated write-direction chat/tool operations and appear as audit
history; the read-only roster surfaces the linked `ticket_id`.

The roster accepts an optional canonical `vertical` filter, and the audit
route applies `mode`, `tier`, `action`, `outcome`, `vertical`, and bounded
`window=<n>d` filters on the server before cursor pagination. An analytical
deep link therefore searches the complete filtered result set rather than
filtering only the first browser page. The cursor is bound to the incident
status and vertical, so changing either filter invalidates a stale cursor.

Overview audit KPIs aggregate the newest 500 audit rows in both the in-memory
and Postgres read models. `GET /kpi` returns that immutable sample as
`audit_sample` with inclusive `from_seq` and `through_seq` bounds, `row_count`,
and `limit`. Every Overview link to Audit carries those bounds, and `GET
/audit` applies `from_seq` and `through_seq` before dimension filters and
cursor pagination. Operators can therefore enumerate the same append-only
sample that produced the displayed count or ratio even after newer rows
arrive. `hil_pending` remains a separate current queue projection and is not
part of the audit sample. Tier keys and tier filtering use lowercase canonical
values (`t0`, `t1`, `t2`).

The SPA preserves native table semantics for the incident roster. The first
cell contains the selection button, each selected row exposes
`aria-selected`, and the control points to the incident detail region with
`aria-controls`. Unknown top-level URLs are replaced with canonical
`/overview`, so one visible screen cannot create multiple conversation caches
under typo paths.

Explicit child-view and entity identifiers fail closed. When a URL names an
unknown workflow, ObjectType, LinkType, ActionType, agent, audit entry,
architecture view or resource, incident correlation, promotion reason, IAM
tab, or live event, the console preserves the requested value and renders an
unavailable or waiting state with valid recovery links. It never substitutes
the first row, default workflow, default view, or another entity's evidence.
Only a URL with no explicit identifier can select the documented default.
ActionType directory filters are canonical URL state (`q`, `category`,
`trigger`, and `execution`) and remain intact when an operator selects an
action, so refresh, back navigation, and shared links reproduce the same list.
Blast-radius query drafts write `target`, `depth`, and `links` to the URL
without running the simulation; `links=none` preserves an explicitly empty
selection until the operator chooses a valid traversal set.
Opaque entity identifiers also remain byte-for-byte stable across canonical
URL replacement and nested drilldowns. In particular, Process ids are encoded
but never lowercased or slugified, and a workflow step link preserves its
catalog ownership group. Manual RCA and Trace lookups first write the submitted
correlation id to the canonical URL; editing the input invalidates any earlier
response so evidence cannot appear under a different identifier.

Write-direction forms keep one idempotency key for one unchanged operator
intent. A transport failure or lost response therefore retries the same key;
changing the target, parameters, or justification rotates it, and a confirmed
success retires it. Daily briefing subscription creation derives a stable
principal-scoped subscription identity from that key and returns the existing
record for an identical retry. Access requests, IAM role requests, and governed
Python runs use the same rule. Batch document upload locks collection, purpose,
storage mode, consent, and selected files until completion, and stops issuing
new requests after the route unmounts.

Canonical source mutations and derivative ontology projections have separate
success boundaries. A committed workflow definition or binding returns the
source-store result even when its immediate ontology projection fails. The
PostgreSQL source transaction enqueues the corresponding projection recovery
record, so a retry never misreports a committed create as a conflict or a
committed delete as not found.

Agent runtime state also requires observed evidence. Before an agent state
frame or durable incident projection attributes work to an agent, Agents,
Agent Activity, and Pantheon render that agent as `unobserved`, not `idle` or
ready. The fixed runtime-binding map reports declared subscriber bindings only;
it doesn't prove that a consumer process is healthy. Deployment schedule
status stays unavailable until a scheduler projection supplies it.

The Capabilities route is an inert catalog projection with `source=static-catalog` and
`execution_eligibility=false`; entries describe side-effect classes, roles, and default modes.
Catalog presence doesn't prove provider binding, runtime health, or execution permission. The
Skills route projects installed skill and governed bundle metadata, ordered members, compatibility,
eligibility, references, and bounded diagnostics from `GET /skills`, with no lifecycle or mutation control.
Bragi uses the same Reader-gated disclosure; content reads recheck trust and budgets, while execution decisions stay with composition, RBAC, verification, and the risk gate.
Approved source evidence is available through GET routes under `/api/v1/skill-sources`, but the
current SPA Skills route reads `/skills` and does not yet consume those routes. A future read-only
source view can browse, search, inspect quarantine, and check disabled update candidates. Candidate
approval and source revocation remain separate authenticated POST routes for Approver and Owner
automation. The Skills panel provides no lifecycle control. See
[skill-source-management.md](skill-source-management.md).

Operational read surfaces render provenance from their payload instead of
static claims. Scheduler Runs shows its ledger `source` and `durable` flag; LLM
Cost shows `latest_occurred_at`; Settings Models shows the generated snapshot
filename and `as_of`. Missing fields render unavailable or fail contract
decoding. The browser doesn't infer durability, freshness, or provider health
from a route name, environment mode, or configured default. A source with
`availability=unavailable` never reports `reachable=true`; unconfigured or unprobed
providers use `reachable=null`. A read-API panel remains `unknown` when any of its owned routes is
missing from the manifest, including when every route is missing. Only explicitly source-independent
panels omit the source status.

Exact entity lookups filter on the server before page limits. Incident
correlation links, Audit entry links, and Approval searches therefore resolve
beyond the first roster page instead of reporting a false absence. Approval
search remains unavailable to count-only roles so filtered totals cannot leak
hidden queue content. Independent sources are isolated: an optional principal
workflow projection cannot hide the built-in workflow catalog, and an unused
analytics source cannot replace another hub with an error screen. Report render
and PDF failures stay local to the selected operation and do not remove the
catalog or variable editor; late downloads are discarded after route changes.

Diagnostics distinguishes process liveness from an authenticated KPI read
path. A successful `/healthz` response never claims that operational data is
healthy. Likewise, last-observed agent frames remain visible as history, but
Engaged, Watching, and Idle are current counts only while the agent stream is
open. Canvas visualizations provide an equivalent keyboard and screen-reader
resource selector, and composite tab widgets move DOM focus together with
roving selection.

During bootstrap, the SPA verifies the signed-in principal through authenticated
`GET /iam/self` before opening console data. A transport failure keeps data closed and renders the
full-screen sign-in recovery surface with access-check retry and sign-in actions. It does not start
an automatic sign-in redirect because an unreachable read API would create a redirect loop.

The Architecture route leads with inventory provenance and factual counts for resources, dependencies, containment boundaries, and resources whose status is unavailable. Its default isometric map makes containment and resource shape visible; top and front views remain optional display settings. Simple inventory projections reflow three or more resource groups into at most two columns, widen each boundary, and render direct resources at up to 1.25 times their base size. Authored layouts with nested boundaries keep their supplied geometry. Selecting a resource updates the canonical deep link without reloading the inventory graph, highlights its direct neighborhood, and exposes directional relationships before technical identifiers.
Map labels avoid node and label collisions, fit long names within the canvas, and grow from 13px up to 20px as the operator zooms, including the first zoom step. The selected label can grow to 22px. Zoom-in and zoom-out steps are reciprocal, and the canvas palette follows the active console theme. The route uses the main page scroll rather than a nested inspector scroll and provides a keyboard-accessible resource and relationship index equivalent to the filtered canvas content.
A truncated snapshot carries an explicit partial-inventory notice. Pointer interaction uses a minimum 44px node target and lets operators select containment boundaries as well as resource nodes.
Architecture renders a subscription-scoped cached snapshot immediately when one exists. It labels an
expired or change-invalidated snapshot as stale, shows the refresh-in-progress state, and polls only
until the read API atomically promotes the completed background refresh. Cache state never upgrades
the server-owned freshness verdict. Polling retries transient failures with a bounded 2-to-30-second
backoff while keeping the stale graph usable.

Time-bound and aggregate evidence remains conservative while a route stays
open. Approval and Operator Memory rows cross their recorded TTL boundary
without requiring a reload; Architecture continuously advances snapshot age
while retaining the server's snapshot freshness verdict. A missing tier
measurement is unavailable, not measured zero. Scope eligibility counts only
`included` entries. A multi-datasource report has a known aggregate evidence
time only when every source supplies one, and then uses the oldest source time.
Mixed-currency LLM cost groups are labelled non-additive and never displayed as
a single-currency total.

The Process list follows the same rule with `source`, nullable `synthetic`, and
nullable `durable`. The local seeded runtime reports
`synthetic-dev/true/false`; production reports `postgres/false/true`. Process
status, journals, and dynamic views remain server-owned, but a current render
doesn't erase how the underlying snapshot was produced or stored.

The selected incident detail keeps the summary and evidence layers separate.
It shows the server-owned incident id, ticket id, lifecycle status and source,
disposition, verdict, owning vertical, latest mode, timestamps, and history
count before the remediation timeline. Missing values render unavailable; the
browser does not infer impact, ownership, or recovery. The detail links to the
correlation-scoped **Incident RCA Dossier** in History > Reports.

Overview keeps every required analytical section visible when autonomy
measurement is absent or malformed. It renders an explicit unavailable state
instead of removing the section or inferring zero. When evidence is present,
the success surface includes cost per resolved event, mixed-model
disagreement, verifier failure, shadow divergence, the measurement window,
sample size, confidence, and the named source. **History > Reports** renders
the declarative reporting catalog and its server-owned widget evidence.
Synthetic measurement can illustrate the analytical shape, but it cannot
decide operational health, increase the attention count, or create failed-guard
drilldowns. Overview and Control Assurance treat synthetic guards as unknown
for operational posture while continuing to label their source, window, sample
size, confidence, and source timestamp. A zero-event vertical renders its
resolution rate as unavailable instead of inferring 0%. Overview loads the
required audit KPI and independent optional cost, promotion, and autonomy
projections concurrently; only the documented unavailable statuses degrade an
optional projection. Analytical tab and comparison links preserve the current
query. Failed guards and T2 leading indicators add canonical `guard` and
`indicator` filters, and an unknown filter value renders unavailable instead of
selecting another row.

Contract rules (enforced by `console/src/routes/view-contract.test.ts`):

- **Every publishing route MUST declare `purpose` and `glossary`**, composed
  from the shared catalog `console/src/deck/glossary.ts` so a term means the
  same thing on every screen. A route that publishes a snapshot without them
  fails the build - an under-described screen can never land silently.
- **Causal fields stay in `records`.** `detail`, `summary`, `reason`, `tier`,
  and `outcome` are NOT projected away, so "why did this start" is answered by
  quoting the recorded audit narrative (and the ordered hand-off chain) instead
  of shrugging.
- The narrator resolves questions with a **screen-agnostic** chain (causal ->
  glossary / value-chip -> route enhancer -> generic record search); a new
  screen becomes explainable by declaring its vocabulary, not by adding code.
  The offline deterministic answerer (`console/src/deck/answerer.ts`) and the
  server narrator (`chat.py`) both ground term and cause answers in the same
  `purpose`/`glossary`.
- The CLI REPL and live cockpit send the same self-describing snapshot to the
  server narrator through `POST /chat`. The CLI contains no model client,
  intent router, cloud credential flow, or console-tool implementation.

#### 13.5.1 RCA view (root-cause analysis)

The read-only SPA exposes a first-class **History > RCA** panel. Given an
incident `correlation_id` (typically deep-linked from the Incidents roster,
`#/rca?correlation=<id>`), it renders the tiered, grounded root-cause
hypotheses the control loop already appends to the audit ledger, plus the
linked response plan. It is the "why did this happen, and what was the plan"
surface that pairs with the Incidents roster (13.5).

The API contract is one GET route:

| Route | Purpose |
|-------|---------|
| `GET /rca?correlation=<id>` | Return the per-incident RCA view for one correlation id. |

The route returns `404` when the correlation has no audit rows. It never turns
an unknown correlation into a normal empty RCA dossier, because that would
present missing evidence as a completed analysis.

The projection composes existing audit data; it introduces no new source of
truth. The control loop writes each hypothesis as a shadow `rca.hypothesis`
audit entry (see
[observability-and-detection.md](../rules-and-detection/observability-and-detection.md)
section 4). The panel reads the correlated audit rows and projects:

- **Root-cause hypotheses**, newest first, each with its `RcaTier`
  (`t0` direct / `t1` correlation / `t2` reasoning), confidence, cause text,
  reason, shadow-vs-enforce mode, and grounded `citations`
  (`rule` / `event` / `telemetry` / `incident` / `change` / `scenario` /
  `knowledge`).
- **Grounding state.** An ungrounded / abstained hypothesis
  (`outcome == "abstained"`, `grounded == false`) is surfaced explicitly as
  "insufficient grounding -> HIL", never as a confident cause.
- **Response plan** composed from the same correlated audit stream: the
  verdict (`auto` / `hil` / `deny` / `abstain`), the delivered action kind,
  its mode, and the rollback reference.
- **Structured T1 causal chain.** A T1 hypothesis can carry
  `causal_chain` with root/failure event ids, ambiguity, and ordered hops.
  Each hop preserves cause/effect event and resource refs, lead seconds,
  relationship, and confidence. Malformed or absent chain data renders
  unavailable instead of being partially reconstructed in the browser.

The reporting catalog includes `incident-rca-dossier`. Its required
`correlation_id` variable scopes hypothesis, citation, causal-hop, response,
and chronology widgets to one incident. When the optional `pdf-report` extra
is installed, Reports exposes an authenticated GET-only **Download PDF**
control. The PDF uses an FDAI-owned A4 layout with cover, at-a-glance page,
table of contents, section pages, running headers/footers, and a source
SHA-256. The RCA-specific renderer uses a solid Calm Slate steel-blue cover, an executive
summary, evidence completeness, measured impact, chronology, causal and
alternative hypotheses, response/recovery, control gaps, corrective/preventive
actions, limitations, and an audit appendix. Cards use uniform neutral
hairlines rather than colored top or left rails. It renders the server-owned
report envelope and performs no new RCA; an unrecorded section is explicitly
unavailable. Print-native chronology tables and SVG causal diagrams avoid the
browser Grid/Flex pagination defects, while content-driven chapter groups keep
the reference report to nine pages.

An RCA hypothesis answers "why", never "execute": execution eligibility stays
with the risk gate + verifier. The route is Reader-gated, returns `405` for
mutating verbs, and provides links into Audit and Trace but no execute /
approve / rollback button. The projection is a pure function
(`src/fdai/delivery/read_api/routes/rca_projection.py`) covered by
`tests/delivery/read_api/test_rca.py`.

### 13.6 Action submit - `POST /chat/action` (propose, never execute)

The read-only deck answers questions; this is the ONE write-direction path -
submitting an action the operator asked for (`restart vm-1`) into the typed
pantheon pipeline. It does **not** break the "console never executes" invariant:
the route publishes an `ActionProposal` *signal* onto the raw event topic (the
same topic the pantheon's Huginn ingests) and holds no executor identity - the
same precedent as the HIL approval callback (13.3). Forseti judges the proposal,
Var approves a high-risk one, and only Thor executes (shadow-first).

- **Endpoint**: `POST /chat/action`, body `{"prompt": str, "session_id": str?,
  "idempotency_key": str?}`. Registered only when `ReadApiConfig.console_action`
  wires a `ConsoleActionSubmitter`
  (`src/fdai/delivery/read_api/console_action.py`); absent, the console has no
  action-submit surface. Operator-supplied values are bounded (prompt <= 4000,
  question <= 2000, resource id / session id / idempotency key <= 200 chars) so
  one large value cannot bloat the pipeline or audit. The client `idempotency_key`
  becomes the proposal's dedup key (namespaced by the initiator, so one operator
  cannot reuse another's key to suppress their action), so a retried or
  duplicated submit collapses at Huginn instead of enqueuing a second action;
  Thor is additionally idempotent per correlation so an at-least-once
  re-delivery never double-executes.
- **Server-derived RBAC**. The operator's role comes from the validated bearer
  token (`Principal.roles`), never client JSON. Submitting requires the
  `author-draft-pr` capability (Contributor and above); a Reader is refused with
  `403 {"submitted": false, "reason": "rbac_capability"}` before anything
  publishes. Forseti re-checks the initiator principal downstream (deny +
  `SecurityEvent`) - defense in depth.
- **Both entry gates agree on the capability, not a role rank**. The
  conversational entry gate (`Bragi.submit_action_proposal`) maps the session's
  Entra role to the SAME canonical capability matrix (`fdai.core.rbac.roles`)
  and also requires `author-draft-pr`, so the HTTP and conversational surfaces
  never diverge. In particular `BreakGlass` is hard-isolated (not a superset of
  Owner) and does not carry `author-draft-pr`, so it cannot submit a normal
  action from either surface.
- **Refusals are observable**. Every pre-pipeline refusal (`invalid_principal` /
  `rbac_capability` / `deny_override_forbidden`) is logged and offered to an
  optional injected `RefusalObserver` (`ConsoleActionSubmitter.refusal_observer`)
  so repeated refusals for one actor - a privilege-probing signal Forseti never
  sees because the request never enters the pipeline - become detectable (audit
  / metric / security event). Absent the seam, only a structured log line is
  emitted.
- **Translation**. `fdai.agents.bragi.translate_action_intent` first matches an
  exact ActionType id or one unambiguous full suffix from the loaded ActionType
  catalog (for example, `flush cache` -> `ops.flush-cache`), then uses the
  conservative built-in verb fallback. Ambiguous and unmapped commands return
  `200 {"submitted": false, "reason": "unmapped_action_intent"}` instead of
  guessing. The function remains the single source of truth shared with the
  pantheon-internal path.
- **Deny-override block (Scenario B)**. When a `prior_outcome_lookup` seam is
  wired, the submitter checks the pipeline's last terminal conclusion for this
  exact `(initiator, resource, action_type)` before publishing. A prior **deny**
  (judged unsafe) is authoritative: a repeat console ask cannot lift it, so the
  submitter refuses with `403 {"submitted": false,
  "reason": "deny_override_forbidden"}` and publishes nothing - only a governed
  rule / policy / override change can lift a deny, never a repeat request. A
  prior **no-op** (the action was unnecessary because the target was already
  satisfied) does **not** block a re-request: conditions drift, so the request
  re-enters the pipeline and is judged fresh. The rule lives in one pure
  function (`fdai.core.console_request.evaluate_operator_rerequest`). Absent the
  seam, every request is treated as fresh (no deny-override check).
- **Response** (submitted): `200 {"submitted": true, "correlation_id": ...,
  "action_type": ..., "resource_id": ...}`. The operator tracks progress by the
  `correlation_id` (Trace panel / audit); the pipeline result (auto shadow-exec,
  HIL wait, or deny) is asynchronous.
- **Investigation Incident**. An explicit `tool.run-investigation <kind> <resource>` command is
  itself confirmation to open or reuse a deterministic Incident for the session, target, and
  resource kind. The proposal uses the Incident ID as its correlation and carries `incident_id`
  in typed parameters. Ordinary questions and discovery work create no Incident.
- **Live stage turn**. After a successful submit, the web deck opens an authenticated,
  correlation-filtered `/live/stream` reader and updates one transcript turn through Huginn
  ingest, Forseti route/verify/gate, Thor execute, and Saga audit. Audit is terminal; timeout or
  stream failure leaves the durable Trace correlation as the recovery source.
- **This is the second documented write route** alongside the 13.3 approval
  callback; both record a signal and never hold the executor Managed Identity.

### 13.7 Python VM task workbench

The Workflow Builder includes a multi-file Python task workbench backed by the
six `/python-tasks/*` routes in
[`python_tasks.py`](../../../src/fdai/delivery/read_api/routes/python_tasks.py).
Operators can edit source files, choose an entrypoint, declare modules and host
capabilities, validate, stage an immutable artifact, and render a shadow plan
for an inventory Resource.

The workbench preserves the console identity boundary:

- **Validate** is pure AST and manifest validation.
- **Generate editable draft** calls the injected `PythonTaskAuthor` with the
  operator intent, target capabilities, and allowlisted modules. The draft must
  still validate and stage before any request control is enabled.
- **Stage artifact** writes the content-addressed artifact store, not a VM.
- **Test shadow plan** uses `PlanningVmTaskRunner`; the read API has no Managed
  Identity capable of creating a Run Command.
- **Request governed run** publishes a typed `ActionProposal`. It doesn't call
  `VmTaskRunner`, copy a file, or execute Python from the console process.
- **Create schedule** stores a strict cron binding for the selected catalog
  Workflow, artifact, and inventory target. A later scheduler tick publishes
  the typed event.

The read-API keeps background, busy-input, and skill runtime composition helpers under `routes/`; the result panel shows validation issues, artifact reference, planned file and
byte counts, target capabilities, or the submitted correlation id. Runtime
status continues on the Processes and audit surfaces after the control loop
accepts the proposal.

### 13.8 Grounded code in chat replies

When a terminal Command Deck answer contains a fenced code block, the read API
extracts it as a bounded `GroundedCodeArtifact`. The artifact carries the code,
language, SHA-256 reference, and a static validation result. Python blocks are
parsed and compiled without importing or executing them. Other languages are
marked `not_checked` rather than presented as validated.

The console keeps code collapsed under **Code evidence** by default. Expanding
the disclosure shows the exact grounded content, its artifact reference, and
whether syntax validation passed. The terminal artifact is derived from the
final verified answer, not from an incomplete streaming token sequence. A tab
may retain the artifact in `sessionStorage` with the transcript; defensive
parsing drops malformed or oversized persisted entries.

This display contract does not grant execution authority:

- **No runtime writes**: the chat route never writes generated code into the
  FDAI source tree, installed package, container filesystem, or active Git
  checkout.
- **No chat execution**: static parsing is the only operation performed in the
  read API. It does not import the generated module, start a subprocess, create
  a virtual environment, or call `VmTaskRunner`.
- **Governed execution stays separate**: an operator who wants to run code must
  create and stage a `PythonTask`, then publish a typed `ActionProposal` through
  the flow in section 13.7. The risk gate, approval ceiling, executor identity,
  and audit path remain authoritative.
- **Temporary storage is not the sandbox**: a runner may use a per-run directory
  such as `/tmp/fdai-code/<run-id>` for writable files, but isolation comes from
  a separate principal, a read-only runtime filesystem, path and symlink checks,
  resource limits, network policy, and cleanup. A path convention alone is not
  a security boundary.

### 13.9 Ontology registry projection

`GET /ontology/graph` is the read-only registry projection for the web
console's three ontology views:

- **Objects**: ObjectTypes and LinkType edges render as one selected,
  deterministic one-hop neighborhood. The inspector shows recorded properties
  plus incoming and outgoing relationships.
- **Links**: selecting a LinkType shows every recorded `from_type -> to_type`
  endpoint pair, cardinality, and the causal, transitive, and temporal flags.
  The console doesn't infer relationship semantics absent from the catalog.
- **Actions**: the response includes the loaded ActionType catalog as complete
  safety-contract records. The catalog view exposes category, trigger,
  execution path, rollback contract, default mode, preconditions, stop
  conditions, blast-radius declaration, tier ceilings, and promotion gate.

The ActionType projection is additive: `action_type_count` and `action_types`
may be zero or absent on an older deployment, while ObjectType and LinkType
exploration continues to work. ActionTypes stay out of the ObjectType graph so
a large action catalog doesn't obscure resource relationships. All three views
are GET-only and issue no action or approval call.

## 14. MCP delivery and managed catalog

FDAI can consume externally hosted MCP tools through the managed outbound catalog under
`src/fdai/delivery/mcp/`. Servers install disabled. Enable performs a non-invoking `tools/list`
discovery and verifies every ActionType-to-tool allowlist entry. Catalog mutations use a durable
revision-CAS snapshot; manifest, health, revision, and the admin audit record commit in one
PostgreSQL transaction. A periodic monitor records health transitions, and only enabled, healthy
servers are routable. Endpoint validation rejects credentials, query strings, fragments, and
non-loopback plaintext HTTP.

This outbound catalog is distinct from publishing FDAI itself as an MCP server. The repository
currently ships no inbound MCP server process, `list_tools`/`call_tool` wire endpoint, or external
MCP principal mapping. A fork MUST NOT infer an FDAI-to-client MCP surface from this document.

A future inbound MCP proposal can additively reuse the coordinator and RBAC, reject anonymous
callers, map mTLS or audience-scoped Entra identities to service `Principal` records, and audit the
resolved role. That remains future scope requiring its own threat model, protocol tests, and
deployment gates.

## 15. Decision status

- **OD-C1 resolved** - the strict core narrator prompt lives in `AzureOpenAINarratorModel`; the
  broader prompt catalog uses `rule-catalog/prompts/base`, `packs`, `scenarios`, and `tools`.
- **OD-C2 resolved** - principal-scoped user memory/preferences and separate governed operator
  memory now have schemas, provenance, consent, and retention paths.
- **OD-C3 residual** - persistent BreakGlass grant/elevation is not implemented. A future design
  must retain no-self-approval and separately approve any distinct-approver requirement.
- **OD-C4 current behavior** - CLI history is bounded process-memory navigation only. A persistent
  history file and retention/redaction contract are neither shipped nor blockers for the current CLI.

## 16. Related docs

- [architecture.instructions.md](../../../.github/instructions/architecture.instructions.md) -
  trust routing, verifier authority.
- [action-ontology.md](../decisioning/action-ontology.md) - ActionType schema with the
  `trigger_kind` axis (`operator_request`) that the console emits, plus
  the `argument_schema` the coordinator validates against.
- [execution-model.md](../decisioning/execution-model.md) - the unified RiskGate the
  chat verifier re-check (§7.2) invokes, and the 5-axis authority
  matrix that decides auto / HIL / deny for every write-class tool call.
- [channels-and-notifications.md](channels-and-notifications.md) - the
  push-direction channel matrix this doc's pull side extends.
- [user-rbac-and-identity.md](user-rbac-and-identity.md) - the RBAC role
  set the tool matrix (§3) references.
- [security-and-identity.md](../architecture/security-and-identity.md) - no-self-approval,
  execution identity, safety invariants.
- [prompt-composition.md](../decisioning/prompt-composition.md) - narrator prompt
  layering, tool-schema exposure, debate orchestrator (Wave 4.5) that
  Month 1 may consume.
- [rule-governance.md](../rules-and-detection/rule-governance.md) - the discovery loop the
  Month-1 console feeds.
- [project-structure.md § console/](../architecture/project-structure.md#console-static-web-app) -
  the read-only console SPA the Month-1 web-chat channel extends.
