---
title: Console Evidence and Resilience
---

# Console Evidence and Resilience

This document owns the operator console contracts for evidence provenance, localization,
stream recovery, durable replay, and Architecture-map resilience. The conversational tool and
RBAC contract remains in [operator-console.md](operator-console.md).

## Navigation context

Selecting an Activity Bar domain opens its Explorer and navigates to the first visible panel under
the operator's local order and visibility preferences. This navigation remains active when the
Command Deck is closed or floating; a full-workspace Deck closes before the route changes.
Selecting a cached conversation from another screen is the bounded exception: the console navigates
to that conversation's origin while suppressing only the synchronous conversation-owned route
event, then activates its transcript. The Deck remains open without a transient default-session
switch or close/reopen focus cycle. Same-screen and agent conversations switch without navigation.
Reselecting the already active same-screen conversation is focus-only; it does not reload the
sessionStorage transcript over newer in-memory turns.
An agent-card Ask action always opens a new empty agent conversation with a unique user-scoped key.
The new summary carries the selected agent immediately, so the first submit sends the same agent
target to the read API. Existing agent conversations are preserved as separate history entries and
are restored only when the operator selects one explicitly.
Removing the active cached conversation selects only a current-route default (including the legacy
`screen` key) or current-route thread. If neither exists, the console creates a new current-route
default instead of activating an unrelated-route or agent transcript.

The shared page title renders the domain and panel labels when they differ, including
`Overview / Dashboard`. A domain root whose panel title repeats the domain label and a standalone
utility keep a single title.

The shared top bar renders the Cloud Aperture mark in its canonical source blue. Console themes
don't desaturate or recolor the brand mark.

Live follows the same shared title contract as `Operations / Live`. Its observation controls stay
in the shared header actions area and wrap below the title on narrow viewports, so Freeze, source,
window, and connection status remain visible.

The Agents workspace uses three compact views: `Fleet`, `Org`, and `Activity`. Fleet combines live
runtime state with the fixed registry ownership and safety flags inside per-agent Details
disclosures. Org renders the keyboard-accessible reporting chart and selected incident evidence.
The stable `/pantheon` path remains a compatibility route for Org, so existing links continue to
resolve without keeping a second Pantheon directory in navigation. Ownership Handover remains a
separate Explorer panel because it has its own governed proposal workflow.

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

Operations includes a Detection readiness route backed only by Muninn's durable StateSnapshots.
It shows Heimdall's decision, the six evidence dimensions, gaps, authority ceiling, source, and
observation time. The browser does not probe AKS or derive a replacement decision. Each target
links to its Architecture resource, and promotion-related counts link to Promotion gates. A
successful HTTP response that fails strict decoding renders an error instead of remaining in the
loading skeleton.

Activity uses one bounded chronological log for durable audit rows and browser-session runtime
frames. Each row keeps its source label, so a runtime frame is never presented as durable audit
evidence. Recorded and live agent-to-agent turns render as individual `from -> to` rows with their
full bounded message text. The log retains at most 200 rendered rows, starts with live tail enabled,
pauses tailing when the operator scrolls upward, and supports agent and keyword filters. Time,
route, type, detail, and correlation columns are configurable; type is hidden by default. Fullscreen
changes presentation only. The Time column shows clock time only in the browser's IANA timezone,
including `KST` for `Asia/Seoul`; the machine-readable row retains the complete timestamp. The
Waterfall view remains the durable audit master-detail surface for lifecycle, inputs, outputs,
recorded conversations, and hashes.
Periodic idle and watching health snapshots update current agent state and observation time without
reloading the unchanged durable audit page. Active work, completed handler transitions, Incidents,
and handoffs continue to refresh audit evidence.
Principal-scoped Command Deck turns and shadow answer-planning contributions stay in conversation
history and never enter the shared Agent Activity stream. Agent Activity shows operational
object-topic handoffs and other runtime activity that is safe for every authorized Reader. Synthetic
`startup_readiness.audit_probe` proof history remains available in Audit and Waterfall but is
excluded from Activity so readiness evidence cannot displace operational work.

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
The console card contract test checks shared KPI destinations, rejects nested whole-card links,
requires nullable KPI values to declare an evidence state, requires raw data cards to expose a link
or explicit detail control, and blocks structural card names.

Operating Outcomes publishes the selected metric, current value, baseline, measurement window,
sample size, confidence, and source provenance as a bounded Command Deck view snapshot. It includes
vertical records only for Auto-resolution, the one metric view that renders that measured
breakdown. The narrator receives only rendered evidence facts; it does not infer unavailable values
or replace the route's authoritative source. Snapshot headlines use the same metric formatter as the
visible cards, and auto-resolution values retain ratio semantics so displayed percentage claims can
be checked at the same rounded precision the operator sees.

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
output composition, the seven-day trend, model attribution, and invocation records are derived only
from the metering projection. When price attribution is not connected, the route states that boundary
and doesn't estimate spend, budgets, per-call prices, or invoice amounts from token volume. Detailed
workload, mode, day, and month rollups remain available in a secondary disclosure so the primary view
stays scannable without hiding evidence.

## Loading presentation

Every route, panel, and bounded content region renders a skeleton from its first loading frame.
The shared skeleton replaces spinner-only and text-only waits, while a route can provide a shape
that preserves its final layout dimensions. Dashboard uses a posture block followed by metric,
distribution, attention, and vertical placeholders so loading does not collapse the report. One
screen-reader status announces loading; decorative blocks stay hidden. Shimmer stops under reduced
motion while the static skeleton remains visible.
The shared fallback uses heading, summary-card, and body-panel placeholders; an owned route shape
replaces that fallback only when it preserves a more accurate final layout.

The Vite development server passes CSS hot updates through Vite's race-safe file reader before
transforming them. This prevents a temporary empty snapshot from replacing the complete stylesheet
when an editor truncates and rewrites a large CSS file. The guard applies only during development;
production CSS bundling is unchanged.

## Localization boundary

The SPA resolves display locale from the operator preference. Reusable strings come from the main
English-source catalog or a complete route-local English/Korean pair with mandatory English
fallback. Static key coverage, catalog parity, route fallback tests, and the console suite prevent
untranslated display text from returning. Grounding trace labels and manifest/reference count
details use the same catalog rather than embedding English in reconstructed evidence metadata.

Localization changes presentation labels only. Machine values, workflow ids, serialized records,
provider payloads, and validation results remain unchanged.

## Durable request replay

A completed request is replayed only when principal, conversation, idempotency key, and request
content match. The stored terminal assistant payload is returned without repeating evidence
retrieval, narration, or post-turn review. Changed content or another conversation under the same
key is a conflict. JSON, SSE, and cross-transport retries share this terminal payload.

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
browse answer stay in their own prompt module, separate from general prompt assembly.
Agent answers keep Bragi as narrator while displaying the verified specialist as response owner.
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

Incident titles are also server-owned evidence. The read projection prefers recorded title,
summary, or rule fields, then uses bounded signal and resource correlation keys; it treats empty,
`None`, and `null` correlation markers as absent. The browser never invents an incident subject.

The selected Incident detail leads with one operator-readable current situation derived only from
the lifecycle summary and its loaded audit history. It separates lifecycle state, response
decision, change authority, and operator attention instead of presenting raw `pending`, `unknown`,
and `shadow` values as one status. Notification-delivery escalation takes precedence for an active
incident and names the required follow-up. Audit and technical activity remain available when
records exist. Root-cause analysis and its dossier become links only after an `rca.*` record exists;
otherwise the rows state that no evidence-backed hypothesis has been recorded. The RCA route also
hides its generic audit fallback response when no hypothesis exists, so `incident.members` is never
presented as a response plan or cause.
The Trace route leads with an interpretation summary that separates notification escalation,
response-decision evidence, RCA evidence, and named pipeline stages before showing the raw ordered
table. Generic correlated activity remains technical history, not a cause claim.


Operational evidence remains one of `matched`, `summary`, `ambiguous`, `none`, or `unavailable`.
For a collection summary request, `summary` renders the bounded matching set immediately without
requiring a single incident selection. Model prose cannot change the selected incident, search
scope, supported cause, collection membership, or absence claim. A source with
`availability=unavailable` never reports `reachable=true`; unconfigured or unprobed sources use
`reachable=null`.
On the Incidents route, a prompt that references the one selected incident by title, correlation
id, or a phrase such as "this incident" uses that selection as a lookup hint. The server rechecks
the incident id and correlation id against the authorized read model before answering. Exact
selected-incident evidence takes precedence over an inventory tool matched only from natural-language
keywords. The coordinator doesn't start unrelated inventory, agent, or public-web branches for
that turn; an explicit canonical tool command such as `query_inventory` keeps tool authority.
Generic recency words such as `latest`, `recent`, or `최신` do not create incident authority by
themselves. Operational lookup also requires explicit incident, issue, outage, failure, problem, or
cause semantics. A public software version or release question therefore remains eligible for the
bounded public-web path instead of producing a deterministic "no matching incident" answer.
Current-screen data scope takes precedence over inventory, incident, agent, and web enrichment.
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
When no citation-grounded RCA exists, deterministic verification may quote a recorded failure or
escalation reason from that audit evidence, but labels it as an observation rather than a complete
root-cause conclusion.

Each manifest route has one owner. The SPA strips query and fragment components, matches exact
paths or descendants on a path-segment boundary, and selects the longest owner. Similar prefixes do
not inherit ownership. A panel remains `unknown` when any owned route is absent from the manifest;
only explicitly source-independent panels omit source status.

The production read API loads and validates the operational ownership map before registering
`GET /stewardship`. The console projects that source read-only. Its Handover form can submit
structured person or group assignments to the separate ingestion boundary, but it cannot apply the
map or hold Git credentials. Draft PR creation and signed merge processing remain on the
ingestion/GitOps boundary, and the returned draft includes the persisted idempotent PR receipt.
The browser renders a receipt URL as a link only when it is an absolute HTTPS URL without embedded
credentials; otherwise it displays the PR reference as non-clickable text.
Content upload keeps the API bearer token only for same-origin ingestion proxy targets. A
cross-origin direct-upload target receives the content headers but never the read API credential.

## Progressive parallel conversations

Command Deck and pull-direction ChatOps use one channel-neutral progressive conversation model.
After deterministic scope and authority routing, the coordinator can start eligible independent
read branches concurrently. A branch is an immutable evidence operation, not a nested narrator
session and not a direct agent call. Bragi remains the presentation translator. The accountable
tool or agent owns the branch evidence, while deterministic verification owns every confirmed
answer segment.

Each branch event carries these bounded fields:

| Field | Contract |
|-------|----------|
| `branch_id` | Stable within the request and derived from the request id plus canonical branch kind. |
| `branch_kind` | One allowlisted read source such as `tool`, `operational`, `agent`, or `public_web`. |
| `parent_branch_id` | Optional dependency reference; independent top-level branches use `null`. |
| `status` | Monotonic `pending`, `running`, then one of `completed`, `unavailable`, `failed`, `timed_out`, or `cancelled`. |
| `summary` | Bounded, redacted operator-facing progress or terminal summary. It is not evidence authority. |
| `started_at`, `completed_at`, `duration_ms` | Optional observed timing. Completed time never precedes started time. |
| `evidence_refs` | Bounded canonical references emitted only at a terminal branch state. |

The server emits branch lifecycle frames in request `seq` order. Branch completion order can vary,
but the join always merges immutable results in canonical branch-kind order. One unavailable,
failed, or timed-out independent read does not erase successful sibling evidence. A conflict in
authoritative facts is different: the join preserves both evidence sets, marks the answer
unverified, and does not let Bragi choose a winner. Shared mutable context is never written by
concurrent branches.

The implemented first wave uses one bounded task group for eligible tool, operational, explicitly
selected agent, read-investigation agent, and deterministic public-web reads. Agent or web work
whose eligibility depends on an earlier authority result runs in a bounded follow-up wave. This
keeps independent I/O overlapped without speculatively calling an agent or external web provider
that the established authority order would suppress. JSON and SSE chat use the same merge helper.

Draft `token` frames remain provisional narration. A `confirmed` frame contains only a complete
segment rendered from evidence that has already passed its deterministic verifier. It includes a
monotonic segment index, answer revision, evidence references, and replacement range when a later
verified result corrects an earlier segment. A confirmed segment never cites a running branch.
The terminal `done` frame remains canonical and is the only answer persisted to conversation
history. Clients label an interrupted stream without a terminal frame as partial and never promote
draft text to confirmed content.

The Web reducer validates branch kind, monotonic status, timing, evidence-reference, and text bounds
before rendering. It shows compact branch summaries and keeps observed execution details collapsed
by default. It applies a confirmed segment only after queued token paint and any correction revision
have drained. Token and confirmed frames must match the current canonical revision. A frame from a
superseded or unannounced revision consumes its sequence position but cannot append text, replace
canonical content, invoke confirmation callbacks, or increment confirmation metrics. Confirmed
revisions also advance strictly, so a duplicate at the current revision is a stale replay. A missing
`seq` value between frames makes the turn partial even if a later `done`
arrives, so an incomplete stream cannot inherit terminal verification.

Web, Teams, and Slack consume the same ordered event reduction:

- **Web** keeps compact branch summaries beside the in-progress answer. Details and canonical
	redacted command or output evidence are collapsed until the operator expands them.
- **Teams and Slack** post one response in the originating thread and apply monotonic edits. The
	final edit contains the canonical verified answer and a bounded folded branch summary.
- **Capability fallback** sends one complete terminal response when a vendor cannot edit. It does
	not call precomputed text chunks streaming and does not change answer authority.

Stream close, operator interruption, or request deadline cancels and awaits every child branch.
Cancellation remains authoritative when its optional progress observer fails; the observer error is
logged without converting a cancelled branch into a failed stream.
Per-branch deadlines, queue capacity, branch count, event size, activity count, text bytes, and
vendor payloads stay bounded. Command and output evidence requires `redacted=true`; branch summaries
never expose credentials, tenant identifiers, customer resource identifiers, or raw untrusted web
content. Durable replay stores the canonical terminal answer and revision state. It never re-runs a
completed read or duplicates the provider message.

Progress metrics retain aggregate counts and latency only: time to first progress and confirmed
content, branch kind/outcome/duration, correction, truncation, terminal completion, replay, queue
saturation, sequence gap, suppressed branch retry, and ambiguous channel update. They retain no
prompt, answer, branch id, channel id, principal id, or resource identifier. Failed and timed-out
read branches are not retried inside the turn; the operator can start a new turn with fresh scope.
Progress, branch outcome, and truncation metrics are recorded only after the bounded stream queue
accepts the event. A cancellation-only lifecycle frame is not counted as first evidence progress.
An idempotent terminal replay contributes its observed time-to-first-confirmed latency and replay
count while still skipping evidence retrieval, narration, and post-turn review.
The browser counts sequence gaps and partial terminals locally because the server cannot observe
missing client frames.

## Stream recovery and authentication

Authenticated live, agent, and provisioning SSE readers cancel after 45 seconds without bytes,
including keepalive comments, then use bounded reconnect. Provisioning also cancels its reader when
event delivery fails. Agent-stream `401` waits for full-screen login recovery; `403` reconnects so a
new App Role can take effect without a page reload.

Command Deck investigation activity can include optional observed execution evidence. The server
removes credentials and sensitive identifiers before emission and sets `redacted=true`; the browser
drops command evidence without that attestation. An accepted activity can show a bounded command,
tool label, exit code, authority, and completion state. Output logs and timestamps stay collapsed by
default. Intermediate progress detail and milestones use an opaque resource placeholder rather
than the parsed resource name. The command is limited to 16 KiB and the output preview to 64 KiB;
truncation is explicit. Activity and retrieval labels are limited to 512 characters, detail and
milestone text to 16 KiB, and contradictory completed/total progress is rejected.
The browser can copy the displayed command but can't run or retry it. This evidence remains a
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

When a turn carries validated inline image attachments, the streaming route also emits read-only
`vision_analyzing` before the narrator composes and `vision_grounded` before the answer, each with
image source previews (name, media type, size) but never the base64 payload. The turn escalates to
a vision-capable narrator, and the preparing-answer trace renders these stages the same way it
renders web-search grounding.

The interactive Live route pauses its SSE reader while the tab is hidden. An operator-enabled
browser notification consumer is the bounded exception: it keeps the authenticated live reader open
in the background, retries authentication failures with the existing capped backoff, and stops as
soon as notification permission or the principal-scoped opt-in is removed. It emits only human
approval, denial, and failure outcomes from non-replay frames. A shared browser ledger suppresses
the same event tag for five minutes across tabs and limits system notification delivery to five per
minute without removing any audit or Incident evidence.

The agent stream receives health-derived `agent.runtime-state` heartbeats through the same shared
stage transport in local and deployed profiles. A heartbeat establishes current runtime observation
for a live agent but isn't classified as work. Missing or malformed health frames never promote a
declared subscriber binding into an observed state. Each read API replica uses an instance-scoped
consumer group so every connected console receives the complete heartbeat set. The deployed
Pantheon also publishes handler `started`, `completed`, and `failed` transitions through this
transport. A consumer that gives up or halts is removed from health-derived heartbeats while its
siblings continue; the terminal agent/topic remains in runtime health. Saga or Vidar failure forces
sticky shadow. These transitions are runtime activity, not durable audit evidence.

The Command Deck rejects a complete or pending SSE frame above 256 KiB before accumulating `data:`
lines or parsing JSON, then uses the deterministic interrupted-stream fallback. Correlation-filtered
action progress treats a terminal audit frame as completion, reports the 120-second deadline as a
timeout, and propagates other authentication or transport failures. Investigation rows advance
from pending to running to one terminal state; stale backward frames and terminal replacements are
ignored so a completed, failed, or unavailable operation cannot return to a spinner.

Before opening console data, bootstrap verifies the principal through authenticated
`GET /iam/self`. Transport failure keeps data closed and offers access-check retry and sign-in. It
does not start an automatic redirect because an unreachable read API would cause a redirect loop.

## Architecture-map resilience

The Architecture route keeps only scope selection in the compact panel that floats over the map's
upper-right corner. It omits inventory counts, explanatory copy, and layer filters. A truncated
graph uses one short status badge. The resource-color legend is drawn directly on the world floor
beside the subscription boundary,
not in a floating or bottom panel. Camera fitting reserves floor space for it. Resource type names
are written directly on that floor without a fixed legend box, title, or color swatches. The names
move with pan and scale with map zoom inside bounded readable sizes.
Resource glyphs use the Microsoft Cloud Adoption Framework
[Azure resource abbreviations](https://learn.microsoft.com/azure/cloud-adoption-framework/ready/azure-best-practices/resource-abbreviations).
Every known canonical type has an explicit lowercase abbreviation. Abstract types without a
one-to-one CAF row use a documented stable extension instead of a generated initialism.
The relationship legend remains the compact canvas control. The default isometric map starts with
Reflections and Connections enabled. It shows containment as subtle dashed links,
shows attachment and dependency links with their directional styles, and renders each resource
shape; top and front views are optional. Simple projections size every resource-group panel,
including a single selected scope, from its observed child count and pack those panels into a
balanced world. Focused service and resource-group views fit that repacked content instead of the
full subscription frame. A resource node never renders
smaller than the standard Event Grid topic block. The world and canvas grow with inventory while
authored nested layouts keep their supplied geometry. The map uses the full workspace width and
places inspection details below it. Narrow viewports preserve node size and use map panning instead
of shrinking boxes into unreadable marks. Selection updates the canonical deep link without
reloading inventory and exposes directional relationships before technical identifiers. Selection
preserves every common resource coordinate while auxiliary neighbors appear. It does not dim
unrelated resources; selection uses the chosen outline and inspection details only. Every resource
selection preserves the current camera scale and position, including virtual machines. Zoom, fit,
pan, and camera-view controls remain explicit operator actions.

The factual counts and inspection index continue to use the complete authoritative inventory. The
isometric overview applies a presentation-only projection that keeps network interfaces and managed
disks visible while collapsing diagnostics, certificates, and provider helper resources.
Each visible owner shows a `+N` badge for its collapsed neighbors. Selecting a resource reveals its
direct auxiliary children and semantic neighbors without requesting or inventing new inventory.
The overview packs only visible resources, orders children by layer and type, reserves up to two
satellite slots beside a collapsed owner, and places larger resource-group panels first in wide
rows. Hidden auxiliaries therefore do not create empty grid holes or inflate the world.
Virtual networks and subnets render as low floor lanes so compute, data, and gateway nodes remain
readable above the network plane; floor lanes do not render reflections. Azure inventory promotes
only subnets observed inside a VNet payload into `network.subnet` records and emits the observed
VNet-to-subnet containment edge. The console assigns a resource to a subnet only when registered
`attached_to` links reach one unique subnet within the bounded resource-to-interface-to-subnet
chain, or a disk reaches it through the bounded disk-to-workload-to-interface-to-subnet chain.
Missing or ambiguous membership leaves the resource on the neutral resource-group floor;
names and provider identifiers never become topology evidence.

The isometric renderer draws a VNet as an outer floor and its subnets as inset floor planes sized
from their visible members. Evidence-derived membership rails and direct `attached_to` links stay
on the floor, while `depends_on` arrows remain above resource tops. Plane names follow the world
axis without a floating label card. Selecting a plane uses the same resource inspector and the
smallest containing plane remains the pointer target. A focused service or resource-group view
uses a wide packing target so three network floors share one row when they fit. It also uses a
smaller desktop legend reserve and canvas height than the complete inventory view. Narrow
viewports keep the same node size, cap the canvas at 520 px, and expose the wider floor through
panning.

Within a subnet, visible path participants are grouped by their observed `attached_to` connected
component, then arranged from network edge to storage: public IP and network security resources,
network interfaces, compute and service resources, then disks and data resources. Multiple
workload paths stay contiguous instead of interleaving by type or name. This is a layout order, not
an inferred traffic direction. Every component gets its own depth-oriented lane: public IP starts
nearest the camera, and security, interface, workload, and storage stages recede in order. The
renderer replaces overlapping intra-subnet edges with one shared floor spine and short stage
branches; only cross-plane attachments retain a direct route. Workloads render larger than
supporting network resources. Path resources use glyphs by default, workloads retain their primary
label, and selecting any resource restores its full name and type.
Perspective scales projected points within bounded depth limits so near resources read larger than
far resources while picking and containment use the same projection. Zoom supports deep inspection
up to 512x scale, zooms around the pointer, and lets content-driven worlds grow without a fixed
canvas-height ceiling. The default isometric camera uses a low oblique angle so path lanes read
left-to-right while depth recedes, and Fit places the world slightly below center to reserve visual
depth above it. Fit remains the explicit way to restore the complete frame.
Left-button drag pans the projected world. Middle-button drag orbits the camera horizontally around
the world center with normalized continuous yaw; vertical movement doesn't change pitch. The right
button keeps its browser behavior. Orbit input uses the same animation-frame coalescing and keeps
floors, paths, and reflections visible while labels are deferred.

Labels avoid collisions, fit long names, and pair each resource name with its plain resource type.
The compact acronym on the block is a secondary cue, not the only way to identify the resource.
Labels scale from 13 px to 20 px as the operator zooms; the selected label may reach 22 px. Zoom
steps are reciprocal, colors follow the console theme, and a keyboard-accessible resource and
relationship index is equivalent to the filtered canvas. Pointer targets are at least 44 px and
include containment boundaries. The selected label is the final canvas overlay so no block glyph,
relationship, or neighboring label can cover it. Truncated snapshots show an explicit
partial-inventory notice.
The canvas renders containment as subdued dashed center-to-center edges. Semantic relationships use
directional node-to-node arrows above the connected block tops and do not connect resource-group
regions as operational endpoints. Drag input coalesces to one draw per animation frame, keeps
reflections continuous, and omits labels only while the pointer is moving; pointer release restores
the labels.
The local projection shows only registered relationship types whose selected endpoint ids and
resource types agree. It drops malformed or over-limit vendor relationships, marks the snapshot
truncated, and keeps the last complete resource graph rather than rendering an untrusted edge.

A subscription-scoped cached snapshot renders immediately. Expired or change-invalidated snapshots
are marked stale while a background refresh runs. The browser polls only until the read API
atomically promotes the completed refresh, never upgrades the server freshness verdict, and retries
transient failures with bounded 2-to-30-second backoff while the stale graph remains usable.

## Verification

- Catalog parity and route-local fallback tests cover localization.
- Replay tests cover JSON, SSE, and cross-transport idempotency.
- Provenance tests cover unavailable, unknown, malformed, and route-owner states.
- Stream tests cover inactivity, authentication classification, frame limits, and action timeout.
- Architecture tests cover layout, selection, accessibility, cache freshness, and bounded polling.
