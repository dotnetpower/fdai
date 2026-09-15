---
title: Console Evidence and Resilience
---
# Console Evidence and Resilience
This document owns the operator console contracts for evidence provenance, localization, stream recovery, durable replay, and Architecture-map resilience. The conversational tool and RBAC contract remains in [operator-console.md](operator-console.md). The Knowledge overview exposes [cloud-reference lifecycle](cloud-resource-knowledge-lifecycle.md) dates, weakest source freshness, exact-byte package review, and confirmed rollback requests. Import and pending index verification never appear as searchable activation; source URLs remain inert and expired policy disables writes without hiding history. Its case-insensitive JSON filename check validates file format only, never conversational intent.
## Navigation context
Selecting an Activity Bar domain opens its Explorer and navigates to the first visible panel under the operator's local order and visibility preferences. This navigation remains active when the Command Deck is closed or floating; a full-workspace Deck closes before the route changes. Browser evidence that opens the current-screen Deck begins from an ordinary panel such as Overview. Settings owns a modal overlay and is not a valid hidden launcher context.
The Activity Bar conversation control opens or resumes general chat without changing the route or Explorer. Its pressed state tracks general chat only. The bottom launcher and `Ctrl+K` or `/` select a separate current-screen conversation. General chat defaults to the workspace; screen chat defaults to the right dock. The rail tooltip opens to the right and the bottom tooltip above, on hover or keyboard focus, and each names its context and actual open/close action. The [conversation lifecycle](operator-console-progressive-conversations.md#command-deck-workspace-lifecycle) owns draft preservation and explicit screen attachments.
Selecting a cached screen conversation from another screen is the bounded exception: the console navigates to its origin while suppressing only the synchronous conversation-owned route event, then activates its transcript. The Deck remains open without a transient default-session switch or close/reopen focus cycle. General, same-screen, and agent conversations switch without navigation.
Reselecting the already active same-screen conversation is focus-only; it does not reload the sessionStorage transcript over newer in-memory turns.
Selecting an inactive conversation records only a browser-local read acknowledgement and does not change its activity timestamp, so the history order remains stable. Principal-scoped `Mine`, `Unread`, and `Favorites` filters use only browser-local navigation metadata; toggling a favorite doesn't change server activity, evidence, or ordering. A conversation title is bold only while its observed activity is newer than its persisted read timestamp; selecting it clears that cue without moving the row. Only newer server activity advances the ordering timestamp.
For a non-agent conversation, the first operator question becomes the title while the originating screen remains separate metadata. The normalized question is bounded to 512 characters in history metadata and preserved across browser and durable restoration. When the title is visually truncated, its visible text keeps the ellipsis. Pointer hover anywhere on the selectable conversation row, including its time, or keyboard focus shows the bounded full question through the shared console tooltip, including titles that fit.
Layout and close icon controls use the same localized tooltip component. The connected-backend tooltip preserves separate mode, endpoint, route-choice, and candidate lines, fills every localized placeholder, and wraps long endpoint or deployment tokens within its viewport bound. Status pills carry their complete visible label and don't use a `title` prop. Non-heading details that need hover or keyboard disclosure use the shared tooltip instead.
An agent-card Ask action always opens a new empty agent conversation with a unique user-scoped key. The new summary carries the selected agent immediately, so the first submit sends the same agent target to the Operator API. Existing agent conversations are preserved as separate history entries and are restored only when the operator selects one explicitly.
Removing the active cached conversation selects only a current-route default (including the legacy `screen` key) or current-route thread. If neither exists, the console creates a new current-route default instead of activating an unrelated-route or agent transcript. Context-dependent cancellation, runbook, knowledge, memory, learning, ordinal-resource, ambiguity, reformatting, and partial-source questions require a verified prior conversation record. The server reconstructs the active investigation, selected resource, prior answer, or source-failure receipt from the latest usable assistant replay in the principal-scoped `ConversationHistoryStore`. The browser transcript cannot mint this authority, and a fresh conversation stays unavailable. After a verified or corrected prior turn, `KnowledgeContextChatTools` can load one unique trusted runbook, report enabled source authorization and refresh state, or show explicit-consent memory visible only to that principal. It reports learning as reusable only when the exact assistant-turn review points to a materialized memory or runtime-skill proposal. Drafts and ambiguous runbooks stay empty, provider failures stay unavailable, and ordinary chat never writes memory or review state. Every completed continuation cites the durable assistant turn and content-addressed source receipts.
Verified fresh inventory answers can include a bounded `resource_result_context` in server-owned replay metadata. It carries no raw resource ID, is never accepted from browser context, and preserves source, snapshot, scope, query digest, freshness, truncation, and up to 40 ordered selectors for later deterministic follow-ups.
Ordinal follow-ups revalidate the selected position through exact fresh inventory predicates. Ambiguity follow-ups show only equal-name candidates from a complete prior result set. Incomplete context stays unavailable and cannot fall back to current-screen or narrator output.
Verified source-manifest answers also preserve bounded unavailable or unknown entries as `source_failure_context`. Partial-source continuations render available facts and exact gaps from that receipt, including reason and last observation when present, without treating an arbitrary unverified answer as source authority. Verified or corrected `query_llm_usage` answers preserve a bounded `analysis_context` with the domain, capability, token measure, grouping, `usage_scope`, and numeric 1-90 day lookback. A refinement that changes only the period, grouping, table, or chart reuses that server-owned anchor and re-reads metering evidence. Comparison, export, missing-anchor, client-supplied-anchor, and explicit different-metric requests return a context-required hold instead of selecting inventory, Resource Health, or narrator output. Current Ontology Instances responses require explicit `runtime_call_graph` and `postgres_role_evidence` source states; the browser rejects either omission instead of converting it to availability, an empty source, or a measured zero.
Full-workspace Command Deck sessions start with the transcript as the only open content column. An empty transcript keeps situational suggestions and adds localized Resilience, Change Safety, and Cost Governance quick starts without changing tool selection or authority. The transcript toolbar exposes filtered conversation history in workspace, docked, and floating layouts; the narrower layouts open it over the transcript instead of reducing transcript width. In workspace, a pointer or keyboard separator resizes conversation history from 180 to 360 px and stores the last width locally. Narrow layouts hide the separator. The history header keeps search and icon-only creation in one compact row, uses lightweight filter tabs, and leaves scrolling to the list rather than the controls. The current-screen digest remains a workspace control. The Deck reads the composition-owned data-source manifest once per open surface and shows compact Inventory, Incidents, Audit, Knowledge, and Automation readiness links above the transcript. Missing or non-authoritative sources remain `unknown`; the browser doesn't infer health, expose raw provider details, or replace the manifest with route presence. Loading uses a stable skeleton, and manifest failure links to Diagnostics without blocking conversation history.
History preserves stable cursor order but renders only 20 summaries initially. Nearing the history scroll boundary reveals the next 20 already loaded summaries. After the local window is exhausted, the same boundary requests the next server page of 20 and reveals it without replacing prior rows. The count shows `20+` while another page exists. Turn bodies hydrate only on selection. An operator image is visible in its sent turn. Browser cache serialization drops inline bytes and keeps a bounded descriptor; durable restoration fetches the binary through the authenticated principal-and-conversation-scoped image route. A transcript restored from browser or durable history shows a resumed-session marker until the operator starts a new conversation. The Deck header owns the route and optional agent context; it never repeats a non-agent conversation question. Digest owns record count, snapshot age, and stale refresh; the composer keeps attachments, question entry, and send or stop.
Command Deck renders transport tokens only in the explicit draft state and renders each receipt-bound revision or confirmed segment as soon as it arrives. A later malformed, interrupted, sequence-gap, or missing-terminal stream retracts the draft and renders an unavailable outcome instead of a success-shaped partial answer. The final server-owned conversation binding updates both the durable index and the active in-memory metadata before the next turn. Verified answers also preserve the semantic receipt's evidence posture: stale, incomplete, conflicting, and unavailable evidence render as attention states even when claim checks passed. Empty citation sets use the neutral grounded-source label, and malformed conversation preflight output uses the planner-recovery guidance.
The shared page title renders the domain and panel labels when they differ, including `Overview / Dashboard`. A domain root whose panel title repeats the domain label and a standalone utility keep a single title.
The shared top bar renders the icon-only FDAI mark in its original source colors beside the `FDAI Console` wordmark. Console themes don't desaturate or recolor the brand asset.
On Overview analysis and every Operations child route, `Sample | Live` appears before incident attention. `Live` is the initial default; `Sample` writes `data=sample`, persists for the tab, replaces the complete projection with a deterministic generic fixture, and shows a page-width non-operational-evidence banner.
A GET-only Sample client serves ordinary projections without authentication or network access. Sample Live seeds 180 deterministic terminal control loops across its 60-second window, then starts one unique loop per second and reveals its ingest, routing, verification, gate, execution when applicable, and audit stages at 800 ms intervals. The latest 30 cards keep fixed positions while their state, progress, owner, and brief top-edge update signal change; authoritative Live retains its 12-item bound. Live, Provision, and Scheduled Continuations use bounded local fixtures; Sample removes Incident intervention, rejects every POST, never activates from API failure, and never mixes with live values. Unsupported routes hide the control and remain Live.
Live follows the same shared title contract as `Operations / Live`. Its observation controls stay in the shared header actions area and wrap below the title on narrow viewports, so Freeze, source, window, and connection status remain visible. An open SSE response proves transport connectivity only. Live reports the source as ready after a fresh validated Huginn runtime heartbeat or an authoritative runtime or replay stage frame is observed. The runtime-source marker expires after 15 seconds without a new observation and never creates a control-loop tile. A keepalive-only connection renders `Awaiting source`, keeps operational metrics unavailable, and points the operator to Core Runtime and stage-topic readiness instead of presenting zero as measured health. The Operator API retains at most 256 accepted stage frames for 60 seconds and replays them in observed order when a new Live subscriber connects. This process-local recovery fills only the current Live window, resets when the Operator API restarts, and never replaces History. Flow is the default view with a bounded 12-item work pool.
Flow and Queue preserve the same title, target, scope, reason, tier, mode, owner, and stage facts; Queue adds only observed risk, impact, SLA, and control-state fields. Flow renders only populated work, packs six items per desktop row, and sorts by attention priority and then newest observation. Terminal outcomes remain available in History instead of occupying the Live work surface. Tier, autonomy, and mode badges use shared pointer and keyboard tooltips. A missing autonomy, risk, impact, or SLA remains `Not observed` and is never inferred in the browser.
The Agents workspace uses three compact views: `Fleet`, `Org`, and `Activity`. Fleet combines live
runtime state with the fixed registry ownership and safety flags inside per-agent Details
disclosures. Org renders the keyboard-accessible reporting chart and selected incident evidence.
The stable `/pantheon` path remains a compatibility route for Org, and Agent oversight remains the Governance panel at `/agent-oversight`.
The previous `/handover` path remains a compatibility alias. [Human-Agent Assignment and Knowledge Transfer](human-agent-assignment-and-knowledge-handover.md#current-owners-read-model-and-console) owns the joined Current owners contract.
Clean route navigation resets both the window and the shell-owned primary content scroller, so a long
Current owners or work-handover page never opens the next route at a stale vertical position.
Its five views are Overview, Human dependencies, Knowledge handover, Approval routes, and Mapping
reviews. Overview and Human dependencies use the strict `GET /stewardship` projection. Mapping
reviews reuses the owner-gated `GET /iam/assignments` projection and derives its capability and
principal only from `GET /iam`. Knowledge handover uses the governed draft boundary. Approval
routes remains explicitly unavailable until its own authoritative projection is connected; the
browser does not infer a route from ownership data. A missing stewardship source blocks only
Overview and Human dependencies; it does not hide the independent Knowledge handover, Approval
routes, or Mapping reviews views.
Overview renders identity-source freshness only from `identity_health`. The Operator API supplies
`checked_at` only from an unexpired last-success heartbeat whose revision matches the stale-finding
snapshot. A completed `clean` or `warn` check requires that timestamp and a finding count that
matches merged `stale_oid` coverage. Any mismatch is a contract error rather than a healthy or
current state.
Each agent's `bus_factor` counts distinct accountable `(kind, id)` subject units, matching the
coverage evaluator. The browser recomputes that count from the steward projection and rejects a
different headline value instead of overstating backup coverage.
Settings includes a Runtime policies route backed by the authoritative StateStore. The route shows
sanitized environment, override, and effective values without exposing secrets, endpoints, tenant
identifiers, or workload identity identifiers. Reader access is observational. Owner updates use a
revision check and an atomic state-plus-audit write. The browser labels startup-bound values as
restart required and never presents a saved value as an action promotion or cloud-resource change.
Integrations and Diagnostics consume the same projection. They expose only configured, ready,
incomplete, mode, and boolean runtime status. They never render endpoint, secret, tenant, resource,
repository credential, recipient, or managed identity values.
Integrations also renders the incident-open email through a sandboxed iframe. The authenticated
preview endpoint calls the same production renderer used by Azure Communication Services Email and
supplies only synthetic placeholders. The preview exposes no runtime incident, endpoint, recipient,
or identity value and provides no send, approval, or execution control.
Operations exposes `Detection coverage` at `/detection-coverage` and keeps `/detection-readiness` as a compatibility alias. The route separates the newest attempt, latest successful run, retained findings, and optional exact-resource Kubernetes evidence. Filters and selection are URL-backed, canonical reasons remain in technical detail, and the browser never probes resources or derives health, readiness, coverage, or authority from a successful response.
With a server-pinned drift context, the GET-only Configuration baselines route fresh-reads identity, lifecycle, drift, Knowledge citation, topology, latency, scheduled-review, and four safety counters.
It reports absent binding or campaign as unavailable or `not-configured`, never invents progress, strictly rejects malformed data, and compares immutable in-scope versions with failed-attempt counts. The SPA exposes no activation, resume, schedule creation, approval, mitigation, or resource mutation; evidence-run, resume, blueprint review, and materialization use separate authenticated routes.
Production exposes the panel only after its mounted JSON/DOCX pair, read-only Managed Identity, and exact resource-group allowlist validate at startup. The Operator API never receives executor identity.

The Processes detail route conditionally renders a Planning Room from the same authoritative
Process journal. Its strict decoder rejects contradictory phase counts, duplicate candidates,
invalid selections, and non-finite effect ranges. Ordinary Processes keep the existing view with
`planning: null`. The Planning Room is read-only and exposes no action, approval, or retry control.

Activity combines at most 200 chronological durable audit and browser-session runtime rows, preserving each source label. Recorded and live agent-to-agent turns remain individual `from -> to` rows with their full bounded message text.
Live tail starts enabled, pauses on upward scroll, and supports agent and keyword filters. Time, route, type, detail, and correlation columns are configurable; type starts hidden. Fullscreen changes presentation only.
Time shows clock time in the browser's IANA timezone (`KST` for `Asia/Seoul`); machine rows retain complete timestamps. Waterfall remains the durable audit master-detail surface for lifecycle, inputs, outputs, recorded conversations, and hashes.

Audit follows the approved record-review mock: query controls, a newest-first record rail, selected evidence, raw JSON, and provenance. Selection is local; exact-record links retain server-side sequence bounds and current filters.
Text search covers loaded records only. Decision, window, and correlation filters query the existing Operator API. Pagination preserves selection and surfaces failures without discarding earlier evidence.
Ledger-wide aggregates remain unavailable without a server projection. Only a selected record's explicit stage marks its evidence phase; neither dispatch nor observation alone proves an effect. Stored hashes never become a browser integrity verification.
Ledger guarantees remain unverified, unsupported replay/export actions are omitted, and English/Korean layouts reflow without clipping identifiers. Current-screen context preserves causal fields and the exact selected record.
Periodic idle and watching health snapshots update current agent state and observation time without
reloading the unchanged durable audit page. Active work, completed handler transitions, Incidents,
and handoffs continue to refresh audit evidence. The Activity header shows the latest observed
heartbeat time without adding repeated passive snapshots as work rows.
Principal-scoped Command Deck turns and answer planning stay in conversation history, never shared
Agent Activity. Conversation Assurance is a separate principal-scoped Evidence route whose list
contains bounded metadata and digests, not answer bodies. Detail reads the original answer only
through the authorized conversation store; its sole write is an idempotent append-only dispute, and
the browser rejects advertised policy mutation authority. Synthetic readiness proof stays in Audit.

Every data-bearing card across the console drills down. The complete card surface uses a native
keyboard-accessible link to the narrowest analytical or filtered-evidence destination that owns the
datum. A card with independent controls exposes a visible primary detail link instead. Dashboard
posture, evidence metadata, measured or unavailable outcomes, distribution legends, attention facts,
vertical statistics, and collapsed operational counts follow the same rule. Section headings and
explanatory copy remain non-interactive. An unavailable value still opens its owner view so the
operator can see which source or sample is missing. Structural groups, forms, editors, and bounded
tools without a detail destination use panel or section semantics rather than card styling or names.
Unavailable metric cards use a subdued whole-surface background, no elevation shadow, and compact
muted value text so they don't read as measured results. They remain focusable drill-down links and
retain a complete-border focus or hover cue; the visual treatment never sets disabled semantics.
The shared KPI card distinguishes `not-measured`, `not-connected`, `insufficient-sample`, and
`not-applicable` evidence states. These states use neutral copy and styling; actual request or probe
failures use the error component and remain visually distinct.
An exact Incident deep link joins an existing roster only when both projections carry the same
analytical snapshot sequence. A concurrent snapshot change remains unavailable rather than mixing
records and metrics from different evidence revisions.
Cards whose authoritative visible content changes in place use the shared `top-edge shimmer`: one
neutral blue sweep, 2 px high and 1.35 seconds long. Primitive shared KPI values opt in
automatically; complex live cards provide a semantic update key. The first render, unchanged parent
rerenders, filters, selection, and clock-, age-, or timestamp-only changes stay quiet. Rapid updates
coalesce while one sweep runs, and reduced-motion preferences disable the animation. The shimmer
only confirms that displayed content changed; status, freshness, severity, and outcome remain in
their labeled content-local cues.
The console card contract test checks shared KPI destinations, rejects nested whole-card links,
requires nullable KPI values to declare an evidence state, requires raw data cards to expose a link
or explicit detail control, and blocks structural card names. Detection coverage reasons and Trace correlation, stage, and timestamp details use the shared tooltip on pointer or keyboard focus; native `title` attributes remain reserved for embedded frames. Loading and unavailable coverage cards retain their owner links, while Impact Scope uses a responsive single-column mobile form, labeled evidence graph, and 44 px mobile controls without changing its read-only authority. Relationship legend swatches use color and line pattern inside the key instead of a thick colored content-surface edge.

Operating Outcomes publishes its metric, value, baseline, window, sample size, confidence and
provenance as a bounded Command Deck snapshot. Only Auto-resolution includes vertical breakdowns.
Narration receives rendered facts, never invented unavailable values or replacement sources.
Headlines and cards share formatting, preserving ratios and the displayed percentage precision.
Dashboard routing retains its own canonical sample, independent of general audit noise.
Mode, tier, action, outcome, window and sequence filters reach the server-owned audit query.
Admitted cohort comparisons remain separate from rolling Live values, expire, and grant no authority. Their captured view context retains both arms and the expiry rather than substituting the rolling baseline. Expiry republishes the view, and every submission withdraws expired cohort groups from pinned snapshots as well.
The audit-backed projection captures one UTC window and append-only head sequence, then reads
canonical classifications, independent outcomes, metric observations and human inputs below it.
An over-budget complete read fails closed rather than reporting a partial rate. Normalized event
identity controls the denominator; incident/change identities control timing sample sizes.
Concurrent appends after the cutoff do not enter the snapshot. An
event is auto-resolved only after an explicit `measurement.action_outcome.v1` record finalizes an
enforce, verified, auto, non-rollback action and the complete event evidence contains no human
approval, denial, execution failure, or rollback signal. Dispatch-only events remain pending. The
route shows observed, finalized, pending, adverse, and auto-resolved counts separately; the
auto-resolution rate keeps the canonical total observed-event denominator, so pending and other
non-auto events never disappear from the rate. Classification, outcome, and metric payload timestamps more than five minutes ahead of their durable audit timestamp make the projection unavailable rather than becoming measured evidence.
Operator builds this read-only projection from the bounded canonical measurement streams at one cutoff, then validates the complete, consistent, non-synthetic envelope. Counts and effective cutoffs must reconcile; Operator never repairs a malformed or partial snapshot from general audit rows or fallback state.
Vertical attribution uses an explicit recorded vertical first, then only strong Resilience or Cost
Governance action/resource hints. Evidence that cannot be attributed without guessing remains in an
`unattributed` row, contributes to the global denominator, and lowers the displayed attribution
coverage. It never falls through to Change Safety. The fixed three-domain portfolio omits the
unattributed row while Operating Outcomes keeps it visible with an Audit destination.

Each Operating Outcomes route keeps a metric-specific analysis surface. Auto-resolution shows its
observed event and auto-resolved record counts, vertical rates, and guard context. Human touchpoints,
MTTR, change lead time, and cost per resolved event each reserve their own analysis and breakdown
sections. When the read projection does not provide touchpoint types, latency percentiles, delivery
stages, or cost composition, the section renders unavailable instead of reusing an unrelated vertical
table or deriving values in the browser. Cost views also state that displayed amounts use standard
prices and can differ from billed amounts after discounts, commitments, credits, taxes, exchange
rates, and provider billing adjustments.

Control Assurance presents the operating banner, evidence metadata, posture metrics, promotion
guards, terminal control-path distribution, and required-attention totals from the audit KPI,
autonomy measurement, and promotion registry projections. Guard rows compare current, baseline,
and threshold values and link to filtered evidence; distribution segments and attention rows link to
their narrowest audit, approval, or promotion destination. Synthetic guards never produce an
operational pass or failure, and a missing projection renders unavailable instead of supplying a
prototype value or inferred zero.

Vertical Outcomes is one portfolio overview rather than three selected-detail routes. Each vertical
card uses the same visual grammar but names a distinct primary outcome and links directly to its
owning evidence surface: Incidents for Resilience, promotion evidence for Change Safety, and Audit
for Cost Governance. The shared comparison table is the only place that repeats events,
auto-resolution, unresolved risk, and savings across verticals. A domain metric such as change
failure rate or recovery drill success remains unavailable until the read model supplies attributed
evidence; global confidence and trend values aren't relabeled as vertical-specific claims. An empty
vertical has no inferred resolution rate, and synthetic evidence never creates an operational health
label or a filtered runtime-evidence claim.

Trust Routing presents T0 (deterministic rules), T1 (lightweight similarity reuse), and T2
(grounded LLM reasoning) as one measured tier map. Routed share, event count, and target band come
from the autonomy and audit KPI projections, and each tier links to its own analytical route. The T2
control flow describes mandatory architecture checks rather than claiming that a run passed them.
Leading indicators compare only reported current and baseline values. Missing values remain
unavailable, and simulated values never create an operational pass or failure.

LLM Cost leads with measured calls, tokens, chat share, and latest invocation evidence. Input and
output composition, the selected-window trend, model and conversation attribution, and invocation records are derived only
from the metering projection. When price attribution is not connected, the route states that boundary
and doesn't estimate spend, budgets, fixed infrastructure cost, per-call prices, or invoice amounts from token volume. The bounded visible invocation ledger can export a fixed allowlist as quoted CSV; formula-leading cells are neutralized. Detailed
conversation, workload, mode, day, and month rollups remain available in a secondary disclosure so the primary view
stays scannable without hiding evidence. Headline KPI labels and values stay left-aligned in a
balanced four-, two-, or one-column grid, while token-composition counts and shares use common
right-aligned numeric columns for comparison. One global UTC selector provides rolling 24-hour,
seven-day, 30-day, and custom one-to-90-day windows. The Operator API validates aware RFC 3339
`from` and `to` values and applies the same inclusive-start, exclusive-end cutoff before computing
every total, attribution, bucket, and invocation record. The URL preserves the exact cutoff. The
24-hour view uses hourly buckets; longer windows use daily buckets. A custom display end date is
inclusive and maps to the next UTC midnight as the exclusive API boundary.

## Loading presentation

The [Console loading presentation reference](../../reference/console-loading-presentation.md)
defines skeleton, reduced-motion, stylesheet, and hot-update behavior.

## Localization boundary

The SPA resolves display locale from the operator preference. Reusable strings come from the main
English-source catalog or a complete route-local English/Korean pair with mandatory English
fallback. Static key coverage, catalog parity, route fallback tests, and the console suite prevent
untranslated display text from returning. Grounding trace labels and manifest/reference count
details use the same catalog rather than embedding English in reconstructed evidence metadata.

Localization changes presentation labels only. Machine values, workflow ids, serialized records,
provider payloads, and validation results remain unchanged.

## Web presentation module registry

The Command Deck validates a complete artifact before module lookup. The registry maps each closed block
kind to one Preact component, responsive policy, and accessibility fallback; modules never infer a table, chart, status, or unit from prose.
Offline and production builds lock Mermaid parsing and DOM sanitization. A known Moderate-or-higher
advisory in that shipped graph blocks release until Console tests, typecheck, offline build, and audit pass.

| Block family | Module responsibility | Accessibility and fallback |
|--------------|-----------------------|----------------------------|
| `summary`, `callout`, `evidence` | KPI facts, limitations, provenance, and receipts | Native description lists or lists; exact text remains visible |
| `table`, `threshold_table`, `list` | Exact records and comparisons | Native table/list semantics; narrow layouts reflow labels without changing values |
| `bar`, `coverage` | Bounded categorical values or verified composition | Visible values plus a semantic description; adjacent exact-value table when required |
| `time_series` | One ordered metric and unit | Focusable points, description, exact timestamp/value table, and no motion requirement |
| `comparison` | Baseline/current/target or before/after | Role labels, unit, exact values, and a table fallback |
| `timeline` | Evidence-bearing order | Ordered list with machine timestamps preserved in `time` elements |

The registry owns component selection only after parser acceptance. Unknown or malformed v2 input,
an unbound reference, duplicate slot, non-finite value, timestamp disorder, unit mismatch, or missing
fallback rejects the artifact and leaves canonical text visible; module errors cannot expose raw JSON.

Charts use CSS and semantic HTML rather than a canvas-only surface. Keyboard users can reach every
data point that has a tooltip, and the visible tooltip repeats exact values rather than introducing
new text. `prefers-reduced-motion` removes transitions without hiding data. Stable dimensions and
overflow policies prevent labels, long Korean, timestamps, and opaque identifiers from moving or
overlapping the transcript.

## Observed conversation trajectory

Each Command Deck question selects the smallest presentation supported by observed work. A turn with
no activity, handoff, or background task keeps a collapsed run record. One successful terminal read
uses a compact investigation row and a collapsed run record. Multiple activities,
milestones, retries, failures, handoffs, commands, or file changes retain the complete timeline but
keep its run record collapsed by default. A durable background task uses a detached task summary. Restored compact turns reconstruct
the observed row from durable detail, while live turns retain the row already shown in causal order.
Every completed answer keeps its trajectory summary available. The bounded original operator prompt
stays hidden while the run record is collapsed and appears when the operator expands it.
Internal AnswerPlan intent and detail labels don't appear above the answer. They remain available in
the Run record decision context, while the answer leads with operator-facing content and verified
evidence. Model-assisted planning changes only a validated presentation shape. A verified
`presentation_artifact` v1 can mix summary, table, chart, coverage, callout, detail, and evidence
blocks whose content was compiled by the server from immutable evidence. The browser rejects an
unknown block, duplicate slot, invalid bound, incompatible chart, or evidence reference outside the
terminal verification receipt, then renders the canonical answer text instead. Partial evidence
keeps every valid block and adds an explicit limitation block; one missing source never suppresses
the rest of the answer. A legacy verified chart can still return bounded `chart_artifact` v1, and
canonical Markdown or fenced chart data remains the compatibility fallback.

The status overview distinguishes completed, corrected, degraded, failed, unverified, running, and
unobserved phases; record presence isn't success. Result chips report observed query and command
counts, evidence completion, references, and verification rather than internal event totals. The
serialized `unverified` status remains stable for replay. Its primary Console label is derived from
the bounded reason code as Context required, Source unavailable, Invalid query, or Unsupported
claim, while technical detail retains the canonical status and raw reason code. The
two result indicators are fixed dots no larger than 10 px that overlap by 2 px on the source-button
edge. The source button keeps its own source tooltip. The dots form a separate pointer and keyboard
trigger and directly widen into compact query, command, and evidence pills to the right without a
floating tooltip or separate container. Full summaries remain in the trigger's accessible name. The
dots use absolute positioning, so they create no row, change no reply-action geometry, and don't
cover adjacent actions. When no source button exists, the same directly expanding dots attach to
Review answer quality. The
expanded run-record summary retains the complete bounded
operator prompt and wraps it on narrow layouts. Changing its disclosure
scrolls only the transcript while the composer remains visible at the Deck boundary. The expanded
view leads with the six-phase rail,
expandable observed-event timeline, and provenance signals, while timing windows, decision context, phase records, and coverage gaps remain in one
collapsed execution-details disclosure.
The preparing-answer surface remains between the operator turn and observed work until observed
activity and evidence branches reach a terminal state. Answer tokens that arrive earlier stay in the
browser paint queue. The activity shell becomes settled in the same render that adds the answer, so
a running investigation skeleton and answer content never appear together. Observed work follows the
execution mock's progress-note, session, connected-step, and dark command-detail hierarchy. A standalone activity
derives its starting note only from that received activity. A milestone remains the note when one was
received, so the browser doesn't duplicate or invent progress. Only the current step opens
automatically; completed step shells remain visible while raw output and timestamps fold. Raw
current-screen records stay in a collapsed source disclosure. Progress, observed activity, and the
terminal answer for one operator question retain separate causal records but render under one
visible agent header and one connected flow. The terminal answer doesn't repeat the same agent or
open a second source badge. Numbered progress and status glyphs are optically centered inside their
fixed circular markers without moving the shared vertical rail. The numbered glyph uses the same
restrained blue accent as the progress label instead of the darker body-text navy. The transcript
disables browser scroll anchoring, keeps extra bottom space, and follows the latest edge only while
work streams. On terminal completion it anchors the first observed work group below the transcript
edge, so execution outcome and answer start remain visible while the final answer lays out.
Untimed plan and collaboration metadata stays in decision context, while only observed input, evidence and tools, model calls, verification, and delivery use the timeline.
Every waterfall lane uses one labeled start-to-completion scale with quarter-window ticks. An
internal causal rail connects the rows, and a dashed segment identifies measured time between
recorded intervals instead of leaving an unexplained blank. An execution activity with complete
timestamps replaces its linked generic evidence branch and keeps its observed label, tool,
authority, and detail. Phase envelopes use restrained blue, evidence work uses green, model work
uses plum, and point-in-time turn records use neutral gray circles. The input marker anchors to the
earliest timestamp observed for the turn, and the terminal answer anchors no earlier than the final
recorded timing completion. Browser and server clock skew therefore cannot place evidence before
input or generation and verification after delivery. The lane baseline and ticks remain distinct
from a completion progress bar.
Answer text uses 15 px text, main disclosures are 44 px high, and content reflows without loss at 200% text resize and 320 CSS pixels.
Trajectory headings use 13 px, event labels use 12 px, and compact trajectory metadata uses 11 px.
A terminal verified answer that contains the exact server-rendered English or Korean recorded-agent-activity block presents those rows as one compact vertical timeline. Each row retains the agent, canonical event token, exact ISO timestamp, and localized readable time; malformed or unknown prose remains ordinary answer content instead of becoming observed activity.
A published screen snapshot becomes visibly stale
after five minutes and offers an explicit page refresh; a bare clock never implies current evidence.
Markdown tables render progressively. A completed header and separator create the table shell before
the first body row arrives, and each completed row appends without replacing the table. Incomplete
header, separator, and row syntax stays hidden rather than appearing as raw Markdown. Every bounded
answer row remains in the transcript flow without an internal vertical scroll region or row-expansion
control. A foreground terminal-only deterministic answer uses the same visual paint queue, so its
canonical table also reveals monotonically from zero rows to the complete row count. Background tabs
finish synchronously. Cells wrap on narrow screens instead of widening the transcript.
After a one-call general-knowledge answer passes its terminal schema, locale, profile, and
no-authority checks, the browser sends its canonical text through the same bounded token callback
and paint queue instead of displaying the whole paragraph in one update. It never exposes partial
provider JSON or pre-validation prose. In the authenticated standard-port desktop check, the answer
became visible at 3.959 seconds, changed across 13 answer-text paints, and completed at 4.415 seconds;
the complete conversation log changed 53 times including progress timing.

Detail includes bounded recorded metadata but doesn't repeat the answer body. Each expanded timeline
event shows the available source-record detail, including evidence summaries and references, plan
intent and format, answer source and model-call count, verification authority and checks, or model
request and response metadata. A recorded-payload block appears for every applicable lane:
operator input, IQL or command plus
observed output, AnswerPlan, redacted model request and response, verification receipt, and terminal
delivery receipt. A lane without that payload type still shows status, start, completion, and its
available facts rather than an empty panel. The answer lane records delivery metadata and does not
repeat the answer body. When a bounded Resource list is truncated, technical details retain the same returned rows plus returned-count, total-count, and truncation metadata. The limitation text never promises that unreturned rows are present in the browser payload.
Inventory execution displays the canonical turn query as an `IQL` activity. Following activities use one terminal icon for exact bounded Azure CLI or ARG receipts. They show the authenticated subscription id, generic argv, measured command duration, count, and at most ten allowlisted preview rows while
redacting pagination tokens, credentials, raw resource ids, and provider errors. IQL source and
result toggle independently; rows describe snapshot refresh without claiming rerun, and the browser never derives commands from IQL or source names. Terminal-only visual reveal is capped at 30 chunks, and server completion rather than paint completion anchors the answer lane, so presentation pacing isn't rendered as an execution gap. Valid object or array JSON in provider messages, action arguments, commands, and outputs uses indented syntax highlighting and copy; malformed or plain text stays unchanged. The terminal replay payload retains final ID-deduplicated branch, activity, milestone, and redacted execution detail under a 64 KiB aggregate cap, truncates each history output at 32 KiB, and reports truncation and omission counts, so durable history and the live turn use the same strict parser and trajectory view. Unavailable or timed-out
evidence is an attempt, not completed evidence, and unverified work never receives completed styling. Missing activity stays in an observation-coverage disclosure and proves no absence. Exact-answer
durable replay uses the same bounded browser parsers. The server buffers model tokens until the provider's terminal content-policy decision is known; a block exposes no partial token or assistant answer, records only a content-free receipt, and produces the same deterministic fallback for SSE and JSON `422`, while logs retain only stage and aggregate counts. An explicit provider refusal, truncated completion, malformed stream frame, or stream without a verified terminal signal never becomes an assistant answer. After Operator already holds a durable semantic projection that its local authority checks mark verified with `semantic_answer_verified`, it may emit cumulative `confirmed` segments carrying that exact semantic receipt, evidence references, and a segment-specific replay cursor before `done`. Locally generated document-ready or unavailable wording is terminal-only and never inherits confirmation from the source answer. The browser withholds confirmation after a sequence gap, rejects a present invalid or cross-request receipt, ignores stale revisions, and synchronously retracts prior text and confirmation when a correction or cancellation occurs. A newer revision may then establish its own verified receipt. The browser also retracts segments if terminal verification, evidence references, receipt, text, revision, sequence, or stream integrity differs.

Terminal timing covers at most eight allowlisted semantic-plan, evidence, generation, quality-review,
and verification phases. One UTC anchor plus monotonic elapsed time produces observed status, start, completion, and duration. Interrupts persist none; strict parsing rejects inconsistent timing.

Model provider tracing is a browser-local Settings opt-in that defaults off. When enabled, the
request-local collector records up to eight actual model calls for that question, including turn
planning, reruns, answer generation, and quality review. The Waterfall uses provider-call timing;
an enabled trace with zero calls remains visible and explains that the deterministic path needed no
provider lane. When capture is off, the panel remains visible with a Settings opt-in notice while
stored trace data stays hidden. A turn without captured trace uses the same explicit unavailable state.
Each disclosure preserves the recorded message array and request SHA while grouping consecutive
system layers under one `SYSTEM` heading. JSON bodies are pretty-printed. Object or array JSON
serialized inside a JSON string is expanded with bounded depth and node limits, while plain text
and malformed nested values remain unchanged. Bounded request and response blocks use
theme-matched scrollbars. The disclosure also shows assistant content, token usage, exact-content
SHA-256, and redaction counts. Credentials, tenant or resource identifiers, URLs,
email, IP addresses, inline images, hidden reasoning, headers, and provider internals aren't
retained. Turning the setting off stops capture, hides stored trace data, and removes the trace from an
idempotent replay response without repeating the provider call.

This principal-scoped view is distinct from [governed trajectory datasets](governed-trajectory-datasets.md),
which remain authorization-first offline review artifacts. The view excludes hidden reasoning, raw
unredacted prompts, credentials, unrestricted payloads, and data that wasn't recorded for the turn.

## Durable request replay

A completed request is replayed only when principal, conversation, idempotency key, and request
content match. The stored terminal assistant payload is returned without repeating evidence
retrieval, narration, or post-turn review. Changed content or another conversation under the same
key is a conflict. JSON, SSE, and cross-transport retries share this terminal payload.
A content-policy receipt follows the same identity checks. A matching retry replays the policy
result before preference resolution, document retrieval, history compaction, planning, or provider
work. A changed prompt or conversation under the same request key is a conflict.

An optional incident conversation binding carries a bounded incident id, correlation id, and
allowlisted Pantheon agent. The browser and server enforce the same bounds. Invalid persisted
bindings are discarded without deleting the conversation. Agent activity describes bounded
historical audit evidence; missing activity does not prove that an agent has no current task.
A new ephemeral conversation does not query durable history before its first operator turn creates
the server record, so a normal first-open state is not reported as a missing-history error.

## Verified evidence

Read-source provenance, ontology browse, cross-screen operational, and inventory answers are
rendered deterministically from typed evidence. Ontology browse requires a target and browse verb,
forwards only allowlisted identity fields with prompt values up to 256 characters, and renders
duplicate or malformed counts and selections unavailable. Ontology projection and its deterministic
browse answer stay in their own prompt module, separate from general prompt assembly. Ontology Instances carries active-generation provider type coverage separately from Resource state and relationship coverage; the browser validates reconciled counts and shows bounded unknown type names without raw object identities or properties. Promotion Gates displays server-joined durable mode and its catalog-default or registry source; browser values cannot author either field. Valid mode fields do not bypass malformed missing-evidence list rejection; decoder regression fixtures must exercise both checks independently. Dashboard v2 restarts its complete bounded page traversal only for typed inventory or ontology generation transitions, discards partial pages, shares the original deadline across two delayed retries, and keeps persistent mismatch visible instead of mixing generations or returning an empty inventory. The Architecture map assigns every canonical ResourceType an explicit layer, color token, and abbreviation; only unknown future types use its generic fallback. Correlation Trace preserves server-projected action id, attempt, execution path, and outcome; exact event-name boundaries classify proposal, decision, approval, dispatch, observation, and recovery per attempt without introducing a natural-language router, while missing evidence remains not recorded, proven no-effect renders as not attempted, and absence never implies success.
The Reader-gated `/ontology/graph` projection contains one exact catalog release with a schema
version, projection revision, release digest, declaration records, semantic-map profile, and
catalog topology. It never returns deployment instance properties. Runtime objects and state facts
enter the Console only through a separately authorized Context snapshot that preserves cutoff,
freshness, completeness, conflicts, truncation, and evidence references. The WARA Controls projection applies the same provenance rule to advisory catalog data: detail views link the pinned APRL source and optional Learn page, display version, revision, digest, retrieval time, license, and query digest, and request bounded 50-row pages with URL-preserved offsets and overflow-safe recommendation, mapping, evaluation, satisfaction, and source identity.
Ordinary delegated answers keep Bragi as narrator while displaying the verified specialist as
response owner. A dedicated target session instead uses that specialist's verified voice until an
explicit handoff returns narration to Bragi.
An agent-targeted Web turn displays that selected specialist from the first provisional token and
keeps the label stable until terminal delegation either confirms the owner or shows a handoff.
When an explicit handoff returns the turn to Bragi, the Web labels ownership as
`specialist -> Bragi` in the reply header and answer-plan row. If the handoff carries no specialist
answer, deterministic verification returns an unavailable-evidence response and never validates
narrator prose against unrelated current-screen facts.
When a selected agent and server-owned operational evidence both resolve, the coordinator retains
both; deterministic verification still owns incident summaries, absence claims, and causes.
Bragi completes the T0/T1 owner route once, then the ordinary answer path selects one uniquely
highest-scoring read tool from that owner. A completed tool result becomes the primary specialist
answer, and its scoped facts enter the existing agent-evidence manifest. A tie or no match keeps the
owner's ordinary response. A selected read that abstains, times out, is held by sensitivity checks,
or completes only partially produces an explicit handoff without a generic or contributor fallback.
Planning and dispatch remain depth-one and share one bounded gather budget. This ordinary path is
lexical and does not add an embedding call to the agent route.
A question no agent owns never enters the tool-answer path.
Charter version, hashes, and tool ids remain hidden provenance. An exact policy match lets the
model receive that server-owned charter after Bragi's global safety prompt; it scopes role and
voice without becoming evidence or authority. Runtime grounding uses supplied
evidence refs or a content-addressed hash of normalized agent facts, never the static agent spec.
Agent narration is not an evidence source: atomic claims bind agent fact leaves to unique JSON
pointers rooted at those runtime-supplied refs, including separately attributed contributor facts.

Incident titles are server-owned evidence. The read projection prefers recorded title, summary, or rule fields, then bounded signal and resource correlation keys; empty, `None`, and `null` markers are absent.
The browser invents no subject. Incident detail labels operator-readable `incident_number` as Incident number and canonical `incident_id` as Incident id; localization never conflates them.

The selected Incident detail leads with one operator-readable current situation derived only from
the lifecycle summary and its loaded audit history. It separates lifecycle state, response
decision, change authority, and operator attention instead of presenting raw `pending`, `unknown`,
and `shadow` values as one status. Notification-delivery escalation takes precedence for an active
incident and names the required follow-up. Audit and technical activity remain available when
records exist. Root-cause analysis and its dossier become links only after an `rca.*` record exists;
otherwise the rows state that no evidence-backed hypothesis has been recorded. The RCA route also
hides its generic audit fallback response when no hypothesis exists, so `incident.members` is never
presented as a response plan or cause. The Trace route leads with an interpretation summary that
separates notification escalation, response-decision evidence, RCA evidence, and named pipeline
stages before showing the raw ordered table; generic correlated activity remains technical history,
not a cause claim.

Operational evidence remains one of `matched`, `summary`, `ambiguous`, `none`, or `unavailable`.
For a collection summary request, `summary` renders the bounded matching set immediately without
requiring a single incident selection. Model prose cannot change the selected incident, search
scope, supported cause, collection membership, or absence claim. A source with
`availability=unavailable` never reports `reachable=true`; unconfigured or unprobed sources use
`reachable=null`. An explicit latest-incident summary selects the single most recent server-read-model incident instead of returning a collection. Root cause, timeline, hypotheses, similar incidents, impact, next action, consumed evidence, uncertainty, and deep-investigation questions require one incident. Without a bound incident, generic analysis wording returns bounded candidates for operator selection and never borrows current-screen, repository, agent, or public-web evidence.
An `ambiguous` terminal answer also carries a versioned artifact with at most five server-validated
incident candidates. The Web client renders one button per candidate with title, severity, status,
last-updated time, and incident id so duplicate titles remain distinguishable. Selecting a button
opens an exact incident-bound conversation and immediately submits a localized read-only
investigation question. The explicit click is the operator request; it doesn't mutate a managed
resource. Missing, malformed, oversized, or unverified candidate artifacts render no buttons and
cannot create a binding.
Generic recency words such as `latest`, `recent`, or `최신` do not create incident authority by
themselves. Operational lookup also requires explicit incident, issue, outage, failure, problem, or
cause semantics. A public software version or release question therefore remains eligible for the
bounded public-web path instead of producing a deterministic "no matching incident" answer.
Current-screen data scope takes precedence over inventory, incident, agent, and web enrichment. Topology, end-to-end reachability, inbound network policy, peering, and failure impact-scope questions require exact source and target resource names or one server-validated selected network resource. Context-free references return a deterministic clarification before the inventory provider runs; current-screen links, resource-group membership, or incident evidence never become proof of connectivity or impact scope.
The Trace correlation is an incident selection hint only when the question explicitly carries
incident, failure, problem, or cause semantics; ordinary stage and actor fields remain screen facts.
Supported current-screen values and explicit absence answers are rendered by Bragi T0 without a
model call. An explicitly empty facts or records projection is evidence of screen coverage, not
permission to fall back to model memory. The resulting answer still passes the atomic-claim
verifier before it becomes terminal.
Current-time questions use an injected timezone-aware server clock and the principal's IANA
timezone preference. The terminal answer is rendered deterministically with the exact timestamp and
timezone. A missing preference falls back to explicitly labeled UTC; the narrator and browser clock
are not time authorities.

The Forecast Learning route reads only the server-owned PostgreSQL projection. Closure completeness
uses due episodes as its denominator, and publication health separates future scheduled work from
due debt, failed attempts, and dead letters. Missing cohorts render unavailable rather than zero;
the browser never derives a model miss, pipeline miss, or retention status from unrelated counts.

The Trace route publishes `correlation_id`, `load_status`, and an actionable `load_error` when
present, including during an error render. The server may use that correlation only as a selection
hint and rechecks it against the authorized read model before returning operational evidence.
Trace keeps correlated audit rows in sequence order, represents activity without a pipeline stage
as `stage: null`, and derives `terminal_stage` from the last named stage.
When no citation-grounded RCA exists, deterministic verification first renders bounded detection
facts from the durable `incident.open` record: signal, target resource, and correlated member-event
count. These facts confirm the observed condition, not its cause. Workload failure reasons remain a
separate section. `notification.*` failures render only under notification delivery and never
become workload failure or root-cause evidence. A notification-focused incident can still lead
with its delivery failure. Every path labels recorded failures as observations rather than a
complete root-cause conclusion.

Each manifest route has one owner. The SPA strips query and fragment components, matches exact
paths or descendants on a path-segment boundary, and selects the longest owner. Similar prefixes do
not inherit ownership. A panel remains `unknown` when any owned route is absent from the manifest;
only explicitly source-independent panels omit source status.

The production Operator API loads and validates the operational ownership map before registering
`GET /stewardship`. The console projects that source read-only. Its Handover form can submit
structured person or group assignments to the separate ingestion boundary, but it cannot apply the
map or hold Git credentials. Draft PR creation and signed merge processing remain on the
ingestion/GitOps boundary, and the returned draft includes the persisted idempotent PR receipt.
The browser renders a receipt URL as a link only when it is an absolute HTTPS URL without embedded
credentials; otherwise it displays the PR reference as non-clickable text.
Content upload keeps the API bearer token only for same-origin ingestion proxy targets. A cross-origin direct-upload target receives the content headers but never the Operator API credential.

## Progressive parallel conversations

Branch lifecycle, ordered reduction, confirmed revisions, cancellation, replay, and metrics are
owned by [Operator Console Progressive Conversations](operator-console-progressive-conversations.md).

## Stream recovery and authentication

Authenticated GET-SSE consumers share bounded parsing, inactivity, reconnect, and cursor handling. A cursor advances only after decoder acceptance; cursor-specific `400` or `416` clears it, and a validated `stream_epoch_changed` gap clears it before current snapshots resume. The epoch transition is shown as a stream restart without fabricating a dropped-frame count. Authentication, rate limiting, and rejected frames preserve cursor and backoff. Server drop advisories remain visible, but local cache eviction is not wire loss. Each consumer retains its own visibility and cross-tab policy, and request-scoped conversation streams remain separate.

Command Deck investigation activity can include optional observed execution evidence. The server removes credentials and sensitive identifiers before emission and sets `redacted=true`; the browser
drops input evidence without that attestation. `input_kind=command` requires a recorded process
invocation and may carry an exit code. `input_kind=query` carries the canonical typed server query,
never a reconstructed provider command, and cannot carry an exit code. An accepted activity shows
the matching `TOOL` or `QUERY` badge, tool label, authority, and completion state. Command output,
query results, and timestamps stay collapsed by default. Valid object or array JSON is pretty-printed
inside bounded fixed-dark code surfaces with theme-matched scrollbars. Inventory results retain the verifier-accepted detailed projection, including matched resources, counts, coverage, and snapshot provenance. Input is limited to 16 KiB and the result preview to 64 KiB; oversized collection tails are omitted with explicit counts so output remains valid JSON. Activity and retrieval labels are limited to 512 characters, detail and
milestone text to 16 KiB, and contradictory completed/total progress is rejected.
The browser can copy the displayed command or query but can't run or retry it. This evidence remains a
read-only observation of work performed by an authorized runtime, not proof that the console owns
an executor identity or temporary permission.

Command Deck web-research turns stream truthful `status` frames while work is in progress. The
server emits `web_search_classifying` only when semantic search intent invokes the narrator model,
`web_search_searching` only before a public-web provider call, and `web_search_grounded` with the
sanitized source count and previews after retrieval. The preparing-answer trace renders these
stages immediately. A turn that doesn't perform a stage doesn't claim that stage.

Each completed model-backed turn keeps a visible LLM escalation disclosure with the selected model
and the stages supported by that turn's recorded metadata: evidence retrieval, model reasoning,
specialist consultation, evidence binding, and verification. A follow-up turn without new citations
still shows the model reasoning step and states that no separate source was attached; it doesn't
reuse earlier citations as if they were newly retrieved. Evidence values and paths wrap instead of
being truncated, and source details remain independently expandable for inspection. A completed
verification stage reports that checks ran; an unverified result uses an attention mark instead of
a success check.

A completed deterministic turn uses the same processing disclosure without an LLM label. The
disclosure identifies the deterministic answerer and preserves a recorded fallback reason such as
an unavailable backend or content-policy block, so a model outage never looks like an undisclosed
model response.

The browser accepts an LLM disclosure only when the recorded model identifier and optional latency
or token metrics match the bounded source-descriptor contract. Empty, oversized, control-character,
duplicate-metric, and free-form metric values don't create an LLM escalation claim. The raw source
badge remains width-bounded so malformed metadata can't displace the reply header. Token totals and
their prompt and completion components must each be finite and nonnegative before the browser
renders token usage.

Verification metadata is accepted only when check counters are nonnegative integers with completed
checks no greater than total checks. Atomic claim spans are ordered nonnegative integers, manifest
schema version 1 is explicit, and claim, failed-claim, and used-evidence references have no duplicate
or dangling identifiers. A non-`unverified` terminal status has all declared checks completed;
partial evidence remains visible but terminal verification stays `unverified`. Invalid combinations
become an unverified malformed artifact. Failed-claim identifiers exactly match unsupported or
ambiguous claims, and a manifest has the same authority as its verification envelope.
The browser mirrors the producer caps of 64 claims, 512 evidence entries, and eight additional
document references. Artifact identifiers are limited to 1 KiB, rendered values to 16 KiB, and
anchor or alias lists to 64 items. Live replies and session replay use the same parser, so reload
can't restore metadata that the HTTP boundary would reject or interpret it differently.

Session replay retains at most 40 recent turns in a 4 MiB JSON envelope. One turn contains at most
256 KiB of text, 512 bounded citations, eight bounded follow-ups, and 64 bounded activity records.
When serialization exceeds the envelope, the browser removes the oldest turns first. Oversized or
internally inconsistent optional collections are omitted rather than restored into the renderer.
Answer-plan section and override labels are limited to 64 and 128 characters, code validation
detail to 4 KiB, and milestone agent identities to 64 characters.

The Web composer sends selected, dropped, and clipboard-pasted raster images through the same bounded attachment tray and validation path. Before staging, the browser fits each raster within a 2048 px longest edge without upscaling and re-encodes it below the 4 MiB per-image ceiling. Clipboard text and HTML retain native textarea paste behavior and never become attachments.
When a turn carries validated inline image attachments, the streaming route also emits read-only `vision_analyzing` before the narrator composes and `vision_grounded` before the answer, each with image source previews (name, media type, size) but never the base64 payload. The turn escalates to a vision-capable narrator, and the preparing-answer trace renders these stages the same way it renders web-search grounding.

Live stage, readiness, and authority-free activity share one authenticated `/live/stream`. Snapshots do not advance the Operator-issued delta cursor, and a bounded cache serves late local subscribers without replacing independent GET projections. Agent state and retained history keep their separate routes and authority. The standard-stack Live E2E harness measures this connection budget, typed current activity, explicit retained-history read, and responsive presentation; the harness alone is not authenticated runtime validation.

The interactive Live subscriber reports idle while the tab is hidden. The shell's incident,
access-grant, and operator-enabled browser notification consumers instead use Web Locks to elect one
principal-scoped reader per channel across same-origin tabs. Incident and access-grant leaders send
validated snapshots to follower tabs through `BroadcastChannel`, so every shell keeps its attention
state without opening a duplicate SSE connection. The notification leader keeps its authenticated
live reader open in the background. This fixed connection budget leaves capacity for ordinary
Operator API requests under HTTP/1.1. The notification leader retries authentication failures with
the existing capped backoff and stops as soon as notification permission or the principal-scoped
opt-in is removed. Eligible alerts open correlated Audit evidence, not an assumed Incident.
[Console Web Notifications](console-web-notifications.md) owns event admission, bounded local
delivery, and recovery from legacy Incident links; no audit or Incident evidence is removed.

The Agent Activity route loads bounded durable inventory scan, ontology projection, and current-state
read records before opening the shared agent stream. Exact activity ids deduplicate replay and live
delivery. The journal keeps these routine work types in separate filter lanes and never creates an
Incident from them. Health-derived `agent.runtime-state` heartbeats establish current observation but
aren't work. Missing, malformed, future, or authority-bearing frames never promote a declared binding
into observed state. Each Operator API replica uses an instance-scoped consumer group so every console
receives the complete heartbeat set. A consumer that gives up or halts leaves health-derived
heartbeats while siblings continue; Saga or Vidar failure still forces sticky shadow. These records
are operational activity, not duplicated action-audit evidence. The Activity journal omits Saga audit-chain mirrors, startup audit probes, and raw observation-transition rows. Waterfall retains that audit evidence and attributes it only from an explicit Pantheon principal, `owner_agent`, known actor, or fixed legacy action owner; an unknown mechanical producer is never assigned by guess. Agent Activity owns per-agent audit and handoff order. Its route-backed Roles and ownership dialog contains only the fixed reporting tree, role ownership, authority boundaries, and supporting current state, preserves underlying filters when closed, and shares the same role-only component as `/pantheon`; neither surface duplicates Incident chronology or conversation evidence.

The Command Deck rejects a complete or pending SSE frame above 256 KiB before accumulating `data:`
lines or parsing JSON, then uses the deterministic interrupted-stream fallback. Correlation-filtered
action progress treats a terminal audit frame as completion, reports the 120-second deadline as a
timeout, and propagates other authentication or transport failures. Investigation rows advance
from pending to running to one terminal state; stale backward frames and terminal replacements are
ignored so a completed, failed, or unavailable operation cannot return to a spinner.

Before opening console data, bootstrap verifies the principal through authenticated `GET /iam/self`.
An initial network failure keeps data closed, presents the existing nebula surface as a service-starting state, and retries on a bounded schedule; a successful retry continues automatically.
After that schedule is exhausted, the surface offers access-check retry and sign-in. It does not start an automatic redirect because an unreachable Operator API would cause a redirect loop.

## Architecture-map resilience

The Architecture route uses one graph-first workbench modeled on the Ontology Instances
presentation. Its top toolbar contains only registered scope selection, bounded Resource search,
the `Topology | Network` lens, and a compact read-only source state. Scope selection reloads the
authoritative projection. Resource search selects only a record already returned by that
projection and never presents a bounded page as a complete tenant search.

Topology is visible before selection. The default Landscape derives authoritative Subscription,
Resource Group, VNet, and Subnet containment from resource identity and reported `contains`
relationships, then aggregates descendants instead of drawing every returned Resource. It never
requires the Operator API to supply presentation coordinates. The deterministic presentation
collapses provider helpers while keeping every returned count in a compact coverage strip. The
strip leads with freshness, truncation, and complete or partial coverage, then distinguishes
displayed and returned Resources and relationships. Selecting a Resource opens its smallest
reported containing scope, preserves stable coordinates inside that scope, reveals bounded direct
neighbors, updates the canonical deep link, and opens a nonmodal Inspector without changing
inventory.

The workbench uses one accessible orthographic SVG for Topology, Network, and the Impact scope map.
Subscription, Resource Group, VNet, and Subnet records render as nested neutral boundaries. The
Console creates all presentation geometry deterministically from the returned projection before
rendering; an unplaced visible record is an explicit unavailable presentation, never an implicit
`0,0` coordinate.
Boundary classification uses canonical Resource types and reported containment, not the presence
of optional presentation fields in an API response.
The SVG boundary rejects any visible Resource without finite generated geometry and renders an
explicit unavailable presentation while leaving search and source evidence accessible. It never
substitutes coordinate zero for a missing placement.
The default Landscape shows at most 16 returned Resource Group boundaries, ranked by returned
descendant count with stable name and identity tie-breakers. Displayed counts and search continue
to expose that this is a bounded presentation over the complete returned page.
If no Resource Group is returned, the Landscape falls back to at most 16 stably ordered actual
Resource records plus required ancestors rather than rendering the complete page.
Subscription remains a neutral outer boundary while each Resource Group becomes a compact summary
card with returned descendant and cross-scope relationship counts. An empty nested panel is not
used as a summary. Summary generation discards any incoming presentation coordinates and dimensions
before assigning compact card geometry.
The localized descendant and external-link summary appears in both visible card text and the
card's accessible name.
Outer boundary descendant counts follow the same visible and accessible-name contract.
Resource focus retains its reported ancestor boundaries and direct relationships, then fills the
smallest containing scope with at most 36 type-diverse returned records. Selection never expands
the workbench back to the full raw page.
Direct children and relationship endpoints consume the 36-record focus budget before unrelated
scope filler. If direct context alone exceeds that budget, coverage names the omitted direct-link
count while the Inspector retains the complete returned direct relationship list.
Direct endpoint reservation spans the complete returned page, including another Resource Group,
and excludes the selected Resource and ancestor boundaries that are already required context.
The omitted value counts returned link records, not unique related Resource identities.
The Inspector resolves its parent boundary through the same reported containment precedence as the
graph, so a VNet-contained Subnet does not fall back to a less specific Resource Group merely
because its provider parent field is broader.
Landscape boundaries count reported non-containment relationships that cross Resource Group
scope, but they do not rewrite those links onto aggregate endpoints. Exact source, target, type,
and direction appear only when the original records are visible in a focused scope.
The coverage strip is collapsed by default. Its summary leads with complete or partial state,
freshness, returned Resource count, displayed Resource count, and any reported page limit.
Snapshot and relationship totals remain available in the native disclosure.
Resources use reviewed official icons where available and stable Cloud Adoption Framework
abbreviations otherwise. Compact text, accessible names, search, and Inspector content preserve
name, type, and state without relying on color. Typed edges terminate on current node or boundary
geometry. Containment remains spatial; `attached_to`, `depends_on`, and `peered_with` retain
distinct paths, endpoint dots, and direction markers.

The right Inspector is collapsible and stays in the same workbench. Overview owns the selected
state and impact-scope drill-down. Links owns exact incoming and outgoing direct relationships.
Path owns Network source and destination, evidence result, filters, and sanitized export. Sources
owns snapshot, freshness, displayed and returned counts, completeness, reported relationship
types, and technical identifiers. At constrained widths the Inspector moves below the graph
without discarding selection, tab, scale, or path state.

The Network lens keeps the complete `InventoryGraphResponse` authoritative. With **Scope
overview** selected, it presents returned VNet and Subnet boundaries plus reported gateways,
firewalls, public exposure, private endpoints, and peering; it does not repeat the complete raw
Resource set. The overview retains all returned VNet and Subnet boundaries and at most 48 other
reported network-role records with their ancestor scope. Selecting a Resource derives one bounded network-plane focus and records that
selection in route state. Path tracing
walks only reported `attached_to`, stored-direction `depends_on`, and symmetric `peered_with`
relationships. It returns `no_observed_path` only for fresh, complete relationship coverage; every
incomplete negative result stays `unknown`. Filters and highlighting change only presentation.
Path tracing always uses the complete returned evidence graph rather than the bounded Network
overview. A found path adds its exact Resources, ancestors, and stored links to the presentation.
Category filters apply to surrounding context before that restoration, so they cannot remove a
current found-path hop from the map or sanitized export while the Inspector still reports it.
SVG and PNG exports retain sanitized provenance and omit names, raw provider ids, subscription
ids, endpoints, and credentials.

The SVG viewport owns pan, wheel zoom, Fit, full screen, keyboard node navigation, and a compact
relationship legend. Shared card geometry drives placement, containment, routing, and nonoverlapping
hit regions; visual cards render above their expanded pointer targets so an adjacent target cannot
steal a card click. Mobile controls and node hit regions are at least 44 px. The viewport remains
bounded and pannable rather than shrinking text below a readable scale. The Resource search and
Inspector provide equivalent non-gesture access. Reduced motion and forced colors preserve
operation and meaning.
Changing from Landscape to another scope starts that new canvas at its fitted origin. Resize inside
the same canvas preserves operator zoom unless the content would become smaller than Fit.
Reset identity includes the visible Resource identities and geometry, so two different scopes with
the same canvas dimensions cannot retain stale viewport state.

The Impact scope map requests an unscoped graph projection at the simulation snapshot and compares
every target and reached Resource identity before rendering. A snapshot mismatch or any omitted
impact identity produces an explicit unavailable map instead of understating the affected
topology. The simulation result and table remain the authoritative impact record.
Impact presentation infers observed subnet membership before generating geometry, matching the
Topology and Network containment pass without changing the impact traversal result.

A subscription-scoped cached snapshot renders immediately. Expired or change-invalidated snapshots
are marked stale while a background refresh runs. The browser polls only until the Operator API
atomically promotes the completed refresh, never upgrades the server freshness verdict, and retries
transient failures with bounded 2-to-30-second backoff while the stale graph remains usable.

## Verification

- Catalog parity and route-local fallback tests cover localization.
- Replay tests cover JSON, SSE, and cross-transport idempotency.
- Provenance tests cover unavailable, unknown, malformed, and route-owner states.
- Stream tests cover inactivity, authentication classification, frame limits, and action timeout.
- Architecture tests cover layout, selection, accessibility, cache freshness, and bounded polling. Browser Entra state transfer accepts only the exact MSAL cache-encryption cookie, keeps its value out of logs, and binds it to the target loopback origin; live Command Deck evidence follows the accessible `complementary` or full-workspace `dialog` role and creates a new conversation through the history panel.
- Architecture layout regression uses a geometry-less, truncated 500-record projection with 40
  Resource Groups and verifies bounded Landscape and focus counts, finite placement, unique
  positions, and zero implicit origin fallback.
- Browser checks assert unique rendered transforms, no unavailable-geometry fallback, a compact
  collapsed coverage summary, exact path-hop restoration, and zero horizontal overflow before
  responsive states can pass.
- Architecture hardening completion requires an independent review with no confirmed
  Medium-or-higher finding after the geometry-less live-shape regression passes.

## Related docs

| To learn about | Read |
|----------------|------|
| Delivery status and remaining work | [Implementation ledger](../../roadmap-implementation/interfaces/console-evidence-and-resilience.md) |
